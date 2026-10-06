from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HttpError(RuntimeError):
    pass


def post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": "amazon-deals-telegram/0.1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            # urllib normally handles HTTP transport but not gzip content decoding.
            if response.headers.get("Content-Encoding", "").lower() == "gzip":
                import gzip

                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise HttpError(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise HttpError(f"Network error: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise HttpError("Remote service returned invalid JSON") from exc
