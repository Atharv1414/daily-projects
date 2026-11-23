-- Identity events from the e-commerce platform: a customer signs in on a device
-- (anonymous_id). Checkout always requires sign-in; some customers sign in to browse.
select
    md5('login|' || true_session_id) as login_id,
    anonymous_id,
    customer_id,
    session_start + to_seconds(20 + {{ rnd('true_session_id', 'lg', 240) }}) as logged_in_at,
    login_reason
from {{ ref('gen_sessions') }}
where login_reason is not null and customer_id is not null
