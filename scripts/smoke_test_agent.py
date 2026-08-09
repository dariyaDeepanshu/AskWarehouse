"""Smoke test for the full orchestrator (core/agent.py)."""
from askwarehouse.providers.local import LocalProvider
from askwarehouse.core.agent import AskWarehouseAgent
from askwarehouse.core.pipeline_config import PipelineConfig

provider = LocalProvider()
agent = AskWarehouseAgent(provider, dialect="duckdb", pipeline_config=PipelineConfig())

questions = [
    "How many completed orders were there in California in 2025?",
    "What is the total revenue by region?",
    "Who are the top 5 customers by lifetime revenue?",
]

for q in questions:
    print("=" * 80)
    print("Q:", q)
    resp = agent.ask(q)
    print("status:", resp.status, "cache_hit:", resp.cache_hit, "llm_calls:", resp.llm_calls,
          "latency_ms:", round(resp.total_latency_ms))
    print("sql:", resp.sql)
    if resp.result:
        print("success:", resp.result.success, "row_count:", resp.result.row_count,
              "rows[:3]:", resp.result.rows[:3] if resp.result.rows else None)
    if resp.clarifying_question:
        print("clarifying_question:", resp.clarifying_question)
    for f in resp.sanity_findings:
        print(f" [{f.severity}] {f.code}: {f.message}")

print("=" * 80)
print("re-asking first question (should be a cache hit this time)")
resp = agent.ask(questions[0])
print("status:", resp.status, "cache_hit:", resp.cache_hit, "llm_calls:", resp.llm_calls)
