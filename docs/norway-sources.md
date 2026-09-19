# Norwegian source map

## Brønnøysundregistrene

| Data | Endpoint | POC use |
|---|---|---|
| Full entity snapshot | `https://data.brreg.no/enhetsregisteret/api/enheter/lastned/csv` | Daily NLOD 2.0 identity universe and frozen sampling |
| Live entity | `https://data.brreg.no/enhetsregisteret/api/enheter/{org}` | Identity, form, status, industry, address, website, employees, latest account flag |
| Public roles | `https://data.brreg.no/enhetsregisteret/api/enheter/{org}/roller` | Company-centric public role holders; dates of birth are discarded |
| Group structure | `https://data.brreg.no/enhetsregisteret/api/konsernstruktur/{org}` | Official corporate relationships when returned |
| Subunits | `https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org}` | Registered establishments, addresses, industries, and reported employees |
| Latest normalized accounts | `https://data.brreg.no/regnskapsregisteret/regnskap/{org}` | Latest normalized annual-account fields when covered |
| Available filing years | `https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/aar` | Historical year discovery, rate limited to roughly 30 requests/minute |
| Annual-account PDF | `https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/{year}` | Official filing copy for a discovered year |

The bulk snapshot and live API are compared by exact organisation number. A 410 response means any
cached copy must be removed. Person data is only used in the company-centric role context; birth dates
are not stored or displayed.

## Stage 1 — Exact Company Identity Engine

The Stage 1 identity engine (`norway_company_agent.identity_engine`) establishes BRREG as the single authoritative source of Norwegian corporate identity:
- **Organisation Numbers**: Strict canonicalization to 9-digit strings. Handles spaces, dots, dashes, "NO" prefixes, "MVA" suffixes, and "org.nr" markers. Validates Modulo 11 check digits using official Norwegian weights `(3, 2, 7, 6, 5, 4, 3, 2)`.
- **Legal Names**: Deterministic matching with normalization for case, whitespace, punctuation, Unicode/diacritics (`æ`, `ø`, `å`), and legal form suffixes (`AS`, `ASA`, `ENK`, `DA`, `ANS`, `NUF`, `SA`, `KS`, etc.). Rejects blind fuzzy matching and flags incompatible legal form conflicts (e.g. `AS` vs `ASA`).
- **Domain & Entity Matching**: Five explicit categories: `exact`, `normalized`, `related_derived` (subdomains, ccTLDs, name-derived domains), `conflicting`, and `unavailable`.
- **Corporate Groups**: Parent companies (`morselskap`), subsidiaries (`datterselskaper`), subunits (`underenheter`), and sister entities are classified via BRREG group and subunit data without ever being conflated as the same legal entity.
- **Ambiguity & Wrong-Company Rejection**: Multiple plausible BRREG matches trigger explicit `ambiguous` verdicts. Conflicting org numbers, incompatible legal forms, or conflicting domains trigger explicit `rejected` verdicts with structured evidence.
- **Identity Evidence**: Produces deterministic `IdentityVerdict` objects containing structured evidence items, explicit reasons, confidence levels (`high`, `medium`, `low`, `none`), and boolean diagnostic flags.

## Stage 2 — Deterministic Website Discovery

