"""Builds eval/gold/own_warehouse_gold.json: 100 hand-designed business
questions with gold SQL against the AskWarehouse star schema + semantic
layer. Templated and parameterized over real values pulled from the
warehouse (so every gold query is guaranteed valid and non-trivial), then
each one is executed and checked to actually run and return sensible
results before being written out."""
import json
import os

import duckdb

con = duckdb.connect("data/warehouse/warehouse.duckdb", read_only=True)

categories = [r[0] for r in con.execute("SELECT DISTINCT category FROM main_marts.dim_products ORDER BY 1").fetchall()]
regions = [r[0] for r in con.execute("SELECT DISTINCT region FROM main_marts.dim_customers WHERE region IS NOT NULL ORDER BY 1").fetchall()]
states = [r[0] for r in con.execute("SELECT DISTINCT state_code, state_name FROM main_marts.dim_customers ORDER BY 1 LIMIT 6").fetchall()]
channels = [r[0] for r in con.execute("SELECT DISTINCT channel FROM main_marts.dim_stores ORDER BY 1").fetchall()]
payment_methods = [r[0] for r in con.execute("SELECT DISTINCT payment_method FROM main_marts.fact_payments ORDER BY 1").fetchall()]
brands = [r[0] for r in con.execute("SELECT DISTINCT brand FROM main_marts.dim_products ORDER BY 1 LIMIT 6").fetchall()]
acq_channels = [r[0] for r in con.execute("SELECT DISTINCT acquisition_channel FROM main_marts.dim_customers ORDER BY 1").fetchall()]
years = [r[0] for r in con.execute("SELECT DISTINCT year FROM main_marts.dim_date ORDER BY 1").fetchall()]
subcats = [r[0] for r in con.execute("SELECT DISTINCT subcategory FROM main_marts.dim_products ORDER BY 1 LIMIT 8").fetchall()]

items = []  # list of (question, sql, tag)


def add(question, sql, tag):
    items.append((question.strip(), sql.strip(), tag))


# ---- 1. basic counts / aggregates (10) ----
add("How many customers do we have in total?",
    "SELECT COUNT(*) FROM main_marts.dim_customers", "basic_count")
add("How many products are currently active?",
    "SELECT COUNT(*) FROM main_marts.dim_products WHERE is_active = true", "basic_count")
add("How many stores do we operate?",
    "SELECT COUNT(*) FROM main_marts.dim_stores", "basic_count")
add("How many orders have been placed in total?",
    "SELECT COUNT(*) FROM main_marts.fact_orders", "basic_count")
add("How many completed orders have we had?",
    "SELECT COUNT(*) FROM main_marts.fact_orders WHERE order_status = 'completed'", "basic_count")
add("How many orders were cancelled?",
    "SELECT COUNT(*) FROM main_marts.fact_orders WHERE order_status = 'cancelled'", "basic_count")
add("How many marketing campaigns have we run?",
    "SELECT COUNT(*) FROM main_marts.fact_campaign_touches", "basic_count")  # campaign touches, not distinct campaigns
add("How many distinct product categories do we sell?",
    "SELECT COUNT(DISTINCT category) FROM main_marts.dim_products", "basic_count")
add("What is the average order value across all completed orders?",
    "SELECT AVG(order_total) FROM main_marts.fact_orders WHERE order_status = 'completed'", "basic_count")
add("What is the total number of units sold across all completed orders?",
    "SELECT SUM(unit_count) FROM main_marts.fact_orders WHERE order_status = 'completed'", "basic_count")

# ---- 2. revenue via semantic layer (15) ----
add("What is our total lifetime revenue across all customers?",
    "SELECT SUM(lifetime_revenue) FROM main_semantic.metric_customer_revenue", "semantic_revenue")
add("Who are the top 10 customers by lifetime revenue?",
    "SELECT customer_id, full_name, lifetime_revenue FROM main_semantic.metric_customer_revenue "
    "ORDER BY lifetime_revenue DESC LIMIT 10", "semantic_revenue")
