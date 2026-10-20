-- CAE sector series: spend and transaction counts side by side, per
-- geography (NUTS III and above only), month and CAE category.
select
    geo_code,
    month,
    breakdown_code as sector_code,
    any_value(breakdown_name) as sector_name,
    max(value) filter (where measure = 'spend_eur') as spend_eur,
    max(value) filter (where measure = 'transactions') as transactions,
    max(retrieved_utc) as source_retrieved_utc
from {{ ref('int_observations__labelled') }}
where breakdown = 'sector'
group by geo_code, month, breakdown_code
