# OrgTrace — Dependencies, Models, APIs, and Licenses

This document inventories all external dependencies, libraries, APIs, machine learning models, and data sources utilized by **OrgTrace**, along with their respective licensing terms and attribution requirements.

---

## A. Python Package Dependencies

All runtime dependencies are pinned in [`requirements.txt`](requirements.txt) with exact versions, and specified with semver ranges in [`pyproject.toml`](pyproject.toml).

### Core Runtime Packages

| Package | Pinned Version | Purpose | Provider / Upstream | License | Attribution Requirement |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `beautifulsoup4` | `4.15.0` | HTML parsing and navigation | Leonard Richardson | MIT | Not required |
| `extruct` | `0.18.0` | Extraction of Microdata, JSON-LD, and RDFa | Scrapinghub / Zyte | BSD-3-Clause | BSD notice in redistributions |
| `lxml` | `6.1.2` | High-performance XML/HTML processing | lxml team | BSD-3-Clause / GPL | BSD notice in redistributions |
| `pydantic` | `2.13.4` | Data validation and settings management | Pydantic Services Inc. | MIT | Not required |
| `pypdf` | `6.16.1` | PDF parsing for annual reports | pypdf contributors | BSD-3-Clause | BSD notice in redistributions |
| `tldextract` | `5.3.2` | Accurate domain and TLD extraction | John Kurkowski | BSD-3-Clause | BSD notice in redistributions |
| `trafilatura` | `2.2.0` | Web scraping and main text extraction | Adrien Barbaresi | Apache-2.0 | Apache 2.0 notice |
| `requests` | `2.34.2` | HTTP client for REST APIs and web pages | Kenneth Reitz / PSF | Apache-2.0 | Apache 2.0 notice |
| `urllib3` | `2.7.0` | Low-level HTTP transport and connection pooling | urllib3 team | MIT | Not required |

### Optional / Extension Packages

| Package | Version Range | Purpose | Provider / Upstream | License | Attribution Requirement |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `scrapy` | `>=2.13,<3` | Distributed web crawling framework | Zyte / Scrapy team | BSD-3-Clause | BSD notice in redistributions |
| `scrapy-playwright` | `>=0.0.44,<1` | Headless Chromium rendering for SPAs | Scrapy team | BSD-3-Clause | BSD notice in redistributions |
| `torch` | `>=2.5,<3` | Deep learning runtime for sentiment analysis | PyTorch Foundation | Modified BSD | BSD notice in redistributions |
| `transformers` | `>=4.51,<5` | Hugging Face transformer model pipelines | Hugging Face | Apache-2.0 | Apache 2.0 notice |
| `accelerate` | `>=1.10,<2` | Multi-device training and inference helper | Hugging Face | Apache-2.0 | Apache 2.0 notice |

---

## B. External APIs

| API Name | Provider | Endpoint | Purpose | Auth Required | Free / Paid Status | License / Terms | Attribution Statement |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Enhetsregisteret Open API** | Brønnøysundregistrene (Norwegian State) | `https://data.brreg.no/enhetsregisteret/api` | Live company status, legal forms, roles, addresses | None | Free (Public Service) | [NLOD 2.0](https://data.norge.no/nlod/no/2.0) | *"Inneholder data under Norsk lisens for offentlige data (NLOD) tilgjengeliggjort av Brønnøysundregistrene."* |
| **Regnskapsregisteret Open API** | Brønnøysundregistrene (Norwegian State) | `https://data.brreg.no/regnskapsregisteret/regnskap` | Official annual accounts, balance sheets, revenues | None | Free (Public Service) | [NLOD 2.0](https://data.norge.no/nlod/no/2.0) | *"Inneholder regnskapsdata under Norsk lisens for offentlige data (NLOD) tilgjengeliggjort av Brønnøysundregistrene."* |
| **Brave Search Web API** | Brave Software, Inc. | `https://api.search.brave.com/res/v1/web/search` | External domain and footprint discovery | API Key (`BRAVE_SEARCH_API_KEY`) | Free tier available; paid commercial plans | Commercial Terms of Service | *"Search candidate results provided via Brave Search API."* |

---

## C. AI and Machine Learning Models

| Model Identifier | Provider / Author | Architecture / Type | Purpose | Auth / Hosting | License | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`NbAiLab/nb-bert-base`** | National Library of Norway (Nasjonalbiblioteket) | Transformer (BERT Base, 110M params) | Norwegian sentiment analysis and text classification | Hugging Face Hub (local download) | CC-BY-4.0 | Optional component in `scripts/run_sentiment_model.py`. Bypassed in standard lightweight evaluation. |
| **Deterministic Pattern Matchers** | OrgTrace First-Party | Rule-based regex and AST tokenizers | Exact entity matching, address parsing, Modulo 11 check | Built-in | MIT / Project License | Zero inference cost, 100% deterministic reproducibility. |

---

## D. Data Sources

| Data Source | Provider | Format / Ingestion | Purpose | License | Verification Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`brreg-enheter.csv`** | Brønnøysundregistrene | CSV bulk export (~154 MB, ~1.17M entities) | Canonical baseline for Norwegian registered business entities | NLOD 2.0 | Verified official government release |
| **`signalpost-universe.jsonl.gz`** | Signalpost Challenge / Builderr.ai | Compressed JSONL (~12.6 MB, 411,160 entities) | Benchmark candidate universe for the competition | Competition Benchmark License | Verified benchmark artifact |
| **First-Party Company Websites** | Individual Norwegian Enterprises | HTTP / HTTPS static HTML | Verification of active business, contact info, leadership | First-Party Copyright / Public Web | Factual claims extracted under fair use / public directory principles |
| **Lovdata Open Legal Data** | Stiftelsen Lovdata | Public legal texts | Legal form and accounting obligation statutory references | Public Sector Information | Verified public legal resource |

---

## E. Restricted Sources (Explicitly Not Used)

To protect evaluator trust and maintain strict legal compliance, OrgTrace **does not scrape or bypass protections** on the following platforms:

| Restricted Platform | Domain | Policy | Rationale |
| :--- | :--- | :--- | :--- |
| **Proff.no** | `proff.no` | Blocked by Policy | Commercial database prohibiting automated extraction in ToS |
| **Purehelp.no** | `purehelp.no` | Blocked by Policy | Proprietary business directory with anti-scraping protections |
| **LinkedIn (direct scraping)** | `linkedin.com` | Blocked by Policy | Strict CFAA and ToS prohibitions against unauthenticated crawling |
| **Gule Sider / 1881** | `gulesider.no`, `1881.no` | Blocked by Policy | Proprietary directory platforms |
