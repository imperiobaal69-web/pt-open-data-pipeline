"""Outputs: Parquet exports, the lineage diagram and the run summary."""

import json

import duckdb
import pytest

from ptdata.cli import FIXTURES, Paths
from ptdata.outputs import MARTS, _table, export_parquet, lineage_mermaid, write_summary
from ptdata.transport import FixtureTransport

from .conftest import run_pipeline


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Paths:
    """One fixture build shared by the tests that only read the warehouse."""
    paths = Paths(tmp_path_factory.mktemp("outputs") / "data")
    run_pipeline(paths, FixtureTransport(FIXTURES))
    return paths


def test_parquet_exports_match_the_marts(built, tmp_path):
    counts = export_parquet(built.db, tmp_path)

    assert set(counts) == set(MARTS)
    assert json.loads((tmp_path / "exports.json").read_text()) == counts
    con = duckdb.connect(str(built.db), read_only=True)
    try:
        for table, order in MARTS.items():
            target = (tmp_path / f"{table}.parquet").as_posix()
            assert counts[table] == con.execute(f"select count(*) from marts.{table}").fetchone()[0] > 0
            # Same rows as the mart, in the documented order.
            exported = con.execute(f"select * from '{target}'").fetchall()
            assert exported == con.execute(f"select * from marts.{table} order by {order}").fetchall()
    finally:
        con.close()


def test_lineage_groups_nodes_by_layer_and_skips_unknown_parents(tmp_path):
    manifest = {
        "sources": {"source.p.ine.observations": {"source_name": "ine", "name": "observations"}},
        "nodes": {
            "seed.p.geo": {"resource_type": "seed", "name": "geo", "fqn": ["p", "geo"]},
            "model.p.stg": {
                "resource_type": "model",
                "name": "stg",
                "fqn": ["p", "staging", "stg"],
                "depends_on": {"nodes": ["source.p.ine.observations"]},
            },
            "model.p.fct": {
                "resource_type": "model",
                "name": "fct",
                "fqn": ["p", "marts", "fct"],
                "depends_on": {"nodes": ["model.p.stg", "seed.p.geo", "model.p.disabled"]},
            },
            "test.p.not_null": {"resource_type": "test", "name": "not_null", "fqn": ["p", "not_null"]},
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))

    assert lineage_mermaid(path) == (
        "flowchart LR\n"
        "  subgraph sources\n    ine_observations[ine.observations]\n  end\n"
        "  subgraph seeds\n    geo[geo]\n  end\n"
        "  subgraph staging\n    stg[stg]\n  end\n"
        "  subgraph marts\n    fct[fct]\n  end\n"
        "  geo --> fct\n"
        "  ine_observations --> stg\n"
        "  stg --> fct\n"
    )


def test_summary_counts_rows_and_dbt_results(built, tmp_path):
    run_results = built.dbt_target / "run_results.json"
    text = write_summary(built.db, run_results, tmp_path / "summary.md", "fixtures")

    assert (tmp_path / "summary.md").read_text() == text
    assert "Source: committed fixtures" in text
    con = duckdb.connect(str(built.db), read_only=True)
    try:
        for table in MARTS:
            rows = con.execute(f"select count(*) from marts.{table}").fetchone()[0]
            assert f"| marts.{table} | {rows:,} |" in text
    finally:
        con.close()
    results = json.loads(run_results.read_text())["results"]
    tests = sum(r["unique_id"].startswith("test.") and r["status"] == "pass" for r in results)
    assert f"| test | pass | {tests} |" in text


def test_summary_of_a_live_run_names_the_retrieval_window(built, tmp_path):
    text = write_summary(built.db, tmp_path / "no_run_results.json", tmp_path / "summary.md", "live")

    assert "Raw responses retrieved from INE between" in text
    assert "Source: committed fixtures" not in text
    # Without run_results.json the dbt section is an empty table, not an error.
    assert "## dbt build results\n\n| resource | status | count |\n|---|---|---|\n\n" in text


def test_table_formats_numbers_for_reading():
    assert _table(["a", "b", "c", "d", "e"], [(None, 0.12345, 12.5, 12345.6, 2553)]) == (
        "| a | b | c | d | e |\n|---|---|---|---|---|\n| – | 0.1235 | 12.50 | 12,346 | 2,553 |"
    )
