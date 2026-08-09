-- Semantic layer: canonical daily revenue by channel, completed orders only.
select
    o.order_date,
    o.channel,
    count(distinct o.order_id) as order_count,
    coalesce(sum(o.order_total), 0) as revenue,
    round(coalesce(sum(o.order_total), 0) / nullif(count(distinct o.order_id), 0), 2) as avg_order_value
from {{ ref('fact_orders') }} o
where o.order_status = 'completed'
group by 1, 2
