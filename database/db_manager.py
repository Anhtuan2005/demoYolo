"""
Database Manager — Lưu trữ lịch sử sự kiện.
"""
import sqlite3
import time
import logging
import threading
from pathlib import Path
import config

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, db_path=None):
        self.db_path = str(db_path or config.DB_PATH)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    threat_level TEXT NOT NULL,
                    description TEXT NOT NULL,
                    track_ids TEXT,
                    image_path TEXT,
                    notified INTEGER DEFAULT 0
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS tracks (
                    track_id INTEGER PRIMARY KEY,
                    label TEXT,
                    first_seen REAL,
                    last_seen REAL,
                    alert_count INTEGER DEFAULT 0
                )
            """)
            conn.commit()
            conn.close()
            logger.info(f"✅ Database initialized: {self.db_path}")

    def add_event(self, event, image_path=None):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute(
                "INSERT INTO events (timestamp, threat_level, description, track_ids, image_path, notified) VALUES (?, ?, ?, ?, ?, ?)",
                (event.timestamp, event.threat_level, event.description,
                 ",".join(str(x) for x in event.track_ids), image_path, int(event.notified))
            )
            conn.commit()
            conn.close()

    def update_track(self, track_info):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO tracks (track_id, label, first_seen, last_seen, alert_count)
                VALUES (?, ?, ?, ?, ?)
            """, (track_info.track_id, track_info.label, track_info.first_seen,
                  track_info.last_seen, track_info.alert_count))
            conn.commit()
            conn.close()

    def get_events(self, limit=50, threat_level=None):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            if threat_level:
                c.execute("SELECT * FROM events WHERE threat_level = ? ORDER BY timestamp DESC LIMIT ?",
                          (threat_level, limit))
            else:
                c.execute("SELECT * FROM events ORDER BY timestamp DESC LIMIT ?", (limit,))
            rows = [dict(r) for r in c.fetchall()]
            conn.close()
            return rows

    def get_stats(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM events")
            total = c.fetchone()[0]
            c.execute("SELECT threat_level, COUNT(*) FROM events GROUP BY threat_level")
            by_level = dict(c.fetchall())
            c.execute("SELECT COUNT(*) FROM tracks")
            total_tracks = c.fetchone()[0]
            conn.close()
            return {"total_events": total, "by_level": by_level, "total_tracks": total_tracks}
