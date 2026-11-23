-- What-if: move 20% of generic paid search spend (the only paid channel near break-even
-- under every model) into paid social, valuing each pound at the channel's position-based
-- ROAS. A first-order estimate that assumes constant returns; validate with a geo holdout
-- before acting on it.
with scorecard as (
    select
        channel,
        spend_gbp,
        revenue_gbp,
        roas
    from {{ ref('mart_channel_attribution') }}
    where model = 'position_based' and spend_gbp > 0
),

moved as (
    select 0.2 * spend_gbp as amount_gbp
    from scorecard
    where channel = 'paid_search_generic'
),

scenario as (
    select
        s.channel,
        s.spend_gbp,
        s.revenue_gbp,
        s.roas,
        case
            when s.channel = 'paid_search_generic' then -m.amount_gbp
            when s.channel = 'paid_social' then m.amount_gbp
            else 0
        end as spend_change_gbp
    from scorecard as s
    cross join moved as m
)

select
    channel,
    round(spend_gbp, 0) as current_spend_gbp,
    round(spend_change_gbp, 0) as spend_change_gbp,
    round(spend_change_gbp * roas, 0) as revenue_change_gbp
from scenario
order by spend_change_gbp
