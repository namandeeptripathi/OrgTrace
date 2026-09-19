from __future__ import annotations

import re
import unicodedata
import urllib.parse
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

# ============================================================================
# 1. ORG NUMBER CANONICALIZATION & MODULO 11 VALIDATION
# ============================================================================

MOD11_WEIGHTS = (3, 2, 7, 6, 5, 4, 3, 2)

COMMON_ORG_PREFIXES = (
    "organisasjonsnummer",
    "org.nr.",
    "org.nr",
    "orgnr",
    "org nr",
    "foretaksregisteret",
    "no",
)

COMMON_ORG_SUFFIXES = (
    "foretaksregisteret",
    "mva",
    "vat",
)


def compute_mod11_check_digit(first_8_digits: str) -> int | None:
    """Compute the Norwegian Modulo 11 control digit for the first 8 digits.

    Returns the integer check digit (0-9), or None if the check digit would be 10 (invalid).
    """
    if len(first_8_digits) != 8 or not first_8_digits.isdigit():
        return None
    total = sum(int(digit) * weight for digit, weight in zip(first_8_digits, MOD11_WEIGHTS))
    remainder = total % 11
    if remainder == 0:
        return 0
    control = 11 - remainder
    if control == 10:
        return None  # Disallowed in Norwegian Modulo 11
    return control


def is_valid_org_mod11(org_9_digits: str) -> bool:
    """Verify if a 9-digit string satisfies the Norwegian Modulo 11 check digit."""
    if len(org_9_digits) != 9 or not org_9_digits.isdigit():
        return False
    expected = compute_mod11_check_digit(org_9_digits[:8])
    if expected is None:
        return False
    return int(org_9_digits[8]) == expected


@dataclass(frozen=True)
class OrgNumberValidation:
    raw: Any
    canonical: str | None
    is_valid: bool
    has_valid_checksum: bool
    error: str | None = None
    detected_prefix: str | None = None
    detected_suffix: str | None = None
    formatting_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonicalize_org_number(value: Any, *, verify_checksum: bool = False) -> str | None:
    """Canonicalize any representation of a Norwegian organisation number to 9 digits.

    Returns the 9-digit string if valid, or None if malformed/invalid.
    """
    res = validate_org_number(value, verify_checksum=verify_checksum)
    return res.canonical if res.is_valid else None


def validate_org_number(value: Any, *, verify_checksum: bool = False) -> OrgNumberValidation:
    """Validate and canonicalize a Norwegian organisation number with full diagnostics."""
    if value is None:
        return OrgNumberValidation(raw=value, canonical=None, is_valid=False, has_valid_checksum=False, error="Value is None")

    raw_str = str(value).strip()
    if not raw_str:
        return OrgNumberValidation(raw=value, canonical=None, is_valid=False, has_valid_checksum=False, error="Value is empty")

    notes: list[str] = []
    detected_prefix: str | None = None
    detected_suffix: str | None = None

    working = raw_str

    # Detect and strip known textual prefixes
    lowered = working.casefold()
    for prefix in COMMON_ORG_PREFIXES:
        pattern = rf"^\s*{re.escape(prefix)}[\s:\-\.]*"
        match = re.match(pattern, lowered)
        if match:
            matched_len = match.end()
            detected_prefix = working[:matched_len].strip()
            notes.append(f"stripped_prefix:{detected_prefix}")
            working = working[matched_len:].strip()
            lowered = working.casefold()
            break

    # Detect and strip known textual suffixes
    for suffix in COMMON_ORG_SUFFIXES:
        pattern = rf"[\s:\-\.]*{re.escape(suffix)}\s*$"
        match = re.search(pattern, lowered)
        if match:
            matched_start = match.start()
            detected_suffix = working[matched_start:].strip()
            notes.append(f"stripped_suffix:{detected_suffix}")
            working = working[:matched_start].strip()
            lowered = working.casefold()
            break

    # Record formatting features
    if " " in working:
        notes.append("contains_spaces")
    if "." in working:
        notes.append("contains_dots")
    if "-" in working:
        notes.append("contains_dashes")

    # Extract digits
    digits = re.sub(r"\D", "", working)

    # Check for extraneous characters that are not formatting
    non_digit_non_format = re.sub(r"[\d\s\.\-]", "", working)
    if non_digit_non_format:
        return OrgNumberValidation(
            raw=value,
            canonical=None,
            is_valid=False,
            has_valid_checksum=False,
            error=f"Contains invalid characters: {non_digit_non_format!r}",
            detected_prefix=detected_prefix,
            detected_suffix=detected_suffix,
            formatting_notes=notes,
        )

    if len(digits) != 9:
        return OrgNumberValidation(
            raw=value,
            canonical=None,
            is_valid=False,
            has_valid_checksum=False,
            error=f"Invalid length: expected 9 digits, got {len(digits)} ({digits})",
            detected_prefix=detected_prefix,
            detected_suffix=detected_suffix,
            formatting_notes=notes,
        )

    has_valid_checksum = is_valid_org_mod11(digits)
    if verify_checksum and not has_valid_checksum:
        return OrgNumberValidation(
            raw=value,
            canonical=digits,
            is_valid=False,
            has_valid_checksum=False,
            error=f"Invalid Modulo 11 check digit for {digits}",
            detected_prefix=detected_prefix,
            detected_suffix=detected_suffix,
            formatting_notes=notes,
        )

    return OrgNumberValidation(
        raw=value,
        canonical=digits,
        is_valid=True,
        has_valid_checksum=has_valid_checksum,
        detected_prefix=detected_prefix,
        detected_suffix=detected_suffix,
        formatting_notes=notes,
    )