The Stage 2 discovery pipeline (`norway_company_agent.website_discovery`) finds the official website for a legally identified company without guessing:
- **Registry Website Anchor**: Uses the Stage 1 BRREG entity record as the primary anchor. Normalizes and validates URLs against SSRF policies.
- **Sitemap Discovery**: Safely discovers and parses `robots.txt` and `sitemap.xml` / sitemap indexes. Filters for high-signal paths (`about`, `om-oss`, `contact`, `kontakt`, `legal`) while excluding media and binary assets.
- **Homepage Discovery**: Resolves candidate domains to their homepages with scheme, host, path, port, and trailing slash normalization. Follows redirects safely with per-hop SSRF validation.
- **Search Candidate Discovery**: Engaged only when registry/sitemap evidence is missing or insufficient. Employs deterministic query construction (`"{name}" {org} {municipality}`) with bounded results and blocked-host filtering (`proff.no`, `purehelp.no`, social platforms, etc.).
- **Candidate Scoring**: Explainable, deterministic scoring model combining exact org number presence (+0.75), distinctive legal name tokens in title (+0.45) or snippet (+0.25), hostname alignment (+0.30), municipality match (+0.10), and provenance weighting.
- **Bounded Candidate Crawling**: Crawls strictly bounded pages (homepage + up to 2–3 priority pages). Deduplicates URLs and enforces page/depth caps.
- **Exact-Entity Verification**: Evaluates strong identifiers (exact 9-digit org number on page/footer, exact legal name in title/imprint), medium identifiers (all name tokens in homepage + municipality match), and weak identifiers. Rejects parked domains, placeholder pages, and conflicting org numbers.
- **Safe Abstention**: Returns `ABSTAIN` whenever evidence is insufficient, conflicting, or budget is exhausted. Never forces a candidate merely for having the highest score.
- **SSRF & Security Controls**: Every outbound request is protected by `assert_public_url`, blocking loopback, link-local, private/internal IP ranges, and unsafe schemes. Respects `robots.txt` and fails closed on unsafe resolution.
- **Request-Budget Accounting**: Explicitly tracks total, search, robots, sitemap, page, redirect, and failed requests against configured caps (`RequestBudget`).

## Stage 3 — Company Profile Extraction

The Stage 3 profile extraction engine (`norway_company_agent.profile_extraction`) extracts evidence-attributed company profile fields from verified company sources without guessing or fabrication:
- **Company Description**: Extracts official company descriptions with prioritized provenance: first-party JSON-LD (`Organization.description`), homepage meta/OpenGraph description, first-party `/om-oss` / `/about` text, and official BRREG activity/industry label fallback. Truncates cleanly and never duplicates boilerplate.
- **Industry Classification**: Extracts authoritative NACE / Næringskode (`code`, `label`, system `NACE / Næringskode`) directly from BRREG as primary ground truth, supplemented by `schema.org` `industry` / `knowsAbout` metadata when available. Rejects weak or speculative industry guessing.
- **Contact Details**: Normalizes postal addresses, 4-digit Norwegian postal codes (`postnummer`), cities (`poststed`/`kommune`), international and domestic phone numbers (`+47` formatting), and official company emails. Corroborates between BRREG business/postal addresses and first-party website contact pages.
- **Locations & Subunits**: Identifies distinct company offices, branches, and establishments via official BRREG subunits (`underenheter`) and `schema.org` `LocalBusiness` entities. Deduplicates by normalized name, address line, and postal code; strictly rejects customer or client site confusion.
- **Leadership & Governance**: Extracts key executives and board members (`daglig leder` / CEO, `styreleder` / Chair, `styremedlemmer`, `cfo`, `cto`, `gründer` / founder) from official BRREG public roles (`roller`) and structured `schema.org` person markup. Filters out inactive roles and arbitrary non-executive employees.
- **Employees**: Extracts exact employee counts directly from BRREG or explicit structured data (`numberOfEmployees`). Accurately captures explicit ranges (e.g. `11-50 ansatte`) or minimums (`>100 ansatte`) from first-party text without synthetic estimation.
- **Careers & Hiring**: Detects dedicated careers paths (`/karriere`, `/careers`, `/stillinger`). Distinguishes active hiring from explicit non-hiring notices (`ingen ledige stillinger`) without assuming hiring from page presence alone.
- **News & Press Activity**: Extracts recent first-party news items and press releases from `/nyheter`, `/aktuelt`, `/pressemeldinger`, extracting article titles, URLs, and publication dates.
- **Structured Data Integration**: Parses JSON-LD, Microdata, and OpenGraph with fallback manual parsing, indexing `Organization`, `Corporation`, `LocalBusiness`, `PostalAddress`, and `Person` records.
- **Evidence Spans & Attribution**: Every field is wrapped in `ExtractedField[T]` with complete provenance: `field_name`, `value`, `status` (`found`, `not_found`, `unavailable`, `extraction_failed`), `source_url`, `source_type`, `evidence_span`, `confidence`, and `note`.
- **Honest Abstention & Zero Fabrication**: Missing fields are never hallucinated or populated with placeholder values. Uncrawled or unprovided sources explicitly yield `unavailable`, while inspected sources lacking a given field yield `not_found`.

