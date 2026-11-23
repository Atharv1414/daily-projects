{#
    Deterministic pseudo-random integer in [0, n) derived from a key and a salt.
    hash() is stable across runs and platforms, so the generated data is reproducible
    without any random-seed state.
#}
{% macro rnd(key, salt, n) -%}
    cast(hash({{ key }}, '{{ salt }}') % {{ n }} as integer)
{%- endmacro %}
