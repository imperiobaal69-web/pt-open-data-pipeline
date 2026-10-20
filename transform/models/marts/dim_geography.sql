-- NUTS 2024 hierarchy as published by INE, plus municipalities. INE's codes
-- are hierarchical (11A1312 = Porto, in NUTS III 11A, in NUTS II 11, in
-- NUTS I 1), so each unit's parent is a prefix of its own code.
with units as (
    select
        category_code as geo_code,
        any_value(category_name) as geo_name,
        any_value(category_level) as geo_level
    from {{ ref('stg_ine__categories') }}
    where dim_num = '2'
    group by category_code
)

select
    geo_code,
    geo_name,
    geo_level,
    case geo_level
        when 1 then 'country'
        when 2 then 'nuts1'
        when 3 then 'nuts2'
        when 4 then 'nuts3'
        when 5 then 'municipality'
    end as geo_level_name,
    case geo_level
        when 2 then 'PT'
        when 3 then left(geo_code, 1)
        when 4 then left(geo_code, 2)
        when 5 then left(geo_code, 3)
    end as parent_geo_code,
    case when geo_level >= 4 then left(geo_code, 3) end as nuts3_geo_code,
    case when geo_level >= 3 then left(geo_code, 2) end as nuts2_geo_code
from units
