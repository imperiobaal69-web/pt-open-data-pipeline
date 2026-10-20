-- The CAE sections of a region must add up to the region's total.
with sections as (
    select geo_code, month, sum(spend_eur) as sections_eur, sum(transactions) as sections_n
    from {{ ref('int_sector_purchases__pivoted') }}
    where sector_code <> 'TOT'
    group by geo_code, month
)
select s.*, t.spend_eur as total_eur, t.transactions as total_n
from sections as s
inner join {{ ref('int_sector_purchases__pivoted') }} as t
    on s.geo_code = t.geo_code and s.month = t.month and t.sector_code = 'TOT'
where abs(s.sections_eur - t.spend_eur) > 1 or abs(s.sections_n - t.transactions) > 1
