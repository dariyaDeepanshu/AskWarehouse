-- Semantic layer: canonical product-level sales performance.
-- Deliberately built from fact_order_items (line-item grain) with an
-- explicit distinct-order count alongside revenue, so "units sold" and
-- "orders containing this product" can't be confused with each other.
select
    p.product_id,
    p.product_name,
    p.category,
    p.subcategory,
    p.brand,
    count(distinct oi.order_id) as order_count,
    sum(oi.quantity) as units_sold,
    round(sum(oi.extended_price), 2) as revenue,
    round(sum(oi.estimated_gross_profit), 2) as gross_profit
from {{ ref('dim_products') }} p
left join {{ ref('fact_order_items') }} oi
    on p.product_id = oi.product_id and oi.order_status = 'completed'
group by 1, 2, 3, 4, 5
