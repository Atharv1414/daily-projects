-- Crawler sessions and QA orders must never reach the analytical layer.
select session_id as offending_id
from {{ ref('int_sessions') }}
where anonymous_id like 'anon-bot%'
union all
select fct.order_id
from {{ ref('fct_orders') }} as fct
where fct.order_id in (
    select src.order_id from {{ ref('raw_orders') }} as src
    where src.customer_email like '%.test'
)
