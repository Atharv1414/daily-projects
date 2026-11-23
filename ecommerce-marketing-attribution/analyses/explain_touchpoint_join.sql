-- Run with EXPLAIN ANALYZE to inspect how DuckDB executes the lookback range join that
-- builds conversion paths (equality on customer plus two inequalities on time).
select
    o.order_id,
    s.session_id
from {{ ref('int_conversions') }} as o
inner join {{ ref('int_sessions_stitched') }} as s
    on
        o.customer_id = s.customer_id
        and o.ordered_at >= s.session_start
        and o.ordered_at - to_days({{ var('lookback_days') }}) < s.session_start