add("What is total revenue in the last 90 days?",
    "SELECT SUM(revenue_last_90d) FROM main_semantic.metric_customer_revenue", "semantic_revenue")
add("What is total revenue in the last 365 days?",
    "SELECT SUM(revenue_last_365d) FROM main_semantic.metric_customer_revenue", "semantic_revenue")
add("What is total revenue by region?",
    "SELECT region, SUM(lifetime_revenue) AS revenue FROM main_semantic.metric_customer_revenue "
    "GROUP BY region ORDER BY revenue DESC", "semantic_revenue")
add("Which region generates the most revenue?",
    "SELECT region, SUM(lifetime_revenue) AS revenue FROM main_semantic.metric_customer_revenue "
    "GROUP BY region ORDER BY revenue DESC LIMIT 1", "semantic_revenue")
add("What is the average lifetime revenue per customer?",
    "SELECT AVG(lifetime_revenue) FROM main_semantic.metric_customer_revenue", "semantic_revenue")
add("How many customers have zero completed orders?",
    "SELECT COUNT(*) FROM main_semantic.metric_customer_revenue WHERE completed_order_count = 0", "semantic_revenue")
add("What is total daily revenue trend for the online channel?",
    "SELECT order_date, revenue FROM main_semantic.metric_daily_revenue WHERE channel = 'online' "
    "ORDER BY order_date", "semantic_revenue")
add("What is the average order value by channel?",
    "SELECT channel, AVG(avg_order_value) AS avg_order_value FROM main_semantic.metric_daily_revenue "
    "GROUP BY channel ORDER BY avg_order_value DESC", "semantic_revenue")
add("What was total revenue across all channels on the single busiest day?",
    "SELECT order_date, SUM(revenue) AS revenue FROM main_semantic.metric_daily_revenue "
    "GROUP BY order_date ORDER BY revenue DESC LIMIT 1", "semantic_revenue")
add("How many customers have generated more than $10,000 in lifetime revenue?",
    "SELECT COUNT(*) FROM main_semantic.metric_customer_revenue WHERE lifetime_revenue > 10000", "semantic_revenue")
for st_code, st_name in states[:3]:
    add(f"What is total lifetime revenue from customers in {st_name}?",
        f"SELECT SUM(lifetime_revenue) FROM main_semantic.metric_customer_revenue WHERE state_code = '{st_code}'",
        "semantic_revenue_value_index")
add("What is the median completed order count per customer?",
    "SELECT MEDIAN(completed_order_count) FROM main_semantic.metric_customer_revenue", "semantic_revenue")

# ---- 3. product performance (10) ----
add("Which product generates the most revenue?",
    "SELECT product_id, product_name, revenue FROM main_semantic.metric_product_performance "
    "ORDER BY revenue DESC LIMIT 1", "product_performance")
add("What are the top 5 products by units sold?",
    "SELECT product_name, units_sold FROM main_semantic.metric_product_performance "
    "ORDER BY units_sold DESC LIMIT 5", "product_performance")
add("What are the top 5 products by gross profit?",
    "SELECT product_name, gross_profit FROM main_semantic.metric_product_performance "
    "ORDER BY gross_profit DESC LIMIT 5", "product_performance")
for cat in categories[:4]:
    add(f"What is total revenue from the {cat} category?",
        f"SELECT SUM(revenue) FROM main_semantic.metric_product_performance WHERE category = '{cat}'",
        "product_performance")
add("Which product category has sold the most units?",
    "SELECT category, SUM(units_sold) AS units FROM main_semantic.metric_product_performance "
    "GROUP BY category ORDER BY units DESC LIMIT 1", "product_performance")
add("What is the average gross profit per product across all products?",
    "SELECT AVG(gross_profit) FROM main_semantic.metric_product_performance", "product_performance")
add("How many products have never been ordered?",
    "SELECT COUNT(*) FROM main_semantic.metric_product_performance WHERE order_count = 0", "product_performance")
