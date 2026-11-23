{#
    Most common converting journeys. Consecutive repeats of a channel are collapsed
    ("email > email > direct" becomes "email > direct"), a gaps-and-islands step, so
    the paths describe channel transitions rather than visit counts.
#}
with touches as (
    select
        order_id,
        touch_position,
        channel,
        net_revenue_gbp,
        days_before_conversion,
        lag(channel) over (partition by order_id order by touch_position) as previous_channel
    from {{ ref('int_conversion_paths') }}
),

collapsed as (
    select
        order_id,
        string_agg(channel, ' > ' order by touch_position) as channel_path,
        count(*) as distinct_steps,
        max(net_revenue_gbp) as revenue_gbp,
        max(days_before_conversion) as days_to_convert
    from touches
    where previous_channel is distinct from channel
    group by order_id
)

select
    channel_path,
    distinct_steps,
    count(*) as conversions,
    round(sum(revenue_gbp), 2) as revenue_gbp,
    round(avg(revenue_gbp), 2) as avg_order_value_gbp,
    round(median(days_to_convert), 2) as median_days_to_convert,
    round(count(*) / sum(count(*)) over (), 4) as share_of_conversions
from collapsed
group by channel_path, distinct_steps
qualify row_number() over (order by count(*) desc, channel_path) <= 50
