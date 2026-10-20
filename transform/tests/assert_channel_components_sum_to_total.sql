-- In-person + online must equal the channel total (to the euro / unit),
-- except where a published inconsistency is recorded in known_source_issues.
select geo_code, month, spend_eur, spend_in_person_eur, spend_online_eur,
       transactions, transactions_in_person, transactions_online
from {{ ref('fct_card_purchases_monthly') }}
where source_issue_note is null
  and (abs(spend_in_person_eur + spend_online_eur - spend_eur) > 1
       or abs(transactions_in_person + transactions_online - transactions) > 1)
