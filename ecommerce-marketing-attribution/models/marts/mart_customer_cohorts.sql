{#
    Acquisition cohorts by first-order month and first-touch channel: how revenue per
    customer builds up month by month after the first order. A recursive CTE builds the
    month-offset spine so cohorts with no orders in a month still appear (as zero).
#}
with recursive month_offsets as (
    select 0 as months_since_first_order
    union all
    select months_since_first_order + 1
    from month_offsets
    where months_since_first_order < 4
),

customers as (
    select
        customer_id,
        date_trunc('month', ordered_at) as cohort_month,
        first_touch_channel
    from {{ ref('fct_orders') }}
    where is_first_order
),

orders as (
    select
        o.customer_id,
        c.cohort_month,
        c.first_touch_channel,
        date_diff('month', c.cohort_month, date_trunc('month', o.ordered_at))
            as months_since_first_order,
        o.net_revenue_gbp,
        o.is_first_order
    from {{ ref('fct_orders') }} as o
    inner join customers as c on o.customer_id = c.customer_id
),

cohort_sizes as (
    select
        cohort_month,
        first_touch_channel,
        count(*) as customers
    from customers
    group by all
),

grid as (
    select
        s.cohort_month,
        s.first_touch_channel,
        s.customers,
        m.months_since_first_order
    from cohort_sizes as s
    cross join month_offsets as m
    -- only offsets that have already happened by the end of the data
    where s.cohort_month + to_months(m.months_since_first_order) <= (
        select max(date_trunc('month', f.ordered_at)) from {{ ref('fct_orders') }} as f
    )
),

monthly as (
    select
        g.cohort_month,
        g.first_touch_channel,
        g.customers,
        g.months_since_first_order,
        coalesce(sum(o.net_revenue_gbp), 0) as revenue_gbp,
        count(distinct o.customer_id) filter (where not o.is_first_order) as repeat_customers
    from grid as g
    left join orders as o
        on
            g.cohort_month = o.cohort_month
            and g.first_touch_channel = o.first_touch_channel
            and g.months_since_first_order = o.months_since_first_order
    group by all
)

select
    cohort_month,
    first_touch_channel,
    customers,
    months_since_first_order,
    round(revenue_gbp, 2) as revenue_gbp,
    repeat_customers,
    round(
        sum(revenue_gbp) over (
            partition by cohort_month, first_touch_channel
            order by months_since_first_order
            rows unbounded preceding
        ) / customers,
        2
    ) as cumulative_revenue_per_customer_gbp
from monthly
