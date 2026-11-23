-- Campaign catalogue as exported from the ad platforms (one row per campaign).
-- cpc_pence is the average cost per click used to synthesise the spend feed.
select
    c.campaign_id,
    c.platform,
    c.utm_source,
    c.utm_medium,
    c.utm_campaign,
    c.true_channel,
    c.cpc_pence,
    cast(c.launched_on as date) as launched_on
from (
    values
    (
        'GADS-BR-01',
        'Google Ads',
        'google',
        'cpc',
        'brand_core',
        'paid_search_brand',
        55,
        '2025-01-01'
    ),
    (
        'BING-BR-01',
        'Microsoft Ads',
        'bing',
        'cpc',
        'brand_core_bing',
        'paid_search_brand',
        48,
        '2025-01-01'
    ),
    (
        'GADS-GN-01',
        'Google Ads',
        'google',
        'cpc',
        'generic_throws_blankets',
        'paid_search_generic',
        150,
        '2025-09-01'
    ),
    (
        'GADS-GN-02',
        'Google Ads',
        'google',
        'cpc',
        'generic_candles_diffusers',
        'paid_search_generic',
        135,
        '2025-09-01'
    ),
    (
        'BING-GN-01',
        'Microsoft Ads',
        'bing',
        'cpc',
        'generic_homeware',
        'paid_search_generic',
        110,
        '2025-09-01'
    ),
    (
        'META-PS-01',
        'Meta',
        'facebook',
        'paid_social',
        'aw26_autumn_lookbook',
        'paid_social',
        95,
        '2026-05-20'
    ),
    (
        'META-PS-02',
        'Meta',
        'instagram',
        'paid_social',
        'aw26_reels_cosy_nights',
        'paid_social',
        90,
        '2026-05-20'
    ),
    (
        'TTK-PS-01',
        'TikTok',
        'tiktok',
        'paid_social',
        'creator_hauls_q3',
        'paid_social',
        70,
        '2026-06-01'
    ),
    (
        'GDN-DS-01',
        'Google Ads',
        'gdn',
        'display',
        'prospecting_display',
        'display',
        40,
        '2026-01-10'
    ),
    (
        'CRT-DS-01',
        'Criteo',
        'criteo',
        'display',
        'retargeting_dynamic',
        'display',
        75,
        '2026-01-10'
    ),
    ('AWIN-AF-01', 'Awin', 'awin', 'affiliate', 'voucher_partners', 'affiliate', 45, '2025-03-01'),
    ('KLAV-EM-01', 'Klaviyo', 'klaviyo', 'email', 'weekly_newsletter', 'email', 0, '2024-01-01'),
    ('KLAV-EM-02', 'Klaviyo', 'klaviyo', 'email', 'abandoned_basket_flow', 'email', 0, '2024-01-01')
) as c (
    campaign_id,
    platform,
    utm_source,
    utm_medium,
    utm_campaign,
    true_channel,
    cpc_pence,
    launched_on
)
