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
from enum import Enum
import json
import random
import socket
import threading
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


# ============================================================================
# Stage 19: Standardized Failure Classification
# ============================================================================

class FailureCategory(str, Enum):
    """Standardized failure categories for competition diagnostics and isolation."""
    NETWORK = "NETWORK"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    AUTH = "AUTH"
    NOT_FOUND = "NOT_FOUND"
    PARSE = "PARSE"
    BUDGET = "BUDGET"
    CONFIGURATION = "CONFIGURATION"
    UNKNOWN = "UNKNOWN"


def classify_failure(
    exception: Exception | str | None,
    status_code: int | None = None,
) -> FailureCategory:
    """Classify an exception, status code, or error message into standardized failure categories."""
    if status_code is not None:
        if status_code in {401, 403}:
            return FailureCategory.AUTH
        if status_code in {404, 410}:
            return FailureCategory.NOT_FOUND
        if status_code == 429:
            return FailureCategory.RATE_LIMIT
        if status_code in {500, 502, 503, 504}:
            return FailureCategory.NETWORK

    if exception is None:
        return FailureCategory.UNKNOWN

    if isinstance(exception, UpstreamTimeoutError):
        return FailureCategory.TIMEOUT
    if isinstance(exception, (TimeoutError, socket.timeout)):
        return FailureCategory.TIMEOUT
    if isinstance(exception, RateLimitExceededError):
        return FailureCategory.RATE_LIMIT
    if isinstance(exception, MalformedResponseError):
        return FailureCategory.PARSE
    if isinstance(exception, NonRetryableHttpError):
        code = getattr(exception, "status_code", None)
        if code in {401, 403}:
            return FailureCategory.AUTH
        if code in {404, 410}:
            return FailureCategory.NOT_FOUND
    if isinstance(exception, json.JSONDecodeError):
        return FailureCategory.PARSE
    if isinstance(exception, urllib.error.HTTPError):
        if exception.code in {401, 403}:
            return FailureCategory.AUTH
        if exception.code in {404, 410}:
            return FailureCategory.NOT_FOUND
        if exception.code == 429:
            return FailureCategory.RATE_LIMIT
        if exception.code in {500, 502, 503, 504}:
            return FailureCategory.NETWORK
    if isinstance(exception, urllib.error.URLError):
        reason_str = str(getattr(exception, "reason", "")).lower()
        if "timed out" in reason_str or "timeout" in reason_str:
            return FailureCategory.TIMEOUT
        return FailureCategory.NETWORK
    if isinstance(exception, (ConnectionResetError, ConnectionRefusedError, BrokenPipeError, socket.error)):
        return FailureCategory.NETWORK

    err_str = str(exception).lower()
    if any(k in err_str for k in ("budget", "request_budget", "time_budget", "cost_budget", "exhausted")):
        return FailureCategory.BUDGET
    if "timeout" in err_str or "timed out" in err_str:
        return FailureCategory.TIMEOUT
    if "rate limit" in err_str or "429" in err_str:
        return FailureCategory.RATE_LIMIT
    if any(k in err_str for k in ("unauthorized", "forbidden", "auth")):
        return FailureCategory.AUTH
    if any(k in err_str for k in ("not found", "404", "not_found")):
        return FailureCategory.NOT_FOUND
    if any(k in err_str for k in ("jsondecodeerror", "parse", "malformed", "syntax")):
        return FailureCategory.PARSE
    if any(k in err_str for k in ("config", "api key", "missing environment")):
        return FailureCategory.CONFIGURATION
    if any(k in err_str for k in ("network", "connection", "reset", "refused", "dns")):
        return FailureCategory.NETWORK

    return FailureCategory.UNKNOWN


# ============================================================================
# Stage 19: Competition Execution Guard
# ============================================================================