## Stage 4 — Financial Intelligence

The Stage 4 financial intelligence engine (`norway_company_agent.financial_intelligence`) extracts, normalizes, and verifies official financial figures, accounting obligations, and financial filings without guessing:
- **Official Accounts (Regnskapsregisteret)**: Ingests official annual accounts from `BRREG_ACCOUNTS` (`https://data.brreg.no/regnskapsregisteret/regnskap/{org}`). Normalizes core financial metrics:
  - **Revenue**: `driftsinntekter` / `sumDriftsinntekter`
  - **Operating Profit/Loss**: `driftsresultat` (EBIT)
  - **Profit Before Tax**: `ordinaertResultatFoerSkattekostnad`
  - **Net Annual Profit/Loss**: `aarsresultat`
  - **Total Assets**: `sumEiendeler`
  - **Total Equity**: `sumEgenkapital`
  - **Total Debt/Liabilities**: `sumGjeld`
- **Key Invariant: Never Treat Missing as Zero**: In accounting, `0` is a valid numerical result (e.g. a company reporting 0 NOK revenue or 0 NOK operating profit). Unreported or missing fields are strictly preserved as `value=None` with `status=FieldStatus.NOT_FOUND` or `UNAVAILABLE`.
- **Reporting Periods**: Parses exact start (`fraDato`) and end (`tilDato`) dates, fiscal year, and duration in months (handling standard 12-month fiscal years and shortened/extended stub periods).
- **Account Types**: Distinguishes standalone legal entity accounts (`SELSKAP`) from consolidated group accounts (`KONSERN`). Standalone `SELSKAP` accounts are prioritized as the primary anchor for exact entity matching.
- **Accounting Obligation Assessment**: Evaluates statutory obligations (`ALWAYS_ACCOUNTING_OBLIGED_FORMS` such as `AS`, `ASA` vs `THRESHOLD_OR_ACTIVITY_FORMS` such as `ENK`, `ANS`, `DA`), distinguishing companies that have an unfulfilled filing obligation from those legally exempt.
- **Financial PDF Detection & Extraction**: Discovers official filing copies from `BRREG_ACCOUNT_PDF` (`https://data.brreg.no/regnskapsregisteret/regnskap/aarsregnskap/kopi/{org}/{year}`) and first-party annual report PDFs from company website IR pages. Extracts financial line items from PDF text using exact-entity verification (validating the 9-digit org number in the document to prevent parent/subsidiary conflation).
## Stage 5 — Evidence & Provenance Engine

The Stage 5 evidence & provenance engine (`norway_company_agent.evidence_engine`) provides end-to-end traceability for every claim in OrgTrace, ensuring zero fabricated provenance and strict fail-closed validation:
- **Claim-Level Evidence**: Every extracted fact is represented as an independently verifiable `ProvenanceClaim[T]` with a deterministic `claim_id`, `field_name`, `value`, `source_url`, `discovered_url`, `source_type`, `source_authority`, `retrieved_at`, `effective_date`, `reporting_date`, `reporting_period`, `content_sha256`, `extraction_method`, `selector`, `evidence_span`, and `confidence`.
- **7-Tier Source Authority Hierarchy**:
  1. `GOVERNMENT_REGISTRY` (100): Official BRREG Enhetsregisteret and Regnskapsregisteret endpoints (primary statutory ground truth).
  2. `OFFICIAL_FILING_COPY` (90): Certified Brønnøysund annual report PDF filings.
  3. `VERIFIED_FIRST_PARTY` (80): Verified company website content (`/om-oss`, `/investor`, `/karriere`).
  4. `FIRST_PARTY_STRUCTURED` (75): First-party schema.org / JSON-LD markup on verified company site.
  5. `REPUTABLE_SECONDARY` (50): Verified news publishers and official partner registers.
  6. `SEARCH_DISCOVERY` (30): Search candidate discovery; strictly candidate-only, never published as ground truth.
  7. `UNVERIFIED_THIRD_PARTY` (10): Aggregators (Proff, Purehelp), directories, or parked pages; quarantined or rejected.
