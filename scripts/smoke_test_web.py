"""Offline smoke test for the web deployment's non-LLM machinery:
catalog + BM25 schema retrieval + value index + guards + read-only execute +
sanity checks + chart spec. Uses a canned provider so no API key is needed.

    python scripts/smoke_test_web.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("ASKWAREHOUSE_WAREHOUSE_PATH", os.path.join(ROOT, "data", "warehouse", "warehouse.duckdb"))
os.environ.setdefault("ASKWAREHOUSE_AUDIT_DB_PATH", os.path.join(ROOT, "data", "warehouse", "_test_audit.duckdb"))
os.environ.setdefault("ASKWAREHOUSE_CACHE_DB_PATH", os.path.join(ROOT, "data", "warehouse", "_test_cache.duckdb"))

from askwarehouse.providers.base import Provider, LLMResponse
from askwarehouse.retrieval.catalog import build_catalog
from askwarehouse.retrieval.schema_index import SchemaIndex
from askwarehouse.retrieval.value_index import ValueIndex
from askwarehouse.safety.guards import static_check
from askwarehouse.execution.sandbox import execute
from askwarehouse.execution.connection import assert_connection_is_readonly
from askwarehouse.core.chart_spec import build_chart_spec
from askwarehouse.core.agent import AskWarehouseAgent
from askwarehouse.core.pipeline_config import PipelineConfig


class CannedProvider(Provider):
    name = "canned"
    model = "canned"

    def generate(self, system, user, max_tokens=800, temperature=0.0):
        # ambiguity gate -> not ambiguous
        if "ambiguity gate" in system:
            return LLMResponse(text='{"ambiguous": false, "reason": "clear", "clarifying_question": null}')
        # planner
        if "planning step" in system:
            return LLMResponse(text="GRAIN: one row. TABLES: fact_orders. JOINS: none. FILTERS: status=completed")
        # NL answer
        if "natural-language answer" in system:
            return LLMResponse(text="There were N completed orders.")
        # SQL generate / critique / repair
        return LLMResponse(text="SELECT count(*) AS completed_orders FROM main_marts.fact_orders WHERE order_status = 'completed'")


def main():
    print("1. read-only guarantee ...")
    assert_connection_is_readonly()
    print("   ok")

    print("2. catalog ...")
    cat = build_catalog()
    names = sorted(t.qualified_name for t in cat)
    print(f"   {len(cat)} tables: {names}")
    assert any("fact_orders" in n for n in names)
    assert not any(n.startswith("raw.") or "staging" in n for n in names), "leaked non-modeled schema"

    print("3. BM25 schema retrieval ...")
    idx = SchemaIndex(tables=cat)
    for q in ["top customers by revenue", "orders in California", "campaign conversions", "product categories"]:
        got = [r.table.name for r in idx.retrieve(q, top_k=4)]
        print(f"   {q!r:42} -> {got}")

    print("4. value index ...")
    vi = ValueIndex()
    for q in ["completed orders in California", "revenue from the paid_social channel", "returned orders"]:
        print(f"   {q!r:42} -> {vi.render_prompt_hints(q) or '(no hints)'}")

    print("5. guards + execute ...")
    known = {t.name.lower() for t in cat} | {"us_states"}
    good = "SELECT count(*) FROM main_marts.fact_orders WHERE order_status = 'completed'"
    g = static_check(good, known)
    assert g.allowed, g.reason
    r = execute(g.sql)
    assert r.success, r.error
    print(f"   completed orders = {r.rows[0][0]:,}")

    bad = "SELECT email FROM main_marts.dim_customers"
    assert not static_check(bad, known).allowed
    bad2 = "DROP TABLE main_marts.fact_orders"
    assert not static_check(bad2, known).allowed
    print("   PII + DDL correctly rejected")

    print("6. full agent with canned provider ...")
    agent = AskWarehouseAgent(CannedProvider(), dialect="duckdb",
                              pipeline_config=PipelineConfig(use_cache=False))
    resp = agent.ask("How many completed orders have we had?")
    print(f"   status={resp.status} sql={resp.sql!r}")
    print(f"   rows={resp.result.row_count} value={resp.result.rows[0][0]:,} llm_calls={resp.llm_calls}")
    assert resp.status == "answered"

    spec = build_chart_spec(resp.result.columns, resp.result.rows)
    print(f"   chart spec: kind={spec.kind} note={spec.note!r}")

    print("\nALL OK")


if __name__ == "__main__":
    main()