class CompetitionExecutionGuard:
    """Thread-safe controller enforcing competition limits:

    - Maximum 2,000 external requests per execution
    - Maximum $10.00 external API spend
    - Maximum 45 minutes (2,700s) execution time
    - Automated transition to reduced-enrichment mode at 40 minutes (2,400s)
    - Formatted competition summary blocks
    """

    def __init__(
        self,
        max_requests: int = 2000,
        max_cost: float = 10.0,
        max_runtime_seconds: float = 2700.0,
        reduced_mode_threshold_seconds: float = 2400.0,
        reduced_mode_remaining_requests: int = 100,
    ):
        self._lock = threading.Lock()
        self.max_requests = max_requests
        self.max_cost = max_cost
        self.max_runtime_seconds = max_runtime_seconds
        self.reduced_mode_threshold_seconds = reduced_mode_threshold_seconds
        self.reduced_mode_remaining_requests = reduced_mode_remaining_requests

        self.requests_used = 0
        self.cost_incurred = 0.0
        self.start_time = time.monotonic()
        self.domain_requests: dict[str, int] = {}
        self.failures_by_category: dict[FailureCategory, int] = {cat: 0 for cat in FailureCategory}
        self._reduced_mode_entered = False
        self._reduced_mode_logged = False
        self._stopped_reason: str | None = None

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.start_time

    @property
    def remaining_seconds(self) -> float:
        return max(0.0, self.max_runtime_seconds - self.elapsed_seconds)

    @property
    def remaining_requests(self) -> int:
        return max(0, self.max_requests - self.requests_used)

    @property
    def remaining_cost(self) -> float:
        return max(0.0, self.max_cost - self.cost_incurred)

    def is_reduced_mode(self) -> bool:
        """Check whether execution has entered reduced-enrichment mode."""
        with self._lock:
            if self._reduced_mode_entered:
                return True
            if self.elapsed_seconds >= self.reduced_mode_threshold_seconds:
                self._reduced_mode_entered = True
                return True
            if self.remaining_requests <= self.reduced_mode_remaining_requests:
                self._reduced_mode_entered = True
                return True
            return False

    def should_log_reduced_mode_entry(self) -> bool:
        """Atomically check and flag whether entering reduced-enrichment mode should be logged once."""
        with self._lock:
            if (self.elapsed_seconds >= self.reduced_mode_threshold_seconds or self.remaining_requests <= self.reduced_mode_remaining_requests):
                self._reduced_mode_entered = True
                if not self._reduced_mode_logged:
                    self._reduced_mode_logged = True
                    return True
            return False

    def acquire_request(self, cost: float = 0.0) -> tuple[bool, str | None]:
        """Atomically check and reserve budget for an outbound request."""
        with self._lock:
            if self._stopped_reason:
                return False, self._stopped_reason

            if self.elapsed_seconds >= self.max_runtime_seconds:
                self._stopped_reason = "time_budget_exhausted"
                self.failures_by_category[FailureCategory.BUDGET] += 1
                return False, self._stopped_reason

            if self.requests_used + 1 > self.max_requests:
                self._stopped_reason = "request_budget_exhausted"
                self.failures_by_category[FailureCategory.BUDGET] += 1
                return False, self._stopped_reason

            if self.cost_incurred + cost > self.max_cost:
                self._stopped_reason = "cost_budget_exhausted"
                self.failures_by_category[FailureCategory.BUDGET] += 1
                return False, self._stopped_reason

            self.requests_used += 1
            self.cost_incurred += cost
            return True, None

    def record_request_result(
        self,
        domain: str = "unknown",
        status_code: int = 200,
        failure_category: FailureCategory | None = None,
    ) -> None:
        """Record domain tracking and failure classification."""
        with self._lock:
            self.domain_requests[domain] = self.domain_requests.get(domain, 0) + 1
            if failure_category is not None:
                self.failures_by_category[failure_category] = self.failures_by_category.get(failure_category, 0) + 1

    def format_request_budget(self) -> str:
        """Render request budget summary card."""
        with self._lock:
            used = self.requests_used
            limit = self.max_requests
            remaining = max(0, limit - used)
        return (
            "Request budget\n"
            "--------------\n"
            f"Limit:      {limit:4d}\n"
            f"Used:       {used:4d}\n"
            f"Remaining:  {remaining:4d}"
        )

    def format_cost_budget(self) -> str:
        """Render API spend summary card."""
        with self._lock:
            used = self.cost_incurred
            limit = self.max_cost
            remaining = max(0.0, limit - used)
        return (
            "API spend\n"
            "---------\n"
            f"Limit:     ${limit:6.2f}\n"
            f"Used:      ${used:6.2f}\n"
            f"Remaining: ${remaining:6.2f}"
        )

    def format_execution_budget(self) -> str:
        """Render execution time budget summary card."""
        elapsed_sec = int(self.elapsed_seconds)
        rem_sec = int(self.remaining_seconds)
        max_sec = int(self.max_runtime_seconds)

        def _fmt(secs: int) -> str:
            m = secs // 60
            s = secs % 60
            return f"{m:02d}:{s:02d}"

        return (
            "Execution budget\n"
            "----------------\n"
            f"Maximum:     {_fmt(max_sec)}\n"
            f"Elapsed:     {_fmt(elapsed_sec)}\n"
            f"Remaining:   {_fmt(rem_sec)}"
        )

    def format_batch_summary(
        self,
        attempted: int,
        successful: int,
        partial: int,
        failed: int,
    ) -> str:
        """Render batch completion summary card."""
        elapsed_sec = int(self.elapsed_seconds)
        m = elapsed_sec // 60
        s = elapsed_sec % 60
        time_str = f"{m}m {s:02d}s" if m > 0 else f"{s}s"

        with self._lock:
            used = self.requests_used
            limit = self.max_requests

        return (
            "Batch completed\n\n"
            f"Profiles attempted:{attempted:>8d}\n"
            f"Successful:{successful:>17d}\n"
            f"Partial:{partial:>20d}\n"
            f"Failed:{failed:>21d}\n\n"
            f"External requests:     {used} / {limit}\n"
            f"Elapsed time:        {time_str}"
        )

    def to_dict(self) -> dict[str, Any]:
        """Telemetry export for run report."""
        with self._lock:
            return {
                "max_requests": self.max_requests,
                "requests_used": self.requests_used,
                "remaining_requests": self.remaining_requests,
                "max_cost": self.max_cost,
                "cost_incurred": round(self.cost_incurred, 4),
                "remaining_cost": round(self.remaining_cost, 4),
                "max_runtime_seconds": self.max_runtime_seconds,
                "elapsed_seconds": round(self.elapsed_seconds, 2),
                "remaining_seconds": round(self.remaining_seconds, 2),
                "reduced_mode_entered": self._reduced_mode_entered,
                "stopped_reason": self._stopped_reason,
                "domain_requests": dict(self.domain_requests),
                "failures_by_category": {cat.value: count for cat, count in self.failures_by_category.items() if count > 0},
            }