- **Evidence Selectors**: Structured locators identifying the precise location within a source:
  - `CSS` / `XPATH`: HTML element queries
  - `JSON_PATH`: JSON body queries (e.g. `$.resultatregnskapResultat.aarsresultat`)
  - `TABLE_CELL`: Structured table coordinate locator (`table_row`, `table_col`)
  - `PDF_PAGE`: PDF document page numbers
  - `TEXT_SPAN` / `LINE_SPAN`: Exact character offsets and line numbers
- **Cryptographic Snapshot Hashing**: SHA-256 fingerprinting of source bytes or text (`compute_content_hash`, `verify_snapshot_match`) to detect changes and verify snapshot integrity.
- **Temporal Provenance**: Explicit distinction between retrieval timestamp (`retrieved_at`), the date as-of when a fact was valid (`effective_date`), and the fiscal/reporting period covered (`reporting_period` / `reporting_date`).
- **Wrong-Source Rejection & Fail-Closed Validation**:
  - Rejects sources containing conflicting 9-digit organisation numbers or different legal entity names.
  - Rejects parent company or group accounts conflating subsidiary facts without explicit attribution.
  - Rejects third-party aggregators (`proff.no`, `purehelp.no`, `ratsit.no`, etc.) and search snippets.
  - Rejects claims where the evidence span is not present in the source content.
  - Rejects unsafe or private network URLs via SSRF validation (`assert_public_url`).

## Stage 6 — External Research & Enrichment

The Stage 6 external research and enrichment engine (`norway_company_agent.external_research`) provides lawful, policy-governed candidate generation and public footprint enrichment:
- **Search-Based Candidate Generation**: Generates candidates for official websites, leadership/founders, company profiles, external footprint, and permitted video/social references. Normalizes schemes, hostnames, ports, paths, and strips tracking parameters (`utm_*`, `gclid`, `fbclid`). Deduplicates candidates deterministically while preserving query, rank, engine, and provenance metadata. Search snippets are strictly flagged `is_candidate_only=True` and are never treated as verified facts alone.
- **Centralized Source Policy Enforcement**: Evaluates candidates centrally via `evaluate_source_policy` before downstream consumption. Implements explicit allowlists:
  - *Permitted*: Official registries (`brreg.no`, `data.brreg.no`, `lovdata.no`, `ssb.no`), verified first-party company domains, and reputable news publications (`e24.no`, `dn.no`, `finansavisen.no`, `nrk.no`, etc.).
  - *Requires Verification*: Permitted video platforms (`youtube.com`, `youtu.be`) for declared or verified channels.
  - *Rejected / Restricted*: Prohibits scraping or direct ingestion from restricted platforms (`linkedin.com`, `facebook.com`, `instagram.com`, `tiktok.com`, `glassdoor.com`, `indeed.com`, and aggregators like `proff.no`, `purehelp.no`, `180.no`).
  - *SSRF Safety*: Rejects local, loopback, private IP ranges, and unsafe schemes.
