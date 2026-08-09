with source as (
    select * from {{ source('raw', 'products') }}
)

select
    product_id,
    sku,
    product_name,
    -- category casing is inconsistent at the source ('electronics' vs 'Electronics');
    -- normalize against the known category list rather than a blind initcap so
    -- multi-word categories like 'Home & Kitchen' stay correct.
    case lower(category)
        when 'electronics' then 'Electronics'
        when 'apparel' then 'Apparel'
        when 'home & kitchen' then 'Home & Kitchen'
        when 'beauty' then 'Beauty'
        when 'sports & outdoors' then 'Sports & Outdoors'
        when 'toys & games' then 'Toys & Games'
        when 'grocery' then 'Grocery'
        else category
    end as category,
    subcategory,
    brand,
    unit_cost,
    list_price,
    round(list_price - unit_cost, 2) as unit_margin,
    round((list_price - unit_cost) / nullif(list_price, 0), 4) as margin_pct,
    is_active,
    launch_date
from source
