-- What each indicator can and cannot be broken down by, computed from INE's
-- own metadata plus what was actually loaded. This is the evidence behind
-- the "what the data cannot tell you" section of the README.
with geo as (
    select
        cat.varcd,
        count(*) as geographies_published,
        count(*) filter (where dim.geo_level_name = 'municipality') as municipalities_published,
        max(cat.category_level) as finest_geo_level
    from {{ ref('stg_ine__categories') }} as cat
    inner join {{ ref('dim_geography') }} as dim
        on cat.category_code = dim.geo_code
    where cat.dim_num = '2'
    group by cat.varcd
),

breakdown as (
    select
        varcd,
        count(*) as breakdown_categories_published,
        max(category_level) as breakdown_levels_published
    from {{ ref('stg_ine__categories') }}
    where dim_num = '3'
    group by varcd
),

periods as (
    select varcd, min(month) as first_month, max(month) as last_month, count(*) as months_published
    from {{ ref('stg_ine__periods') }}
    group by varcd
),

loaded as (
    select
        varcd,
        count(distinct month) as months_loaded,
        count(distinct geo_code) as geographies_loaded,
        count(distinct breakdown_code) as breakdown_categories_loaded,
        count(*) as observations_loaded,
        count(*) filter (where is_missing_value) as observations_missing_value
    from {{ ref('stg_ine__observations') }}
    group by varcd
)

select
    series.varcd,
    series.measure,
    series.breakdown,
    series.breakdown_dimension,
    series.unit,
    series.last_updated,
    periods.first_month,
    periods.last_month,
    periods.months_published,
    geo.geographies_published,
    geo.municipalities_published,
    case geo.finest_geo_level
        when 5 then 'municipality'
        when 4 then 'nuts3'
        when 3 then 'nuts2'
        when 2 then 'nuts1'
        else 'country'
    end as finest_geography,
    breakdown.breakdown_categories_published,
    breakdown.breakdown_levels_published,
    loaded.months_loaded,
    loaded.geographies_loaded,
    loaded.breakdown_categories_loaded,
    loaded.observations_loaded,
    loaded.observations_missing_value
from {{ ref('stg_ine__series') }} as series
left join geo on series.varcd = geo.varcd
left join breakdown on series.varcd = breakdown.varcd
left join periods on series.varcd = periods.varcd
left join loaded on series.varcd = loaded.varcd
