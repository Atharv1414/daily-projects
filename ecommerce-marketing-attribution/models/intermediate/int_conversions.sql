-- Orders as conversions, with the customer's previous order to bound the lookback window.
select
    order_id,
    customer_id,
    ordered_at,
    net_revenue_gbp,
    status,
    row_number() over (partition by customer_id order by ordered_at, order_id) as order_sequence,
    lag(ordered_at) over (partition by customer_id order by ordered_at, order_id)
        as previous_ordered_at
from {{ ref('stg_orders') }}
