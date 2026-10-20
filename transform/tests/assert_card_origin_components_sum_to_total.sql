-- Domestic + foreign cards must equal the card-origin total.
select geo_code, month, spend_card_origin_total_eur, spend_domestic_cards_eur, spend_foreign_cards_eur
from {{ ref('fct_card_purchases_monthly') }}
where abs(spend_domestic_cards_eur + spend_foreign_cards_eur - spend_card_origin_total_eur) > 1
