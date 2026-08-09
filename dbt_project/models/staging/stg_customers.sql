with source as (
    select * from {{ source('raw', 'customers') }}
)

select
    customer_id,
    first_name,
    last_name,
    first_name || ' ' || last_name as full_name,
    lower(email) as email,
    phone,
    city,
    state as state_code,
    country,
    -- signup_date_raw arrives in two formats from the source system
    -- ('YYYY-MM-DD' and 'MM/DD/YYYY'); normalize both to a real date.
    coalesce(
        try_strptime(signup_date_raw, '%Y-%m-%d'),
        try_strptime(signup_date_raw, '%m/%d/%Y')
    )::date as signup_date,
    birth_date,
    is_marketing_opt_in,
    acquisition_channel
from source
