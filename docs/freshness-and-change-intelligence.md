# OrgTrace — Stage 16: Freshness & Change Intelligence

## 1. Overview & Objectives

Stage 16 delivers **Freshness & Change Intelligence** for OrgTrace, directly targeting the Signalpost competition's **freshness/update evaluation component**.

The primary objective is to reliably detect **meaningful, evidence-backed changes between an older company profile and the current company profile** while eliminating representation/formatting noise and minimizing false positives.

```text
Previous Profile
      ↓
Current Profile
      ↓
Field Normalization (URL, date, string, address, numbers)
      ↓
Field Comparison
      ↓
Change Classification (ADDED, MODIFIED, INCREASE, DECREASE, VALUE_UNAVAILABLE, IDENTITY_CONFLICT, NEW_PERIOD_AVAILABLE)
      ↓
Materiality Detection (CRITICAL, HIGH, MEDIUM, LOW, NONE)
      ↓
Evidence Verification (Source, URL, Retrieved_At, Supports, Confidence)
      ↓
Change Report (Structured JSON summary)
```

The system answers:
> *"What materially changed about this Norwegian company since the previous observation, and what evidence supports each change?"*

---

## 2. Canonical Profile Snapshot Model

To make profiles comparable across different runs, sources, and data models (e.g. statutory BRREG CSV, live APIs, `UnifiedCompanyProfile`, or `CompanySnapshot`), Stage 16 introduces `CanonicalProfile` in `src/norway_company_agent/change_intelligence.py`.

```python
@dataclass
class CanonicalProfile:
    organisation_number: str
    name: str = ""
    status: str = "ACTIVE"
    industry_code: str | None = None
    industry_label: str | None = None
    website: str | None = None
    website_status: str = "available"  # "available", "unavailable", "not_observed"
    address: dict[str, str] = field(default_factory=lambda: {"street": "", "postal_code": "", "city": "", "country": "Norway"})
    employees: int | None = None
    employees_status: str = "available"  # "available", "unavailable", "not_observed"
    financials: dict[str, dict[str, Any]] = field(default_factory=dict)  # Keyed by reporting period (e.g. "2024")
    registration: dict[str, Any] = field(default_factory=dict)
    observed_at: str | None = None
    evidence_map: dict[str, Any] = field(default_factory=dict)
```

The adapter function `normalize_canonical_snapshot(raw_profile)` accepts:
- Dictionary profiles (from bulk CSV, API fetches, or evaluations)
- Stage 7 `CompanySnapshot` instances
- Stage 14 `UnifiedCompanyProfile` instances
and converts them deterministically into a `CanonicalProfile`.

---

## 3. Field Normalization Engine

Before comparison, values undergo field-aware semantic normalization to eliminate non-business differences:

| Field Type | Normalizer | Rules & Transformations | Example: Equivalent (No Change) | Example: Real Change |
|---|---|---|---|---|
| **Strings** | `normalize_string_field` | Collapses multiple whitespace, trims leading/trailing spaces and punctuation. Field-aware case-folding for company names. | `"Example AS"` vs `" example as "` | `"Example AS"` vs `"Acme AS"` |
| **URLs** | `normalize_url_canonical`, `normalize_domain_canonical` | Strips `www.`, default ports (`:80`, `:443`), trailing slashes, normalizes scheme. Preserves meaningful subpaths. | `https://example.no` vs `http://example.no/` | `example.no` vs `examplegroup.no` |
| **Numbers** | `normalize_number_value` | Parses strings, floats, ints, European decimal commas (`42,5` -> `42.5`), converts whole floats (`42.0` -> `42`). | `42` vs `42.0` vs `"42"` | `42` vs `43` (fluctuation) |
| **Dates** | `normalize_date_iso` | Parses ISO 8601, `%d.%m.%Y`, `%Y/%m/%d`, `%d/%m/%Y`, `%d-%m-%Y` and converts to `YYYY-MM-DD`. | `"2026-01-15"` vs `"15.01.2026"` vs `"2026/01/15"` | `"2025-01-15"` vs `"2026-01-15"` |
| **Addresses** | `normalize_address_components` | Strips trailing commas/periods from street lines, pads postal codes to 4 digits, normalizes country (`Norge`/`NO` -> `Norway`). | `"Exampleveien 10,"` vs `"Exampleveien 10"` | `Oslo` vs `Bergen` (Relocation) |

---

## 4. Mandatory Rule: Missing Data is NOT a Change

Missing data is never converted into 0 or interpreted as deletion:

