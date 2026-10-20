-- Card purchases by CAE Rev.4 section, per NUTS III region (and above) and
-- month, with each section's share of the region's total. INE publishes
-- this breakdown only from February 2026 and never below NUTS III.
with sectors as (
    select * from {{ ref('int_sector_purchases__pivoted') }}
)

select
    sec.geo_code,
    sec.month,
    sec.sector_code,
    sec.sector_name,
    sec.spend_eur,
    sec.transactions,
    round(sec.spend_eur / nullif(sec.transactions, 0), 2) as avg_ticket_eur,
    round(sec.spend_eur / nullif(total.spend_eur, 0), 6) as share_of_region_spend,
    sec.source_retrieved_utc
from sectors as sec
left join sectors as total
    on sec.geo_code = total.geo_code
    and sec.month = total.month
    and total.sector_code = 'TOT'
where sec.sector_code <> 'TOT'
