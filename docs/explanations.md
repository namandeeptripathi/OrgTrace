# Evidence-Grounded Explanations

## 1. Overview & Primary Goal

OrgTrace includes a lightweight, zero-hallucination explanation layer designed for the Signalpost **10-point explanation/usability** competition component.

The explanation engine answers five fundamental questions for any company field:
1. **What the agent found** (concise summary)
2. **Why the conclusion was reached** (evidence-based reasoning rationale)
3. **Which evidence supports it** (explicit evidence IDs and source citations)
4. **How confident the system is** (`HIGH`, `MEDIUM`, `LOW`, `UNKNOWN`)
5. **What remains uncertain or unsupported** (explicit missing evidence statements)

---

## 2. Core Design Principle: Evidence First, Explanation Second

The explanation layer never invents missing information or operates as an independent fact generator. It strictly operates on already-retrieved, verified facts and evidence:

```
Retrieved Facts
      ↓
Evidence (4-Tier Source Hierarchy)
      ↓
Explanation Reasoning (Deterministic / Guardrailed LLM)
      ↓
Strict Hallucination Validator
      ↓
Validated Explanation OR Safe Deterministic Fallback
```

---

## 3. Evidence Requirements & 4-Tier Source Hierarchy

Evidence is strictly partitioned into four deterministic priority tiers:

| Tier | Category | Sources | Policy |
| :--- | :--- | :--- | :--- |
| **Tier 1** | **Statutory & First-Party** | Brønnøysundregistrene (Enhetsregisteret), Verified Corporate Website | Primary basis for all identity, status, workforce, and activity claims. |
| **Tier 2** | **Authoritative Public** | Regnskapsregisteret, official annual financial reports, Aa-registeret | Authoritative source for financial figures and statutory metrics. |
| **Tier 3** | **Reputable Secondary** | Verified public announcements, official partner registries | Supporting corroboration only; never used alone for core status claims. |
| **Tier 4** | **Weak / Unverified** | Unverified aggregators, unlinked web pages, scrapers | Quarantined; rejected as sole basis for explanatory statements. |

---

## 4. Confidence Levels

The system assigns confidence deterministically based on source corroboration:

- **HIGH**: Multiple strong Tier 1 / Tier 2 sources agree (e.g., BRREG statutory registry + verified corporate website).
- **MEDIUM**: A single strong authoritative source supports the claim with limited corroboration.
- **LOW**: Available evidence is weak, indirect, outdated, or conflicting across sources.
- **UNKNOWN**: Insufficient evidence exists in public registers or corporate disclosures.

---

## 5. Uncertainty & Conflict Handling

- **Missing Evidence**: When a fact is unobserved (e.g., no employee census in Aa-registeret or no website), OrgTrace does not guess or fill gaps from parametric model memory. It emits an explicit insufficient-evidence explanation with `UNKNOWN` confidence and populated `missing_evidence`.
- **Conflicting Sources**: When sources disagree (e.g., registry states active while a news report claims liquidation), OrgTrace does not silently pick a winner. It reports `LOW` confidence, notes the conflict explicitly in `conflicts`, and refuses to treat the field as definitively resolved.

---

## 6. Hallucination Safeguards & Validation

Every explanation candidate (especially LLM-generated output) is subjected to post-generation validation:

1. **Evidence ID Check**: Every referenced evidence ID must exist in `context.available_evidence_ids`. Invalid IDs trigger immediate rejection.
2. **Prohibited Sources Check**: Citations of unsupplied third-party platforms (e.g. `proff.no`, `purehelp.no`, `bloomberg`) are rejected.
3. **Numeric Grounding Check**: Substantive numbers in the text must match supplied facts (e.g. registered employees, revenue, organisation numbers).
4. **Temporal Grounding Check**: 4-digit years must originate from supplied evidence dates.
5. **Entity Identity Check**: Extraneous or foreign company entities (e.g. `Acme Corporation`) mentioned in prose are rejected.

**Failure Rule**: Any validation failure causes immediate rejection and replaces the text with a safe, deterministic fallback.

---

## 7. Example Output

### Grounded High-Confidence Explanation (Industry)
```json
{
  "field_name": "industry",
  "summary": "The company operates in Utvinning av råolje (NACE 06.100), corroborated by its official website.",
  "reasoning": "Its registered statutory classification in Brønnøysundregistrene is 06.100 (Utvinning av råolje), which aligns with service and activity descriptions found on its official website.",
  "confidence": "high",
  "uncertainty": null,
  "supporting_evidence": [
    {
      "evidence_id": "ev-registry",
      "source_name": "BRREG_ENHETSREGISTERET",
      "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
      "source_tier": 1
    },
    {
      "evidence_id": "ev-website",
      "source_name": "OFFICIAL_COMPANY_WEBSITE",
      "source_url": "https://www.equinor.com",
      "source_tier": 1
    }
  ],
  "missing_evidence": [],
  "conflicts": [],
  "is_fallback": false,
  "validation_passed": true
}
```

### Insufficient Evidence Explanation (Missing Workforce)
```json
{
  "field_name": "workforce",
  "summary": "No registered employee count is available for this company.",
  "reasoning": "The register record does not contain an employee count; missing values are never interpreted as zero.",
  "confidence": "unknown",
  "uncertainty": "Employee count not observed in register.",
  "supporting_evidence": [],
  "missing_evidence": [
    "Aa-registeret employee census record"
  ],
  "conflicts": [],
  "is_fallback": false,
  "validation_passed": true
}
```

---

## 8. CLI Formatting

The explanation suite formats cleanly for CLI consumption:

```text
────────────────────────────────────────────────────────────────────────────────
 EXPLANATIONS: 923609016 (Equinor Energy AS)
 Overall Confidence: HIGH | Grounded Rate: 100.0% | Evidence Coverage: 87.5%
────────────────────────────────────────────────────────────────────────────────
[IDENTITY]
Summary: Equinor Energy AS is an identified Norwegian legal entity with organisation number 923609016.
Reasoning: The legal name and 9-digit statutory organisation number are verified directly against Brønnøysundregistrene (Enhetsregisteret) under legal form AS.
Confidence: HIGH
Evidence:
  • BRREG_ENHETSREGISTERET (https://data.brreg.no/enhetsregisteret/api/enheter/923609016)

[STATUS]
Summary: The company is registered as active in Norway according to official registry records.
Reasoning: Statutory records from Brønnøysundregistrene confirm the company is in normal operation with no active bankruptcy, liquidation, or dissolution proceedings.
Confidence: HIGH
Evidence:
  • BRREG_ENHETSREGISTERET (https://data.brreg.no/enhetsregisteret/api/enheter/923609016)
```
