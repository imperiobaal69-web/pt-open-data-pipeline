-- Dimension categories from the latest metadata snapshot of each indicator.
select
    categories.varcd,
    categories.dim_num,
    categories.category_code,
    categories.category_name,
    categories.category_order,
    categories.category_level
from {{ source('ine', 'ine_categories') }} as categories
inner join {{ ref('stg_ine__series') }} as series
    on categories.varcd = series.varcd
    and categories.source_path = series.metadata_source_path
