-- Sessionisation should recover the generator's true visits plus the visits that the
-- 30-minute timeout legitimately splits, within 1%. Direct return visits that start within
-- 30 minutes of the previous visit are merged by design (as GA does).
with truth as (
    select count(*) + count(*) filter (where has_idle_gap and n_hits > 1) as expected_sessions
    from {{ ref('gen_sessions') }}
),

rebuilt as (
    select count(*) as actual_sessions
    from {{ ref('int_sessions') }}
)

select
    t.expected_sessions,
    r.actual_sessions
from truth as t
cross join rebuilt as r
where abs(r.actual_sessions - t.expected_sessions) > 0.01 * t.expected_sessions
