{{ config(severity='warn') }}
{%- set columns = ["spend_eur", "spend_in_person_eur", "spend_online_eur", "spend_domestic_cards_eur",
                    "spend_foreign_cards_eur", "transactions", "transactions_in_person", "transactions_online"] -%}
-- Warns when INE has corrected a value listed in known_source_issues, so the
-- entry can be removed. Silent when the geography is not loaded (fixtures).
select issue.*, case issue.fct_column
    {%- for c in columns %}
    when '{{ c }}' then fct.{{ c }}{% endfor %}
    end as currently_published
from {{ ref('known_source_issues') }} as issue
inner join {{ ref('fct_card_purchases_monthly') }} as fct
    on issue.geo_code = fct.geo_code and issue.month = fct.month
where currently_published is distinct from issue.published_value
