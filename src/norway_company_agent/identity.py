from __future__ import annotations

import re
import unicodedata
import urllib.parse
from typing import Any

from .discovery import BLOCKED_DISCOVERY_HOSTS
from .identity_engine import (
    DomainMatch,
    DomainMatchCategory,
    GroupRelationship,
    GroupRelationType,
    IdentityConfidence,
    IdentityEvidence,
    IdentityVerdict,
    IdentityVerdictStatus,
    LegalNameMatch,
    LegalNameMatchCategory,
    OrgNumberValidation,
    assess_company_identity,
    canonicalize_org_number,
    classify_group_relationship,
    compute_mod11_check_digit,
    detect_ambiguity,
    extract_legal_form,
    is_valid_org_mod11,
    match_domain_entity,
    match_legal_names,
    normalize_legal_name,
    validate_org_number,
)

LEGAL_AND_GENERIC = {
    "as", "asa", "ans", "da", "enk", "iks", "sa", "sam", "sti", "stiftelsen",
    "nuf", "ab", "b", "v", "limited", "ltd", "inc", "plc", "the", "og", "and",
}

VENDOR_PLATFORM_HANDLES = {
    "squarespace", "wix", "wordpress", "shopify", "webflow", "weebly",
    "hubspot", "ghost", "drupal", "joomla", "prestashop", "magento",
    "bigcommerce", "strapi", "contentful", "carrd", "automattic",
    "wpengine", "mailchimp", "klaviyo", "zendesk", "intercom", "github",
    "bitbucket", "gitlab", "vercel", "netlify", "medium", "substack",
    "google", "apple", "microsoft",
}

VENDOR_AGENCY_KEYWORDS = {
    "webdesign", "webbyraa", "nettbyraa", "designbyraa", "digitalbyraa",
    "reklamebyraa", "webutvikling", "mediabyraa", "kommunikasjonsbyraa",
    "designbureau", "adagency", "creativeagency", "theme", "template",
    "webdesignbureauet", "nettside", "utviklet",
}

GENERIC_INDUSTRY_TERMS = {
    "design", "media", "consulting", "solutions", "gruppe", "gruppen", "group",
    "holding", "holdings", "invest", "investment", "service", "services",
    "drift", "eiendom", "bygg", "transport", "handel", "teknologi", "technology",
    "consult", "advokat", "studio", "consultants", "partners", "partner",
    "management", "international",
}

GEOGRAPHIC_DISCRIMINATORS = {
    "norway", "norge", "nordic", "scandinavia", "oslo", "bergen", "stavanger",
    "trondheim", "tromso",
}

GENERIC_NAME_STOPWORDS = GENERIC_INDUSTRY_TERMS | {
    "as", "asa", "ans", "da", "enk", "sa", "nuf", "sti", "iks", "ba",
}



def _tokens(value: Any) -> list[str]:
    text = str(value or "").translate(str.maketrans({"ø": "o", "Ø": "O", "å": "a", "Å": "A", "æ": "ae", "Æ": "AE"}))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    return [token for token in re.findall(r"[a-z0-9]+", text) if token not in LEGAL_AND_GENERIC and len(token) > 1]


def _structured_names(value: Any) -> list[str]:
    names: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"name", "legalName", "alternateName"} and isinstance(child, str):
                names.append(child)
            else:
                names.extend(_structured_names(child))
    elif isinstance(value, list):
        for child in value:
            names.extend(_structured_names(child))
    return names


