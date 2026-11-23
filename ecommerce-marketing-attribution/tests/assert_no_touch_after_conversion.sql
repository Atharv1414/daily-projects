-- A touch can only be credited if it happened before the order, inside the lookback window.
select
    order_id,
    session_id,
    days_before_conversion
from {{ ref('int_conversion_paths') }}
where
    session_start > ordered_at
    or days_before_conversion > {{ var('lookback_days') }}
