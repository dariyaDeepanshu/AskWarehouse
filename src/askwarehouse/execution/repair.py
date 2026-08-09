"""The repair loop: guard -> execute -> on DB error, feed the exact error
text + failed SQL back to the model, capped at max_repair_attempts. Every
attempt (guard rejection, DB error, or success) is audit-logged and returned
in the attempt list, which is what the eval harness uses to compute the
marginal-value-of-each-retry curve."""
import uuid
from dataclasses import dataclass, field

from askwarehouse.execution.audit import AuditLogger, AuditRecord, timed
from askwarehouse.execution.connection import readonly_connection
from askwarehouse.execution.sandbox import execute, ExecutionResult
from askwarehouse.safety.config import SafetyConfig, DEFAULT_SAFETY_CONFIG
from askwarehouse.safety.guards import static_check, explain_cost_check
from askwarehouse.sql.generate import SQLGenerator


@dataclass
class AttemptRecord:
    attempt_number: int
    sql: str
    stage: str          # 'guard_rejected' | 'db_error' | 'timeout' | 'success'
    outcome: str
    error: str | None = None
    latency_ms: float = 0.0


@dataclass
class RepairRunResult:
    final: ExecutionResult | None
    final_sql: str
    attempts: list = field(default_factory=list)  # list[AttemptRecord]
    succeeded: bool = False
    attempts_used: int = 0


def run_with_repair(question: str, initial_sql: str, schema_context: str,
                     known_tables: set[str], generator: SQLGenerator,
                     config: SafetyConfig = DEFAULT_SAFETY_CONFIG,
                     audit: AuditLogger | None = None,
                     session_id: str | None = None) -> RepairRunResult:
    audit = audit or AuditLogger(config)
    session_id = session_id or str(uuid.uuid4())
    attempts: list[AttemptRecord] = []
    sql = initial_sql

    for attempt_n in range(1, config.max_repair_attempts + 1):
        guard = static_check(sql, known_tables, dialect=generator.dialect, config=config)
        if not guard.allowed:
            attempts.append(AttemptRecord(attempt_n, sql, "guard_rejected", "guard_rejected", guard.reason))
            audit.log(AuditRecord(session_id, question, sql, attempt_n, "guard_rejected",
                                   "guard_rejected", 0.0, error_message=guard.reason))
            if attempt_n == config.max_repair_attempts:
                break
            repaired = generator.repair(question, schema_context, sql, f"Query rejected by safety guard: {guard.reason}")
            sql = repaired.sql
            continue

        sql = guard.sql  # guard-normalized (LIMIT injected/clamped)

        with readonly_connection(config) as con:
            cost = explain_cost_check(con, sql, config)
        if not cost.allowed:
            stage = "guard_rejected" if cost.kind == "policy" else "execute"
            outcome = "guard_rejected" if cost.kind == "policy" else "db_error"
            attempts.append(AttemptRecord(attempt_n, sql, stage, outcome, cost.reason))
            audit.log(AuditRecord(session_id, question, sql, attempt_n, stage, outcome,
                                   0.0, error_message=cost.reason))
            if attempt_n == config.max_repair_attempts:
                break
            repair_msg = cost.reason if cost.kind == "invalid_sql" else f"Query rejected by safety guard: {cost.reason}"
            repaired = generator.repair(question, schema_context, sql, repair_msg)
            sql = repaired.sql
            continue

        with timed() as box:
            result = execute(sql, config)
        box_latency = box.get("latency_ms", result.latency_ms)

        if result.success:
            attempts.append(AttemptRecord(attempt_n, sql, "execute", "success", None, result.latency_ms))
            audit.log(AuditRecord(session_id, question, sql, attempt_n, "execute", "success",
                                   result.latency_ms, row_count=result.row_count))
            return RepairRunResult(final=result, final_sql=sql, attempts=attempts,
                                    succeeded=True, attempts_used=attempt_n)

        outcome = "timeout" if result.timed_out else "db_error"
        attempts.append(AttemptRecord(attempt_n, sql, "execute", outcome, result.error, result.latency_ms))
        audit.log(AuditRecord(session_id, question, sql, attempt_n, "execute", outcome,
                               result.latency_ms, error_message=result.error))

        if attempt_n == config.max_repair_attempts:
            return RepairRunResult(final=result, final_sql=sql, attempts=attempts,
                                    succeeded=False, attempts_used=attempt_n)

        repaired = generator.repair(question, schema_context, sql, result.error or "unknown error")
        sql = repaired.sql

    return RepairRunResult(final=None, final_sql=sql, attempts=attempts,
                            succeeded=False, attempts_used=len(attempts))
