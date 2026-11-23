{#
    Identity resolution with two ASOF joins on the device's sign-in history:
      1. the latest sign-in at or before the end of the session (who was using the device), else
      2. the next sign-in after the session (anonymous browsing that led to a sign-in).
    Shared household devices therefore credit each session to whoever was signed in at
    the time, not to whoever signed in first or last.
#}
with sessions as (
    select * from {{ ref('int_sessions') }}
),

logins as (
    select
        anonymous_id,
        customer_id,
        logged_in_at
    from {{ ref('stg_logins') }}
)

select
    s.*,
    coalesce(prior_login.customer_id, next_login.customer_id) as customer_id,
    case
        when prior_login.customer_id is not null then 'signed_in'
        when next_login.customer_id is not null then 'back_filled'
        else 'anonymous'
    end as identity_source
from sessions as s
asof left join logins as prior_login
    on
        s.anonymous_id = prior_login.anonymous_id
        and s.session_end >= prior_login.logged_in_at
asof left join logins as next_login
    on
        s.anonymous_id = next_login.anonymous_id
        and s.session_start <= next_login.logged_in_at
