import sqlite3
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional


class Database:
    def __init__(self, db_path: str = "bot_database.db"):
        self.db_path = db_path

    def get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self):
        with self.get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    joined_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    added_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT UNIQUE,
                    channel_name TEXT,
                    added_at TEXT DEFAULT (datetime('now'))
                );
            """)
            conn.commit()

    def add_user(self, user_id: int, username: str, full_name: str):
        with self.get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
                (user_id, username, full_name)
            )
            conn.commit()

    def get_user(self, user_id: int) -> Optional[Dict]:
        with self.get_conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            return dict(row) if row else None

    def get_total_users(self) -> int:
        with self.get_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def get_users_page(self, page: int, per_page: int = 10) -> List[Dict]:
        offset = page * per_page
        with self.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY joined_at DESC LIMIT ? OFFSET ?",
                (per_page, offset)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_user_ids(self) -> List[int]:
        with self.get_conn() as conn:
            rows = conn.execute("SELECT user_id FROM users").fetchall()
            return [r[0] for r in rows]

    def get_stats(self) -> Dict:
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')
        week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')
        month_ago = (now - timedelta(days=30)).strftime('%Y-%m-%d')

        with self.get_conn() as conn:
            total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            today_users = conn.execute(
                "SELECT COUNT(*) FROM users WHERE date(joined_at) = ?", (today,)
            ).fetchone()[0]
            week_users = conn.execute(
                "SELECT COUNT(*) FROM users WHERE date(joined_at) >= ?", (week_ago,)
            ).fetchone()[0]
            month_users = conn.execute(
                "SELECT COUNT(*) FROM users WHERE date(joined_at) >= ?", (month_ago,)
            ).fetchone()[0]
            total_channels = conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
            total_admins = conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]

        return {
            "total_users": total_users,
            "today_users": today_users,
            "week_users": week_users,
            "month_users": month_users,
            "total_channels": total_channels,
            "total_admins": total_admins
        }

    # Admin methods
    def is_admin(self, user_id: int) -> bool:
        with self.get_conn() as conn:
            row = conn.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,)).fetchone()
            return row is not None

    def add_admin(self, user_id: int, username: str, full_name: str):
        with self.get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO admins (user_id, username, full_name) VALUES (?, ?, ?)",
                (user_id, username, full_name)
            )
            conn.commit()

    def remove_admin(self, user_id: int):
        with self.get_conn() as conn:
            conn.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
            conn.commit()

    def get_admins(self) -> List[Dict]:
        with self.get_conn() as conn:
            rows = conn.execute("SELECT * FROM admins").fetchall()
            return [dict(r) for r in rows]

    # Channel methods
    def add_channel(self, channel_id: str, channel_name: str):
        with self.get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO channels (channel_id, channel_name) VALUES (?, ?)",
                (channel_id, channel_name)
            )
            conn.commit()

    def remove_channel(self, channel_id: str):
        with self.get_conn() as conn:
            conn.execute("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
            conn.commit()

    def get_channels(self) -> List[Dict]:
        with self.get_conn() as conn:
            rows = conn.execute("SELECT * FROM channels").fetchall()
            return [dict(r) for r in rows]