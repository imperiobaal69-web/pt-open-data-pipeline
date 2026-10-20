{{
    config(
        materialized='incremental',
        unique_key=['geo_code', 'month'],
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}

-- Monthly card purchases per geography (country down to municipality).
-- Values are kept exactly as INE published them; known inconsistencies are
-- flagged in source_issue_note (see the known_source_issues seed).
-- Incremental: each run rebuilds only the months from the latest loaded
-- month minus `incremental_lookback_months`, so newly published months are
-- added and recent INE revisions overwrite earlier values. A revision to an
-- older month needs `dbt build --full-refresh` (the monthly workflow runs one).
with issues as (
    select geo_code, month, string_agg(fct_column || ': ' || note, '; ' order by fct_column) as source_issue_note
    from {{ ref('known_source_issues') }}
    group by geo_code, month
)

select
    pivoted.geo_code,
    pivoted.month,
    spend_eur,
    spend_in_person_eur,
    spend_online_eur,
    spend_domestic_cards_eur,
    spend_foreign_cards_eur,
    spend_card_origin_total_eur,
    transactions,
    transactions_in_person,
    transactions_online,
    round(spend_eur / nullif(transactions, 0), 2) as avg_ticket_eur,
    round(spend_online_eur / nullif(spend_eur, 0), 6) as online_share,
    round(spend_foreign_cards_eur / nullif(spend_card_origin_total_eur, 0), 6) as foreign_card_share,
    issues.source_issue_note,
    source_retrieved_utc
from {{ ref('int_card_purchases__pivoted') }} as pivoted
left join issues
    on pivoted.geo_code = issues.geo_code
    and pivoted.month = issues.month
{% if is_incremental() %}
where pivoted.month >= (
    select cast(max(month) - interval '{{ var("incremental_lookback_months") }} months' as date)
    from {{ this }}
)
{% endif %}
