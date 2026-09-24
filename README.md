# OrgTrace — Norwegian Enterprise Intelligence Engine

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: NLOD 2.0 / MIT](https://img.shields.io/badge/License-NLOD%202.0%20%2F%20MIT-green.svg)](docs/dependencies-and-licenses.md)
[![Tests: 254 Passed](https://img.shields.io/badge/tests-254%20passed-brightgreen.svg)](docs/final-evaluation.md)
[![Profiles: 1,000+ Verified](https://img.shields.io/badge/profiles-%E2%89%A51%2C000%20verified-success.svg)](docs/final-evaluation.md)

---

## 1. Problem Statement

Automated company research in Norway faces severe challenges with identity confusion, entity drift, and hallucinated corporate footprints. Holding companies, operating subsidiaries, franchise networks, and similarly named regional firms frequently share brand names, physical addresses, or executive leadership, causing naive crawlers to attribute corporate websites, financial statements, and employee counts to the wrong legal entity. Furthermore, web scraping often violates terms of service or yields unverified claims lacking cryptographic provenance. **OrgTrace** solves this by establishing a mathematically grounded, evidence-first research pipeline that anchors every corporate claim in official Norwegian public registry records (Brønnøysundregistrene) and verified first-party digital assets, producing auditable, deterministic company intelligence at scale with zero silent drops.

---

## 2. What OrgTrace Does

OrgTrace ingests batches of Norwegian 9-digit organisation numbers (*organisasjonsnummer*), resolves corporate identity against canonical registry datasets, enriches profiles with official financial reports and leadership roles, discovers and verifies first-party company websites through strict identity gates, tracks semantic mutations over time, and emits deterministic, machine-readable JSONL envelopes with complete source provenance.

---

## 3. Key Capabilities

- **Exact Company Identity Resolution**: Enforces Modulo 11 check digit validation and exact legal entity matching. Rejects lookalikes, parent holding companies, and distinct subsidiaries lacking exact organisation number correlation.
- **Official Financial & Governance Intelligence**: Integrates with Regnskapsregisteret to extract revenues, operating profit, total assets, and accounting obligations under the Norwegian Accounting Act (*Regnskapsloven*).
- **Evidence-Gated Website Discovery**: Discovers and verifies first-party company domains. Crawls candidate homepages and contact pages, requiring explicit corporate identifier correlation before publishing.
- **Cryptographic Provenance Engine**: Accompanies every claim with source URLs, retrieval timestamps, content SHA-256 hashes, and extracted claim spans.
- **Change Intelligence & Failed-Refresh Preservation**: Differentiates material corporate changes from formatting or timestamp noise. Preserves verified claims during upstream network or API outages with zero false removals.
- **Bounded Competition Batch Processing**: Processes cohorts of ≥ 1,000 companies with thread-safe request budgets, runtime limits, cost caps, and resumable caching.
- **Zero Restricted Scraping**: Operates strictly within lawful public data licenses (NLOD 2.0) and robots.txt policies, completely avoiding unauthorized scraping of commercial directories (e.g., `proff.no`, `purehelp.no`, `linkedin.com`).

---

## 4. High-Level Architecture

OrgTrace is organized into decoupled, deterministic pipeline stages:

```
[ Input Batch ] 
       │
       ▼
[ Identity Engine ] ─────────► Canonicalize 9-digit Org Number & Modulo 11 Check
       │                      Lookup baseline metadata in bulk snapshot (brreg-enheter.csv)
       ▼
[ Discovery & Gating ] ──────► Resolve official website or query Brave Search fallback
       │                      Apply Identity Gate (require org number / address match)
       ▼
[ Extraction & Financials ] ─► Query Regnskapsregisteret for annual accounts & metrics
       │                      Extract leadership roles, registered locations, contacts
       ▼
[ Evidence & Snapshots ] ────► Hash evidence content (SHA-256), generate claim provenance
       │                      Detect material semantic changes vs prior snapshots
       ▼
[ Terminal Output ] ─────────► Validate envelopes (zero silent drops, all states terminal)
                              Emit out/envelopes.jsonl, out/profiles.jsonl, out/run-report.json
```

For full architectural details and Mermaid diagrams, see [`docs/architecture.md`](docs/architecture.md).

---

## 5. End-to-End Pipeline

1. **Intake & Normalization**: Normalizes inputs to 9-digit strings, rejects duplicates, and validates check digits.
2. **Bulk Registry Lookup**: Reads canonical registration status, legal form, municipality, and industry code from `brreg-enheter.csv`.
3. **Accounting Obligation Assessment**: Deterministically evaluates statutory filing obligations based on corporate form and size thresholds.
4. **Live Enrichment (Optional)**: Queries official REST endpoints for live updates, annual accounts, executive board members, and workplaces.
5. **Website Verification Gate**: Crawls candidate domain; verifies presence of organisation number or registered address. Emits `not_found` if unverified.
6. **Snapshot & Change Detection**: Compares against previous snapshots, logging added, modified, or removed claims.
7. **Terminal Envelope Emission**: Generates exactly one JSON object per input with terminal state (`complete`, `not_found`, `not_applicable`, `blocked_robots`, `source_error`).

---

## 6. Repository Structure

```
signalpost-starter-kit/
├── MANIFEST.json                      # Machine-readable reproducibility manifest
├── README.md                          # Main technical documentation (this file)
├── OUTPUT_CONTRACT.md                 # Specification of terminal envelope output schema
├── pyproject.toml                     # Python package specification & semver constraints
├── requirements.txt                   # Pinned production runtime dependencies
├── requirements-dev.txt               # Development & testing dependencies
├── uv.lock                            # Cryptographic lockfile for uv package manager
├── .env.example                       # Production configuration template (no secrets)
│
├── src/norway_company_agent/          # Core OrgTrace Python package
│   ├── identity_engine.py             # Exact identity resolution & candidate scoring
│   ├── website_discovery.py           # Domain discovery, crawl candidates & identity gate
│   ├── profile_extraction.py          # Structured data, Microdata, JSON-LD & contact parsing
│   ├── financial_intelligence.py      # Annual accounts & accounting obligation logic
│   ├── evidence_engine.py             # Immutable Evidence dataclasses & provenance tracking
│   ├── change_intelligence.py         # Semantic normalization & material change detection
│   ├── strategy_harness.py            # Challenger strategy evaluation & promotion harness
│   ├── batch_engine.py                # 1,000+ profile streaming & shared budget tracker
│   ├── batch.py                       # Envelope generation, bulk parsing & validation
│   ├── evaluation.py                  # Evaluation benchmark harness & reporting
│   ├── url_safety.py                  # SSRF prevention, IP validation & URL sanitization
│   ├── resilience.py                  # Exponential backoff, jitter & HTTP error handling
│   ├── licensing.py                   # License tracking & NLOD 2.0 attribution
│   ├── config.py                      # Centralized environment configuration
│   ├── logging_utils.py               # Structured logging & secret redaction
│   └── observability.py               # Telemetry, operation metrics & request counts
│
├── docs/                              # Comprehensive technical documentation
│   ├── architecture.md                # System architecture, components & Mermaid diagram
│   ├── limitations.md                 # Unvarnished disclosure of system boundaries
│   ├── dependencies-and-licenses.md   # Inventory of packages, APIs, models & licenses
│   ├── cost-analysis.md               # Empirical, calculated & estimated cost breakdown
│   ├── final-evaluation.md            # Test suite & 1,000-profile benchmark results
│   ├── competition-control-loop.md    # Stage 0 competition control loop contract
│   └── production-hardening.md        # Stage 11 production hardening guide
│
├── scripts/                           # Operational and execution scripts
│   ├── run_competition.sh             # One-command executable runner (full, smoke, eval, test)
│   ├── run_competition_batch.py       # Batch execution CLI against bulk CSV & APIs
│   ├── generate_manifest.py           # Tool to regenerate MANIFEST.json
│   ├── run_refresh_replay.py          # Deterministic refresh replay demonstration
│   ├── select_entry_batch.py          # Reproducible sampling script from public universe
│   └── score_competition_v3.py        # Competition scoring proxy
│
├── tests/                             # Comprehensive test suite
│   ├── test_poc.py                    # 254 unit and integration tests across Stages 0–11
│   └── fixtures/                      # Test snapshots, HTML stubs & refresh samples
│
├── out/                               # Generated run artifacts (gitignored)
│   ├── envelopes.jsonl                # Terminal company envelopes
│   ├── profiles.jsonl                 # Enriched corporate profiles
│   └── run-report.json                # Machine-readable batch report
│
├── brreg-enheter.csv                  # Brønnøysundregistrene bulk CSV snapshot (~154 MB)
├── entry-companies.jsonl              # 1,000-company competition entry batch
├── smoke-companies.jsonl              # 10-company smoke test batch
└── signalpost-universe.jsonl.gz       # 411,160-company public competition universe
```

---

## 7. Prerequisites

- **Operating System**: Linux, macOS, or Windows (POSIX and Windows paths supported).
- **Python**: `Python >= 3.12` (Audited and tested on Python 3.14.7).
- **Package Manager**: `uv` (recommended) or standard `python3` / `pip`.

---

## 8. Installation

### Quick Setup with `uv` (Recommended):
```bash
# 1. Navigate to workspace
cd signalpost-starter-kit

# 2. Sync virtual environment and dependencies
uv sync
```

### Standard Setup with `pip`:
```bash
# 1. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 2. Install pinned runtime dependencies
pip install -r requirements.txt
```

---

## 9. Environment Configuration

OrgTrace provides a template in [`.env.example`](.env.example). Copy to `.env` if custom configuration is needed:

```bash
cp .env.example .env
```

Key environment variables:
- `ORGTRACE_ENV`: Execution mode (`production`, `staging`, `development`, `test`). Default: `production`.
- `BRAVE_SEARCH_API_KEY`: Optional API key for Brave Search domain discovery. If omitted, discovery operates via registry/sitemap anchors only.
- `BRREG_API_BASE_URL`: Base URL for Brønnøysundregistrene Enhetsregisteret API (default: `https://data.brreg.no/enhetsregisteret/api`).
- `ORGTRACE_LOG_JSON`: Set to `true` for single-line JSON logging. Default: `false`.
- `ORGTRACE_ENFORCE_DNS_CHECK`: Enable strict DNS-level SSRF resolution checks. Default: `false`.

---

## 10. One-Command Execution

OrgTrace provides a single, unified execution script [`scripts/run_competition.sh`](scripts/run_competition.sh) (executable):

### Run Full 1,000-Company Batch (Default):
```bash
./scripts/run_competition.sh
# or explicitly:
./scripts/run_competition.sh full
```
*Outputs: `out/envelopes.jsonl` (1,000 envelopes), `out/profiles.jsonl`, `out/run-report.json`.*

### Run 10-Company Smoke Test:
```bash
./scripts/run_competition.sh smoke
```

### Run Stage 10 Evaluation Benchmark:
```bash
./scripts/run_competition.sh eval
# or directly via Python:
PYTHONPATH=src uv run python -m norway_company_agent.evaluation
```

### Run Full Test Suite (254 Tests):
```bash
./scripts/run_competition.sh test
# or directly via pytest:
uv run --with pytest pytest -q
```

---

## 11. Input Format

OrgTrace accepts organisation numbers in `.jsonl`, `.json`, or plain `.txt` format. Each line in a `.jsonl` input file represents a target company:

```json
{"organisation_number": "985589003", "name": "ARKITEKTFIRMA JON VIKØREN AS"}
{"organisation_number": "935095190", "name": "FJELLGLØD HOLDING AS"}
```
Plain text inputs contain one 9-digit organisation number per line:
```
985589003
935095190
```

---

## 12. Output Format

OrgTrace strictly adheres to the [`OUTPUT_CONTRACT.md`](OUTPUT_CONTRACT.md) specification, emitting exactly one terminal envelope JSON object per input:

```json
{
  "run_id": "competition-final-001",
  "organisation_number": "985589003",
  "state": "complete",
  "started_at": "2026-09-19T20:00:00Z",
  "completed_at": "2026-09-19T20:00:15Z",
  "modules": {
    "registry": {
      "state": "complete",
      "retry_count": 0,
      "final_timestamp": "2026-09-19T20:00:01Z"
    },
    "accounting_obligation": {
      "state": "complete",
      "retry_count": 0,
      "final_timestamp": "2026-09-19T20:00:01Z"
    }
  },
  "profile": {
    "organisation_number": "985589003",
    "name": "ARKITEKTFIRMA JON VIKØREN AS",
    "legal_form": "AS",
    "evidence": {
      "registry": {
        "field": "registry",
        "status": "available",
        "source_type": "official_registry_bulk",
        "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv",
        "retrieved_at": "2026-09-19T20:00:01Z",
        "content_sha256": "5392f7a9b625594fdbd7aa21bbf2badc18201f0ec8956930bf47e3245166a455"
      }
    }
  }
}
```

Allowed availability states: `available`, `not_available`, `blocked`, `not_applicable`, `ambiguous`, `failed`.

---

## 13. Example Usage: Refresh Replay

To verify deterministic change intelligence without network requests, run the bundled snapshot replay:

```bash
./scripts/run_competition.sh replay
```

Open `out/refresh-demo.json` to inspect the detected material changes and evidence IDs between two historical versions of a company profile.

---

## 13.5 Evidence-Grounded Explanations

OrgTrace provides a lightweight, zero-hallucination explanation layer designed for the Signalpost **10-point explanation/usability** component.

- **Evidence First, Explanation Second**: Generates explanations exclusively from retrieved, verified facts and statutory evidence; never invents missing information.
- **4-Tier Source Hierarchy**: Prioritizes statutory registers (BRREG Tier 1) and official websites over secondary or weak aggregators.
- **Structured Rationale**: Explains *what* was found, *why* the conclusion was reached, *which* evidence supports it, and *what* remains uncertain.
- **Deterministic Validation & Fallbacks**: Strict hallucination validator screens evidence IDs, source names, substantive numbers, dates, and entity identifiers. Replaces any ungrounded candidate with a safe deterministic fallback.

See [`docs/explanations.md`](docs/explanations.md) for full architecture and schema examples.

---

## 14. Evaluation Methodology

OrgTrace uses a dual evaluation strategy:
1. **Automated Unit & Integration Suite**: 254 test cases in `tests/test_poc.py` testing identity resolution, SSRF blocking, retry logic, snapshot immutability, and parallel budget contention.
2. **Deterministic Benchmark Harness (`EvaluationHarness`)**: Evaluates 9 canonical corporate scenarios (exact match, ambiguous name, subsidiary, parent holding company, lookalike competitor, weak web presence, missing data, material changes, and external non-target). Measures coverage, precision, recall, validity rate, and false changes.

---

## 15. Dataset and Source Information

- **`brreg-enheter.csv`**: Official bulk export from Brønnøysundregistrene Enhetsregisteret (154 MB, ~1.17M entities). License: NLOD 2.0.
- **`signalpost-universe.jsonl.gz`**: 411,160 Norwegian companies in the competition benchmark universe.
- **`entry-companies.jsonl`**: 1,000 companies sampled reproducibly via `select_entry_batch.py --seed 20260823`.
- **First-Party Corporate Websites**: Extracted directly under public directory / fair use principles with strict robots.txt compliance.

---

## 16. Models Used

1. **Deterministic Pattern Engine**: Rule-based regex and Modulo 11 check digit verification. 100% deterministic, 0 inference cost.
2. **Financial Intelligence Engine**: Rule-based statutory accounting classification under Norwegian Accounting Act (*Regnskapsloven*).
3. **Change Intelligence Engine**: Deterministic semantic diffing and AST value normalization.
4. **`NbAiLab/nb-bert-base` (Optional)**: 110M-parameter transformer from the National Library of Norway for Norwegian sentiment classification. Bypassed in default lightweight mode.

---

## 17. APIs Used

| API | Provider | Purpose | Auth | License |
| :--- | :--- | :--- | :--- | :--- |
| **Enhetsregisteret Open API** | Brønnøysundregistrene | Live registry data | None | NLOD 2.0 |
| **Regnskapsregisteret Open API** | Brønnøysundregistrene | Annual accounts | None | NLOD 2.0 |
| **Brave Search Web API** | Brave Software | Search discovery (fallback) | API Key | Commercial Terms |

---

## 18. Licenses & Attribution

- **OrgTrace Code**: MIT License.
- **Norwegian Government Data**: Norsk lisens for offentlige data (NLOD 2.0).
  - *Attribution*: "Inneholder data under Norsk lisens for offentlige data (NLOD) tilgjengeliggjort av Brønnøysundregistrene."
- See [`docs/dependencies-and-licenses.md`](docs/dependencies-and-licenses.md) for the complete dependency inventory.

---

## 19. Cost Assumptions & Economics

- **Measured Baseline Cost**: **$0.000000 USD** (100% free official endpoints).
- **Official Open APIs & Bulk Data**: Free public utility funded by the Norwegian government.
- **Website Crawling**: $0.00 third-party fees (direct HTTP).
- **Brave Search Fallback (Optional)**: 2,000 queries/month free; $0.005/query thereafter.

---

## 20. Cost per 100 Profiles

- **Measured Cost**: **$0.00 USD**
- **Calculated Paid Cost (with Brave Search fallback)**: **$0.15 USD** (~30 queries @ $0.005)
- **Free-Tier Cost**: **$0.00 USD**

See [`docs/cost-analysis.md`](docs/cost-analysis.md) for details.

---

## 21. Scaling to 1,000+ Profiles

- **Measured 1,000-Profile Batch**: Executed on `entry-companies.jsonl` against `brreg-enheter.csv` in **15.58 seconds** (~64.2 profiles/sec).
- **Memory Footprint**: Generator-based chunked streaming (`iter_company_inputs`) maintains steady memory usage (< 250 MB).
- **Budget Protection**: `SharedBudgetTracker` enforces atomic ceilings across worker threads to prevent runaway resource consumption.

---

## 22. Known Limitations

- **Website Coverage**: ~25–35% of registered entities (e.g., holding firms, shell entities) do not list an official website in Enhetsregisteret.
- **Client-Side Rendering**: Static HTML parser does not execute heavy client-side JavaScript SPAs unless escalated to `scrapy-playwright`.
- **Zero Scraping Policy**: Data from restricted platforms (`proff.no`, `purehelp.no`, `linkedin.com`) is not scraped, strictly adhering to terms of service.
- **API Rate Limits**: Brønnøysundregistrene public APIs cap burst concurrency (worker threads capped at 8).

See [`docs/limitations.md`](docs/limitations.md) for full disclosure.

---

## 23. Reproducibility Instructions

1. Verify environment: `python3 --version` (requires Python >= 3.12).
2. Install dependencies: `pip install -r requirements.txt`.
3. Verify manifest: Inspect [`MANIFEST.json`](MANIFEST.json) for exact input/output hashes and commit SHA.
4. Execute benchmark: `./scripts/run_competition.sh eval`.
5. Execute batch: `./scripts/run_competition.sh full`.

---

## 24. Testing Instructions

```bash
# Run unit and integration tests (254 tests)
PYTHONPATH=src uv run python -m unittest tests.test_poc -v

# Run with pytest
uv run --with pytest pytest -v

# Run evaluation benchmark
PYTHONPATH=src uv run python -m norway_company_agent.evaluation
```

All 254 tests must pass with 0 failures.

---

## 25. Competition Submission Notes

- **Submission Repository**: `namandeeptripathi/OrgTrace`
- **One-Command Execution**: `./scripts/run_competition.sh`
- **Evaluation Command**: `PYTHONPATH=src uv run python -m norway_company_agent.evaluation`
- **Output Manifest**: [`MANIFEST.json`](MANIFEST.json)
- **Verified Batch**: 1,000 completed company profiles in [`out/envelopes.jsonl`](out/envelopes.jsonl)
- **Third-Party Cost per 100 Profiles**: **$0.00 USD** (measured baseline) / **$0.15 USD** (calculated with search discovery fallback)
- **Declared Models & APIs**: Brønnøysundregistrene Enhetsregisteret (NLOD 2.0), Regnskapsregisteret (NLOD 2.0), Brave Search API (Commercial, optional).
