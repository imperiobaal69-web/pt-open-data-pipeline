-- One value per (indicator, month, geography, breakdown category): the most
-- recently retrieved snapshot wins, so re-extracts and partial refreshes
-- supersede earlier values without deleting them from the raw layer.
with ranked as (
    select
        *,
        row_number() over (
            partition by varcd, period_label, geo_code, breakdown_code
            order by retrieved_utc desc, source_path desc
        ) as snapshot_rank
    from {{ source('ine', 'ine_observations') }}
)

select
    ranked.varcd,
    periods.month,
    ranked.geo_code,
    ranked.breakdown_code,
    ranked.breakdown_name,
    -- INE marks unavailable / confidential cells with non-numeric values;
    -- they become NULL here and are counted in is_missing_value.
    try_cast(nullif(trim(ranked.value_raw), '') as decimal(20, 2)) as value,
    try_cast(nullif(trim(ranked.value_raw), '') as decimal(20, 2)) is null as is_missing_value,
    ranked.retrieved_utc,
    ranked.source_path,
    ranked.source_sha256
from ranked
left join {{ ref('stg_ine__periods') }} as periods
    on ranked.varcd = periods.varcd
    and ranked.period_label = periods.period_label
where ranked.snapshot_rank = 1
