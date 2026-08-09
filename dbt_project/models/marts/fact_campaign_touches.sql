select
    t.touch_id,
    t.customer_id,
    t.campaign_id,
    c.campaign_name,
    c.channel as campaign_channel,
    t.touch_ts,
    t.touch_ts::date as touch_date,
    t.touch_type
from {{ ref('stg_customer_campaign_touch') }} t
join {{ ref('stg_campaigns') }} c on t.campaign_id = c.campaign_id
