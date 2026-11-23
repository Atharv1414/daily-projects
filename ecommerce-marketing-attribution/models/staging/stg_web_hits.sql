-- Clean page views: drop crawler traffic and tag double-fires, normalise UTM values.
with source as (
    select * from {{ ref('raw_web_hits') }}
),

deduplicated as (
    select *
    from source
    qualify row_number() over (partition by hit_id order by hit_at) = 1
)

select
    hit_id,
    anonymous_id,
    hit_at,
    device_type,
    page_path,
    {{ normalise_source('utm_source') }} as utm_source,
    {{ normalise_medium('utm_medium') }} as utm_medium,
    lower(trim(utm_campaign)) as utm_campaign,
    lower(referrer_domain) as referrer_domain,
    page_path = '/checkout/confirmation' as is_conversion_page
from deduplicated
where not regexp_matches(lower(user_agent), 'bot|crawler|spider|slurp')