- **Identity-Safe Leadership Discovery**: Discovers founders, executives, and directors (`daglig leder`, `styreleder`, `styremedlem`, `grunnlegger`) from authoritative sources (BRREG roller and first-party company pages). Fails closed against name collisions across different entities by requiring matching organisation numbers or legal company names in the source evidence.
- **Social & Video Discovery**: Ingests social and video references exclusively through first-party declared links (e.g. YouTube channels or social handles found on verified company websites). Strictly enforces zero unauthorized scraping of restricted social platforms.
- **Normalized External Footprint**: Represents public digital presence via `ExternalFootprintProfile` and `ExternalFootprintItem`, categorizing footprint into official website, company profile, leadership profile, news publication, video reference, social reference, and public register. Rejections are routed to an inspectable audit log.

## Stage 7 — Refresh & Change Intelligence

The Stage 7 change detection and refresh engine (`norway_company_agent.change_intelligence`) tracks company evolution over time with fail-closed preservation:
- **Stable Claim Keys**: Deterministic claim keys (`generate_stable_claim_key`) formatted as `org:{org}|field:{field}` or `org:{org}|field:{field}|entity:{qualifier}`. Keys are purely semantic: independent of crawl timestamps, random UUIDs, ordering, or volatile fetch IDs. Logically identical claims across different runs generate the exact same key.
- **Immutable Snapshots**: Successful refreshes produce an immutable, versioned `CompanySnapshot`. Historical snapshots are frozen upon creation and cannot be mutated by later runs.
- **Semantic Comparison & Material Change Detection**: Detects `ADDED`, `REMOVED`, `MODIFIED`, and `UNCHANGED` claims. Evaluates materiality purely on normalized semantic values (`is_material_change`), strictly preventing false changes caused by:
  - Timestamp differences (`retrieved_at`, `effective_at`)
  - Dictionary key ordering differences
  - List ordering differences for set-like items
  - Whitespace differences (collapsed multi-spaces)
  - URL normalization variations (scheme, default ports, trailing slashes, tracking parameters)
  - Case differences for case-insensitive fields (`legal_form`, `municipality`, `email`, `domain`)
  - Floating point rounding noise
- **Failed Refresh Preservation (Critical)**:
  - When a refresh fails (network error, HTTP 500, timeout, or invalid payload), the previous known-good snapshot is **preserved intact**.
  - Missing data caused by a failed fetch is never interpreted as deletion: **zero false removals**.
  - In partial failures (e.g., registry succeeded but website timed out), claims from failed sources are carried forward from the previous snapshot, while claims from succeeded sources are updated.
- **Idempotent Reruns**: Rerunning the refresh pipeline with identical input state produces identical snapshots and zero duplicate changes.
- **Versioned Snapshot Store**: In-memory `MemorySnapshotStore` maintains chronological snapshot history per organisation number.

## Stage 8 — Learning & Strategy Harness

The Stage 8 strategy harness (`norway_company_agent.strategy_harness`) provides systematic strategy lifecycle management, reproducible evaluations, and precision-first promotion:
- **Strategy Registry (`StrategyRegistry`)**: Central registry managing `StrategyDefinition` records with stable strategy IDs, versions, configurations, and lifecycle statuses (`CHALLENGER`, `CANDIDATE`, `PROMOTED`, `FROZEN`, `RETIRED`).
- **Frozen Production Strategy**: Guarantees exactly one active frozen production strategy for a given evaluation configuration. Frozen strategies cannot be silently replaced and can only be updated through explicit, audited promotion.
- **Strategy Attempts (`StrategyAttempt`)**: Every strategy execution records input/output fingerprints, terminal state, success status, request count, runtime (ms), and cost for reproducible offline evaluation.
- **Success & Failure Tracking (`evaluate_strategy_attempts`)**: Aggregates attempts into exact metrics: `precision` (successful / total attempts), `coverage` (successful / eligible profiles), `error_rate`, request usage, runtime, and cost.
- **Precision-First Promotion Engine (`evaluate_promotion`)**:
  - *Precision Primary Constraint*: A challenger strategy cannot be promoted if its precision drops below baseline or below the configured minimum (`min_precision`), regardless of any coverage gain.
  - *Coverage Improvement*: Evaluated as a secondary gate after precision preservation is verified.
  - *Resource Bounds*: Rejects challengers whose request count, runtime, or cost ratios exceed configured ceilings (`max_request_increase_ratio`, `max_runtime_increase_ratio`, `max_cost_increase_ratio`).
  - *Explainability*: Produces machine-readable `PromotionDecision` detailing individual gate checks and metric deltas.

