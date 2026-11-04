from __future__ import annotations

import re
import unicodedata
import urllib.parse
from typing import Any

from .website import normalize_homepage


BLOCKED_DISCOVERY_HOSTS = {
    "proff.no", "purehelp.no", "1881.no", "gulesider.no", "firmalisten.no", "companywall.no",
    "firmadatabasen.no", "sokfirma.no", "yra.no", "northdata.com", "nor47business.com",
    "linkedin.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "youtube.com", "tiktok.com",
}
GENERIC_NAME_TOKENS = {"as", "asa", "ans", "da", "enk", "sa", "nuf", "company", "norge", "norway", "gruppen", "group"}


def build_company_search_query(profile: dict[str, Any]) -> str:
    return build_company_search_queries(profile)[0]


def build_company_search_queries(profile: dict[str, Any]) -> list[str]:
    name = " ".join(str(profile.get("name") or "").split())
    org = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    municipality = " ".join(str(profile.get("municipality") or "").split())
    if not name or not org:
        raise ValueError("Company discovery requires a legal name and organisation number")
    queries = [
        f'"{name}" {org}' + (f" {municipality}" if municipality else "") ,
        f'"{name}" "{org}" Norway official website',
        f'"{name}"' + (f" {municipality}" if municipality else " Norway") + " official website",
    ]
    return list(dict.fromkeys(queries))


def parse_brave_web_results(payload: dict[str, Any], *, query: str) -> list[dict[str, Any]]:
    results = (payload.get("web") or {}).get("results") or []
    parsed = []
    for rank, result in enumerate(results, start=1):
        if not isinstance(result, dict) or not result.get("url"):
            continue
        parsed.append({
            "url": result.get("url"),
            "title": result.get("title") or "",
            "snippet": result.get("description") or "",
            "rank": rank,
            "provider": "brave_search_api",
            "query": query,
            "page_age": result.get("page_age") or result.get("age"),
            "result_kind": result.get("result_kind"),
        })
    return parsed


def _tokens(value: Any) -> list[str]:
    text = str(value or "").translate(str.maketrans({"ø": "o", "å": "a", "æ": "ae", "Ø": "O", "Å": "A", "Æ": "AE"}))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()
    return [token for token in re.findall(r"[a-z0-9]+", text) if len(token) > 1]


