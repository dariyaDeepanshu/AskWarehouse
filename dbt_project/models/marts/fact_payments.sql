select
    payment_id,
    order_id,
    payment_method,
    amount,
    payment_ts,
    payment_ts::date as payment_date,
    payment_status
from {{ ref('stg_payments') }}
