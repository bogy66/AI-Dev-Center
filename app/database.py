import sqlite3
from pathlib import Path


DB_PATH = Path("ai_dev_center.db")


class Database:

    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH)
        self.conn.row_factory = sqlite3.Row
        self.init_db()


    def init_db(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                description TEXT,
                created TEXT DEFAULT CURRENT_TIMESTAMP,
                last_used TEXT
            )
            """
        )

        self.conn.commit()


    def execute(self, query, params=()):
        cursor = self.conn.execute(query, params)
        self.conn.commit()
        return cursor
