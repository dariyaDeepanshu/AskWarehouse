-- Grain: one row per order line item (order_id, product_id combination can repeat
-- across order_items, so joining this to fact_orders and summing order-level
-- fields fans out revenue -- this is the intentional "grain trap" the agent's
-- sanity checks are meant to catch).
select
    oi.order_item_id,
    oi.order_id,
    oi.product_id,
    o.customer_id,
    o.store_id,
    o.order_date,
    o.order_status,
    oi.quantity,
    oi.unit_price,
    oi.discount_pct,
    oi.extended_price,
    round(oi.extended_price * (p.unit_cost / nullif(p.list_price, 0)), 2) as estimated_cost,
    round(oi.extended_price - (oi.extended_price * (p.unit_cost / nullif(p.list_price, 0))), 2) as estimated_gross_profit
from {{ ref('stg_order_items') }} oi
join {{ ref('stg_orders') }} o on oi.order_id = o.order_id
join {{ ref('stg_products') }} p on oi.product_id = p.product_id
