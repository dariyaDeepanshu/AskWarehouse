select
    order_item_id,
    order_id,
    product_id,
    quantity,
    unit_price,
    coalesce(discount_pct, 0) as discount_pct,
    round(quantity * unit_price, 2) as extended_price
from {{ source('raw', 'order_items') }}
