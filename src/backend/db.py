"""SQLite 연결 및 초기화."""

import sqlite3

from backend.config import get_settings


def get_connection() -> sqlite3.Connection:
    settings = get_settings()
    settings.db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_spans_workflow_id(conn: sqlite3.Connection) -> None:
    """예전 DB 에 workflow_id 컬럼 추가. 기존 trace 는 trace 마다 legacy 워크플로우로 묶음."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(spans)")}
    if "workflow_id" not in cols:
        conn.execute("ALTER TABLE spans ADD COLUMN workflow_id TEXT")
        conn.execute("UPDATE spans SET workflow_id = 'legacy-' || trace_id")
        conn.execute(
            """INSERT OR IGNORE INTO workflows (id, name, status, started_at, ended_at)
               SELECT workflow_id, 'legacy', status, started_at, ended_at
               FROM spans WHERE parent_id IS NULL"""
        )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_spans_workflow ON spans (workflow_id)")


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

            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY,          -- {이름}-{YYYYMMDD-HHMMSS}-{난수}
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                input TEXT,
                output TEXT,
                attributes TEXT,
                error_type TEXT,
                error_message TEXT,
                traceback TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_workflows_started ON workflows (started_at);
            """
        )
        _migrate_spans_workflow_id(conn)
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
