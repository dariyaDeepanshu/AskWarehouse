"""AskWarehouse HTTP API (Vercel Python serverless function).

One FastAPI app behind /api/* -- the whole text-to-SQL pipeline from the
`askwarehouse` package runs here unchanged: schema retrieval -> ambiguity
gate -> plan -> generate -> self-critique -> static sqlglot guards ->
read-only DuckDB execute -> repair loop -> sanity checks -> NL answer +
chart spec + the exact SQL.

Adaptations for serverless (no GPU, read-only bundled FS, ephemeral /tmp):
  * default LLM backend is a free hosted model (see providers/registry.py)
  * the warehouse .duckdb ships in the bundle and is copied to /tmp so
    DuckDB can open it without any read-only-FS edge cases
  * audit / cache DuckDB files live in /tmp (best-effort, per-instance)
"""
import os
import shutil
import sys
import time
import threading
import traceback

# --------------------------------------------------------------------------
# paths + env: must run before anything imports `askwarehouse`
# --------------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, "src"))

_TMP = os.environ.get("ASKWAREHOUSE_TMP", "/tmp/askwarehouse")
os.makedirs(_TMP, exist_ok=True)

_BUNDLED_DB = os.path.join(_ROOT, "data", "warehouse", "warehouse.duckdb")
_RUNTIME_DB = os.path.join(_TMP, "warehouse.duckdb")


def _ensure_warehouse() -> None:
    if os.path.exists(_RUNTIME_DB) and os.path.getsize(_RUNTIME_DB) > 0:
        return
    if os.path.exists(_BUNDLED_DB):
        shutil.copy2(_BUNDLED_DB, _RUNTIME_DB)


_ensure_warehouse()
os.environ.setdefault("ASKWAREHOUSE_WAREHOUSE_PATH", _RUNTIME_DB)
os.environ.setdefault("ASKWAREHOUSE_AUDIT_DB_PATH", os.path.join(_TMP, "audit.duckdb"))
os.environ.setdefault("ASKWAREHOUSE_CACHE_DB_PATH", os.path.join(_TMP, "cache.duckdb"))

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from askwarehouse.core.agent import AskWarehouseAgent  # noqa: E402
from askwarehouse.core.chart_spec import build_chart_spec  # noqa: E402
from askwarehouse.core.nl_answer import generate_nl_answer  # noqa: E402
from askwarehouse.core.pipeline_config import PipelineConfig  # noqa: E402
from askwarehouse.core.verify import verify as verify_answer  # noqa: E402
from askwarehouse.execution.audit import AuditLogger  # noqa: E402
from askwarehouse.providers.registry import get_provider, DEFAULT_MODELS  # noqa: E402
from askwarehouse.safety.config import DEFAULT_SAFETY_CONFIG  # noqa: E402

