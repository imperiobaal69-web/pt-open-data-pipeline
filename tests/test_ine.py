import datetime as dt
import json

import pytest

from ptdata import ine


def test_month_codes_round_trip():
    assert ine.month_code(dt.date(2020, 1, 1)) == "S3A202001"
    assert ine.parse_month_code("S3A202612") == dt.date(2026, 12, 1)


@pytest.mark.parametrize("bad", ["S3A2020", "S7A202001", "S3A2020AB", "202001"])
def test_parse_month_code_rejects_non_monthly(bad):
    with pytest.raises(ValueError):
        ine.parse_month_code(bad)


def test_months_between_crosses_year_boundary():
    months = ine.months_between(dt.date(2025, 11, 1), dt.date(2026, 2, 1))
    assert months == ["S3A202511", "S3A202512", "S3A202601", "S3A202602"]


def test_months_between_matches_published_span():
    # Jan 2020 .. Sep 2026 is the 81-month span INE published for the municipal series.
    assert len(ine.months_between(dt.date(2020, 1, 1), dt.date(2026, 9, 1))) == 81


def test_data_url_enumerates_periods_and_keeps_commas():
    url = ine.data_url("0012848", ["S3A202601", "S3A202602"], geos=["11A1312", "11A"])
    assert url == (
        "https://www.ine.pt/ine/json_indicador/pindica.jsp?op=2&varcd=0012848"
        "&Dim1=S3A202601,S3A202602&Dim2=11A1312,11A&Dim3=&lang=PT"
    )


def test_data_url_refuses_empty_period_list():
    # An empty Dim1 silently returns only the latest month.
    with pytest.raises(ValueError):
        ine.data_url("0012848", [])


def test_parse_payload_accepts_single_element_list():
    body = json.dumps([{"IndicadorCod": "1", "Sucesso": {"Verdadeiro": [{"Msg": "OK"}]}}]).encode()
    assert ine.parse_payload(body)["IndicadorCod"] == "1"


@pytest.mark.parametrize(
    "body",
    [
        b"<html><body>Servico indisponivel</body></html>",
        json.dumps([{"Sucesso": {"Falso": [{"Msg": "Indicador inexistente"}]}}]).encode(),
        json.dumps([{}, {}]).encode(),
        b"\xff\xfe",
    ],
)
def test_parse_payload_rejects_error_bodies(body):
    with pytest.raises(ine.IneResponseError):
        ine.parse_payload(body)


def test_metadata_categories_and_periods(fixture_transport):
    meta = ine.parse_payload(fixture_transport.get(ine.meta_url("0012848")))
    periods = ine.monthly_periods(meta)
    assert periods[0] == "S3A202401" and periods == sorted(periods)
    assert periods == ine.months_between(dt.date(2024, 1, 1), ine.parse_month_code(periods[-1]))
    breakdown = {c["categ_cod"]: c["categ_dsg"] for c in ine.categories(meta, "3")}
    assert breakdown == {"T": "Total", "1": "Compras presenciais", "2": "Compras online"}
