{#
    Month x channel-group x channel totals with subtotals, the shape finance asks for:
    every month, every channel group, every channel and a grand total in one table.
    ROLLUP gives the month hierarchy; a second grouping adds whole-period channel totals
    (together equivalent to GROUPING SETS ((m, g, c), (m, g), (m), (g, c), ())).
    grouping_level is the grouping_id() bitmask that tells subtotal rows apart.
#}
with revenue as (
    select
        date_trunc('month', ordered_at) as revenue_month,
        channel,
        sum(attributed_revenue_gbp) as revenue_gbp,
        sum(conversion_credit) as conversions
    from {{ ref('fct_attributed_conversions') }}
    where model = 'position_based'
    group by all
),

spend as (
    select
        date_trunc('month', spend_date) as revenue_month,
        channel,
        sum(spend_gbp) as spend_gbp
    from {{ ref('mart_campaign_daily') }}
    group by all
),

joined as (
    select
        coalesce(r.revenue_month, s.revenue_month) as revenue_month,
        coalesce(r.channel, s.channel) as channel,
        d.channel_group,
        coalesce(r.revenue_gbp, 0) as revenue_gbp,
        coalesce(r.conversions, 0) as conversions,
        coalesce(s.spend_gbp, 0) as spend_gbp
    from revenue as r
    full outer join spend as s
        on r.revenue_month = s.revenue_month and r.channel = s.channel
    left join {{ ref('dim_channel') }} as d on coalesce(r.channel, s.channel) = d.channel
),

month_hierarchy as (
    select
        revenue_month,
        channel_group,
        channel,
        grouping_id(revenue_month, channel_group, channel) as grouping_level,
        sum(revenue_gbp) as revenue_gbp,
        sum(conversions) as conversions,
        sum(spend_gbp) as spend_gbp
    from joined
    group by rollup(revenue_month, channel_group, channel)
),

channel_totals as (
    select
        null::date as revenue_month,
        channel_group,
        channel,
        4 as grouping_level,
        sum(revenue_gbp) as revenue_gbp,
        sum(conversions) as conversions,
        sum(spend_gbp) as spend_gbp
    from joined
    group by channel_group, channel
),

combined as (
    select * from month_hierarchy
    union all
    select * from channel_totals
)

select
    revenue_month,
    channel_group,
    channel,
    grouping_level,
    round(revenue_gbp, 2) as revenue_gbp,
    round(conversions, 2) as conversions,
    round(spend_gbp, 2) as spend_gbp,
    round(revenue_gbp / nullif(spend_gbp, 0), 2) as roas
from combined
