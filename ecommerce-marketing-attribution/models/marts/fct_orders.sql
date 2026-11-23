-- Order grain with journey context: first and last touch, path length, time to convert.
with path_summary as (
    select
        order_id,
        max(touch_count) as touch_count,
        arg_min(channel, touch_position) as first_touch_channel,
        arg_max(channel, touch_position) as last_touch_channel,
        max(days_before_conversion) as days_from_first_touch
    from {{ ref('int_conversion_paths') }}
    group by order_id
)

select
    o.order_id,
    o.customer_id,
    o.ordered_at,
    cast(o.ordered_at as date) as order_date,
    o.status,
    o.order_sequence,
    o.order_sequence = 1 as is_first_order,
    o.net_revenue_gbp,
    coalesce(p.touch_count, 0) as touch_count,
    coalesce(p.first_touch_channel, 'unattributed') as first_touch_channel,
    coalesce(p.last_touch_channel, 'unattributed') as last_touch_channel,
    round(p.days_from_first_touch, 2) as days_from_first_touch
from {{ ref('int_conversions') }} as o
left join path_summary as p on o.order_id = p.order_id