app = FastAPI(title="AskWarehouse API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# --------------------------------------------------------------------------
# agent cache: one AskWarehouseAgent per (pipeline config, provider identity)
# --------------------------------------------------------------------------
_agents: dict[tuple, AskWarehouseAgent] = {}
_agents_lock = threading.Lock()

# very soft per-IP rate limit, only for requests that use the shared server
# key (bring-your-own-key requests are never limited)
_RL_MAX = int(os.environ.get("ASKWAREHOUSE_RL_PER_MIN", "6"))
_rl: dict[str, list[float]] = {}
_rl_lock = threading.Lock()

SERVER_KEY_PRESENT = any(
    os.environ.get(k)
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
)


def _pc_from(body: dict) -> PipelineConfig:
    d = body.get("pipeline") or {}
    base = PipelineConfig()
    return PipelineConfig(
        use_schema_retrieval=bool(d.get("use_schema_retrieval", base.use_schema_retrieval)),
        use_value_index=bool(d.get("use_value_index", base.use_value_index)),
        use_self_critique=bool(d.get("use_self_critique", base.use_self_critique)),
        use_repair_loop=bool(d.get("use_repair_loop", base.use_repair_loop)),
        use_semantic_layer=bool(d.get("use_semantic_layer", base.use_semantic_layer)),
        use_cache=bool(d.get("use_cache", base.use_cache)),
        use_ambiguity_check=bool(d.get("use_ambiguity_check", base.use_ambiguity_check)),
    )


def _provider_from_headers(request: Request):
    """Bring-your-own-key: x-llm-provider + x-llm-key headers. Falls back to
    the server's configured provider. Returns (provider, used_byo_key)."""
    key = request.headers.get("x-llm-key") or None
    name = request.headers.get("x-llm-provider") or None
    model = request.headers.get("x-llm-model") or None
    if key:
        return get_provider(name, api_key=key, model=model), True
    if not SERVER_KEY_PRESENT:
        raise HTTPException(
            status_code=428,
            detail="This deployment has no server API key configured. Add your own "
                   "free Gemini or Groq key in Settings to run a query.",
        )
    return get_provider(name, model=model), False


def _get_agent(pc: PipelineConfig, provider) -> AskWarehouseAgent:
    ident = (
        pc.use_schema_retrieval, pc.use_value_index, pc.use_self_critique,
        pc.use_repair_loop, pc.use_semantic_layer, pc.use_cache, pc.use_ambiguity_check,
        getattr(provider, "name", "?"), getattr(provider, "model", "?"), id(provider),
    )
    with _agents_lock:
        agent = _agents.get(ident)
        if agent is None:
            agent = AskWarehouseAgent(provider, dialect="duckdb", pipeline_config=pc)
            _agents[ident] = agent
        return agent


def _rate_limit(request: Request, used_byo_key: bool) -> None:
    if used_byo_key:  # someone paying with their own key is never limited
        return
    ip = (request.headers.get("x-forwarded-for") or "unknown").split(",")[0].strip()
    now = time.time()
    with _rl_lock:
        hits = [t for t in _rl.get(ip, []) if now - t < 60]
        if len(hits) >= _RL_MAX:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit: {_RL_MAX} questions/min on the shared key. "
                       "Add your own free key in Settings to lift this.",
            )
        hits.append(now)
        _rl[ip] = hits


# --------------------------------------------------------------------------
# serialization
# --------------------------------------------------------------------------
def _result_payload(result) -> dict | None:
    if result is None:
        return None
    return {
        "success": result.success,
        "row_count": result.row_count,
        "columns": result.columns or [],
        "rows": [list(r) for r in (result.rows or [])],
        "latency_ms": result.latency_ms,
        "error": result.error,
        "timed_out": result.timed_out,
    }


def _response_payload(resp) -> dict:
    return {
        "question": resp.question,
        "status": resp.status,
        "sql": resp.sql,
        "result": _result_payload(resp.result),
        "attempts": [
            {
                "attempt_number": a.attempt_number, "sql": a.sql, "stage": a.stage,
                "outcome": a.outcome, "error": a.error, "latency_ms": a.latency_ms,
            }
            for a in resp.attempts
        ],
        "sanity_findings": [
            {"code": f.code, "severity": f.severity, "message": f.message}
            for f in resp.sanity_findings
        ],
        "clarifying_question": resp.clarifying_question,
        "ambiguity": (
            {"is_ambiguous": resp.ambiguity.is_ambiguous, "reason": resp.ambiguity.reason,
             "clarifying_question": resp.ambiguity.clarifying_question}
            if resp.ambiguity else None
        ),
        "cache_hit": resp.cache_hit,
        "schema_context": resp.schema_context,
        "value_hints": resp.value_hints,
        "plan_text": resp.plan_text,
        "total_latency_ms": resp.total_latency_ms,
        "llm_calls": resp.llm_calls,
    }


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------
class AskBody(BaseModel):
    question: str
    pipeline: dict | None = None
    session_id: str | None = None


