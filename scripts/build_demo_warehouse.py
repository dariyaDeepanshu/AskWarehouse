"""Builds the bundled demo warehouse for the Vercel deployment.

Runs the existing synthetic-data generator, then materializes the exact same
staging -> marts -> semantic layer the dbt project builds, but as plain SQL
(no dbt dependency at deploy time). Output: data/warehouse/warehouse.duckdb
with schemas main (seeds), main_staging, main_marts, main_semantic -- the
schema names AskWarehouse's safety config already expects.

Usage:
    python scripts/build_demo_warehouse.py --scale small
"""
import argparse
import csv
import os
import subprocess
import sys

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "warehouse", "warehouse.duckdb")
SEED_CSV = os.path.join(ROOT, "dbt_project", "seeds", "us_states.csv")

# ---------------------------------------------------------------------------
# staging views (dbt_project/models/staging/*.sql, refs resolved to raw.*)
# ---------------------------------------------------------------------------
STAGING = {
    "stg_customers": """
        select
            customer_id, first_name, last_name,
            first_name || ' ' || last_name as full_name,
            lower(email) as email, phone, city,
            state as state_code, country,
            coalesce(
                try_strptime(signup_date_raw, '%Y-%m-%d'),
                try_strptime(signup_date_raw, '%m/%d/%Y')
            )::date as signup_date,
            birth_date, is_marketing_opt_in, acquisition_channel
        from raw.customers
    """,
    "stg_products": """
        select
            product_id, sku, product_name,
            case lower(category)
                when 'electronics' then 'Electronics'
                when 'apparel' then 'Apparel'
                when 'home & kitchen' then 'Home & Kitchen'
                when 'beauty' then 'Beauty'
                when 'sports & outdoors' then 'Sports & Outdoors'
                when 'toys & games' then 'Toys & Games'
                when 'grocery' then 'Grocery'
                else category
            end as category,
            subcategory, brand, unit_cost, list_price,
            round(list_price - unit_cost, 2) as unit_margin,
            round((list_price - unit_cost) / nullif(list_price, 0), 4) as margin_pct,
            is_active, launch_date
        from raw.products
    """,
    "stg_stores": """
        select store_id, store_name, channel, state as state_code, region
        from raw.stores
    """,
    "stg_campaigns": """
        select campaign_id, campaign_name, channel, start_date, end_date, budget
        from raw.campaigns
    """,
    "stg_orders": """
        select
            order_id, customer_id, store_id, order_ts,
            order_ts::date as order_date, order_status, channel, currency
        from raw.orders
    """,
    "stg_order_items": """
        select
            order_item_id, order_id, product_id, quantity, unit_price,
            coalesce(discount_pct, 0) as discount_pct,
            round(quantity * unit_price, 2) as extended_price
        from raw.order_items
    """,
    "stg_payments": """
        select payment_id, order_id, payment_method, amount, payment_ts, payment_status
        from raw.payments
    """,
    "stg_customer_campaign_touch": """
        select touch_id, customer_id, campaign_id, touch_ts, touch_type
        from raw.customer_campaign_touch
    """,
}

