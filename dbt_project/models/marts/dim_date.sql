with spine as (
    select unnest(generate_series(
        (select min(order_date) from {{ ref('stg_orders') }}),
        (select max(order_date) from {{ ref('stg_orders') }}),
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
