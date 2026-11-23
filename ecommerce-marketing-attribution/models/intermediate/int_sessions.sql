{{
    config(
        materialized='incremental',
        unique_key='session_id',
        incremental_strategy='delete+insert'
    )
}}
{#
    Sessionisation (gaps-and-islands). A new session starts when
      * it is the visitor's first hit, or
      * more than var('session_timeout_minutes') passed since the previous hit, or
      * the hit carries campaign parameters or an external referrer (a new entrance).
    A running sum of the "new session" flag numbers the islands.

    Incremental runs re-sessionise a trailing day of hits so sessions that straddle
    the previous high-water mark are rebuilt with the same deterministic id.
#}
with hits as (
    select *
    from {{ ref('stg_web_hits') }}
    {% if is_incremental() %}
        where hit_at >= (
            select date_trunc('day', max(prior_run.session_start)) - interval 1 day
            from {{ this }} as prior_run
        )
    {% endif %}
),

flagged as (
    select
        *,
        case
            when lag(hit_at) over visitor is null then 1
            when
                hit_at - lag(hit_at) over visitor
                > to_minutes({{ var('session_timeout_minutes') }}) then 1
            when utm_source is not null or referrer_domain is not null then 1
            else 0
        end as is_new_session
    from hits
    window visitor as (partition by anonymous_id order by hit_at, hit_id)
),

numbered as (
    select
        *,
        sum(is_new_session) over (
            partition by anonymous_id order by hit_at, hit_id rows unbounded preceding
        ) as session_number
    from flagged
),

sessions as (
    select
        anonymous_id,
        session_number,
        min(hit_at) as session_start,
        max(hit_at) as session_end,
        count(*) as page_views,
        min(hit_id) as min_hit_id,
        arg_min(page_path, hit_at) as landing_page,
        arg_min(device_type, hit_at) as device_type,
        arg_min(utm_source, hit_at) as utm_source,
        arg_min(utm_medium, hit_at) as utm_medium,
        arg_min(utm_campaign, hit_at) as utm_campaign,
        arg_min(referrer_domain, hit_at) as referrer_domain,
        bool_or(is_conversion_page) as reached_confirmation
    from numbered
    group by anonymous_id, session_number
)

select
    -- the smallest hit id breaks ties between islands that start in the same second
    md5(s.anonymous_id || '|' || cast(s.session_start as varchar) || '|' || s.min_hit_id)
        as session_id,
    s.anonymous_id,
    s.session_start,
    s.session_end,
    date_diff('second', s.session_start, s.session_end) as duration_seconds,
    s.page_views,
    s.page_views = 1 as is_bounce,
    s.landing_page,
    s.device_type,
    s.utm_source,
    s.utm_medium,
    s.utm_campaign,
    s.referrer_domain,
    {{ channel_grouping('s.utm_source', 's.utm_medium', 's.utm_campaign', 's.referrer_domain') }}
        as channel,
    c.campaign_id,
    s.reached_confirmation
from sessions as s
left join {{ ref('stg_campaigns') }} as c on s.utm_campaign = c.utm_campaign
