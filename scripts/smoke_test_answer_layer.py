"""Smoke test for core/chart.py, core/nl_answer.py, core/verify.py."""
from askwarehouse.providers.local import LocalProvider
from askwarehouse.core.agent import AskWarehouseAgent
from askwarehouse.core.pipeline_config import PipelineConfig
from askwarehouse.core.chart import render_chart
from askwarehouse.core.nl_answer import generate_nl_answer
from askwarehouse.core.verify import verify

provider = LocalProvider()
agent = AskWarehouseAgent(provider, dialect="duckdb", pipeline_config=PipelineConfig())

question = "What is the total revenue by region?"
resp = agent.ask(question)
print("SQL:", resp.sql)
print("rows:", resp.result.rows)

chart = render_chart(resp.result.columns, resp.result.rows, title=question)
print("chart kind:", chart.kind, "| png bytes:", len(chart.png_base64) if chart.png_base64 else None)

answer = generate_nl_answer(provider, question, resp.result.columns, resp.result.rows)
print("NL answer:", answer)

print()
print("=== verify ===")
v = verify(agent, question, resp.sql, resp.result.columns, resp.result.rows)
print("paraphrased question:", v.verify_question)
print("verify_sql:", v.verify_sql)
print("match:", v.match, "|", v.detail)
print("original_summary:", v.original_summary)
print("verify_summary:", v.verify_summary)
