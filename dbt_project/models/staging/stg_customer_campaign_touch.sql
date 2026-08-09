select
    touch_id,
    customer_id,
    campaign_id,
    touch_ts,
    touch_type
from {{ source('raw', 'customer_campaign_touch') }}