# ============================================================================
# 2. LEGAL NAME NORMALIZATION & MATCHING
# ============================================================================

LEGAL_FORM_SUFFIXES: dict[str, str] = {
    # Canonical form -> normalized key
    "as": "AS",
    "a/s": "AS",
    "a.s.": "AS",
    "a.s": "AS",
    "asa": "ASA",
    "a/s/a": "ASA",
    "a.s.a.": "ASA",
    "a.s.a": "ASA",
    "enk": "ENK",
    "ans": "ANS",
    "da": "DA",
    "d.a.": "DA",
    "nuf": "NUF",
    "sa": "SA",
    "s.a.": "SA",
    "ks": "KS",
    "k.s.": "KS",
    "iks": "IKS",
    "sti": "STI",
    "stiftelse": "STI",
    "stiftelsen": "STI",
    "ba": "BA",
    "brl": "BRL",
    "bbl": "BBL",
    "sf": "SF",
    "kf": "KF",
    "k.f.": "KF",
    "fkf": "FKF",
    "ab": "AB",
    "ltd": "LTD",
    "limited": "LTD",
    "inc": "INC",
    "corp": "CORP",
    "gmbh": "GMBH",
    "plc": "PLC",
}

GENERIC_DESCRIPTORS = {
    "holding", "group", "gruppen", "norge", "norway", "invest", "eiendom",
    "nordic", "scandinavia", "international", "holding as", "holding asa",
}


def normalize_legal_name(name: str | None) -> str:
    """Normalize a legal company name for robust comparison.

    Performs Unicode decomposition (NFKD), maps Norwegian letters (æ->ae, ø->o, å->a),
    removes punctuation, and standardizes whitespace.
    """
    text = str(name or "").strip()
    if not text:
        return ""
    # Map Norwegian characters
    text = text.translate(str.maketrans({
        "ø": "o", "Ø": "O",
        "å": "a", "Å": "A",
        "æ": "ae", "Æ": "AE",
    }))
    # Normalize NFKD to strip combining accents (é, ü, etc.)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    # Normalize punctuation and symbols to spaces
    text = re.sub(r"[^\w\s]", " ", text)
    # Standardize whitespace and lowercase
    return " ".join(text.casefold().split())


def _name_tokens(name: str | None) -> list[str]:
    """Tokenize a name, removing standard legal form suffixes and single characters."""
    normalized = normalize_legal_name(name)
    tokens = [t for t in normalized.split() if len(t) > 1]
    return [t for t in tokens if t not in LEGAL_FORM_SUFFIXES]


