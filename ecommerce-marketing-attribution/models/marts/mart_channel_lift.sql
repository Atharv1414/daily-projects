{#
    Incrementality proxy that attribution cannot give: do journeys that include a
    channel convert more often than journeys that do not? Uses every visitor (buyers and
    non-buyers), so it sees the journeys that went nowhere. Observational, not causal:
    confounded by intent, so read it next to a holdout test, not instead of one.
#}
with visitor_sessions as (
    select
        coalesce(customer_id, anonymous_id) as person_id,
        channel,
        reached_confirmation
    from {{ ref('int_sessions_stitched') }}
),

journeys as (
    select
        person_id,
        bool_or(reached_confirmation) as converted,
        list_distinct(list(channel)) as channels
    from visitor_sessions
    group by person_id
),

channels as (
    select channel
    from {{ ref('dim_channel') }}
    where channel <> 'other'
),

channel_flags as (
    select
        j.person_id,
        j.converted,
        c.channel,
        list_contains(j.channels, c.channel) as touched
    from journeys as j
    cross join channels as c
),

rates as (
    select
        channel,
        count(*) filter (where touched) as journeys_with,
        avg(converted::int) filter (where touched) as cvr_with,
        count(*) filter (where not touched) as journeys_without,
        avg(converted::int) filter (where not touched) as cvr_without
    from channel_flags
    group by channel
)

select
    channel,
    journeys_with,
    round(cvr_with, 4) as conversion_rate_with,
    journeys_without,
    round(cvr_without, 4) as conversion_rate_without,
    round(cvr_with / nullif(cvr_without, 0), 2) as relative_lift,
    -- two-proportion z statistic for the difference in conversion rates
    round(
        (cvr_with - cvr_without) / sqrt(
            (
                (cvr_with * journeys_with + cvr_without * journeys_without)
                / (journeys_with + journeys_without)
            )
            * (
                1 - (cvr_with * journeys_with + cvr_without * journeys_without)
                / (journeys_with + journeys_without)
            )
            * (1.0 / journeys_with + 1.0 / journeys_without)
        ),
        1
    ) as z_score
from rates
