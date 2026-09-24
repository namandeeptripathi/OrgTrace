"""Stage 18: Identity Accuracy Evaluation.

Evaluates company identity resolution against authoritative registry expectations:
- Exact organisation number match
- Company name matching (exact, normalized, suffix variation, conflict)
- Website / domain grounding
- Jurisdiction checks
- Grounded classification: exact_match, probable_match, ambiguous, wrong_company, not_found.
"""

from __future__ import annotations

from typing import Any
import urllib.parse

from ..identity_engine import canonicalize_org_number, normalize_legal_name
from ..identity_hardening import (
    NameMatchStatus,
    compare_company_names,
    compare_org_numbers,
    canonicalize_domain_hostname,
)
from .models import IdentityEvaluation, IdentityStatus


def evaluate_company_identity(
    expected_org_number: str | None,
    expected_name: str | None,
    observed_profile: dict[str, Any] | None,
    expected_website: str | None = None,
) -> IdentityEvaluation:
    """Evaluate whether the observed agent output matches the intended target company."""
    notes: list[str] = []

    if observed_profile is None or not observed_profile:
        # If neither org number nor name was expected (e.g. non-target / ambiguous query that should abstain)
        if expected_org_number is None and expected_name is None:
            return IdentityEvaluation(
                status=IdentityStatus.EXACT_MATCH,
                expected_org_number=None,
                observed_org_number=None,
                name_match=True,
                website_match=True,
                accuracy=1.0,
                notes=["Correctly abstained / not found for ungrounded or non-target query."],
            )
        return IdentityEvaluation(
            status=IdentityStatus.NOT_FOUND,
            expected_org_number=expected_org_number,
            observed_org_number=None,
            name_match=False,
            website_match=False,
            accuracy=0.0,
            notes=["No company profile was produced by the agent."],
        )

    observed_org = observed_profile.get("organisation_number")
    if observed_org:
        observed_org = canonicalize_org_number(str(observed_org))

    observed_name = observed_profile.get("name") or observed_profile.get("company_name")
    observed_website = observed_profile.get("website")

    # If the case expected an abstention / rejection (e.g., non-target or ambiguous name)
    if expected_org_number is None and expected_name is None:
        verdict = observed_profile.get("verdict_status") or observed_profile.get("status")
        if verdict in {"rejected", "not_found", "ambiguous"}:
            status = IdentityStatus.EXACT_MATCH
            accuracy = 1.0
            notes.append(f"Correctly classified as {verdict}.")
        else:
            status = IdentityStatus.WRONG_COMPANY
            accuracy = 0.0
            notes.append("Emitted entity profile for a non-target query.")
        return IdentityEvaluation(
            status=status,
            expected_org_number=None,
            observed_org_number=observed_org,
            name_match=(expected_name is None and observed_name is None),
            website_match=True,
            accuracy=accuracy,
            notes=notes,
        )

    # 1. Check Organisation Number
    canonical_expected_org = canonicalize_org_number(str(expected_org_number)) if expected_org_number else None
    org_match = False
    org_mismatch = False

    if canonical_expected_org and observed_org:
        org_cmp = compare_org_numbers(canonical_expected_org, observed_org)
        org_match = org_cmp.is_match
        org_mismatch = not org_cmp.is_match
        if org_mismatch:
            notes.append(f"Org number mismatch: expected {canonical_expected_org}, got {observed_org}")
    elif canonical_expected_org and not observed_org:
        notes.append("Missing organisation number in agent output.")

    # 2. Check Name Matching
    name_match = False
    name_status = None
    if expected_name and observed_name:
        name_cmp = compare_company_names(expected_name, observed_name)
        name_status = name_cmp.name_match_status
        name_match = name_cmp.is_acceptable_match
        if not name_match:
            notes.append(f"Name divergence ({name_status.value}): expected {expected_name!r}, got {observed_name!r}")
    elif not expected_name and observed_name:
        name_match = True

    # 3. Check Website / Domain Matching
    website_match = True
    if expected_website and observed_website:
        exp_dom = canonicalize_domain_hostname(expected_website)
        obs_dom = canonicalize_domain_hostname(observed_website)
        website_match = (exp_dom == obs_dom) or (exp_dom in obs_dom) or (obs_dom in exp_dom)
        if not website_match:
            notes.append(f"Website domain divergence: expected {expected_website}, got {observed_website}")
    elif expected_website and not observed_website:
        # Website wasn't retrieved, but might not be a total identity failure
        notes.append("Expected website was not retrieved.")

    # 4. Identity Classification
    if org_mismatch:
        status = IdentityStatus.WRONG_COMPANY
        accuracy = 0.0
    elif org_match:
        if name_match:
            status = IdentityStatus.EXACT_MATCH
            accuracy = 1.0
        else:
            status = IdentityStatus.PROBABLE_MATCH
            accuracy = 1.0
    elif not org_match and name_match:
        # Org number not matched/missing, but name matches
        if observed_profile.get("verdict_status") == "ambiguous":
            status = IdentityStatus.AMBIGUOUS
            accuracy = 0.0
        else:
            status = IdentityStatus.PROBABLE_MATCH
            accuracy = 0.8
    elif not observed_org and not observed_name:
        status = IdentityStatus.NOT_FOUND
        accuracy = 0.0
    else:
        status = IdentityStatus.WRONG_COMPANY
        accuracy = 0.0

    return IdentityEvaluation(
        status=status,
        expected_org_number=canonical_expected_org,
        observed_org_number=observed_org,
        name_match=name_match,
        website_match=website_match,
        accuracy=accuracy,
        notes=notes,
    )
