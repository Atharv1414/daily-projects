{#
    Channel x model scorecard: attributed conversions and revenue against spend, plus how
    far each model moves a channel away from last-touch (the default most ad platforms
    and analytics tools report).
#}
with credit as (
    select
        channel,
        model,
        sum(conversion_credit) as conversions,
        sum(attributed_revenue_gbp) as revenue_gbp
    from {{ ref('fct_attributed_conversions') }}
    group by channel, model
),

campaign_channels as (
    select distinct
        campaign_id,
        channel
    from {{ ref('int_sessions') }}
    where campaign_id is not null
),

spend as (
    select
        s.channel,
        sum(a.spend_gbp) as spend_gbp,
        sum(a.clicks) as clicks
    from {{ ref('stg_ad_spend') }} as a
    inner join campaign_channels as s on a.campaign_id = s.campaign_id
    group by s.channel
),

scored as (
    select
        c.channel,
        c.model,
        d.channel_group,
        d.is_paid,
        round(c.conversions, 2) as conversions,
        round(c.revenue_gbp, 2) as revenue_gbp,
        round(coalesce(s.spend_gbp, 0), 2) as spend_gbp,
        round(c.revenue_gbp / nullif(s.spend_gbp, 0), 2) as roas,
        round(s.spend_gbp / nullif(c.conversions, 0), 2) as cpa_gbp,
        round(c.revenue_gbp / sum(c.revenue_gbp) over (partition by c.model), 4) as revenue_share
    from credit as c
    left join spend as s on c.channel = s.channel
    left join {{ ref('dim_channel') }} as d on c.channel = d.channel
)

select
    *,
    round(
        revenue_gbp
        - first_value(revenue_gbp) over (
            partition by channel
            order by case when model = 'last_touch' then 0 else 1 end
        ),
        2
    ) as revenue_vs_last_touch_gbp,
    rank() over (partition by model order by revenue_gbp desc) as revenue_rank
from scored
