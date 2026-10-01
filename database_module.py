"""
Database Management Module
Handles all SQLite interactions for the Audiobook Organizer.
"""

import sqlite3
import os

def init_db(db_file: str):
    """Initializes the SQLite database and creates the books table if it doesn't exist."""
    # Ensure the directory exists if the database is buried in a folder
    os.makedirs(os.path.dirname(os.path.abspath(db_file)), exist_ok=True)
    
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author TEXT,
            title TEXT,
            folder_path TEXT,
            file_path TEXT UNIQUE,
            cover_path TEXT,
            date_added DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


def insert_book(db_file: str, author: str, title: str, folder_path: str, file_path: str, cover_path: str):
    """Inserts a new book into the database, or updates it if it already exists."""
    init_db(db_file)  # Always ensure the table exists before inserting
    
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    try:
        # INSERT OR REPLACE ensures we don't get errors if a book is scanned twice
        cursor.execute('''
            INSERT OR REPLACE INTO books (author, title, folder_path, file_path, cover_path)
            VALUES (?, ?, ?, ?, ?)
        ''', (author, title, folder_path, file_path, cover_path))
        conn.commit()
    except sqlite3.Error as e:
        print(f"❌ SQLite Insert Error: {e}")
    finally:
        conn.close()


def get_all_file_paths(db_file: str) -> set:
    """Returns a mathematical Set of all file paths currently in the database."""
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT file_path FROM books")
        # Extract the first column from each row and normalize the path for Windows
        paths = {os.path.normpath(row[0]) for row in cursor.fetchall()}
        conn.close()
        return paths
    except sqlite3.OperationalError:
        # If the table doesn't exist yet, return an empty set
        return set()


def remove_book_by_path(db_file: str, file_path: str):
    """Deletes a book record from the database if the physical file is missing."""
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM books WHERE file_path = ?", (file_path,))
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        print(f"❌ SQLite Delete Error: {e}")