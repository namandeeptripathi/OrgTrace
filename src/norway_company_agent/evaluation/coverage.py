"""Stage 18: Coverage Evaluation Module.

Evaluates data completeness across the 13 defined information categories:
- identity
- company_profile
- contact
- website
- financial
- industry
- management
- ownership
- locations
- external_research
- changes
- evidence
- explanations

Distinguishes: found, missing, invalid, unknown, not_applicable.
Calculates coverage_rate, field_coverage_rate, category_coverage_rate,
and preserves detailed missing/invalid field diagnostic lists.
"""

from __future__ import annotations

from typing import Any

from .models import CoverageEvaluation, CoverageFieldStatus


# Schema mapping the 13 categories to expected field keys / extractors
COVERAGE_SCHEMA: dict[str, list[str]] = {
    "identity": ["organisation_number", "legal_name", "legal_form", "status"],
    "company_profile": ["description", "registration_date", "municipality", "address"],
    "contact": ["email", "phone", "contact_url"],
    "website": ["website_url"],
    "financial": ["revenue", "profit_loss", "assets", "equity", "financial_year"],
    "industry": ["industry_code", "industry_label"],
    "management": ["leadership_roles"],
    "ownership": ["group_structure", "parent_company"],
    "locations": ["subunits"],
    "external_research": ["social_presence", "news"],
    "changes": ["recent_changes"],
    "evidence": ["evidence_items"],
    "explanations": ["explanation_records"],
}


def _check_field_status(category: str, field_name: str, profile: dict[str, Any]) -> tuple[CoverageFieldStatus, str | None]:
    """Inspect profile to determine if a field is found, missing, invalid, unknown, or not applicable."""
    # Check top-level or nested values
    val: Any = None
    evidence_block = profile.get("evidence", {})

    if category == "identity":
        if field_name == "organisation_number":
            val = profile.get("organisation_number") or profile.get("orgnr")
            if val and (not str(val).isdigit() or len(str(val)) != 9):
                return CoverageFieldStatus.INVALID, "invalid_org_number_format"
        elif field_name == "legal_name":
            val = profile.get("name") or profile.get("company_name")
        elif field_name == "legal_form":
            val = profile.get("legal_form") or profile.get("organisasjonsform")
        elif field_name == "status":
            val = profile.get("status") or profile.get("verdict_status") or "active"

    elif category == "company_profile":
        if field_name == "description":
            val = profile.get("description")
            if not val and isinstance(evidence_block.get("website"), dict):
                val = (evidence_block["website"].get("value") or {}).get("description")
        elif field_name == "registration_date":
            val = profile.get("registration_date") or profile.get("registered_at")
        elif field_name == "municipality":
            val = profile.get("municipality") or profile.get("forretningsadresse", {}).get("kommune")
        elif field_name == "address":
            val = profile.get("address") or profile.get("business_address") or profile.get("postal_address")

    elif category == "contact":
        contact_dict = profile.get("contact") or {}
        if field_name in contact_dict:
            val = contact_dict.get(field_name)
        elif field_name == "email":
            val = profile.get("email")
        elif field_name == "phone":
            val = profile.get("phone") or profile.get("telephone")
        elif field_name == "contact_url":
            val = profile.get("contact_url")

    elif category == "website":
        if field_name == "website_url":
            val = profile.get("website") or profile.get("homepage")
            if not val and isinstance(evidence_block.get("website"), dict):
                w_rec = evidence_block["website"]
                if w_rec.get("status") == "available":
                    val = w_rec.get("source_url") or (w_rec.get("value") or {}).get("url")
            if val and not (str(val).startswith("http://") or str(val).startswith("https://") or "www." in str(val)):
                return CoverageFieldStatus.INVALID, "invalid_url_format"

    elif category == "financial":
        fin_data = profile.get("financials") or profile.get("financial_profile")
        if not fin_data and isinstance(evidence_block.get("financials"), dict):
            fin_val = evidence_block["financials"].get("value") or {}
            recs = fin_val.get("records") or []
            if recs:
                fin_data = recs[0]
        if isinstance(fin_data, dict):
            if field_name == "revenue":
                val = fin_data.get("revenue") or fin_data.get("salgsinntekter")
            elif field_name == "profit_loss":
                val = fin_data.get("operating_result") or fin_data.get("annual_result") or fin_data.get("ordinaertResultatForSkattekostnad")
            elif field_name == "assets":
                val = fin_data.get("assets") or fin_data.get("eiendeler")
            elif field_name == "equity":
                val = fin_data.get("equity") or fin_data.get("egenkapital")
            elif field_name == "financial_year":
                val = fin_data.get("period") or fin_data.get("year") or fin_data.get("financial_year") or profile.get("latest_submitted_accounts")

    elif category == "industry":
        if field_name == "industry_code":
            val = profile.get("industry_code") or (profile.get("industry") or {}).get("code")
        elif field_name == "industry_label":
            val = profile.get("industry_label") or (profile.get("industry") or {}).get("label") or (profile.get("industry") or {}).get("beskrivelse")

    elif category == "management":
        roles = profile.get("roles") or profile.get("leadership")
        if not roles and isinstance(evidence_block.get("roles"), dict):
            roles = (evidence_block["roles"].get("value") or {}).get("roles")
        if roles and isinstance(roles, list) and len(roles) > 0:
            val = roles

    elif category == "ownership":
        grp = profile.get("group") or profile.get("group_structure") or profile.get("ownership")
        if not grp and isinstance(evidence_block.get("group"), dict):
            grp = evidence_block["group"].get("value")
        if grp is not None:
            val = grp

    elif category == "locations":
        locs = profile.get("locations") or profile.get("subunits")
        if not locs and isinstance(evidence_block.get("locations"), dict):
            locs = (evidence_block["locations"].get("value") or {}).get("locations")
        if locs is not None:
            val = locs

    elif category == "external_research":
        if field_name == "social_presence":
            val = profile.get("social_presence") or profile.get("social_links")
            if not val and isinstance(evidence_block.get("website"), dict):
                val = (evidence_block["website"].get("value") or {}).get("social_links")
        elif field_name == "news":
            val = profile.get("news") or profile.get("news_events")

    elif category == "changes":
        val = profile.get("change_intelligence") or profile.get("changes") or profile.get("material_changes")

    elif category == "evidence":
        ev = profile.get("evidence") or profile.get("evidence_items")
        if ev and isinstance(ev, (dict, list)) and len(ev) > 0:
            val = ev

    elif category == "explanations":
        exp = profile.get("explanations") or profile.get("explanation_report")
        if exp and isinstance(exp, (dict, list)) and len(exp) > 0:
            val = exp

    # Classify presence
    if val is not None and val != "" and val != [] and val != {}:
        return CoverageFieldStatus.FOUND, None
    return CoverageFieldStatus.MISSING, None