def score_search_candidate(profile: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_homepage(result.get("url"))
    if not normalized:
        return {"status": "rejected", "score": 0.0, "publishable_candidate": False, "reasons": ["invalid HTTP(S) candidate URL"]}
    host = (urllib.parse.urlparse(normalized).hostname or "").casefold().removeprefix("www.")
    if any(host == blocked or host.endswith("." + blocked) for blocked in BLOCKED_DISCOVERY_HOSTS):
        return {"status": "rejected", "score": 0.0, "publishable_candidate": False, "url": normalized, "host": host, "reasons": ["directory, aggregator, or social host is not a company website candidate"]}

    name_tokens = [token for token in _tokens(profile.get("name")) if token not in GENERIC_NAME_TOKENS]
    title_tokens = _tokens(result.get("title"))
    snippet_tokens = _tokens(result.get("snippet"))
    evidence_tokens = set(title_tokens + snippet_tokens + _tokens(host))
    host_compact = "".join(_tokens(host))
    name_compact = "".join(name_tokens)
    org = re.sub(r"\D", "", str(profile.get("organisation_number") or ""))
    evidence_digits = re.sub(r"\D", "", f"{result.get('title', '')} {result.get('snippet', '')}")
    municipality_tokens = set(_tokens(profile.get("municipality")))

    # Reject candidates where snippet explicitly cites a DIFFERENT 9-digit Norwegian org number
    found_orgs = re.findall(r"\b\d{9}\b", f"{result.get('title', '')} {result.get('snippet', '')}")
    if found_orgs and all(cand != org for cand in found_orgs):
        return {
            "status": "rejected",
            "score": 0.0,
            "publishable_candidate": False,
            "url": normalized,
            "host": host,
            "reasons": ["conflicting organisation number in search evidence"],
        }

    org_match = bool(org and org in evidence_digits)
    all_name_tokens = bool(name_tokens and set(name_tokens).issubset(evidence_tokens))
    all_name_tokens_in_title = bool(name_tokens and set(name_tokens).issubset(set(title_tokens)))
    name_in_host = bool(name_compact and name_compact in host_compact)
    municipality_match = bool(municipality_tokens and municipality_tokens <= set(snippet_tokens))
    score = 0.0
    reasons = []
    if org_match:
        score += 0.75
        reasons.append("exact organisation number appears in result evidence")
    if all_name_tokens_in_title:
        score += 0.45
        reasons.append("all distinctive legal-name tokens appear in the result title")
    elif all_name_tokens:
        score += 0.25
        reasons.append("all distinctive legal-name tokens appear across result evidence")
    if name_in_host:
        score += 0.3
        reasons.append("normalized legal name appears in candidate hostname")
    if municipality_match:
        score += 0.1
        reasons.append("registry municipality appears in result snippet")
    score = min(score, 1.0)
    path = urllib.parse.urlparse(normalized).path.casefold()
    is_directory_path = any(
        path.startswith(prefix)
        for prefix in ("/selskap/", "/bedrift/", "/foretak/", "/firma/", "/enhet/", "/enheter/", "/virksomhet/", "/company/", "/companies/")
    )
    if is_directory_path:
        return {
            "status": "rejected",
            "score": 0.0,
            "publishable_candidate": False,
            "url": normalized,
            "host": host,
            "reasons": ["directory path structure indicates company directory, not company website"],
        }

    # Registry/directory pages routinely reproduce both the legal name and org
    # number. A candidate must therefore also have distinctive company name
    # tokens in its hostname before it is worth crawling as a company-owned website.
    name_in_host = bool(name_compact and name_compact in host_compact or any(len(t) >= 4 and t in host_compact for t in name_tokens))
    publishable_candidate = score >= 0.75 and name_in_host and (org_match or all_name_tokens_in_title)
    return {
        "status": "accepted_for_crawl" if publishable_candidate else "review" if score >= 0.6 else "rejected",
        "score": score,
        "publishable_candidate": publishable_candidate,
        "url": normalized,
        "host": host,
        "rank": result.get("rank"),
        "provider": result.get("provider"),
        "query": result.get("query"),
        "reasons": reasons or ["insufficient exact-entity evidence"],
        "method": "deterministic_search_candidate_identity_v1",
    }


def choose_search_candidate(profile: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    assessed = [score_search_candidate(profile, result) for result in results]
    assessed.sort(key=lambda item: (-item.get("score", 0.0), item.get("rank") or 10_000, item.get("url") or ""))
    accepted = [item for item in assessed if item.get("publishable_candidate")]
    return {
        "selected": accepted[0] if accepted else None,
        "candidates": assessed,
        "abstained": not accepted,
        "policy": "A search result is only a crawl candidate. Publication still requires fetched-page exact-entity verification.",
    }


def compare_registry_and_search_candidates(
    profile: dict[str, Any],
    registry_website: dict[str, Any] | None,
    search_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare a registry website candidate with independent search candidates.

    Guarantees:
    - Never attributes parent/brand or wrong company websites to a subsidiary.
    - Corroborates when registry and independent search candidate agree.
    - Resolves conflict in favor of verified company-specific candidate over parent candidate.
    - Marks uncertain / ambiguous when sources conflict without decisive proof.
    """
    from .identity import assess_website_identity

    reg_url = ""
    reg_assessment: dict[str, Any] | None = None
    if registry_website:
        reg_val = registry_website.get("value") or {}
        reg_url = str(reg_val.get("final_url") or registry_website.get("source_url") or profile.get("website") or "").strip()
        reg_assessment = reg_val.get("identity_assessment")
        if not reg_assessment and reg_url:
            temp_p = {**profile, "evidence": {**profile.get("evidence", {}), "website": registry_website}}
            reg_assessment = assess_website_identity(temp_p)

    search_decision = choose_search_candidate(profile, search_candidates) if search_candidates else {"selected": None, "candidates": []}
    selected_search = search_decision.get("selected")
    search_url = str(selected_search.get("url") or "").strip() if selected_search else ""

    reg_host = (urllib.parse.urlparse(reg_url).hostname or "").lower().removeprefix("www.")
    search_host = (urllib.parse.urlparse(search_url).hostname or "").lower().removeprefix("www.")

    # If independent search returned a result on the registry domain, consider it for corroboration
    if reg_host and search_candidates and not search_host:
        matching_cand = next(
            (c for c in search_candidates if (urllib.parse.urlparse(str(c.get("url") or "")).hostname or "").lower().removeprefix("www.") == reg_host),
            None,
        )
        if matching_cand:
            selected_search = matching_cand
            search_url = str(matching_cand.get("url") or "").strip()
            search_host = reg_host

    reg_publishable = bool(reg_assessment and reg_assessment.get("publishable") and registry_website and registry_website.get("status") == "available")
    search_publishable = bool(selected_search and (selected_search.get("publishable_candidate") or search_host == reg_host))

    # Case 1: Both candidates exist and agree on domain
    if reg_host and search_host and (reg_host == search_host or reg_host.endswith("." + search_host) or search_host.endswith("." + reg_host)):
        if reg_publishable:
            return {
                "verdict": "corroborated",
                "status": "available",
                "publishable": True,
                "selected_url": reg_url,
                "confidence": 0.99,
                "comparison_reason": f"Registry website and independent search candidate independently agree on domain '{reg_host}'",
                "registry_assessment": reg_assessment,
                "search_candidate": selected_search,
                "quarantined_urls": [],
            }
        else:
            return {
                "verdict": "corroborated_but_unverified",
                "status": "not_found",
                "publishable": False,
                "selected_url": None,
                "confidence": 0.0,
                "comparison_reason": f"Registry domain '{reg_host}' and search candidate agree but failed exact-entity identity verification ({reg_assessment.get('status') if reg_assessment else 'unverified'})",
                "registry_assessment": reg_assessment,
                "search_candidate": selected_search,
                "quarantined_urls": [reg_url] if reg_url else [],
            }

    # Case 2: Registry is rejected / parent / wrong-company, but search candidate is company-specific
    if (not reg_publishable) and search_publishable:
        rej_desc = reg_assessment.get("status") if reg_assessment else "unverified"
        rej_reasons = "; ".join(reg_assessment.get("reasons", [])) if reg_assessment else "lacks exact-entity proof"
        return {
            "verdict": "search_candidate_preferred",
            "status": "pending_crawl",
            "publishable": True,
            "selected_url": search_url,
            "confidence": 0.92,
            "comparison_reason": f"Registry website '{reg_url}' rejected ({rej_desc}: {rej_reasons}); independent search candidate '{search_url}' preferred for company-specific attribution",
            "registry_assessment": reg_assessment,
            "search_candidate": selected_search,
            "quarantined_urls": [reg_url] if reg_url else [],
        }

    # Case 3: Both are publishable but domains conflict!
    if reg_publishable and search_publishable and reg_host != search_host:
        return {
            "verdict": "unsure_conflict",
            "status": "ambiguous",
            "publishable": False,
            "selected_url": None,
            "confidence": 0.0,
            "comparison_reason": f"Registry domain '{reg_host}' conflicts with search candidate domain '{search_host}' without conclusive exact-entity corroboration",
            "registry_assessment": reg_assessment,
            "search_candidate": selected_search,
            "quarantined_urls": [reg_url, search_url],
        }

    # Case 4: Registry is confirmed exact match (and search candidate is not conflicting or does not exist)
    if reg_publishable:
        return {
            "verdict": "registry_confirmed",
            "status": "available",
            "publishable": True,
            "selected_url": reg_url,
            "confidence": 0.98,
            "comparison_reason": f"Registry website '{reg_url}' verified with exact company identity evidence",
            "registry_assessment": reg_assessment,
            "search_candidate": selected_search,
            "quarantined_urls": [],
        }

    # Case 5: Registry rejected and no valid search candidate
    if reg_url and not reg_publishable and not search_publishable:
        rej_desc = reg_assessment.get("status") if reg_assessment else "unverified"
        rej_reasons = "; ".join(reg_assessment.get("reasons", [])) if reg_assessment else "lacks exact-entity proof"
        return {
            "verdict": "registry_rejected_no_search_candidate",
            "status": "not_found",
            "publishable": False,
            "selected_url": None,
            "confidence": 0.0,
            "comparison_reason": f"Registry website '{reg_url}' rejected ({rej_desc}: {rej_reasons}) and no publishable independent search candidate discovered",
            "registry_assessment": reg_assessment,
            "search_candidate": selected_search,
            "quarantined_urls": [reg_url],
        }

    # Case 5: Conflicting candidates without conclusive proof
    if reg_host and search_host and reg_host != search_host:
        return {
            "verdict": "unsure_conflict",
            "status": "ambiguous",
            "publishable": False,
            "selected_url": None,
            "confidence": 0.0,
            "comparison_reason": f"Registry domain '{reg_host}' conflicts with search candidate domain '{search_host}' without conclusive exact-entity corroboration",
            "registry_assessment": reg_assessment,
            "search_candidate": selected_search,
            "quarantined_urls": [reg_url, search_url],
        }

    # Case 6: Neither exists
    return {
        "verdict": "no_candidates",
        "status": "not_found",
        "publishable": False,
        "selected_url": None,
        "confidence": 0.0,
        "comparison_reason": "No registry website and no search candidate found",
        "registry_assessment": None,
        "search_candidate": None,
        "quarantined_urls": [],
    }