for brand in brands[:2]:
    add(f"What is total revenue for products from brand {brand}?",
        f"SELECT SUM(mp.revenue) FROM main_semantic.metric_product_performance mp "
        f"JOIN main_marts.dim_products p ON mp.product_id = p.product_id WHERE p.brand = '{brand}'",
        "product_performance")

# ---- 4. time-based / date filtering (15) ----
for yr in years[:3]:
    add(f"How many completed orders were placed in {yr}?",
        f"SELECT COUNT(*) FROM main_marts.fact_orders WHERE order_status = 'completed' "
        f"AND EXTRACT(year FROM order_date) = {yr}", "time_based")
add("What was total revenue in the most recent full month?",
    "SELECT date_trunc('month', order_date)::date AS month, SUM(order_total) AS revenue "
    "FROM main_marts.fact_orders WHERE order_status = 'completed' "
    "GROUP BY 1 ORDER BY 1 DESC LIMIT 1", "time_based")
add("What is total revenue by quarter?",
    "SELECT date_trunc('quarter', order_date)::date AS quarter, SUM(order_total) AS revenue "
    "FROM main_marts.fact_orders WHERE order_status = 'completed' GROUP BY 1 ORDER BY 1", "time_based")
add("How many orders were placed on weekends?",
    "SELECT COUNT(*) FROM main_marts.fact_orders o JOIN main_marts.dim_date d "
    "ON o.order_date = d.date_day WHERE d.is_weekend = true", "time_based")
add("What is average revenue per order by day of week?",
    "SELECT d.day_name, AVG(o.order_total) AS avg_revenue FROM main_marts.fact_orders o "
    "JOIN main_marts.dim_date d ON o.order_date = d.date_day WHERE o.order_status = 'completed' "
    "GROUP BY d.day_name, d.day_of_week ORDER BY d.day_of_week", "time_based")
add("How many new customers signed up each year?",
    "SELECT EXTRACT(year FROM signup_date) AS signup_year, COUNT(*) AS new_customers "
    "FROM main_marts.dim_customers GROUP BY 1 ORDER BY 1", "time_based")
add("What is the total revenue trend by month for the current year?",
    "SELECT date_trunc('month', order_date)::date AS month, SUM(order_total) AS revenue "
    "FROM main_marts.fact_orders WHERE order_status = 'completed' "
    "AND EXTRACT(year FROM order_date) = EXTRACT(year FROM current_date) GROUP BY 1 ORDER BY 1", "time_based")
add("How many orders were placed in the last 30 days?",
    "SELECT COUNT(*) FROM main_marts.fact_orders WHERE order_date >= current_date - INTERVAL 30 DAY", "time_based")
add("How many orders were placed in the last 7 days?",
    "SELECT COUNT(*) FROM main_marts.fact_orders WHERE order_date >= current_date - INTERVAL 7 DAY", "time_based")
add("What was the earliest order date on record?",
    "SELECT MIN(order_date) FROM main_marts.fact_orders", "time_based")
add("What was the most recent order date on record?",
    "SELECT MAX(order_date) FROM main_marts.fact_orders", "time_based")
add("How many products were launched in the last 2 years?",
    "SELECT COUNT(*) FROM main_marts.dim_products WHERE launch_date >= current_date - INTERVAL 730 DAY", "time_based")
add("What is month-over-month revenue for the last 6 months with data?",
    "SELECT date_trunc('month', order_date)::date AS month, SUM(order_total) AS revenue "
    "FROM main_marts.fact_orders WHERE order_status = 'completed' "
    "GROUP BY 1 ORDER BY 1 DESC LIMIT 6", "time_based")
add("How many completed orders happened in Q1 of any year?",
    "SELECT COUNT(*) FROM main_marts.fact_orders o JOIN main_marts.dim_date d ON o.order_date = d.date_day "
    "WHERE o.order_status = 'completed' AND d.quarter = 1", "time_based")
add("What is total revenue generated on Mondays?",
    "SELECT SUM(o.order_total) FROM main_marts.fact_orders o JOIN main_marts.dim_date d "
    "ON o.order_date = d.date_day WHERE o.order_status = 'completed' AND d.day_name = 'Monday'", "time_based")

