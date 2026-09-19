# OrgTrace — Stage 11: Production Hardening Guide

This document specifies the production architecture, security controls, resilience mechanisms, licensing requirements, and operational procedures for OrgTrace.

---

## 1. Supported Environment & Python Version

- **Supported Python Version**: `Python >= 3.12` (Audited on Python 3.14.7).
- **Supported Operating Systems**: Linux, macOS, Windows (POSIX and Windows paths supported).
- **Package Tooling**: Standard `pip` and modern `uv` workflows supported.

---

## 2. Clean Installation & Reproducible Setup

### Clean Checkout Setup:
```bash
# 1. Clone repository (or navigate to existing workspace)
cd signalpost-starter-kit

# 2. Create isolated virtual environment
python3 -m venv .venv

# 3. Activate virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 4. Install pinned production runtime dependencies
pip install -r requirements.txt

# 5. (Optional) Install development and testing dependencies
pip install -r requirements-dev.txt
```

### Dependency Management & Updates:
- **Production Lock**: [`requirements.txt`](file:///Users/apple/Downloads/signalpost-starter-kit/requirements.txt) contains exact pinned versions for deterministic deployments.
- **Specification**: [`pyproject.toml`](file:///Users/apple/Downloads/signalpost-starter-kit/pyproject.toml) specifies bounded semver constraints (`beautifulsoup4>=4.14,<5`, `extruct>=0.18,<1`, `lxml>=6,<7`, `pydantic>=2.12,<3`, `pypdf>=6,<7`, `tldextract>=5.3,<6`, `trafilatura>=2.0,<3`).
- **Lockfile**: [`uv.lock`](file:///Users/apple/Downloads/signalpost-starter-kit/uv.lock) provides cryptographic hash verification when using `uv`.

---

## 3. Configuration & Secret Management

OrgTrace centralizes configuration in [`norway_company_agent.config`](file:///Users/apple/Downloads/signalpost-starter-kit/src/norway_company_agent/config.py), loading settings from environment variables or `.env` files.

### Template:
A template is provided in [`.env.example`](file:///Users/apple/Downloads/signalpost-starter-kit/.env.example). Copy to `.env` for local deployment:
```bash
cp .env.example .env
```

### Supported Environment Variables:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `ORGTRACE_ENV` | `production` | Environment mode (`production`, `staging`, `development`, `test`) |
| `ORGTRACE_LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |
| `ORGTRACE_LOG_JSON` | `false` | When `true`, emits single-line structured JSON logs |
| `ORGTRACE_REDACT_SECRETS` | `true` | When `true`, automatically redacts secrets and credentials from logs |
| `BRAVE_SEARCH_API_KEY` | *(None)* | Optional API key for Brave Search candidate discovery |
| `BRAVE_SEARCH_API_URL` | `https://api.search.brave.com/res/v1/web/search` | Brave Search API endpoint |
| `BRREG_API_BASE_URL` | `https://data.brreg.no/enhetsregisteret/api` | Brønnøysundregistrene Enhetsregisteret API |
| `BRREG_ACCOUNTS_BASE_URL` | `https://data.brreg.no/regnskapsregisteret/regnskap` | Regnskapsregisteret Annual Accounts API |
| `ORGTRACE_CONNECT_TIMEOUT` | `10.0` | Socket connection timeout in seconds |
| `ORGTRACE_READ_TIMEOUT` | `20.0` | Socket read timeout in seconds |
| `ORGTRACE_MAX_RETRIES` | `3` | Maximum retry attempts for retryable HTTP errors |
| `ORGTRACE_RETRY_BACKOFF` | `0.4` | Base exponential backoff delay in seconds |
| `ORGTRACE_MAX_URL_LENGTH` | `4096` | Maximum allowed URL length in characters |
| `ORGTRACE_ENFORCE_DNS_CHECK` | `false` | When `true`, resolves hostnames and checks all IPs against SSRF rules |
| `ORGTRACE_DEFAULT_ENVELOPE_COUNT` | `100` | Default maximum evaluation envelope size |
| `ORGTRACE_DEFAULT_REQUEST_BUDGET` | `500` | Default request budget for batch evaluations |
| `ORGTRACE_DEFAULT_RUNTIME_BUDGET` | `300.0` | Default batch runtime budget in seconds |
| `ORGTRACE_DEFAULT_COST_BUDGET` | `10.0` | Default batch cost budget in USD |

### Secret Redaction Guarantees:
- Secrets are **never** committed to version control (`.env` and `.env.*` are ignored in `.gitignore`).
- `SecretRedactionFilter` inspects all log messages and parameters, replacing sensitive values with `secr****1234` or `[REDACTED]`.
- Regex patterns detect and redact `Authorization: Bearer ...` and `X-Subscription-Token: ...` headers.
- Calling `require_brave_api_key()` when unset raises `MissingCredentialError` with an actionable message, never exposing raw credentials or fake placeholders.

---

## 4. URL Safety & SSRF Defenses

Centralized in [`norway_company_agent.url_safety`](file:///Users/apple/Downloads/signalpost-starter-kit/src/norway_company_agent/url_safety.py):

### Defense Layers:
1. **Scheme Validation**: Strictly allows `http` and `https`. Dangerous schemes (`file://`, `javascript:`, `data:`, `vbscript:`, `ftp:`, `gopher:`) raise `DangerousSchemeError`.
2. **Credential Injection Prevention**: URLs with embedded userinfo (`http://user:pass@host`) raise `EmbeddedCredentialsError`.
3. **Length Enforcement**: URLs exceeding 4,096 characters raise `UrlLengthExceededError`.
4. **SSRF & Private Network Blocking**:
   - Blocks `localhost`, `*.localhost`, `*.local`, `*.internal`, `*.corp`, `*.lan`.
   - Blocks loopback (`127.0.0.0/8`, `::1`), link-local (`169.254.0.0/16`), private (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), multicast, and reserved IPs.
   - Raises `PrivateNetworkAccessError`.
5. **URL Sanitization for Logging (`sanitize_url_for_logging`)**:
   - Masks embedded credentials (`[REDACTED]:[REDACTED]@host`).
   - Redacts sensitive query parameters (`api_key`, `token`, `secret`, `password`, `auth`).

---

## 5. Network Resilience & Failure Recovery

Centralized in [`norway_company_agent.resilience`](file:///Users/apple/Downloads/signalpost-starter-kit/src/norway_company_agent/resilience.py) and [`norway_company_agent.http`](file:///Users/apple/Downloads/signalpost-starter-kit/src/norway_company_agent/http.py):

### Retry Policy & Error Classification:
- **Retryable Status Codes**: `429` (Rate Limited), `500` (Internal Server Error), `502` (Bad Gateway), `503` (Service Unavailable), `504` (Gateway Timeout).
  - Retried up to `max_retries` (default 3) with exponential backoff and jitter (`base_delay * (2 ^ attempt) + random_jitter`).
  - Respects `Retry-After` header (seconds or RFC 7231 HTTP-date) up to a 5.0s cap.
- **Non-Retryable Status Codes**: `400` (Bad Request), `401` (Unauthorized), `403` (Forbidden), `404` (Not Found), `410` (Gone), `422` (Unprocessable Entity).
  - Fails immediately on attempt 1 without wasteful retries (`NonRetryableHttpError`).
- **Infinite Retry Prevention**: Retries are strictly bounded by `max_retries`.
- **Partial Failure Representation**: `PartialFailureResult` explicitly separates succeeded from failed components without silent data corruption.

---

## 6. Source Licensing & Attribution

Centralized in [`norway_company_agent.licensing`](file:///Users/apple/Downloads/signalpost-starter-kit/src/norway_company_agent/licensing.py):

| Source / Domain | License Type | License Name | Attribution Required | Attribution Statement |
| :--- | :--- | :--- | :--- | :--- |
| `data.brreg.no` / `brreg.no` | `NLOD-2.0` | Norsk lisens for offentlige data | Yes | *"Inneholder data under Norsk lisens for offentlige data (NLOD) tilgjengeliggjort av Brønnøysundregistrene."* |
| `lovdata.no` | `public_sector_information` | Public Sector Legal Information | Yes | *"Kilde: Lovdata."* |
| `ssb.no` | `NLOD-2.0` | Norsk lisens for offentlige data | Yes | *"Kilde: Statistisk sentralbyrå (SSB)."* |
| `search.brave.com` | `commercial_terms_of_service` | Brave Search API Terms | Yes | *"Search candidate results provided via Brave Search API."* |
| Company Websites | `first_party_copyright` | First-Party Website Terms | Yes | *"Attributed to first-party company website ({domain})."* |
| `proff.no` / `purehelp.no` | `proprietary_restricted` | Proprietary Commercial Database | N/A | Automated scraping is strictly blocked by policy. |
| Unknown Domains | `unknown_unverified` | Unverified External License | Yes | *"Source: {domain}."* (Factual claims only; licensing unverified). |

---

## 7. Logging & Observability

### Structured Logging ([`logging_utils.py`](file:///Users/apple/Downloads/signalpost-starter-kit/src/norway_company_agent/logging_utils.py)):
- Standard Python `logging` with `norway_company_agent` root logger.
- `SecretRedactionFilter` automatically attached to all handlers.
- Format options:
  - Standard human-readable: `2026-09-20T01:00:00Z [INFO] norway_company_agent: ...`
  - Structured JSON (`ORGTRACE_LOG_JSON=true`): `{"timestamp": "...", "level": "INFO", "engine": "...", "operation": "...", "duration_ms": 45.2, ...}`

### Lightweight Observability ([`observability.py`](file:///Users/apple/Downloads/signalpost-starter-kit/src/norway_company_agent/observability.py)):
- `ProductionMetricsCollector` provides in-memory telemetry without external infrastructure overhead:
  - Operation counts and durations per engine
  - Success and failure counts with exact success rate
  - Total, failed, retried, and duplicate request counts
  - Error category distribution
  - Snapshot refresh outcome breakdown
- Access via `ProductionMetricsCollector.get_instance().get_metrics_snapshot()`.

---

## 8. Failure-Safe Data Handling & Refresh Invariants

- **Failed-Refresh Preservation**: When an upstream source fails or returns an error, the previous verified snapshot is **preserved intact**.
- **Zero False Removals**: A network timeout or HTTP 500 is never interpreted as a claim deletion.
- **Snapshot Immutability**: `CompanySnapshot` instances are frozen upon creation; mutation attempts raise `AttributeError`.
- **Semantic Normalization**: Comparisons (`is_material_change`) ignore formatting, whitespace, dictionary key order, and timestamp noise.

---

## 9. Production Validation Suite

To run the complete production validation suite:

```bash
# Run full unit test suite (254 tests)
PYTHONPATH=src /Users/apple/Downloads/signalpost-starter-kit/.venv/bin/python -m unittest tests.test_poc -v

# Run Stage 10 Evaluation Harness benchmark
PYTHONPATH=src /Users/apple/Downloads/signalpost-starter-kit/.venv/bin/python -c "
from norway_company_agent.evaluation import EvaluationHarness
report = EvaluationHarness().run()
print(report.to_markdown())
"
```
