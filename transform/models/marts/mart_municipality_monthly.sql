-- Municipality-level monthly view with month-on-month and year-on-year
-- change. Prior periods are found by exact calendar offset (self-join on
-- month - 1 / month - 12), not with LAG(): if a prior month is missing,
-- the change is NULL instead of being computed against the wrong month.
-- A prior value of zero also yields NULL rather than a division error.
with facts as (
    select fct.*, geo.geo_name, geo.nuts3_geo_code
    from {{ ref('fct_card_purchases_monthly') }} as fct
    inner join {{ ref('dim_geography') }} as geo
        on fct.geo_code = geo.geo_code
    where geo.geo_level_name = 'municipality'
)

select
    cur.geo_code,
    cur.geo_name,
    cur.nuts3_geo_code,
    nuts3.geo_name as nuts3_name,
    cur.month,
    cur.spend_eur,
    cur.transactions,
    cur.avg_ticket_eur,
    cur.online_share,
    cur.foreign_card_share,
    prev_month.spend_eur as spend_eur_prev_month,
    prev_year.spend_eur as spend_eur_prev_year,
    round(cur.spend_eur / nullif(prev_month.spend_eur, 0) - 1, 6) as spend_mom_change,
    round(cur.spend_eur / nullif(prev_year.spend_eur, 0) - 1, 6) as spend_yoy_change,
    round(cur.foreign_card_share - prev_year.foreign_card_share, 6) as foreign_card_share_yoy_diff,
    round(cur.online_share - prev_year.online_share, 6) as online_share_yoy_diff
from facts as cur
left join facts as prev_month
    on cur.geo_code = prev_month.geo_code
    and prev_month.month = cast(cur.month - interval 1 month as date)
left join facts as prev_year
    on cur.geo_code = prev_year.geo_code
    and prev_year.month = cast(cur.month - interval 12 month as date)
left join {{ ref('dim_geography') }} as nuts3
    on cur.nuts3_geo_code = nuts3.geo_code