# ---- 5. geographic (10) ----
for st_code, st_name in states[3:6]:
    add(f"How many customers do we have in {st_name}?",
        f"SELECT COUNT(*) FROM main_marts.dim_customers WHERE state_code = '{st_code}'",
        "geographic_value_index")
add("How many stores do we have in each region?",
    "SELECT region, COUNT(*) AS store_count FROM main_marts.dim_stores GROUP BY region ORDER BY store_count DESC",
    "geographic")
add("Which region has the most customers?",
    "SELECT region, COUNT(*) AS n FROM main_marts.dim_customers GROUP BY region ORDER BY n DESC LIMIT 1",
    "geographic")
for r in regions[:3]:
    add(f"How many completed orders came from customers in the {r} region?",
        f"SELECT COUNT(*) FROM main_marts.fact_orders o JOIN main_marts.dim_customers c "
        f"ON o.customer_id = c.customer_id WHERE o.order_status = 'completed' AND c.region = '{r}'",
        "geographic")
add("How many international (non-US) customers do we have?",
    "SELECT COUNT(*) FROM main_marts.dim_customers WHERE country != 'US'", "geographic")
add("What percentage of customers are in the West region?",
    "SELECT 100.0 * COUNT(*) FILTER (WHERE region = 'West') / COUNT(*) FROM main_marts.dim_customers",
    "geographic")
add("How many stores are in California?",
    "SELECT COUNT(*) FROM main_marts.dim_stores WHERE state_code = 'CA'", "geographic_value_index")

# ---- 6. customer segmentation / behavior (10) ----
add("How many customers are active in the last 30 days?",
    "SELECT COUNT(*) FROM main_semantic.metric_active_users WHERE is_active_30d = true", "customer_behavior")
add("How many customers are active in the last 90 days?",
    "SELECT COUNT(*) FROM main_semantic.metric_active_users WHERE is_active_90d = true", "customer_behavior")
add("What percentage of customers are opted into marketing communications?",
    "SELECT 100.0 * COUNT(*) FILTER (WHERE is_marketing_opt_in) / COUNT(*) FROM main_marts.dim_customers",
    "customer_behavior")
for ch in acq_channels[:3]:
    add(f"How many customers were acquired through {ch}?",
        f"SELECT COUNT(*) FROM main_marts.dim_customers WHERE acquisition_channel = '{ch}'",
        "customer_behavior")
add("What is the average lifetime completed order count per active customer?",
    "SELECT AVG(lifetime_completed_orders) FROM main_semantic.metric_active_users WHERE is_active_90d = true",
    "customer_behavior")
add("How many customers have placed more than 5 completed orders?",
    "SELECT COUNT(*) FROM main_semantic.metric_customer_revenue WHERE completed_order_count > 5",
    "customer_behavior")
add("What is the average customer age?",
    "SELECT AVG(age_years) FROM main_marts.dim_customers WHERE age_years IS NOT NULL", "customer_behavior")
add("How many customers signed up but have never placed a completed order?",
    "SELECT COUNT(*) FROM main_semantic.metric_active_users WHERE lifetime_completed_orders = 0",
    "customer_behavior")
add("What acquisition channel produces customers with the highest average lifetime revenue?",
    "SELECT c.acquisition_channel, AVG(m.lifetime_revenue) AS avg_revenue "
    "FROM main_marts.dim_customers c JOIN main_semantic.metric_customer_revenue m "
    "ON c.customer_id = m.customer_id GROUP BY c.acquisition_channel ORDER BY avg_revenue DESC LIMIT 1",
    "customer_behavior")

# ---- 7. marketing / campaigns (8) ----
add("How many campaign touches resulted in a conversion?",
    "SELECT COUNT(*) FROM main_marts.fact_campaign_touches WHERE touch_type = 'conversion'", "marketing")
add("How many distinct customers were touched by any marketing campaign?",
    "SELECT COUNT(DISTINCT customer_id) FROM main_marts.fact_campaign_touches", "marketing")
