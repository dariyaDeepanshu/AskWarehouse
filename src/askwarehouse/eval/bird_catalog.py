"""Builds a TableInfo catalog (the same dataclass core/retrieval uses for
the hero warehouse) for an arbitrary BIRD SQLite database, by introspecting
sqlite_master/PRAGMA directly. BIRD databases ship with no dbt-style
descriptions -- this is deliberately the "no curated metadata" condition:
retrieval and generation only have column names, types, and sample values
to work with, which is a harder and more realistic test of schema linking
than our own hand-documented warehouse."""
import sqlite3

from askwarehouse.retrieval.catalog import TableInfo, ColumnInfo

MAX_CARDINALITY_FOR_SAMPLES = 200
SAMPLE_VALUES_PER_COLUMN = 6


def _ro_connect(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def build_bird_catalog(db_path: str) -> list:
    con = _ro_connect(db_path)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]

        out = []
        for table in tables:
            col_rows = con.execute(f'PRAGMA table_info("{table}")').fetchall()
            columns = []
            for _cid, col_name, data_type, _notnull, _default, _pk in col_rows:
                samples = []
                if (data_type or "").upper() in ("TEXT", "VARCHAR", "CHAR", ""):
                    try:
                        n_distinct = con.execute(
                            f'SELECT COUNT(DISTINCT "{col_name}") FROM "{table}"'
                        ).fetchone()[0]
                        if n_distinct and n_distinct <= MAX_CARDINALITY_FOR_SAMPLES:
                            samples = [
                                r[0] for r in con.execute(
                                    f'SELECT DISTINCT "{col_name}" FROM "{table}" '
                                    f'WHERE "{col_name}" IS NOT NULL LIMIT {SAMPLE_VALUES_PER_COLUMN}'
                                ).fetchall()
                            ]
                    except sqlite3.Error:
                        pass
                columns.append(ColumnInfo(
                    name=col_name, data_type=data_type or "TEXT", description="",
                    sample_values=samples,
                ))
            out.append(TableInfo(schema="main", name=table, description="", columns=columns))
        return out
    finally:
        con.close()
