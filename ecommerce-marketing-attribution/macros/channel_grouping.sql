{#
    Default channel grouping from (normalised) UTM parameters and the referrer, in the
    spirit of GA4's rules. Order matters: paid mediums win over referrers, and brand
    search is split from generic search by campaign naming convention.
#}
{% macro channel_grouping(source, medium, campaign, referrer) -%}
    case
        when {{ medium }} in ('cpc', 'ppc', 'paid_search') and {{ campaign }} like '%brand%'
            then 'paid_search_brand'
        when {{ medium }} in ('cpc', 'ppc', 'paid_search')
            then 'paid_search_generic'
        when {{ medium }} in ('paid_social', 'paidsocial', 'social_paid')
            or ({{ source }} in ('facebook', 'instagram', 'tiktok') and {{ medium }} = 'cpm')
            then 'paid_social'
        when {{ medium }} in ('display', 'banner', 'cpm')
            then 'display'
        when {{ medium }} = 'affiliate'
            then 'affiliate'
        when {{ medium }} = 'email'
            then 'email'
        when {{ medium }} is null
            and regexp_matches({{ referrer }}, '(^|\.)(google|bing|duckduckgo|yahoo)\.')
            then 'organic_search'
        when {{ medium }} is null and {{ referrer }} is not null
            then 'referral'
        when {{ medium }} is null and {{ referrer }} is null
            then 'direct'
        else 'other'
    end
{%- endmacro %}
