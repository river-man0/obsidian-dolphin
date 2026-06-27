"""A tiny caching HTTP downloader.

Geofabrik extracts are large, so we cache them on disk keyed by URL and never
re-download a file that is already present. Local paths and ``file://`` URLs are
passed straight through, which keeps the pipeline runnable fully offline (and
makes it testable without network access).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, unquote


class Downloader:
    def __init__(self, cache_dir: os.PathLike, session=None, timeout: int = 120):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self._session = session

    # ---- session is created lazily so importing the package needs no network.
    @property
    def session(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
            # The agent proxy re-terminates TLS; honour a custom CA bundle if set.
            ca = os.environ.get("REQUESTS_CA_BUNDLE") or os.environ.get(
                "SSL_CERT_FILE"
            )
            if ca:
                self._session.verify = ca
        return self._session

    @staticmethod
    def _local_path(url: str) -> Optional[Path]:
        """Return a filesystem path if ``url`` refers to a local file."""
        parsed = urlparse(url)
        if parsed.scheme in ("", "file"):
            return Path(unquote(parsed.path) if parsed.scheme == "file" else url)
        return None

    def _cache_path(self, url: str) -> Path:
        name = Path(urlparse(url).path).name or "download"
        digest = hashlib.sha256(url.encode()).hexdigest()[:12]
        return self.cache_dir / f"{digest}-{name}"

    def fetch(self, url: str) -> Path:
        """Download ``url`` to the cache and return the local path."""
        local = self._local_path(url)
        if local is not None:
            if not local.exists():
                raise FileNotFoundError(f"Local source does not exist: {local}")
            return local

        dest = self._cache_path(url)
        if dest.exists() and dest.stat().st_size > 0:
            return dest

        tmp = dest.with_suffix(dest.suffix + ".part")
        with self.session.get(url, stream=True, timeout=self.timeout) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    if chunk:
                        fh.write(chunk)
        tmp.replace(dest)
        return dest

    def fetch_json(self, url: str) -> dict:
        path = self.fetch(url)
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