## Stage 9 — Competition Batch Engine

The Stage 9 batch engine (`norway_company_agent.batch_engine`) orchestrates high-throughput, bounded competition evaluations over the single-company pipeline:
- **1,000+ Profile Streaming Support**: Stream inputs via `iter_company_inputs` in configurable chunks, avoiding high memory overhead and enabling large-scale evaluation datasets.
- **100-Company Evaluation Envelope (`EvaluationEnvelope`)**: Explicitly bounds the evaluation scope (selected organisations, maximum evaluation count, request budget, runtime budget, cost budget, strategy ID/version, configuration fingerprint). The engine never evaluates more than the configured envelope ceiling.
- **Exact Terminal States (`BatchTerminalState`)**: Every evaluation concludes with an explicit, mutually exclusive terminal state (`complete`, `source_error`, `request_budget_exceeded`, `runtime_budget_exceeded`, `cost_budget_exceeded`, `invalid_input`, `not_found`, `not_applicable`, `blocked_policy`, `blocked_robots`, `cancelled`). Zero silent drops.
- **Parallelism & Thread-Safe Shared Budgets (`SharedBudgetTracker`)**: Bounded multi-threading via `ThreadPoolExecutor` with atomic, lock-protected request, runtime, and cost accounting. Prevents race conditions from collectively exceeding budgets under parallel load.
- **Resumable Result Cache (`ResultCache`)**: Deterministic cache keys (`compute_cache_key`) factoring organisation number, strategy ID, strategy version, config fingerprint, and schema version. Reuses valid prior results while strictly rejecting stale or mismatched cache entries.
- **Deterministic Output Ordering**: Results are deterministically ordered according to the evaluation envelope's initial sequence regardless of thread completion order. Timestamps and random IDs are kept in metadata and excluded from output fingerprints (`compute_output_fingerprint`).
- **Run Manifest & Validation (`RunManifest`, `validate_manifest`)**: Emits a comprehensive run manifest verifying strategy match, count match, unique organisation membership, valid terminal states, budget consistency, and deterministic output fingerprints.
## Stage 10 — Evaluation & Optimization

The Stage 10 evaluation and optimization layer (`norway_company_agent.evaluation`, `norway_company_agent.evaluation_dataset`) provides reproducible, machine-readable benchmarking across the enrichment pipeline:
- **Deterministic 9-Category Evaluation Dataset (`build_deterministic_evaluation_dataset`)**:
  1. *Exact Norwegian Companies*: Active AS with official website, annual accounts, and public roles.
  2. *Ambiguous Company Names*: Generic names matching multiple entities; validates safe abstention without unique org numbers.
  3. *Subsidiary Companies*: Operating entities with distinct org numbers; prevents conflation with parent holding accounts.
  4. *Parent Companies*: Holding entities with consolidated accounts and multiple subsidiary links.
  5. *Similarly Named Companies*: Companies with near-identical names; verifies rejection of false attribution.
  6. *Weak Web Presence*: Companies lacking websites or using parked domains; tests honest abstention without hallucination.
  7. *Missing Information*: Entities exempt from statutory accounts (e.g. ENK); ensures missing data is preserved as `None` (never zero).
  8. *Changed Information*: Entities with modified corporate names or legal forms; validates refresh and change detection.
  9. *External Non-Target Companies*: Foreign entities and third-party directory listings; verifies rejection of out-of-scope entities.
- **Coverage Evaluation (`evaluate_coverage`)**:
  - Measures total cases evaluated, usable results, and usable result rate.
  - Provides field-level coverage across `organisation_number`, `name`, `website`, `financials`, and `leadership`.
  - Strictly distinguishes:
    - *Missing data*: Permitted absence in ground truth (e.g. legally exempt sole proprietorship).
    - *Failed retrieval*: Network or fetch failure where data was expected.
    - *Incorrect result*: Extracted data conflicting with ground truth.