@app.get("/api/health")
def health():
    from askwarehouse.execution.connection import assert_connection_is_readonly
    ok = True
    detail = "read_only=True enforced by DuckDB storage engine"
    try:
        assert_connection_is_readonly()
    except Exception as e:  # pragma: no cover
        ok, detail = False, str(e)
    return {"ok": ok, "readonly_enforced": ok, "detail": detail,
            "server_key_present": SERVER_KEY_PRESENT, "warehouse": _RUNTIME_DB}


@app.get("/api/config")
def config():
    return {
        "server_key_present": SERVER_KEY_PRESENT,
        "default_models": DEFAULT_MODELS,
        "rate_limit_per_min": _RL_MAX,
        "allowed_schemas": sorted(DEFAULT_SAFETY_CONFIG.allowed_schemas),
        "pii_denylist": [f"{t}.{c}" for t, c in sorted(DEFAULT_SAFETY_CONFIG.pii_denylist)],
        "max_rows": DEFAULT_SAFETY_CONFIG.max_rows,
        "statement_timeout_seconds": DEFAULT_SAFETY_CONFIG.statement_timeout_seconds,
        "max_repair_attempts": DEFAULT_SAFETY_CONFIG.max_repair_attempts,
    }


@app.get("/api/examples")
def examples():
    return {"examples": EXAMPLE_QUESTIONS}


@app.get("/api/audit")
def audit(limit: int = 20):
    try:
        rows = AuditLogger().recent(min(limit, 100))
    except Exception:
        rows = []
    for r in rows:
        if r.get("ts") is not None:
            r["ts"] = str(r["ts"])
    return {"rows": rows}


@app.post("/api/ask")
def ask(body: AskBody, request: Request):
    q = (body.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="empty question")
    if len(q) > 500:
        raise HTTPException(status_code=400, detail="question too long (500 char max)")

    provider, used_byo = _provider_from_headers(request)
    _rate_limit(request, used_byo)
    pc = _pc_from(body.model_dump())
    agent = _get_agent(pc, provider)

    try:
        resp = agent.ask(q, session_id=body.session_id)
        payload = _response_payload(resp)

        if resp.status == "answered" and resp.result is not None:
            try:
                payload["nl_answer"] = generate_nl_answer(
                    agent.provider, q, resp.result.columns, resp.result.rows
                )
            except Exception:
                payload["nl_answer"] = None
            spec = build_chart_spec(resp.result.columns, resp.result.rows)
            payload["chart"] = {
                "kind": spec.kind, "x_label": spec.x_label, "y_label": spec.y_label,
                "labels": spec.labels, "values": spec.values, "note": spec.note,
            }
        return payload
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=502, detail=f"pipeline error: {e}")


class VerifyBody(BaseModel):
    question: str
    sql: str
    columns: list
    rows: list
    pipeline: dict | None = None


@app.post("/api/verify")
def verify(body: VerifyBody, request: Request):
    provider, used_byo = _provider_from_headers(request)
    _rate_limit(request, used_byo)
    pc = _pc_from(body.model_dump())
    agent = _get_agent(pc, provider)
    try:
        v = verify_answer(agent, body.question, body.sql, body.columns,
                          [tuple(r) for r in body.rows])
        return {
            "match": v.match, "verify_question": v.verify_question, "verify_sql": v.verify_sql,
            "original_summary": v.original_summary, "verify_summary": v.verify_summary,
            "detail": v.detail,
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=502, detail=f"verify error: {e}")


EXAMPLE_QUESTIONS = [
    "How many completed orders were there in California in 2025?",
    "Who are the top 10 customers by revenue?",
    "What's our monthly revenue trend for the last 12 months?",
    "Which product categories sell the most units?",
    "What is the average order value by sales channel?",
    "How many active customers do we have (placed an order in the last 90 days)?",
    "Break down revenue by US region.",
    "Which marketing campaigns drove the most conversions?",
    "What are our best products?",
    "How did sales trend recently?",
]

# Vercel's Python runtime detects the ASGI `app` object above.
