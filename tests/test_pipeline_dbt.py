"""End-to-end: extract -> load -> dbt build against fixtures, in a temp dir."""

import datetime as dt
import json

import duckdb
import pytest

from ptdata import ine
from ptdata.cli import FIXTURES, run_dbt
from ptdata.transport import FixtureTransport

from .conftest import dbt_results, run_pipeline

MUNICIPAL = {"0012848", "0012847", "0012103"}
FACT_COLUMNS = (
    "geo_code, month, spend_eur, spend_in_person_eur, spend_online_eur, spend_domestic_cards_eur, "
    "spend_foreign_cards_eur, transactions, avg_ticket_eur, online_share, foreign_card_share"
)


class EditingTransport:
    """Wraps the fixture transport and rewrites data (or metadata) responses."""

    def __init__(self, inner, edit, endpoint=ine.DATA_ENDPOINT):
        self.inner, self.edit, self.endpoint, self.name = inner, edit, endpoint, inner.name

    def get(self, url):
        body = self.inner.get(url)
        if not url.startswith(self.endpoint):
            return body
        doc = ine.parse_payload(body)
        self.edit(doc)
        return json.dumps([doc], ensure_ascii=False).encode()


def query(paths, sql):
    con = duckdb.connect(str(paths.db), read_only=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def test_full_build_passes_all_dbt_tests(paths, fixture_transport):
    results = run_pipeline(paths, fixture_transport)
    tests = {k: v for k, v in results.items() if k.startswith("test.")}
    assert len(tests) >= 60
    assert set(results.values()) <= {"success", "pass"}


def test_incremental_run_adds_new_months_and_matches_full_refresh(tmp_path):
    from ptdata.cli import Paths

    inc, full = Paths(tmp_path / "inc"), Paths(tmp_path / "full")
    run_pipeline(inc, FixtureTransport(FIXTURES, as_of=dt.date(2026, 6, 1)))
    assert query(inc, "select max(month)::varchar from marts.fct_card_purchases_monthly") == [("2026-06-01",)]
    first_stamp = query(inc, "select max(source_retrieved_utc) from marts.fct_card_purchases_monthly")[0][0]

    run_pipeline(inc, FixtureTransport(FIXTURES))  # INE publishes Jul-Sep: incremental run
    run_pipeline(full, FixtureTransport(FIXTURES), full_refresh=True)

    sql = f"select {FACT_COLUMNS} from marts.fct_card_purchases_monthly order by geo_code, month"
    assert query(inc, sql) == query(full, sql)
    assert query(inc, "select max(month)::varchar from marts.fct_card_purchases_monthly") == [("2026-09-01",)]
    # Only months inside the 3-month lookback window (from 2026-03) were rebuilt.
    rebuilt = query(
        inc,
        f"select month < date '2026-03-01', bool_and(source_retrieved_utc = '{first_stamp}') "
        "from marts.fct_card_purchases_monthly group by 1 order by 1",
    )
    assert rebuilt == [(False, False), (True, True)]


def test_revised_values_supersede_earlier_snapshot(paths, fixture_transport):
    run_pipeline(paths, fixture_transport)
    before = query(
        paths,
        "select month::varchar, spend_eur from marts.fct_card_purchases_monthly "
        "where geo_code = '11A1312' and month >= '2026-08-01' order by month",
    )

    def revise(doc):  # INE revises September: every value of the channel/value series doubles
        if doc["IndicadorCod"] == "0012848":
            for r in doc["Dados"].get("Setembro de 2026", []):
                r["valor"] = str(int(r["valor"]) * 2)

    run_pipeline(paths, EditingTransport(fixture_transport, revise), refresh=True)
    after = query(
        paths,
        "select month::varchar, spend_eur from marts.fct_card_purchases_monthly "
        "where geo_code = '11A1312' and month >= '2026-08-01' order by month",
    )
    assert after[0] == before[0]
    assert after[1][1] == before[1][1] * 2
    assert (
        query(paths, "select count(distinct source_sha256) from raw.ine_observations where varcd = '0012848'")[0][0]
        == 2
    )  # both snapshots kept in raw


def test_missing_month_fails_gapless_test_and_growth_stays_null(paths, fixture_transport):
    def drop_march_2025(doc):
        if doc["IndicadorCod"] in MUNICIPAL:
            doc["Dados"].pop("Março de 2025", None)

    with pytest.raises(SystemExit):
        run_pipeline(paths, EditingTransport(fixture_transport, drop_march_2025))
    failed = {k for k, v in dbt_results(paths).items() if v == "fail"}
    assert any("gapless_monthly_series_fct_card_purchases_monthly" in k for k in failed)

    run_dbt(paths, "run", "--quiet")  # build the marts anyway to inspect the growth logic
    april = query(
        paths,
        "select spend_eur is not null, spend_mom_change, spend_yoy_change is not null "
        "from marts.mart_municipality_monthly where geo_code = '11A1312' and month = '2025-04-01'",
    )
    assert april == [(True, None, True)]  # no March to compare with: NULL, not a 2-month change


def test_municipalities_must_add_up_to_their_region(paths, fixture_transport):
    # Fixtures hold every municipality of NUTS III 11A, so its additivity is checked.
    def inflate_porto(doc):  # +1000 EUR in-person (and total) for Porto only: components still add up
        if doc["IndicadorCod"] == "0012848":
            for r in doc["Dados"].get("Maio de 2025", []):
                if r["geocod"] == "11A1312" and r["dim_3"] in ("T", "1"):
                    r["valor"] = str(int(r["valor"]) + 1000)

    with pytest.raises(SystemExit):
        run_pipeline(paths, EditingTransport(fixture_transport, inflate_porto))
    results = dbt_results(paths)
    status = {k.split(".")[2]: v for k, v in results.items() if k.startswith("test.")}
    assert status["assert_municipalities_sum_to_nuts3"] == "fail"
    assert status["assert_channel_components_sum_to_total"] == "pass"


@pytest.mark.parametrize(
    ("field", "value", "failing_test"),
    [
        ("Potencia10", "3", "stg_ine__series_power_of_ten_is_zero"),  # values now in thousands of euros
        ("UnidadeMedida", "Milhares de euros", "stg_ine__series_spend_unit_is_euro"),
        ("PrecisaoDecimal", "4", "accepted_range_stg_ine__series_decimals"),
    ],
)
def test_change_in_unit_or_scaling_fails_the_build(paths, fixture_transport, field, value, failing_test):
    def rescale(meta):
        if meta["IndicadorCod"] == "0012848":
            meta[field] = value

    with pytest.raises(SystemExit):
        run_pipeline(paths, EditingTransport(fixture_transport, rescale, endpoint=ine.META_ENDPOINT))
    results = dbt_results(paths)
    failed = {k.split(".")[2] for k, v in results.items() if v == "fail"}
    assert any(name.startswith(failing_test) for name in failed), failed
    # Nothing downstream of the staging series is built from mis-scaled values.
    assert results["model.pt_card_spend.fct_card_purchases_monthly"] == "skipped"
