import datetime as dt
import json
import stat

import pytest

from ptdata.raw import RawLayerError, RawStore, sha256_hex

NOW = dt.datetime(2026, 10, 20, 12, 0, 0, tzinfo=dt.UTC)


def test_put_writes_read_only_file_and_manifest(tmp_path):
    store = RawStore(tmp_path)
    entry = store.put("data", "0012848", "https://x/?a=1", b'{"a": 1}', "live", now=NOW)
    path = tmp_path / entry.path
    assert path.read_bytes() == b'{"a": 1}'
    assert not path.stat().st_mode & stat.S_IWUSR
    assert entry.path == f"ine/0012848/data/20261020T120000Z_{sha256_hex(b'{"a": 1}')[:12]}.json"
    assert entry.bytes == 8 and entry.retrieved_utc == "2026-10-20T12:00:00+00:00"
    assert store.entries() == [entry]


def test_never_overwrites_existing_content(tmp_path):
    store = RawStore(tmp_path)
    entry = store.put("data", "0012848", "u", b"one", "live", now=NOW)
    path = tmp_path / entry.path
    path.chmod(0o644)
    path.write_bytes(b"tampered")
    with pytest.raises(RawLayerError, match="refusing to overwrite"):
        store.put("data", "0012848", "other-url", b"one", "live", now=NOW)


def test_identical_response_is_recorded_as_confirmed_not_stored_twice(tmp_path):
    store = RawStore(tmp_path)
    first = store.put("meta", "a", "u1", b"same", "live", now=NOW)
    again = store.put("meta", "a", "u1", b"same", "live", now=NOW + dt.timedelta(hours=1))
    assert (again.path, again.sha256, again.bytes) == (first.path, first.sha256, first.bytes)
    assert (first.event, again.event) == ("stored", "confirmed")
    assert again.retrieved_utc == "2026-10-20T13:00:00+00:00"
    assert store.entries() == [first, again]
    assert len(list(tmp_path.glob("ine/**/*.json"))) == 1  # one file on disk
    assert store.cached("u1", dt.timedelta(hours=2), now=NOW + dt.timedelta(hours=2, minutes=30)) == again
    assert store.verify() == []


def test_manifest_written_before_the_event_field_still_reads(tmp_path):
    store = RawStore(tmp_path)
    entry = store.put("meta", "a", "u1", b"x", "live", now=NOW)
    legacy = {k: v for k, v in json.loads(store.manifest_path.read_text()).items() if k != "event"}
    store.manifest_path.write_text(json.dumps(legacy) + "\n")
    assert store.entries() == [entry]


def test_manifest_is_append_only(tmp_path):
    store = RawStore(tmp_path)
    store.put("meta", "a", "u1", b"1", "live", now=NOW)
    store.put("meta", "a", "u1", b"2", "live", now=NOW + dt.timedelta(hours=1))
    assert [e.sha256 for e in store.entries()] == [sha256_hex(b"1"), sha256_hex(b"2")]


def test_cache_returns_latest_fresh_snapshot_of_same_url(tmp_path):
    store = RawStore(tmp_path)
    store.put("meta", "a", "u1", b"old", "live", now=NOW)
    newer = store.put("meta", "a", "u1", b"new", "live", now=NOW + dt.timedelta(hours=1))
    later = NOW + dt.timedelta(hours=2)
    assert store.cached("u1", dt.timedelta(hours=24), now=later) == newer
    assert store.cached("u2", dt.timedelta(hours=24), now=later) is None
    assert store.cached("u1", dt.timedelta(minutes=30), now=later) is None


def test_cache_ignores_corrupted_snapshot_and_verify_reports_it(tmp_path):
    store = RawStore(tmp_path)
    entry = store.put("meta", "a", "u1", b"good", "live", now=NOW)
    path = tmp_path / entry.path
    path.chmod(0o644)
    path.write_bytes(b"bad")
    assert store.cached("u1", dt.timedelta.max, now=NOW) is None
    assert store.verify() == [f"checksum mismatch: {entry.path}"]
    with pytest.raises(RawLayerError):
        store.read(entry)
