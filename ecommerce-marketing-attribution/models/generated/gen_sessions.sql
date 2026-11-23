{#
    Generator internals: the "ground truth" customer journeys behind the raw feeds.
    Staging never reads this model; it exists so raw_* feeds stay consistent with each
    other and so tests can check that sessionisation recovers the true sessions.

    Story baked into the data (what the analysis should rediscover):
      * paid social and display start journeys; brand search, direct and email end them
      * having paid social or email anywhere in the journey genuinely raises conversion
      * ~30% of first-time buyers come back on a new device and buy again
#}
with visitors as (
    select
        range as visitor_n,
        'anon-' || lpad(cast(range as varchar), 7, '0') as anonymous_id,
        {{ rnd('range', 'start', var('days') - 10) }} as start_day,
        {{ rnd('range', 'nsess', 100) }} as nsess_roll,
        {{ rnd('range', 'known', 100) }} < 7 as is_known_customer,
        case
            when {{ rnd('range', 'device', 100) }} < 64 then 'mobile'
            when {{ rnd('range', 'device', 100) }} < 88 then 'desktop'
            else 'tablet'
        end as device_type
    from range(1, {{ var('visitor_count') }} + 1)
),

visitor_sessions as (
    select
        visitor_n,
        anonymous_id,
        start_day,
        is_known_customer,
        device_type,
        case
            when nsess_roll < 42 then 1
            when nsess_roll < 62 then 2
            when nsess_roll < 76 then 3
            when nsess_roll < 86 then 4
            when nsess_roll < 92 then 5
            when nsess_roll < 96 then 6
            else 7 + nsess_roll % 4
        end as n_sessions
    from visitors
),

exploded as (
    select
        v.*,
        unnest(range(1, v.n_sessions + 1)) as session_k
    from visitor_sessions as v
),

timed as (
    select
        *,
        case
            when session_k = 1 then 0
            when {{ rnd('visitor_n, session_k', 'gap', 100) }} < 40 then 0
            when {{ rnd('visitor_n, session_k', 'gap', 100) }} < 65 then 1
            when {{ rnd('visitor_n, session_k', 'gap', 100) }} < 80 then 2 + session_k % 2
            else 4 + {{ rnd('visitor_n, session_k', 'gap2', 6) }}
        end as gap_days,
        case
            when {{ rnd('visitor_n, session_k', 'hour', 100) }} < 10 then 7 + session_k % 3
            when {{ rnd('visitor_n, session_k', 'hour', 100) }} < 30 then 12 + session_k % 3
            when {{ rnd('visitor_n, session_k', 'hour', 100) }} < 75
                then 18 + {{ rnd('visitor_n, session_k', 'eve', 5) }}
            else {{ rnd('visitor_n, session_k', 'any', 24) }}
        end as start_hour,
        {{ rnd('visitor_n, session_k', 'chan', 100) }} as chan_roll,
        case
            when n_sessions = 1 then 'single'
            when session_k = 1 then 'first'
            when session_k = n_sessions then 'last'
            else 'mid'
        end as journey_stage
    from exploded
),

channelled as (
    select
        *,
        cast(start_day + sum(gap_days) over (
            partition by visitor_n order by session_k rows unbounded preceding
        ) as integer) as session_day,
        case journey_stage
            when 'first'
                then
                    case
                        when chan_roll < 30 then 'paid_social'
                        when chan_roll < 50 then 'organic_search'
                        when chan_roll < 62 then 'display'
                        when chan_roll < 77 then 'paid_search_generic'
                        when chan_roll < 84 then 'affiliate'
                        when chan_roll < 92 then 'referral'
                        else 'direct'
                    end
            when 'mid'
                then
                    case
                        when chan_roll < 22 then 'email'
                        when chan_roll < 40 then 'organic_search'
                        when chan_roll < 55 then 'paid_social'
                        when chan_roll < 67 then 'paid_search_generic'
                        when chan_roll < 77 then 'display'
                        when chan_roll < 90 then 'direct'
                        else 'affiliate'
                    end
            when 'last'
                then
                    case
                        when chan_roll < 32 then 'paid_search_brand'
                        when chan_roll < 57 then 'direct'
                        when chan_roll < 74 then 'email'
                        when chan_roll < 85 then 'organic_search'
                        when chan_roll < 93 then 'affiliate'
                        else 'paid_search_generic'
                    end
            else
                case
                    when chan_roll < 25 then 'organic_search'
                    when chan_roll < 45 then 'direct'
                    when chan_roll < 60 then 'paid_social'
                    when chan_roll < 72 then 'paid_search_generic'
                    when chan_roll < 82 then 'paid_search_brand'
                    when chan_roll < 90 then 'display'
                    else 'referral'
                end
        end as true_channel
    from timed
),

journeys as (
    select
        visitor_n,
        max(n_sessions) as n_sessions,
        bool_or(true_channel = 'paid_social') as has_social,
        bool_or(true_channel = 'email') as has_email,
        bool_or(true_channel = 'display') as has_display,
        bool_or(true_channel = 'paid_search_generic') as has_generic
    from channelled
    group by visitor_n
),

conversion as (
    select
        visitor_n,
        -- conversion probability in 0.1% units
        {{ rnd('visitor_n', 'conv', 1000) }} < (
            case
                when n_sessions = 1 then 12
                when n_sessions = 2 then 35
                when n_sessions = 3 then 60
                else 85
            end
            + case when has_social then 40 else 0 end
            + case when has_email then 30 else 0 end
            + case when has_display then 10 else 0 end
            + case when has_generic then 15 else 0 end
        ) as converts
    from journeys
),

first_journeys as (
    select
        c.visitor_n,
        c.anonymous_id,
        c.device_type,
        c.session_k,
        c.n_sessions,
        c.true_channel,
        timestamp '{{ var("start_date") }}'
        + to_days(c.session_day)
        + to_hours(c.start_hour)
        + to_seconds({{ rnd('c.visitor_n, c.session_k', 'sec', 3600) }}) as session_start,
        coalesce(j.converts and c.session_k = c.n_sessions, false) as converts,
        case
            when j.converts or c.is_known_customer
                then 'C' || lpad(cast(c.visitor_n as varchar), 7, '0')
        end as customer_id,
        case
            when j.converts and c.session_k = c.n_sessions then 'checkout'
            when c.is_known_customer and c.session_k = 1 then 'account'
        end as login_reason,
        'first' as journey_type
    from channelled as c
    inner join conversion as j on c.visitor_n = j.visitor_n
    where c.session_day < {{ var('days') }}
),

buyers as (
    select
        visitor_n,
        anonymous_id,
        customer_id,
        device_type,
        session_start as first_order_at
    from first_journeys
    where converts and {{ rnd('visitor_n', 'repeat', 100) }} < 32
),

repeat_sessions as (
    select
        b.*,
        unnest(range(1, 1 + 1 + {{ rnd('b.visitor_n', 'rn', 3) }})) as session_k,
        1 + 1 + {{ rnd('b.visitor_n', 'rn', 3) }} - 1 as n_sessions
    from buyers as b
),

repeat_journeys as (
    select
        r.visitor_n,
        case
            -- 4% are a shared household device that another visitor also uses
            when {{ rnd('r.visitor_n', 'shared', 100) }} < 4
                then 'anon-' || lpad(cast(r.visitor_n + 1 as varchar), 7, '0')
            when {{ rnd('r.visitor_n', 'samedev', 100) }} < 20 then r.anonymous_id
            else 'anon-r' || lpad(cast(r.visitor_n as varchar), 7, '0')
        end as anonymous_id,
        r.device_type,
        100 + r.session_k as session_k,
        r.n_sessions,
        case
            when r.session_k = r.n_sessions
                then
                    case
                        when {{ rnd('r.visitor_n', 'rlast', 100) }} < 45 then 'email'
                        when {{ rnd('r.visitor_n', 'rlast', 100) }} < 75 then 'direct'
                        else 'paid_search_brand'
                    end
            when {{ rnd('r.visitor_n, r.session_k', 'rmid', 100) }} < 50 then 'email'
            when {{ rnd('r.visitor_n, r.session_k', 'rmid', 100) }} < 75 then 'paid_social'
            else 'organic_search'
        end as true_channel,
        r.first_order_at
        + to_days(20 + {{ rnd('r.visitor_n', 'rdelay', 70) }} + r.session_k * 2)
        + to_seconds({{ rnd('r.visitor_n, r.session_k', 'rsec', 7200) }}) as session_start,
        r.session_k = r.n_sessions and {{ rnd('r.visitor_n', 'rconv', 100) }} < 58 as converts,
        r.customer_id,
        case
            when r.session_k = r.n_sessions and {{ rnd('r.visitor_n', 'rconv', 100) }} < 58
                then 'checkout'
            when r.session_k = 1 and {{ rnd('r.visitor_n', 'rlogin', 100) }} < 60 then 'account'
        end as login_reason,
        'repeat' as journey_type
    from repeat_sessions as r
)

select
    md5(anonymous_id || '|' || cast(visitor_n as varchar) || '|' || cast(session_k as varchar))
        as true_session_id,
    visitor_n,
    anonymous_id,
    customer_id,
    device_type,
    journey_type,
    session_k,
    true_channel,
    session_start,
    converts,
    login_reason,
    -- 38% of sessions bounce (one page view); the rest browse 2-14 pages
    case
        when converts then 6 + {{ rnd('visitor_n, session_k', 'hits', 8) }}
        when {{ rnd('visitor_n, session_k', 'bounce', 100) }} < 38 then 1
        else 2 + {{ rnd('visitor_n, session_k', 'hits', 13) }}
    end as n_hits,
    -- 2% of sessions contain a 35-55 minute idle gap: GA-style timeout splits them in two
    {{ rnd('visitor_n, session_k', 'idle', 100) }} < 2 as has_idle_gap
from first_journeys
where session_start < timestamp '{{ var("start_date") }}' + to_days({{ var('days') }})
union all
select
    md5(anonymous_id || '|' || cast(visitor_n as varchar) || '|' || cast(session_k as varchar))
        as true_session_id,
    visitor_n,
    anonymous_id,
    customer_id,
    device_type,
    journey_type,
    session_k,
    true_channel,
    session_start,
    converts,
    login_reason,
    case
        when converts then 6 + {{ rnd('visitor_n, session_k', 'hits', 8) }}
        else 2 + {{ rnd('visitor_n, session_k', 'hits', 6) }}
    end as n_hits,
    false as has_idle_gap
from repeat_journeys
where session_start < timestamp '{{ var("start_date") }}' + to_days({{ var('days') }})
