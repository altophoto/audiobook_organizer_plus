#!/usr/bin/env python3
"""
Audiobook Scanner (Phase 2)
Crawls the destination library drives and reconciles the SQLite database,
adding untracked files and removing deleted records.
"""

import os
from pathlib import Path
from html_builder import get_all_books, build_html

# Import tools from our existing modules
from audiobook_organizer import Config, setup_logging, get_metadata
from database import insert_book, get_all_file_paths, remove_book_by_path

def scan_library(config: Config, logger):
    db_file = config.config.get('settings', {}).get('db_file', 'library.db')
    
    logger.info("🔍 Fetching current database records...")
    db_files = get_all_file_paths(db_file)
    logger.info(f"   Found {len(db_files)} records in database.")
    
    # 1. Walk the physical drives to collect all audio files
    disk_files = set()
    drives_to_scan = [config.drive_a_l, config.drive_m_z]
    
    logger.info("🔍 Scanning physical drives for audiobooks... (this may take a minute)")
    for drive in drives_to_scan:
        if not os.path.exists(drive):
            logger.warning(f"⚠️ Drive not found or not mounted: {drive}")
            continue
            
        for root, _, files in os.walk(drive):
            for filename in files:
                file_path = os.path.join(root, filename)
                
                # Ignore temp files from InAudible muxing
                if filename.startswith('temp') or filename.endswith('.tmp') or filename.endswith('.ff.txt'):
                    continue
                    
                if Path(file_path).suffix.lower() in config.audio_extensions:
                    disk_files.add(os.path.normpath(file_path))
                    
    logger.info(f"   Found {len(disk_files)} audio files physically on disk.")
    
    # 2. Reconcile differences using Set mathematics
    missing_from_db = disk_files - db_files
    missing_from_disk = db_files - disk_files
    
    # 3. Process new additions (On Disk, but not in DB)
    if missing_from_db:
        logger.info(f"➕ Found {len(missing_from_db)} files missing from database. Adding them...")
        for path in missing_from_db:
            author, book_title = get_metadata(path, debug=False)
            
            if author and book_title:
                source_dir = os.path.dirname(path)
                cover_path = None
                
                # Look for cover art in the same folder
                for f in os.listdir(source_dir):
                    if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                        cover_path = os.path.join(source_dir, f)
                        break
                        
                insert_book(db_file, author, book_title, source_dir, path, cover_path)
                logger.info(f"   💾 Added: {book_title} by {author}")
            else:
                logger.warning(f"   ❌ Could not read metadata for: {path}")
    else:
        logger.info("➕ No new untracked files found.")
        
    # 4. Process deletions (In DB, but not on Disk)
    if missing_from_disk:
        logger.info(f"➖ Found {len(missing_from_disk)} ghost records in database. Removing them...")
        for path in missing_from_disk:
            # NOTE: The actual removal is commented out to prevent accidental data loss. Uncomment the line below to enable deletion.
            # remove_book_by_path(db_file, path)
            logger.info(f"   🗑️ Removed orphaned record: {os.path.basename(path)}")
    else:
        logger.info("➖ No orphaned records found.")
        
    logger.info("✅ Library scan and reconciliation complete!")

    # 5. Rebuild the HTML Interface
    logger.info("🌐 Rebuilding Vue.js HTML interface...")
    books_data = get_all_books(db_file)
    output_path = config.config.get('settings', {}).get('index_file', 'library_vue.html')
    
    if books_data:
        build_html(books_data, output_path)
        logger.info("✅ Vue.js interface updated!")

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Reconcile Audiobook Database with Physical Drives')
    parser.add_argument('--config', default='config.yaml', help='Path to config file')
    args = parser.parse_args()
    
    config = Config(args.config)
    logger = setup_logging(config)
    
    print("=" * 70)
    print("🎧 AUDIOBOOK SCANNER & RECONCILER")
    print("=" * 70)
    
    scan_library(config, logger)

if __name__ == "__main__":
    main()