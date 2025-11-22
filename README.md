# 🎧 Audiobook Organizer

Automatically organize your audiobook library into a clean `Author/Book Title` folder structure based on metadata tags. Perfect for use with [Audiobookshelf](https://www.audiobookshelf.org/) or any audiobook library management system!

## ✨ Features

- 📚 **Automatic Organization**: Reads metadata (Album Artist & Album tags) and creates Author/Book folders
- 💾 **Multi-Drive Support**: Split library across drives (e.g., A-L on one drive, M-Z on another)
- 🔄 **Duplicate Handling**: Choose to replace old versions or skip duplicates
- 👀 **Watch Mode**: Continuously monitors a folder for new audiobooks
- 🎯 **One-Time Mode**: Process existing files and exit
- 🛠️ **Highly Configurable**: YAML config file for all settings
- 📝 **Multiple Formats**: Supports M4B, M4A, MP3, FLAC, OGG, and more
- 🧹 **Filename Sanitization**: Removes problematic characters automatically

## 📋 Requirements

- Python 3.7 or higher
- External drives (if using multi-drive setup)
- Audiobooks with proper metadata tags (Album Artist = Author, Album = Book Title)

## 🚀 Quick Start

### 1. Install

```bash
# Clone the repository
git clone https://github.com/yourusername/audiobook-organizer.git
cd audiobook-organizer

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure

```bash
# Copy the example config
cp config.yaml.example config.yaml

# Edit with your paths
nano config.yaml  # or use your favorite editor
```

**Minimum configuration:**
```yaml
watch_directory: "/path/to/completed/audiobooks"

drives:
  a_l: "/Volumes/Audiobooks_AL/Library"  # Authors A-L
  m_z: "/Volumes/Audiobooks_MZ/Library"  # Authors M-Z
```

### 3. Run

```bash
# Watch mode (continuous)
python3 audiobook_organizer.py

# One-time mode (process existing files and exit)
python3 audiobook_organizer.py --once

# Use custom config file
python3 audiobook_organizer.py --config /path/to/config.yaml
```

## 📖 How It Works

1. **Monitors** your watch directory for audiobook files
2. **Reads** metadata tags:
   - Album Artist (or Artist) → Author name
   - Album → Book title
3. **Determines** target drive based on author's first letter:
   - A-L → Drive 1
   - M-Z → Drive 2
4. **Creates** folder structure: `Author/Book Title/`
5. **Moves** the file to the organized location

### Example

```
Input file: /completed/audiobook.m4b
Metadata:
  - Album Artist: "Brandon Sanderson"
  - Album: "The Way of Kings"

Output: /Volumes/Audiobooks_AL/Library/Brandon Sanderson/The Way of Kings/audiobook.m4b
```

## ⚙️ Configuration Options

### Basic Settings

```yaml
# Directory to watch for new audiobooks
watch_directory: "/path/to/completed"

# Target drives for organized library
drives:
  a_l: "/path/to/drive1"  # Authors A-L
  m_z: "/path/to/drive2"  # Authors M-Z
```

### Advanced Settings

```yaml
settings:
  # Handle duplicates: "replace" or "skip"
  on_duplicate: "replace"
  
  # File check interval (seconds)
  check_interval: 2
  
  # Supported file extensions
  audio_extensions:
    - ".m4b"
    - ".m4a"
    - ".mp3"
    - ".flac"

logging:
  log_file: "audiobook_organizer.log"  # or "console" for terminal only
  log_level: "INFO"  # DEBUG, INFO, WARNING, ERROR
  debug_metadata: false  # Show detailed metadata extraction info
```

## 🔗 Integration with Other Tools

### Audiobookshelf

Perfect companion for [Audiobookshelf](https://www.audiobookshelf.org/)! Organize your files first, then point Audiobookshelf at your organized library.

### Telegram Uploader

Works great with audiobook upload/download workflows! Use this organizer as the final step after downloading/processing.

### Custom Workflows

The organizer can be integrated into larger automation workflows. See the [workflow example](docs/workflow-example.md) for ideas.

## 🐛 Troubleshooting

### "Missing metadata"

**Problem**: Files are skipped with "Missing metadata" error

**Solution**: Check that your audiobook files have:
- Album Artist (or Artist) tag set to the author name
- Album tag set to the book title

Use a tool like [Mp3tag](https://www.mp3tag.de/) or [Kid3](https://kid3.kde.org/) to edit tags.

### "Target drive not mounted"

**Problem**: Script can't find your external drives

**Solution**: 
1. Check that drives are connected and mounted
2. Verify paths in `config.yaml` match your actual mount points
3. On macOS, check `/Volumes/`; on Linux, check `/mnt/` or `/media/`

### Watch mode not picking up files

**Problem**: Files appear in folder but aren't processed

**Solution**:
- Use `--once` mode first to process existing files
- Then start watch mode for new files
- Or use `touch *.m4b` to update file timestamps

## 📁 Project Structure

```
audiobook-organizer/
├── audiobook_organizer.py     # Main script
├── config.yaml.example        # Example configuration
├── requirements.txt           # Python dependencies
├── README.md                  # This file
└── docs/
    ├── workflow-example.md    # Integration examples
    └── metadata-guide.md      # Metadata tagging guide
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

### Development Setup

```bash
# Clone and install in development mode
git clone https://github.com/yourusername/audiobook-organizer.git
cd audiobook-organizer
pip install -r requirements.txt

# Run tests (if available)
python -m pytest tests/
```

## 📜 License

MIT License - see LICENSE file for details

## 🙏 Acknowledgments

- Built for the [Audiobookshelf](https://www.audiobookshelf.org/) community
- Uses [mutagen](https://mutagen.readthedocs.io/) for metadata reading
- File watching powered by [watchdog](https://python-watchdog.readthedocs.io/)

## 💬 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/audiobook-organizer/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/audiobook-organizer/discussions)
- **Audiobookshelf Discord**: [Join here](https://discord.gg/audiobookshelf)

---

Made with ❤️ for audiobook lovers everywhere
