import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / 'atlas.sqlite3'
        with self.connection() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS tasks (
              id INTEGER PRIMARY KEY, title TEXT NOT NULL, subject TEXT NOT NULL,
              kind TEXT NOT NULL, due TEXT NOT NULL, minutes INTEGER NOT NULL,
              done INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY, title TEXT NOT NULL, start TEXT NOT NULL,
              end TEXT NOT NULL, task_id INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
              generated INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS notes (
              id INTEGER PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
              source TEXT NOT NULL DEFAULT 'notitie');
            CREATE TABLE IF NOT EXISTS recipes (
              id INTEGER PRIMARY KEY, title TEXT NOT NULL, portions REAL NOT NULL,
              ingredients TEXT NOT NULL, method TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS actions (
              id INTEGER PRIMARY KEY, name TEXT NOT NULL, payload TEXT NOT NULL,
              status TEXT NOT NULL, result TEXT NOT NULL DEFAULT '',
              created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def rows(self, sql, args=()):
        with self.connection() as db:
            return [dict(row) for row in db.execute(sql, args)]

    def write(self, sql, args=()):
        with self.connection() as db:
            return db.execute(sql, args).lastrowid

    def setting(self, key, default=None):
        rows = self.rows('SELECT value FROM settings WHERE key=?', (key,))
        return json.loads(rows[0]['value']) if rows else default

    def set_setting(self, key, value):
        self.write('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))
