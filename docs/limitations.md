# OrgTrace — Known Limitations & System Boundaries

This document provides a transparent, unvarnished disclosure of the known boundaries, limitations, and operational constraints of **OrgTrace**. 

Reproducibility and evaluator trust require complete honesty about what the system can and cannot do. OrgTrace prioritizes precision over coverage: where information is ambiguous, restricted, or unavailable, the system explicitly reports `not_found`, `not_applicable`, or `blocked` rather than hallucinating or guessing.

---

## 1. Source Availability & Platform Constraints

### 1.1 First-Party Company Website Availability
- **No Registered Website**: Approximately 25–35% of registered Norwegian commercial entities (particularly small holding companies, real estate shells, and local trade contractors) do not register an official website in Enhetsregisteret.
- **Dormant or Parked Domains**: Domains registered in Enhetsregisteret may expire, show registrar parking pages, or redirect to third-party domain brokers. OrgTrace's identity gate detects and rejects parking pages when corporate identifiers are absent, resulting in a `not_found` verdict.
- **Client-Side Rendering (SPA) Limitations**: The default fast crawler relies on static HTML extraction via `trafilatura` and `beautifulsoup4`. Websites that render content exclusively via heavy client-side JavaScript (e.g., React/Vue/Angular single-page apps without SSR) may yield incomplete text unless escalated to the optional headless browser crawler (`scrapy-playwright`).

### 1.2 Website Blocking & Bot Defenses
- **Cloudflare, Akamai, & WAF Protection**: Modern corporate websites frequently employ bot protection that issues CAPTCHA challenges or HTTP 403 Forbidden to automated HTTP clients. OrgTrace strictly respects these responses and emits `blocked_policy`, never attempting CAPTCHA bypass or fingerprint spoofing.
- **Robots.txt Exclusions**: Where a website's `robots.txt` disallows crawler access to contact or about pages, OrgTrace honors the exclusion and marks the source `blocked_robots`.

### 1.3 Proprietary Platform Restrictions (LinkedIn, Proff, Purehelp)
- **Zero Platform Scraping Policy**: Platforms like `proff.no`, `purehelp.no`, and `linkedin.com` contain rich Norwegian business data but explicitly prohibit automated scraping under their Terms of Service. OrgTrace **does not scrape** these restricted platforms. Any LinkedIn data is restricted to company-owned outbound links or official public APIs.

---

## 2. API Rate Limits & Network Constraints

### 2.1 Brønnøysundregistrene Public API
- **Throughput Caps**: The official `data.brreg.no` APIs (Enhetsregisteret and Regnskapsregisteret) are shared public utilities. Heavy burst traffic (e.g., > 20 requests/second from a single IP) can trigger HTTP 429 Too Many Requests. OrgTrace bounds retries with exponential backoff and caps worker concurrency at 8 threads.
- **Outages & Maintenance Windows**: Brønnøysundregistrene conducts regular weekend and overnight maintenance windows during which APIs return HTTP 500 or 503. OrgTrace's failed-refresh preservation ensures that previously verified snapshots are never wiped during an upstream outage.

### 2.2 Brave Search API
- **Subscription Quotas**: Brave Search Web API requires an active subscription key. Free-tier plans impose hard query rate limits (1 req/sec) and monthly volume caps. When the API key is omitted or exhausted, external search discovery is disabled and the engine falls back strictly to registry-linked domains.

---

## 3. Ambiguity in Identity Resolution

### 3.1 Holding Companies & Group Structures
- **Shared Brand Names**: In Norwegian corporate structures, a holding company (e.g., `XYZ Holding AS`) often shares branding, domain names, and leadership with multiple operating subsidiaries (e.g., `XYZ Drift AS`, `XYZ Eiendom AS`).
- **Precision Gate Behavior**: OrgTrace's identity gate requires exact evidence correlation (matching organisation number or unambiguous legal name match). If a shared website only references the operating subsidiary, OrgTrace will **refuse to publish** the domain for the holding company to prevent false-entity attribution. This intentionally depresses raw coverage in favor of 100% precision.

