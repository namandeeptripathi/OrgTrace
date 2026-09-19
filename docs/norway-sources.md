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
