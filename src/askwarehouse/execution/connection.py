"""Read-only connection to the analytical warehouse, kept physically
separate from the writable audit database (see audit.py) so the two can
never share a connection or a write path."""
import duckdb
from contextlib import contextmanager

from askwarehouse.safety.config import SafetyConfig, DEFAULT_SAFETY_CONFIG


@contextmanager
def readonly_connection(config: SafetyConfig = DEFAULT_SAFETY_CONFIG):
    """Yields a DuckDB connection opened read_only=True. Any INSERT/UPDATE/
    DELETE/CREATE/DROP/COPY raises here, at the storage engine, independent
    of the AST-level guard in safety/guards.py."""
    con = duckdb.connect(config.warehouse_path, read_only=True)
    try:
        yield con
    finally:
        con.close()


def assert_connection_is_readonly(config: SafetyConfig = DEFAULT_SAFETY_CONFIG) -> None:
    """Smoke test used at startup / in CI: proves the read-only guarantee is
    real by attempting a write and confirming DuckDB rejects it."""
    with readonly_connection(config) as con:
        try:
            con.execute("CREATE TABLE __should_fail__ (x INT)")
        except duckdb.Error:
            return
    raise RuntimeError(
        "SAFETY REGRESSION: write succeeded against a read_only=True connection"
    )
