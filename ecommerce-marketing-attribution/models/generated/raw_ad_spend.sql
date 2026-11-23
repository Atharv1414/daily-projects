{#
    Daily cost feed per campaign from the ad platforms. Clicks are derived from tracked
    landing sessions (85% of clicks produce a tracked visit), so spend scales with traffic.
    4% of campaign-days were restated by the platform a day later: the latest load wins.
    Email has a flat daily sending cost instead of clicks.
#}
with campaigns as (
    select
        *,
        row_number() over (partition by true_channel order by campaign_id) as idx,
        count(*) over (partition by true_channel) as n_in_channel
    from {{ ref('raw_campaigns') }}
),

-- the same campaign assignment rule raw_web_hits uses for the landing hit
clicks as (
    select
        c.campaign_id,
        cast(s.session_start as date) as spend_date,
        count(*) as tracked_sessions
    from {{ ref('gen_sessions') }} as s
    inner join campaigns as c
        on
            s.true_channel = c.true_channel
            and c.idx = 1 + {{ rnd('s.true_session_id', 'camp', 1000) }} % c.n_in_channel
    group by all
),

days as (
    select cast(t.d as date) as spend_date
    from range(
        date '{{ var("start_date") }}',
        date '{{ var("start_date") }}' + to_days({{ var('days') }}),
        interval 1 day
    ) as t (d)
),

daily as (
    select
        c.campaign_id,
        d.spend_date,
        coalesce(k.tracked_sessions, 0) as tracked_sessions,
        c.cpc_pence,
        c.true_channel
    from {{ ref('raw_campaigns') }} as c
    cross join days as d
    left join clicks as k
        on c.campaign_id = k.campaign_id and d.spend_date = k.spend_date
),

costed as (
    select
        campaign_id,
        spend_date,
        cast(round(tracked_sessions / 0.85) as integer) as clicks,
        cast(round(tracked_sessions / 0.85) as integer)
        * (60 + {{ rnd("campaign_id || cast(spend_date as varchar)", 'ctr', 140) }}) as impressions,
        case
            when true_channel = 'email' then 1500
            else cast(round(
                tracked_sessions / 0.85 * cpc_pence
                * (
                    0.85
                    + {{ rnd("campaign_id || cast(spend_date as varchar)", 'noise', 30) }} / 100.0
                )
            ) as integer)
        end as spend_pence,
        cast(spend_date as timestamp) + interval 1 day + interval 3 hour as _loaded_at
    from daily
)

select * from costed
union all
-- the earlier, superseded version of restated rows (loaded first, lower spend)
select
    campaign_id,
    spend_date,
    clicks,
    impressions,
    cast(spend_pence * 0.8 as integer) as spend_pence,
    _loaded_at - interval 1 day + interval 30 minute as _loaded_at
from costed
where {{ rnd("campaign_id || cast(spend_date as varchar)", 'restate', 100) }} < 4
