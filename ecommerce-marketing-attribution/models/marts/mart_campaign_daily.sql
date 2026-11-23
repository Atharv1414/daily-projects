{#
    Daily campaign performance with running and rolling window metrics. Attributed
    revenue uses the position-based model (the house model, see README) on the day
    of the touch, so cost and credit line up in time.
#}
with dates as (
    select distinct spend_date from {{ ref('stg_ad_spend') }}
),

campaign_days as (
    select
        c.campaign_id,
        c.platform,
        c.platform_channel as channel,
        d.spend_date
    from {{ ref('stg_campaigns') }} as c
    cross join dates as d
),

credit as (
    select
        campaign_id,
        touch_date,
        sum(conversion_credit) as conversions,
        sum(attributed_revenue_gbp) as revenue_gbp
    from {{ ref('fct_attributed_conversions') }}
    where model = 'position_based' and campaign_id is not null
    group by campaign_id, touch_date
),

sessions as (
    select
        campaign_id,
        cast(session_start as date) as session_date,
        count(*) as sessions
    from {{ ref('int_sessions') }}
    where campaign_id is not null
    group by all
),

daily as (
    select
        cd.campaign_id,
        cd.platform,
        cd.channel,
        cd.spend_date,
        coalesce(sp.spend_gbp, 0) as spend_gbp,
        coalesce(sp.clicks, 0) as clicks,
        coalesce(se.sessions, 0) as sessions,
        coalesce(cr.conversions, 0) as conversions,
        coalesce(cr.revenue_gbp, 0) as revenue_gbp
    from campaign_days as cd
    left join {{ ref('stg_ad_spend') }} as sp
        on cd.campaign_id = sp.campaign_id and cd.spend_date = sp.spend_date
    left join sessions as se
        on cd.campaign_id = se.campaign_id and cd.spend_date = se.session_date
    left join credit as cr
        on cd.campaign_id = cr.campaign_id and cd.spend_date = cr.touch_date
)

select
    *,
    sum(spend_gbp) over campaign_to_date as cumulative_spend_gbp,
    sum(revenue_gbp) over campaign_to_date as cumulative_revenue_gbp,
    sum(revenue_gbp) over trailing_7d / nullif(sum(spend_gbp) over trailing_7d, 0) as roas_7d,
    1.0 * sessions / nullif(clicks, 0) as click_to_session_rate
from daily
window
    campaign_to_date as (partition by campaign_id order by spend_date rows unbounded preceding),
    trailing_7d as (
        partition by campaign_id
        order by spend_date
        range between interval 6 day preceding and current row
    )
