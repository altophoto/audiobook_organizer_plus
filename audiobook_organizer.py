#!/usr/bin/env python3
"""
Audiobook Organizer
Automatically organizes audiobook files into Author/Book Title folder structure
based on metadata tags.

Now updated for Phase 1: SQLite Integration.
"""

import os
import shutil
import time
import re
import sys
import logging
from pathlib import Path
from typing import Optional, Tuple

# Import our new database module (ensure database.py is in the same folder!)
import database

try:
    import yaml
    from mutagen import File as MutagenFile
    from mutagen.mp4 import MP4
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError as e:
    print(f"Missing required package: {e}")
    print("\nPlease install required packages:")
    print("  pip install -r requirements.txt")
    sys.exit(1)


class Config:
    def __init__(self, config_file='config.yaml'):
        self.config_file = config_file
        self.config = self.load_config()
        
    def load_config(self):
        if not os.path.exists(self.config_file):
            print(f"❌ Config file not found: {self.config_file}")
            sys.exit(1)
            
        with open(self.config_file, 'r') as f:
            config = yaml.safe_load(f)
            
        required = ['watch_directory', 'drives']
        for field in required:
            if field not in config:
                print(f"❌ Missing required field in config: {field}")
                sys.exit(1)
                
        return config
    
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
        return self.config.get('settings', {}).get('on_duplicate', 'replace')
    
    @property
    def check_interval(self):
        return self.config.get('settings', {}).get('check_interval', 2)
    
    @property
    def audio_extensions(self):
        extensions = self.config.get('settings', {}).get('audio_extensions', 
            ['.m4b', '.m4a', '.mp3', '.mp4', '.aac', '.flac', '.ogg'])
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
        # Allow defining database location, default to library.db in the working directory
        path = self.config.get('settings', {}).get('db_file', 'library.db')
        if os.path.isdir(path) or path.endswith('/') or path.endswith('\\'):
            return os.path.join(path, 'library.db')
        return path


