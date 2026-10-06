from __future__ import annotations

import gzip
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class HttpError(RuntimeError):
    pass


def _decode_response(response) -> dict[str, Any]:
    raw = response.read()
    if response.headers.get("Content-Encoding", "").lower() == "gzip":
        raw = gzip.decompress(raw)
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HttpError("Remote service returned invalid JSON") from exc


def get_json(url: str, params: dict[str, Any], timeout: int) -> dict[str, Any]:
    query = urlencode({k: v for k, v in params.items() if v is not None})
    request = Request(
        f"{url}?{query}",
        method="GET",
        headers={"Accept": "application/json", "Accept-Encoding": "gzip", "User-Agent": "amazon-deals-telegram/0.2.0"},
    )
    return _execute(request, timeout)


def post_json(url: str, payload: Any, timeout: int, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = urlencode({k: v for k, v in (params or {}).items() if v is not None})
    final_url = f"{url}?{query}" if query else url
    request = Request(
        final_url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": "amazon-deals-telegram/0.2.0",
        },
    )
    return _execute(request, timeout)


def _execute(request: Request, timeout: int) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=timeout) as response:
            return _decode_response(response)
    except HTTPError as exc:
        raw = exc.read()
        if exc.headers.get("Content-Encoding", "").lower() == "gzip":
            raw = gzip.decompress(raw)
        detail = raw.decode("utf-8", errors="replace")[:1000]
        raise HttpError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise HttpError(f"Network error: {exc.reason}") from exc
