-- Grain: one row per order. order_total/item_count are pre-aggregated here
-- specifically so "revenue by X" questions don't require the agent to join
-- down to order_items and risk fan-out double-counting when they don't need
-- line-item detail.
with items_agg as (
    select
        order_id,
        count(*) as item_count,
        sum(quantity) as unit_count,
        round(sum(extended_price), 2) as order_total
    from {{ ref('stg_order_items') }}
    group by 1
),
payments_agg as (
    select
        order_id,
        count(*) as payment_count,
        sum(case when payment_status = 'succeeded' then amount else 0 end) as amount_collected,
        max(payment_status) filter (where payment_status = 'succeeded') as has_succeeded_payment
    from {{ ref('stg_payments') }}
    group by 1
)

select
    o.order_id,
    o.customer_id,
    o.store_id,
    o.order_date,
    o.order_ts,
    o.order_status,
    o.channel,
    o.currency,
    coalesce(i.item_count, 0) as item_count,
    coalesce(i.unit_count, 0) as unit_count,
    coalesce(i.order_total, 0) as order_total,
    coalesce(p.payment_count, 0) as payment_count,
    coalesce(p.amount_collected, 0) as amount_collected
from {{ ref('stg_orders') }} o
left join items_agg i on o.order_id = i.order_id
left join payments_agg p on o.order_id = p.order_id
