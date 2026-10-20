"""Load: raw layer -> DuckDB ``raw`` schema.

Responses are flattened to one row per observation / category and loaded
with explicit column types. Every snapshot in the manifest is loaded (not
just the newest); de-duplication to the latest value per key happens in the
dbt staging layer, so the warehouse keeps full lineage back to the file and
checksum each value came from. The load is a full rebuild of ``raw.*``: the
raw layer is the source of truth and a rebuild takes seconds at this volume.
"""

from __future__ import annotations

import datetime as dt
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from . import ine
from .raw import ManifestEntry, RawStore

OBSERVATION_COLUMNS = {
    "varcd": "VARCHAR",
    "period_label": "VARCHAR",
    "geo_code": "VARCHAR",
    "geo_name": "VARCHAR",
    "breakdown_code": "VARCHAR",
    "breakdown_name": "VARCHAR",
    "value_raw": "VARCHAR",
    "value_display": "VARCHAR",
    "retrieved_utc": "TIMESTAMP",
    "source_path": "VARCHAR",
    "source_sha256": "VARCHAR",
}
CATEGORY_COLUMNS = {
    "varcd": "VARCHAR",
    "dim_num": "VARCHAR",
    "category_code": "VARCHAR",
    "category_name": "VARCHAR",
    "category_order": "INTEGER",
    "category_level": "INTEGER",
    "retrieved_utc": "TIMESTAMP",
    "source_path": "VARCHAR",
    "source_sha256": "VARCHAR",
}
SERIES_COLUMNS = {
    "varcd": "VARCHAR",
    "name": "VARCHAR",
    "periodicity": "VARCHAR",
    "first_period_label": "VARCHAR",
    "last_period_label": "VARCHAR",
    "unit": "VARCHAR",
    "power_of_ten": "INTEGER",
    "decimals": "INTEGER",
    "last_updated": "DATE",
    "dim2_label": "VARCHAR",
    "dim3_label": "VARCHAR",
    "retrieved_utc": "TIMESTAMP",
    "source_path": "VARCHAR",
    "source_sha256": "VARCHAR",
}
MANIFEST_COLUMNS = {
    "source": "VARCHAR",
    "kind": "VARCHAR",
    "varcd": "VARCHAR",
    "url": "VARCHAR",
    "retrieved_utc": "TIMESTAMP",
    "sha256": "VARCHAR",
    "bytes": "BIGINT",
    "path": "VARCHAR",
    "transport": "VARCHAR",
}


@dataclass
class LoadSummary:
    files: int
    observations: int
    categories: int
    series: int


def _utc(entry: ManifestEntry) -> str:
    """Naive UTC timestamp string, the form DuckDB's TIMESTAMP parses."""
    return entry.retrieved.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M:%S")


def _write_table(
    con: duckdb.DuckDBPyConnection, table: str, columns: dict[str, str], rows: list[dict[str, Any]], tmp: Path
) -> None:
    path = tmp / f"{table}.ndjson"
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    cols = ", ".join(f"'{k}': '{v}'" for k, v in columns.items())
    select = ", ".join(columns)
    con.execute(
        f"create or replace table raw.{table} as "
        f"select {select} from read_json('{path.as_posix()}', format='newline_delimited', columns={{{cols}}})"
    )


def load(store: RawStore, db_path: Path) -> LoadSummary:
    observations: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []
    series: list[dict[str, Any]] = []
    entries = store.entries()
    # A file is referenced twice only if identical bytes were stored in the
    # same second; load it once, as its latest retrieval.
    files = list({e.path: e for e in entries}.values())

    for entry in files:
        doc = ine.parse_payload(store.read(entry))
        stamp = {"retrieved_utc": _utc(entry), "source_path": entry.path, "source_sha256": entry.sha256}
        if entry.kind == "meta":
            dims = {d["dim_num"]: d["abrv"] for d in doc["Dimensoes"]["Descricao_Dim"]}
            series.append(
                {
                    "varcd": doc["IndicadorCod"],
                    "name": doc["IndicadorNome"],
                    "periodicity": doc.get("Periodic"),
                    "first_period_label": doc.get("PrimeiroPeriodo"),
                    "last_period_label": doc.get("UltimoPeriodo"),
                    "unit": doc.get("UnidadeMedida"),
                    "power_of_ten": int(doc.get("Potencia10") or 0),
                    "decimals": int(doc.get("PrecisaoDecimal") or 0),
                    "last_updated": doc.get("DataUltimaAtualizacao"),
                    "dim2_label": dims.get("2"),
                    "dim3_label": dims.get("3"),
                    **stamp,
                }
            )
            for dim_num in ("1", "2", "3"):
                for c in ine.categories(doc, dim_num):
                    categories.append(
                        {
                            "varcd": doc["IndicadorCod"],
                            "dim_num": dim_num,
                            "category_code": c["categ_cod"],
                            "category_name": c["categ_dsg"],
                            "category_order": int(c["categ_ord"]),
                            "category_level": int(c["categ_nivel"]),
                            **stamp,
                        }
                    )
        elif entry.kind == "data":
            for period_label, records in doc["Dados"].items():
                for r in records:
                    observations.append(
                        {
                            "varcd": doc["IndicadorCod"],
                            "period_label": period_label,
                            "geo_code": r.get("geocod"),
                            "geo_name": r.get("geodsg"),
                            "breakdown_code": r.get("dim_3"),
                            "breakdown_name": r.get("dim_3_t"),
                            "value_raw": r.get("valor"),
                            "value_display": r.get("ind_string"),
                            **stamp,
                        }
                    )

    manifest = [{**{k: getattr(e, k) for k in MANIFEST_COLUMNS}, "retrieved_utc": _utc(e)} for e in entries]
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute("create schema if not exists raw")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_table(con, "ine_observations", OBSERVATION_COLUMNS, observations, tmp_path)
            _write_table(con, "ine_categories", CATEGORY_COLUMNS, categories, tmp_path)
            _write_table(con, "ine_series", SERIES_COLUMNS, series, tmp_path)
            _write_table(con, "extract_manifest", MANIFEST_COLUMNS, manifest, tmp_path)
    finally:
        con.close()
    return LoadSummary(files=len(files), observations=len(observations), categories=len(categories), series=len(series))
