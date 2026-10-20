-- Published months per indicator. INE labels periods in Portuguese
-- ("Janeiro de 2020"); the metadata maps each label to its code (S3A202001),
-- which is parsed instead of the label.
select
    varcd,
    category_code as period_code,
    category_name as period_label,
    cast(strptime(substr(category_code, 4, 6), '%Y%m') as date) as month
from {{ ref('stg_ine__categories') }}
where dim_num = '1'
