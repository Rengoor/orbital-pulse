"""Shared helpers for the NASA fetchers: download, cache raw, write processed.

Raw downloads go to data/nasa/raw/ (git-ignored). Only small processed JSON
files are committed, each carrying where it came from and when it was fetched,
so every value shown downstream can be traced to a dataset and a field.

Owner: person D
"""

from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

NASA_DIR = Path(__file__).resolve().parent
RAW_DIR = NASA_DIR / "raw"

# A generic client name: no personal or project details leave the machine.
_HEADERS = {"User-Agent": "astro-health-data-fetch/0.1", "Accept": "*/*"}


def _ssl_context() -> ssl.SSLContext:
    """Verify certificates against the certifi bundle when it is installed.

    The Windows system store can hold an expired intermediate that makes
    Python reject NASA hosts that browsers accept. Verification stays on.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "Z"


def download(url: str, raw_name: str, params: list[tuple[str, str]] | None = None, timeout: float = 120.0) -> bytes:
    """GET *url* (plus *params*), keep a copy under raw/, return the bytes."""
    if params:
        url = url + "?" + "&".join(
            # RadLab filters are bare expressions such as "timestamp>=2024-05-08T00:00".
            urllib.parse.quote(k, safe="<>=:") + ("=" + urllib.parse.quote(v, safe="") if v is not None else "")
            for k, v in params
        )
    request = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
        body = response.read()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / raw_name).write_bytes(body)
    return body


def write_processed(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def read_processed(path: Path) -> dict | None:
    """Load a processed file, or None when it has not been built yet."""
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)
