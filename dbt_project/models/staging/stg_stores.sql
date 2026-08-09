select
    store_id,
    store_name,
    channel,
    state as state_code,
    region
from {{ source('raw', 'stores') }}