def assess_website_identity(profile: dict[str, Any]) -> dict[str, Any]:
    website = profile.get("evidence", {}).get("website", {})
    value = website.get("value") or {}
    core = _tokens(profile.get("name"))
    raw_url = str(value.get("final_url") or website.get("source_url") or "")
    parsed_url = urllib.parse.urlparse(raw_url)
    hostname = (parsed_url.hostname or "").lower()
    clean_host = hostname.removeprefix("www.")

    # 1. Reject aggregator, directory, and social platform hostnames
    if clean_host and any(clean_host == b or clean_host.endswith("." + b) for b in BLOCKED_DISCOVERY_HOSTS):
        return {
            "status": "wrong_company_or_directory",
            "score": 0.0,
            "publishable": False,
            "legal_name_tokens": core,
            "matched_tokens": [],
            "reasons": [f"aggregator_or_directory_host: Website host '{clean_host}' is an aggregator, directory, or social platform, not a company website"],
            "method": "deterministic_name_org_evidence_v2",
        }

    # 2. Reject root builder/vendor hosts
    if clean_host in {"wixsite.com", "wordpress.com", "squarespace.com", "weebly.com", "shopify.com"}:
        return {
            "status": "vendor_platform_attribution",
            "score": 0.0,
            "publishable": False,
            "legal_name_tokens": core,
            "matched_tokens": [],
            "reasons": [f"platform_root_host: Website host '{clean_host}' is a generic vendor platform root, not a company website"],
            "method": "deterministic_name_org_evidence_v2",
        }

    structured_names = _structured_names(value.get("structured_organisations") or [])
    rendered = value.get("js_fallback") or {}
    homepage_identity_parts = [
        value.get("title"), value.get("description"), value.get("identity_text_excerpt"), hostname, *structured_names,
        rendered.get("title"),
    ]
    candidate_parts = [
        *homepage_identity_parts, value.get("main_text_excerpt"), value.get("main_text"),
        *[page.get("title") for page in value.get("pages", [])],
        *[page.get("main_text_excerpt") for page in value.get("pages", [])],
        *[page.get("main_text") for page in value.get("pages", [])],
        *[page.get("identity_text_excerpt") for page in value.get("pages", [])],
    ]
    candidate_parts.append(rendered.get("main_text_excerpt"))
    candidate_parts.append(rendered.get("main_text"))
    candidate_text = " ".join(str(part or "") for part in candidate_parts)
    homepage_candidate_text = " ".join(str(part or "") for part in [*homepage_identity_parts, value.get("main_text_excerpt"), value.get("main_text"), rendered.get("main_text_excerpt")])
    normalized_candidate_text = " ".join(_tokens(candidate_text))
    candidate_tokens = set(_tokens(candidate_text))
    org_digits = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    compact_candidate = re.sub(r"\D", "", candidate_text)
    compact_homepage_candidate = re.sub(r"\D", "", homepage_candidate_text)
    overlap = sorted(set(core) & candidate_tokens)
    ratio = len(overlap) / len(set(core)) if core else 0.0
    reasons = []
    parked_markers = (
        "domain is for sale", "domain for sale", "hugedomains", "parked at", "miss hosting",
        "her flytter snart en ny gjest", "has been informing visitors",
        "find the best information and most relevant links on all topics related to",
        "buy this domain", "domainet er parkert", "parkert hos", "for sale",
    )
    normalized_raw = unicodedata.normalize("NFKD", candidate_text).encode("ascii", "ignore").decode().casefold()
    homepage_token_sets = [set(_tokens(part)) for part in homepage_identity_parts if part]
    exact_in_header = bool(core and any(set(core).issubset(tokens) for tokens in homepage_token_sets))
    header_tokens = set().union(*homepage_token_sets) if homepage_token_sets else set()
    body_tokens = set(_tokens(value.get("main_text_excerpt") or value.get("main_text") or ""))
    full_in_body = bool(core and set(core).issubset(body_tokens))
    has_header_anchor = bool(set(core) & header_tokens)
    exact_homepage_name = exact_in_header or (full_in_body and has_header_anchor)
    raw_html_len = len(str(value.get("raw_html") or ""))
    substantive_homepage = (
        len(str(value.get("main_text_excerpt") or value.get("main_text") or "").strip()) >= 100
        or len(str(value.get("description") or "").strip()) >= 40
        or raw_html_len >= 5000
        or (bool(core) and clean_host and clean_host.split(".")[0] == core[0] and bool(value.get("title")))
    )
    is_business_sports_club = bool(re.search(r"(?:^|\s)B\.?\s*I\.?\s*L\.?(?:\s|$)", str(profile.get("name") or ""), re.I))

    # 3. Detect valid Modulo-11 Norwegian organisation numbers on page (supporting 9-digit or 3-3-3 spaced formats)
    raw_found = re.findall(r"\b\d{3}\s*\d{3}\s*\d{3}\b|\b\d{9}\b", candidate_text)
    cleaned_found = [re.sub(r"\s+", "", c) for c in raw_found]
    found_orgs = list(dict.fromkeys(
        cand for cand in cleaned_found
        if len(cand) == 9 and is_valid_org_mod11(cand)
    ))
    parent_org = canonicalize_org_number(profile.get("overordnetEnhet") or profile.get("parent_organisation"))

    if any(marker in normalized_raw for marker in parked_markers):
        score = 0.1
        reasons.append("captured page is a parked, for-sale, or generic hosting placeholder")
    elif found_orgs and org_digits and org_digits not in found_orgs:
        # Page explicitly cites a different valid organisation number
        if parent_org and parent_org in found_orgs:
            score = 0.35
            reasons.append(f"parent_attribution: captured page cites parent organisation number {parent_org}, not target company {org_digits}")
        else:
            score = 0.1
            reasons.append(f"wrong_company_attribution: captured page cites conflicting organisation number {found_orgs[0]}, target is {org_digits}")
    elif is_business_sports_club and "bedriftsidrett" not in normalized_candidate_text and "b i l" not in normalized_candidate_text:
        score = 0.3
        reasons.append("business sports-club entity points to the operating company's site without club evidence")
    elif org_digits and org_digits in compact_homepage_candidate:
        score = 1.0
        reasons.append("exact organisation number appears in homepage identity evidence")
    elif len(core) >= 2 and exact_homepage_name:
        score = 0.95
        reasons.append("all normalized legal-name tokens appear together in homepage identity evidence")
    elif len(core) == 1 and exact_homepage_name and substantive_homepage:
        score = 0.95
        reasons.append("single distinctive legal-name token appears in homepage identity evidence with substantive content")
    elif ratio >= 0.75 and len(overlap) >= 2:
        score = 0.85
        reasons.append("most legal-name tokens appear, but exact identity is incomplete")
    elif ratio >= 0.5 and len(overlap) >= 2:
        score = 0.65
        reasons.append("partial legal-name overlap only")
    else:
        score = 0.3
        reasons.append("registry-linked URL lacks strong exact-entity identity evidence")

    if score >= 0.9:
        status = "exact"
    elif "parent organisation" in " ".join(reasons):
        status = "parent_attribution"
    elif "conflicting organisation" in " ".join(reasons):
        status = "wrong_company_attribution"
    elif score >= 0.8:
        status = "review"
    else:
        status = "related_or_uncertain"

    ret = {
        "status": status,
        "score": score,
        "publishable": status == "exact",
        "legal_name_tokens": core,
        "matched_tokens": overlap,
        "reasons": reasons,
        "method": "deterministic_name_org_evidence_v2",
    }
    if found_orgs and org_digits and org_digits not in found_orgs:
        if parent_org and parent_org in found_orgs:
            ret["parent_org_number"] = parent_org
        elif found_orgs:
            ret["conflicting_org_number"] = found_orgs[0]
    return ret


