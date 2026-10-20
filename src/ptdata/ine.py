"""INE JSON indicator API: URL construction and response parsing.

Behaviour verified against the live API (it is not documented):

* ``Dim1`` holds periods. Monthly periods are ``S3A`` + ``YYYYMM``. An empty
  ``Dim1`` returns only the latest period, so every month must be enumerated.
* ``Dim2`` holds geography (NUTS 2024 + municipalities). Empty means all units.
* ``Dim3`` holds the breakdown of the indicator (channel, card origin, CAE).
  A long ``Dim3`` list (e.g. 915 CAE subclass codes) fails server-side with
  ORA-06502; an empty ``Dim3`` returns every category instead.
* A successful payload carries ``"Sucesso": {"Verdadeiro": [...]}``. When the
  service is degraded it can answer HTTP 200 with an HTML page or a
  ``"Falso"`` status, so the body is validated, not just the status code.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any
from urllib.parse import urlencode

DATA_ENDPOINT = "https://www.ine.pt/ine/json_indicador/pindica.jsp"
META_ENDPOINT = "https://www.ine.pt/ine/json_indicador/pindicaMeta.jsp"
MONTH_PREFIX = "S3A"


class IneResponseError(Exception):
    """The API answered, but not with a usable payload."""


def meta_url(varcd: str) -> str:
    return f"{META_ENDPOINT}?{urlencode({'varcd': varcd, 'lang': 'PT'})}"


def data_url(
    varcd: str,
    periods: list[str],
    geos: list[str] | tuple[str, ...] = (),
    breakdown: list[str] | tuple[str, ...] = (),
) -> str:
    if not periods:
        raise ValueError("periods must be enumerated: an empty Dim1 returns only the latest period")
    query = {
        "op": "2",
        "varcd": varcd,
        "Dim1": ",".join(periods),
        "Dim2": ",".join(geos),
        "Dim3": ",".join(breakdown),
        "lang": "PT",
    }
    return f"{DATA_ENDPOINT}?{urlencode(query, safe=',')}"


def month_code(month: dt.date) -> str:
    return f"{MONTH_PREFIX}{month.year:04d}{month.month:02d}"


def parse_month_code(code: str) -> dt.date:
    if not (code.startswith(MONTH_PREFIX) and len(code) == 9 and code[3:].isdigit()):
        raise ValueError(f"not a monthly period code: {code!r}")
    year, month = int(code[3:7]), int(code[7:9])
    return dt.date(year, month, 1)


def months_between(start: dt.date, end: dt.date) -> list[str]:
    """Inclusive list of monthly period codes from ``start`` to ``end``."""
    out = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{MONTH_PREFIX}{y:04d}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def parse_payload(body: bytes) -> dict[str, Any]:
    """Decode a metadata or data response and check INE's success flag."""
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise IneResponseError(f"response is not JSON ({len(body)} bytes)") from e
    if isinstance(doc, list):
        if len(doc) != 1 or not isinstance(doc[0], dict):
            raise IneResponseError("expected a single-element JSON array")
        doc = doc[0]
    if not isinstance(doc, dict):
        raise IneResponseError("expected a JSON object")
    status = doc.get("Sucesso") or {}
    if "Verdadeiro" not in status:
        raise IneResponseError(f"INE reported failure: {status!r}")
    return doc


def categories(meta: dict[str, Any], dim_num: str) -> list[dict[str, str]]:
    """Flatten ``Dimensoes.Categoria_Dim`` for one dimension, in INE's order."""
    groups = meta["Dimensoes"]["Categoria_Dim"]
    out = [cat for group in groups for entries in group.values() for cat in entries if cat["dim_num"] == dim_num]
    return sorted(out, key=lambda c: int(c["categ_ord"]))


def monthly_periods(meta: dict[str, Any]) -> list[str]:
    codes = [c["categ_cod"] for c in categories(meta, "1")]
    for code in codes:
        parse_month_code(code)  # raises on a non-monthly series
    return sorted(codes)
