"""Extract: INE API -> raw layer.

Metadata is fetched first and drives the request: the list of published
months comes from the metadata's period dimension (the data endpoint needs
every month enumerated), and for very wide breakdowns (CAE has 1,963
categories) only the levels named in the catalog are requested.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field

from . import ine
from .catalog import Series
from .raw import ManifestEntry, RawStore
from .transport import Transport


@dataclass
class ExtractSummary:
    requests: int = 0
    cache_hits: int = 0
    bytes_fetched: int = 0
    entries: list[ManifestEntry] = field(default_factory=list)


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def extract(
    store: RawStore,
    transport: Transport,
    catalog: list[Series],
    since: dt.date | None = None,
    max_age: dt.timedelta = dt.timedelta(hours=24),
    chunk_months: int = 60,
    log: Callable[[str], None] = print,
) -> ExtractSummary:
    summary = ExtractSummary()

    def fetch(kind: str, varcd: str, url: str) -> ManifestEntry:
        # Metadata is always re-fetched: it is small and it is what announces
        # newly published months. Data responses are cached by exact URL.
        hit = store.cached(url, max_age) if kind == "data" else None
        if hit is not None:
            summary.cache_hits += 1
            log(f"    cache  {kind:4} {varcd} ({hit.bytes:,} bytes, {hit.retrieved_utc})")
            return hit
        body = transport.get(url)
        entry = store.put(kind, varcd, url, body, transport.name)
        summary.requests += 1
        summary.bytes_fetched += len(body)
        log(f"    fetch  {kind:4} {varcd} ({len(body):,} bytes)")
        return entry

    for series in catalog:
        log(f"  {series.varcd}  {series.description}")
        meta_entry = fetch("meta", series.varcd, ine.meta_url(series.varcd))
        summary.entries.append(meta_entry)
        meta = ine.parse_payload(store.read(meta_entry))

        periods = ine.monthly_periods(meta)
        if since is not None:
            periods = [p for p in periods if ine.parse_month_code(p) >= since]
        if not periods:
            log("    no periods to fetch")
            continue

        breakdown: list[str] = []
        if series.max_breakdown_level is not None:
            breakdown = [
                c["categ_cod"] for c in ine.categories(meta, "3") if int(c["categ_nivel"]) <= series.max_breakdown_level
            ]

        for chunk in _chunks(periods, chunk_months):
            url = ine.data_url(series.varcd, chunk, geos=(), breakdown=breakdown)
            summary.entries.append(fetch("data", series.varcd, url))
    return summary
