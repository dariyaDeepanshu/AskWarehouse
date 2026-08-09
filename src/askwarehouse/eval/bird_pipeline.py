"""BIRD-specific execution + repair loop (SQLite, not DuckDB) and the
ablation-ready question-answering pipeline used by the eval runner. Reuses
the same safety guard (safety/guards.static_check, dialect-parameterized)
and the same SQLGenerator/provider used everywhere else -- only the
execution engine differs, because BIRD's target databases are SQLite files,
not our DuckDB warehouse. The EXPLAIN-based cost guard is DuckDB-specific
(it parses DuckDB's own plan-text format) and BIRD's databases are a few MB
each, so it's skipped here; the statement timeout is the cost backstop."""
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field

from askwarehouse.safety.guards import static_check
from askwarehouse.sql.generate import SQLGenerator

STATEMENT_TIMEOUT_SECONDS = 12
MAX_REPAIR_ATTEMPTS_DEFAULT = 3


@dataclass
class SqliteExecResult:
    success: bool
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    error: str | None = None
    timed_out: bool = False
    latency_ms: float = 0.0


def execute_sqlite_readonly(db_path: str, sql: str, timeout_seconds: int = STATEMENT_TIMEOUT_SECONDS) -> SqliteExecResult:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    timer = threading.Timer(timeout_seconds, con.interrupt)
    timer.start()
    t0 = time.perf_counter()
    try:
        cur = con.execute(sql)
        rows = cur.fetchall()
        columns = [d[0] for d in cur.description] if cur.description else []
        return SqliteExecResult(success=True, columns=columns, rows=rows,
                                 latency_ms=(time.perf_counter() - t0) * 1000)
    except sqlite3.OperationalError as e:
        timed_out = "interrupted" in str(e).lower()
        return SqliteExecResult(success=False, error=str(e), timed_out=timed_out,
                                 latency_ms=(time.perf_counter() - t0) * 1000)
    except Exception as e:
        return SqliteExecResult(success=False, error=str(e),
                                 latency_ms=(time.perf_counter() - t0) * 1000)
    finally:
        timer.cancel()
        con.close()


@dataclass
class AttemptRecord:
    attempt_number: int
    sql: str
    outcome: str  # 'guard_rejected' | 'db_error' | 'timeout' | 'success'
    error: str | None = None


@dataclass
class PipelineResult:
    question_id: int
    db_id: str
    question: str
    difficulty: str
    final_sql: str
    exec_result: SqliteExecResult | None
    attempts: list  # list[AttemptRecord]
    valid_sql: bool          # did *any* attempt execute successfully (regardless of correctness)
    exec_correct: bool | None  # None until scored against gold
    total_latency_ms: float
    llm_calls: int
    schema_context_chars: int


def run_bird_question(question: str, evidence: str, db_id: str, db_path: str, question_id: int,
                       difficulty: str, known_tables: set, schema_context: str, value_hints: str,
                       generator: SQLGenerator, use_self_critique: bool, use_repair_loop: bool,
                       max_repair_attempts: int = MAX_REPAIR_ATTEMPTS_DEFAULT) -> PipelineResult:
    t0 = time.perf_counter()
    llm_calls = 0
    full_question = question + (f"\n\nExternal knowledge: {evidence}" if evidence else "")

    gen = generator.generate(full_question, schema_context, value_hints, plan_text="")
    llm_calls += 1
    sql = gen.sql

    if use_self_critique:
        crit = generator.critique(full_question, schema_context, value_hints, "", sql)
        llm_calls += 1
        sql = crit.sql

    attempts: list[AttemptRecord] = []
    max_attempts = max_repair_attempts if use_repair_loop else 1
    final_result = None

    for attempt_n in range(1, max_attempts + 1):
        guard = static_check(sql, known_tables, dialect="sqlite")
        if not guard.allowed:
            attempts.append(AttemptRecord(attempt_n, sql, "guard_rejected", guard.reason))
            if attempt_n == max_attempts:
                break
            repaired = generator.repair(full_question, schema_context, sql, f"Query rejected: {guard.reason}")
            llm_calls += 1
            sql = repaired.sql
            continue

        sql = guard.sql
        result = execute_sqlite_readonly(db_path, sql)
        if result.success:
            attempts.append(AttemptRecord(attempt_n, sql, "success"))
            final_result = result
            break

        outcome = "timeout" if result.timed_out else "db_error"
        attempts.append(AttemptRecord(attempt_n, sql, outcome, result.error))
        final_result = result
        if attempt_n == max_attempts:
            break
        repaired = generator.repair(full_question, schema_context, sql, result.error or "unknown error")
        llm_calls += 1
        sql = repaired.sql

    valid_sql = any(a.outcome == "success" for a in attempts)
    return PipelineResult(
        question_id=question_id, db_id=db_id, question=question, difficulty=difficulty,
        final_sql=sql, exec_result=final_result, attempts=attempts, valid_sql=valid_sql,
        exec_correct=None, total_latency_ms=(time.perf_counter() - t0) * 1000,
        llm_calls=llm_calls, schema_context_chars=len(schema_context),
    )


def _normalize_cell(v):
    if isinstance(v, float):
        return round(v, 3)
    if isinstance(v, str):
        return v.strip().lower()
    return v


def results_match(pred_rows: list, gold_rows: list) -> bool:
    """Standard BIRD/Spider execution-accuracy comparison: result sets as
    order-independent, column-order-independent bags of normalized tuples."""
    if pred_rows is None:
        return False

    def as_multiset(rows):
        out = {}
        for r in rows:
            key = tuple(sorted((_normalize_cell(v) for v in r), key=lambda x: str(type(x)) + str(x)))
            out[key] = out.get(key, 0) + 1
        return out

    return as_multiset(pred_rows) == as_multiset(gold_rows)
