{#
    Orders as exported from the shop platform. Messiness: re-sent orders (same order_id,
    later _loaded_at), internal test orders, cancellations and refunds.
#}
with converting as (
    select
        s.*,
        row_number() over (order by s.session_start, s.true_session_id) as order_n
    from {{ ref('gen_sessions') }} as s
    where s.converts
),

orders as (
    select
        'HF-' || lpad(cast(100000 + order_n as varchar), 7, '0') as order_id,
        customer_id,
        session_start + to_minutes(10 + {{ rnd('true_session_id', 'ordmin', 25) }}) as ordered_at,
        1 + {{ rnd('true_session_id', 'items', 4) }} as item_count,
        -- right-skewed basket value: most £25-£90, a tail of £150-£400 home makeovers
        case
            when {{ rnd('true_session_id', 'big', 100) }} < 8
                then 15000 + {{ rnd('true_session_id', 'bigv', 25000) }}
            else 2500 + {{ rnd('true_session_id', 'val', 6500) }}
        end as gross_pence,
        case
            when {{ rnd('true_session_id', 'disc', 100) }} < 22
                then 'AUTUMN15'
        end as discount_code,
        case
            when {{ rnd('true_session_id', 'status', 100) }} < 2 then 'cancelled'
            when {{ rnd('true_session_id', 'status', 100) }} < 8 then 'refunded'
            else 'completed'
        end as status,
        {{ rnd('true_session_id', 'test', 1000) }} < 3 as is_test_order,
        journey_type
    from converting
),

priced as (
    select
        order_id,
        customer_id,
        ordered_at,
        item_count,
        gross_pence,
        discount_code,
        case when discount_code is not null then gross_pence * 15 // 100 else 0 end
            as discount_pence,
        case when gross_pence >= 5000 then 0 else 395 end as delivery_pence,
        status,
        case
            when is_test_order then 'qa+' || order_id || '@hearthandfield.test'
            else lower(customer_id) || '@example.co.uk'
        end as customer_email,
        ordered_at + to_minutes(2) as _loaded_at
    from orders
)

select * from priced
union all
-- 0.6% of orders are re-sent by the platform webhook an hour later
select
    order_id,
    customer_id,
    ordered_at,
    item_count,
    gross_pence,
    discount_code,
    discount_pence,
    delivery_pence,
    status,
    customer_email,
    _loaded_at + to_hours(1) as _loaded_at
from priced
where {{ rnd('order_id', 'resend', 1000) }} < 6