- **Missing Employees**:
  $$\text{Previous: } 42 \quad \longrightarrow \quad \text{Current: } \text{None}$$
  Emits `ChangeType.VALUE_UNAVAILABLE` with severity `NONE` and `material=False`. It is **NEVER** reported as `42 -> 0` or workforce decrease.
- **Failed Website Crawl**:
  A temporary timeout, network error, or HTTP 503 is **NOT** website removal. Emits `ChangeType.VALUE_UNAVAILABLE` with explanation: *"Website fetch failed or was unavailable; previous known website preserved, not reported as removed."*
- **Allowed States**:
  `CHANGED`, `ADDED`, `REMOVED`, `INCREASE`, `DECREASE`, `VALUE_UNAVAILABLE`, `NOT_OBSERVED`, `IDENTITY_CONFLICT`, `NEW_PERIOD_AVAILABLE`.

---

## 5. Status & Legal Entity Change Detection

Statutory status transitions represent the highest business significance and receive `CRITICAL` severity:

- `ACTIVE` $\rightarrow$ `DISSOLVED` (`SLETTET`): `CRITICAL`
- `ACTIVE` $\rightarrow$ `BANKRUPT` (`KONKURS`): `CRITICAL`
- `ACTIVE` $\rightarrow$ `UNDER_LIQUIDATION` (`UNDER_AVVIKLING`): `CRITICAL`
- Evidence is anchored to authoritative Brreg Enhetsregisteret statutory records (`confidence=0.99`).

---

## 6. Industry Change Detection

Industry classification comparison adheres to statutory hierarchy:
1. **Canonical NACE Codes Preferred**: `industry_code` (e.g., `62.010`) is compared before textual descriptions.
2. **Wording Variance Suppressed**: If the NACE code remains `62.010`, variations in description (e.g., `"Software development"` vs `"Dataprogrammering og systemutvikling"`) produce **ZERO** change events.
3. **Genuine Code Change**: A change such as `62.010` (IT) $\rightarrow$ `68.200` (Real estate) produces a material change with `HIGH` severity.

---

## 7. Website & Domain Change Detection

Website comparison distinguishes between domain changes, path modifications, and crawl failures:
- `example.no` $\rightarrow$ `examplegroup.no`: Genuine domain rebranding $\rightarrow$ `MODIFIED`, `material=True`, `severity=MEDIUM`.
- `https://example.no` $\rightarrow$ `https://example.no/`: Protocol/trailing slash variation $\rightarrow$ `UNCHANGED`, no event emitted.
- `https://example.no/about` $\rightarrow$ `https://example.no/contact`: Path modification on same domain $\rightarrow$ `MODIFIED`, `material=False`, `severity=LOW`.
- Crawl failure / HTTP error $\rightarrow$ `VALUE_UNAVAILABLE`, `material=False`, `severity=NONE`.

---

## 8. Structured Address Relocation

Address changes are evaluated at the component level:
- **Municipality / City Relocation** (e.g., `Oslo` $\rightarrow$ `Bergen`): Emitted as `address.city`, `material=True`, `severity=HIGH`.
- **Street Relocation** (e.g., `Storgata 1` $\rightarrow$ `Dronning Eufemias gate 10`): Emitted as `address.street`, `material=True`, `severity=MEDIUM`.
- **Formatting Variance** (e.g., `"Exampleveien 10,"` vs `"Exampleveien 10"`): Normalizes to identical strings $\rightarrow$ `material=False`, no event emitted.

---

## 9. Workforce & Employee Change Detection

To prevent treating natural small turnover as major events, OrgTrace enforces documented, deterministic thresholds:

### Documented Workforce Thresholds

```python
WORKFORCE_MIN_ABSOLUTE_DELTA: int = 10
WORKFORCE_MIN_PERCENTAGE_DELTA: float = 25.0
WORKFORCE_LARGE_MOVEMENT_DELTA: int = 50
WORKFORCE_HIGH_SEVERITY_PERCENTAGE: float = 50.0
```

- **Material Workforce Event**:
  - $| \Delta | \ge 10$ **AND** $| \% \Delta | \ge 25.0\%$, OR
  - $| \Delta | \ge 50$ (absolute large-scale restructuring).
- **Fluctuation Example**:
  $42 \rightarrow 43$ ($\Delta = +1, +2.4\%$): Emits `INCREASE`, `material=False`, `severity=LOW`.
