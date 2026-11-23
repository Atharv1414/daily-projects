-- Every model must hand out exactly the revenue of the orders it attributes: no credit is
-- created or lost between fct_orders and fct_attributed_conversions.
with attributed as (
    select
        model,
        sum(attributed_revenue_gbp) as revenue_gbp
    from {{ ref('fct_attributed_conversions') }}
    group by model
),

orders as (
    select sum(net_revenue_gbp) as revenue_gbp
    from {{ ref('fct_orders') }}
    where touch_count > 0
)

select
    a.model,
    a.revenue_gbp,
    o.revenue_gbp as order_revenue_gbp
from attributed as a
cross join orders as o
where abs(a.revenue_gbp - o.revenue_gbp) > 0.01
