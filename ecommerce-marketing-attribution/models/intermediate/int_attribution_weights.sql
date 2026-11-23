{#
    Six attribution models in long format: one row per (order, touch, model) with the
    share of the conversion that touch earns. Weights sum to 1 per order and model
    (enforced by the weights_sum_to_one test).

      first_touch      100% to the first touch
      last_touch       100% to the last touch
      last_non_direct  100% to the last non-direct touch (last touch if all are direct)
      linear           equal split
      time_decay       2^(-days_before / half_life), normalised
      position_based   40% first, 40% last, 20% shared by the middle (U-shaped)
#}
with paths as (
    select * from {{ ref('int_conversion_paths') }}
),

raw_weights as (
    select
        *,
        case when touch_position = 1 then 1.0 else 0.0 end as w_first_touch,
        case when touch_position = touch_count then 1.0 else 0.0 end as w_last_touch,
        case
            when non_direct_count = 0
                then case when touch_position = touch_count then 1.0 else 0.0 end
            when non_direct_rank_from_end = 1 then 1.0
            else 0.0
        end as w_last_non_direct,
        1.0 / touch_count as w_linear,
        pow(2, -days_before_conversion / {{ var('time_decay_half_life_days') }}) as decay_raw,
        case
            when touch_count = 1 then 1.0
            when touch_count = 2 then 0.5
            when touch_position in (1, touch_count) then 0.4
            else 0.2 / (touch_count - 2)
        end as w_position_based
    from paths
),

normalised as (
    select
        *,
        decay_raw / sum(decay_raw) over (partition by order_id) as w_time_decay
    from raw_weights
)

select
    order_id,
    customer_id,
    ordered_at,
    order_sequence,
    net_revenue_gbp,
    session_id,
    session_start,
    channel,
    campaign_id,
    touch_position,
    touch_count,
    days_before_conversion,
    model,
    weight
from normalised
unpivot (
    weight for model in (
        w_first_touch as first_touch,
        w_last_touch as last_touch,
        w_last_non_direct as last_non_direct,
        w_linear as linear,
        w_time_decay as time_decay,
        w_position_based as position_based
    )
)
