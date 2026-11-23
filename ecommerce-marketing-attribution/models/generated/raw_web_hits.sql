{#
    Raw clickstream as delivered by the tracking tag: one row per page view, no session id.
    Campaign parameters and the referrer appear only on the landing hit of a visit,
    exactly like real web analytics feeds. Messiness included on purpose:
      * inconsistent UTM casing and aliases ('Facebook ', 'fb', 'CPC', 'paid-social')
      * 0.5% duplicate hits (tag double-fire, same hit_id)
      * crawler traffic that must be filtered out
      * idle gaps inside visits that a 30-minute timeout must split
#}
with campaigns as (
    select
        *,
        row_number() over (partition by true_channel order by campaign_id) as idx,
        count(*) over (partition by true_channel) as n_in_channel
    from {{ ref('raw_campaigns') }}
),

sessions as (
    select
        s.*,
        {{ rnd('s.true_session_id', 'camp', 1000) }} as camp_roll
    from {{ ref('gen_sessions') }} as s
),

with_campaign as (
    select
        s.*,
        c.utm_source,
        c.utm_medium,
        c.utm_campaign
    from sessions as s
    left join campaigns as c
        on
            s.true_channel = c.true_channel
            and c.idx = 1 + s.camp_roll % c.n_in_channel
),

hits as (
    select
        w.*,
        unnest(range(w.n_hits)) as hit_n
    from with_campaign as w
),

timed as (
    select
        *,
        session_start
        + to_seconds(cast(
            sum(
                case
                    when hit_n = 0 then 0 else
                        15 + {{ rnd('true_session_id, hit_n', 'dwell', 225) }}
                end
            ) over (partition by true_session_id order by hit_n rows unbounded preceding)
            as bigint
        ))
        + case
            when has_idle_gap and n_hits > 1 and hit_n >= n_hits // 2
                then to_minutes(35 + {{ rnd('true_session_id', 'idle', 20) }})
            else to_minutes(0)
        end as hit_at
    from hits
),

shaped as (
    select
        md5(true_session_id || '#' || cast(hit_n as varchar)) as hit_id,
        anonymous_id,
        hit_at,
        device_type,
        case
            when converts and hit_n = n_hits - 1 then '/checkout/confirmation'
            when converts and hit_n = n_hits - 2 then '/checkout/payment'
            when converts and hit_n = n_hits - 3 then '/basket'
            when hit_n = 0 and true_channel in ('direct', 'paid_search_brand') then '/'
            when {{ rnd('true_session_id, hit_n', 'page', 10) }} < 4
                then
                    '/c/'
                    || ['throws', 'candles', 'cushions', 'tableware'][
                        1 + {{ rnd('true_session_id, hit_n', 'cat', 4) }}
                    ]
            else
                '/p/sku-'
                || lpad(cast({{ rnd('true_session_id, hit_n', 'sku', 400) }} as varchar), 4, '0')
        end as page_path,
        case
            when hit_n = 0 then
                case {{ rnd('true_session_id', 'case', 6) }}
                    when 0 then upper(utm_source)
                    when 1 then utm_source || ' '
                    when
                        2
                        then
                            case utm_source
                                when 'facebook' then 'fb' when 'instagram' then 'IG' else utm_source
                            end
                    else utm_source
                end
        end as utm_source,
        case
            when hit_n = 0 then
                case {{ rnd('true_session_id', 'mcase', 5) }}
                    when 0 then upper(utm_medium)
                    when 1 then replace(utm_medium, '_', '-')
                    else utm_medium
                end
        end as utm_medium,
        case when hit_n = 0 then utm_campaign end as utm_campaign,
        case
            when hit_n > 0 then null
            when true_channel = 'organic_search'
                then
                    ['www.google.co.uk', 'www.google.com', 'www.bing.com', 'duckduckgo.com'][
                        1 + {{ rnd('true_session_id', 'se', 4) }}
                    ]
            when true_channel = 'referral'
                then
                    ['uk.pinterest.com', 'www.reddit.com', 'cosyhomeblog.co.uk'][
                        1 + {{ rnd('true_session_id', 'ref', 3) }}
                    ]
            when true_channel in ('paid_social') then 'l.facebook.com'
        end as referrer_domain,
        case device_type
            when
                'mobile'
                then 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) Mobile Safari'
            when 'tablet' then 'Mozilla/5.0 (iPad; CPU OS 18_1 like Mac OS X) Safari'
            else 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0'
        end as user_agent
    from timed
),

bots as (
    select
        md5('bot#' || cast(b.range as varchar) || '#' || cast(h.hit as varchar)) as hit_id,
        'anon-bot' || lpad(cast(b.range as varchar), 5, '0') as anonymous_id,
        timestamp '{{ var("start_date") }}'
        + to_days({{ rnd('b.range', 'bday', var('days')) }})
        + to_seconds(h.hit * 3) as hit_at,
        'desktop' as device_type,
        '/p/sku-' || lpad(cast(h.hit as varchar), 4, '0') as page_path,
        null as utm_source,
        null as utm_medium,
        null as utm_campaign,
        null as referrer_domain,
        'Mozilla/5.0 (compatible; ' || ['Googlebot/2.1', 'AhrefsBot/7.0', 'SemrushBot/7'][
            1 + {{ rnd('b.range', 'ua', 3) }}
        ] || ')' as user_agent
    from range(1, {{ var('visitor_count') }} // 40 + 1) as b
    cross join lateral (select unnest(range(20 + {{ rnd('b.range', 'bhits', 40) }})) as hit) as h
)

select * from shaped
union all
select * from bots
union all
-- tag double-fires: an exact copy of 0.5% of hits
select * from shaped
where {{ rnd('hit_id', 'dup', 1000) }} < 5
