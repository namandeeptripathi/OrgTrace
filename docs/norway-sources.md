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