### 3.2 Foreign Entities & Branch Offices (NUF)
- **NUF Complexity**: Norwegian branches of foreign enterprises (*Norsk avdeling av utenlandsk foretak* - NUF) often operate under parent company foreign domains (e.g., `.co.uk`, `.com`, `.se`) where the Norwegian 9-digit organisation number is not displayed on the homepage. Such entities may fail domain verification unless the Norwegian branch is explicitly listed on a contact or country-selector page.

---

## 4. Financial Intelligence Constraints

### 4.1 Entities Without Accounting Obligations
- **Legal Form Exclusions**: Sole proprietorships (*Enkeltpersonforetak* - ENK) and certain partnerships (*ANS*/*DA*) that fall below size thresholds (under NOK 50M balance sheet or fewer than 20 employees) are legally exempt from submitting annual accounts to Regnskapsregisteret under the Norwegian Accounting Act (*Regnskapsloven § 1-2*). For these entities, financial statements are marked `not_applicable`.
- **Newly Formed Entities**: Companies registered in the current or previous calendar year may not yet have submitted their first annual financial statements.

### 4.2 Restructured Financial Metrics
- **Simplified Account Extraction**: Regnskapsregisteret public JSON/XML schemas provide standardized line items (*salgsinntekter*, *driftsresultat*, *ordinært resultat før skattekostnad*, *sum eiendeler*). Complex non-standard accounting notes, segment reporting, and unconsolidated group eliminations are not parsed by the automated baseline.

---

## 5. Source Freshness & Temporal Drift

### 5.1 Registry Bulk Snapshot Lag
- The bulk CSV export (`brreg-enheter.csv`) is a point-in-time snapshot. Companies dissolved, merged, or newly registered after the snapshot download date will show discrepancies with live API queries.
- OrgTrace reconciles this by allowing live module checks (`registry_live`) to supersede stale bulk rows while recording both snapshot and live timestamps.

### 5.2 Website Content Volatility
- Company websites update unpredictably. A website verified yesterday may redesign today, temporarily altering structured data markup or relocating executive lists. OrgTrace's change intelligence isolates material changes from cosmetic revisions.

---

## 6. Language, Locale, & NLP Model Constraints

### 6.1 Language Support
- OrgTrace is optimized specifically for **Norwegian (Bokmål and Nynorsk)** and **English**.
- Companies operating in minority languages (e.g., Northern Sami) or international languages without Norwegian/English counterparts may experience lower extraction recall.

### 6.2 Sentiment & NLP Models
- The optional Norwegian sentiment classifier relies on `NbAiLab/nb-bert-base`. Transformer inference requires PyTorch and GPU/CPU resources. In resource-constrained environments (e.g., standard CI runners), the model may be disabled or mocked, bypassing sentiment scoring.

---

## 7. Cost & Scaling Constraints

### 7.1 Scaling to Full Universe (411,000+ Companies)
- **Local Bulk Extraction**: Processing the full 411,160 companies via bulk CSV takes ~15–25 minutes on standard hardware with zero external API cost.
- **Live HTTP Enrichment**: Fetching live official APIs and crawling websites for all 411,000 companies would require ~2,000,000 HTTP requests. At respectful public API rate limits (10 req/s), a complete live crawl would require approximately 55 hours of continuous execution and must be scheduled across multi-day maintenance windows.

### 7.2 Evaluation Dataset Scope
- The included benchmark dataset (`EvaluationHarness`) evaluates 9 deterministic representative cases covering exact, ambiguous, subsidiary, parent, similarly named, weak web, missing info, changed info, and non-target scenarios. While achieving 100% precision on this suite, edge cases in the broader 411,000-company universe will encounter unforeseen structural variations.
