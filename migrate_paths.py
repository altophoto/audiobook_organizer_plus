#!/usr/bin/env python3
"""
Path Migrator
Updates the root directory paths in your SQLite database and regenerates the HTML.
"""

import sqlite3
import yaml
import os
from html_builder import get_all_books, build_html

def main():
    # ---------------------------------------------------------
    # 1. EDIT THESE TWO LINES WITH YOUR ACTUAL PATHS
    # ---------------------------------------------------------
    # Example old path (from your previous logs)
    old_path = "C:/sebdev/books_processed/Volumes/"
    
    # Example new Google Drive path (update this to match your new config.yaml!)
    new_path = "G:/My Drive/Audiobooks/Volumes" 
    # ---------------------------------------------------------

    # Normalize paths to match Windows slashes exactly how they are stored in SQLite
    old_path = os.path.normpath(old_path)
    new_path = os.path.normpath(new_path)

    # 2. Get database and HTML locations from config
    db_file = 'library.db'
    html_file = 'library_vue.html'
    if os.path.exists('config.yaml'):
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)
            db_file = config.get('settings', {}).get('db_file', 'library.db')
            html_file = config.get('settings', {}).get('index_file', 'library_vue.html')

    print(f"🔄 Replacing paths in database:\n  Old: {old_path}\n  New: {new_path}")
    
    # 3. Update the SQLite Database
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        # SQLite's REPLACE function does the heavy lifting instantly
        cursor.execute("""
            UPDATE books 
            SET file_path = REPLACE(file_path, ?, ?),
                folder_path = REPLACE(folder_path, ?, ?),
                cover_path = REPLACE(cover_path, ?, ?)
        """, (old_path, new_path, old_path, new_path, old_path, new_path))
        
        changes = cursor.rowcount
        conn.commit()
        conn.close()
        
        # Note: rowcount shows total rows checked/updated, not just the ones that changed
        print(f"✅ Successfully executed replacement across {changes} records.")
        
    except Exception as e:
        print(f"❌ Database error: {e}")
        return

    # 4. Rebuild the HTML file with the new links
    print("🌐 Rebuilding Vue.js HTML interface...")
    books_data = get_all_books(db_file)
    if books_data:
        build_html(books_data, html_file)
        print("✅ Migration complete! Open your HTML file to test the new Google Drive links.")

if __name__ == "__main__":
    main()