-- One row per real order: latest webhook version wins, internal test orders removed.
with latest as (
    select *
    from {{ ref('raw_orders') }}
    qualify row_number() over (partition by order_id order by _loaded_at desc) = 1
)

select
    order_id,
    customer_id,
    ordered_at,
    item_count,
    status,
    discount_code,
    {{ pence_to_pounds('gross_pence') }} as gross_gbp,
    {{ pence_to_pounds('discount_pence') }} as discount_gbp,
    {{ pence_to_pounds('delivery_pence') }} as delivery_gbp,
    -- Attributable revenue: merchandise net of discount; refunds count as zero.
    case
        when status = 'completed' then {{ pence_to_pounds('gross_pence - discount_pence') }}
        else 0
    end as net_revenue_gbp
from latest
where
    not customer_email like '%.test'
    and status <> 'cancelled'