# ---------------------------------------------------------------------------
# marts tables (dbt_project/models/marts/*.sql)
# ---------------------------------------------------------------------------
MARTS = {
    "dim_customers": """
        select
            c.customer_id, c.full_name, c.first_name, c.last_name, c.email, c.phone,
            c.city, c.state_code, s.state_name,
            coalesce(s.region, 'Other') as region,
            c.country, c.signup_date, c.birth_date,
            date_diff('year', c.birth_date, current_date) as age_years,
            c.is_marketing_opt_in, c.acquisition_channel
        from main_staging.stg_customers c
        left join main.us_states s on c.state_code = s.state_code
    """,
    "dim_products": """
        select
            product_id, sku, product_name, category, subcategory, brand,
            unit_cost, list_price, unit_margin, margin_pct, is_active, launch_date
        from main_staging.stg_products
    """,
    "dim_stores": """
        select store_id, store_name, channel, state_code, region
        from main_staging.stg_stores
    """,
    "dim_date": """
        with spine as (
            select unnest(generate_series(
                (select min(order_date) from main_staging.stg_orders),
                (select max(order_date) from main_staging.stg_orders),
                interval 1 day
            )) as date_day
        )
        select
            date_day,
            date_part('year', date_day) as year,
            date_part('quarter', date_day) as quarter,
            date_part('month', date_day) as month,
            strftime(date_day, '%B') as month_name,
            date_part('week', date_day) as iso_week,
            date_part('dayofweek', date_day) as day_of_week,
            strftime(date_day, '%A') as day_name,
            date_part('dayofweek', date_day) in (0, 6) as is_weekend,
            date_trunc('month', date_day)::date as month_start,
            date_trunc('quarter', date_day)::date as quarter_start
        from spine
    """,
    "fact_orders": """
        with items_agg as (
            select
                order_id,
                count(*) as item_count,
                sum(quantity) as unit_count,
                round(sum(extended_price), 2) as order_total
            from main_staging.stg_order_items
            group by 1
        ),
        payments_agg as (
            select
                order_id,
                count(*) as payment_count,
                sum(case when payment_status = 'succeeded' then amount else 0 end) as amount_collected,
                max(payment_status) filter (where payment_status = 'succeeded') as has_succeeded_payment
            from main_staging.stg_payments
            group by 1
        )
        select
            o.order_id, o.customer_id, o.store_id, o.order_date, o.order_ts,
            o.order_status, o.channel, o.currency,
            coalesce(i.item_count, 0) as item_count,
            coalesce(i.unit_count, 0) as unit_count,
            coalesce(i.order_total, 0) as order_total,
            coalesce(p.payment_count, 0) as payment_count,
            coalesce(p.amount_collected, 0) as amount_collected
        from main_staging.stg_orders o
        left join items_agg i on o.order_id = i.order_id
        left join payments_agg p on o.order_id = p.order_id
    """,
    "fact_order_items": """
        select
            oi.order_item_id, oi.order_id, oi.product_id, o.customer_id, o.store_id,
            o.order_date, o.order_status, oi.quantity, oi.unit_price, oi.discount_pct,
            oi.extended_price,
            round(oi.extended_price * (p.unit_cost / nullif(p.list_price, 0)), 2) as estimated_cost,
            round(oi.extended_price - (oi.extended_price * (p.unit_cost / nullif(p.list_price, 0))), 2) as estimated_gross_profit
        from main_staging.stg_order_items oi
        join main_staging.stg_orders o on oi.order_id = o.order_id
        join main_staging.stg_products p on oi.product_id = p.product_id
    """,
    "fact_payments": """
        select
            payment_id, order_id, payment_method, amount, payment_ts,
            payment_ts::date as payment_date, payment_status
        from main_staging.stg_payments
    """,
    "fact_campaign_touches": """
        select
            t.touch_id, t.customer_id, t.campaign_id, c.campaign_name,
            c.channel as campaign_channel, t.touch_ts, t.touch_ts::date as touch_date,
            t.touch_type
        from main_staging.stg_customer_campaign_touch t
        join main_staging.stg_campaigns c on t.campaign_id = c.campaign_id
    """,
}

