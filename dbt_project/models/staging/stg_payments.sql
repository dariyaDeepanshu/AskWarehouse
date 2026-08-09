select
    payment_id,
    order_id,
    payment_method,
    amount,
    payment_ts,
    payment_status
from {{ source('raw', 'payments') }}
