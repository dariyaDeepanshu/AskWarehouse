-- Semantic layer: canonical "active_user" definition.
-- active_30d / active_90d = placed >=1 completed order in the trailing window.
select
    c.customer_id,
    c.full_name,
    c.signup_date,
    max(o.order_date) filter (where o.order_status = 'completed') as last_completed_order_date,
    bool_or(o.order_status = 'completed' and o.order_date >= current_date - interval 30 day) as is_active_30d,
    bool_or(o.order_status = 'completed' and o.order_date >= current_date - interval 90 day) as is_active_90d,
    count(o.order_id) filter (where o.order_status = 'completed') as lifetime_completed_orders
from {{ ref('dim_customers') }} c
left join {{ ref('fact_orders') }} o on c.customer_id = o.customer_id
group by 1, 2, 3
