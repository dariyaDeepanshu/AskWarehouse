-- Semantic layer: canonical "revenue" definition at customer grain.
-- Revenue = sum of order_total for orders with order_status = 'completed'.
-- Cancelled, returned, and pending orders are excluded on purpose -- this is
-- the exact ambiguity ("top customers by what, over what window, completed
-- or all orders?") the agent should resolve by using this view instead of
-- re-deriving the definition per question.
select
    c.customer_id,
    c.full_name,
    c.state_code,
    c.state_name,
    c.region,
    count(o.order_id) as completed_order_count,
    coalesce(sum(o.order_total), 0) as lifetime_revenue,
    coalesce(sum(o.order_total) filter (
        where o.order_date >= current_date - interval 90 day
    ), 0) as revenue_last_90d,
    coalesce(sum(o.order_total) filter (
        where o.order_date >= current_date - interval 365 day
    ), 0) as revenue_last_365d,
    max(o.order_date) as last_order_date
from {{ ref('dim_customers') }} c
left join {{ ref('fact_orders') }} o
    on c.customer_id = o.customer_id and o.order_status = 'completed'
group by 1, 2, 3, 4, 5
