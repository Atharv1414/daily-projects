select
    campaign_id,
    platform,
    lower(utm_campaign) as utm_campaign,
    true_channel as platform_channel,
    cpc_pence,
    launched_on
from {{ ref('raw_campaigns') }}
