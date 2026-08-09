with customers as (
    select * from {{ ref('stg_customers') }}
),
states as (
    select * from {{ ref('us_states') }}
)

select
    c.customer_id,
    c.full_name,
    c.first_name,
    c.last_name,
    c.email,
    c.phone,
    c.city,
    c.state_code,
    s.state_name,
    coalesce(s.region, 'Other') as region,
    c.country,
    c.signup_date,
    c.birth_date,
    date_diff('year', c.birth_date, current_date) as age_years,
    c.is_marketing_opt_in,
    c.acquisition_channel
from customers c
left join states s on c.state_code = s.state_code
