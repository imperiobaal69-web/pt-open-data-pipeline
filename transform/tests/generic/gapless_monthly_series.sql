{#-
    Fails for every series (one per value of `partition_by`) whose months are
    not a contiguous run of first-of-month dates. A missing month would make
    "previous month" comparisons silently wrong downstream.
-#}
{% test gapless_monthly_series(model, column_name, partition_by=none) %}
{%- set key = "concat_ws('|', " ~ (partition_by | join(', ')) ~ ")" if partition_by else "'all'" -%}
with months as (
    select {{ key }} as series_key, cast({{ column_name }} as date) as month
    from {{ model }}
    where {{ column_name }} is not null
    group by all
),

bounds as (
    select
        series_key,
        min(month) as first_month,
        max(month) as last_month,
        count(*) as months_present,
        datediff('month', min(month), max(month)) + 1 as months_expected,
        count(*) filter (where month <> date_trunc('month', month)) as not_month_start
    from months
    group by series_key
)

select *
from bounds
where months_present <> months_expected or not_month_start > 0
{% endtest %}
