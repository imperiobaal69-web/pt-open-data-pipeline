"""How request URLs become response bytes.

``HttpTransport`` talks to INE with retries and exponential backoff.
``FixtureTransport`` serves committed fixtures and emulates the API's
period / geography / breakdown filtering, so the whole pipeline (including
request chunking and incremental arrival of new months) runs offline.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlsplit

from . import ine

RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}
USER_AGENT = "pt-open-data-pipeline/0.1 (+https://github.com/imperiobaal69-web)"


class ExtractError(Exception):
    """A request failed permanently or exhausted its retries."""


class Transport(Protocol):
    name: str

    def get(self, url: str) -> bytes: ...


class HttpTransport:
    name = "live"

    def __init__(
        self,
        timeout: float = 240.0,
        attempts: int = 5,
        backoff: float = 2.0,
        max_backoff: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        opener: Callable[..., object] = urllib.request.urlopen,
        jitter: Callable[[], float] = random.random,
        log: Callable[[str], None] = print,
    ):
        self.timeout = timeout
        self.attempts = attempts
        self.backoff = backoff
        self.max_backoff = max_backoff
        self.sleep = sleep
        self.opener = opener
        self.jitter = jitter
        self.log = log

    def delay(self, attempt: int) -> float:
        """Exponential backoff with up to 25% jitter: 2s, 4s, 8s, ... capped."""
        base = min(self.max_backoff, self.backoff * 2 ** (attempt - 1))
        return base * (1 + 0.25 * self.jitter())

    def get(self, url: str) -> bytes:
        last: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    body = response.read()
                ine.parse_payload(body)  # INE can return 200 with an error page
                return body
            except urllib.error.HTTPError as e:
                if e.code not in RETRYABLE_HTTP:
                    raise ExtractError(f"HTTP {e.code} for {url}") from e
                last = e
            except (urllib.error.URLError, TimeoutError, ConnectionError, ine.IneResponseError) as e:
                last = e
            if attempt < self.attempts:
                wait = self.delay(attempt)
                self.log(f"    retry {attempt}/{self.attempts - 1} in {wait:.1f}s ({last})")
                self.sleep(wait)
        raise ExtractError(f"gave up after {self.attempts} attempts: {url} ({last})")


class FixtureTransport:
    """Answers requests from ``meta_<varcd>.json`` / ``data_<varcd>.json`` files.

    ``as_of`` hides every month after the given date, which simulates the
    state of the API at an earlier point in time (used to test incremental
    loads when a new month is published).
    """

    name = "fixtures"

    def __init__(self, root: Path, as_of: dt.date | None = None):
        self.root = Path(root)
        self.as_of = as_of

    def _read(self, name: str) -> dict:
        path = self.root / name
        if not path.exists():
            raise ExtractError(f"no fixture {path}")
        return ine.parse_payload(path.read_bytes())

    def _meta(self, varcd: str) -> dict:
        meta = self._read(f"meta_{varcd}.json")
        if self.as_of is None:
            return meta
        meta = copy.deepcopy(meta)
        for group in meta["Dimensoes"]["Categoria_Dim"]:
            for key in list(group):
                cat = group[key][0]
                if cat["dim_num"] == "1" and ine.parse_month_code(cat["categ_cod"]) > self.as_of:
                    del group[key]
        visible = ine.categories(meta, "1")
        meta["UltimoPeriodo"] = visible[-1]["categ_dsg"]
        return meta

    def get(self, url: str) -> bytes:
        parts = urlsplit(url)
        query = {k: v[0] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
        varcd = query["varcd"]
        if url.startswith(ine.META_ENDPOINT):
            return json.dumps([self._meta(varcd)], ensure_ascii=False).encode("utf-8")
        if not url.startswith(ine.DATA_ENDPOINT):
            raise ExtractError(f"fixture transport cannot serve {url}")

        meta = self._meta(varcd)
        label_by_code = {c["categ_cod"]: c["categ_dsg"] for c in ine.categories(meta, "1")}
        wanted_periods = [p for p in query.get("Dim1", "").split(",") if p]
        if not wanted_periods:
            wanted_periods = [max(label_by_code)]  # mirror the API: latest period only
        wanted_labels = {label_by_code[p] for p in wanted_periods if p in label_by_code}
        geos = {g for g in query.get("Dim2", "").split(",") if g}
        breakdown = {b for b in query.get("Dim3", "").split(",") if b}

        doc = self._read(f"data_{varcd}.json")
        filtered = {}
        for label, records in doc["Dados"].items():
            if label not in wanted_labels:
                continue
            keep = [
                r for r in records if (not geos or r["geocod"] in geos) and (not breakdown or r["dim_3"] in breakdown)
            ]
            if keep:
                filtered[label] = keep
        doc = {**doc, "Dados": filtered}
        return json.dumps([doc], ensure_ascii=False).encode("utf-8")
