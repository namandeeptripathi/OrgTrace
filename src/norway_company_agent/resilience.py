"""Stage 11: Production Network Resilience & Failure Recovery.

Provides bounded, safe execution with retry, rate-limit backoff, and partial failure handling:
- Distinguishes retryable HTTP errors (429, 5xx) from non-retryable (400, 401, 403, 404, 410)
- Enforces exponential backoff with jitter and respects 'Retry-After' headers
- Guarantees finite retry bounds (zero infinite retry loops)
- Explicit representation of partial failures
- Safe JSON decoding with graceful malformed response handling
"""

from __future__ import annotations

import email.utils
import json
import random
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from .url_safety import assert_public_url


T = TypeVar("T")


RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
NON_RETRYABLE_STATUS_CODES = frozenset({400, 401, 403, 404, 410, 422})


class ResilienceError(Exception):
    """Base exception for resilience and network execution failures."""
    pass


class NonRetryableHttpError(ResilienceError):
    """Raised when an HTTP error is definitively non-retryable (e.g. 401, 403, 404, 410)."""
    def __init__(self, status_code: int, message: str):
        super().__init__(f"HTTP {status_code}: {message}")
        self.status_code = status_code


class RateLimitExceededError(ResilienceError):
    """Raised when rate limits (HTTP 429) are repeatedly encountered and retries exhausted."""
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class UpstreamTimeoutError(ResilienceError):
    """Raised when upstream calls repeatedly time out."""
    pass


class MalformedResponseError(ResilienceError):
    """Raised when an upstream response body is corrupt or invalid JSON."""
    pass


@dataclass(frozen=True)
class RetryPolicy:
    """Configurable, bounded retry policy."""
    max_retries: int = 3
    base_delay: float = 0.4
    max_delay: float = 5.0
    exponential_factor: float = 2.0
    jitter: bool = True
    retryable_statuses: frozenset[int] = RETRYABLE_STATUS_CODES
    non_retryable_statuses: frozenset[int] = NON_RETRYABLE_STATUS_CODES

    def compute_delay(self, attempt: int, retry_after_header: str | None = None) -> float:
        """Compute delay in seconds for an attempt with exponential backoff and jitter."""
        if retry_after_header:
            parsed = parse_retry_after(retry_after_header)
            if parsed is not None:
                return min(parsed, self.max_delay)

        delay = self.base_delay * (self.exponential_factor ** attempt)
        if self.jitter:
            delay += random.uniform(0, 0.1 * delay)
        return min(delay, self.max_delay)


def parse_retry_after(header_value: str | None) -> float | None:
    """Parse HTTP 'Retry-After' header (either seconds or HTTP-date)."""
    if not header_value:
        return None
    val = header_value.strip()
    try:
        # Seconds format
        secs = float(val)
        return max(0.0, secs)
    except ValueError:
        pass

    try:
        # Date format
        dt = email.utils.parsedate_to_datetime(val)
        diff = (dt - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, diff)
    except Exception:
        return None


def execute_with_retry(
    operation: Callable[[], T],
    policy: RetryPolicy | None = None,
    on_retry: Callable[[int, Exception, float], None] | None = None,
) -> T:
    """Execute a callable with bounded retry and backoff.

    Guarantees:
    - Never loops infinitely; capped at policy.max_retries.
    - Fails immediately on non-retryable errors.
    - Applies backoff for retryable errors.
    """
    pol = policy or RetryPolicy()
    last_exc: Exception | None = None

    for attempt in range(pol.max_retries + 1):
        try:
            return operation()
        except urllib.error.HTTPError as exc:
            last_exc = exc
            code = exc.code
            if code in pol.non_retryable_statuses or attempt >= pol.max_retries:
                if code in pol.non_retryable_statuses:
                    raise NonRetryableHttpError(code, f"Non-retryable HTTP error on attempt {attempt + 1}") from exc
                if code == 429:
                    retry_after = parse_retry_after(exc.headers.get("Retry-After")) if exc.headers else None
                    raise RateLimitExceededError(f"HTTP 429 Rate Limit exceeded after {attempt + 1} attempts", retry_after) from exc
                raise ResilienceError(f"HTTP {code} failure after {attempt + 1} attempts") from exc

            # Retryable error: wait and continue
            retry_after_hdr = exc.headers.get("Retry-After") if exc.headers else None
            delay = pol.compute_delay(attempt, retry_after_hdr)
            if on_retry:
                on_retry(attempt + 1, exc, delay)
            time.sleep(delay)

        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            last_exc = exc
            if attempt >= pol.max_retries:
                if isinstance(exc, (TimeoutError, socket.timeout)) or "timed out" in str(exc).lower():
                    raise UpstreamTimeoutError(f"Operation timed out after {attempt + 1} attempts") from exc
                raise ResilienceError(f"Network connection failed after {attempt + 1} attempts: {exc}") from exc

            delay = pol.compute_delay(attempt)
            if on_retry:
                on_retry(attempt + 1, exc, delay)
            time.sleep(delay)

    raise ResilienceError(f"Operation failed after {pol.max_retries + 1} attempts") from last_exc


@dataclass
class PartialFailureResult:
    """Explicit container for partial operations where some sub-components succeeded."""
    is_partial: bool
    succeeded_components: list[str] = field(default_factory=list)
    failed_components: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_partial": self.is_partial,
            "succeeded_components": list(self.succeeded_components),
            "failed_components": list(self.failed_components),
            "errors": dict(self.errors),
            "data": dict(self.data),
        }