# ---------------------------------------------------------------------------
# semantic views (dbt_project/models/semantic/*.sql)
# ---------------------------------------------------------------------------
SEMANTIC = {
    "metric_customer_revenue": """
        select
            c.customer_id, c.full_name, c.state_code, c.state_name, c.region,
            count(o.order_id) as completed_order_count,
            coalesce(sum(o.order_total), 0) as lifetime_revenue,
            coalesce(sum(o.order_total) filter (where o.order_date >= current_date - interval 90 day), 0) as revenue_last_90d,
            coalesce(sum(o.order_total) filter (where o.order_date >= current_date - interval 365 day), 0) as revenue_last_365d,
            max(o.order_date) as last_order_date
        from main_marts.dim_customers c
        left join main_marts.fact_orders o
            on c.customer_id = o.customer_id and o.order_status = 'completed'
        group by 1, 2, 3, 4, 5
    """,
    "metric_daily_revenue": """
        select
            o.order_date, o.channel,
            count(distinct o.order_id) as order_count,
            coalesce(sum(o.order_total), 0) as revenue,
            round(coalesce(sum(o.order_total), 0) / nullif(count(distinct o.order_id), 0), 2) as avg_order_value
        from main_marts.fact_orders o
        where o.order_status = 'completed'
        group by 1, 2
    """,
    "metric_active_users": """
        select
            c.customer_id, c.full_name, c.signup_date,
            max(o.order_date) filter (where o.order_status = 'completed') as last_completed_order_date,
            bool_or(o.order_status = 'completed' and o.order_date >= current_date - interval 30 day) as is_active_30d,
            bool_or(o.order_status = 'completed' and o.order_date >= current_date - interval 90 day) as is_active_90d,
            count(o.order_id) filter (where o.order_status = 'completed') as lifetime_completed_orders
        from main_marts.dim_customers c
        left join main_marts.fact_orders o on c.customer_id = o.customer_id
        group by 1, 2, 3
    """,
    "metric_product_performance": """
        select
            p.product_id, p.product_name, p.category, p.subcategory, p.brand,
            count(distinct oi.order_id) as order_count,
            sum(oi.quantity) as units_sold,
            round(sum(oi.extended_price), 2) as revenue,
            round(sum(oi.estimated_gross_profit), 2) as gross_profit
        from main_marts.dim_products p
        left join main_marts.fact_order_items oi
            on p.product_id = oi.product_id and oi.order_status = 'completed'
        group by 1, 2, 3, 4, 5
    """,
}


def _load_seed(con):
    con.execute("CREATE SCHEMA IF NOT EXISTS main")
    with open(SEED_CSV, newline="") as f:
        rows = list(csv.reader(f))
    header, data = rows[0], rows[1:]
    con.execute("DROP TABLE IF EXISTS main.us_states")
    con.execute("CREATE TABLE main.us_states (state_code VARCHAR, state_name VARCHAR, region VARCHAR)")
    con.executemany("INSERT INTO main.us_states VALUES (?, ?, ?)", data)
    print(f"  seed main.us_states: {len(data)} rows")


def main(scale: str):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    print(f"[gen] synthetic raw data (scale={scale}) ...")
    subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "generate_warehouse_data.py"), "--scale", scale],
        check=True, cwd=ROOT,
    )

    con = duckdb.connect(DB_PATH)
    _load_seed(con)

    con.execute("CREATE SCHEMA IF NOT EXISTS main_staging")
    con.execute("CREATE SCHEMA IF NOT EXISTS main_marts")
    con.execute("CREATE SCHEMA IF NOT EXISTS main_semantic")

    for name, sql in STAGING.items():
        con.execute(f"CREATE OR REPLACE VIEW main_staging.{name} AS {sql}")
        print(f"  view main_staging.{name}")

    for name, sql in MARTS.items():
        con.execute(f"CREATE OR REPLACE TABLE main_marts.{name} AS {sql}")
        n = con.execute(f"SELECT count(*) FROM main_marts.{name}").fetchone()[0]
        print(f"  table main_marts.{name}: {n:,} rows")

    for name, sql in SEMANTIC.items():
        con.execute(f"CREATE OR REPLACE VIEW main_semantic.{name} AS {sql}")
        print(f"  view main_semantic.{name}")

    # marts are standalone tables and the semantic views only reference
    # main_marts, so raw + staging are no longer needed -- and dropping them
    # keeps the shipped .duckdb small and makes it structurally impossible for
    # the agent to reach pre-normalization data.
    con.execute("DROP SCHEMA main_staging CASCADE")
    con.execute("DROP SCHEMA raw CASCADE")
    con.execute("VACUUM")
    con.execute("CHECKPOINT")
    con.close()

    size_mb = os.path.getsize(DB_PATH) / 1e6
    print(f"\ndone -> {DB_PATH}  ({size_mb:.1f} MB)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--scale", choices=["small", "medium", "full"], default="small")
    args = p.parse_args()
    main(args.scale)
