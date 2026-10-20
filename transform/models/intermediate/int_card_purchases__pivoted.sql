-- One row per geography and month with the channel and card-origin series
-- side by side. The three source indicators are independent INE tables:
-- channel and card origin are never crossed (there is no "foreign online").
select
    geo_code,
    month,
    max(value) filter (where measure = 'spend_eur' and breakdown = 'channel' and member = 'total') as spend_eur,
    max(value) filter (where measure = 'spend_eur' and breakdown = 'channel' and member = 'in_person') as spend_in_person_eur,
    max(value) filter (where measure = 'spend_eur' and breakdown = 'channel' and member = 'online') as spend_online_eur,
    max(value) filter (where measure = 'spend_eur' and breakdown = 'card_origin' and member = 'total') as spend_card_origin_total_eur,
    max(value) filter (where measure = 'spend_eur' and breakdown = 'card_origin' and member = 'domestic') as spend_domestic_cards_eur,
    max(value) filter (where measure = 'spend_eur' and breakdown = 'card_origin' and member = 'foreign') as spend_foreign_cards_eur,
    max(value) filter (where measure = 'transactions' and breakdown = 'channel' and member = 'total') as transactions,
    max(value) filter (where measure = 'transactions' and breakdown = 'channel' and member = 'in_person') as transactions_in_person,
    max(value) filter (where measure = 'transactions' and breakdown = 'channel' and member = 'online') as transactions_online,
    max(retrieved_utc) as source_retrieved_utc
from {{ ref('int_observations__labelled') }}
where breakdown in ('channel', 'card_origin')
group by geo_code, month
