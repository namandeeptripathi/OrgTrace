# OrgTrace — Signalpost Competition Gap Audit

> **Document Version**: 1.0.0  
> **Evaluation Date**: 2026-09-24  
> **Repository**: [`namandeeptripathi/OrgTrace`]()  
> **Status**: Completed Stage 13 Audit (Readiness Assessment for Stage 14+ Implementation)  
> **Auditors**: Antigravity Agentic Pair-Programming System  

---

## Executive Summary

This document presents a comprehensive, evidence-grounded competition readiness audit of **OrgTrace** following the completion of Stages 1–12. OrgTrace was built to solve the challenges of corporate identity confusion, entity drift, and unverified data harvesting in the Norwegian enterprise intelligence domain.

### Key Audit Finding: The Architectural Decoupling Paradox
The repository contains **two distinct functional tiers**:
1. **The Hardened Stage 1–11 Engine Suite** ([`src/norway_company_agent/identity_engine.py`](src/norway_company_agent/identity_engine.py), [`website_discovery.py`](src/norway_company_agent/website_discovery.py), [`profile_extraction.py`](src/norway_company_agent/profile_extraction.py), [`financial_intelligence.py`](src/norway_company_agent/financial_intelligence.py), [`evidence_engine.py`](src/norway_company_agent/evidence_engine.py), [`change_intelligence.py`](src/norway_company_agent/change_intelligence.py), [`strategy_harness.py`](src/norway_company_agent/strategy_harness.py), [`batch_engine.py`](src/norway_company_agent/batch_engine.py)): A mathematically rigorous, type-safe, immutable architecture thoroughly tested across 254 passing unit/integration tests and an evaluation harness benchmark.
2. **The Active CLI Runner Pipeline** ([`scripts/run_competition_batch.py`](scripts/run_competition_batch.py), [`src/norway_company_agent/batch.py`](src/norway_company_agent/batch.py), [`src/norway_company_agent/official.py`](src/norway_company_agent/official.py), [`src/norway_company_agent/identity.py`](src/norway_company_agent/identity.py)): The operational script executed by [`scripts/run_competition.sh`](scripts/run_competition.sh). **This runner is decoupled from the Stage 1–11 engines**, relying on older heuristic modules, and by default executes with `--modules registry,accounting_obligation` only.

Consequently, while OrgTrace's core algorithms are exceptionally sound in isolation, **the competition batch artifacts (`out/envelopes.jsonl`) currently emit zero live financial statements, zero executive board roles, zero subunit locations, and zero verified web claims**, and emit an envelope structure that diverges from [`OUTPUT_CONTRACT.md`](OUTPUT_CONTRACT.md). Furthermore, if all live modules were naively activated for 1,000 companies, the system would issue 5,000–8,000 outbound HTTP requests, causing an immediate failure of the competition's **2,000 outbound-request constraint**.

---

## 1. Inspection of the Current System

### 1.1 Repository Architecture & Assets
The workspace contains:
- **Core Library** (`src/norway_company_agent/`): 37 Python modules encompassing identity resolution, website discovery, profile extraction, financial intelligence, cryptographic provenance, change intelligence, batch execution, resilience, licensing, and URL safety.
- **Operational Scripts** (`scripts/`): 27 operational tools for batch runs, research agent queries, prototype visualization, and experimental connectors (Brave Search, LinkedIn, Fagfolkguiden, YouTube, Google Maps).
- **Test Suite** (`tests/test_poc.py`): 254 unit and integration tests across 27 test classes, completing in ~1.49 seconds with 0 failures.
- **Static Public Datasets**:
  - `brreg-enheter.csv` (154.7 MB, 1,174,956 rows): Complete snapshot of the Norwegian Central Coordinating Register for Legal Entities (*Enhetsregisteret*).
  - `signalpost-universe.jsonl.gz` (12.6 MB, 411,160 entities): Competition reference universe.
  - `entry-companies.jsonl` (318.5 KB, 1,000 entities): Deterministically sampled competition batch (seed `20260823`).
  - `smoke-companies.jsonl` (3.2 KB, 10 entities): Smoke test batch.

### 1.2 Capability Tracing: Input → Implementation → Output → Evidence → Tests

