{#
    Range join: every stitched session of the buyer that happened in the lookback window
    before the order, and after their previous order (so a repeat purchase does not
    re-credit the touches that drove the first one).
#}
with touches as (
    select
        o.order_id,
        o.customer_id,
        o.ordered_at,
        o.net_revenue_gbp,
        o.order_sequence,
        s.session_id,
        s.session_start,
        s.channel,
        s.campaign_id,
        date_diff('second', s.session_start, o.ordered_at) / 86400.0 as days_before_conversion
    from {{ ref('int_conversions') }} as o
    inner join {{ ref('int_sessions_stitched') }} as s
        on
            o.customer_id = s.customer_id
            and o.ordered_at >= s.session_start
            and s.session_start > o.ordered_at - to_days({{ var('lookback_days') }})
            and s.session_start > coalesce(o.previous_ordered_at, timestamp '1900-01-01')
)

select
    *,
    row_number() over (partition by order_id order by session_start, session_id) as touch_position,
    count(*) over (partition by order_id) as touch_count,
    -- position among non-direct touches, used by last-non-direct
    case
        when channel <> 'direct' then
            row_number() over (
                partition by order_id, channel <> 'direct'
                order by session_start desc, session_id asc
            )
    end as non_direct_rank_from_end,
    count(*) filter (where channel <> 'direct') over (partition by order_id) as non_direct_count
from touches
