#!/usr/bin/env python3
"""
Audiobook Organizer (safe rewrite)

Watches an inbox folder for InAudible output (one folder per book: .m4b plus
.nfo/.cue/.jpg), files each book under <volume>/<Author>/<Title>/, records it
in SQLite, and regenerates the HTML catalog from the database.

Safety rules this version enforces:
  * Polling, not event callbacks. A folder is only touched after its contents
    have stopped changing for `settle_seconds`.
  * Nothing is deleted until its copy is verified at the destination.
  * The watch folder itself is never removed; the library can never sit
    inside the watch folder (or vice versa).
  * Companion files travel only with the single audio file in THEIR folder.
  * Folders it does not understand (several audio files) are left untouched.
  * Only one copy of the program can run at a time.
"""

import os
import re
import sys
import time
import shutil
import socket
import logging
from pathlib import Path
from typing import Optional, Tuple, List, Dict

try:
    import yaml
    from mutagen import File as MutagenFile
    from mutagen.mp4 import MP4
except ImportError as e:
    print(f"Missing required package: {e}")
    print("\nPlease install required packages:")
    print("  pip install -r requirements.txt")
    sys.exit(1)

import database
from html_builder import get_all_books, build_html

COMPANION_EXTENSIONS = {'.nfo', '.cue', '.jpg', '.jpeg', '.png', '.txt'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
IN_PROGRESS_SUFFIXES = ('.tmp', '.part', '.partial', '.crdownload')
JUNK_NAMES = {'desktop.ini', 'thumbs.db', '.ds_store'}


# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
class Config:
    """Configuration manager for the audiobook organizer"""

    def __init__(self, config_file='config.yaml'):
        self.config_file = config_file
        self.config = self.load_config()

    def load_config(self):
        if not os.path.exists(self.config_file):
            print(f"❌ Config file not found: {self.config_file}")
            print("Please copy config.yaml.example to config.yaml and update paths")
            sys.exit(1)
        with open(self.config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        for field in ['watch_directory', 'drives']:
            if field not in config:
                print(f"❌ Missing required field in config: {field}")
                sys.exit(1)
        return config

    def _setting(self, key, default):
        return self.config.get('settings', {}).get(key, default)

    @property
    def watch_directory(self):
        return os.path.expanduser(self.config['watch_directory'])

    @property
    def drive_a_l(self):
        return os.path.expanduser(self.config['drives']['a_l'])

    @property
    def drive_m_z(self):
        return os.path.expanduser(self.config['drives']['m_z'])

    @property
    def on_duplicate(self):
        return self._setting('on_duplicate', 'skip')

    @property
    def poll_seconds(self):
        return float(self._setting('poll_seconds', 10))

    @property
    def settle_seconds(self):
        return float(self._setting('settle_seconds', 30))

    @property
    def allow_filename_fallback(self):
        return bool(self._setting('allow_filename_fallback', False))

    @property
    def audio_extensions(self):
        extensions = self._setting(
            'audio_extensions', ['.m4b', '.m4a', '.mp3', '.mp4', '.aac', '.flac', '.ogg'])
        return set(ext.lower() for ext in extensions)

    @property
    def log_file(self):
        return self.config.get('logging', {}).get('log_file', 'audiobook_organizer.log')

    @property
    def log_level(self):
        return self.config.get('logging', {}).get('log_level', 'INFO')

    @property
    def debug_metadata(self):
        return self.config.get('logging', {}).get('debug_metadata', False)

    @property
    def db_file(self):
        path = os.path.expanduser(self._setting('db_file', 'library.db'))
        if os.path.isdir(path) or path.endswith(('/', '\\')):
            return os.path.join(path, 'library.db')
        return path

    @property
    def html_file(self):
        path = os.path.expanduser(self._setting('index_file', 'library_vue.html'))
        if os.path.isdir(path) or path.endswith(('/', '\\')):
            return os.path.join(path, 'library_vue.html')
        if os.path.splitext(path)[1].lower() == '.html':
            return path
        return os.path.join(os.path.dirname(os.path.abspath(path)), 'library_vue.html')

    @property
    def instance_port(self):
        return int(self._setting('instance_port', 47653))


def setup_logging(config: Config) -> logging.Logger:
    logger = logging.getLogger('audiobook_organizer')
    if logger.handlers:
        return logger
    logger.setLevel(getattr(logging, config.log_level))

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    logger.addHandler(console_handler)

    if config.log_file != 'console':
        file_handler = logging.FileHandler(config.log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
    return logger


# ----------------------------------------------------------------------------
# Names and metadata
# ----------------------------------------------------------------------------
def sanitize_filename(name: str) -> str:
    """Strip characters Windows forbids (matches the folder names already in the library)."""
    if not name:
        return ""
    name = re.sub(r'[\\/*?:"<>|]', '', name)
    name = re.sub(r'\s+', ' ', name).strip(' .')
    return name[:150].rstrip(' .')


def get_metadata(file_path: str, debug: bool = False) -> Tuple[Optional[str], Optional[str], bool]:
    """Extract (author, title, needs_tagging). needs_tagging=True means we had to guess
    from the filename because the tags were incomplete."""
    needs_tagging = False
    author = None
    book_title = None

    try:
        audio = MutagenFile(file_path)

        if audio is not None:
            if isinstance(audio, MP4):
                for tag in ['aART', '\xa9ART', '©ART']:
                    if tag in audio:
                        author = str(audio[tag][0] if isinstance(audio[tag], list) else audio[tag])
                        break
                for tag in ['\xa9alb', '©alb', '\xa9nam', '©nam']:
                    if tag in audio:
                        book_title = str(audio[tag][0] if isinstance(audio[tag], list) else audio[tag])
                        break
            elif hasattr(audio, 'tags') and audio.tags:
                for tag in ['albumartist', 'artist', 'ALBUMARTIST', 'ARTIST', 'TPE2', 'TPE1']:
                    if tag in audio.tags:
                        author = str(audio.tags[tag][0] if isinstance(audio.tags[tag], list) else audio.tags[tag])
                        break
                for tag in ['album', 'ALBUM', 'TALB']:
                    if tag in audio.tags:
                        book_title = str(audio.tags[tag][0] if isinstance(audio.tags[tag], list) else audio.tags[tag])
                        break

        if author:
            author = author.strip()
        if book_title:
            book_title = book_title.strip()

        if not author or not book_title:
            clean_name = Path(file_path).stem.replace('_', ' ')
            if " - " in clean_name:
                parts = clean_name.split(" - ", 1)
                author = author or parts[0].strip()
                book_title = book_title or parts[1].strip()
            elif "-" in clean_name:
                parts = clean_name.split("-", 1)
                author = author or parts[0].strip()
                book_title = book_title or parts[1].strip()
            else:
                book_title = book_title or clean_name.strip()
                author = author or "Unknown Author"
            needs_tagging = True

        return author, book_title, needs_tagging

    except Exception as e:
        if debug:
            print(f"Error reading metadata: {e}")
        return None, None, False


def get_target_drive(author_name: str, config: Config) -> Optional[str]:
    """A-L goes to drive 1, everything else to drive 2 (digits/symbols go to drive 1)."""
    if not author_name:
        return None
    first_letter = author_name[0].upper()
    if 'A' <= first_letter <= 'L':
        return config.drive_a_l
    if 'M' <= first_letter <= 'Z':
        return config.drive_m_z
    return config.drive_a_l


# ----------------------------------------------------------------------------
# File helpers
# ----------------------------------------------------------------------------
def is_in_progress(name: str) -> bool:
    return name.lower().endswith(IN_PROGRESS_SUFFIXES)


def is_temp_or_junk(name: str) -> bool:
    low = name.lower()
    return (is_in_progress(name) or low.endswith('.ff.txt') or low in JUNK_NAMES
            or re.match(r'^temp[\W_\d]', low) is not None)


def transfer(src: str, dst: str, replace: bool, logger: logging.Logger) -> str:
    """Move src to dst without ever deleting src until dst is verified.
    Returns 'moved', 'skipped' or 'failed'."""
    if os.path.exists(dst) and not replace:
        logger.warning(f"   ⚠️ Already exists, leaving source in place: {dst}")
        return 'skipped'
    tmp = dst + '.partial'
    try:
        try:
            os.replace(src, dst)          # same volume: instant and atomic
            return 'moved'
        except OSError:
            pass                           # different volume: copy, verify, then delete
        shutil.copy2(src, tmp)
        if os.path.getsize(tmp) != os.path.getsize(src):
            raise IOError("size mismatch after copy")
        os.replace(tmp, dst)
        os.remove(src)
        return 'moved'
    except Exception as e:
        logger.error(f"   ❌ Could not move {os.path.basename(src)}: {e} (source left in place)")
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return 'failed'


def snapshot(path: str) -> tuple:
    """A comparable fingerprint of a file or folder tree: (relpath, size, mtime) per file."""
    items = []
    try:
        if os.path.isfile(path):
            st = os.stat(path)
            return ((os.path.basename(path), st.st_size, int(st.st_mtime)),)
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                full = os.path.join(dirpath, f)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                items.append((os.path.relpath(full, path), st.st_size, int(st.st_mtime)))
    except OSError:
        pass
    return tuple(sorted(items))


def snapshot_in_progress(snap: tuple) -> bool:
    return any(is_in_progress(os.path.basename(item[0])) for item in snap)


def is_within(child: str, parent: str) -> bool:
    child = os.path.normcase(os.path.abspath(child))
    parent = os.path.normcase(os.path.abspath(parent))
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:      # different drives on Windows
        return False


# ----------------------------------------------------------------------------
# Filing a book
# ----------------------------------------------------------------------------
def file_audiobook(audio_path: str, companions: List[str], config: Config,
                   logger: logging.Logger) -> bool:
    name = os.path.basename(audio_path)
    logger.info(f"📚 Processing: {name}")

    try:
        with open(audio_path, 'rb') as fh:     # fails if another program still holds it
            fh.read(1)
    except OSError as e:
        logger.warning(f"   ⏳ File not readable yet ({e}); will retry if it changes")
        return False

    author, book_title, needs_tagging = get_metadata(audio_path, debug=config.debug_metadata)
    if not author or not book_title:
        logger.warning("   ❌ No usable metadata; leaving in place")
        return False
    if needs_tagging and not config.allow_filename_fallback:
        logger.warning(f"   ❌ Tags incomplete (Author: {author} | Book: {book_title}); "
                       "leaving in place. Set allow_filename_fallback: true to guess from filename.")
        return False

    safe_author = sanitize_filename(author)
    safe_book = sanitize_filename(book_title)
    if not safe_author or not safe_book:
        logger.warning("   ❌ Author or title empty after cleaning; leaving in place")
        return False

    drive = get_target_drive(safe_author, config)
    if not drive or not os.path.isdir(drive):
        logger.error(f"   ❌ Target volume not available: {drive}")
        return False

    logger.info(f"   📖 {safe_author} / {safe_book}")
    dest_dir = os.path.join(drive, safe_author, safe_book)
    try:
        os.makedirs(dest_dir, exist_ok=True)
    except OSError as e:
        logger.error(f"   ❌ Cannot create {dest_dir}: {e}")
        return False

    replace = (config.on_duplicate == 'replace')
    dest_file = os.path.join(dest_dir, name)
    if transfer(audio_path, dest_file, replace, logger) != 'moved':
        return False                    # audio did not move: touch nothing else

    for comp in companions:
        if transfer(comp, os.path.join(dest_dir, os.path.basename(comp)), replace, logger) == 'moved':
            logger.info(f"   📎 {os.path.basename(comp)}")

    cover = ""
    for f in sorted(os.listdir(dest_dir)):
        if Path(f).suffix.lower() in IMAGE_EXTENSIONS:
            cover = os.path.join(dest_dir, f)
            break

    database.insert_book(config.db_file, author, book_title, dest_dir, dest_file, cover)
    logger.info("   ✅ Filed and recorded in database")
    return True


def prune_empty_folders(entry_path: str, watch_root: str, logger: logging.Logger):
    """Remove folders under the entry that are now empty (or hold only junk). Never the watch root."""
    dirs = [d for d, _, _ in os.walk(entry_path)]
    for d in reversed(dirs):
        if os.path.normcase(os.path.abspath(d)) == os.path.normcase(os.path.abspath(watch_root)):
            continue
        try:
            names = os.listdir(d)
            if all(is_temp_or_junk(n) and not is_in_progress(n) and os.path.isfile(os.path.join(d, n))
                   for n in names):
                for n in names:
                    os.remove(os.path.join(d, n))
                os.rmdir(d)
                logger.info(f"   🧹 Removed empty folder: {os.path.basename(d)}")
        except OSError as e:
            logger.debug(f"Could not remove {d}: {e}")


def process_entry(path: str, config: Config, logger: logging.Logger) -> int:
    """Process one top-level item in the watch folder. Returns number of books filed."""
    audio_ext = config.audio_extensions
    filed = 0

    if os.path.isfile(path):
        name = os.path.basename(path)
        if Path(name).suffix.lower() in audio_ext and not is_temp_or_junk(name):
            filed += 1 if file_audiobook(path, [], config, logger) else 0
        return filed

    units = [(d, list(files)) for d, _, files in os.walk(path)]
    for dirpath, filenames in units:
        audio = [f for f in filenames
                 if Path(f).suffix.lower() in audio_ext and not is_temp_or_junk(f)]
        if not audio:
            continue
        if len(audio) > 1:
            logger.warning(f"⚠️ {len(audio)} audio files in '{os.path.basename(dirpath)}'; "
                           "leaving the whole folder untouched")
            continue
        companions = [os.path.join(dirpath, f) for f in filenames
                      if Path(f).suffix.lower() in COMPANION_EXTENSIONS and not is_temp_or_junk(f)]
        if file_audiobook(os.path.join(dirpath, audio[0]), companions, config, logger):
            filed += 1

    if filed:
        prune_empty_folders(path, config.watch_directory, logger)
    return filed


# ----------------------------------------------------------------------------
# Watching (polling)
# ----------------------------------------------------------------------------
def run_pass(config: Config, logger: logging.Logger, state: Dict[str, dict],
             once: bool = False) -> int:
    """One sweep of the watch folder. An item is processed only after its contents have
    been identical for `settle_seconds` (or immediately in --once mode)."""
    root = config.watch_directory
    try:
        names = sorted(os.listdir(root))
    except OSError as e:
        logger.warning(f"⚠️ Cannot read watch folder: {e}")
        return 0

    now = time.time()
    seen = set()
    filed_total = 0

    for name in names:
        if name.startswith(('.', '_', '$')) or name.lower() in JUNK_NAMES:
            continue
        seen.add(name)
        path = os.path.join(root, name)
        snap = snapshot(path)

        st = state.get(name)
        if st is None or st['snap'] != snap:
            st = state[name] = {'snap': snap, 'since': now, 'handled': False}
        if st['handled']:
            continue
        if not once and now - st['since'] < config.settle_seconds:
            continue
        if snapshot_in_progress(snap):
            continue

        filed_total += process_entry(path, config, logger)
        # Remember what is left so unchanged leftovers are not retried (or re-logged) forever.
        state[name] = {'snap': snapshot(path), 'since': now, 'handled': True}

    for gone in set(state) - seen:
        del state[gone]
    return filed_total


def rebuild_html(config: Config, logger: logging.Logger):
    try:
        books = get_all_books(config.db_file)
        if books:
            build_html(books, config.html_file)
    except Exception as e:
        logger.error(f"❌ Could not rebuild HTML catalog: {e}")


def acquire_single_instance(port: int):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', port))
    except OSError:
        print("❌ Another copy of the organizer is already running. Close it first.")
        sys.exit(1)
    return s


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='Audiobook Organizer - file audiobooks by Author/Book Title')
    parser.add_argument('--config', default='config.yaml', help='Path to config file')
    parser.add_argument('--once', action='store_true',
                        help='Process what is in the watch folder now and exit')
    args = parser.parse_args()

    config = Config(args.config)
    logger = setup_logging(config)
    _lock = acquire_single_instance(config.instance_port)

    print("=" * 70)
    print("🎧 AUDIOBOOK ORGANIZER")
    print("=" * 70)
    print(f"📂 Watching:   {config.watch_directory}")
    print(f"📚 A-L →       {config.drive_a_l}")
    print(f"📚 M-Z →       {config.drive_m_z}")
    print(f"🔄 Duplicates: {config.on_duplicate}")
    print(f"🗄️  Database:   {os.path.abspath(config.db_file)}")
    print(f"🌐 Catalog:    {os.path.abspath(config.html_file)}")

    if not os.path.isdir(config.watch_directory):
        logger.error(f"❌ Watch folder doesn't exist: {config.watch_directory}")
        return
    for label, drive in (('A-L', config.drive_a_l), ('M-Z', config.drive_m_z)):
        if is_within(drive, config.watch_directory) or is_within(config.watch_directory, drive):
            logger.error(f"❌ The {label} library folder and the watch folder overlap. "
                         "Refusing to run; they must be separate, non-nested folders.")
            return

    database.init_db(config.db_file)
    state: Dict[str, dict] = {}

    if args.once:
        filed = run_pass(config, logger, state, once=True)
        if filed:
            rebuild_html(config, logger)
        logger.info(f"✅ One-time pass complete: {filed} book(s) filed")
        return

    rebuild_html(config, logger)
    print(f"\nPress Ctrl+C to stop. A folder is filed after it has been unchanged "
          f"for {config.settle_seconds:.0f}s.\n")
    logger.info("👀 Watching...")
    try:
        while True:
            filed = run_pass(config, logger, state)
            if filed:
                rebuild_html(config, logger)
            time.sleep(config.poll_seconds)
    except KeyboardInterrupt:
        logger.info("🛑 Stopped")


if __name__ == "__main__":
    main()
