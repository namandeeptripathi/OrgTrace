# OrgTrace — Premium Frontend (Stage 21)

Evidence-first Norwegian company intelligence interface built for the Signalpost competition.

## Architecture

The frontend is built with **Next.js 16 (App Router)** and **React 19**, designed to consume OrgTrace's deterministic backend data artifacts directly with zero artificial/synthetic data:

- `out/profiles.jsonl` — 1,000+ extracted company profiles
- `out/envelopes.jsonl` — Canonical envelopes with full evidence chains and pipeline module telemetry
- `out/run-report.json` — Bounded competition batch benchmark and execution guard report

```
Search & Directory (/)
       │
       ▼
Company Intelligence (/company/[org]) ◄── Interactive Evidence Drawer
       │
       ▼
Batch / Competition Status (/batch)
```

## Features

### 1. Landing & Search (`/`)
- **Evidence-First Branding**: Professional dark-mode design with clean typography and glassmorphism.
- **Search Hero**: Real-time autocomplete searching across company names, 9-digit organisation numbers, industries, and municipalities. Supports direct Enter submission for 9-digit numbers or selected results, debounced API calls, and full keyboard navigation (Arrow Up/Down, Enter, Escape).
- **Key Benchmark Metrics**: Profile counts, success rate, verification rate, and change tracking summary.
- **Profile Directory**: Paginated/searchable company directory linking directly to detailed intelligence profiles.

### 2. Company Intelligence (`/company/[org]`)
- **Canonical Identity**: Official legal name, 9-digit org number, legal form (AS, ASA, ENK, etc.), active status, municipality, NACE industry classification, and verified website.
- **Financial Intelligence**: Regnskapsregisteret accounts including latest operating revenue, operating profit, net income, balance sheet (total assets & equity), accounting year, and statutory accounting obligation.
- **Evidence Chain & Verification**: Overall grounded rate, evidence coverage, and unsupported claim metrics. Clickable evidence nodes that open the slide-in Evidence Drawer.
- **Slide-in Evidence Drawer**: Accessible modal drawer (`role="dialog"`, Escape to close, focus management) inspecting provenance details: source type/class, verification state (Verified / Partial / Unavailable), retrieval timestamp, source URL link, and raw JSON payload preview.
- **Intelligence Explanations**: Field-level reasoning summaries with confidence levels (High / Medium / Low), uncertainty factors, and supporting evidence references.
- **Change Intelligence**: Historical snapshot comparisons showing added, modified, and removed attributes with graceful empty state when no prior snapshot exists.
- **Pipeline Modules**: Execution timings and completion statuses across all pipeline stages.

### 3. Competition Batch & Benchmark Status (`/batch`)
- **Run Summary**: Emitted profiles vs expected count, success/partial/failure rates, validation check pass/fail badge.
- **Budget Gauges**: Visual utilization gauges for request budget, execution time limit, and API cost caps.
- **Intelligence Quality**: Explanations average grounded rate, evidence coverage, change intelligence stats, and registry scan efficiency.
- **Telemetry & Domain Distribution**: Top domain request distribution and failure categories breakdown.

## Getting Started

### Prerequisites
- Node.js 18+ (tested on Node 20+)
- Backend output generated in `out/` (`out/profiles.jsonl`, `out/envelopes.jsonl`, `out/run-report.json`)

### Development Server
```bash
cd frontend
npm install
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser.

### Production Build & Typecheck
```bash
npm run build
npm run lint
```
