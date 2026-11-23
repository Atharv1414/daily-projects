-- Checkout requires sign-in, so every order's customer must own at least one touch.
select order_id
from {{ ref('fct_orders') }}
where touch_count = 0
