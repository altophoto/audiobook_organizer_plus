"""
Audiobook Database Manager
Handles all SQLite connections, table creation, and queries for the audiobook library.
"""

import sqlite3
import os
from datetime import datetime
import logging

logger = logging.getLogger('audiobook_organizer.database')

def get_connection(db_path: str):
    """
    Creates a connection to the SQLite database.
    If the file doesn't exist, SQLite will automatically create it.
    """
    # row_factory allows us to access columns by name (e.g., row['author']) later
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: str):
    """
    Initializes the database schema.
    Creates the 'books' table if it doesn't already exist.
    """
    # We use a context manager (with) to ensure the connection closes automatically
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        
        # We use IF NOT EXISTS so this safely runs every time the script starts
        # file_path is UNIQUE to prevent duplicate entries if a file is re-processed
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                author TEXT NOT NULL,
                title TEXT NOT NULL,
                file_path TEXT UNIQUE NOT NULL,
                folder_path TEXT NOT NULL,
                cover_path TEXT,
                date_added DATETIME NOT NULL
            )
        ''')
        
        conn.commit()
        logger.debug(f"Database initialized at {os.path.abspath(db_path)}")

def add_book(db_path: str, author: str, title: str, file_path: str, folder_path: str, cover_path: str = None):
    """
    Inserts a new book into the database, or updates it if the file path already exists.
    """
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        date_added = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        try:
            # We use INSERT OR REPLACE. If the file_path already exists (because it's UNIQUE),
            # it updates the row instead of throwing an error.
            # Using '?' parameterization protects against SQL injection and handles weird characters in titles.
            cursor.execute('''
                INSERT OR REPLACE INTO books 
                (author, title, file_path, folder_path, cover_path, date_added)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (author, title, file_path, folder_path, cover_path, date_added))
            
            conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Database error adding book {title}: {e}")
            return False

def get_all_books(db_path: str):
    """
    Retrieves all books from the database. (We will use this in Phase 3 for the HTML builder).
    """
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM books ORDER BY author, title')
        return cursor.fetchall()