def evaluate_company_coverage(
    profile: dict[str, Any] | None,
    schema: dict[str, list[str]] | None = None,
) -> CoverageEvaluation:
    """Evaluate field and category coverage for a single company profile."""
    target_schema = schema or COVERAGE_SCHEMA
    if not profile:
        # All fields missing
        all_missing: list[str] = []
        cat_map: dict[str, dict[str, int | float]] = {}
        for cat, fields in target_schema.items():
            for f in fields:
                all_missing.append(f"{cat}.{f}")
            cat_map[cat] = {
                "found": 0,
                "missing": len(fields),
                "invalid": 0,
                "unknown": 0,
                "not_applicable": 0,
                "rate": 0.0,
            }
        return CoverageEvaluation(
            rate=0.0,
            field_coverage_rate=0.0,
            category_coverage_rate=0.0,
            found_fields_count=0,
            missing_fields_count=len(all_missing),
            invalid_fields_count=0,
            missing_fields=all_missing,
            invalid_fields=[],
            categories=cat_map,
        )

    total_fields = 0
    found_fields = 0
    missing_fields_list: list[str] = []
    invalid_fields_list: list[str] = []
    category_rates: list[float] = []
    category_breakdowns: dict[str, dict[str, int | float]] = {}

    for cat_name, field_names in target_schema.items():
        cat_found = 0
        cat_missing = 0
        cat_invalid = 0
        cat_unknown = 0
        cat_na = 0

        for f_name in field_names:
            total_fields += 1
            path = f"{cat_name}.{f_name}"
            status, reason = _check_field_status(cat_name, f_name, profile)

            if status == CoverageFieldStatus.FOUND:
                found_fields += 1
                cat_found += 1
            elif status == CoverageFieldStatus.INVALID:
                invalid_fields_list.append(f"{path} ({reason or 'invalid'})")
                cat_invalid += 1
            elif status == CoverageFieldStatus.NOT_APPLICABLE:
                cat_na += 1
            elif status == CoverageFieldStatus.UNKNOWN:
                cat_unknown += 1
            else:
                missing_fields_list.append(path)
                cat_missing += 1

        cat_evaluable = cat_found + cat_missing + cat_invalid
        cat_rate = cat_found / cat_evaluable if cat_evaluable > 0 else 1.0
        category_rates.append(cat_rate)

        category_breakdowns[cat_name] = {
            "found": cat_found,
            "missing": cat_missing,
            "invalid": cat_invalid,
            "unknown": cat_unknown,
            "not_applicable": cat_na,
            "rate": round(cat_rate, 4),
        }

    field_rate = found_fields / total_fields if total_fields > 0 else 0.0
    cat_avg_rate = sum(category_rates) / len(category_rates) if category_rates else 0.0
    overall_rate = (field_rate * 0.5) + (cat_avg_rate * 0.5)

    return CoverageEvaluation(
        rate=overall_rate,
        field_coverage_rate=field_rate,
        category_coverage_rate=cat_avg_rate,
        found_fields_count=found_fields,
        missing_fields_count=len(missing_fields_list),
        invalid_fields_count=len(invalid_fields_list),
        missing_fields=missing_fields_list,
        invalid_fields=invalid_fields_list,
        categories=category_breakdowns,
    )
