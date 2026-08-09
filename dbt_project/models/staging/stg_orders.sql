select
    order_id,
    customer_id,
    store_id,
    order_ts,
    order_ts::date as order_date,
    order_status,
    channel,
    currency
from {{ source('raw', 'orders') }}
