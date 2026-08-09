select
    product_id,
    sku,
    product_name,
    category,
    subcategory,
    brand,
    unit_cost,
    list_price,
    unit_margin,
    margin_pct,
    is_active,
    launch_date
from {{ ref('stg_products') }}
