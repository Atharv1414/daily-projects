-- One row per order x touch x model: the credit and revenue each touch earns.
select
    md5(order_id || '|' || session_id || '|' || model) as attribution_id,
    order_id,
    customer_id,
    ordered_at,
    order_sequence,
    session_id,
    cast(session_start as date) as touch_date,
    channel,
    campaign_id,
    touch_position,
    touch_count,
    model,
    weight as conversion_credit,
    weight * net_revenue_gbp as attributed_revenue_gbp
from {{ ref('int_attribution_weights') }}
