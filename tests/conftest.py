from __future__ import annotations

import json
from pathlib import Path

import pytest

from ptdata.catalog import load_catalog
from ptdata.cli import FIXTURES, Paths, run_dbt
from ptdata.extract import extract
from ptdata.load import load
from ptdata.raw import RawStore
from ptdata.transport import FixtureTransport


@pytest.fixture
def fixture_transport() -> FixtureTransport:
    return FixtureTransport(FIXTURES)


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(tmp_path / "data")


def run_pipeline(paths: Paths, transport, *, refresh: bool = False, full_refresh: bool = False) -> dict:
    """Extract -> load -> dbt build into ``paths``. Returns dbt run_results by node name.

    Raises SystemExit if dbt reports a failure (the results are still on disk).
    """
    import datetime as dt

    store = RawStore(paths.raw)
    extract(
        store, transport, load_catalog(), max_age=dt.timedelta(0) if refresh else dt.timedelta.max, log=lambda _: None
    )
    load(store, paths.db)
    run_dbt(paths, "build", "--quiet", *(["--full-refresh"] if full_refresh else []))
    return dbt_results(paths)


def dbt_results(paths: Paths) -> dict[str, str]:
    results = json.loads((paths.dbt_target / "run_results.json").read_text())["results"]
    return {r["unique_id"]: r["status"] for r in results}
