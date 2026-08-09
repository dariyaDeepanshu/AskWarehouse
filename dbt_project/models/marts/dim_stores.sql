select
    store_id,
    store_name,
    channel,
    state_code,
    region
from {{ ref('stg_stores') }}
