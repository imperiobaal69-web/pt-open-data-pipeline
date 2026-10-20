-- Latest metadata snapshot per catalogued indicator.
with ranked as (
    select
        *,
        row_number() over (
            partition by varcd order by retrieved_utc desc, source_path desc
        ) as snapshot_rank
    from {{ source('ine', 'ine_series') }}
)

select
    ranked.varcd,
    catalog.measure,
    catalog.breakdown,
    ranked.name as indicator_name,
    ranked.unit,
    ranked.power_of_ten,
    ranked.decimals,
    ranked.last_updated,
    ranked.first_period_label,
    ranked.last_period_label,
    ranked.dim2_label as geography_dimension,
    ranked.dim3_label as breakdown_dimension,
    ranked.retrieved_utc as metadata_retrieved_utc,
    ranked.source_path as metadata_source_path,
    ranked.source_sha256 as metadata_sha256
from ranked
inner join {{ ref('series_catalog') }} as catalog
    on ranked.varcd = catalog.varcd
where ranked.snapshot_rank = 1
