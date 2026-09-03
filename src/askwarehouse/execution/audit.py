"""Append-only audit log of every statement that was attempted against the
warehouse, independent of what the UI ends up showing the user. Lives in its
own writable DuckDB file -- never the same connection/file as the read-only
analytical warehouse, so a bug here can't ever threaten the "read-only"
guarantee on the actual data."""
import duckdb
import time
import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional

from askwarehouse.safety.config import SafetyConfig, DEFAULT_SAFETY_CONFIG

_SCHEMA_SQL = """
CREATE SEQUENCE IF NOT EXISTS audit_seq START 1;
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGINT PRIMARY KEY DEFAULT nextval('audit_seq'),
    ts TIMESTAMP DEFAULT current_timestamp,
    session_id VARCHAR,
    user_email VARCHAR,
    question VARCHAR,
    sql_text VARCHAR,
    attempt_number INTEGER,
    stage VARCHAR,          -- 'guard_rejected' | 'execute' | 'repair'
    outcome VARCHAR,        -- 'success' | 'db_error' | 'guard_rejected' | 'timeout'
    error_message VARCHAR,
    row_count INTEGER,
    latency_ms DOUBLE
);
"""


@dataclass
class AuditRecord:
    session_id: str
    question: str
    sql_text: str
    attempt_number: int
    stage: str
    outcome: str
    latency_ms: float
    row_count: Optional[int] = None
    error_message: Optional[str] = None
    user_email: Optional[str] = None


class AuditLogger:
    # In a serverless deployment several warm instances may hold this file at
    # once and DuckDB is single-writer, so every write is best-effort: a lock
    # conflict must never break a user's answer. The per-response attempt
    # trace returned by the agent is the authoritative record; this DB is a
    # convenience aggregate.
    def __init__(self, config: SafetyConfig = DEFAULT_SAFETY_CONFIG):
        self.config = config
        try:
            os.makedirs(os.path.dirname(config.audit_db_path), exist_ok=True)
            con = duckdb.connect(config.audit_db_path)
            con.execute(_SCHEMA_SQL)
            con.close()
        except Exception:
            pass

    def log(self, record: AuditRecord) -> None:
        try:
            con = duckdb.connect(self.config.audit_db_path)
            try:
                con.execute(
                    """INSERT INTO audit_log
                       (session_id, user_email, question, sql_text, attempt_number,
                        stage, outcome, error_message, row_count, latency_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [record.session_id, record.user_email, record.question, record.sql_text,
                     record.attempt_number, record.stage, record.outcome, record.error_message,
                     record.row_count, record.latency_ms],
                )
            finally:
                con.close()
        except Exception:
            pass

    def recent(self, limit: int = 50) -> list[dict]:
        try:
            con = duckdb.connect(self.config.audit_db_path, read_only=True)
        except Exception:
            return []
        try:
            cur = con.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", [limit]
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            con.close()


@contextmanager
def timed():
    t0 = time.perf_counter()
    box = {}
    yield box
    box["latency_ms"] = (time.perf_counter() - t0) * 1000
