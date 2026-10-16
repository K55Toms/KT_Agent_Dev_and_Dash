"""Persist only the dashboard's bounded, sanitized projections."""

import json
import os
from pathlib import Path
import sqlite3
import stat
import threading


class Store:
    def __init__(self, directory):
        directory = Path(directory)
        if not directory.is_absolute():
            directory = Path.cwd() / directory
        for ancestor in [directory, *directory.parents]:
            if ancestor.is_symlink():
                raise ValueError("Runtime paths must not contain symbolic links")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("Runtime directory must be owned by the current user")
        os.chmod(directory, 0o700)
        database = directory / "dashboard.sqlite3"
        for candidate in [database, *[Path(str(database) + x) for x in ("-journal", "-wal", "-shm")]]:
            if candidate.exists() or candidate.is_symlink():
                info = candidate.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                    raise ValueError("Database files must be private regular files with one link")
                # Existing SQLite sidecars must be private before SQLite opens them.
                if candidate != database:
                    os.chmod(candidate, 0o600, follow_symlinks=False)
        fd = os.open(database, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise ValueError("Database must be a private regular file")
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        # The private, owned directory prevents other users swapping the checked file.
        self.lock = threading.RLock()
        self.db = sqlite3.connect(database, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))")
        self.db.commit()

    def load(self, kind):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute(
                "SELECT body FROM records WHERE kind=? ORDER BY rowid", (kind,))]

    def put(self, kind, record):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?)",
                            (kind, record["id"], json.dumps(record, allow_nan=False)))
            self.db.commit()

    def close(self):
        with self.lock:
            self.db.close()

    def delete(self, kind, identifier):
        with self.lock:
            self.db.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, identifier))
            self.db.commit()