- **Material Shift Example**:
  $42 \rightarrow 120$ ($\Delta = +78, +185.7\%$): Emits `INCREASE`, `material=True`, `severity=HIGH`.
- **Missing Data Example**:
  $42 \rightarrow \text{None}$: Emits `VALUE_UNAVAILABLE`, `material=False`, `severity=NONE`.

---

## 10. Financial Statement Change Handling

Financial metrics are strictly compared **by reporting period**:

- **New Reporting Period Available**:
  ```text
  Previous: 2024 Revenue = 10,000,000 NOK
  Current:  2024 Revenue = 10,000,000 NOK, 2025 Revenue = 12,000,000 NOK
  ```
  Emits `ChangeType.NEW_PERIOD_AVAILABLE` for `financials.2025`, `material=True`, `severity=MEDIUM`.
  **CRITICAL**: 2024 is **NOT** reported as changed!
- **Same-Period Restatement**:
  ```text
  Previous: 2024 Revenue = 10,000,000 NOK
  Current:  2024 Revenue = 11,000,000 NOK
  ```
  Emits `ChangeType.MODIFIED` for `financials.2024.revenue` with explanation *"Financial statement restatement for period 2024"*.

---

## 11. Registration & Identity Conflict

If an older record and a newer record have different organization numbers:
```text
Previous: 123456789
Current:  987654321
```
The engine does **NOT** report `"organisation number changed"`.
Instead, it emits:
- `ChangeType.IDENTITY_CONFLICT`
- `category=ChangeCategory.IDENTITY`
- `severity=MaterialitySeverity.CRITICAL`
- `material=True`, `confidence=1.0`
- Report status is set to `"IDENTITY_CONFLICT"`.

---

## 12. Materiality Classification Matrix

| Severity | Definition | Applicable Change Events |
|---|---|---|
| **CRITICAL** | Core legal status transition or identity breach | Insolvency, liquidation, dissolution, statutory entity status changes, `IDENTITY_CONFLICT`. |
| **HIGH** | Major structural business movement | Industry classification code change (NACE), municipality relocation, legal form conversion (`ENK` $\rightarrow$ `AS`), major workforce restructuring ($|\Delta| \ge 50$ or $\ge 50\%$). |
| **MEDIUM** | Meaningful commercial / operational evolution | Domain rebranding, street address relocation, new annual financial filing (`NEW_PERIOD_AVAILABLE`), same-period financial restatement. |
| **LOW** | Minor non-critical movements | Small employee fluctuations ($|\Delta| < 10$ or $< 25\%$), postal code updates, same-domain URL path updates. |
| **NONE** | Technical representation variance & missing data | Whitespace/casing differences, trailing URL slashes, date formatting variations, crawl failures, unavailable fields. |

---

## 13. Evidence Linkage & Confidence Scoring

Every material change record includes verifiable evidence:

```json
{
  "category": "STATUS",
  "field": "status",
  "previous": "ACTIVE",
  "current": "UNDER_LIQUIDATION",
  "change_type": "modified",
  "material": true,
  "severity": "CRITICAL",
  "confidence": 0.99,
  "evidence": [
    {
      "source": "BRREG_ENHETSREGISTERET",
      "url": "https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
      "observed_at": "2026-09-24T12:00:00Z",
      "supports": "current_value",
      "content_sha256": "feedbeef1234567890abcdef"
    }
  ],
  "explanation": "Company legal status transitioned from 'ACTIVE' to 'UNDER_LIQUIDATION'"
}
```

Confidence scores reflect source authority:
- Statutory Registry (`BRREG_ENHETSREGISTERET`, `A_ORDNINGEN`): `0.99`
- Official Annual Financial Filing (`REGNSKAPSREGISTERET`): `0.95`
- Verified Company Website: `0.85`
- Secondary / Unverified: `0.50` - `0.70`

---

## 14. First Observation Handling

When analyzing a company for the first time (`previous=None`):
- Report status: `"INITIAL_OBSERVATION"`
- Total changes: `0`
- Material changes: `0`
- Prevents generating false alarms or claiming every existing field is a "change".

---

## 15. Validation & Test Execution

### Running Stage 16 Tests

```bash
# Run Stage 16 dedicated unit and integration tests
uv run python -m unittest tests/test_stage16_change_intelligence.py -v

# Run full OrgTrace regression test suite (331 tests)
uv run python -m unittest discover tests

# Run competition refresh replay demonstration
./scripts/run_competition.sh replay

# Run 10-profile competition batch smoke test
./scripts/run_competition.sh smoke
```