def setup_logging(config: Config) -> logging.Logger:
    logger = logging.getLogger('audiobook_organizer')
    logger.setLevel(getattr(logging, config.log_level))
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    if config.log_file != 'console':
        file_handler = logging.FileHandler(config.log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    
    return logger


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip('. ')
    return name


def get_metadata(file_path: str, debug: bool = False) -> Tuple[Optional[str], Optional[str]]:
    try:
        audio = MutagenFile(file_path)
        if audio is None:
            return None, None
        
        author, book_title = None, None
        
        if isinstance(audio, MP4):
            for tag in ['aART', '\xa9ART', '©ART']:
                if tag in audio:
                    value = audio[tag]
                    author = str(value[0] if isinstance(value, list) else value)
                    break
            
            for tag in ['\xa9alb', '©alb']:
                if tag in audio:
                    value = audio[tag]
                    book_title = str(value[0] if isinstance(value, list) else value)
                    break
            
            if not book_title:
                for tag in ['\xa9nam', '©nam']:
                    if tag in audio:
                        value = audio[tag]
                        book_title = str(value[0] if isinstance(value, list) else value)
                        break
        else:
            if hasattr(audio, 'tags') and audio.tags:
                for tag_name in ['albumartist', 'artist', 'ALBUMARTIST', 'ARTIST', 'TPE2', 'TPE1']:
                    if tag_name in audio.tags:
                        author = str(audio.tags[tag_name][0] if isinstance(audio.tags[tag_name], list) else audio.tags[tag_name])
                        break
                
                for tag_name in ['album', 'ALBUM', 'TALB']:
                    if tag_name in audio.tags:
                        book_title = str(audio.tags[tag_name][0] if isinstance(audio.tags[tag_name], list) else audio.tags[tag_name])
                        break
        
        return author.strip() if author else None, book_title.strip() if book_title else None
        
    except Exception:
        return None, None


def get_target_drive(author_name: str, config: Config) -> Optional[str]:
    if not author_name:
        return None
    first_letter = author_name[0].upper()
    if 'A' <= first_letter <= 'L':
        return config.drive_a_l
    elif 'M' <= first_letter <= 'Z':
        return config.drive_m_z
    return config.drive_a_l


def organize_audiobook(file_path: str, config: Config, logger: logging.Logger) -> bool:
    logger.info(f"📚 Processing: {os.path.basename(file_path)}")
    
    if Path(file_path).suffix.lower() not in config.audio_extensions:
        return False
    
    author, book_title = get_metadata(file_path, debug=config.debug_metadata)
    
    if not author or not book_title:
        logger.warning(f"❌ Missing metadata - Author: {author}, Book: {book_title}")
        return False
        
    target_drive = get_target_drive(author, config)
    if not target_drive or not os.path.exists(target_drive):
        logger.error(f"❌ Target drive not mounted: {target_drive}")
        return False
    
    author_folder = os.path.join(target_drive, sanitize_filename(author))
    book_folder = os.path.join(author_folder, sanitize_filename(book_title))
    os.makedirs(book_folder, exist_ok=True)
    
    destination = os.path.join(book_folder, os.path.basename(file_path))
    source_dir = os.path.dirname(file_path)
    
    if os.path.exists(destination):
        if config.on_duplicate == 'replace':
            os.remove(destination)
        else:
            return False
            
    shutil.move(file_path, destination)
    
    # Track the cover path if we find an image
    cover_path = None
    companion_extensions = {'.nfo', '.cue', '.jpg', '.jpeg', '.png', '.txt'}
    
    for comp_file in os.listdir(source_dir):
        comp_path = os.path.join(source_dir, comp_file)
        if os.path.isfile(comp_path):
            comp_ext = Path(comp_path).suffix.lower()
            if comp_ext in companion_extensions:
                comp_dest = os.path.join(book_folder, comp_file)
                if os.path.exists(comp_dest) and config.on_duplicate == 'replace':
                    os.remove(comp_dest)
                shutil.move(comp_path, comp_dest)
                
                # If it's an image, save this path for the database
                if comp_ext in ['.jpg', '.jpeg', '.png']:
                    cover_path = comp_dest

    # Database Entry
    if database.add_book(config.db_file, author, book_title, destination, book_folder, cover_path):
        logger.info(f"  💾 Saved to SQLite database")

    # Clean up empty folder
    if os.path.normpath(source_dir) != os.path.normpath(config.watch_directory):
        if not os.listdir(source_dir): 
            try:
                os.rmdir(source_dir)
            except Exception:
                pass
                
    logger.info(f"✅ Successfully organized!")
    return True


class AudiobookHandler(FileSystemEventHandler):
    """Handle new files appearing in the watched folder"""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.processed_files = set()
    
    def on_created(self, event):
        if event.is_directory:
            return
        self._process_file(event.src_path)

    def on_moved(self, event):
        # This catches when a temporary file is renamed to the final .m4b
        if event.is_directory:
            return
        self._process_file(event.dest_path)
        
    def _process_file(self, file_path):
        # Ignore temporary files used during audio extraction/muxing
        filename = os.path.basename(file_path)
        if filename.startswith('temp') or filename.endswith('.tmp') or filename.endswith('.ff.txt'):
            return

        if file_path in self.processed_files:
            return
            
        time.sleep(self.config.check_interval)
        
        if not os.path.exists(file_path):
            return
            
        self.processed_files.add(file_path)
        organize_audiobook(file_path, self.config, self.logger)


def process_existing_files(config: Config, logger: logging.Logger):
    if not os.path.exists(config.watch_directory): return
    audio_files = []
    for root, _, files in os.walk(config.watch_directory):
        for f in files:
            file_path = os.path.join(root, f)
            if Path(file_path).suffix.lower() in config.audio_extensions:
                audio_files.append(file_path)
    
    for file_path in audio_files:
        organize_audiobook(file_path, config, logger)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.yaml')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    
    config = Config(args.config)
    logger = setup_logging(config)
    
    # Initialize the Database at startup!
    database.init_db(config.db_file)
    
    print("=" * 70)
    print("🎧 AUDIOBOOK ORGANIZER (Phase 1: Database Powered)")
    print("=" * 70)
    print(f"📝 Database File: {os.path.abspath(config.db_file)}")
    
    process_existing_files(config, logger)
    if args.once: return
        
    event_handler = AudiobookHandler(config, logger)
    observer = Observer()
    observer.schedule(event_handler, config.watch_directory, recursive=True)
    observer.start()
    
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()