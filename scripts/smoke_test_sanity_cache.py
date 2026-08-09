"""Smoke test for core/sanity.py and core/cache.py. No LLM calls needed --
just hand-crafted SQL to exercise the heuristics, and cache get/put/hit."""
from askwarehouse.execution.sandbox import execute
from askwarehouse.core.sanity import run_sanity_checks
from askwarehouse.core.cache import SQLCache

print("=== sanity checks ===")

# 1. deliberate fan-out double-count: SUMs fact_orders.order_total after
# joining down to fact_order_items (order-item grain) -- classic silent bug.
bad_sql = """
SELECT c.customer_id, SUM(o.order_total) AS total
FROM main_marts.dim_customers c
JOIN main_marts.fact_orders o ON c.customer_id = o.customer_id
JOIN main_marts.fact_order_items oi ON o.order_id = oi.order_id
GROUP BY c.customer_id
LIMIT 5
"""
res = execute(bad_sql)
print("bad_sql rows:", res.row_count, "success:", res.success)
for f in run_sanity_checks(bad_sql, res):
    print(f" [{f.severity}] {f.code}: {f.message}")

# 2. empty result (impossible filter)
empty_sql = "SELECT * FROM main_marts.dim_customers WHERE state_code = 'ZZ' LIMIT 10"
res2 = execute(empty_sql)
print()
print("empty_sql rows:", res2.row_count, "success:", res2.success)
for f in run_sanity_checks(empty_sql, res2):
    print(f" [{f.severity}] {f.code}: {f.message}")

# 3. clean query, aggregated correctly at fact_orders grain -- should have no findings
good_sql = """
SELECT c.customer_id, SUM(o.order_total) AS total
FROM main_marts.dim_customers c
JOIN main_marts.fact_orders o ON c.customer_id = o.customer_id
GROUP BY c.customer_id
LIMIT 5
"""
res3 = execute(good_sql)
print()
print("good_sql rows:", res3.row_count, "success:", res3.success)
findings3 = run_sanity_checks(good_sql, res3)
print("findings:", findings3 if findings3 else "(none, as expected)")

print()
print("=== cache ===")
cache = SQLCache()
q = "smoke test question: total revenue by region"
print("get (should be miss):", cache.get(q))
cache.put(q, "SELECT region, SUM(revenue) FROM main_semantic.metric_daily_revenue GROUP BY 1")
hit = cache.get(q)
print("get (should be hit):", hit)
print("schema_version:", cache.schema_version())
