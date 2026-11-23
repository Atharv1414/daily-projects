{#
    Generic test: for every group, the weights in `column_name` must sum to 1
    (within a tolerance). Used to prove every attribution model distributes exactly
    one conversion's worth of credit per order.
#}
{% test weights_sum_to_one(model, column_name, group_by, tolerance=0.000001) %}
    select
        {{ group_by | join(', ') }},
        sum({{ column_name }}) as total_weight
    from {{ model }}
    group by {{ group_by | join(', ') }}
    having abs(sum({{ column_name }}) - 1) > {{ tolerance }}
{% endtest %}
