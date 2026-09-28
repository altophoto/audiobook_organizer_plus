#!/usr/bin/env python3
"""
Audiobook Organizer
Automatically organizes audiobook files into Author/Book Title folder structure
based on metadata tags, with configurable drive splitting (e.g., A-L vs M-Z).
Now includes support for processing InAudible subfolders, companion files (.nfo, .cue, .jpg),
and automatically generating BOTH clickable Markdown and HTML indexes of processed books.
"""

import os
import shutil
import time
import re
import sys
import logging
import urllib.request
import html
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

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
    """Configuration manager for the audiobook organizer"""
    
    def __init__(self, config_file='config.yaml'):
        self.config_file = config_file
        self.config = self.load_config()
        
    def load_config(self):
        """Load configuration from YAML file"""
        if not os.path.exists(self.config_file):
            print(f"❌ Config file not found: {self.config_file}")
            print(f"Please copy config.yaml.example to config.yaml and update paths")
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
    def index_file(self):
        path = self.config.get('settings', {}).get('index_file', 'library_index.md')
        # Smart detection: if you just provided a folder path in config.yaml, auto-append the filename
        if os.path.isdir(path) or path.endswith('/') or path.endswith('\\'):
            return os.path.join(path, 'library_index.md')
        return path


def setup_logging(config: Config) -> logging.Logger:
    """Set up logging configuration"""
    logger = logging.getLogger('audiobook_organizer')
    logger.setLevel(getattr(logging, config.log_level))
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    if config.log_file != 'console':
        file_handler = logging.FileHandler(config.log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    
    return logger


def sanitize_filename(name: str) -> str:
    """Remove or replace characters that are problematic in filenames"""
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    name = name.strip('. ')
    return name


def update_library_index(author: str, book_title: str, folder_path: str, file_path: str, index_file: str):
    """
    Appends an entry to both a Markdown index and an HTML index with clickable file:// links
    and an inline HTML5 audio player.
    """
    # Convert absolute Windows/OS paths into valid file:/// URIs
    folder_uri = "file:" + urllib.request.pathname2url(os.path.abspath(folder_path))
    file_uri = "file:" + urllib.request.pathname2url(os.path.abspath(file_path))
    date_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    # 1. MARKDOWN GENERATION
    file_exists = os.path.exists(index_file)
    with open(index_file, 'a', encoding='utf-8') as f:
        if not file_exists:
            f.write("# Audiobook Library Index\n\n")
            f.write("| Date Processed | Author | Book Title | Folder Link | Audio File |\n")
            f.write("|---|---|---|---|---|\n")
        
        safe_auth_md = author.replace('|', '-')
        safe_book_md = book_title.replace('|', '-')
        f.write(f"| {date_str} | {safe_auth_md} | {safe_book_md} | [📁 Open Folder]({folder_uri}) | [🎧 File Link]({file_uri}) |\n")

    # 2. HTML GENERATION
    base_path, _ = os.path.splitext(index_file)
    html_file = f"{base_path}.html"
    
    safe_auth_html = html.escape(author)
    safe_book_html = html.escape(book_title)
    
    folder_uri_html = folder_uri.replace("'", "%27").replace('"', "%22")
    file_uri_html = file_uri.replace("'", "%27").replace('"', "%22")
    
    # NEW: Added an <audio> tag to embed a mini media player right in the table cell!
    player_html = f"<audio controls preload='none' style='height: 35px;'><source src='{file_uri_html}'></audio><br><a href='{file_uri_html}' style='font-size: 0.8em; color: #7f8c8d;'>💾 Download/Save</a>"
    
    row_html = f"        <tr><td>{date_str}</td><td>{safe_auth_html}</td><td>{safe_book_html}</td><td><a href='{folder_uri_html}'>📁 Open Folder</a></td><td>{player_html}</td></tr>\n"
    closing_tags = "    </tbody>\n</table>\n</body>\n</html>"
    
    if not os.path.exists(html_file):
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write("<!DOCTYPE html>\n<html>\n<head>\n<meta charset='utf-8'>\n")
            f.write("<title>Audiobook Library Index</title>\n")
            f.write("<style>\n")
            f.write("  body { font-family: system-ui, sans-serif; margin: 2rem; background: #f4f4f9; color: #333; }\n")
            f.write("  h2 { color: #2c3e50; }\n")
            f.write("  table { border-collapse: collapse; width: 100%; background: white; box-shadow: 0 2px 5px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden; }\n")
            f.write("  th, td { text-align: left; padding: 12px 16px; border-bottom: 1px solid #eee; vertical-align: middle; }\n")
            f.write("  th { background-color: #2c3e50; color: white; font-weight: 600; }\n")
            f.write("  tr:hover { background-color: #f8f9fa; }\n")
            f.write("  a { text-decoration: none; color: #3498db; font-weight: 500; }\n")
            f.write("  a:hover { text-decoration: underline; color: #2980b9; }\n")
            f.write("  audio { max-width: 250px; }\n")
            f.write("</style>\n</head>\n<body>\n")
            f.write("<h2>🎧 Audiobook Library Index</h2>\n")
            f.write("<table>\n")
            f.write("    <thead><tr><th>Date Processed</th><th>Author</th><th>Book Title</th><th>Folder</th><th>Audio Player</th></tr></thead>\n")
            f.write("    <tbody>\n")
            f.write(row_html)
            f.write(closing_tags)
    else:
        with open(html_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if closing_tags in content:
            content = content.replace(closing_tags, row_html + closing_tags)
        else:
            content += row_html
            
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(content)


def get_metadata(file_path: str, debug: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """Extract author and book title from audio file metadata"""
    try:
        audio = MutagenFile(file_path)
        
        if audio is None:
            if debug:
                print(f"Could not read metadata from {file_path}")
            return None, None
        
        author = None
        book_title = None
        
        if isinstance(audio, MP4):
            if debug:
                print(f"  🔍 Available tags: {list(audio.keys())[:10]}")
            
            for tag in ['aART', '\xa9ART', '©ART']:
                if tag in audio:
                    value = audio[tag]
                    if isinstance(value, list):
                        value = value[0]
                    author = str(value)
                    break
            
            for tag in ['\xa9alb', '©alb']:
                if tag in audio:
                    value = audio[tag]
                    if isinstance(value, list):
                        value = value[0]
                    book_title = str(value)
                    break
            
            if not book_title:
                for tag in ['\xa9nam', '©nam']:
                    if tag in audio:
                        value = audio[tag]
                        if isinstance(value, list):
                            value = value[0]
                        book_title = str(value)
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
        
        if author:
            author = str(author).strip()
        if book_title:
            book_title = str(book_title).strip()
            
        return author, book_title
        
    except Exception as e:
        if debug:
            print(f"Error reading metadata from {file_path}: {e}")
        return None, None


def get_target_drive(author_name: str, config: Config) -> Optional[str]:
    """Determine which drive to use based on first letter of author's first name"""
    if not author_name:
        return None
    
    first_letter = author_name[0].upper()
    
    if 'A' <= first_letter <= 'L':
        return config.drive_a_l
    elif 'M' <= first_letter <= 'Z':
        return config.drive_m_z
    else:
        return config.drive_a_l


def organize_audiobook(file_path: str, config: Config, logger: logging.Logger) -> bool:
    """Read metadata, move audiobook, grab companion files, and update index."""
    logger.info(f"📚 Processing: {os.path.basename(file_path)}")
    
    if Path(file_path).suffix.lower() not in config.audio_extensions:
        return False
    
    author, book_title = get_metadata(file_path, debug=config.debug_metadata)
    
    if not author or not book_title:
        logger.warning(f"❌ Missing metadata - Author: {author}, Book: {book_title}")
        logger.warning(f"  Leaving file in watch folder")
        return False
    
    logger.info(f"📖 Author: {author}")
    logger.info(f"📕 Book: {book_title}")
    
    target_drive = get_target_drive(author, config)
    
    if not target_drive or not os.path.exists(target_drive):
        logger.error(f"❌ Target drive not mounted: {target_drive}")
        return False
    
    safe_author = sanitize_filename(author)
    safe_book = sanitize_filename(book_title)
    
    author_folder = os.path.join(target_drive, safe_author)
    book_folder = os.path.join(author_folder, safe_book)
    
    try:
        os.makedirs(book_folder, exist_ok=True)
    except Exception as e:
        logger.error(f"❌ Error creating folder {book_folder}: {e}")
        return False
    
    filename = os.path.basename(file_path)
    destination = os.path.join(book_folder, filename)
    source_dir = os.path.dirname(file_path)
    
    try:
        if os.path.exists(destination):
            logger.warning(f"⚠️  File already exists at destination: {destination}")
            
            if config.on_duplicate == 'replace':
                logger.info(f"  Deleting old version and replacing with new...")
                try:
                    os.remove(destination)
                except Exception as e:
                    logger.error(f"  ❌ Error deleting old file: {e}")
                    return False
            else:
                logger.info(f"  Skipping (on_duplicate='skip')")
                return False
        
        logger.info(f"🚚 Moving audio file to: {destination}")
        shutil.move(file_path, destination)
        
        # Move companion files
        companion_extensions = {'.nfo', '.cue', '.jpg', '.jpeg', '.png', '.txt'}
        
        for comp_file in os.listdir(source_dir):
            comp_path = os.path.join(source_dir, comp_file)
            
            if os.path.isfile(comp_path):
                comp_ext = Path(comp_path).suffix.lower()
                if comp_ext in companion_extensions:
                    comp_dest = os.path.join(book_folder, comp_file)
                    
                    try:
                        if os.path.exists(comp_dest):
                            if config.on_duplicate == 'replace':
                                os.remove(comp_dest)
                            else:
                                continue
                                
                        shutil.move(comp_path, comp_dest)
                        logger.info(f"  📎 Moved companion file: {comp_file}")
                    except Exception as e:
                        logger.error(f"  ❌ Error moving companion {comp_file}: {e}")

        # Clean up empty folder
        if os.path.normpath(source_dir) != os.path.normpath(config.watch_directory):
            if not os.listdir(source_dir): 
                try:
                    os.rmdir(source_dir)
                    logger.info(f"  🗑️ Removed empty folder: {os.path.basename(source_dir)}")
                except Exception as e:
                    logger.debug(f"Could not remove folder {source_dir}: {e}")
                    
        # Update BOTH index files
        try:
            update_library_index(author, book_title, book_folder, destination, config.index_file)
            base_html, _ = os.path.splitext(config.index_file)
            logger.info(f"  📝 Updated indexes: .md and .html")
        except Exception as e:
            logger.error(f"  ❌ Error updating library index: {e}")
                    
        logger.info(f"✅ Successfully organized!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error moving file: {e}")
        return False


class AudiobookHandler(FileSystemEventHandler):
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.processed_files = set()
    
    def on_created(self, event):
        if event.is_directory:
            return
            
        file_path = event.src_path
        
        if file_path in self.processed_files:
            return
            
        time.sleep(self.config.check_interval)
        
        if not os.path.exists(file_path):
            return
            
        self.processed_files.add(file_path)
        organize_audiobook(file_path, self.config, self.logger)


def process_existing_files(config: Config, logger: logging.Logger):
    logger.info(f"🔍 Checking for existing files in {config.watch_directory}...")
    
    if not os.path.exists(config.watch_directory):
        logger.warning(f"⚠️  Watch folder doesn't exist: {config.watch_directory}")
        return
    
    audio_files = []
    for root, _, files in os.walk(config.watch_directory):
        for f in files:
            file_path = os.path.join(root, f)
            if Path(file_path).suffix.lower() in config.audio_extensions:
                audio_files.append(file_path)
    
    if not audio_files:
        logger.info("  No existing audio files found")
        return
        
    logger.info(f"  Found {len(audio_files)} audio file(s) to process")
    
    success_count = 0
    for file_path in audio_files:
        if organize_audiobook(file_path, config, logger):
            success_count += 1
            
    logger.info(f"✅ Processed {success_count}/{len(audio_files)} files")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='Audiobook Organizer - Organize audiobooks by Author/Book Title'
    )
    parser.add_argument(
        '--config', 
        default='config.yaml',
        help='Path to config file (default: config.yaml)'
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='Process existing files and exit (don\'t watch for new files)'
    )
    args = parser.parse_args()
    
    config = Config(args.config)
    logger = setup_logging(config)
    
    print("=" * 70)
    print("🎧 AUDIOBOOK ORGANIZER")
    print("=" * 70)
    print(f"\n📂 Watching: {config.watch_directory}")
    print(f"📚 A-L Authors → {config.drive_a_l}")
    print(f"📚 M-Z Authors → {config.drive_m_z}")
    print(f"🔄 On duplicate: {config.on_duplicate}")
    print(f"📝 Index Files Output To: {os.path.dirname(os.path.abspath(config.index_file))}")
    
    if not os.path.exists(config.watch_directory):
        logger.error(f"❌ Watch folder doesn't exist: {config.watch_directory}")
        return
        
    process_existing_files(config, logger)
    
    if args.once:
        logger.info("✅ One-time processing complete")
        return
        
    print("\nPress Ctrl+C to stop\n")
    event_handler = AudiobookHandler(config, logger)
    observer = Observer()
    
    observer.schedule(event_handler, config.watch_directory, recursive=True)
    observer.start()
    
    logger.info("👀 Now watching for new files and folders...")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("\n🛑 Stopping audiobook organizer...")
        observer.stop()
        
    observer.join()
    logger.info("✅ Stopped")


if __name__ == "__main__":
    main()