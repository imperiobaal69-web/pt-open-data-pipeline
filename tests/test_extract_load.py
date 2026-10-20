import datetime as dt
import json
from urllib.parse import parse_qs, urlsplit

import duckdb
import pytest

from ptdata import load as load_module
from ptdata.catalog import load_catalog
from ptdata.cli import FIXTURES
from ptdata.extract import extract
from ptdata.load import load
from ptdata.raw import RawStore
from ptdata.transport import FixtureTransport

QUIET = {"log": lambda _: None}


def data_requests(store):
    return [e for e in store.entries() if e.kind == "data"]


def test_extract_enumerates_months_from_metadata_and_chunks(tmp_path, fixture_transport):
    store = RawStore(tmp_path)
    summary = extract(store, fixture_transport, load_catalog(), chunk_months=12, **QUIET)
    by_series = {}
    for e in data_requests(store):
        periods = parse_qs(urlsplit(e.url).query)["Dim1"][0].split(",")
        by_series.setdefault(e.varcd, []).extend(periods)
    # 33 fixture months in chunks of 12 -> 3 requests per municipal series, 1 per sector series.
    assert summary.requests == 5 + 3 * 3 + 2 * 1
    assert len(by_series["0012848"]) == 33 and len(set(by_series["0012848"])) == 33
    assert len(by_series["0014710"]) == 8


def test_extract_requests_only_cae_sections(tmp_path, fixture_transport):
    store = RawStore(tmp_path)
    extract(store, fixture_transport, load_catalog(), **QUIET)
    sector = [e for e in data_requests(store) if e.varcd == "0014710"][0]
    codes = parse_qs(urlsplit(sector.url).query)["Dim3"][0].split(",")
    assert codes[0] == "TOT" and len(codes) == 23 and all(len(c) <= 3 for c in codes)


def test_second_run_serves_data_from_cache_and_rechecks_metadata(tmp_path, fixture_transport):
    store = RawStore(tmp_path)
    extract(store, fixture_transport, load_catalog(), **QUIET)
    again = extract(store, fixture_transport, load_catalog(), **QUIET)
    assert again.requests == 5 and again.cache_hits == 5  # 5 metadata re-checks, 5 cached data responses
    # Unchanged metadata is not stored again; the re-check is recorded as a confirmation.
    assert [e.event for e in store.entries()].count("stored") == 10
    assert [e.event for e in store.entries()].count("confirmed") == 5
    assert len(list(tmp_path.glob("ine/**/*.json"))) == 10


def test_load_stamps_a_reconfirmed_file_with_its_latest_retrieval(tmp_path, fixture_transport):
    store = RawStore(tmp_path / "raw")
    extract(store, fixture_transport, load_catalog(), **QUIET)
    meta = next(e for e in store.entries() if e.varcd == "0012848" and e.kind == "meta")
    later = meta.retrieved + dt.timedelta(days=30)
    store.put("meta", "0012848", meta.url, store.read(meta), "fixtures", now=later)
    load(store, tmp_path / "w.duckdb")
    con = duckdb.connect(str(tmp_path / "w.duckdb"), read_only=True)
    rows = con.execute("select retrieved_utc, source_path from raw.ine_series where varcd = '0012848'").fetchall()
    events = con.execute("select event, count(*) from raw.extract_manifest group by 1 order by 1").fetchall()
    assert rows == [(later.replace(tzinfo=None), meta.path)]  # loaded once, as of the confirmation
    assert events == [("confirmed", 1), ("stored", 10)]


def test_new_month_in_metadata_triggers_a_new_data_request(tmp_path):
    store = RawStore(tmp_path)
    extract(store, FixtureTransport(FIXTURES, as_of=dt.date(2026, 8, 1)), load_catalog(), **QUIET)
    later = extract(store, FixtureTransport(FIXTURES), load_catalog(), **QUIET)
    assert later.cache_hits == 0 and later.requests == 10


def test_since_limits_requested_months(tmp_path, fixture_transport):
    store = RawStore(tmp_path)
    extract(store, fixture_transport, load_catalog(), since=dt.date(2026, 8, 1), **QUIET)
    periods = {p for e in data_requests(store) for p in parse_qs(urlsplit(e.url).query)["Dim1"][0].split(",")}
    assert periods == {"S3A202608", "S3A202609"}


def test_load_keeps_every_record_with_lineage(tmp_path, fixture_transport):
    store = RawStore(tmp_path / "raw")
    extract(store, fixture_transport, load_catalog(), **QUIET)
    summary = load(store, tmp_path / "w.duckdb")
    expected = sum(
        len(records)
        for name in FIXTURES.glob("data_*.json")
        for records in json.loads(name.read_text())[0]["Dados"].values()
    )
    assert summary.observations == expected
    con = duckdb.connect(str(tmp_path / "w.duckdb"), read_only=True)
    row = con.execute(
        "select count(*), count(distinct source_sha256), min(retrieved_utc) is not null from raw.ine_observations"
    ).fetchone()
    assert row == (expected, 5, True)
    assert con.execute("select count(*) from raw.extract_manifest").fetchone()[0] == 10


def test_failed_load_leaves_previous_tables_intact(tmp_path, fixture_transport, monkeypatch):
    store = RawStore(tmp_path / "raw")
    db = tmp_path / "w.duckdb"
    extract(store, FixtureTransport(FIXTURES, as_of=dt.date(2026, 6, 1)), load_catalog(), **QUIET)
    load(store, db)
    tables = ("ine_observations", "ine_categories", "ine_series", "extract_manifest")

    def snapshot():
        con = duckdb.connect(str(db), read_only=True)
        try:
            return {t: con.execute(f"select * from raw.{t} order by all").fetchall() for t in tables}
        finally:
            con.close()

    before = snapshot()
    extract(store, fixture_transport, load_catalog(), **QUIET)  # Jul-Sep arrive: every table would change

    real_write, calls = load_module._write_table, []

    def crash_on_third_table(con, table, *args):
        calls.append(table)
        if len(calls) == 3:
            raise RuntimeError("simulated crash mid-load")
        real_write(con, table, *args)

    monkeypatch.setattr(load_module, "_write_table", crash_on_third_table)
    with pytest.raises(RuntimeError, match="simulated crash"):
        load(store, db)
    assert calls == ["ine_observations", "ine_categories", "ine_series"]
    assert snapshot() == before  # the two tables rebuilt before the crash were rolled back too

    monkeypatch.setattr(load_module, "_write_table", real_write)
    load(store, db)
    after = snapshot()
    assert all(len(after[t]) > len(before[t]) for t in ("ine_observations", "extract_manifest"))
