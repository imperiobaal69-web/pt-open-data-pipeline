import datetime as dt
import json
from urllib.parse import parse_qs, urlsplit

import duckdb

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
    assert len(store.entries()) == 10  # unchanged metadata is not stored again


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
