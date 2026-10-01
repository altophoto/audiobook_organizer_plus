#!/usr/bin/env python3
"""
Audiobook HTML Builder (Phase 3)
Queries the SQLite database and generates a static HTML file powered by Vue.js
for lightning-fast searching, sorting, and cover art display.
"""

import os
import sqlite3
import json
from turtle import color
import urllib.request
import yaml

def get_all_books(db_file: str) -> list:
    """Fetch all books from the database and format as a list of dictionaries."""
    if not os.path.exists(db_file):
        print(f"❌ Database {db_file} not found.")
        return []
        
    conn = sqlite3.connect(db_file)
    # This row_factory allows us to access columns by their name instead of index
    conn.row_factory = sqlite3.Row  
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT author, title AS book_title, folder_path, file_path, cover_path, date_added 
            FROM books
        """)
    except sqlite3.OperationalError as e:
        print(f"❌ SQLite Error: {e}")
        return []

    rows = cursor.fetchall()
    books = []
    
    for row in rows:
        book = dict(row)
        
        # Convert local OS paths to valid file:/// URIs for the browser
        if book.get('file_path'):
            book['file_uri'] = "file:" + urllib.request.pathname2url(os.path.abspath(book['file_path']))
        if book.get('folder_path'):
            book['folder_uri'] = "file:" + urllib.request.pathname2url(os.path.abspath(book['folder_path']))
        
        # Handle cover art (falling back to empty if missing)
        # if book.get('cover_path') and os.path.exists(book['cover_path']):
        # Handle cover art (trusting the database path for cloud streams)
        if book.get('cover_path'):
            book['cover_uri'] = "file:" + urllib.request.pathname2url(os.path.abspath(book['cover_path']))
        else:
            book['cover_uri'] = ""
            
        books.append(book)
        
    conn.close()
    return books


def build_html(books: list, output_file: str = "library_vue.html"):
    """Injects the JSON payload into a Vue.js HTML template and saves it."""
    
    # 1. Auto-correct the extension if the config file still says .md
    if output_file.lower().endswith('.md'):
        output_file = output_file[:-3] + '.html'
        
    # 2. Safely create the target directories if they don't exist yet
    output_dir = os.path.dirname(os.path.abspath(output_file))
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        
    # Convert our list of Python dictionaries into a massive JSON string
    books_json = json.dumps(books)
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Audiobook Library</title>
    <!-- Load Vue 3 via CDN -->
    <script src="https://unpkg.com/vue@3/dist/vue.global.js"></script>
    <style>
        :root {{
            --bg-color: #1e1e24;
            --card-bg: #2b2b36;
            --text-main: #f5f5f5;
            --text-muted: #a0a0b0;
            --accent: #4fc08d;
            --border-color: #3f3f4e;
        }}
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 2rem 4rem;
        }}
        .top-bar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--border-color);
        }}
        .search-box {{
            padding: 0.8rem 1.2rem;
            width: 350px;
            border-radius: 20px;
            border: 1px solid var(--border-color);
            background-color: var(--card-bg);
            color: white;
            font-size: 1rem;
            transition: border-color 0.2s;
        }}
        .search-box:focus {{
            outline: none;
            border-color: var(--accent);
        }}
        .sort-select {{
            padding: 0.8rem;
            background: var(--card-bg);
            color: white;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            margin-left: 15px;
            font-size: 1rem;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 2rem;
        }}
        .card {{
            background-color: var(--card-bg);
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid var(--border-color);
            transition: transform 0.2s, box-shadow 0.2s;
            display: flex;
            flex-direction: column;
        }}
        .card:hover {{
            transform: translateY(-4px);
            box-shadow: 0 10px 20px rgba(0,0,0,0.4);
            border-color: #555;
        }}
        .cover {{
            width: 100%;
            aspect-ratio: 1 / 1;
            object-fit: cover;
            background-color: #1a1a20;
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--text-muted);
            font-size: 0.9rem;
        }}
        .info {{
            padding: 1.2rem;
            flex-grow: 1;
            display: flex;
            flex-direction: column;
        }}
        .title {{
            font-weight: 600;
            font-size: 1.1rem;
            margin: 0 0 0.4rem 0;
            line-height: 1.3;
        }}
        .author {{
            color: var(--text-muted);
            font-size: 0.95rem;
            margin: 0 0 1.2rem 0;
        }}
        .buttons {{
            margin-top: auto;
            display: flex;
            gap: 10px;
        }}
        .buttons a {{
            text-decoration: none;
            font-size: 0.85rem;
            padding: 0.6rem;
            border-radius: 6px;
            text-align: center;
            flex: 1;
            font-weight: 600;
            transition: opacity 0.2s;
        }}
        .buttons a:hover {{
            opacity: 0.8;
        }}
        .btn-play {{ background-color: var(--accent); color: #000; }}
        .btn-folder {{ background-color: #444; color: white; border: 1px solid #555; }}
        .btn-download {{ background-color: #3498db; color: white; border: 1px solid #2980b9; }}
        .empty-state {{
            grid-column: 1 / -1;
            text-align: center;
            padding: 4rem;
            color: var(--text-muted);
            font-size: 1.2rem;
        }}
    </style>
</head>
<body>
    <div id="app">
        <div class="top-bar">
            <div>
                <h1 style="margin: 0 0 8px 0;">🎧 Audiobook Vault</h1>
                <div style="color: var(--text-muted);">{{{{ filteredBooks.length }}}} titles found</div>
            </div>
            <div style="display: flex; align-items: center;">
                <input type="text" class="search-box" v-model="searchQuery" placeholder="Search by title or author...">
                <select class="sort-select" v-model="sortBy">
                    <option value="date_added">Date Added (Newest)</option>
                    <option value="book_title">Title (A-Z)</option>
                    <option value="author">Author (A-Z)</option>
                </select>
            </div>
        </div>

        <div class="grid">
            <div class="card" v-for="book in filteredBooks" :key="book.file_path">
                <img v-if="book.cover_uri" :src="book.cover_uri" class="cover" loading="lazy">
                <div v-else class="cover">No Cover Art</div>
                
                <div class="info">
                    <h3 class="title">{{{{ book.book_title }}}}</h3>
                    <p class="author">{{{{ book.author }}}}</p>
                    <div class="buttons">
                        <a :href="book.file_uri" class="btn-play">▶ Play</a>
                        <a :href="book.folder_uri" class="btn-folder">📁 Folder</a>
                        <a :href="book.file_uri" download class="btn-download">⬇️ Download</a>
                    </div>
                </div>
            </div>
            
            <div v-if="filteredBooks.length === 0" class="empty-state">
                No audiobooks found matching "{{{{ searchQuery }}}}"
            </div>
        </div>
    </div>

    <script>
        const {{ createApp }} = Vue;

        createApp({{
            data() {{
                return {{
                    searchQuery: '',
                    sortBy: 'date_added',
                    // The JSON payload injected directly from Python
                    books: {books_json}
                }}
            }},
            computed: {{
                // This computed property reacts instantly whenever searchQuery or sortBy changes
                filteredBooks() {{
                    let result = this.books;
                    
                    if (this.searchQuery) {{
                        const query = this.searchQuery.toLowerCase();
                        result = result.filter(b => 
                            (b.book_title && b.book_title.toLowerCase().includes(query)) ||
                            (b.author && b.author.toLowerCase().includes(query))
                        );
                    }}
                    
                    result.sort((a, b) => {{
                        if (this.sortBy === 'date_added') {{
                            // Reverse chronological (newest first)
                            return (b.date_added || '').localeCompare(a.date_added || '');
                        }} else if (this.sortBy === 'book_title') {{
                            return (a.book_title || '').localeCompare(b.book_title || '');
                        }} else if (this.sortBy === 'author') {{
                            return (a.author || '').localeCompare(b.author || '');
                        }}
                        return 0;
                    }});
                    
                    return result;
                }}
            }}
        }}).mount('#app');
    </script>
</body>
</html>
"""
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
        
    print(f"✅ Vue.js library interface successfully generated at: {os.path.abspath(output_file)}")


def main():
    db_path = 'library.db'
    output_path = 'library_vue.html'
    
    if os.path.exists('config.yaml'):
        with open('config.yaml', 'r') as f:
            config = yaml.safe_load(f)
            db_path = config.get('settings', {}).get('db_file', 'library.db')
            output_path = config.get('settings', {}).get('index_file', 'library_vue.html')
            
    print(f"🔍 Reading from database: {db_path}")
    books_data = get_all_books(db_path)
    
    if books_data:
        print(f"📚 Found {len(books_data)} books. Building HTML...")
        build_html(books_data, output_path)
    else:
        print("⚠️ No books found to generate. Ensure the database is populated.")

if __name__ == "__main__":
    main()