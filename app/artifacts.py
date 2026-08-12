"""Custody of files that kdb generated on disk.

kdb hands back a *path*. The browser never sees it. Instead the path is checked,
registered under an opaque token, and the browser is given
`/api/download/<token>`. That buys two things:

* the filesystem layout is not public, so nobody can probe it by editing a URL;
* there is exactly one place where a path from kdb is validated, and it refuses
  anything that does not resolve to inside REPORT_DIR.

The realpath comparison is what makes it safe: symlinks and `..` are resolved
*before* the prefix check, so `/reports/../../etc/passwd` fails, and so does a
symlink inside REPORT_DIR pointing somewhere else.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Dict, Optional

from . import config
from .errors import ArtifactMissing, ReportError


class Artifact:
    __slots__ = ("token", "path", "filename", "media_type", "report_id",
                 "created", "size")

    def __init__(self, path: str, filename: str, media_type: str, report_id: str):
        self.token = uuid.uuid4().hex
        self.path = path
        self.filename = filename
        self.media_type = media_type
        self.report_id = report_id
        self.created = time.time()
        self.size = os.path.getsize(path)


def safe_path(raw: str, base: str = None) -> str:
    """Resolve a path kdb returned, refusing anything outside REPORT_DIR."""
    base = os.path.realpath(base or config.REPORT_DIR)
    if not raw or not str(raw).strip():
        raise ReportError("kdb returned an empty file path")
    candidate = str(raw).strip()
    if not os.path.isabs(candidate):
        candidate = os.path.join(base, candidate)
    resolved = os.path.realpath(candidate)
    if resolved != base and not resolved.startswith(base + os.sep):
        raise ReportError(
            "kdb returned a path outside the report directory",
            detail="refused %r" % candidate,
        )
    if not os.path.isfile(resolved):
        raise ReportError(
            "kdb reported a file that is not there",
            detail="missing %r" % candidate,
        )
    return resolved


class ArtifactStore:
    def __init__(self, ttl: float = None):
        self.ttl = config.ARTIFACT_TTL_S if ttl is None else ttl
        self._items: Dict[str, Artifact] = {}
        self._lock = threading.Lock()

    def register(self, raw_path: str, report_id: str,
                 media_type: str = "application/pdf") -> Artifact:
        path = safe_path(raw_path)
        art = Artifact(path, os.path.basename(path), media_type, report_id)
        with self._lock:
            self._items[art.token] = art
        self.sweep()
        return art

    def get(self, token: str) -> Artifact:
        with self._lock:
            art = self._items.get(token)
        if art is None:
            raise ArtifactMissing("that download link has expired or is unknown")
        if not os.path.isfile(art.path):
            with self._lock:
                self._items.pop(token, None)
            raise ArtifactMissing("the generated file is no longer on disk")
        return art

    def sweep(self) -> int:
        """Forget expired tokens. The files themselves are kdb's to clean up."""
        cutoff = time.time() - self.ttl
        with self._lock:
            stale = [t for t, a in self._items.items() if a.created < cutoff]
            for t in stale:
                self._items.pop(t, None)
        return len(stale)

    def count(self) -> int:
        with self._lock:
            return len(self._items)
