import datetime as dt
import io
import json
import urllib.error

import pytest

from ptdata import ine
from ptdata.cli import FIXTURES
from ptdata.transport import ExtractError, FixtureTransport, HttpTransport

OK = json.dumps([{"IndicadorCod": "x", "Sucesso": {"Verdadeiro": [{"Msg": "OK"}]}}]).encode()


class FakeOpener:
    """Replays a script of responses: bytes, or an exception to raise."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def __call__(self, request, timeout):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return io.BytesIO(item)


def http_error(code):
    return urllib.error.HTTPError("https://www.ine.pt", code, "error", {}, None)


def make(script, attempts=5):
    sleeps = []
    opener = FakeOpener(script)
    transport = HttpTransport(
        attempts=attempts, sleep=sleeps.append, opener=opener, jitter=lambda: 0.0, log=lambda _: None
    )
    return transport, opener, sleeps


def test_retries_transient_failures_with_exponential_backoff():
    transport, opener, sleeps = make([http_error(503), urllib.error.URLError("reset"), TimeoutError(), OK])
    assert transport.get("https://example") == OK
    assert opener.calls == 4
    assert sleeps == [2.0, 4.0, 8.0]


def test_retries_a_200_response_that_is_not_a_valid_payload():
    transport, opener, sleeps = make([b"<html>maintenance</html>", OK])
    assert transport.get("https://example") == OK
    assert opener.calls == 2


def test_does_not_retry_client_errors():
    transport, opener, sleeps = make([http_error(404)])
    with pytest.raises(ExtractError, match="HTTP 404"):
        transport.get("https://example")
    assert opener.calls == 1 and sleeps == []


def test_gives_up_after_max_attempts():
    transport, opener, sleeps = make([http_error(502)] * 3, attempts=3)
    with pytest.raises(ExtractError, match="gave up after 3 attempts"):
        transport.get("https://example")
    assert opener.calls == 3 and len(sleeps) == 2


def test_backoff_is_capped_and_jittered():
    transport = HttpTransport(backoff=2.0, max_backoff=60.0, jitter=lambda: 1.0)
    assert transport.delay(1) == 2.5
    assert transport.delay(10) == 75.0  # 60s cap + 25% jitter


def test_fixture_transport_filters_like_the_api(fixture_transport):
    url = ine.data_url("0012103", ["S3A202501", "S3A202502"], geos=["11A1312"], breakdown=["2"])
    doc = ine.parse_payload(fixture_transport.get(url))
    assert set(doc["Dados"]) == {"Janeiro de 2025", "Fevereiro de 2025"}
    records = [r for recs in doc["Dados"].values() for r in recs]
    assert {(r["geocod"], r["dim_3"]) for r in records} == {("11A1312", "2")}


def test_fixture_transport_empty_period_returns_latest_only(fixture_transport):
    url = ine.data_url("0012848", ["S3A202401"]).replace("Dim1=S3A202401", "Dim1=")
    doc = ine.parse_payload(fixture_transport.get(url))
    assert len(doc["Dados"]) == 1


def test_fixture_transport_as_of_hides_later_months():
    transport = FixtureTransport(FIXTURES, as_of=dt.date(2026, 6, 1))
    meta = ine.parse_payload(transport.get(ine.meta_url("0012848")))
    assert ine.monthly_periods(meta)[-1] == "S3A202606"
    assert meta["UltimoPeriodo"] == "Junho de 2026"
    url = ine.data_url("0012848", ["S3A202606", "S3A202607"])
    assert set(ine.parse_payload(transport.get(url))["Dados"]) == {"Junho de 2026"}
