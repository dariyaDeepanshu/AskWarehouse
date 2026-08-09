"""Smoke test for the repair loop (execution/repair.py): feeds it a
deliberately broken query (typo'd column name) and checks that the exact
DB error text gets fed back to the model and the query gets fixed."""
from askwarehouse.providers.local import LocalProvider
from askwarehouse.sql.generate import SQLGenerator
from askwarehouse.execution.repair import run_with_repair
from askwarehouse.retrieval.catalog import build_catalog
from askwarehouse.retrieval.schema_index import SchemaIndex

provider = LocalProvider()
gen = SQLGenerator(provider, dialect="duckdb")
known = {t.name.lower() for t in build_catalog()} | {"us_states"}
si = SchemaIndex()

question = "How many customers are in California?"
schema_ctx = si.render_prompt_schema(question, top_k=3)

broken_sql = "SELECT COUNT(*) FROM main_marts.dim_customers WHERE state_cod = 'CA'"
res = run_with_repair(question, broken_sql, schema_ctx, known, gen)

print("=== broken SQL test ===")
print("succeeded:", res.succeeded, "attempts_used:", res.attempts_used)
for a in res.attempts:
    print(" ", a.attempt_number, a.stage, a.outcome, (a.error or "")[:80])
print("final_sql:", res.final_sql)
if res.final:
    print("rows:", res.final.rows)