- **Exact-Company Precision (`evaluate_exact_precision`)**:
  - Measures whether the selected entity is the intended company.
  - Covers legal name matches, aliases, subsidiaries, similarly named entities, and conflicting identity signals.
  - Computes precision, recall, and F1 score while tracking true negatives on ambiguous/rejected queries.
- **External Precision (`evaluate_external_precision`)**:
  - Validates that discovered external URLs, domains, and sources belong strictly to the target company.
  - Tracks true external matches against false positives (e.g., unrelated domains or foreign entities).
- **Bounded Recall (`evaluate_recall`)**:
  - Evaluates discovery of all expected verifiable fields and leadership entities.
  - *Explicit Evaluation Boundary*: Recall is bounded to the statutory Norwegian registry (Brønnøysundregistrene) and official company domains discovered via deterministic domain matching. Ground truth is never fabricated.
- **Evidence Validity (`evaluate_evidence_validity`)**:
  - Validates all citations and provenance claims:
    - URL syntax (valid HTTP/HTTPS scheme and domain format).
    - Source type classification (`registry`, `financials`, `roles`, `website`, `external_research`, `filings`).
    - Provenance completeness (valid `retrieved_at` timestamp and cryptographic `content_sha256` hash).
    - Computes `validity_rate` and records invalid items with specific diagnostic reasons.
- **Refresh Correctness (`evaluate_refresh_correctness`)**:
  - Deterministically evaluates refresh transitions across `UNCHANGED`, `MODIFIED`, `ADDED`, `REMOVED`, and `FAILED_REFRESH`.
  - Verifies failed-refresh preservation: fetch failures never emit false removals.
  - Verifies that formatting, whitespace, dictionary key ordering, and timestamp differences are rejected as noise.
- **False-Change Rate (`calculate_false_change_rate`)**:
  - Employs semantic normalization (`is_material_change`, `normalize_semantic_value`) to isolate genuine material changes from noise.
  - Reports total detected changes, true material changes, false changes, and `false_change_rate`.
- **Runtime Instrumentation (`RuntimeStats`, `EvaluationInstrumentation`)**:
  - Uses `time.monotonic()` timing so instrumentation never alters business logic.
  - Tracks per-stage runtime, per-engine runtime, average latency, P50 latency, P95 latency, and slowest operations.
- **Request Telemetry (`RequestStats`)**:
  - Instruments network requests: total requests, requests per case, requests per engine, failed requests, retries, and duplicate requests.
  - Detects duplicate URL calls for caching optimization.
- **Provider-Aware Cost Model (`CostModelConfig`, `CostStats`)**:
  - Configurable pricing for HTTP requests, prompt tokens, and completion tokens.
  - Never invents provider pricing; reports unconfigured usage as explicit unknown cost items.
- **Automated Bottleneck Analysis (`analyze_bottlenecks`)**:
  - Automatically identifies runtime bottlenecks (engines consuming ≥ 40% time or P95 ≥ 1.0s).
  - Flags high-request engines (≥ 50% request volume) and duplicate network requests.
  - Surfaces high failure rates and cost drivers with actionable optimization recommendations based on measured data.
- **Evaluation Reports (`EvaluationReport`)**:
  - Machine-readable dictionary output (`to_dict()`).
  - Human-readable GitHub-flavored markdown output (`to_markdown()`) with executive summary tables, telemetry metrics, and per-case breakdowns.

## Stage 11 — Production Hardening

The Stage 11 production hardening layer establishes reproducible, safe, and observable production execution:
- **Reproducible Setup & Pinned Dependencies**:
  - Supported on `Python >= 3.12` (audited on Python 3.14.7).
  - Pinned runtime dependencies in `requirements.txt` and `requirements-dev.txt` mirroring `pyproject.toml` and `uv.lock`.
  - Detailed clean installation and deployment guide in `docs/production-hardening.md`.
