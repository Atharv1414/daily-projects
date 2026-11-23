{# Parenthesised so expressions such as 'gross_pence - discount_pence' convert correctly. #}
{% macro pence_to_pounds(column_name) -%}
    round(({{ column_name }}) / 100.0, 2)
{%- endmacro %}
