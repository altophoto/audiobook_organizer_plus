#!/usr/bin/env python3
"""
verify_folders.py - READ-ONLY audit of InAudible output.

Never moves, renames, writes or deletes anything in the folders it inspects.
It only writes one report file (verify_report.csv) in the current directory.

For every folder that contains an audio file (default: .m4b) it checks:
  * exactly one audio file, non-zero size, and mutagen can parse it
  * a duration exists
  * the .cue's last chapter starts BEFORE the audio ends (a truncated or
    damaged file usually fails this)
  * the file is not far smaller than its duration implies (heuristic)
  * the Author/Title tags exist
  * the .cue, .nfo and cover image are present

Status, worst first:
  SUSPECT      - regenerate this book with InAudible
  NO_METADATA  - audio is probably fine but tags are missing/incomplete
  WARN         - audio looks fine, something minor is missing (cover, nfo, cue)
  OK           - nothing found wrong

Usage:
  python verify_folders.py "C:\\path\\to\\InAudible\\output"
  python verify_folders.py "C:\\path" --ext .m4b --ext .mp3
"""

import os
import re
import sys
import csv
import argparse
from pathlib import Path

from mutagen import File as MutagenFile
from audiobook_organizer import get_metadata

RANK = {'OK': 0, 'WARN': 1, 'NO_METADATA': 2, 'SUSPECT': 3}
IMAGES = {'.jpg', '.jpeg', '.png'}


def cue_last_seconds(path):
    """Start time (seconds) of the last chapter in a .cue file, or None."""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        return None
    best = None
    for m in re.finditer(r'INDEX\s+01\s+(\d+):(\d+):(\d+)', text):
        mm, ss, ff = (int(x) for x in m.groups())
        t = mm * 60 + ss + ff / 75.0
        best = t if best is None or t > best else best
    return best


def audit_folder(dirpath, files, audio_ext):
    status, notes = 'OK', []

    def flag(level, note):
        nonlocal status
        notes.append(note)
        if RANK[level] > RANK[status]:
            status = level

    audio = [f for f in files if Path(f).suffix.lower() in audio_ext]
    exts = {Path(f).suffix.lower() for f in files}
    size_bytes = sum(os.path.getsize(os.path.join(dirpath, f)) for f in files
                     if os.path.isfile(os.path.join(dirpath, f)))

    if len(audio) > 1:
        flag('WARN', f'{len(audio)} audio files in one folder')
    target = os.path.join(dirpath, audio[0])

    try:
        actual = os.path.getsize(target)
        if actual == 0:
            flag('SUSPECT', 'audio file is 0 bytes')
        else:
            info = MutagenFile(target)
            if info is None or getattr(info, 'info', None) is None:
                flag('SUSPECT', 'audio cannot be parsed')
            else:
                length = getattr(info.info, 'length', 0) or 0
                if length <= 0:
                    flag('SUSPECT', 'no duration found')
                else:
                    cue = next((f for f in files if f.lower().endswith('.cue')), None)
                    if cue:
                        last = cue_last_seconds(os.path.join(dirpath, cue))
                        if last is not None and last > length + 2:
                            flag('SUSPECT', f'cue chapters run to {last/3600:.2f}h but audio is only {length/3600:.2f}h')
                    bitrate = getattr(info.info, 'bitrate', 0) or 0
                    if bitrate > 0 and actual < 0.85 * (bitrate / 8.0 * length):
                        flag('WARN', 'file smaller than its duration implies (possible truncation)')
    except Exception as e:
        flag('SUSPECT', f'error reading audio: {e}')

    if status != 'SUSPECT':
        author, title, needs_tagging = get_metadata(target)
        if not author or not title or needs_tagging:
            flag('NO_METADATA', 'author/title tags missing or incomplete')

    if '.cue' not in exts:
        flag('WARN', 'no .cue')
    if '.nfo' not in exts:
        flag('WARN', 'no .nfo')
    if not (exts & IMAGES):
        flag('WARN', 'no cover image')

    return status, size_bytes, '; '.join(notes)


def main():
    ap = argparse.ArgumentParser(description='Read-only audit of audiobook folders')
    ap.add_argument('root')
    ap.add_argument('--ext', action='append', help='audio extension (repeatable); default .m4b')
    ap.add_argument('--report', default='verify_report.csv')
    args = ap.parse_args()

    audio_ext = {e.lower() if e.startswith('.') else '.' + e.lower() for e in (args.ext or ['.m4b'])}
    if not os.path.isdir(args.root):
        print(f'Not a folder: {args.root}')
        sys.exit(1)

    rows, totals = [], {k: [0, 0] for k in RANK}
    for dirpath, _, files in os.walk(args.root):
        if not any(Path(f).suffix.lower() in audio_ext for f in files):
            continue
        status, size, notes = audit_folder(dirpath, files, audio_ext)
        rows.append((status, round(size / 1e9, 3), dirpath, notes))
        totals[status][0] += 1
        totals[status][1] += size
        if status != 'OK':
            print(f'{status:<12} {dirpath}\n{"":<12} {notes}')

    rows.sort(key=lambda r: (-RANK[r[0]], r[2]))
    with open(args.report, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['status', 'size_gb', 'folder', 'notes'])
        w.writerows(rows)

    print('\n' + '=' * 60)
    for k in ('OK', 'WARN', 'NO_METADATA', 'SUSPECT'):
        print(f'{k:<12} {totals[k][0]:>5} folders   {totals[k][1] / 1e9:>8.1f} GB')
    print(f'\nFull report: {os.path.abspath(args.report)}')
    print('Nothing was moved or changed.')


if __name__ == '__main__':
    main()
