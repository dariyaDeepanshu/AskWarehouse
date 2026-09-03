"""Exercises the FastAPI app in api/index.py end to end with a canned
provider (no API key needed): routing, request/response serialization, the
agent cache, chart spec, verify, health, config, audit.

    python scripts/smoke_test_api.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "api"))

_tmp = tempfile.mkdtemp(prefix="aw_api_test_")
os.environ["ASKWAREHOUSE_TMP"] = _tmp
os.environ["ASKWAREHOUSE_WAREHOUSE_PATH"] = os.path.join(_tmp, "warehouse.duckdb")
os.environ["ASKWAREHOUSE_AUDIT_DB_PATH"] = os.path.join(_tmp, "audit.duckdb")
os.environ["ASKWAREHOUSE_CACHE_DB_PATH"] = os.path.join(_tmp, "cache.duckdb")
os.environ["GEMINI_API_KEY"] = "test-key-not-used"  # make SERVER_KEY_PRESENT true

import shutil
shutil.copy2(os.path.join(ROOT, "data", "warehouse", "warehouse.duckdb"),
             os.environ["ASKWAREHOUSE_WAREHOUSE_PATH"])

from fastapi.testclient import TestClient
import askwarehouse.providers.registry as registry
from askwarehouse.providers.base import Provider, LLMResponse


class CannedProvider(Provider):
    name = "canned"
    model = "canned"

    def generate(self, system, user, max_tokens=800, temperature=0.0):
        if "ambiguity gate" in system:
            return LLMResponse(text='{"ambiguous": false, "reason": "clear", "clarifying_question": null}')
        if "planning step" in system:
            return LLMResponse(text="GRAIN: one row per month. TABLES: fact_orders.")
        if "natural-language answer" in system:
            return LLMResponse(text="Revenue rose steadily over the period.")
        if "Rephrase" in system:
            return LLMResponse(text="What was the completed-order count each month?")
        if "how many" in user.lower():
            return LLMResponse(text=(
                "SELECT count(*) AS completed_orders FROM main_marts.fact_orders "
                "WHERE order_status = 'completed'"
            ))
        return LLMResponse(text=(
            "SELECT date_trunc('month', order_date) AS month, "
            "round(sum(order_total)) AS revenue FROM main_marts.fact_orders "
            "WHERE order_status = 'completed' GROUP BY 1 ORDER BY 1"
        ))


registry.get_provider = lambda *a, **k: CannedProvider()

import index  # noqa: E402  (api/index.py)

client = TestClient(index.app)


def check(name, cond):
    print(f"  {'OK ' if cond else 'FAIL'} {name}")
    if not cond:
        raise SystemExit(1)


print("health"); r = client.get("/api/health"); print("  ", r.json())
check("health ok", r.json()["ok"] and r.json()["readonly_enforced"])

print("config"); r = client.get("/api/config"); j = r.json()
check("config schemas", "main_marts" in j["allowed_schemas"])
check("config pii", any("email" in p for p in j["pii_denylist"]))

print("examples"); r = client.get("/api/examples")
check("examples", len(r.json()["examples"]) >= 5)

print("ask (chart series)")
r = client.post("/api/ask", json={"question": "monthly revenue trend", "pipeline": {"use_cache": False}})
j = r.json(); print("   status", j["status"], "| rows", j["result"]["row_count"], "| chart", j["chart"]["kind"], "| llm_calls", j["llm_calls"])
check("answered", j["status"] == "answered")
check("has sql", j["sql"].lower().startswith("select"))
check("chart line", j["chart"]["kind"] == "line" and len(j["chart"]["values"]) > 1)
check("nl answer", bool(j["nl_answer"]))
check("limit injected", "limit" in j["sql"].lower())

print("ask (single value)")
r = client.post("/api/ask", json={"question": "how many completed orders", "pipeline": {"use_cache": False}})
j2 = r.json(); print("   ", j2["status"], j2["chart"]["kind"], j2["result"]["rows"])
check("single_value", j2["chart"]["kind"] == "single_value")

print("verify")
r = client.post("/api/verify", json={
    "question": "monthly revenue trend", "sql": j["sql"],
    "columns": j["result"]["columns"], "rows": j["result"]["rows"],
    "pipeline": {"use_cache": False},
})
jv = r.json(); print("   ", jv)
check("verify match", jv["match"] is True)

print("byo-key required when no server key")
saved = index.SERVER_KEY_PRESENT
index.SERVER_KEY_PRESENT = False
r = client.post("/api/ask", json={"question": "x"})
check("428 without key", r.status_code == 428)
index.SERVER_KEY_PRESENT = saved

print("rate limit")
os.environ["ASKWAREHOUSE_RL_PER_MIN"] = "2"
index._RL_MAX = 2
index._rl.clear()
codes = [client.post("/api/ask", json={"question": f"q{i} completed orders", "pipeline": {"use_cache": False}},
                     headers={"x-forwarded-for": "9.9.9.9"}).status_code for i in range(4)]
print("   codes", codes)
check("429 eventually", 429 in codes)

print("\nALL OK")
