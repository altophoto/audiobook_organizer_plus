#!/usr/bin/env python3
"""
Audiobook Organizer
Automatically organizes audiobook files into Author/Book Title folder structure
based on metadata tags, with configurable drive splitting (e.g., A-L vs M-Z).

Perfect for use with Audiobookshelf or any audiobook library management system.

Author: Community collaboration
License: MIT
"""

import os
import shutil
import time
import re
import sys
import logging
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
            
        # Validate required fields
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


def setup_logging(config: Config) -> logging.Logger:
    """Set up logging configuration"""
    logger = logging.getLogger('audiobook_organizer')
    logger.setLevel(getattr(logging, config.log_level))
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File handler (if specified)
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
    """
    Remove or replace characters that are problematic in filenames
    
    Args:
        name: Filename to sanitize
        
    Returns:
        Sanitized filename
    """
    # Replace problematic characters
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Remove leading/trailing spaces and dots
    name = name.strip('. ')
    return name


def get_metadata(file_path: str, debug: bool = False) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract author and book title from audio file metadata
    
    Args:
        file_path: Path to the audio file
        debug: Whether to show debug output
        
    Returns:
        Tuple of (author, book_title) or (None, None) if extraction fails
    """
    try:
        # Read metadata directly (not using easy=True for better MP4 tag access)
        audio = MutagenFile(file_path)
        
        if audio is None:
            if debug:
                print(f"Could not read metadata from {file_path}")
            return None, None
        
        author = None
        book_title = None
        
        # For M4B/M4A files (MP4 container)
        if isinstance(audio, MP4):
            if debug:
                print(f"   🔍 Available tags: {list(audio.keys())[:10]}")
            
            # Author: Try album artist first, then regular artist
            for tag in ['aART', '\xa9ART', '©ART']:
                if tag in audio:
                    value = audio[tag]
                    if isinstance(value, list):
                        value = value[0]
                    author = str(value)
                    if debug:
                        print(f"   ✓ Found author in '{tag}': {author}")
                    break
            
            # Book title: Try album first, then title
            for tag in ['\xa9alb', '©alb']:
                if tag in audio:
                    value = audio[tag]
                    if isinstance(value, list):
                        value = value[0]
                    book_title = str(value)
                    if debug:
                        print(f"   ✓ Found book title in '{tag}': {book_title}")
                    break
            
            # If no album, try title as fallback
            if not book_title:
                for tag in ['\xa9nam', '©nam']:
                    if tag in audio:
                        value = audio[tag]
                        if isinstance(value, list):
                            value = value[0]
                        book_title = str(value)
                        if debug:
                            print(f"   ✓ Found book title in title '{tag}': {book_title}")
                        break
        else:
            # For other formats (MP3, etc) - try using tags directly
            if hasattr(audio, 'tags') and audio.tags:
                # Try to get album artist or artist
                for tag_name in ['albumartist', 'artist', 'ALBUMARTIST', 'ARTIST', 'TPE2', 'TPE1']:
                    if tag_name in audio.tags:
                        author = str(audio.tags[tag_name][0] if isinstance(audio.tags[tag_name], list) else audio.tags[tag_name])
                        break
                
                # Try to get album
                for tag_name in ['album', 'ALBUM', 'TALB']:
                    if tag_name in audio.tags:
                        book_title = str(audio.tags[tag_name][0] if isinstance(audio.tags[tag_name], list) else audio.tags[tag_name])
                        break
        
        # Clean up the metadata
        if author:
            author = str(author).strip()
        if book_title:
            book_title = str(book_title).strip()
            
        return author, book_title
        
    except Exception as e:
        if debug:
            print(f"Error reading metadata from {file_path}: {e}")
            import traceback
            traceback.print_exc()
        return None, None


def get_target_drive(author_name: str, config: Config) -> Optional[str]:
    """
    Determine which drive to use based on first letter of author's first name
    
    Args:
        author_name: Name of the author
        config: Configuration object
        
    Returns:
        Path to target drive or None if invalid
    """
    if not author_name:
        return None
    
    # Get the first letter of the first name
    first_letter = author_name[0].upper()
    
    # A-L goes to drive 1, M-Z goes to drive 2
    if 'A' <= first_letter <= 'L':
        return config.drive_a_l
    elif 'M' <= first_letter <= 'Z':
        return config.drive_m_z
    else:
        # Numbers or special characters default to A-L drive
        return config.drive_a_l


def organize_audiobook(file_path: str, config: Config, logger: logging.Logger) -> bool:
    """
    Read metadata and move audiobook to appropriate location
    
    Args:
        file_path: Path to the audiobook file
        config: Configuration object
        logger: Logger instance
        
    Returns:
        True if successful, False otherwise
    """
    logger.info(f"📚 Processing: {os.path.basename(file_path)}")
    
    # Check if it's an audio file
    if Path(file_path).suffix.lower() not in config.audio_extensions:
        logger.info(f"⏭️  Skipping non-audio file: {file_path}")
        return False
    
    # Get metadata
    author, book_title = get_metadata(file_path, debug=config.debug_metadata)
    
    if not author or not book_title:
        logger.warning(f"❌ Missing metadata - Author: {author}, Book: {book_title}")
        logger.warning(f"   Leaving file in watch folder")
        return False
    
    logger.info(f"📖 Author: {author}")
    logger.info(f"📕 Book: {book_title}")
    
    # Determine target drive
    target_drive = get_target_drive(author, config)
    
    if not target_drive or not os.path.exists(target_drive):
        logger.error(f"❌ Target drive not mounted: {target_drive}")
        return False
    
    logger.info(f"💾 Target drive: {target_drive}")
    
    # Sanitize names for filesystem
    safe_author = sanitize_filename(author)
    safe_book = sanitize_filename(book_title)
    
    # Create folder structure: Author/Book Title/
    author_folder = os.path.join(target_drive, safe_author)
    book_folder = os.path.join(author_folder, safe_book)
    
    # Create directories if they don't exist
    try:
        os.makedirs(book_folder, exist_ok=True)
        logger.info(f"📁 Created/verified folder: {book_folder}")
    except Exception as e:
        logger.error(f"❌ Error creating folder {book_folder}: {e}")
        return False
    
    # Move the file
    filename = os.path.basename(file_path)
    destination = os.path.join(book_folder, filename)
    
    try:
        # Check if file already exists at destination
        if os.path.exists(destination):
            logger.warning(f"⚠️  File already exists at destination: {destination}")
            
            if config.on_duplicate == 'replace':
                logger.info(f"   Deleting old version and replacing with new...")
                try:
                    os.remove(destination)
                    logger.info(f"   🗑️  Old version deleted")
                except Exception as e:
                    logger.error(f"   ❌ Error deleting old file: {e}")
                    return False
            else:  # skip
                logger.info(f"   Skipping (on_duplicate='skip')")
                return False
        
        logger.info(f"🚚 Moving to: {destination}")
        shutil.move(file_path, destination)
        logger.info(f"✅ Successfully organized!")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error moving file: {e}")
        return False


class AudiobookHandler(FileSystemEventHandler):
    """Handle new files appearing in the watched folder"""
    
    def __init__(self, config: Config, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self.processed_files = set()
    
    def on_created(self, event):
        """Called when a file is created"""
        if event.is_directory:
            return
        
        file_path = event.src_path
        
        # Avoid processing the same file multiple times
        if file_path in self.processed_files:
            return
        
        # Wait a moment to ensure file is fully written
        time.sleep(self.config.check_interval)
        
        # Check if file still exists (in case it was quickly moved)
        if not os.path.exists(file_path):
            return
        
        # Mark as processed
        self.processed_files.add(file_path)
        
        # Organize the audiobook
        organize_audiobook(file_path, self.config, self.logger)


def process_existing_files(config: Config, logger: logging.Logger):
    """Process any files that already exist in the watch folder"""
    logger.info(f"🔍 Checking for existing files in {config.watch_directory}...")
    
    if not os.path.exists(config.watch_directory):
        logger.warning(f"⚠️  Watch folder doesn't exist: {config.watch_directory}")
        return
    
    files = [f for f in os.listdir(config.watch_directory) 
             if os.path.isfile(os.path.join(config.watch_directory, f))]
    
    if not files:
        logger.info("   No existing files found")
        return
    
    logger.info(f"   Found {len(files)} file(s) to process")
    
    success_count = 0
    for filename in files:
        file_path = os.path.join(config.watch_directory, filename)
        if organize_audiobook(file_path, config, logger):
            success_count += 1
    
    logger.info(f"✅ Processed {success_count}/{len(files)} files")


def main():
    """Main entry point"""
    # Parse command line arguments
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
    
    # Load configuration
    config = Config(args.config)
    logger = setup_logging(config)
    
    print("=" * 70)
    print("🎧 AUDIOBOOK ORGANIZER")
    print("=" * 70)
    print(f"\n📂 Watching: {config.watch_directory}")
    print(f"📚 A-L Authors → {config.drive_a_l}")
    print(f"📚 M-Z Authors → {config.drive_m_z}")
    print(f"🔄 On duplicate: {config.on_duplicate}")
    
    # Check if watch folder exists
    if not os.path.exists(config.watch_directory):
        logger.error(f"❌ Watch folder doesn't exist: {config.watch_directory}")
        return
    
    # Process existing files first
    process_existing_files(config, logger)
    
    # If --once flag is set, exit after processing existing files
    if args.once:
        logger.info("✅ One-time processing complete")
        return
    
    # Set up file watcher
    print("\nPress Ctrl+C to stop\n")
    event_handler = AudiobookHandler(config, logger)
    observer = Observer()
    observer.schedule(event_handler, config.watch_directory, recursive=False)
    observer.start()
    
    logger.info("👀 Now watching for new files...")
    
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
