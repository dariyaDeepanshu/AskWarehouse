"""Runs a single, already-guard-passed SQL statement against the read-only
warehouse connection with a wall-clock timeout. Uses DuckDB's own
interrupt() from a watchdog timer thread -- the documented way to bound a
DuckDB query's runtime from Python, since the client call is otherwise
synchronous and blocking."""
import threading
import time
from dataclasses import dataclass

import duckdb

from askwarehouse.execution.connection import readonly_connection
from askwarehouse.safety.config import SafetyConfig, DEFAULT_SAFETY_CONFIG


@dataclass
class ExecutionResult:
    success: bool
    row_count: int = 0
    columns: list | None = None
    rows: list | None = None  # list of tuples, capped by MAX_ROWS via the guard's LIMIT
    latency_ms: float = 0.0
    error: str | None = None
    timed_out: bool = False


def execute(sql: str, config: SafetyConfig = DEFAULT_SAFETY_CONFIG) -> ExecutionResult:
    with readonly_connection(config) as con:
        timer = threading.Timer(config.statement_timeout_seconds, con.interrupt)
        timer.start()
        t0 = time.perf_counter()
        try:
            cursor = con.execute(sql)
            rows = cursor.fetchall()
            columns = [d[0] for d in cursor.description]
            latency_ms = (time.perf_counter() - t0) * 1000
            return ExecutionResult(
                success=True, row_count=len(rows), columns=columns, rows=rows,
                latency_ms=latency_ms,
            )
        except duckdb.InterruptException:
            latency_ms = (time.perf_counter() - t0) * 1000
            return ExecutionResult(
                success=False, latency_ms=latency_ms, timed_out=True,
                error=f"statement exceeded {config.statement_timeout_seconds}s timeout and was interrupted",
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - t0) * 1000
            return ExecutionResult(success=False, latency_ms=latency_ms, error=str(e))
        finally:
            timer.cancel()
