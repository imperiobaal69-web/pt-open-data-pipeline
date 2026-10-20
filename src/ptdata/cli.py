"""Command-line entrypoint: ``ptdata <step> [--source live|fixtures]``.

Each source gets its own data directory (``data/<source>/``) holding the raw
layer, the DuckDB warehouse, dbt artefacts and Parquet exports, so a fixture
run never mixes with a live run.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .catalog import REPO_ROOT, load_catalog
from .extract import extract
from .load import load
from .outputs import export_parquet, write_lineage, write_summary
from .raw import RawStore
from .transport import FixtureTransport, HttpTransport, Transport

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "ine"
DBT_PROJECT = REPO_ROOT / "transform"


class Paths:
    def __init__(self, data_dir: Path):
        self.data = data_dir
        self.raw = data_dir / "raw"
        self.db = data_dir / "warehouse.duckdb"
        self.dbt_target = data_dir / "dbt_target"
        self.dbt_logs = data_dir / "dbt_logs"
        self.exports = data_dir / "exports"
        self.build_results = data_dir / "dbt_build_results.json"


def _month(value: str) -> dt.date:
    return dt.datetime.strptime(value, "%Y-%m").date()


def run_dbt(paths: Paths, *args: str) -> None:
    dbt = Path(sys.executable).with_name("dbt")
    env = {**os.environ, "PTDATA_DUCKDB": str(paths.db)}
    cmd = [
        str(dbt),
        *args,
        "--project-dir",
        str(DBT_PROJECT),
        "--profiles-dir",
        str(DBT_PROJECT),
        "--target-path",
        str(paths.dbt_target),
        "--log-path",
        str(paths.dbt_logs),
    ]
    result = subprocess.run(cmd, env=env, check=False)
    if result.returncode != 0:
        raise SystemExit(f"dbt {args[0]} failed (exit {result.returncode})")


def cmd_extract(args: argparse.Namespace, paths: Paths) -> None:
    transport: Transport
    if args.source == "live":
        transport = HttpTransport()
    else:
        transport = FixtureTransport(FIXTURES, as_of=_month(args.as_of) if args.as_of else None)
    if args.refresh:
        max_age = dt.timedelta(0)
    elif args.source == "fixtures" and args.max_age_hours is None:
        max_age = dt.timedelta.max  # fixtures never change; keeps fixture runs deterministic
    else:
        max_age = dt.timedelta(hours=args.max_age_hours or 24.0)
    print(f"extract ({transport.name}) -> {paths.raw}")
    summary = extract(
        RawStore(paths.raw),
        transport,
        load_catalog(),
        since=_month(args.since) if args.since else None,
        max_age=max_age,
    )
    print(f"  {summary.requests} requests, {summary.cache_hits} cache hits, {summary.bytes_fetched:,} bytes")


def cmd_load(args: argparse.Namespace, paths: Paths) -> None:
    store = RawStore(paths.raw)
    problems = store.verify()
    if problems:
        raise SystemExit("raw layer integrity check failed:\n  " + "\n  ".join(problems))
    s = load(store, paths.db)
    print(f"load -> {paths.db}: {s.files} files, {s.observations:,} observations, {s.categories:,} categories")


def cmd_transform(args: argparse.Namespace, paths: Paths) -> None:
    run_dbt(paths, "build", *(["--full-refresh"] if args.full_refresh else []))
    # Later dbt commands (docs generate) overwrite run_results.json; keep the build's.
    shutil.copyfile(paths.dbt_target / "run_results.json", paths.build_results)


def cmd_export(args: argparse.Namespace, paths: Paths) -> None:
    counts = export_parquet(paths.db, paths.exports)
    for table, n in counts.items():
        print(f"  {paths.exports / (table + '.parquet')}  {n:,} rows")


def cmd_docs(args: argparse.Namespace, paths: Paths) -> None:
    run_dbt(paths, "docs", "generate")
    write_lineage(paths.dbt_target / "manifest.json", REPO_ROOT / "docs" / "lineage.md")
    print(f"  dbt docs: {paths.dbt_target / 'index.html'}  (serve with: make docs-serve)")
    print(f"  lineage:  {REPO_ROOT / 'docs' / 'lineage.md'}")


def cmd_report(args: argparse.Namespace, paths: Paths) -> None:
    out = REPO_ROOT / "reports" / f"summary_{args.source}.md"
    write_summary(paths.db, paths.build_results, out, args.source)
    print(f"  report: {out}")


def cmd_all(args: argparse.Namespace, paths: Paths) -> None:
    cmd_extract(args, paths)
    cmd_load(args, paths)
    cmd_transform(args, paths)
    cmd_export(args, paths)
    cmd_report(args, paths)
    cmd_docs(args, paths)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ptdata", description="Portuguese card-spend ELT pipeline (INE / SIBS).")
    parser.add_argument("--source", choices=["live", "fixtures"], default=os.environ.get("PTDATA_SOURCE", "fixtures"))
    parser.add_argument("--data-dir", type=Path, help="default: data/<source>")
    sub = parser.add_subparsers(dest="command", required=True)

    def extract_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--since", help="only fetch months from YYYY-MM on")
        p.add_argument("--as-of", help="fixtures only: pretend INE has published up to YYYY-MM")
        p.add_argument(
            "--max-age-hours",
            type=float,
            help="reuse cached responses younger than this (default 24; fixtures: forever)",
        )
        p.add_argument("--refresh", action="store_true", help="ignore the cache")

    extract_args(sub.add_parser("extract", help="fetch INE responses into the raw layer"))
    sub.add_parser("load", help="load the raw layer into DuckDB")
    p = sub.add_parser("transform", help="dbt build (seeds, models, tests)")
    p.add_argument("--full-refresh", action="store_true")
    sub.add_parser("export", help="write marts to Parquet")
    sub.add_parser("docs", help="dbt docs + Mermaid lineage")
    sub.add_parser("report", help="write reports/summary_<source>.md")
    p = sub.add_parser("all", help="extract, load, transform, export, report, docs")
    extract_args(p)
    p.add_argument("--full-refresh", action="store_true")

    args = parser.parse_args(argv)
    paths = Paths(args.data_dir or REPO_ROOT / "data" / args.source)
    handlers = {
        "extract": cmd_extract,
        "load": cmd_load,
        "transform": cmd_transform,
        "export": cmd_export,
        "docs": cmd_docs,
        "report": cmd_report,
        "all": cmd_all,
    }
    handlers[args.command](args, paths)


if __name__ == "__main__":
    main()
