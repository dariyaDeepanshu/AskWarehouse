"""Question -> SQL fingerprint cache. The fingerprint is a hash of the
normalized question AND a live-computed schema-version hash, so a dbt
migration (a column renamed, a table added/dropped) invalidates every
existing cache entry automatically -- old fingerprints simply stop matching
new lookups, with no explicit invalidation step required."""
import hashlib
import os
from dataclasses import dataclass

import duckdb

from askwarehouse.execution.connection import readonly_connection
from askwarehouse.safety.config import SafetyConfig, DEFAULT_SAFETY_CONFIG

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sql_cache (
    fingerprint VARCHAR PRIMARY KEY,
    question VARCHAR,
    schema_version VARCHAR,
    sql_text VARCHAR,
    created_at TIMESTAMP DEFAULT current_timestamp,
    hit_count INTEGER DEFAULT 0
);
"""


@dataclass
class CacheEntry:
    sql_text: str
    schema_version: str


def _normalize(question: str) -> str:
    return " ".join(question.strip().lower().split())


class SQLCache:
    def __init__(self, config: SafetyConfig = DEFAULT_SAFETY_CONFIG):
        self.config = config
        os.makedirs(os.path.dirname(config.cache_db_path), exist_ok=True)
        con = duckdb.connect(config.cache_db_path)
        con.execute(_SCHEMA_SQL)
        con.close()

    def schema_version(self) -> str:
        with readonly_connection(self.config) as con:
            rows = con.execute(
                """SELECT table_schema, table_name, column_name, data_type
                   FROM information_schema.columns
                   WHERE table_schema = ANY(?)
                   ORDER BY 1, 2, 3""",
                [list(self.config.allowed_schemas)],
            ).fetchall()
        digest = hashlib.sha256(repr(rows).encode()).hexdigest()[:16]
        return digest

    def _fingerprint(self, question: str, schema_version: str) -> str:
        return hashlib.sha256(f"{_normalize(question)}::{schema_version}".encode()).hexdigest()

    def get(self, question: str) -> CacheEntry | None:
        schema_version = self.schema_version()
        fp = self._fingerprint(question, schema_version)
        con = duckdb.connect(self.config.cache_db_path)
        try:
            row = con.execute(
                "SELECT sql_text FROM sql_cache WHERE fingerprint = ?", [fp]
            ).fetchone()
            if row is None:
                return None
            con.execute("UPDATE sql_cache SET hit_count = hit_count + 1 WHERE fingerprint = ?", [fp])
            return CacheEntry(sql_text=row[0], schema_version=schema_version)
        finally:
            con.close()

    def put(self, question: str, sql_text: str) -> None:
        schema_version = self.schema_version()
        fp = self._fingerprint(question, schema_version)
        con = duckdb.connect(self.config.cache_db_path)
        try:
            con.execute(
                """INSERT INTO sql_cache (fingerprint, question, schema_version, sql_text)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT (fingerprint) DO UPDATE SET sql_text = excluded.sql_text""",
                [fp, question, schema_version, sql_text],
            )
        finally:
            con.close()
