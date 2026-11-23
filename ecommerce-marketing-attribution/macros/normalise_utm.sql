{#
    Trim, lower-case and map known aliases so 'Facebook ', 'fb' and 'FB' become one
    source and 'paid-social' / 'CPC' become canonical mediums.
#}
{% macro normalise_source(column_name) -%}
    case lower(trim({{ column_name }}))
        when 'fb' then 'facebook'
        when 'ig' then 'instagram'
        when '' then null
        else lower(trim({{ column_name }}))
    end
{%- endmacro %}

{% macro normalise_medium(column_name) -%}
    nullif(replace(lower(trim({{ column_name }})), '-', '_'), '')
{%- endmacro %}
