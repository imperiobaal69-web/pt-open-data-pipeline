"""Rebuild the offline test fixtures from the live INE API.

Data fixtures are real API responses, stored byte-for-byte, for a small
request: a handful of geographies across the NUTS hierarchy and the months
from FIXTURE_START to the latest published month. Metadata fixtures are the
real metadata trimmed to the same periods, geographies and breakdown
categories, so that the fixture transport can emulate the API consistently.

Usage: uv run python scripts/build_fixtures.py
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from ptdata import ine
from ptdata.catalog import load_catalog
from ptdata.transport import HttpTransport

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "ine"
FIXTURE_START = dt.date(2024, 1, 1)

# Country -> NUTS I -> NUTS II -> NUTS III -> municipality, on the mainland and
# in the Azores. Every municipality of NUTS III 11A (Área Metropolitana do
# Porto) is included so that the cross-level additivity test has a complete
# region to check; the Azores region is deliberately incomplete.
NUTS3_COMPLETE = "11A"
MUNICIPAL_GEOS = ["PT", "1", "11", "11A", "2", "20", "200", "2004203"]  # 2004203 = Ponta Delgada
# The CAE series are only published down to NUTS III.
SECTOR_GEOS = ["PT", "1", "11", "11A", "2", "20", "200"]


def trim_meta(meta: dict, periods: set[str], geos: set[str], breakdown: set[str] | None) -> dict:
    keep = {"1": periods, "2": geos, "3": breakdown}
    groups = []
    for group in meta["Dimensoes"]["Categoria_Dim"]:
        kept = {}
        for key, entries in group.items():
            cat = entries[0]
            allowed = keep[cat["dim_num"]]
            if allowed is None or cat["categ_cod"] in allowed:
                kept[key] = entries
        groups.append(kept)
    meta = {**meta, "Dimensoes": {**meta["Dimensoes"], "Categoria_Dim": groups}}
    first = ine.categories(meta, "1")
    meta["PrimeiroPeriodo"] = first[0]["categ_dsg"]
    meta["UltimoPeriodo"] = first[-1]["categ_dsg"]
    return meta


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    http = HttpTransport()
    for series in load_catalog():
        print(f"{series.varcd} {series.description}")
        meta = ine.parse_payload(http.get(ine.meta_url(series.varcd)))
        periods = [p for p in ine.monthly_periods(meta) if ine.parse_month_code(p) >= FIXTURE_START]
        if series.breakdown == "sector":
            geos = SECTOR_GEOS
        else:
            region = [
                c["categ_cod"]
                for c in ine.categories(meta, "2")
                if c["categ_nivel"] == "5" and c["categ_cod"].startswith(NUTS3_COMPLETE)
            ]
            geos = MUNICIPAL_GEOS + region
        breakdown = None
        if series.max_breakdown_level is not None:
            breakdown = [
                c["categ_cod"] for c in ine.categories(meta, "3") if int(c["categ_nivel"]) <= series.max_breakdown_level
            ]
        body = http.get(ine.data_url(series.varcd, periods, geos, breakdown or ()))
        (OUT / f"data_{series.varcd}.json").write_bytes(body)
        trimmed = trim_meta(meta, set(periods), set(geos), set(breakdown) if breakdown else None)
        (OUT / f"meta_{series.varcd}.json").write_text(
            json.dumps([trimmed], ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print(f"  {len(periods)} months, {len(geos)} geographies, {len(body):,} bytes")


if __name__ == "__main__":
    main()
