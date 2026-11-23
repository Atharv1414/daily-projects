select
    login_id,
    anonymous_id,
    customer_id,
    logged_in_at,
    login_reason
from {{ ref('raw_logins') }}