def extract_legal_form(name: str | None) -> tuple[str, str | None]:
    """Extract the base name and standard legal form suffix from a company name.

    Returns (core_name, canonical_legal_form or None).
    """
    raw = str(name or "").strip()
    if not raw:
        return "", None

    # Check for trailing legal form suffix
    # We test suffixes by sorting by descending length
    clean = re.sub(r"[,\.]+$", "", raw).strip()
    for suffix, canonical in sorted(LEGAL_FORM_SUFFIXES.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = rf"(?:^|\s+|[,/\-])({re.escape(suffix)})\s*$"
        if re.search(pattern, clean, re.IGNORECASE):
            core = re.sub(pattern, "", clean, flags=re.IGNORECASE).strip()
            return core, canonical

    return clean, None


class LegalNameMatchCategory(str, Enum):
    EXACT = "exact"
    EXACT_NORMALIZED = "exact_normalized"
    LEGAL_SUFFIX_VARIATION = "legal_suffix_variation"
    LEGAL_SUFFIX_OMITTED = "legal_suffix_omitted"
    LEGAL_FORM_CONFLICT = "legal_form_conflict"
    PARTIAL_OVERLAP = "partial_overlap"
    CONFLICTING = "conflicting"


@dataclass(frozen=True)
class LegalNameMatch:
    target_name: str
    candidate_name: str
    category: LegalNameMatchCategory
    is_match: bool
    target_core: str
    candidate_core: str
    target_form: str | None
    candidate_form: str | None
    tokens_target: list[str]
    tokens_candidate: list[str]
    matched_tokens: list[str]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["category"] = self.category.value
        return data


def match_legal_names(target_name: str | None, candidate_name: str | None) -> LegalNameMatch:
    """Compare two company legal names deterministically without blind fuzzy matching."""
    t_raw = str(target_name or "").strip()
    c_raw = str(candidate_name or "").strip()

    if not t_raw or not c_raw:
        return LegalNameMatch(
            target_name=t_raw,
            candidate_name=c_raw,
            category=LegalNameMatchCategory.CONFLICTING,
            is_match=False,
            target_core="",
            candidate_core="",
            target_form=None,
            candidate_form=None,
            tokens_target=[],
            tokens_candidate=[],
            matched_tokens=[],
            reasons=["One or both legal names are empty"],
        )

    # 1. Exact string match
    if t_raw == c_raw:
        core, form = extract_legal_form(t_raw)
        tokens = _name_tokens(core)
        return LegalNameMatch(
            target_name=t_raw,
            candidate_name=c_raw,
            category=LegalNameMatchCategory.EXACT,
            is_match=True,
            target_core=core,
            candidate_core=core,
            target_form=form,
            candidate_form=form,
            tokens_target=tokens,
            tokens_candidate=tokens,
            matched_tokens=tokens,
            reasons=["Exact identical legal name strings"],
        )

    # 2. Normalized match
    t_norm = normalize_legal_name(t_raw)
    c_norm = normalize_legal_name(c_raw)

    t_core, t_form = extract_legal_form(t_raw)
    c_core, c_form = extract_legal_form(c_raw)

    t_core_norm = normalize_legal_name(t_core)
    c_core_norm = normalize_legal_name(c_core)

    t_tokens = _name_tokens(t_core)
    c_tokens = _name_tokens(c_core)
    matched_tokens = sorted(set(t_tokens) & set(c_tokens))

    # Check for identical normalized strings (same form or equivalent form)
    if t_norm == c_norm:
        return LegalNameMatch(
            target_name=t_raw,
            candidate_name=c_raw,
            category=LegalNameMatchCategory.EXACT_NORMALIZED,
            is_match=True,
            target_core=t_core,
            candidate_core=c_core,
            target_form=t_form,
            candidate_form=c_form,
            tokens_target=t_tokens,
            tokens_candidate=c_tokens,
            matched_tokens=matched_tokens,
            reasons=["Exact match after case, whitespace, punctuation, and Unicode normalization"],
        )

    # Check core name vs legal form
    if t_core_norm == c_core_norm:
        if t_form == c_form:
            return LegalNameMatch(
                target_name=t_raw,
                candidate_name=c_raw,
                category=LegalNameMatchCategory.EXACT_NORMALIZED,
                is_match=True,
                target_core=t_core,
                candidate_core=c_core,
                target_form=t_form,
                candidate_form=c_form,
                tokens_target=t_tokens,
                tokens_candidate=c_tokens,
                matched_tokens=matched_tokens,
                reasons=["Core legal name matches with equivalent legal form"],
            )
        elif t_form is not None and c_form is not None:
            # Both have different legal forms (e.g. AS vs ASA or AS vs ENK)
            return LegalNameMatch(
                target_name=t_raw,
                candidate_name=c_raw,
                category=LegalNameMatchCategory.LEGAL_FORM_CONFLICT,
                is_match=False,
                target_core=t_core,
                candidate_core=c_core,
                target_form=t_form,
                candidate_form=c_form,
                tokens_target=t_tokens,
                tokens_candidate=c_tokens,
                matched_tokens=matched_tokens,
                reasons=[f"Legal form conflict: target has {t_form}, candidate has {c_form}"],
            )
        else:
            # One side omitted legal form
            omitted_which = "candidate" if c_form is None else "target"
            return LegalNameMatch(
                target_name=t_raw,
                candidate_name=c_raw,
                category=LegalNameMatchCategory.LEGAL_SUFFIX_OMITTED,
                is_match=True,
                target_core=t_core,
                candidate_core=c_core,
                target_form=t_form,
                candidate_form=c_form,
                tokens_target=t_tokens,
                tokens_candidate=c_tokens,
                matched_tokens=matched_tokens,
                reasons=[f"Core legal name matches exactly ({omitted_which} omitted legal form suffix)"],
            )

    # Core names differ: check token overlap vs conflict
    if set(t_tokens) == set(c_tokens) and t_tokens:
        if t_form != c_form and t_form is not None and c_form is not None:
            category = LegalNameMatchCategory.LEGAL_FORM_CONFLICT
            is_match = False
            reasons = [f"Distinctive tokens match, but legal forms conflict ({t_form} vs {c_form})"]
        else:
            category = LegalNameMatchCategory.EXACT_NORMALIZED
            is_match = True
            reasons = ["All distinctive core legal-name tokens match"]
        return LegalNameMatch(
            target_name=t_raw,
            candidate_name=c_raw,
            category=category,
            is_match=is_match,
            target_core=t_core,
            candidate_core=c_core,
            target_form=t_form,
            candidate_form=c_form,
            tokens_target=t_tokens,
            tokens_candidate=c_tokens,
            matched_tokens=matched_tokens,
            reasons=reasons,
        )

    # Distinctive tokens differ
    extra_in_c = set(c_tokens) - set(t_tokens)
    extra_in_t = set(t_tokens) - set(c_tokens)

    if matched_tokens and (extra_in_c or extra_in_t):
        return LegalNameMatch(
            target_name=t_raw,
            candidate_name=c_raw,
            category=LegalNameMatchCategory.PARTIAL_OVERLAP,
            is_match=False,
            target_core=t_core,
            candidate_core=c_core,
            target_form=t_form,
            candidate_form=c_form,
            tokens_target=t_tokens,
            tokens_candidate=c_tokens,
            matched_tokens=matched_tokens,
            reasons=[
                f"Partial token overlap ({len(matched_tokens)} shared tokens), "
                f"but distinctive tokens differ: target has {sorted(extra_in_t)}, candidate has {sorted(extra_in_c)}"
            ],
        )

    return LegalNameMatch(
        target_name=t_raw,
        candidate_name=c_raw,
        category=LegalNameMatchCategory.CONFLICTING,
        is_match=False,
        target_core=t_core,
        candidate_core=c_core,
        target_form=t_form,
        candidate_form=c_form,
        tokens_target=t_tokens,
        tokens_candidate=c_tokens,
        matched_tokens=[],
        reasons=["Legal names have no common distinctive tokens"],
    )


# ============================================================================
# 3. DOMAIN & ENTITY MATCHING
# ============================================================================

class DomainMatchCategory(str, Enum):
    EXACT = "exact"
    NORMALIZED = "normalized"
    RELATED_DERIVED = "related_derived"
    CONFLICTING = "conflicting"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class DomainMatch:
    target_domain: str | None
    candidate_domain: str | None
    category: DomainMatchCategory
    is_match: bool
    target_hostname: str | None
    candidate_hostname: str | None
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["category"] = self.category.value
        return data


def _extract_hostname(url_or_domain: str | None) -> str | None:
    """Extract clean lowercase hostname from URL or raw domain string."""
    val = str(url_or_domain or "").strip().lower()
    if not val:
        return None
    if not re.match(r"^https?://", val):
        val = "https://" + val
    try:
        parsed = urllib.parse.urlparse(val)
        host = parsed.hostname
        if host:
            return host.rstrip(".").removeprefix("www.")
    except Exception:
        pass
    return None


def _registered_domain_name(hostname: str | None) -> str | None:
    """Extract registered domain name (without TLD) for derivation comparison.

    e.g. 'equinor.com' -> 'equinor', 'sub.equinor.no' -> 'equinor'.
    """
    if not hostname:
        return None
    parts = hostname.split(".")
    if len(parts) >= 2:
        return parts[-2]
    return parts[0]


def match_domain_entity(
    target_url_or_domain: str | None,
    candidate_url_or_domain: str | None,
    *,
    target_name: str | None = None,
) -> DomainMatch:
    """Classify domain/entity matching into 5 distinct categories."""
    t_raw = str(target_url_or_domain or "").strip()
    c_raw = str(candidate_url_or_domain or "").strip()

    t_host = _extract_hostname(t_raw)
    c_host = _extract_hostname(c_raw)

    if not c_host:
        return DomainMatch(
            target_domain=t_raw or None,
            candidate_domain=c_raw or None,
            category=DomainMatchCategory.UNAVAILABLE,
            is_match=False,
            target_hostname=t_host,
            candidate_hostname=c_host,
            reasons=["Candidate domain is missing, empty, or unparseable"],
        )

    # If target domain is missing from BRREG, check if candidate domain is derived from target legal name
    if not t_host:
        name_tokens = _name_tokens(target_name) if target_name else []
        name_compact = "".join(name_tokens)
        c_compact = re.sub(r"[^a-z0-9]", "", c_host)
        c_reg = _registered_domain_name(c_host)
        is_name_derived = bool(name_compact and (name_compact in c_compact or (c_reg and c_reg in name_compact)))
        if is_name_derived:
            return DomainMatch(
                target_domain=t_raw or None,
                candidate_domain=c_raw,
                category=DomainMatchCategory.RELATED_DERIVED,
                is_match=True,
                target_hostname=None,
                candidate_hostname=c_host,
                reasons=[f"Candidate domain {c_host} is derived from target legal name tokens {name_tokens}"],
            )
        return DomainMatch(
            target_domain=t_raw or None,
            candidate_domain=c_raw,
            category=DomainMatchCategory.UNAVAILABLE,
            is_match=False,
            target_hostname=None,
            candidate_hostname=c_host,
            reasons=["Target domain is not registered in BRREG"],
        )

    # 1. Exact match
    if t_raw == c_raw:
        return DomainMatch(
            target_domain=t_raw,
            candidate_domain=c_raw,
            category=DomainMatchCategory.EXACT,
            is_match=True,
            target_hostname=t_host,
            candidate_hostname=c_host,
            reasons=["Exact identical domain / URL string"],
        )

    # 2. Normalized match (identical hostname after www. stripping)
    if t_host == c_host:
        return DomainMatch(
            target_domain=t_raw,
            candidate_domain=c_raw,
            category=DomainMatchCategory.NORMALIZED,
            is_match=True,
            target_hostname=t_host,
            candidate_hostname=c_host,
            reasons=["Normalized hostnames are identical"],
        )

    # 3. Related / Derived domain
    t_reg = _registered_domain_name(t_host)
    c_reg = _registered_domain_name(c_host)

    # Subdomain of same domain (e.g. careers.equinor.com vs equinor.com)
    is_subdomain = t_host.endswith("." + c_host) or c_host.endswith("." + t_host)

    # Same SLD with different ccTLD (e.g. equinor.no vs equinor.com)
    is_tld_variant = bool(t_reg and c_reg and t_reg == c_reg and len(t_reg) > 2)

    # Candidate domain derived from target legal name tokens
    name_tokens = _name_tokens(target_name) if target_name else []
    name_compact = "".join(name_tokens)
    c_compact = re.sub(r"[^a-z0-9]", "", c_host)
    is_name_derived = bool(name_compact and (name_compact in c_compact or (c_reg and c_reg in name_compact)))

    if is_subdomain:
        return DomainMatch(
            target_domain=t_raw,
            candidate_domain=c_raw,
            category=DomainMatchCategory.RELATED_DERIVED,
            is_match=True,
            target_hostname=t_host,
            candidate_hostname=c_host,
            reasons=[f"Subdomain relationship between {t_host} and {c_host}"],
        )

    if is_tld_variant:
        return DomainMatch(
            target_domain=t_raw,
            candidate_domain=c_raw,
            category=DomainMatchCategory.RELATED_DERIVED,
            is_match=True,
            target_hostname=t_host,
            candidate_hostname=c_host,
            reasons=[f"Registered domain base matches ({t_reg}) with different TLD/extension"],
        )

    if is_name_derived:
        return DomainMatch(
            target_domain=t_raw,
            candidate_domain=c_raw,
            category=DomainMatchCategory.RELATED_DERIVED,
            is_match=True,
            target_hostname=t_host,
            candidate_hostname=c_host,
            reasons=[f"Candidate domain {c_host} is derived from target legal name tokens {name_tokens}"],
        )

    # 4. Conflicting domain
    return DomainMatch(
        target_domain=t_raw,
        candidate_domain=c_raw,
        category=DomainMatchCategory.CONFLICTING,
        is_match=False,
        target_hostname=t_host,
        candidate_hostname=c_host,
        reasons=[f"Candidate domain {c_host} conflicts with target domain {t_host}"],
    )


# ============================================================================
# 4. PARENT / SUBSIDIARY / GROUP HANDLING
# ============================================================================

class GroupRelationType(str, Enum):
    SAME_ENTITY = "same_entity"
    PARENT = "parent"
    SUBSIDIARY = "subsidiary"
    SISTER_SUBSIDIARY = "sister_subsidiary"
    SUBUNIT = "subunit"
    CORPORATE_GROUP = "corporate_group"
    UNRELATED = "unrelated"


@dataclass(frozen=True)
class GroupRelationship:
    target_org: str
    candidate_org: str
    relation_type: GroupRelationType
    is_same_legal_entity: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["relation_type"] = self.relation_type.value
        return data


def classify_group_relationship(
    target_entity: dict[str, Any],
    candidate_entity: dict[str, Any],
    *,
    group_data: dict[str, Any] | None = None,
) -> GroupRelationship:
    """Classify corporate group relationship between two entities.

    Ensures parent companies, subsidiaries, subunits, and sister entities
    are NEVER conflated as the same legal entity.
    """
    t_org = canonicalize_org_number(target_entity.get("organisation_number")) or ""
    c_org = canonicalize_org_number(candidate_entity.get("organisation_number")) or ""

    if not t_org or not c_org:
        return GroupRelationship(
            target_org=t_org,
            candidate_org=c_org,
            relation_type=GroupRelationType.UNRELATED,
            is_same_legal_entity=False,
            reasons=["Missing valid organisation number for target or candidate"],
        )

    # 1. Exact same legal entity
    if t_org == c_org:
        return GroupRelationship(
            target_org=t_org,
            candidate_org=c_org,
            relation_type=GroupRelationType.SAME_ENTITY,
            is_same_legal_entity=True,
            reasons=[f"Identical organisation number ({t_org})"],
        )

    # 2. Check subunit / overordnetEnhet
    t_parent = canonicalize_org_number(target_entity.get("overordnetEnhet"))
    c_parent = canonicalize_org_number(candidate_entity.get("overordnetEnhet"))

    if t_parent == c_org:
        return GroupRelationship(
            target_org=t_org,
            candidate_org=c_org,
            relation_type=GroupRelationType.PARENT,
            is_same_legal_entity=False,
            reasons=[f"Candidate {c_org} is registered parent / overordnetEnhet of target {t_org}"],
        )

    if c_parent == t_org:
        return GroupRelationship(
            target_org=t_org,
            candidate_org=c_org,
            relation_type=GroupRelationType.SUBUNIT,
            is_same_legal_entity=False,
            reasons=[f"Candidate {c_org} is registered subunit of target {t_org}"],
        )

    if t_parent and c_parent and t_parent == c_parent:
        return GroupRelationship(
            target_org=t_org,
            candidate_org=c_org,
            relation_type=GroupRelationType.SISTER_SUBSIDIARY,
            is_same_legal_entity=False,
            reasons=[f"Target {t_org} and candidate {c_org} share parent entity {t_parent}"],
        )

    # 3. Check group_data (konsernstruktur API)
    if group_data and isinstance(group_data, dict):
        # BRREG konsernstruktur inspection
        morselskap_org = canonicalize_org_number(
            group_data.get("morselskap", {}).get("organisasjonsnummer")
            if isinstance(group_data.get("morselskap"), dict)
            else group_data.get("morselskap")
        )
        if morselskap_org == c_org:
            return GroupRelationship(
                target_org=t_org,
                candidate_org=c_org,
                relation_type=GroupRelationType.PARENT,
                is_same_legal_entity=False,
                reasons=[f"Candidate {c_org} is parent company (morselskap) in BRREG group structure"],
            )

        subsidiaries = group_data.get("datterselskaper") or group_data.get("underenheter") or []
        sub_orgs = {
            canonicalize_org_number(item.get("organisasjonsnummer") if isinstance(item, dict) else item)
            for item in subsidiaries
        }
        if c_org in sub_orgs:
            return GroupRelationship(
                target_org=t_org,
                candidate_org=c_org,
                relation_type=GroupRelationType.SUBSIDIARY,
                is_same_legal_entity=False,
                reasons=[f"Candidate {c_org} is subsidiary (datterselskap) in BRREG group structure"],
            )

    return GroupRelationship(
        target_org=t_org,
        candidate_org=c_org,
        relation_type=GroupRelationType.UNRELATED,
        is_same_legal_entity=False,
        reasons=[f"Entities have different organisation numbers ({t_org} vs {c_org}) and no recorded group link"],
    )


# ============================================================================
# 5. AMBIGUITY DETECTION & WRONG-COMPANY REJECTION
# ============================================================================

class IdentityVerdictStatus(str, Enum):
    ACCEPTED = "accepted"
    AMBIGUOUS = "ambiguous"
    REJECTED = "rejected"
    UNRESOLVED = "unresolved"


class IdentityConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


@dataclass(frozen=True)
class IdentityEvidence:
    field: str
    source: str
    observed_value: Any
    expected_value: Any
    status: str  # "matched", "conflict", "compatible", "missing", "unverified"
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IdentityVerdict:
    verdict: IdentityVerdictStatus
    confidence: IdentityConfidence
    target_org: str | None
    target_name: str | None
    matched_entity: dict[str, Any] | None
    evidence: list[IdentityEvidence]
    reasons: list[str]
    flags: dict[str, bool]
    candidates_evaluated: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "confidence": self.confidence.value,
            "target_org": self.target_org,
            "target_name": self.target_name,
            "matched_entity": self.matched_entity,
            "evidence": [item.to_dict() for item in self.evidence],
            "reasons": self.reasons,
            "flags": self.flags,
            "candidates_evaluated": self.candidates_evaluated,
        }


