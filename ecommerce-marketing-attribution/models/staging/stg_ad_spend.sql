-- Daily cost per campaign. Platforms restate spend; the most recent load is the truth.
select
    campaign_id,
    spend_date,
    clicks,
    impressions,
    {{ pence_to_pounds('spend_pence') }} as spend_gbp
from {{ ref('raw_ad_spend') }}
qualify row_number() over (
    partition by campaign_id, spend_date order by _loaded_at desc
) = 1
