-- Spend must agree between staging, the daily campaign mart and the rollup grand total.
with staging as (
    select round(sum(spend_gbp), 2) as spend_gbp from {{ ref('stg_ad_spend') }}
),

daily as (
    select round(sum(spend_gbp), 2) as spend_gbp from {{ ref('mart_campaign_daily') }}
),

rollup as (
    select spend_gbp from {{ ref('mart_monthly_rollup') }}
    where grouping_level = 7
)

select
    s.spend_gbp as staging_spend,
    d.spend_gbp as daily_spend,
    r.spend_gbp as rollup_spend
from staging as s
cross join daily as d
cross join rollup as r
where abs(s.spend_gbp - d.spend_gbp) > 0.01 or abs(s.spend_gbp - r.spend_gbp) > 0.01