def detect_ambiguity(
    target_entity: dict[str, Any],
    candidate_entities: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Detect if multiple candidate entities plausibly match the target without a discriminator."""
    target_name = target_entity.get("name")
    target_org = canonicalize_org_number(target_entity.get("organisation_number"))

    if not candidate_entities:
        return False, ["No candidate entities provided"]

    # If an exact org number match exists in candidates, it is unambiguous
    if target_org:
        exact_org_matches = [
            c for c in candidate_entities
            if canonicalize_org_number(c.get("organisation_number")) == target_org
        ]
        if len(exact_org_matches) == 1:
            return False, ["Single candidate matches authoritative organisation number"]
        elif len(exact_org_matches) > 1:
            return True, ["Duplicate candidate records with identical organisation number"]

    # Evaluate name matches
    plausible_matches: list[tuple[dict[str, Any], LegalNameMatch]] = []
    for cand in candidate_entities:
        match = match_legal_names(target_name, cand.get("name"))
        if match.is_match:
            plausible_matches.append((cand, match))

    if len(plausible_matches) > 1:
        c_orgs = [c.get("organisation_number") for c, _ in plausible_matches]
        c_names = [c.get("name") for c, _ in plausible_matches]
        return True, [
            f"Multiple distinct BRREG entities ({len(plausible_matches)}) match legal name {target_name!r}: "
            f"orgs={c_orgs}, names={c_names}"
        ]

    return False, []


def assess_company_identity(
    target_entity: dict[str, Any],
    candidate_entity: dict[str, Any],
    *,
    group_data: dict[str, Any] | None = None,
    candidate_pool: list[dict[str, Any]] | None = None,
) -> IdentityVerdict:
    """Assess company identity deterministically against authoritative BRREG criteria.

    Explicitly rejects wrong companies and related corporate group entities (parent/subsidiary).
    """
    evidence_items: list[IdentityEvidence] = []
    reasons: list[str] = []
    flags: dict[str, bool] = {
        "org_number_exact_match": False,
        "legal_name_match": False,
        "legal_form_match": False,
        "legal_form_conflict": False,
        "domain_match": False,
        "domain_conflict": False,
        "group_relation_detected": False,
        "is_parent_or_subsidiary": False,
        "ambiguity_detected": False,
    }

    t_org = canonicalize_org_number(target_entity.get("organisation_number"))
    t_name = str(target_entity.get("name") or "").strip()
    t_web = target_entity.get("website")

    c_org = canonicalize_org_number(candidate_entity.get("organisation_number"))
    c_name = str(candidate_entity.get("name") or "").strip()
    c_web = candidate_entity.get("website")

    candidates_count = len(candidate_pool) if candidate_pool else 1

    # 1. Ambiguity Check across candidate pool
    if candidate_pool and len(candidate_pool) > 1:
        is_ambig, ambig_reasons = detect_ambiguity(target_entity, candidate_pool)
        if is_ambig:
            flags["ambiguity_detected"] = True
            evidence_items.append(IdentityEvidence(
                field="candidate_pool",
                source="brreg_candidates",
                observed_value=[c.get("organisation_number") for c in candidate_pool],
                expected_value=t_org,
                status="conflict",
                explanation="; ".join(ambig_reasons),
            ))
            return IdentityVerdict(
                verdict=IdentityVerdictStatus.AMBIGUOUS,
                confidence=IdentityConfidence.NONE,
                target_org=t_org,
                target_name=t_name,
                matched_entity=None,
                evidence=evidence_items,
                reasons=ambig_reasons,
                flags=flags,
                candidates_evaluated=candidates_count,
            )

    # 2. Organisation Number Assessment
    if t_org and c_org:
        if t_org == c_org:
            flags["org_number_exact_match"] = True
            evidence_items.append(IdentityEvidence(
                field="organisation_number",
                source="brreg_registry",
                observed_value=c_org,
                expected_value=t_org,
                status="matched",
                explanation="Authoritative organisation number matches exactly",
            ))
        else:
            # Different organisation numbers -> evaluate group relationship
            group_rel = classify_group_relationship(target_entity, candidate_entity, group_data=group_data)
            if group_rel.relation_type in {
                GroupRelationType.PARENT,
                GroupRelationType.SUBSIDIARY,
                GroupRelationType.SUBUNIT,
                GroupRelationType.SISTER_SUBSIDIARY,
            }:
                flags["group_relation_detected"] = True
                flags["is_parent_or_subsidiary"] = True
                rel_desc = group_rel.relation_type.value
                reasons.extend(group_rel.reasons)
                evidence_items.append(IdentityEvidence(
                    field="organisation_number",
                    source="brreg_registry",
                    observed_value=c_org,
                    expected_value=t_org,
                    status="conflict",
                    explanation=f"Entity is a related {rel_desc}, not the exact target legal entity",
                ))
                return IdentityVerdict(
                    verdict=IdentityVerdictStatus.REJECTED,
                    confidence=IdentityConfidence.HIGH,
                    target_org=t_org,
                    target_name=t_name,
                    matched_entity=None,
                    evidence=evidence_items,
                    reasons=[f"Rejected: candidate is a related {rel_desc} ({c_org}), not target legal entity ({t_org})"],
                    flags=flags,
                    candidates_evaluated=candidates_count,
                )
            else:
                evidence_items.append(IdentityEvidence(
                    field="organisation_number",
                    source="brreg_registry",
                    observed_value=c_org,
                    expected_value=t_org,
                    status="conflict",
                    explanation=f"Organisation number mismatch: target {t_org} != candidate {c_org}",
                ))
                return IdentityVerdict(
                    verdict=IdentityVerdictStatus.REJECTED,
                    confidence=IdentityConfidence.HIGH,
                    target_org=t_org,
                    target_name=t_name,
                    matched_entity=None,
                    evidence=evidence_items,
                    reasons=[f"Rejected wrong company: candidate org {c_org} does not match target org {t_org}"],
                    flags=flags,
                    candidates_evaluated=candidates_count,
                )
    elif not t_org and not c_org:
        evidence_items.append(IdentityEvidence(
            field="organisation_number",
            source="brreg_registry",
            observed_value=None,
            expected_value=None,
            status="missing",
            explanation="Both target and candidate lack organisation number",
        ))

    # 3. Legal Name Assessment
    name_match = match_legal_names(t_name, c_name)
    if name_match.is_match:
        flags["legal_name_match"] = True
        flags["legal_form_match"] = name_match.target_form == name_match.candidate_form
        evidence_items.append(IdentityEvidence(
            field="name",
            source="brreg_registry",
            observed_value=c_name,
            expected_value=t_name,
            status="matched",
            explanation="; ".join(name_match.reasons),
        ))
    else:
        if name_match.category == LegalNameMatchCategory.LEGAL_FORM_CONFLICT:
            flags["legal_form_conflict"] = True
        evidence_items.append(IdentityEvidence(
            field="name",
            source="brreg_registry",
            observed_value=c_name,
            expected_value=t_name,
            status="conflict",
            explanation="; ".join(name_match.reasons),
        ))

    # 4. Domain Assessment
    dom_match = match_domain_entity(t_web, c_web, target_name=t_name)
    if dom_match.is_match:
        flags["domain_match"] = True
        evidence_items.append(IdentityEvidence(
            field="website",
            source="website_evidence",
            observed_value=c_web,
            expected_value=t_web,
            status="matched",
            explanation="; ".join(dom_match.reasons),
        ))
    elif dom_match.category == DomainMatchCategory.CONFLICTING:
        flags["domain_conflict"] = True
        evidence_items.append(IdentityEvidence(
            field="website",
            source="website_evidence",
            observed_value=c_web,
            expected_value=t_web,
            status="conflict",
            explanation="; ".join(dom_match.reasons),
        ))
    else:
        evidence_items.append(IdentityEvidence(
            field="website",
            source="website_evidence",
            observed_value=c_web,
            expected_value=t_web,
            status="missing" if dom_match.category == DomainMatchCategory.UNAVAILABLE else "unverified",
            explanation="; ".join(dom_match.reasons),
        ))

    # 5. Deterministic Verdict Synthesis
    # Case A: Exact org match confirmed
    if flags["org_number_exact_match"]:
        if flags["legal_name_match"]:
            reasons.append("Authoritative organisation number and legal name match")
            return IdentityVerdict(
                verdict=IdentityVerdictStatus.ACCEPTED,
                confidence=IdentityConfidence.HIGH,
                target_org=t_org,
                target_name=t_name,
                matched_entity=candidate_entity,
                evidence=evidence_items,
                reasons=reasons,
                flags=flags,
                candidates_evaluated=candidates_count,
            )
        elif not t_name or not c_name:
            # Org matches, name is missing on one side
            reasons.append("Authoritative organisation number matches exactly; name unverified")
            return IdentityVerdict(
                verdict=IdentityVerdictStatus.ACCEPTED,
                confidence=IdentityConfidence.HIGH,
                target_org=t_org,
                target_name=t_name,
                matched_entity=candidate_entity,
                evidence=evidence_items,
                reasons=reasons,
                flags=flags,
                candidates_evaluated=candidates_count,
            )
        else:
            # Org matches, but names conflict (e.g. recent name change or data error)
            reasons.append(f"Organisation number matches ({t_org}), but legal names differ ({t_name!r} vs {c_name!r})")
            return IdentityVerdict(
                verdict=IdentityVerdictStatus.AMBIGUOUS,
                confidence=IdentityConfidence.LOW,
                target_org=t_org,
                target_name=t_name,
                matched_entity=None,
                evidence=evidence_items,
                reasons=reasons,
                flags=flags,
                candidates_evaluated=candidates_count,
            )

    # Case B: No candidate org number, but target org exists
    if t_org and not c_org:
        if flags["legal_form_conflict"]:
            reasons.append(f"Rejected: legal form conflict ({name_match.target_form} vs {name_match.candidate_form})")
            return IdentityVerdict(
                verdict=IdentityVerdictStatus.REJECTED,
                confidence=IdentityConfidence.HIGH,
                target_org=t_org,
                target_name=t_name,
                matched_entity=None,
                evidence=evidence_items,
                reasons=reasons,
                flags=flags,
                candidates_evaluated=candidates_count,
            )
        if flags["legal_name_match"]:
            if flags["domain_match"]:
                reasons.append("Legal name and registered domain match; candidate lacks organisation number")
                return IdentityVerdict(
                    verdict=IdentityVerdictStatus.ACCEPTED,
                    confidence=IdentityConfidence.MEDIUM,
                    target_org=t_org,
                    target_name=t_name,
                    matched_entity=candidate_entity,
                    evidence=evidence_items,
                    reasons=reasons,
                    flags=flags,
                    candidates_evaluated=candidates_count,
                )
            elif flags["domain_conflict"]:
                reasons.append("Legal name matches, but domain conflicts; candidate lacks organisation number")
                return IdentityVerdict(
                    verdict=IdentityVerdictStatus.REJECTED,
                    confidence=IdentityConfidence.MEDIUM,
                    target_org=t_org,
                    target_name=t_name,
                    matched_entity=None,
                    evidence=evidence_items,
                    reasons=reasons,
                    flags=flags,
                    candidates_evaluated=candidates_count,
                )
            else:
                # Name matches, but no domain and no org number on candidate
                reasons.append("Legal name matches, but no organisation number or matching domain on candidate")
                return IdentityVerdict(
                    verdict=IdentityVerdictStatus.UNRESOLVED,
                    confidence=IdentityConfidence.LOW,
                    target_org=t_org,
                    target_name=t_name,
                    matched_entity=None,
                    evidence=evidence_items,
                    reasons=reasons,
                    flags=flags,
                    candidates_evaluated=candidates_count,
                )
        else:
            reasons.append("Rejected: neither organisation number nor legal name match")
            return IdentityVerdict(
                verdict=IdentityVerdictStatus.REJECTED,
                confidence=IdentityConfidence.HIGH,
                target_org=t_org,
                target_name=t_name,
                matched_entity=None,
                evidence=evidence_items,
                reasons=reasons,
                flags=flags,
                candidates_evaluated=candidates_count,
            )

    # Case C: Neither has org number
    if flags["legal_name_match"] and flags["domain_match"]:
        reasons.append("Legal name and domain match without organisation numbers")
        return IdentityVerdict(
            verdict=IdentityVerdictStatus.ACCEPTED,
            confidence=IdentityConfidence.MEDIUM,
            target_org=None,
            target_name=t_name,
            matched_entity=candidate_entity,
            evidence=evidence_items,
            reasons=reasons,
            flags=flags,
            candidates_evaluated=candidates_count,
        )

    reasons.append("Insufficient authoritative evidence to establish company identity")
    return IdentityVerdict(
        verdict=IdentityVerdictStatus.UNRESOLVED,
        confidence=IdentityConfidence.NONE,
        target_org=t_org,
        target_name=t_name,
        matched_entity=None,
        evidence=evidence_items,
        reasons=reasons,
        flags=flags,
        candidates_evaluated=candidates_count,
    )
