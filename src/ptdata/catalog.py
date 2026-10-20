"""Series catalog: which INE indicators the pipeline extracts.

The catalog lives in the dbt seed ``transform/seeds/series_catalog.csv`` so that
the extractor and the warehouse read the same single source of truth.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "transform" / "seeds" / "series_catalog.csv"


@dataclass(frozen=True)
class Series:
    varcd: str
    measure: str
    breakdown: str
    max_breakdown_level: int | None
    description: str


def load_catalog(path: Path = CATALOG_PATH) -> list[Series]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    series = [
        Series(
            varcd=r["varcd"],
            measure=r["measure"],
            breakdown=r["breakdown"],
            max_breakdown_level=int(r["max_breakdown_level"]) if r["max_breakdown_level"] else None,
            description=r["description"],
        )
        for r in rows
    ]
    ids = [s.varcd for s in series]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate varcd in {path}")
    return series