- **Secret Handling & Configuration Hardening (`norway_company_agent.config`)**:
  - Centralized `AppConfig` loading from environment variables or `.env`.
  - Complete `.env.example` configuration template.
  - Secret redaction via `redact_secret_value` and `redact_secrets_from_text`.
  - Zero raw credentials or fake keys committed to version control.
  - Strict validation preventing invalid settings (negative timeouts, negative retry caps, invalid log levels).
- **URL Safety & SSRF Protection (`norway_company_agent.url_safety`)**:
  - Centralized `validate_public_url` and `assert_public_url`.
  - Rejects dangerous schemes (`file://`, `javascript:`, `data:`, `vbscript:`, `ftp:`).
  - Rejects embedded credentials in URLs (`http://user:pass@host`).
  - Rejects localhost, loopback, link-local, multicast, and private IP ranges (`127.0.0.1`, `10.0.0.0/8`, `192.168.0.0/16`, `172.16.0.0/12`, `169.254.0.0/16`).
  - Enforces maximum URL length limit (4,096 chars).
  - `sanitize_url_for_logging` redacts credentials and sensitive query parameters.
- **Source Licensing & Attribution (`norway_company_agent.licensing`)**:
  - Explicit licensing catalog (`get_source_license_info`):
    - Brønnøysundregistrene: `NLOD-2.0` (Norwegian Licence for Open Government Data) with required attribution.
    - Lovdata: Public sector legal information.
    - SSB: `NLOD-2.0` open data.
    - Brave Search: Commercial API terms of service.
    - First-party websites: Corporate copyright with fair-use factual extraction.
    - Proff/Purehelp: Proprietary restricted databases (automated scraping blocked by policy).
    - Unverified sources: Honestly represented as `unknown_unverified` without fabricated open licenses.
- **Network Resilience & Failure Recovery (`norway_company_agent.resilience`)**:
  - Bounded exponential backoff with jitter (`execute_with_retry`, `RetryPolicy`).
  - Distinguishes retryable errors (`429`, `500`, `502`, `503`, `504`) from non-retryable errors (`400`, `401`, `403`, `404`, `410`, `422`).
  - Parses and respects `Retry-After` headers.
  - Capped retries guarantee zero infinite retry loops.
  - Explicit `PartialFailureResult` separates succeeded from failed components.
- **Structured Logging & Secret Redaction (`norway_company_agent.logging_utils`)**:
  - Standard Python `logging` with contextual log attributes (`engine`, `operation`, `case_id`, `duration_ms`, `status`).
  - `SecretRedactionFilter` automatically masks sensitive values (`secr****1234`) and auth headers.
  - Configurable log levels (`ORGTRACE_LOG_LEVEL`) and optional structured JSON output.
- **Lightweight Observability (`norway_company_agent.observability`)**:
  - `ProductionMetricsCollector` tracks operations, latencies, success rates, request counts, and refresh outcomes in memory.
  - `get_metrics_snapshot()` API provides health check and telemetry snapshots without heavy external dependencies.
- **Failure-Safe Data Handling**:
  - Verifies failed-refresh preservation: fetch failures never delete existing snapshot claims.
  - Snapshot immutability enforced across all models.

## Coverage limits

- Public annual accounts do not exist for every registered entity. AS and ASA generally file; many sole
  proprietorships do not. An endpoint 404 is evidence of no returned record, not evidence of zero.
- The normalized account endpoint returned source errors for a small bank/insurer slice in the POC.
  Those cases remain explicit source errors and can be routed to official PDFs or regulated-sector data.
- The annual shareholder register is available from the Norwegian Tax Administration by request and is
  not a same-day dependency. It may take several business days and requires GDPR-aware handling.
- The beneficial-owner register is not a general public enrichment source for this POC.
- Company websites are a company-reported layer, not official proof. Search/news/social sources require a
  lawful, declared connector and their own evidence classification.
