#!/usr/bin/env python3
"""
Audiobook Scanner (Phase 2)
Crawls the destination library drives and reconciles the SQLite database,
adding untracked files and removing deleted records.
"""

import os
from html_builder import get_all_books, build_html
from pathlib import Path
import time
import os
import signal
import sys

# Global flag for graceful shutdown
stop_requested = False

def request_shutdown(sig, frame):
    """Catches Ctrl+C and politely asks the loop to stop."""
    global stop_requested
    if stop_requested:
        print("\n🚨 Force quit detected! Shutting down immediately!")
        sys.exit(1)
    
    print("\n⚠️ Graceful shutdown requested! Finishing current file... (Press Ctrl+C again to force quit)")
    stop_requested = True

# Hook the interceptor to the Ctrl+C command (SIGINT)
signal.signal(signal.SIGINT, request_shutdown)

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
        total_missing = len(missing_from_db)
        logger.info(f"➕ Found {total_missing} files missing from database. Rebuilding...")
        
        start_time = time.time()  # ⏱️ Start the stopwatch
        
        # enumerate() gives us a counter (index) starting at 1
        for index, path in enumerate(missing_from_db, 1):
            # --- THE SHUTDOWN CHECKPOINT ---
            if stop_requested:
                logger.warning(f"🛑 Processing halted early at file {index-1}. Saving current progress...")
                break  # This breaks out of the loop safely
                
            # Ensure we unpack all THREE variables from our newly upgraded metadata tool!
            author, book_title, needs_tagging = get_metadata(path, debug=False)
            
            if author and book_title:
                source_dir = os.path.dirname(path)
                cover_path = None
                
                # Look for cover art
                for f in os.listdir(source_dir):
                    if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                        cover_path = os.path.join(source_dir, f)
                        break
                        
                insert_book(db_file, author, book_title, source_dir, path, cover_path)
                
                # --- TIMER & ETA MATH ---
                elapsed_time = time.time() - start_time
                # Files divided by seconds
                files_per_second = index / elapsed_time if elapsed_time > 0 else 0
                remaining_files = total_missing - index
                # Remaining files divided by speed equals remaining seconds
                eta_seconds = int(remaining_files / files_per_second) if files_per_second > 0 else 0
                
                # Convert raw seconds into neat Minutes:Seconds
                mins, secs = divmod(eta_seconds, 60)
                
                # We slice the book title [:25] so super long titles don't ruin the console layout
                logger.info(f"   💾 [{index}/{total_missing}] Added: {book_title[:25]:<25} | Rate: {files_per_second:.1f} f/s | ETA: {mins:02d}m:{secs:02d}s")
            else:
                logger.warning(f"   ❌ Could not read metadata for: {path}")
    else:
        logger.info("➕ No new untracked files found.")
        
    # 4. Process deletions (In DB, but not on Disk)
    if missing_from_disk:
        logger.info(f"➖ Found {len(missing_from_disk)} ghost records in database. Removing them...")
        for path in missing_from_disk:
            remove_book_by_path(db_file, path)
            logger.info(f"   🗑️ Removed orphaned record: {os.path.basename(path)}")
    else:
        logger.info("➖ No orphaned records found.")

    # 5. Rebuild the HTML Interface
    logger.info("🌐 Rebuilding Vue.js HTML interface...")
    books_data = get_all_books(db_file)
    output_path = config.config.get('settings', {}).get('index_file', 'library_vue.html')
    
    if books_data:
        build_html(books_data, output_path)
        logger.info("✅ Vue.js interface updated!")

    logger.info("✅ Library scan and reconciliation complete!")

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