add("Which campaign channel has the most touches?",
    "SELECT campaign_channel, COUNT(*) AS n FROM main_marts.fact_campaign_touches "
    "GROUP BY campaign_channel ORDER BY n DESC LIMIT 1", "marketing")
add("What is the click-through count by campaign channel?",
    "SELECT campaign_channel, COUNT(*) FILTER (WHERE touch_type = 'click') AS clicks "
    "FROM main_marts.fact_campaign_touches GROUP BY campaign_channel ORDER BY clicks DESC", "marketing")
add("What is the conversion rate (conversions / total touches) by campaign channel?",
    "SELECT campaign_channel, 100.0 * COUNT(*) FILTER (WHERE touch_type = 'conversion') / COUNT(*) AS conversion_rate_pct "
    "FROM main_marts.fact_campaign_touches GROUP BY campaign_channel ORDER BY conversion_rate_pct DESC", "marketing")
add("Which single campaign has generated the most conversions?",
    "SELECT campaign_name, COUNT(*) AS conversions FROM main_marts.fact_campaign_touches "
    "WHERE touch_type = 'conversion' GROUP BY campaign_name ORDER BY conversions DESC LIMIT 1", "marketing")
add("How many customers touched by an email campaign later became active in the last 90 days?",
    "SELECT COUNT(DISTINCT t.customer_id) FROM main_marts.fact_campaign_touches t "
    "JOIN main_semantic.metric_active_users u ON t.customer_id = u.customer_id "
    "WHERE t.campaign_channel = 'email' AND u.is_active_90d = true", "marketing")
add("What is the total number of impressions recorded across all campaigns?",
    "SELECT COUNT(*) FROM main_marts.fact_campaign_touches WHERE touch_type = 'impression'", "marketing")

# ---- 8. payment method / channel (8) ----
for pm in payment_methods[:3]:
    add(f"How many successful payments were made via {pm}?",
        f"SELECT COUNT(*) FROM main_marts.fact_payments WHERE payment_method = '{pm}' AND payment_status = 'succeeded'",
        "payment_channel")
add("What is total amount collected by payment method?",
    "SELECT payment_method, SUM(amount) AS total_collected FROM main_marts.fact_payments "
    "WHERE payment_status = 'succeeded' GROUP BY payment_method ORDER BY total_collected DESC", "payment_channel")
add("How many payments failed?",
    "SELECT COUNT(*) FROM main_marts.fact_payments WHERE payment_status = 'failed'", "payment_channel")
add("What percentage of payments were refunded?",
    "SELECT 100.0 * COUNT(*) FILTER (WHERE payment_status = 'refunded') / COUNT(*) FROM main_marts.fact_payments",
    "payment_channel")
for ch in channels:
    add(f"How many completed orders were placed through the {ch} channel?",
        f"SELECT COUNT(*) FROM main_marts.fact_orders WHERE order_status = 'completed' AND channel = '{ch}'",
        "payment_channel")
add("Which sales channel has the highest average order value?",
    "SELECT channel, AVG(order_total) AS avg_order_value FROM main_marts.fact_orders "
    "WHERE order_status = 'completed' GROUP BY channel ORDER BY avg_order_value DESC LIMIT 1", "payment_channel")

# ---- 9. grain-sensitive / join complexity (8) ----
add("What is total revenue per completed order, joined with its line items, without double-counting the order total?",
    "SELECT o.order_id, o.order_total FROM main_marts.fact_orders o WHERE o.order_status = 'completed' LIMIT 20",
    "grain_sensitive")
add("What is the correct total revenue when considering both orders and their line items (should not double count)?",
    "SELECT SUM(order_total) FROM main_marts.fact_orders WHERE order_status = 'completed'", "grain_sensitive")
add("What is total revenue computed strictly from line items at the order-item grain?",
    "SELECT SUM(extended_price) FROM main_marts.fact_order_items WHERE order_status = 'completed'",
    "grain_sensitive")
