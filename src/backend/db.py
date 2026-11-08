"""SQLite 연결 및 초기화."""

import sqlite3

from backend.config import get_settings


def get_connection() -> sqlite3.Connection:
    settings = get_settings()
    settings.db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("PRAGMA journal_mode=WAL")  # 기록 중에도 trace 화면에서 읽을 수 있게
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS spans (
                id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                parent_id TEXT,
                kind TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                duration_ms INTEGER,
                input TEXT,
                output TEXT,
                attributes TEXT,
                error_type TEXT,
                error_message TEXT,
                traceback TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans (trace_id);
            CREATE INDEX IF NOT EXISTS idx_spans_root ON spans (parent_id, started_at);
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
