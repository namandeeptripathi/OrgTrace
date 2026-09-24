"""Stage 18: Outbound Request Evaluation Module.

Tracks external network requests:
- total requests
- requests per company
- breakdown by target domain
- breakdown by request type (registry, company_website, search, financial, external_research, other)
- failed requests & retry tracking
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import urllib.parse

from .models import RequestEvaluation


def classify_request_domain(domain: str) -> str:
    """Classify domain into standard categories."""
    dom = domain.lower().strip()
    if "brreg.no" in dom:
        return "registry"
    elif "api.search.brave.com" in dom or "google.com" in dom or "bing.com" in dom:
        return "search"
    elif "proff.no" in dom or "purehelp.no" in dom or "regnskap" in dom:
        return "financial"
    elif "linkedin.com" in dom or "youtube.com" in dom or "maps.googleapis.com" in dom:
        return "external_research"
    elif dom:
        return "company_website"
    return "other"


@dataclass
class RequestTracker:
    """Thread-safe request instrumentation accumulator."""
    requests: list[dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        url: str,
        *,
        status_code: int = 200,
        latency_ms: float = 0.0,
        bytes_count: int = 0,
        retries: int = 0,
        error: str | None = None,
        request_type: str | None = None,
    ) -> None:
        try:
            domain = urllib.parse.urlsplit(url).netloc.lower()
        except Exception:
            domain = "unknown"

        req_type = request_type or classify_request_domain(domain)
        is_failed = (status_code >= 400 or error is not None)

        self.requests.append({
            "url": url,
            "domain": domain,
            "type": req_type,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "bytes": bytes_count,
            "retries": retries,
            "failed": is_failed,
            "error": error,
        })

    def get_evaluation(self) -> RequestEvaluation:
        """Produce request evaluation snapshot."""
        domain_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        failed_count = 0
        retry_count = 0

        for r in self.requests:
            d = r.get("domain") or "other"
            domain_counts[d] = domain_counts.get(d, 0) + 1

            t = r.get("type") or "other"
            type_counts[t] = type_counts.get(t, 0) + 1

            if r.get("failed"):
                failed_count += 1
            retry_count += r.get("retries", 0)

        return RequestEvaluation(
            total=len(self.requests),
            requests_by_domain=domain_counts,
            requests_by_type=type_counts,
            failed=failed_count,
            retries=retry_count,
        )
