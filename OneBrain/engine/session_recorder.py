"""
OneBrain — Session Recording System
Records frequency + brain response data to SQLite for analysis.
"""

import sqlite3
import uuid
import time
import json
import csv
import os
from datetime import datetime
from typing import Optional, Dict, List

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sessions.db")


class SessionRecorder:
    def __init__(self, db_path: str = DB_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

        self.session_id: Optional[str] = None
        self.start_time: Optional[float] = None

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                start_time REAL,
                end_time REAL,
                user_id TEXT DEFAULT 'default',
                device_type TEXT DEFAULT 'tgam',
                notes TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                timestamp REAL,
                frequency_hz REAL,
                frequency_type TEXT,
                volume_db REAL,
                raw_eeg INTEGER,
                attention INTEGER,
                meditation INTEGER,
                signal_quality INTEGER,
                delta INTEGER, theta INTEGER,
                low_alpha INTEGER, high_alpha INTEGER,
                low_beta INTEGER, high_beta INTEGER,
                low_gamma INTEGER, mid_gamma INTEGER,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            );

            CREATE INDEX IF NOT EXISTS idx_samples_session ON samples(session_id);
            CREATE INDEX IF NOT EXISTS idx_samples_freq ON samples(frequency_hz);
        """)
        self.conn.commit()

    def start_session(self, user_id: str = "default", device_type: str = "tgam", notes: str = "") -> str:
        self.session_id = str(uuid.uuid4())[:8]
        self.start_time = time.time()
        self.conn.execute(
            "INSERT INTO sessions (session_id, start_time, user_id, device_type, notes) VALUES (?, ?, ?, ?, ?)",
            (self.session_id, self.start_time, user_id, device_type, notes)
        )
        self.conn.commit()
        print(f"Session started: {self.session_id}")
        return self.session_id

    def record_sample(self, frequency_hz: float = 0, frequency_type: str = "none",
                      volume_db: float = 0, raw_eeg: int = 0, attention: int = 0,
                      meditation: int = 0, signal_quality: int = 200,
                      bands: Optional[Dict[str, int]] = None):
        if not self.session_id:
            return

        b = bands or {}
        self.conn.execute(
            """INSERT INTO samples (session_id, timestamp, frequency_hz, frequency_type,
               volume_db, raw_eeg, attention, meditation, signal_quality,
               delta, theta, low_alpha, high_alpha, low_beta, high_beta, low_gamma, mid_gamma)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (self.session_id, time.time(), frequency_hz, frequency_type,
             volume_db, raw_eeg, attention, meditation, signal_quality,
             b.get("delta", 0), b.get("theta", 0),
             b.get("low_alpha", 0), b.get("high_alpha", 0),
             b.get("low_beta", 0), b.get("high_beta", 0),
             b.get("low_gamma", 0), b.get("mid_gamma", 0))
        )

    def end_session(self):
        if self.session_id:
            self.conn.execute(
                "UPDATE sessions SET end_time = ? WHERE session_id = ?",
                (time.time(), self.session_id)
            )
            self.conn.commit()
            print(f"Session ended: {self.session_id}")
            self.session_id = None

    def analyze_best_frequency(self, metric: str = "attention") -> List[Dict]:
        """Find which frequency produces highest average of a given metric."""
        if metric not in ("attention", "meditation"):
            raise ValueError("metric must be 'attention' or 'meditation'")

        rows = self.conn.execute(f"""
            SELECT frequency_hz, frequency_type,
                   AVG({metric}) as avg_val,
                   COUNT(*) as sample_count
            FROM samples
            WHERE frequency_hz > 0 AND signal_quality < 50
            GROUP BY frequency_hz, frequency_type
            HAVING sample_count > 10
            ORDER BY avg_val DESC
            LIMIT 10
        """).fetchall()

        results = []
        for r in rows:
            results.append({
                "frequency_hz": r["frequency_hz"],
                "frequency_type": r["frequency_type"],
                f"avg_{metric}": round(r["avg_val"], 1),
                "samples": r["sample_count"],
            })
        return results

    def export_csv(self, session_id: str, filepath: str):
        rows = self.conn.execute(
            "SELECT * FROM samples WHERE session_id = ? ORDER BY timestamp", (session_id,)
        ).fetchall()

        with open(filepath, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([desc[0] for desc in self.conn.execute("SELECT * FROM samples LIMIT 0").description])
            for row in rows:
                writer.writerow(tuple(row))
        print(f"Exported {len(rows)} samples to {filepath}")

    def export_json(self, session_id: str, filepath: str):
        rows = self.conn.execute(
            "SELECT * FROM samples WHERE session_id = ? ORDER BY timestamp", (session_id,)
        ).fetchall()

        data = [dict(row) for row in rows]
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Exported {len(data)} samples to {filepath}")

    def get_sessions(self) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT * FROM sessions ORDER BY start_time DESC LIMIT 20"
        ).fetchall()
        return [dict(r) for r in rows]

    def flush(self):
        self.conn.commit()


if __name__ == "__main__":
    print("OneBrain Session Recorder — Test")
    rec = SessionRecorder()
    sid = rec.start_session(notes="test session")
    for i in range(20):
        rec.record_sample(frequency_hz=10.0, frequency_type="binaural",
                          attention=50 + i, meditation=40 + i,
                          signal_quality=0)
    rec.flush()
    rec.end_session()
    print(f"Sessions: {rec.get_sessions()}")
    print("Done.")