| Capability | Input | Implementation Module | Output Artifact / Field | Evidence Attribution | Test Verification |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Org Number Validation** | Raw string / int / dict | [`identity_engine.py`](src/norway_company_agent/identity_engine.py#L75-L125) | `OrgNumberValidation` (9-digit canonical) | Modulo 11 check digit verification | `test_poc.py::Stage1IdentityEngineTests` (15 tests) |
| **Bulk Registry Resolution** | 9-digit org nr | [`sampling.py`](src/norway_company_agent/sampling.py), [`batch.py`](src/norway_company_agent/batch.py#L58-L128) | Profile row with name, form, municipality, industry | `official_registry_bulk` with CSV SHA-256 hash | `test_poc.py::SamplingTests`, `test_bulk_iterator` |
| **Accounting Obligation** | Legal form & accounts year | [`official.py`](src/norway_company_agent/official.py#L27-L64) | `accounting_obligation` classification & reason | `official_rule_interpretation` citing Regnskapsloven | `test_poc.py::OfficialNormalizationTests` |
| **Live Entity & Accounts** | Org nr + network GET | [`official.py`](src/norway_company_agent/official.py#L181-L202) | Normalized financial metrics, roles, subunits | `official_annual_accounts`, `official_roles` | `test_poc.py::Stage4FinancialIntelligenceTests` |
| **Financial Intelligence (Deep)** | JSON body / PDF bytes | [`financial_intelligence.py`](src/norway_company_agent/financial_intelligence.py#L221-L320) | `FinancialStatement`, `ExtractedField` (None != 0) | Exact period, currency, `sumDriftsinntekter` | `test_poc.py::Stage4FinancialIntelligenceTests` (18 tests) |
| **Website Identity Gate** | Profile + Crawl HTML | [`website_discovery.py`](src/norway_company_agent/website_discovery.py), [`identity.py`](src/norway_company_agent/identity.py#L163-L185) | `website` status (`available` vs `not_found`), social links | SHA-256 content hash, URL, exact match reasons | `test_poc.py::Stage2WebsiteDiscoveryTests`, `WebsiteIdentityTests` |
| **Profile Extraction** | HTML / JSON-LD | [`profile_extraction.py`](src/norway_company_agent/profile_extraction.py) | Description, contacts, leadership, hiring | CSS / JSONPath selector, source URL, confidence | `test_poc.py::Stage3ProfileExtractionTests` (18 tests) |
| **Provenance Tracking** | Claim + source metadata | [`evidence_engine.py`](src/norway_company_agent/evidence_engine.py) | `ProvenanceClaim` with 7-tier authority rank | Cryptographic hash, retrieval timestamp | `test_poc.py::Stage5EvidenceProvenanceTests` (16 tests) |
| **Change Intelligence** | Old & New snapshots | [`change_intelligence.py`](src/norway_company_agent/change_intelligence.py), [`refresh.py`](src/norway_company_agent/refresh.py) | `MaterialChangeRecord` (Added, Removed, Modified) | `old_content_sha256`, `new_content_sha256` | `test_poc.py::Stage7ChangeIntelligenceTests` (14 tests) |
| **Competition Batch** | 1,000-org file | [`scripts/run_competition_batch.py`](scripts/run_competition_batch.py) | `out/envelopes.jsonl`, `out/profiles.jsonl` | Envelope terminal states (`complete`) | `./scripts/run_competition.sh full` (1,000 in 15.58s) |

---

## 2. Audit Against the Signalpost Scoring Model

### A. Useful Information — 35 Points

*Note: In the absence of a competition-published sub-weighting per field, point allocations represent qualitative coverage assessments.*

| Company Attribute / Field | Status | Why / Detailed Implementation Evidence |
| :--- | :---: | :--- |
| **Company Identity** | ✅ Covered | Modulo 11 check digit verification via [`compute_mod11_check_digit`](src/norway_company_agent/identity_engine.py#L33-L48) and [`is_valid_org_mod11`](src/norway_company_agent/identity_engine.py#L50-L58). Canonicalizes prefixes (`NO`, `org.nr.`) and suffixes (`MVA`). |
| **Legal Name** | ✅ Covered | Ingested from canonical BRREG bulk snapshot and live REST endpoints. Normalized in [`normalize_legal_name`](src/norway_company_agent/identity_engine.py#L145-L185) (Unicode NFKC, diacritics `æøå`, whitespace, legal form suffixes). |
| **Organisation Number** | ✅ Covered | 9-digit canonical representation enforced across all ingestion boundaries. Zero duplicate org numbers allowed in batch intake. |
| **Registration Information** | ✅ Covered | Registration status, legal form (`organisasjonsform`), registration dates from BRREG. Evaluated in [`normalize_entity`](src/norway_company_agent/official.py#L156-L171). |
| **Company Status** | ✅ Covered | Explicit boolean tracking of bankruptcy (`konkurs`) and liquidation (`underAvvikling`) from BRREG Enhetsregisteret. |
| **Address** | 🟡 Partially covered | Municipality and municipality number are covered in bulk CSV. Full business and postal street addresses exist in `official.py:normalize_entity` and `underenheter`, but are **omitted from default batch execution** (`--modules registry,accounting_obligation`). |
| **Website** | 🟡 Partially covered | Official website URL extracted from bulk CSV if present (~70% coverage). Bounded Brave Search discovery fallback exists in [`run_brave_discovery.py`](scripts/run_brave_discovery.py), but is **disabled by default in batch runs** unless an API key and explicit module flag are supplied. |
| **Contact Information** | 🟡 Partially covered | Contact phone, email, and social handles are implemented in [`profile_extraction.py`](src/norway_company_agent/profile_extraction.py#L300-L380) and [`official.py`](src/norway_company_agent/official.py#L156-L171), but **not crawled or emitted in default batch outputs**. |
| **Industry / Activity** | ✅ Covered | Authoritative 5-digit NACE code (`naeringskode1`) and Norwegian textual label (`Arkitektvirksomhet med vekt på bygg`) extracted directly from BRREG bulk export. |
| **Products & Services** | ❌ Missing | No structured parser or extraction pipeline exists for company product catalogs, service listings, or pricing models. |
| **Executives / Key People** | 🟡 Partially covered | Implemented in [`official.py:normalize_roles`](src/norway_company_agent/official.py#L123-L143) (CEO / `daglig leder`, Board Chair / `styreleder`, board members; birthdates discarded for GDPR compliance) and [`profile_extraction.py`](src/norway_company_agent/profile_extraction.py#L420-L480). However, **excluded from default batch execution**. |
| **Ownership Structure** | 🟡 Partially covered | Corporate parent/subsidiary relationships supported via [`BRREG_GROUP`](src/norway_company_agent/official.py#L17) (`/konsernstruktur/{org}`). However, the Norwegian Shareholder Register (*Aksjonærregisteret*) requires non-API manual processing, and ultimate beneficial ownership is not accessible via public BRREG APIs. |
| **Company Description** | 🟡 Partially covered | Implemented in [`profile_extraction.py:extract_company_description`](src/norway_company_agent/profile_extraction.py#L220-L280) with prioritized fallbacks (JSON-LD → meta description → `/om-oss` text → NACE industry fallback). **Omitted from default batch outputs**. |
| **Financial Information** | 🟡 Partially covered | Official Regnskapsregisteret JSON parser in [`financial_intelligence.py`](src/norway_company_agent/financial_intelligence.py) extracts Revenue, EBIT, Profit Before Tax, Net Profit, Total Assets, Equity, and Debt, preserving `0` vs `None`. Statutory accounting obligation assessment works in bulk mode. **However, actual numerical figures are absent from default batch output** (only `latest_submitted_accounts` year string is emitted). |
| **Employee Information** | ✅ Covered | Employee count (`antallAnsatte`) extracted from BRREG bulk CSV. Range extraction from text implemented in `profile_extraction.py`. Subunit employee counts supported in `official.py:normalize_locations`. |
| **Locations / Establishments** | 🟡 Partially covered | Subunit extraction (`underenheter`) implemented in [`official.py:normalize_locations`](src/norway_company_agent/official.py#L145-L154). **Omitted from default batch run**. |
| **External Signals (Reviews/News)** | ⚠️ Unreliable / Risky | Standalone experimental scripts exist for Google Places (`normalize_google_maps_results.py`), YouTube (`run_youtube_search_connector.py`), News RSS (`run_google_news_rss_connector.py`), and LinkedIn (`run_linkedin_guest_jobs_connector.py`). However, **they are quarantined, unvalidated against frozen labels, and completely absent from production envelopes**. |

---

## 3. Correct Company + Evidence — 30 Points

Identifying the correct legal entity and proving information attribution is the highest-weighted integrity requirement. Attributing information to the wrong legal entity triggers the critical **WRONG COMPANY** failure condition.

### 3.1 Current Protections (Verified Working)
1. **Modulo 11 Arithmetic Check**: [`identity_engine.py:is_valid_org_mod11`](src/norway_company_agent/identity_engine.py#L50-L58) rejects corrupted, truncated, or synthetic organisation numbers using the official Norwegian weights `(3, 2, 7, 6, 5, 4, 3, 2)`.
2. **Canonical BRREG Ground Truth**: Company identity is grounded in official government registries. Lookup by exact 9-digit organisation number prevents confusion among namesake entities.
3. **Legal Form Disambiguation**: [`match_legal_names`](src/norway_company_agent/identity_engine.py#L220-L310) prevents conflation between different entity types (e.g. `AS` vs `ENK` or `AS` vs `ASA`).
4. **Corporate Group Distinction**: [`classify_group_relationship`](src/norway_company_agent/identity_engine.py#L420-L480) classifies parent companies (`morselskap`), subsidiaries (`datterselskap`), and subunits (`underenheter`) without conflating their legal identities.
5. **Parked Domain Detection**: [`identity.py:assess_website_identity`](src/norway_company_agent/identity.py#L87-L99) detects and rejects domain-broker placeholders (`"domain for sale"`, `"hugedomains"`, `"miss hosting"`).
6. **Cryptographic Provenance**: Every evidence record includes a SHA-256 hash of source content, retrieval timestamp, and exact source URL.

### 3.2 Critical Failure Modes & Remaining Risks (Scenarios that could cause WRONG COMPANY)

> [!CAUTION]
> ### 1. Loose Token Matching in Website Identity Gate (`identity.py:106-111`)
> In [`src/norway_company_agent/identity.py`](src/norway_company_agent/identity.py#L106-L111):
> ```python
> elif len(core) >= 2 and exact_homepage_name:
>     score = 0.95
>     reasons.append("all normalized legal-name tokens appear together in homepage identity evidence")
> elif len(core) == 1 and exact_homepage_name and substantive_homepage:
>     score = 0.95
>     reasons.append("single distinctive legal-name token appears in homepage identity evidence with substantive content")
> ```
> When `score >= 0.9`, the website is classified as `publishable: true`.
> **The Failure Scenario**: If a company is named "Nordic Logistics AS" (tokens: `["nordic", "logistics"]`), any unrelated enterprise containing "Nordic Logistics" on its homepage will receive a 0.95 score and be published as verified, **even if the 9-digit organisation number and registered address are completely absent from the site**.

> [!CAUTION]
> ### 2. Digit Concatenation Vulnerability in PDF Financial Extractor (`financial_intelligence.py:449-450`)
> In [`src/norway_company_agent/financial_intelligence.py`](src/norway_company_agent/financial_intelligence.py#L449-L450):
> ```python
> clean_digits = re.sub(r"\D", "", text)
> if canonical_org not in clean_digits:
>     return None
> ```
> `re.sub(r"\D", "", text)` strips all non-digits from an entire 50-page annual report PDF into a continuous digit stream.
> **The Failure Scenario**: If page 12 has account numbers ending in `985` and table columns on page 13 begin with `589003`, their concatenated digits form `985589003`. The extractor believes the target company's organisation number was present in the document and proceeds to extract and attribute financial tables from an entirely different corporate filing.

> [!CAUTION]
> ### 3. Shared Corporate Domains in Group Holdings
> In Norwegian conglomerates, parent holding companies (`XYZ Holding AS`) often list the website of their primary operating subsidiary (`www.xyz-drift.no`) in Enhetsregisteret. If the website does not explicitly state the holding company's legal name or organisation number, attributing the subsidiary's operational descriptions, contact emails, and employee counts to the holding company is a **Wrong-Company misattribution**.

> [!CAUTION]
> ### 4. Social Handle Token Collisions (`identity.py:141-150`)
> The social handle gate scores handle substrings. Generic handles (e.g., `instagram.com/norge_bygg`) can easily match short corporate names without belonging to the legal entity.

---

## 4. Updates / Freshness — 20 Points

The competition requires evaluating company profiles across time, detecting material updates, and explaining changes while resisting noise.

### 4.1 What Works (Verified Working)
- **Deterministic Refresh Replay**: Verified via [`scripts/run_refresh_replay.py`](scripts/run_refresh_replay.py) and `./scripts/run_competition.sh replay` (precision 1.0, recall 1.0, 100% idempotent).
- **Semantic Normalization**: [`change_intelligence.py:normalize_semantic_value`](src/norway_company_agent/change_intelligence.py#L220-L260) normalizes URLs (stripping query parameters and trailing slashes), collapses whitespace, lowercases case-insensitive strings (`legal_form`, `municipality`), and sorts set-like lists.
- **Noise Rejection**: Timestamp variations (`retrieved_at`), dictionary key ordering differences, and floating-point rounding errors are rejected as cosmetic changes (`is_material_change(...) == False`).
- **Failed-Refresh Preservation**: Upstream fetch failures (HTTP 500, timeouts) **never emit false claim removals**. Prior verified claims are carried forward intact with updated diagnostics.
- **Structured Explanations**: Detected changes are emitted as typed [`MaterialChangeRecord`](src/norway_company_agent/change_intelligence.py#L280-L350) objects with previous value, current value, previous source, current source, and human-readable explanation.

### 4.2 What is Missing / Deficient
1. **No Historical Snapshot Store in Main Batch Execution**: While `MemorySnapshotStore` exists in `change_intelligence.py`, [`scripts/run_competition_batch.py`](scripts/run_competition_batch.py) writes point-in-time envelopes directly to disk without loading a baseline snapshot from prior runs. Consequently, **batch runs cannot emit change diffs between consecutive days**.
2. **Missing `changes` Array in Output Envelopes**: The emitted envelopes in `out/envelopes.jsonl` do not contain a `changes: []` field, violating the output contract specification in [`OUTPUT_CONTRACT.md`](OUTPUT_CONTRACT.md#L33).
3. **No Stale Data Expiry Policy**: Data from months-old bulk CSV runs is not automatically flagged as stale if live endpoints are unreachable.

---

## 5. Explanations — 10 Points

The system must justify its selections, cite evidence, explain why claims were accepted or rejected, and distinguish unverified assertions from proven facts.

### 5.1 What Works (Verified Working)
- **7-Tier Source Authority Hierarchy**: Implemented in [`evidence_engine.py:SourceAuthority`](src/norway_company_agent/evidence_engine.py#L23-L32), ranking `GOVERNMENT_REGISTRY` (100) > `OFFICIAL_FILING_COPY` (90) > `VERIFIED_FIRST_PARTY` (80) > `FIRST_PARTY_STRUCTURED` (75) > `REPUTABLE_SECONDARY` (50) > `SEARCH_DISCOVERY` (30) > `UNVERIFIED_THIRD_PARTY` (10).
- **Explainable Authority Ranking**: [`explain_authority_rank`](src/norway_company_agent/evidence_engine.py#L104-L117) provides human-readable explanations of why an authority level was assigned.
- **Statutory Accounting Rule Reasoning**: [`accounting_obligation_assessment`](src/norway_company_agent/official.py#L27-L64) returns an explicit legal justification based on the Norwegian Accounting Act (*Regnskapsloven* § 1-2).
- **Honest Abstention in Research Agent**: [`research.py:answer_profile`](src/norway_company_agent/research.py#L19-L97) explicitly separates verified source-backed facts from `unsupported_or_uncertain` claims, explaining why sentiment or missing financial years were not returned.

### 5.2 What is Missing / Deficient
1. **Omission of Explanations in Envelopes**: The terminal envelope emitted by `run_competition_batch.py` strips the rich explanation objects generated by `identity_engine.py` and `change_intelligence.py`, emitting only raw values and module states.
2. **Search Candidate Rejection Traceability**: When Brave Search returns 10 candidates, the scoring breakdown explaining why 9 candidates were rejected is discarded from the final profile envelope.

---

## 6. Usability — 5 Points

The system's operator experience, CLI clarity, and batch repeatability.

### 6.1 Usability Assessment

| Usability Criterion | Assessment | Finding / Evidence |
| :--- | :---: | :--- |
| **CLI Usability & One-Command Runner** | Excellent | Unified runner [`scripts/run_competition.sh`](scripts/run_competition.sh) supporting `full`, `smoke`, `eval`, `test`, `replay`, and `manifest` modes. |
| **Input Format Flexibility** | Excellent | Accepts `.jsonl`, `.json`, or plain `.txt` (one 9-digit org nr per line). Validates digits and rejects duplicates cleanly at intake. |
| **Batch Throughput (Bulk)** | Exceptional | 1,000 profiles processed in **15.58 seconds** (~64.2 profiles/sec) in bulk mode. Memory usage stays < 250 MB. |
| **Error Handling & Terminal States** | Excellent | All 1,000 outputs reach valid terminal states (`complete` or `not_found`). Zero unhandled crashes on dissolved entities. |
| **Documentation & Transparency** | Exceptional | Outstanding technical documentation in [`README.md`](README.md), [`docs/architecture.md`](docs/architecture.md), [`docs/limitations.md`](docs/limitations.md), [`MANIFEST.json`](MANIFEST.json). |
| **Ad-Hoc Single Company Lookup** | 🟡 Deficient | No direct CLI command exists to query an arbitrary single company over the network (e.g. `orgtrace lookup 985589003`). `scripts/ask_agent.py` requires pre-existing frozen batch rows. |
| **Contract Schema Alignment** | ❌ Deficient | The emitted envelope schema (`out/envelopes.jsonl`) diverges from the schema documented in [`OUTPUT_CONTRACT.md`](OUTPUT_CONTRACT.md). |

---

## 7. Competition Constraints

### 7.1 45-Minute Evaluation Limit
- **Measured Bulk Batch Execution**: 1,000 companies processed in **15.58 seconds** on standard hardware (0.57% of the 45-minute window).
- **Projected Full Live Enrichment (APIs + Website Crawling)**:
  - If 1,000 companies are enriched live across 8 worker threads with network latency:
    - HTTP requests per company: ~5 calls @ 120ms average = 600ms per company.
    - Web crawling: ~700 companies have websites @ 1.2s average = 840s total.
    - Total estimated wall-clock time: **10 to 16 minutes**.
- **Verdict**: ✅ **FEASIBLE**. The 45-minute limit is easily met under both bulk and bounded live operations.

### 7.2 2,000 Outbound-Request Limit

> [!WARNING]
> ### Critical Outbound Request Budget Risk
> Signalpost enforces a strict ceiling of **2,000 outbound network requests** during the entire evaluation run.

#### Request Consumption Matrix

| Company Batch Size | Mode: Bulk Snapshot Only | Mode: Standard Live Enrichment (BRREG APIs) | Mode: Full Live + Website Crawling | Mode: Full Live + Search Discovery |
| :---: | :---: | :---: | :---: | :---: |
| **1 company** | 0 requests | 4–5 requests | 5–7 requests | 6–9 requests |
| **10 companies** (Smoke) | 0 requests | 40–50 requests | 50–70 requests | 60–90 requests |
| **100 companies** (Dev) | 0 requests | 400–500 requests | 500–700 requests | 600–900 requests |
| **1,000 companies** (Full) | **0 requests** | **4,000–5,000 requests** 🚨 | **5,000–7,000 requests** 🚨 | **6,000–9,000 requests** 🚨 |

*Estimates Breakdown for 1,000 Companies in Full Mode*:
- `registry_live`: 1,000 requests
- `financials` (Regnskapsregisteret): 1,000 requests
- `roles`: 1,000 requests
- `locations` (underenheter): 1,000 requests
- `group` (konsernstruktur): 1,000 requests
- `website` (crawl homepage + contact): ~1,400 requests
- `search_discovery` (Brave Search for ~300 missing sites): ~300 requests
- **Total Potential Requests**: **~6,700 requests (335% of the 2,000 limit!)**

#### Optimization Strategy Required for Stage 14:
To evaluate 1,000 companies within 2,000 requests, the system must achieve an average of **≤ 2.0 outbound requests per company**:
1. **Zero Requests for Registry Baseline**: Rely exclusively on `brreg-enheter.csv` for identity, legal form, municipality, industry, and employee counts (**0 network requests**).
2. **Selective Financial Ingestion**: Only query `data.brreg.no/regnskapsregisteret/regnskap/{org}` for companies with statutory accounting obligations (AS, ASA, or observed filings) (**~750 requests**).
3. **Budget-Capped Website Verification**: Only crawl websites for companies where official domains exist in bulk data, capped at 1 request per company (**~700 requests**).
4. **Selective Search Fallback**: Cap search queries to high-priority targets only (**~150 requests**).
5. **Total Optimized Consumption**: **~1,600 requests** (well under the 2,000 ceiling).

### 7.3 $10 API-Cost Limit

| Component / Service | Pricing Model | Calls for 1,000 Companies | Estimated Cost | Status |
| :--- | :--- | :--- | :--- | :--- |
| **BRREG Open APIs** | Free public government utility (NLOD 2.0) | Up to 5,000 calls | **$0.0000** | Free |
| **First-Party Web Crawling** | Direct HTTP requests | Up to 1,500 calls | **$0.0000** | Free |
| **LLM Inference** | Zero cloud LLMs used in core pipeline | 0 tokens | **$0.0000** | Free |
| **Local NLP Model** (`nb-bert-base`) | Local inference on host CPU/GPU | Local | **$0.0000** | Free |
| **Brave Search Web API** | $0.005 per query (2,000/mo free tier) | ~300 queries | **$0.00 – $1.50** | Paid / Free Tier |
| **Total Estimated Run Cost** | — | — | **$0.00 – $1.50 USD** | ✅ **Passed (< $10.00)** |

*Cost Verdict*: ✅ **SAFE**. Maximum realistic third-party cost is $1.50 USD, remaining far below the $10.00 limit. The atomic [`SharedBudgetTracker`](src/norway_company_agent/batch_engine.py#L186-L250) enforces a hard stop if costs reach $10.00.

---

## 8. Permitted Sources Audit

Signalpost enforces strict rules on data rights, platform terms of service, and anti-scraping policies.

| Source | Used by OrgTrace | Purpose | Permitted? | Repository Evidence | Compliance & Platform Risk |
| :--- | :---: | :--- | :---: | :--- | :--- |
| **Brønnøysundregistrene (Enhetsregisteret bulk CSV)** | Yes | Authoritative legal identity & baseline attributes | **Yes** | [`brreg-enheter.csv`](brreg-enheter.csv), [`MANIFEST.json`](MANIFEST.json) | **Zero risk**. Official open data licensed under NLOD 2.0. Required attribution embedded. |
| **Brønnøysundregistrene (Enhetsregisteret REST API)** | Yes | Live status, addresses, roles, subunits | **Yes** | [`src/norway_company_agent/official.py`](src/norway_company_agent/official.py#L15-L21) | **Low risk**. Rate limit compliance required (cap concurrency at 8 workers). |
| **Regnskapsregisteret (Accounts REST API)** | Yes | Standardized annual accounts (revenue, EBIT, assets) | **Yes** | [`src/norway_company_agent/official.py`](src/norway_company_agent/official.py#L19) | **Low risk**. Official NLOD 2.0 open government endpoint. |
| **Regnskapsregisteret (Filing Copy PDF API)** | Yes | Official PDF annual reports | **Yes** | [`src/norway_company_agent/official.py`](src/norway_company_agent/official.py#L20-L21) | **Medium risk**. Observed rate limit of ~30 starts/min; requires [`_reserve_history_slot`](src/norway_company_agent/official.py#L107-L115) delay. |
| **First-Party Corporate Websites** | Yes | Company descriptions, contact details, hiring | **Yes** | [`src/norway_company_agent/website.py`](src/norway_company_agent/website.py), [`website_discovery.py`](src/norway_company_agent/website_discovery.py) | **Low risk**. Bounded crawling respecting `robots.txt` and SSRF controls. |
| **Brave Search Web API** | Yes (Optional) | Domain discovery for unlisted websites | **Yes** | [`scripts/run_brave_discovery.py`](scripts/run_brave_discovery.py), [`docs/external-connectors.md`](docs/external-connectors.md) | **Low risk**. Official commercial API with transient processing (snippets discarded after crawl). |
| **Commercial Aggregators (`proff.no`, `purehelp.no`, `180.no`)** | **No** (Blocked) | Financials and directory listings | **Prohibited** | [`evidence_engine.py:BLOCKED_AGGREGATOR_DOMAINS`](src/norway_company_agent/evidence_engine.py#L34-L38) | **Zero risk**. Explicitly blocked by hardcoded policy and never queried. |
| **Google Places API** | Script only | Place IDs, review counts, user ratings | **Yes** (with API key) | [`scripts/normalize_google_maps_results.py`](scripts/normalize_google_maps_results.py) | **Low risk** if official API is used; quota and key required. |
| **YouTube Data API** | Script only | Video cadence, views, channel subscriber metrics | **Yes** (with API key) | [`scripts/run_youtube_search_connector.py`](scripts/run_youtube_search_connector.py) | **Low risk** if official API is used; quota required. |
| **Google News RSS** | Script only | Recent news mentions and press headlines | **Questionable** | [`scripts/run_google_news_rss_connector.py`](scripts/run_google_news_rss_connector.py) | **Medium risk**. RSS parsing is a grey area under Google terms; quarantined from production. |
| **Fagfolkguiden** | Script only | Artisan ratings and trade reviews | **Questionable** | [`scripts/run_fagfolkguiden_reviews_connector.py`](scripts/run_fagfolkguiden_reviews_connector.py) | **High risk**. Direct HTML directory scraping; conflicts with competition anti-scraping policy. |
| **LinkedIn (Guest Scraping)** | Script only | Workforce counts and job postings | **Prohibited** | [`scripts/run_linkedin_guest_jobs_connector.py`](scripts/run_linkedin_guest_jobs_connector.py) | **High risk**. Scraping LinkedIn guest endpoints violates LinkedIn Terms of Service. **Properly quarantined in experimental scripts and must remain excluded from production submissions.** |

---

## 9. Failure Conditions Deep-Dive

### 9.1 Wrong-Company Failure Condition

The competition strictly penalizes attributing claims, websites, or financials to the wrong legal entity. Below are the specific technical vulnerabilities identified in OrgTrace:

```
[Target: 985589003 "Arkitekt Jon AS"] ──► Name tokens: ["arkitekt", "jon"]
                                                  │
                                                  ▼
                         Homepage crawl: "Jon er arkitekt hos oss i Bergen Bygg AS"
                                                  │
                         ┌────────────────────────┴────────────────────────┐
                         ▼                                                 ▼
             Old `identity.py:106`                            Hardened `identity_engine.py`
      Finds 2 tokens ("arkitekt", "jon")              Requires exact 9-digit org number match
      Matches exact_homepage_name = True              or multi-signal address/municipality proof
      Score: 0.95 -> PUBLISHABLE!                     Score: 0.20 -> REJECTED!
      🚨 WRONG COMPANY PUBLICATION!                  ✅ SAFE ABSTENTION
```

#### Realistic Implementation Examples:
1. **The Common-Token Trap**: In `identity.py:106`, if the legal name tokens appear anywhere in the homepage identity evidence, the gate assigns `score = 0.95` and sets `publishable = True`. For companies with common or descriptive names (e.g. *Fjellglød Holding AS* vs *Fjellglød Hytter AS*), this causes false domain attribution.
2. **Subsidiary Domain Conflation**: An operating subsidiary owns and registers the domain `vikoren.no`. The parent investment company lists `vikoren.no` in the registry. If the site only identifies the operating company, attributing the domain to the parent company is an entity error.
3. **Social Handle Misattribution**: `assess_social_identity` accepts handles where legal name tokens appear as a substring, risking association with personal or brand fan accounts.

### 9.2 Fabricated Financial-Value Failure Condition

Signalpost treats fabricated, hallucinated, or incorrectly attributed financial numbers as a catastrophic integrity failure.

#### Complete Pipeline Audit:

1. **Pipeline 1: Bulk Snapshot CSV (`brreg-enheter.csv`)**:
   - Fields: Only contains `sisteInnsendteAarsregnskap` (e.g. `"2023"`).
   - Inferred Values: Zero numerical values inferred.
   - Integrity Status: **100% Reliable (No fabrication)**.

2. **Pipeline 2: Regnskapsregisteret JSON REST API (`data.brreg.no/regnskapsregisteret/regnskap/{org}`)**:
   - Fields: `sumDriftsinntekter`, `driftsresultat`, `ordinaertResultatFoerSkattekostnad`, `aarsresultat`, `sumEiendeler`, `sumEgenkapital`, `sumGjeld`.
   - Invariant: Implements [`_make_financial_field`](src/norway_company_agent/financial_intelligence.py#L180-L215), guaranteeing that `0` is preserved as a legitimate number while missing values are marked `None` (`FieldStatus.NOT_FOUND`).
   - Integrity Status: **100% Reliable (Official government data with provenance)**.

3. **Pipeline 3: PDF Annual Report Extractor (`financial_intelligence.py:extract_financials_from_pdf`)**:
   - **Severe Failure Pathways Identified**:
     - *Column-Bleed*: Annual accounts present comparative multi-year tables (e.g., 2023 vs 2022). Simple regex matching extracts whichever number matches the regex first on the page, frequently capturing prior-year figures.
     - *Global Multiplier Bleed*: Line 461 checks `re.search(r"\b(?:tall\s+i\s+tusen|i\s+tusen|tusen\s+kroner|TNOK)\b", text)`. If the word "tusen" appears anywhere in the CEO's annual letter (e.g., *"vi har tusen ansatte"*), all extracted balance sheet numbers are multiplied by 1,000!
     - *Consolidated vs. Standalone Confusion*: Line 517 hardcodes `account_type = FinancialAccountType.SELSKAP.value`, even when reading consolidated group accounts (*Konsernregnskap*).
     - *Digit Concatenation Entity Bypass*: As detailed in Section 3.2, `re.sub(r"\D", "", text)` creates accidental 9-digit matches from arbitrary numbers across page boundaries.

---

## 10. Current Strengths

The audit confirms substantial engineering excellence across multiple components:

1. **Deterministic Identity Grounding**: Enforces Modulo 11 check digit arithmetic and exact 9-digit canonicalization, eliminating random or malformed inputs.
2. **Exhaustive Unit & Integration Test Coverage**: **254 passing tests in 1.49 seconds**, validating edge cases across all 11 stages without flaky network dependencies.
3. **Statutory Accounting Obligation Engine**: Built directly on the statutory criteria of the Norwegian Accounting Act (*Regnskapsloven* § 1-2), distinguishing entities legally obliged to file accounts (AS, ASA) from exempt entities (ENK).
4. **Zero-Fabrication Principle**: Missing or exempt fields are strictly preserved as `None` / `not_applicable`, never hallucinated or populated with synthetic zeros.
5. **Fail-Closed Change Intelligence**: Verified snapshot immutability with zero false removals during network outages or partial fetch failures.
6. **Thread-Safe Budget Protection**: Atomic request, runtime, and cost tracking via [`SharedBudgetTracker`](src/norway_company_agent/batch_engine.py#L186-L250) prevents resource exhaustion during parallel execution.
7. **Production Security Hardening**: Centralized URL safety and SSRF validation ([`url_safety.py`](src/norway_company_agent/url_safety.py)) blocking private IP ranges, loopback addresses, and credential leaks.

---

## 11. Gap Classification

### P0 — Critical (Could directly cause competition disqualification or major scoring failure)
- **`G-P0-1`**: **Architectural Decoupling**: The production batch runner (`scripts/run_competition_batch.py`) does not utilize the Stage 1–11 engines (`identity_engine`, `profile_extraction`, `financial_intelligence`, `evidence_engine`, `batch_engine`).
- **`G-P0-2`**: **Empty Production Envelopes**: Default batch output (`./scripts/run_competition.sh full`) contains zero numerical financial metrics, zero roles, zero locations, and zero verified web descriptions.
- **`G-P0-3`**: **Outbound Request Limit Violation Risk**: Uncapped live enrichment of 1,000 companies triggers 5,000–8,000 HTTP requests, severely breaching the 2,000-request competition ceiling.
- **`G-P0-4`**: **Output Contract Discrepancy**: Emitted envelope schema does not match [`OUTPUT_CONTRACT.md`](OUTPUT_CONTRACT.md) (`claims`, `evidence`, `changes`, `operations`).

### P1 — High (Materially reduces score, precision, or reliability)
- **`G-P1-1`**: **Vulnerabilities in PDF Financial Extraction**: Digit concatenation collisions, global multiplier triggers, and comparative column bleed in `extract_financials_from_pdf`.
- **`G-P1-2`**: **Permissive Website Identity Gate in `identity.py`**: Website marked publishable (0.95) based on 2 common name tokens without requiring org number or municipality match.
- **`G-P1-3`**: **Lack of Multi-Run Snapshot Persistence in Batch Runner**: Batch CLI cannot detect or emit changes across successive daily evaluation runs.
- **`G-P1-4`**: **Prohibited Scraping Scripts in Repository**: Experimental scripts for LinkedIn guest scraping and Fagfolkguiden present compliance risks if accidentally activated.

### P2 — Medium (Useful capabilities missing or unoptimized)
- **`G-P2-1`**: **No Products & Services Extraction**: System lacks extraction logic for commercial product/service offerings.
- **`G-P2-2`**: **Missing Single-Company Interactive CLI**: Operators cannot perform an ad-hoc live lookup for a single company via command-line (e.g. `orgtrace lookup <org>`).
- **`G-P2-3`**: **No SPA / JavaScript Rendering in Default Crawler**: Static HTML parsing misses content on single-page apps without SSR.
- **`G-P2-4`**: **Duplicate Network Requests**: Evaluation harness telemetry flags duplicate URL calls due to lack of an in-memory HTTP cache.

### P3 — Low (Code hygiene and polish)
- **`G-P3-1`**: **Hardcoded File Links in Documentation**: `README.md` contains absolute paths pointing to `/Users/apple/Downloads/...`.
- **`G-P3-2`**: **Dependency Deprecation Warnings**: Deprecation warnings in `mf2py/backcompat.py` (`codecs.open`).

---

## 12. Final Audit Matrix

| Area | Competition Weight | Current Status | Evidence in Repository | Identified Gap | Priority |
| :--- | :---: | :---: | :--- | :--- | :---: |
| **Useful Information** | 35 | 🟡 Partially Covered | Identity, NACE, employees, status covered in bulk CSV. Financials, roles, locations, descriptions exist in code but absent from default batch envelopes. | Default batch outputs only bulk CSV row & accounting rule; missing financials, roles, locations. | **P0** |
| **Correct Company + Evidence** | 30 | ⚠️ Covered but Risky | Modulo 11 check and bulk lookups are rock-solid. Website gate in `identity.py` allows token-only matching. PDF financial parser has digit concatenation vulnerability. | Risk of wrong-company domain attribution and PDF entity bypass. | **P1** |
| **Updates / Freshness** | 20 | 🟡 Partially Covered | Refresh replay works on fixtures with 100% precision. `change_intelligence.py` rejects noise. | Main batch script lacks multi-run snapshot persistence; no `changes` array in envelope. | **P1** |
| **Explanations** | 10 | 🟡 Partially Covered | 7-tier authority hierarchy, statutory accounting reasons, research agent explainability all implemented. | Detailed explanations stripped from emitted batch envelopes. | **P2** |
| **Usability** | 5 | 🟡 Partially Covered | Unified runner `./scripts/run_competition.sh`, fast 15.5s batch throughput, great docs. | Emitted envelopes do not match `OUTPUT_CONTRACT.md`; lacks single-company CLI. | **P0** |
| **Wrong-Company Protection** | Failure Condition | ⚠️ Covered but Risky | High precision on registry; website token overlap gate (`identity.py:106`) is vulnerable. | Common-name companies can publish unrelated websites. | **P1** |
| **Financial-Value Integrity** | Failure Condition | ⚠️ Covered but Risky | Official API parser is flawless (None != 0). PDF regex extraction has column-bleed & multiplier risks. | Potential corrupted or misattributed figures from PDF reports. | **P1** |
| **Permitted Sources** | Constraint | 🟡 Partially Covered | Core uses NLOD 2.0 and public web. Experimental LinkedIn & Fagfolkguiden scripts present in repo. | Prohibited scrapers must remain strictly quarantined from evaluation. | **P1** |
| **45-Minute Limit** | Constraint | ✅ Compliant | 1,000 profiles in 15.58s (bulk); projected live run is 10–16 minutes. | None. Feasible within budget. | — |
| **2,000-Request Limit** | Constraint | 🚨 High Risk | Live batch of 1,000 entities naively consumes 5,000–8,000 HTTP requests. | Severe request limit breach if live modules activated without budget governor. | **P0** |
| **$10 API-Cost Limit** | Constraint | ✅ Compliant | Core is $0.00. Brave Search fallback is $0.00–$1.50 per 1,000 profiles. | None. Far below $10.00 cap. | — |

---

## 13. Recommended Next Stages (Stage 14+ Implementation Plan)

Below is the recommended roadmap for Stage 14+, ordered strictly by technical priority:

### Priority 1: Unify Batch Pipeline with Stage 1–11 Engines (Required — P0)
- **Problem**: `scripts/run_competition_batch.py` bypasses the Stage 1–11 engines, outputting impoverished profiles.
- **Evidence**: `batch_engine.py` and `identity_engine.py` are only imported in `test_poc.py`.
- **Expected Impact**: Connects the complete, hardened feature set to competition batch execution.
- **Complexity**: Medium. Wire `BatchExecutionEngine` and `EvaluationEnvelope` into `scripts/run_competition_batch.py`.
- **Dependencies**: None.

### Priority 2: Request-Budget Governed Live Enrichment (Required — P0)
- **Problem**: Querying all live endpoints for 1,000 companies uses 5,000–8,000 requests, violating the 2,000-request limit.
- **Evidence**: 5 endpoints per company in `official.py:fetch_official_modules`.
- **Expected Impact**: Enriches 1,000 companies with official accounts, roles, and verified websites within ~1,600 requests.
- **Complexity**: Medium. Implement hierarchical budget allocation: rely on bulk CSV for identity, prioritize official accounts (1 req) for accounting-obliged entities, and cap website crawls to 1 hop.
- **Dependencies**: Priority 1.

### Priority 3: Align Output Envelope with OUTPUT_CONTRACT.md (Required — P0)
- **Problem**: `out/envelopes.jsonl` structure does not match `OUTPUT_CONTRACT.md`.
- **Evidence**: `out/envelopes.jsonl` contains `modules` and `profile`; contract requires `claims`, `evidence`, `changes`, `errors`, `operations`.
- **Expected Impact**: Guarantees automated evaluator validation passes without schema rejection.
- **Complexity**: Low. Implement an envelope formatter mapping `ExtractedField` and `ProvenanceClaim` into the contract schema.
- **Dependencies**: Priority 1.

### Priority 4: Harden Website Gate & PDF Financial Parser (Required — P1)
- **Problem**: Risk of wrong-company website publishing and corrupted PDF financial numbers.
- **Evidence**: `identity.py:106` token overlap; `financial_intelligence.py:449` digit stripping and global multiplier regex.
- **Expected Impact**: Eliminates false website matches and guarantees zero fabricated financial figures.
- **Complexity**: Medium. Replace `identity.py` with `identity_engine.py:assess_company_identity` (requiring org number or strict address correlation). Fix PDF digit checks to require boundary-delimited 9-digit tokens.
- **Dependencies**: Priority 1.

### Priority 5: Multi-Run Snapshot Store & Change Emission (Required — P1)
- **Problem**: Main batch runner cannot emit change diffs between consecutive days.
- **Evidence**: `run_competition_batch.py` does not save or load historical `CompanySnapshot` objects.
- **Expected Impact**: Enables OrgTrace to capture the 20 points in Updates / Freshness during multi-day evaluations.
- **Complexity**: Medium. Integrate `MemorySnapshotStore` with filesystem persistence (`out/snapshots/{org}.json`).
- **Dependencies**: Priority 1.

### Priority 6: Interactive Single-Company CLI (Optional — P2)
- **Problem**: No operator CLI exists to inspect an arbitrary live company.
- **Evidence**: `scripts/ask_agent.py` only inspects static input files.
- **Expected Impact**: Greatly improves demonstration usability and inspection during competition review.
- **Complexity**: Low. Create `scripts/lookup_company.py <org_number>`.
- **Dependencies**: Priority 1, Priority 2.
