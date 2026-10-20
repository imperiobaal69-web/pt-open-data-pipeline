{%- set measures = ["spend_eur", "spend_in_person_eur", "spend_online_eur", "spend_domestic_cards_eur",
                     "spend_foreign_cards_eur", "transactions", "transactions_in_person", "transactions_online"] -%}
-- Cross-level additivity: for every NUTS III region whose municipalities are
-- all loaded, each measure summed over its municipalities must equal the
-- region's published value. Known published inconsistencies are excluded.
with municipal as (
    select
        geo.nuts3_geo_code as geo_code,
        fct.month,
        count(*) as municipalities_loaded
        {%- for m in measures %},
        sum(fct.{{ m }}) as {{ m }}{% endfor %}
    from {{ ref('fct_card_purchases_monthly') }} as fct
    inner join {{ ref('dim_geography') }} as geo
        on fct.geo_code = geo.geo_code
    where geo.geo_level_name = 'municipality'
    group by geo.nuts3_geo_code, fct.month
),

complete as (
    select municipal.*
    from municipal
    inner join {{ ref('nuts3_municipality_counts') }} as expected
        on municipal.geo_code = expected.nuts3_geo_code
        and municipal.municipalities_loaded = expected.municipalities
)

{%- for m in measures %}
{{ "union all" if not loop.first }}
select complete.geo_code, complete.month, '{{ m }}' as measure,
       complete.{{ m }} as municipal_sum, region.{{ m }} as region_value
from complete
inner join {{ ref('fct_card_purchases_monthly') }} as region
    on complete.geo_code = region.geo_code and complete.month = region.month
left join {{ ref('known_source_issues') }} as issue
    on issue.geo_code = region.geo_code and issue.month = region.month and issue.fct_column = '{{ m }}'
where issue.geo_code is null and abs(complete.{{ m }} - region.{{ m }}) > 1
{%- endfor %}
