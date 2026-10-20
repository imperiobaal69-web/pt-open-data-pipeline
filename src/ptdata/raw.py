"""Immutable raw layer.

Every response is stored exactly as received under
``<root>/ine/<varcd>/<kind>/<retrieved_utc>_<sha12>.json`` and recorded in an
append-only ``manifest.jsonl`` (URL, retrieval time, SHA-256, size). Files are
written atomically, made read-only, and never overwritten. The warehouse is
rebuilt from this layer, so it can always be thrown away. A response that
is byte-identical to the previous one for the same URL is not stored again.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


class RawLayerError(Exception):
    pass


@dataclass(frozen=True)
class ManifestEntry:
    source: str
    kind: str
    varcd: str
    url: str
    retrieved_utc: str
    sha256: str
    bytes: int
    path: str
    transport: str

    @property
    def retrieved(self) -> dt.datetime:
        return dt.datetime.fromisoformat(self.retrieved_utc)


def sha256_hex(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


class RawStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.manifest_path = self.root / "manifest.jsonl"

    def put(
        self,
        kind: str,
        varcd: str,
        url: str,
        body: bytes,
        transport: str,
        now: dt.datetime | None = None,
    ) -> ManifestEntry:
        now = (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC).replace(microsecond=0)
        digest = sha256_hex(body)
        previous = self.latest(url)
        if previous is not None and previous.sha256 == digest and (self.root / previous.path).exists():
            return previous  # unchanged since the last retrieval: nothing new to store
        rel = Path("ine", varcd, kind, f"{now.strftime('%Y%m%dT%H%M%SZ')}_{digest[:12]}.json")
        path = self.root / rel
        if path.exists():
            if sha256_hex(path.read_bytes()) != digest:
                raise RawLayerError(f"refusing to overwrite {path} with different content")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
            with os.fdopen(fd, "wb") as f:
                f.write(body)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            path.chmod(0o444)
        entry = ManifestEntry(
            source="ine",
            kind=kind,
            varcd=varcd,
            url=url,
            retrieved_utc=now.isoformat(),
            sha256=digest,
            bytes=len(body),
            path=rel.as_posix(),
            transport=transport,
        )
        self.root.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        return entry

    def entries(self) -> list[ManifestEntry]:
        if not self.manifest_path.exists():
            return []
        with self.manifest_path.open(encoding="utf-8") as f:
            return [ManifestEntry(**json.loads(line)) for line in f if line.strip()]

    def latest(self, url: str) -> ManifestEntry | None:
        for entry in reversed(self.entries()):
            if entry.url == url:
                return entry
        return None

    def read(self, entry: ManifestEntry) -> bytes:
        body = (self.root / entry.path).read_bytes()
        if sha256_hex(body) != entry.sha256:
            raise RawLayerError(f"checksum mismatch for {entry.path}")
        return body

    def cached(self, url: str, max_age: dt.timedelta, now: dt.datetime | None = None) -> ManifestEntry | None:
        """Most recent intact snapshot of exactly this URL, if younger than ``max_age``."""
        now = now or dt.datetime.now(dt.UTC)
        for entry in reversed(self.entries()):
            if entry.url != url:
                continue
            if now - entry.retrieved > max_age:
                return None
            path = self.root / entry.path
            if path.exists() and sha256_hex(path.read_bytes()) == entry.sha256:
                return entry
        return None

    def verify(self) -> list[str]:
        problems = []
        for entry in self.entries():
            path = self.root / entry.path
            if not path.exists():
                problems.append(f"missing: {entry.path}")
            elif sha256_hex(path.read_bytes()) != entry.sha256:
                problems.append(f"checksum mismatch: {entry.path}")
        return problems
