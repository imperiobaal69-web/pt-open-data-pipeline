-- Observations tagged with what they measure (spend / transactions), the
-- breakdown they belong to, and, for channel and card-origin series, the
-- meaning of the breakdown code (total, online, foreign, ...).
select
    obs.varcd,
    series.measure,
    series.breakdown,
    obs.month,
    obs.geo_code,
    obs.breakdown_code,
    obs.breakdown_name,
    members.member,
    obs.value,
    obs.is_missing_value,
    obs.retrieved_utc
from {{ ref('stg_ine__observations') }} as obs
inner join {{ ref('stg_ine__series') }} as series
    on obs.varcd = series.varcd
left join {{ ref('breakdown_members') }} as members
    on series.breakdown = members.breakdown
    and obs.breakdown_code = members.breakdown_code