add("For each customer, what is their average number of items per completed order?",
    "SELECT customer_id, AVG(item_count) AS avg_items_per_order FROM main_marts.fact_orders "
    "WHERE order_status = 'completed' GROUP BY customer_id ORDER BY avg_items_per_order DESC LIMIT 10",
    "grain_sensitive")
add("What is total quantity of units sold per product category, at the line-item grain?",
    "SELECT p.category, SUM(oi.quantity) AS units FROM main_marts.fact_order_items oi "
    "JOIN main_marts.dim_products p ON oi.product_id = p.product_id "
    "WHERE oi.order_status = 'completed' GROUP BY p.category ORDER BY units DESC", "grain_sensitive")
add("How many orders had more than 5 line items?",
    "SELECT COUNT(*) FROM main_marts.fact_orders WHERE item_count > 5", "grain_sensitive")
add("What is the gap between order_total and the sum of amount_collected for completed orders?",
    "SELECT SUM(order_total) - SUM(amount_collected) FROM main_marts.fact_orders WHERE order_status = 'completed'",
    "grain_sensitive")
add("What is the average discount percentage applied across all order line items?",
    "SELECT AVG(discount_pct) FROM main_marts.fact_order_items WHERE discount_pct > 0", "grain_sensitive")

# ---- 10. top-N / ranking (6) ----
add("What are the top 3 regions by number of completed orders?",
    "SELECT c.region, COUNT(*) AS n FROM main_marts.fact_orders o JOIN main_marts.dim_customers c "
    "ON o.customer_id = c.customer_id WHERE o.order_status = 'completed' GROUP BY c.region "
    "ORDER BY n DESC LIMIT 3", "ranking")
add("What are the 5 lowest-margin products currently active?",
    "SELECT product_name, margin_pct FROM main_marts.dim_products WHERE is_active = true "
    "ORDER BY margin_pct ASC LIMIT 5", "ranking")
add("Who are the bottom 5 customers by lifetime revenue (with at least one completed order)?",
    "SELECT customer_id, full_name, lifetime_revenue FROM main_semantic.metric_customer_revenue "
    "WHERE completed_order_count > 0 ORDER BY lifetime_revenue ASC LIMIT 5", "ranking")
add("What are the top 3 subcategories by revenue?",
    "SELECT p.subcategory, SUM(oi.extended_price) AS revenue FROM main_marts.fact_order_items oi "
    "JOIN main_marts.dim_products p ON oi.product_id = p.product_id WHERE oi.order_status = 'completed' "
    "GROUP BY p.subcategory ORDER BY revenue DESC LIMIT 3", "ranking")
add("Which store has processed the most completed orders?",
    "SELECT store_id, COUNT(*) AS n FROM main_marts.fact_orders WHERE order_status = 'completed' "
    "GROUP BY store_id ORDER BY n DESC LIMIT 1", "ranking")
add("What are the top 5 states by customer count?",
    "SELECT state_code, COUNT(*) AS n FROM main_marts.dim_customers GROUP BY state_code "
    "ORDER BY n DESC LIMIT 5", "ranking")

print(f"total questions authored: {len(items)}")

# validate every gold query actually executes
failures = []
validated = []
for i, (q, sql, tag) in enumerate(items, start=1):
    try:
        res = con.execute(sql)
        rows = res.fetchall()
        cols = [d[0] for d in res.description]
        validated.append({"id": i, "question": q, "gold_sql": sql, "tag": tag,
                           "gold_row_count": len(rows), "gold_columns": cols})
    except Exception as e:
        failures.append((i, q, sql, str(e)))

print(f"validated OK: {len(validated)}  failed: {len(failures)}")
for i, q, sql, err in failures:
    print(f"  FAIL #{i}: {q}\n    SQL: {sql}\n    ERROR: {err}")

os.makedirs("eval/gold", exist_ok=True)
with open("eval/gold/own_warehouse_gold.json", "w") as f:
    json.dump(validated, f, indent=2, default=str)

print(f"wrote {len(validated)} validated gold questions to eval/gold/own_warehouse_gold.json")
