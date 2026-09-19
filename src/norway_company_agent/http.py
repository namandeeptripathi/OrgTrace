"""Stage 11: Production-hardened HTTP fetcher.

Provides safe, bounded HTTP JSON fetching with:
- SSRF and URL safety enforcement via assert_public_url
- Bounded retries and exponential backoff
- 429 Rate-limit and Retry-After header awareness
- Cryptographic SHA-256 fingerprinting of response bytes
- Safe JSON decoding without unhandled exceptions
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .resilience import parse_retry_after
from .url_safety import assert_public_url, sanitize_url_for_logging


USER_AGENT = "builderr-signalpost-poc/0.1 (+https://builderr.ai)"


@dataclass
class FetchResult:
    url: str
    status: int
    elapsed_ms: int
    bytes_received: int
    body: Any = None
    error: str | None = None
    content_sha256: str | None = None
    retrieved_at: str | None = None
    effective_at: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_json(url: str, *, timeout: float = 20.0, attempts: int = 3) -> FetchResult:
    """Fetch JSON from a URL with URL safety validation and bounded retries."""
    # 1. URL Safety Check
    try:
        assert_public_url(url)
    except Exception as exc:
        sanitized = sanitize_url_for_logging(url)
        return FetchResult(sanitized, 0, 0, 0, error=f"Blocked unsafe URL: {exc}", retrieved_at=_utc_now())

    last_error = "request failed"
    for attempt in range(attempts):
        started = time.monotonic()
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                elapsed = int((time.monotonic() - started) * 1000)
                sha = hashlib.sha256(raw).hexdigest()
                try:
                    parsed_body = json.loads(raw)
                except Exception as json_exc:
                    return FetchResult(url, response.status, elapsed, len(raw), error=f"JSONDecodeError: {json_exc}", content_sha256=sha, retrieved_at=_utc_now())

                return FetchResult(
                    url,
                    response.status,
                    elapsed,
                    len(raw),
                    body=parsed_body,
                    content_sha256=sha,
                    retrieved_at=_utc_now(),
                )

        except urllib.error.HTTPError as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            raw = exc.read()
            sha = hashlib.sha256(raw).hexdigest() if raw else None

            # Non-retryable definitive client errors
            if exc.code in {400, 401, 403, 404, 410, 422}:
                return FetchResult(
                    url,
                    exc.code,
                    elapsed,
                    len(raw),
                    error=f"HTTP {exc.code}",
                    content_sha256=sha,
                    retrieved_at=_utc_now(),
                )

            last_error = f"HTTP {exc.code}"

            # 429 Rate Limit: check Retry-After
            if exc.code == 429:
                retry_after = parse_retry_after(exc.headers.get("Retry-After")) if exc.headers else None
                if retry_after is not None and attempt + 1 < attempts:
                    time.sleep(min(retry_after, 5.0))
                    continue

        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = type(exc).__name__

        if attempt + 1 < attempts:
            time.sleep(0.4 * (2**attempt))

    return FetchResult(url, 0, 0, 0, error=last_error, retrieved_at=_utc_now())