def assess_social_identity(profile: dict[str, Any], link: dict[str, str]) -> dict[str, Any]:
    url = link.get("url") or ""
    parsed = urllib.parse.urlparse(url)
    path = urllib.parse.unquote(parsed.path)
    clean_parts = [p.casefold().strip() for p in path.split("/") if p.strip()]
    handle_text = clean_parts[-1] if clean_parts else ""
    handle_compact = "".join(_tokens(handle_text))
    full_path_tokens = set(_tokens(path))

    # 1. Reject vendor platform root profiles, CMS tools, site builders, and web agencies
    is_vendor = any(part in VENDOR_PLATFORM_HANDLES for part in clean_parts)
    is_agency = any(
        kw in part or any(kw in tok for tok in full_path_tokens)
        for part in clean_parts
        for kw in VENDOR_AGENCY_KEYWORDS
    )
    is_admin = any(part in {"mycompany", "verification", "admin", "login", "sharer", "share", "intent", "plugins", "dialog"} for part in clean_parts)

    if is_vendor or is_agency or is_admin:
        vendor_match = next((part for part in clean_parts if part in VENDOR_PLATFORM_HANDLES), None) or "vendor_or_agency"
        return {
            **link,
            "identity_score": 0.0,
            "publishable": False,
            "matched_tokens": [],
            "rejection_category": "vendor_or_agency_handle",
            "reason": f"Vendor, CMS, hosting, agency, or theme handle '{vendor_match}' is not owned by target company",
            "method": "deterministic_exact_entity_ownership_v1",
        }

    # 2. Check for exact organisation number in handle or URL query
    org_digits = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    found_orgs = [o for o in re.findall(r"\b\d{9}\b", url) if is_valid_org_mod11(o)]
    parent_org = canonicalize_org_number(profile.get("overordnetEnhet") or profile.get("parent_organisation"))

    if found_orgs:
        if org_digits and org_digits in found_orgs:
            return {
                **link,
                "identity_score": 1.0,
                "publishable": True,
                "matched_tokens": [org_digits],
                "reason": "Exact organisation number appears in social URL",
                "method": "deterministic_exact_entity_ownership_v1",
            }
        elif parent_org and parent_org in found_orgs:
            return {
                **link,
                "identity_score": 0.2,
                "publishable": False,
                "matched_tokens": [],
                "rejection_category": "parent_attribution",
                "reason": f"parent_attribution: Social URL cites parent organisation number {parent_org}, not subsidiary {org_digits}",
                "method": "deterministic_exact_entity_ownership_v1",
            }
        else:
            return {
                **link,
                "identity_score": 0.0,
                "publishable": False,
                "matched_tokens": [],
                "rejection_category": "wrong_company_attribution",
                "reason": f"wrong_company_attribution: Social URL cites conflicting organisation number {found_orgs[0]}",
                "method": "deterministic_exact_entity_ownership_v1",
            }

    # 3. Check exact legal name tokens
    core = _tokens(profile.get("name"))
    distinctive = [t for t in core if t not in GENERIC_NAME_STOPWORDS and len(t) >= 3]
    core_compact = "".join(core)
    matched = [token for token in core if token in handle_compact]
    matched_distinctive = [token for token in distinctive if token in handle_compact]

    # Non-negotiable: Parent/group profiles must not be attributed to subsidiaries
    geo_in_name = set(core).intersection(GEOGRAPHIC_DISCRIMINATORS)
    if geo_in_name and not any(g in handle_compact for g in geo_in_name):
        return {
            **link,
            "identity_score": 0.2,
            "publishable": False,
            "matched_tokens": matched,
            "rejection_category": "parent_attribution",
            "reason": f"parent_attribution: Social URL handle '{handle_text}' lacks entity geographic identifier ({', '.join(sorted(geo_in_name))}) distinguishing the Norwegian subsidiary from parent brand",
            "method": "deterministic_exact_entity_ownership_v1",
        }

    # Non-negotiable: Do NOT broadly accept name substring matches
    # A handle must contain the distinctive entity token(s), not merely generic words like 'design' or 'as'
    if core_compact and core_compact in handle_compact:
        score = 0.98
        publishable = True
        reason = "normalized legal-name sequence appears in the social handle"
    elif distinctive and len(set(matched_distinctive)) == len(set(distinctive)):
        score = 0.95
        publishable = True
        reason = "all distinctive legal-name tokens appear in the social handle"
    elif len(distinctive) == 1 and matched_distinctive and (len(distinctive[0]) >= 4 or handle_compact == distinctive[0]):
        score = 0.92
        publishable = True
        reason = "single distinctive legal-name token appears in the social handle"
    elif len(distinctive) >= 2 and len(set(matched_distinctive)) >= 2 and len(set(matched_distinctive)) / len(set(distinctive)) >= 0.75:
        score = 0.90
        publishable = True
        reason = "most distinctive legal-name tokens appear in the social handle"
    else:
        score = 0.2
        publishable = False
        if not distinctive:
            reason = "company legal name consists solely of generic terms; independent organisation number is required to claim social handle"
        elif not matched_distinctive:
            reason = f"social handle '{handle_text}' lacks distinctive name tokens for '{profile.get('name')}'"
        else:
            reason = "social handle lacks sufficient exact-entity distinctive token coverage"

    return {
        **link,
        "identity_score": score,
        "publishable": publishable,
        "matched_tokens": matched,
        "reason": reason,
        "method": "deterministic_exact_entity_ownership_v1",
    }


