"""Non-overwriting SQLite backup/restore to a NEW path; never prints row data.

Use only after operator approval. This does not coordinate uploads: quiesce writes
and snapshot uploads/configuration with the database as described in the runbook.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from urllib.parse import quote


def verify(path):
    connection = sqlite3.connect('file:' + quote(str(Path(path).resolve())) + '?mode=ro', uri=True)
    try:
        if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise RuntimeError('SQLite integrity check failed')
        if connection.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('SQLite foreign-key verification failed')
        tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {table: connection.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0] for table in tables}
    finally:
        connection.close()


def snapshot(source, destination):
    source, destination = Path(source).resolve(strict=True), Path(destination).absolute()
    manifest = Path(str(destination) + '.manifest.json')
    if destination.exists() or manifest.exists():
        raise FileExistsError('Destination/manifest must be new; existing data is never overwritten')
    verify(source)
    source_db = sqlite3.connect('file:' + quote(str(source)) + '?mode=ro', uri=True)
    target_db = None
    try:
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        target_db = sqlite3.connect(destination)
        source_db.backup(target_db)
    finally:
        source_db.close()
        if target_db:
            target_db.close()
    counts = verify(destination)
    with destination.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
    payload = {'format': 1, 'sha256': checksum, 'table_counts': counts}
    with manifest.open('x') as stream:
        os.chmod(manifest, 0o600)
        json.dump(payload, stream, indent=2)
    return payload


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--approved', action='store_true', required=True)
    args = parser.parse_args()
    result = snapshot(args.source, args.destination)
    print('Verified new SQLite snapshot; tables:', len(result['table_counts']))