def apply_website_identity_gate(profile: dict[str, Any], website: dict[str, Any]) -> dict[str, Any]:
    if website.get("status") != "available":
        return {"website": website, "assessment": None, "quarantined_social_links": 0}
    temporary_profile = {**profile, "evidence": {**profile.get("evidence", {}), "website": website}}
    value = website.get("value") or {}
    assessment = assess_website_identity(temporary_profile)
    value["identity_assessment"] = assessment
    website["identity_assessment"] = assessment
    original = list(value.get("discovered_social_links") or value.get("social_links") or [])
    value["discovered_social_links"] = original
    social_assessments = [assess_social_identity(profile, link) for link in original]
    value["social_link_assessments"] = social_assessments
    value["social_links"] = [
        {"platform": item["platform"], "url": item["url"]}
        for item in social_assessments
        if assessment["publishable"] and item["publishable"]
    ]
    value["quarantined_social_links"] = [
        {"platform": item["platform"], "url": item["url"], "reason": item.get("reason", "Identity rejected")}
        for item in social_assessments
        if not (assessment["publishable"] and item["publishable"])
    ]
    website["value"] = value
    if not assessment.get("publishable"):
        website["status"] = "not_found"
        website["identity_rejected"] = True
        website["rejection_status"] = assessment.get("status")
        website["rejection_reason"] = "; ".join(assessment.get("reasons", []))
        website["note"] = f"Identity gate rejected: {'; '.join(assessment.get('reasons', []))}"
    return {
        "website": website,
        "assessment": assessment,
        "quarantined_social_links": len(original) - len(value["social_links"]),
    }
