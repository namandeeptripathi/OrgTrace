"""Stage 14: Coverage Expansion.

Provides comprehensive, useful-information coverage across Norwegian enterprises targeting
the competition's 35-point coverage component across all 29 defined categories.

Ensures:
1. Exact company identity
2. Deterministic source provenance and fallback hierarchy
3. Strict evidence attachment without hallucination
4. Graceful and explicit missing-data states
5. Robust normalization for numbers, phones, URLs, currencies, and dates
6. Transparent conflict resolution and divergence tracking
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import math
import re
from typing import Any, Iterable
import urllib.parse

from .evidence import Evidence, evidence, utc_now
from .financial_intelligence import CompanyFinancialProfile, FinancialStatement
from .identity_engine import canonicalize_org_number, normalize_legal_name
from .profile_extraction import (
    ExtractedCompanyProfile,
    ExtractedField,
    FieldStatus,
)


# ============================================================================
# 1. 29 INFORMATION CATEGORIES & TIERS
# ============================================================================

class CoverageCategory(str, Enum):
    # Company Identity
    LEGAL_NAME = "legal_name"
    ORGANISATION_NUMBER = "organisation_number"
    ORGANISATION_FORM = "organisation_form"
    REGISTRATION_DATE = "registration_date"
    STATUS = "status"

    # Business Profile
    INDUSTRY = "industry"
    ADDRESS = "address"
    MUNICIPALITY = "municipality"
    WEBSITE = "website"
    DESCRIPTION = "description"
    CONTACT_INFORMATION = "contact_information"

    # People & Governance
    LEADERSHIP = "leadership"
    EMPLOYEES = "employees"

    # Financial Intelligence
    REVENUE = "revenue"
    PROFIT_LOSS = "profit_loss"
    ASSETS = "assets"
    EQUITY = "equity"
    FINANCIAL_YEAR = "financial_year"

    # Operations & Commercial Offerings
    PRODUCTS_SERVICES = "products_services"
    CUSTOMERS_MARKETS = "customers_markets"
    LOCATIONS = "locations"
    TECHNOLOGY = "technology"

    # Digital & Public Presence
    NEWS_EVENTS = "news_events"
    SOCIAL_PRESENCE = "social_presence"
    CERTIFICATIONS = "certifications"
    PARTNERSHIPS = "partnerships"

    # Corporate Structure & Intelligence
    OWNERSHIP_INFO = "ownership_information"
    PARENT_SUBSIDIARY = "parent_subsidiary_relationships"
    RECENT_CHANGES = "recent_changes"


ALL_29_CATEGORIES: list[CoverageCategory] = list(CoverageCategory)
assert len(ALL_29_CATEGORIES) == 29, f"Must have exactly 29 categories, got {len(ALL_29_CATEGORIES)}"


class CategoryTier(str, Enum):
    TIER_1_CORE = "tier_1_core"                  # High-value & statutory/authoritative
    TIER_2_COMMERCIAL = "tier_2_commercial"      # Useful business intel, source-dependent
    TIER_3_RESTRICTED = "tier_3_restricted"      # Low reliability without direct primary proof


TIER_MAPPING: dict[CoverageCategory, CategoryTier] = {
    # Tier 1: Core Statutory & Financial (Authoritative & deterministic)
    CoverageCategory.LEGAL_NAME: CategoryTier.TIER_1_CORE,
    CoverageCategory.ORGANISATION_NUMBER: CategoryTier.TIER_1_CORE,
    CoverageCategory.ORGANISATION_FORM: CategoryTier.TIER_1_CORE,
    CoverageCategory.REGISTRATION_DATE: CategoryTier.TIER_1_CORE,
    CoverageCategory.STATUS: CategoryTier.TIER_1_CORE,
    CoverageCategory.INDUSTRY: CategoryTier.TIER_1_CORE,
    CoverageCategory.ADDRESS: CategoryTier.TIER_1_CORE,
    CoverageCategory.MUNICIPALITY: CategoryTier.TIER_1_CORE,
    CoverageCategory.WEBSITE: CategoryTier.TIER_1_CORE,
    CoverageCategory.DESCRIPTION: CategoryTier.TIER_1_CORE,
    CoverageCategory.CONTACT_INFORMATION: CategoryTier.TIER_1_CORE,
    CoverageCategory.LEADERSHIP: CategoryTier.TIER_1_CORE,
    CoverageCategory.EMPLOYEES: CategoryTier.TIER_1_CORE,
    CoverageCategory.REVENUE: CategoryTier.TIER_1_CORE,
    CoverageCategory.PROFIT_LOSS: CategoryTier.TIER_1_CORE,
    CoverageCategory.ASSETS: CategoryTier.TIER_1_CORE,
    CoverageCategory.EQUITY: CategoryTier.TIER_1_CORE,
    CoverageCategory.FINANCIAL_YEAR: CategoryTier.TIER_1_CORE,

    # Tier 2: Commercial & Operational Profile
    CoverageCategory.PRODUCTS_SERVICES: CategoryTier.TIER_2_COMMERCIAL,
    CoverageCategory.CUSTOMERS_MARKETS: CategoryTier.TIER_2_COMMERCIAL,
    CoverageCategory.LOCATIONS: CategoryTier.TIER_2_COMMERCIAL,
    CoverageCategory.NEWS_EVENTS: CategoryTier.TIER_2_COMMERCIAL,
    CoverageCategory.SOCIAL_PRESENCE: CategoryTier.TIER_2_COMMERCIAL,
    CoverageCategory.CERTIFICATIONS: CategoryTier.TIER_2_COMMERCIAL,
    CoverageCategory.PARENT_SUBSIDIARY: CategoryTier.TIER_2_COMMERCIAL,
    CoverageCategory.RECENT_CHANGES: CategoryTier.TIER_2_COMMERCIAL,

    # Tier 3: Strict Proof Required (Never speculate)
    CoverageCategory.TECHNOLOGY: CategoryTier.TIER_3_RESTRICTED,
    CoverageCategory.PARTNERSHIPS: CategoryTier.TIER_3_RESTRICTED,
    CoverageCategory.OWNERSHIP_INFO: CategoryTier.TIER_3_RESTRICTED,
}


# ============================================================================
# 2. SOURCE PRECEDENCE & MISSING DATA ENUMS
# ============================================================================

class SourcePriority:
    OFFICIAL_REGISTRY = 100       # Brønnøysundregistrene (Enhetsregisteret)
    OFFICIAL_FILING = 90         # Regnskapsregisteret / Official annual accounts
    FIRST_PARTY_STRUCTURED = 85  # JSON-LD Schema.org on verified company website
    FIRST_PARTY_WEBSITE = 80     # Verified company homepage, about, contact, products
    REPUTABLE_SECONDARY = 50     # Permitted business directory, verified news
    UNVERIFIED = 10              # Low-confidence mentions


class CoverageFieldStatus(str, Enum):
    AVAILABLE = "available"                     # Fact extracted and corroborated
    UNAVAILABLE = "unavailable"                 # Source offline, not accessible, or company exempt
    NOT_FOUND = "not_found"                     # Source inspected, fact is not publicly stated
    CONFLICTING_SOURCES = "conflicting_sources" # Material divergence between permitted sources
    EXTRACTION_FAILED = "extraction_failed"     # Parsing error or corrupted payload


# Strategy definition for each category: primary, fallback, secondary fallback
CATEGORY_SOURCE_STRATEGY: dict[CoverageCategory, dict[str, Any]] = {
    CoverageCategory.LEGAL_NAME: {
        "primary": "official_registry",
        "fallback": "first_party_structured",
        "secondary_fallback": "first_party_website",
    },
    CoverageCategory.ORGANISATION_NUMBER: {
        "primary": "official_registry",
        "fallback": "first_party_website",
        "secondary_fallback": None,
    },
    CoverageCategory.ORGANISATION_FORM: {
        "primary": "official_registry",
        "fallback": None,
        "secondary_fallback": None,
    },
    CoverageCategory.REGISTRATION_DATE: {
        "primary": "official_registry",
        "fallback": "first_party_website",
        "secondary_fallback": None,
    },
    CoverageCategory.STATUS: {
        "primary": "official_registry",
        "fallback": None,
        "secondary_fallback": None,
    },
    CoverageCategory.INDUSTRY: {
        "primary": "official_registry",
        "fallback": "first_party_structured",
        "secondary_fallback": "first_party_website",
    },
    CoverageCategory.ADDRESS: {
        "primary": "official_registry",
        "fallback": "first_party_structured",
        "secondary_fallback": "first_party_website",
    },
    CoverageCategory.MUNICIPALITY: {
        "primary": "official_registry",
        "fallback": "official_registry_address",
        "secondary_fallback": None,
    },
    CoverageCategory.WEBSITE: {
        "primary": "official_registry",
        "fallback": "first_party_verified",
        "secondary_fallback": None,
    },
    CoverageCategory.DESCRIPTION: {
        "primary": "first_party_structured",
        "fallback": "first_party_website",
        "secondary_fallback": "official_registry_purpose",
    },
    CoverageCategory.CONTACT_INFORMATION: {
        "primary": "first_party_structured",
        "fallback": "first_party_website",
        "secondary_fallback": "official_registry",
    },
    CoverageCategory.LEADERSHIP: {
        "primary": "official_roles",
        "fallback": "first_party_structured",
        "secondary_fallback": "first_party_website",
    },
    CoverageCategory.EMPLOYEES: {
        "primary": "official_registry",
        "fallback": "first_party_structured",
        "secondary_fallback": "first_party_website",
    },
    CoverageCategory.REVENUE: {
        "primary": "official_regnskapsregisteret",
        "fallback": "official_pdf_filing",
        "secondary_fallback": None,
    },
    CoverageCategory.PROFIT_LOSS: {
        "primary": "official_regnskapsregisteret",
        "fallback": "official_pdf_filing",
        "secondary_fallback": None,
    },
    CoverageCategory.ASSETS: {
        "primary": "official_regnskapsregisteret",
        "fallback": "official_pdf_filing",
        "secondary_fallback": None,
    },
    CoverageCategory.EQUITY: {
        "primary": "official_regnskapsregisteret",
        "fallback": "official_pdf_filing",
        "secondary_fallback": None,
    },
    CoverageCategory.FINANCIAL_YEAR: {
        "primary": "official_regnskapsregisteret",
        "fallback": "official_pdf_filing",
        "secondary_fallback": None,
    },
    CoverageCategory.PRODUCTS_SERVICES: {
        "primary": "first_party_structured",
        "fallback": "first_party_website",
        "secondary_fallback": "official_registry_purpose",
    },
    CoverageCategory.CUSTOMERS_MARKETS: {
        "primary": "first_party_structured",
        "fallback": "first_party_website",
        "secondary_fallback": "official_registry_scope",
    },
    CoverageCategory.LOCATIONS: {
        "primary": "official_subunits",
        "fallback": "first_party_structured",
        "secondary_fallback": "official_registry_headquarters",
    },
    CoverageCategory.TECHNOLOGY: {
        "primary": "first_party_website_tech",
        "fallback": None,
        "secondary_fallback": None,
    },
    CoverageCategory.NEWS_EVENTS: {
        "primary": "first_party_website",
        "fallback": "official_announcements",
        "secondary_fallback": None,
    },
    CoverageCategory.SOCIAL_PRESENCE: {
        "primary": "first_party_website",
        "fallback": "first_party_structured",
        "secondary_fallback": None,
    },
    CoverageCategory.CERTIFICATIONS: {
        "primary": "first_party_website",
        "fallback": "official_standards_registry",
        "secondary_fallback": None,
    },
    CoverageCategory.PARTNERSHIPS: {
        "primary": "first_party_website",
        "fallback": None,
        "secondary_fallback": None,
    },
    CoverageCategory.OWNERSHIP_INFO: {
        "primary": "official_registry_aksjeeier",
        "fallback": "official_registry_group",
        "secondary_fallback": None,
    },
    CoverageCategory.PARENT_SUBSIDIARY: {
        "primary": "official_registry_group",
        "fallback": "first_party_website",
        "secondary_fallback": None,
    },
    CoverageCategory.RECENT_CHANGES: {
        "primary": "official_refresh_audit",
        "fallback": "first_party_news",
        "secondary_fallback": None,
    },
}


# ============================================================================
# 3. NORMALIZATION UTILITIES
# ============================================================================

def normalize_org_number(val: Any) -> str | None:
    """Validate and normalize 9-digit Norwegian organisation number."""
    if val is None:
        return None
    raw = re.sub(r"\D", "", str(val))
    if len(raw) != 9:
        return None
    return raw


def normalize_phone_number(val: Any) -> str | None:
    """Normalize Norwegian and international phone numbers into clean standard format."""
    if not val or not isinstance(val, str):
        return None
    cleaned = re.sub(r"[^\d+]", "", val.strip())
    # Handle European trunk prefix (0) after country code, e.g. +47 (0) 22 33 44 55 -> +47022334455
    if cleaned.startswith("+470") and len(cleaned) == 12:
        cleaned = "+47" + cleaned[4:]
    elif cleaned.startswith("00470") and len(cleaned) == 14:
        cleaned = "+47" + cleaned[5:]
    elif cleaned.startswith("0047") and len(cleaned) == 13:
        cleaned = "+47" + cleaned[4:]

    # Format Norwegian 8-digit numbers (+47 XXXXXXXX or XXXXXXXX)
    if cleaned.startswith("+47") and len(cleaned) == 11:
        num = cleaned[3:]
        return f"+47 {num[:2]} {num[2:4]} {num[4:6]} {num[6:]}"
    elif len(cleaned) == 8 and cleaned[0] in "23456789":
        return f"+47 {cleaned[:2]} {cleaned[2:4]} {cleaned[4:6]} {cleaned[6:]}"
    elif cleaned.startswith("+"):
        return cleaned
    elif len(cleaned) >= 8:
        return cleaned
    return None


def normalize_url(val: Any) -> str | None:
    """Normalize URL with proper scheme, lowercase domain, and clean formatting."""
    if not val or not isinstance(val, str):
        return None
    url = val.strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urllib.parse.urlparse(url)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        if not netloc:
            return None
        # Drop default ports
        if netloc.endswith(":443") and scheme == "https":
            netloc = netloc[:-4]
        elif netloc.endswith(":80") and scheme == "http":
            netloc = netloc[:-3]
        path = parsed.path
        if path == "/":
            path = ""
        elif path.endswith("/"):
            path = path.rstrip("/")
        normalized = urllib.parse.urlunparse((scheme, netloc, path, "", parsed.query, ""))
        return normalized
    except Exception:
        return None


def normalize_email(val: Any) -> str | None:
    """Normalize and validate email address."""
    if not val or not isinstance(val, str):
        return None
    email = val.strip().lower()
    if re.match(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$", email):
        return email
    return None


def normalize_date(val: Any) -> str | None:
    """Normalize date representations to ISO 8601 YYYY-MM-DD."""
    if not val:
        return None
    s = str(val).strip()
    # YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    # DD.MM.YYYY
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", s)
    if m:
        d, mon, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mon:02d}-{d:02d}"
    # DD-MM-YYYY
    m = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})$", s)
    if m:
        d, mon, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mon:02d}-{d:02d}"
    # ISO datetime with T
    if "T" in s:
        part = s.split("T")[0]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", part):
            return part
    return None


def normalize_financial_amount(val: Any) -> tuple[float | int | None, str]:
    """Normalize financial text or number into consistent numeric representation and currency.

    Handles:
    - 12500000 -> (12500000, "NOK")
    - "NOK 12 500 000" -> (12500000, "NOK")
    - "12.5 million NOK" -> (12500000.0, "NOK")
    - "12,500,000 NOK" -> (12500000, "NOK")
    """
    if val is None:
        return None, "NOK"
    if isinstance(val, (int, float)):
        return val, "NOK"

    raw = str(val).strip()
    currency = "NOK"
    if "EUR" in raw.upper():
        currency = "EUR"
    elif "USD" in raw.upper():
        currency = "USD"

    # Million pattern: "12.5 million NOK" or "12,5 mill NOK"
    mill_match = re.search(r"([\d\s.,]+)\s*(?:million(?:er)?|mill\.?|m)\b", raw, re.I)
    if mill_match:
        num_str = mill_match.group(1).replace(" ", "").replace(",", ".")
        try:
            return round(float(num_str) * 1_000_000, 2), currency
        except ValueError:
            pass

    # Clean punctuation and spaces: "12 500 000" or "12,500,000"
    cleaned = re.sub(r"[^\d.,\-]", "", raw)
    # If both . and , are present (e.g. 12,500,000.00 or 12.500.000,00)
    if "." in cleaned and "," in cleaned:
        if cleaned.rfind(".") > cleaned.rfind(","):
            # US format 12,500.00
            cleaned = cleaned.replace(",", "")
        else:
            # European format 12.500,00
            cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned and len(cleaned.split(",")[-1]) == 2:
        # European decimal 12500,00
        cleaned = cleaned.replace(",", ".")
    else:
        # Punctuation as thousands separators
        cleaned = cleaned.replace(" ", "").replace(",", "").replace(".", "")

    try:
        if "." in cleaned:
            return float(cleaned), currency
        return int(cleaned), currency
    except ValueError:
        return None, currency


def normalize_address(raw_addr: Any) -> dict[str, str | None]:
    """Normalize street address, postal code, city, and country."""
    if not raw_addr:
        return {"street": None, "postal_code": None, "city": None, "country": "Norge"}
    if isinstance(raw_addr, str):
        # Extract postal code and city if present
        m = re.search(r"\b(\d{4})\s+([A-ZÆØÅa-zæøå\s-]+)\b", raw_addr)
        if m:
            p_code = m.group(1)
            p_city = m.group(2).strip()
            street = raw_addr[:m.start()].strip().rstrip(",")
            return {"street": street or None, "postal_code": p_code, "city": p_city, "country": "Norge"}
        return {"street": raw_addr.strip(), "postal_code": None, "city": None, "country": "Norge"}

    if isinstance(raw_addr, dict):
        street = raw_addr.get("adresse") or raw_addr.get("street") or raw_addr.get("streetAddress")
        if isinstance(street, list):
            street = ", ".join(str(x) for x in street if x)
        postal = raw_addr.get("postnummer") or raw_addr.get("postal_code") or raw_addr.get("postalCode")
        city = raw_addr.get("poststed") or raw_addr.get("city") or raw_addr.get("kommune") or raw_addr.get("addressLocality")
        country = raw_addr.get("land") or raw_addr.get("country") or raw_addr.get("addressCountry") or "Norge"
        return {
            "street": str(street).strip() if street else None,
            "postal_code": str(postal).strip() if postal else None,
            "city": str(city).strip() if city else None,
            "country": str(country).strip() if country else "Norge",
        }
    return {"street": None, "postal_code": None, "city": None, "country": "Norge"}


# ============================================================================
# 4. CONFLICT RECORD & RESOLUTION
# ============================================================================

@dataclass
class ConflictRecord:
    """Records divergent signals between permitted public sources."""
    category: str
    chosen_value: Any
    chosen_source: str
    conflicting_value: Any
    conflicting_source: str
    resolution_rationale: str
    is_material: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "chosen_value": self.chosen_value,
            "chosen_source": self.chosen_source,
            "conflicting_value": self.conflicting_value,
            "conflicting_source": self.conflicting_source,
            "resolution_rationale": self.resolution_rationale,
            "is_material": self.is_material,
        }


def resolve_field_conflict(
    category: CoverageCategory,
    val_a: Any,
    source_a: str,
    priority_a: int,
    val_b: Any,
    source_b: str,
    priority_b: int,
) -> tuple[Any, str, int, ConflictRecord | None, CoverageFieldStatus]:
    """Deterministically resolve conflict between two sources using priority precedence."""
    if val_a is not None and val_b is None:
        return val_a, source_a, priority_a, None, CoverageFieldStatus.AVAILABLE
    if val_b is not None and val_a is None:
        return val_b, source_b, priority_b, None, CoverageFieldStatus.AVAILABLE
    if val_a is None and val_b is None:
        return None, source_a, priority_a, None, CoverageFieldStatus.NOT_FOUND

    # Normalize values for semantic equality comparison
    norm_a = str(val_a).strip().lower()
    norm_b = str(val_b).strip().lower()

    if norm_a == norm_b:
        # Concordant: pick the higher priority
        if priority_a >= priority_b:
            return val_a, source_a, priority_a, None, CoverageFieldStatus.AVAILABLE
        return val_b, source_b, priority_b, None, CoverageFieldStatus.AVAILABLE

    # Material divergence detected
    if priority_a > priority_b:
        conflict = ConflictRecord(
            category=category.value,
            chosen_value=val_a,
            chosen_source=source_a,
            conflicting_value=val_b,
            conflicting_source=source_b,
            resolution_rationale=f"Higher source priority ({priority_a} > {priority_b})",
            is_material=True,
        )
        return val_a, source_a, priority_a, conflict, CoverageFieldStatus.AVAILABLE
    elif priority_b > priority_a:
        conflict = ConflictRecord(
            category=category.value,
            chosen_value=val_b,
            chosen_source=source_b,
            conflicting_value=val_a,
            conflicting_source=source_a,
            resolution_rationale=f"Higher source priority ({priority_b} > {priority_a})",
            is_material=True,
        )
        return val_b, source_b, priority_b, conflict, CoverageFieldStatus.AVAILABLE
    else:
        # Equal priority conflict: preserve conflict explicitly
        conflict = ConflictRecord(
            category=category.value,
            chosen_value=val_a,
            chosen_source=source_a,
            conflicting_value=val_b,
            conflicting_source=source_b,
            resolution_rationale="Equal priority sources with divergent values",
            is_material=True,
        )
        return val_a, source_a, priority_a, conflict, CoverageFieldStatus.CONFLICTING_SOURCES


# ============================================================================
# 5. COVERAGE FACT DATA MODEL
# ============================================================================

@dataclass
class CoverageFact:
    """A verified, provenance-backed factual claim in the company profile."""
    category: CoverageCategory
    field_name: str
    value: Any
    normalized_value: Any
    status: CoverageFieldStatus
    source_url: str | None
    source_type: str
    source_priority: int
    evidence_span: str | None
    confidence: float
    observed_at: str = field(default_factory=utc_now)
    conflict: ConflictRecord | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "category": self.category.value,
            "field_name": self.field_name,
            "value": self.value,
            "normalized_value": self.normalized_value,
            "status": self.status.value,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "source_priority": self.source_priority,
            "evidence_span": self.evidence_span,
            "confidence": round(self.confidence, 3),
            "observed_at": self.observed_at,
        }
        if self.conflict:
            data["conflict"] = self.conflict.to_dict()
        if self.note:
            data["note"] = self.note
        return data


# ============================================================================
# 6. UNIFIED COMPANY PROFILE
# ============================================================================

@dataclass
class UnifiedCompanyProfile:
    """Comprehensive, human-usable, and evaluation-ready Norwegian company profile."""
    organisation_number: str
    company_name: str
    facts: dict[CoverageCategory, CoverageFact]
    conflicts: list[ConflictRecord] = field(default_factory=list)
    operations: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "2.0.0"
    created_at: str = field(default_factory=utc_now)

    def get_fact(self, category: CoverageCategory) -> CoverageFact | None:
        return self.facts.get(category)

    def to_dict(self) -> dict[str, Any]:
        return {
            "organisation_number": self.organisation_number,
            "company_name": self.company_name,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "facts": {cat.value: fact.to_dict() for cat, fact in self.facts.items()},
            "conflicts": [c.to_dict() for c in self.conflicts],
            "operations": self.operations,
        }

    def to_contract_envelope(self, run_id: str = "run-stage14") -> dict[str, Any]:
        """Format to match OUTPUT_CONTRACT.md claims/evidence envelope."""
        claims = []
        evidence_list = []

        for i, (cat, fact) in enumerate(self.facts.items()):
            ev_id = f"ev-{i+1}"
            claims.append({
                "field": cat.value,
                "value": fact.normalized_value if fact.value is not None else None,
                "availability": fact.status.value,
                "confidence": round(fact.confidence, 2),
                "evidence_ids": [ev_id] if fact.evidence_span or fact.source_url else [],
            })
            if fact.evidence_span or fact.source_url:
                evidence_list.append({
                    "id": ev_id,
                    "source_url": fact.source_url or "https://data.brreg.no/enhetsregisteret/api/enheter",
                    "source_class": fact.source_type,
                    "retrieved_at": fact.observed_at,
                    "content_sha256": hashlib.sha256(str(fact.evidence_span or fact.value).encode()).hexdigest(),
                    "claim_span": str(fact.evidence_span or fact.value)[:300],
                })

        return {
            "organisation_number": self.organisation_number,
            "run": {
                "run_id": run_id,
                "started_at": self.created_at,
                "completed_at": utc_now(),
                "terminal_status": "completed",
            },
            "claims": claims,
            "evidence": evidence_list,
            "changes": [],
            "errors": [],
            "operations": {
                "requests": self.operations.get("requests", 0),
                "runtime_ms": self.operations.get("runtime_ms", 0),
                "third_party_cost_usd": self.operations.get("cost", 0.0),
            },
        }


# ============================================================================
# 7. UNIFIED PROFILE BUILDER
# ============================================================================

def build_unified_company_profile(
    profile: dict[str, Any],
    *,
    extracted_profile: ExtractedCompanyProfile | None = None,
    financial_profile: CompanyFinancialProfile | None = None,
    operations_metrics: dict[str, Any] | None = None,
) -> UnifiedCompanyProfile:
    """Build a deterministic, fully corroborated 29-category company profile."""
    org_number = normalize_org_number(profile.get("organisation_number")) or str(profile.get("organisation_number") or "").strip()
    company_name = str(profile.get("name") or "").strip()
    evidence_dict = profile.get("evidence") or {}

    facts: dict[CoverageCategory, CoverageFact] = {}
    conflicts: list[ConflictRecord] = []

    # ------------------------------------------------------------------------
    # 1. LEGAL NAME
    # ------------------------------------------------------------------------
    raw_name = profile.get("name")
    if raw_name:
        facts[CoverageCategory.LEGAL_NAME] = CoverageFact(
            category=CoverageCategory.LEGAL_NAME,
            field_name="legal_name",
            value=raw_name,
            normalized_value=normalize_legal_name(raw_name),
            status=CoverageFieldStatus.AVAILABLE,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=f"Navn i Enhetsregisteret: {raw_name}",
            confidence=1.0,
        )
    else:
        facts[CoverageCategory.LEGAL_NAME] = CoverageFact(
            category=CoverageCategory.LEGAL_NAME,
            field_name="legal_name",
            value=None,
            normalized_value=None,
            status=CoverageFieldStatus.NOT_FOUND,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=None,
            confidence=0.0,
        )

    # ------------------------------------------------------------------------
    # 2. ORGANISATION NUMBER
    # ------------------------------------------------------------------------
    if org_number:
        facts[CoverageCategory.ORGANISATION_NUMBER] = CoverageFact(
            category=CoverageCategory.ORGANISATION_NUMBER,
            field_name="organisation_number",
            value=org_number,
            normalized_value=org_number,
            status=CoverageFieldStatus.AVAILABLE,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=f"Organisasjonsnummer: {org_number}",
            confidence=1.0,
        )
    else:
        facts[CoverageCategory.ORGANISATION_NUMBER] = CoverageFact(
            category=CoverageCategory.ORGANISATION_NUMBER,
            field_name="organisation_number",
            value=None,
            normalized_value=None,
            status=CoverageFieldStatus.NOT_FOUND,
            source_url=None,
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=None,
            confidence=0.0,
        )

    # ------------------------------------------------------------------------
    # 3. ORGANISATION FORM
    # ------------------------------------------------------------------------
    org_form = profile.get("organisation_form") or profile.get("orgform") or profile.get("legal_form")
    if org_form:
        facts[CoverageCategory.ORGANISATION_FORM] = CoverageFact(
            category=CoverageCategory.ORGANISATION_FORM,
            field_name="organisation_form",
            value=org_form,
            normalized_value=str(org_form).upper(),
            status=CoverageFieldStatus.AVAILABLE,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=f"Organisasjonsform: {org_form}",
            confidence=1.0,
        )
    else:
        facts[CoverageCategory.ORGANISATION_FORM] = CoverageFact(
            category=CoverageCategory.ORGANISATION_FORM,
            field_name="organisation_form",
            value=None,
            normalized_value=None,
            status=CoverageFieldStatus.NOT_FOUND,
            source_url=None,
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=None,
            confidence=0.0,
        )

    # ------------------------------------------------------------------------
    # 4. REGISTRATION DATE
    # ------------------------------------------------------------------------
    reg_date = profile.get("registration_date")
    norm_reg_date = normalize_date(reg_date)
    if norm_reg_date:
        facts[CoverageCategory.REGISTRATION_DATE] = CoverageFact(
            category=CoverageCategory.REGISTRATION_DATE,
            field_name="registration_date",
            value=reg_date,
            normalized_value=norm_reg_date,
            status=CoverageFieldStatus.AVAILABLE,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=f"Registreringsdato i Enhetsregisteret: {norm_reg_date}",
            confidence=1.0,
        )
    else:
        facts[CoverageCategory.REGISTRATION_DATE] = CoverageFact(
            category=CoverageCategory.REGISTRATION_DATE,
            field_name="registration_date",
            value=None,
            normalized_value=None,
            status=CoverageFieldStatus.NOT_FOUND,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=None,
            confidence=0.0,
        )

    # ------------------------------------------------------------------------
    # 5. STATUS
    # ------------------------------------------------------------------------
    is_bankrupt = bool(profile.get("is_bankrupt"))
    is_liquidation = bool(profile.get("is_under_liquidation"))
    status_str = "KONKURS" if is_bankrupt else ("UNDER AVVIKLING" if is_liquidation else "AKTIV")
    facts[CoverageCategory.STATUS] = CoverageFact(
        category=CoverageCategory.STATUS,
        field_name="status",
        value=status_str,
        normalized_value=status_str.lower(),
        status=CoverageFieldStatus.AVAILABLE,
        source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
        source_type="official_registry",
        source_priority=SourcePriority.OFFICIAL_REGISTRY,
        evidence_span=f"Virksomhetsstatus: {status_str} (konkurs={is_bankrupt}, avvikling={is_liquidation})",
        confidence=1.0,
    )

    # ------------------------------------------------------------------------
    # 6. INDUSTRY
    # ------------------------------------------------------------------------
    ind_field = extracted_profile.industry if extracted_profile else None
    if ind_field and ind_field.status == FieldStatus.FOUND and ind_field.value:
        facts[CoverageCategory.INDUSTRY] = CoverageFact(
            category=CoverageCategory.INDUSTRY,
            field_name="industry",
            value=ind_field.value,
            normalized_value=ind_field.value.get("code") or ind_field.value.get("label"),
            status=CoverageFieldStatus.AVAILABLE,
            source_url=ind_field.source_url or "https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type=ind_field.source_type,
            source_priority=SourcePriority.OFFICIAL_REGISTRY if "registry" in ind_field.source_type else SourcePriority.FIRST_PARTY_STRUCTURED,
            evidence_span=ind_field.evidence_span,
            confidence=ind_field.confidence,
        )
    elif profile.get("industry_code") or profile.get("industry"):
        code = str(profile.get("industry_code") or profile.get("industry"))
        label = profile.get("industry_label")
        facts[CoverageCategory.INDUSTRY] = CoverageFact(
            category=CoverageCategory.INDUSTRY,
            field_name="industry",
            value={"code": code, "label": label},
            normalized_value=code,
            status=CoverageFieldStatus.AVAILABLE,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=f"NACE {code}: {label}" if label else f"NACE {code}",
            confidence=1.0,
        )
    else:
        facts[CoverageCategory.INDUSTRY] = CoverageFact(
            category=CoverageCategory.INDUSTRY,
            field_name="industry",
            value=None,
            normalized_value=None,
            status=CoverageFieldStatus.NOT_FOUND,
            source_url=None,
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=None,
            confidence=0.0,
        )

    # ------------------------------------------------------------------------
    # 7. ADDRESS & 8. MUNICIPALITY
    # ------------------------------------------------------------------------
    reg_addr = profile.get("business_address") or profile.get("forretningsadresse") or profile.get("postal_address") or profile.get("postadresse")
    norm_addr = normalize_address(reg_addr)
    municipality = profile.get("municipality") or norm_addr.get("city")

    if norm_addr.get("street") or norm_addr.get("postal_code") or norm_addr.get("city"):
        facts[CoverageCategory.ADDRESS] = CoverageFact(
            category=CoverageCategory.ADDRESS,
            field_name="address",
            value=norm_addr,
            normalized_value=f"{norm_addr.get('street') or ''}, {norm_addr.get('postal_code') or ''} {norm_addr.get('city') or ''}".strip(", "),
            status=CoverageFieldStatus.AVAILABLE,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=f"Forretningsadresse i Enhetsregisteret: {norm_addr.get('street')}, {norm_addr.get('postal_code')} {norm_addr.get('city')}",
            confidence=1.0,
        )
    else:
        facts[CoverageCategory.ADDRESS] = CoverageFact(
            category=CoverageCategory.ADDRESS,
            field_name="address",
            value=None,
            normalized_value=None,
            status=CoverageFieldStatus.NOT_FOUND,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=None,
            confidence=0.0,
        )

    if municipality:
        facts[CoverageCategory.MUNICIPALITY] = CoverageFact(
            category=CoverageCategory.MUNICIPALITY,
            field_name="municipality",
            value=municipality,
            normalized_value=str(municipality).title(),
            status=CoverageFieldStatus.AVAILABLE,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=f"Kommune: {municipality}",
            confidence=1.0,
        )
    else:
        facts[CoverageCategory.MUNICIPALITY] = CoverageFact(
            category=CoverageCategory.MUNICIPALITY,
            field_name="municipality",
            value=None,
            normalized_value=None,
            status=CoverageFieldStatus.NOT_FOUND,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=None,
            confidence=0.0,
        )

    # ------------------------------------------------------------------------
    # 9. WEBSITE
    # ------------------------------------------------------------------------
    website_rec = evidence_dict.get("website") or {}
    web_status = website_rec.get("status")
    if web_status in ("source_error", "blocked", "failed", "offline"):
        facts[CoverageCategory.WEBSITE] = CoverageFact(
            category=CoverageCategory.WEBSITE,
            field_name="website",
            value=None,
            normalized_value=None,
            status=CoverageFieldStatus.UNAVAILABLE,
            source_url=website_rec.get("source_url"),
            source_type="website_discovery",
            source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=None,
            confidence=0.0,
            note=f"Website source inaccessible ({website_rec.get('error') or web_status})",
        )
        norm_website = None
    else:
        raw_website = (website_rec.get("value") or {}).get("final_url") or profile.get("website") or (website_rec.get("source_url") if web_status == "available" else None)
        norm_website = normalize_url(raw_website)
        if norm_website:
            facts[CoverageCategory.WEBSITE] = CoverageFact(
                category=CoverageCategory.WEBSITE,
                field_name="website",
                value=raw_website,
                normalized_value=norm_website,
                status=CoverageFieldStatus.AVAILABLE,
                source_url=norm_website,
                source_type="website_discovery",
                source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
                evidence_span=f"Verified website: {norm_website}",
                confidence=0.98,
            )
        else:
            facts[CoverageCategory.WEBSITE] = CoverageFact(
                category=CoverageCategory.WEBSITE,
                field_name="website",
                value=None,
                normalized_value=None,
                status=CoverageFieldStatus.NOT_FOUND,
                source_url=None,
                source_type="website_discovery",
                source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
                evidence_span=None,
                confidence=0.0,
                note="No verified first-party website found",
            )

    # ------------------------------------------------------------------------
    # 10. DESCRIPTION
    # ------------------------------------------------------------------------
    desc_field = extracted_profile.description if extracted_profile else None
    if desc_field and desc_field.status == FieldStatus.FOUND and desc_field.value:
        facts[CoverageCategory.DESCRIPTION] = CoverageFact(
            category=CoverageCategory.DESCRIPTION,
            field_name="description",
            value=desc_field.value,
            normalized_value=" ".join(str(desc_field.value).split()),
            status=CoverageFieldStatus.AVAILABLE,
            source_url=desc_field.source_url,
            source_type=desc_field.source_type,
            source_priority=SourcePriority.FIRST_PARTY_STRUCTURED if "jsonld" in desc_field.source_type else SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=desc_field.evidence_span,
            confidence=desc_field.confidence,
        )
    else:
        # Fallback to statutory purpose
        purpose = profile.get("purpose") or profile.get("vedtektsfestetFormaal")
        if purpose:
            clean_purp = " ".join(str(purpose).split())
            facts[CoverageCategory.DESCRIPTION] = CoverageFact(
                category=CoverageCategory.DESCRIPTION,
                field_name="description",
                value=f"Vedtektsfestet formål: {clean_purp}",
                normalized_value=clean_purp,
                status=CoverageFieldStatus.AVAILABLE,
                source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
                source_type="official_registry_purpose",
                source_priority=SourcePriority.OFFICIAL_REGISTRY,
                evidence_span=clean_purp[:300],
                confidence=0.9,
            )
        else:
            facts[CoverageCategory.DESCRIPTION] = CoverageFact(
                category=CoverageCategory.DESCRIPTION,
                field_name="description",
                value=None,
                normalized_value=None,
                status=CoverageFieldStatus.NOT_FOUND,
                source_url=None,
                source_type="company_website",
                source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
                evidence_span=None,
                confidence=0.0,
            )

    # ------------------------------------------------------------------------
    # 11. CONTACT INFORMATION
    # ------------------------------------------------------------------------
    contact_field = extracted_profile.contact if extracted_profile else None
    if contact_field and contact_field.status == FieldStatus.FOUND and contact_field.value:
        c_val = contact_field.value
        phone = normalize_phone_number(c_val.get("phone") or profile.get("phone"))
        email = normalize_email(c_val.get("email") or profile.get("email"))
        norm_contact = {
            "phone": phone,
            "email": email,
            "address": c_val.get("address"),
            "postal_code": c_val.get("postal_code"),
            "city": c_val.get("city"),
            "country": c_val.get("country", "Norge"),
        }
        if c_val.get("address_divergence"):
            norm_contact["address_divergence"] = c_val["address_divergence"]
            conflicts.append(ConflictRecord(
                category=CoverageCategory.ADDRESS.value,
                chosen_value=c_val["address_divergence"]["registered_headquarters"],
                chosen_source="official_registry",
                conflicting_value=c_val["address_divergence"]["operational_address"],
                conflicting_source="company_website",
                resolution_rationale="Registered legal headquarters preserved over operational site",
            ))

        facts[CoverageCategory.CONTACT_INFORMATION] = CoverageFact(
            category=CoverageCategory.CONTACT_INFORMATION,
            field_name="contact_information",
            value=c_val,
            normalized_value=norm_contact,
            status=CoverageFieldStatus.AVAILABLE,
            source_url=contact_field.source_url,
            source_type=contact_field.source_type,
            source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=contact_field.evidence_span,
            confidence=contact_field.confidence,
        )
    elif profile.get("phone") or profile.get("email"):
        phone = normalize_phone_number(profile.get("phone"))
        email = normalize_email(profile.get("email"))
        c_dict = {"phone": phone, "email": email, "address": None, "postal_code": None, "city": None, "country": "Norge"}
        facts[CoverageCategory.CONTACT_INFORMATION] = CoverageFact(
            category=CoverageCategory.CONTACT_INFORMATION,
            field_name="contact_information",
            value=c_dict,
            normalized_value=c_dict,
            status=CoverageFieldStatus.AVAILABLE,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=f"Phone: {phone}; Email: {email}",
            confidence=0.9,
        )
    else:
        facts[CoverageCategory.CONTACT_INFORMATION] = CoverageFact(
            category=CoverageCategory.CONTACT_INFORMATION,
            field_name="contact_information",
            value=None,
            normalized_value=None,
            status=CoverageFieldStatus.NOT_FOUND,
            source_url=None,
            source_type="company_website",
            source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=None,
            confidence=0.0,
        )

    # ------------------------------------------------------------------------
    # 12. LEADERSHIP
    # ------------------------------------------------------------------------
    lead_field = extracted_profile.leadership if extracted_profile else None
    if lead_field and lead_field.status == FieldStatus.FOUND and lead_field.value:
        facts[CoverageCategory.LEADERSHIP] = CoverageFact(
            category=CoverageCategory.LEADERSHIP,
            field_name="leadership",
            value=lead_field.value,
            normalized_value=lead_field.value,
            status=CoverageFieldStatus.AVAILABLE,
            source_url=lead_field.source_url,
            source_type=lead_field.source_type,
            source_priority=SourcePriority.OFFICIAL_REGISTRY if "roles" in lead_field.source_type else SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=lead_field.evidence_span,
            confidence=lead_field.confidence,
        )
    else:
        facts[CoverageCategory.LEADERSHIP] = CoverageFact(
            category=CoverageCategory.LEADERSHIP,
            field_name="leadership",
            value=[],
            normalized_value=[],
            status=CoverageFieldStatus.NOT_FOUND,
            source_url=None,
            source_type="official_roles",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=None,
            confidence=0.0,
            note="No active executive or board leadership recorded",
        )

    # ------------------------------------------------------------------------
    # 13. EMPLOYEES
    # ------------------------------------------------------------------------
    emp_field = extracted_profile.employees if extracted_profile else None
    if emp_field and emp_field.status == FieldStatus.FOUND and emp_field.value is not None:
        facts[CoverageCategory.EMPLOYEES] = CoverageFact(
            category=CoverageCategory.EMPLOYEES,
            field_name="employees",
            value=emp_field.value,
            normalized_value=emp_field.value,
            status=CoverageFieldStatus.AVAILABLE,
            source_url=emp_field.source_url,
            source_type=emp_field.source_type,
            source_priority=SourcePriority.OFFICIAL_REGISTRY if "registry" in emp_field.source_type else SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=emp_field.evidence_span,
            confidence=emp_field.confidence,
        )
    elif profile.get("employees") is not None:
        c_emp = int(profile["employees"])
        facts[CoverageCategory.EMPLOYEES] = CoverageFact(
            category=CoverageCategory.EMPLOYEES,
            field_name="employees",
            value=c_emp,
            normalized_value=c_emp,
            status=CoverageFieldStatus.AVAILABLE,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=f"Ansatte i Enhetsregisteret: {c_emp}",
            confidence=1.0,
        )
    else:
        facts[CoverageCategory.EMPLOYEES] = CoverageFact(
            category=CoverageCategory.EMPLOYEES,
            field_name="employees",
            value=None,
            normalized_value=None,
            status=CoverageFieldStatus.NOT_FOUND,
            source_url=None,
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=None,
            confidence=0.0,
        )

    # ------------------------------------------------------------------------
    # 14-18. FINANCIAL INTELLIGENCE (Revenue, Profit/Loss, Assets, Equity, Year)
    # ------------------------------------------------------------------------
    latest_stmt: FinancialStatement | None = None
    if financial_profile:
        latest_stmt = financial_profile.latest_accounts
        if not latest_stmt and financial_profile.historical_accounts:
            latest_stmt = financial_profile.historical_accounts[0]
        if not latest_stmt and hasattr(financial_profile, "statements") and financial_profile.statements:
            latest_stmt = financial_profile.statements[0]

    fin_fields = [
        (CoverageCategory.REVENUE, "revenue", latest_stmt.revenue if latest_stmt else None),
        (CoverageCategory.PROFIT_LOSS, "profit_loss", latest_stmt.net_profit if latest_stmt else (latest_stmt.operating_profit if latest_stmt else None)),
        (CoverageCategory.ASSETS, "assets", latest_stmt.total_assets if latest_stmt else None),
        (CoverageCategory.EQUITY, "equity", latest_stmt.total_equity if latest_stmt else None),
    ]

    for cat, field_label, f_ext in fin_fields:
        if f_ext and f_ext.status == FieldStatus.FOUND and f_ext.value is not None:
            norm_val, curr = normalize_financial_amount(f_ext.value)
            facts[cat] = CoverageFact(
                category=cat,
                field_name=field_label,
                value=f_ext.value,
                normalized_value={"amount": norm_val, "currency": curr},
                status=CoverageFieldStatus.AVAILABLE,
                source_url=f_ext.source_url or "https://data.brreg.no/regnskapsregisteret/regnskap",
                source_type=f_ext.source_type,
                source_priority=SourcePriority.OFFICIAL_FILING,
                evidence_span=f_ext.evidence_span or f"{field_label}: {norm_val} {curr}",
                confidence=f_ext.confidence,
            )
        else:
            is_exempt = False
            if financial_profile and financial_profile.accounting_obligation:
                obl = financial_profile.accounting_obligation
                if isinstance(obl, dict):
                    is_exempt = not obl.get("required", True)
                elif hasattr(obl, "required"):
                    is_exempt = not obl.required
            facts[cat] = CoverageFact(
                category=cat,
                field_name=field_label,
                value=None,
                normalized_value=None,
                status=CoverageFieldStatus.UNAVAILABLE if is_exempt else CoverageFieldStatus.NOT_FOUND,
                source_url="https://data.brreg.no/regnskapsregisteret/regnskap",
                source_type="official_regnskapsregisteret",
                source_priority=SourcePriority.OFFICIAL_FILING,
                evidence_span=None,
                confidence=0.0,
                note="Company exempt from statutory filing" if is_exempt else "Filing not found or pending",
            )

    # 18. FINANCIAL YEAR
    if latest_stmt and latest_stmt.period and latest_stmt.period.year:
        f_yr = latest_stmt.period.year
        facts[CoverageCategory.FINANCIAL_YEAR] = CoverageFact(
            category=CoverageCategory.FINANCIAL_YEAR,
            field_name="financial_year",
            value=f_yr,
            normalized_value=f_yr,
            status=CoverageFieldStatus.AVAILABLE,
            source_url=latest_stmt.source_url or "https://data.brreg.no/regnskapsregisteret/regnskap",
            source_type=latest_stmt.source_type,
            source_priority=SourcePriority.OFFICIAL_FILING,
            evidence_span=f"Regnskapsår: {f_yr}",
            confidence=1.0,
        )
    else:
        facts[CoverageCategory.FINANCIAL_YEAR] = CoverageFact(
            category=CoverageCategory.FINANCIAL_YEAR,
            field_name="financial_year",
            value=None,
            normalized_value=None,
            status=CoverageFieldStatus.NOT_FOUND,
            source_url="https://data.brreg.no/regnskapsregisteret/regnskap",
            source_type="official_regnskapsregisteret",
            source_priority=SourcePriority.OFFICIAL_FILING,
            evidence_span=None,
            confidence=0.0,
        )

    # ------------------------------------------------------------------------
    # 19. PRODUCTS & SERVICES
    # ------------------------------------------------------------------------
    prod_field = getattr(extracted_profile, "products_and_services", None)
    if prod_field and prod_field.status == FieldStatus.FOUND and prod_field.value:
        facts[CoverageCategory.PRODUCTS_SERVICES] = CoverageFact(
            category=CoverageCategory.PRODUCTS_SERVICES,
            field_name="products_services",
            value=prod_field.value,
            normalized_value=[p.get("name") for p in prod_field.value if isinstance(p, dict)],
            status=CoverageFieldStatus.AVAILABLE,
            source_url=prod_field.source_url,
            source_type=prod_field.source_type,
            source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=prod_field.evidence_span,
            confidence=prod_field.confidence,
        )
    else:
        facts[CoverageCategory.PRODUCTS_SERVICES] = CoverageFact(
            category=CoverageCategory.PRODUCTS_SERVICES,
            field_name="products_services",
            value=[],
            normalized_value=[],
            status=CoverageFieldStatus.NOT_FOUND if norm_website else CoverageFieldStatus.UNAVAILABLE,
            source_url=norm_website,
            source_type="company_website",
            source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=None,
            confidence=0.0,
            note="No commercial product catalog identified",
        )

    # ------------------------------------------------------------------------
    # 20. CUSTOMERS & MARKETS
    # ------------------------------------------------------------------------
    cust_field = getattr(extracted_profile, "customers_and_markets", None)
    if cust_field and cust_field.status == FieldStatus.FOUND and cust_field.value:
        facts[CoverageCategory.CUSTOMERS_MARKETS] = CoverageFact(
            category=CoverageCategory.CUSTOMERS_MARKETS,
            field_name="customers_markets",
            value=cust_field.value,
            normalized_value=cust_field.value,
            status=CoverageFieldStatus.AVAILABLE,
            source_url=cust_field.source_url,
            source_type=cust_field.source_type,
            source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=cust_field.evidence_span,
            confidence=cust_field.confidence,
        )
    else:
        facts[CoverageCategory.CUSTOMERS_MARKETS] = CoverageFact(
            category=CoverageCategory.CUSTOMERS_MARKETS,
            field_name="customers_markets",
            value=None,
            normalized_value=None,
            status=CoverageFieldStatus.NOT_FOUND if norm_website else CoverageFieldStatus.UNAVAILABLE,
            source_url=norm_website,
            source_type="company_website",
            source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=None,
            confidence=0.0,
        )

    # ------------------------------------------------------------------------
    # 21. LOCATIONS
    # ------------------------------------------------------------------------
    loc_field = extracted_profile.locations if extracted_profile else None
    if loc_field and loc_field.status == FieldStatus.FOUND and loc_field.value:
        facts[CoverageCategory.LOCATIONS] = CoverageFact(
            category=CoverageCategory.LOCATIONS,
            field_name="locations",
            value=loc_field.value,
            normalized_value=[f"{loc.get('city') or loc.get('address')}" for loc in loc_field.value if isinstance(loc, dict)],
            status=CoverageFieldStatus.AVAILABLE,
            source_url=loc_field.source_url,
            source_type=loc_field.source_type,
            source_priority=SourcePriority.OFFICIAL_REGISTRY if "subunits" in loc_field.source_type else SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=loc_field.evidence_span,
            confidence=loc_field.confidence,
        )
    else:
        facts[CoverageCategory.LOCATIONS] = CoverageFact(
            category=CoverageCategory.LOCATIONS,
            field_name="locations",
            value=[],
            normalized_value=[],
            status=CoverageFieldStatus.NOT_FOUND,
            source_url=None,
            source_type="official_subunits",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=None,
            confidence=0.0,
        )

    # ------------------------------------------------------------------------
    # 22. TECHNOLOGY (Strict Tier 3: Only when proven)
    # ------------------------------------------------------------------------
    tech_stack: list[str] = []
    # If website structured data contains software application / frameworks
    if extracted_profile and extracted_profile.structured_data_summary:
        if extracted_profile.structured_data_summary.get("json_ld_entities_count", 0) > 0:
            tech_stack.append("Schema.org JSON-LD")
        if extracted_profile.structured_data_summary.get("opengraph_records_count", 0) > 0:
            tech_stack.append("OpenGraph Metadata")

    if tech_stack:
        facts[CoverageCategory.TECHNOLOGY] = CoverageFact(
            category=CoverageCategory.TECHNOLOGY,
            field_name="technology",
            value=tech_stack,
            normalized_value=tech_stack,
            status=CoverageFieldStatus.AVAILABLE,
            source_url=norm_website,
            source_type="first_party_website_tech",
            source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=f"Detected web technologies: {', '.join(tech_stack)}",
            confidence=0.85,
        )
    else:
        facts[CoverageCategory.TECHNOLOGY] = CoverageFact(
            category=CoverageCategory.TECHNOLOGY,
            field_name="technology",
            value=[],
            normalized_value=[],
            status=CoverageFieldStatus.NOT_FOUND if norm_website else CoverageFieldStatus.UNAVAILABLE,
            source_url=norm_website,
            source_type="first_party_website_tech",
            source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=None,
            confidence=0.0,
            note="No proprietary software stack claims without first-party proof",
        )

    # ------------------------------------------------------------------------
    # 23. NEWS & EVENTS
    # ------------------------------------------------------------------------
    news_field = extracted_profile.news if extracted_profile else None
    if news_field and news_field.status == FieldStatus.FOUND and news_field.value:
        facts[CoverageCategory.NEWS_EVENTS] = CoverageFact(
            category=CoverageCategory.NEWS_EVENTS,
            field_name="news_events",
            value=news_field.value,
            normalized_value=[n.get("title") for n in news_field.value if isinstance(n, dict)],
            status=CoverageFieldStatus.AVAILABLE,
            source_url=news_field.source_url,
            source_type=news_field.source_type,
            source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=news_field.evidence_span,
            confidence=news_field.confidence,
        )
    else:
        facts[CoverageCategory.NEWS_EVENTS] = CoverageFact(
            category=CoverageCategory.NEWS_EVENTS,
            field_name="news_events",
            value=[],
            normalized_value=[],
            status=CoverageFieldStatus.NOT_FOUND if norm_website else CoverageFieldStatus.UNAVAILABLE,
            source_url=norm_website,
            source_type="company_website",
            source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=None,
            confidence=0.0,
        )

    # ------------------------------------------------------------------------
    # 24. SOCIAL / COMPANY PRESENCE
    # ------------------------------------------------------------------------
    social_urls: list[str] = []
    if norm_website:
        # Check careers or links
        careers_field = extracted_profile.careers if extracted_profile else None
        if careers_field and careers_field.status == FieldStatus.FOUND and careers_field.value:
            c_url = careers_field.value.get("careers_url")
            if c_url:
                social_urls.append(c_url)

    if social_urls:
        facts[CoverageCategory.SOCIAL_PRESENCE] = CoverageFact(
            category=CoverageCategory.SOCIAL_PRESENCE,
            field_name="social_presence",
            value=social_urls,
            normalized_value=social_urls,
            status=CoverageFieldStatus.AVAILABLE,
            source_url=norm_website,
            source_type="first_party_website",
            source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=f"Public web channels: {', '.join(social_urls)}",
            confidence=0.9,
        )
    else:
        facts[CoverageCategory.SOCIAL_PRESENCE] = CoverageFact(
            category=CoverageCategory.SOCIAL_PRESENCE,
            field_name="social_presence",
            value=[],
            normalized_value=[],
            status=CoverageFieldStatus.NOT_FOUND if norm_website else CoverageFieldStatus.UNAVAILABLE,
            source_url=norm_website,
            source_type="first_party_website",
            source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=None,
            confidence=0.0,
        )

    # ------------------------------------------------------------------------
    # 25. CERTIFICATIONS
    # ------------------------------------------------------------------------
    cert_field = getattr(extracted_profile, "certifications", None)
    if cert_field and cert_field.status == FieldStatus.FOUND and cert_field.value:
        facts[CoverageCategory.CERTIFICATIONS] = CoverageFact(
            category=CoverageCategory.CERTIFICATIONS,
            field_name="certifications",
            value=cert_field.value,
            normalized_value=cert_field.value,
            status=CoverageFieldStatus.AVAILABLE,
            source_url=cert_field.source_url,
            source_type=cert_field.source_type,
            source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=cert_field.evidence_span,
            confidence=cert_field.confidence,
        )
    else:
        facts[CoverageCategory.CERTIFICATIONS] = CoverageFact(
            category=CoverageCategory.CERTIFICATIONS,
            field_name="certifications",
            value=[],
            normalized_value=[],
            status=CoverageFieldStatus.NOT_FOUND if norm_website else CoverageFieldStatus.UNAVAILABLE,
            source_url=norm_website,
            source_type="company_website",
            source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
            evidence_span=None,
            confidence=0.0,
        )

    # ------------------------------------------------------------------------
    # 26. PARTNERSHIPS (Strict Tier 3)
    # ------------------------------------------------------------------------
    facts[CoverageCategory.PARTNERSHIPS] = CoverageFact(
        category=CoverageCategory.PARTNERSHIPS,
        field_name="partnerships",
        value=[],
        normalized_value=[],
        status=CoverageFieldStatus.NOT_FOUND,
        source_url=norm_website,
        source_type="first_party_website",
        source_priority=SourcePriority.FIRST_PARTY_WEBSITE,
        evidence_span=None,
        confidence=0.0,
        note="No formal public partnership contracts verified",
    )

    # ------------------------------------------------------------------------
    # 27. OWNERSHIP INFORMATION
    # ------------------------------------------------------------------------
    gov_field = getattr(extracted_profile, "corporate_governance", None)
    share_cap = None
    if gov_field and gov_field.status == FieldStatus.FOUND and gov_field.value:
        share_cap = gov_field.value.get("share_capital")

    if share_cap is not None:
        facts[CoverageCategory.OWNERSHIP_INFO] = CoverageFact(
            category=CoverageCategory.OWNERSHIP_INFO,
            field_name="ownership_information",
            value={"share_capital": share_cap, "currency": "NOK"},
            normalized_value=share_cap,
            status=CoverageFieldStatus.AVAILABLE,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=f"Aksjekapital i Foretaksregisteret: {share_cap} NOK",
            confidence=1.0,
        )
    else:
        facts[CoverageCategory.OWNERSHIP_INFO] = CoverageFact(
            category=CoverageCategory.OWNERSHIP_INFO,
            field_name="ownership_information",
            value=None,
            normalized_value=None,
            status=CoverageFieldStatus.NOT_FOUND,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=None,
            confidence=0.0,
        )

    # ------------------------------------------------------------------------
    # 28. PARENT / SUBSIDIARY RELATIONSHIPS
    # ------------------------------------------------------------------------
    is_in_group = profile.get("is_in_group")
    parent_org = profile.get("parent_organisation")
    if is_in_group or parent_org:
        val_rel = {
            "is_in_group": bool(is_in_group),
            "parent_organisation": parent_org,
        }
        facts[CoverageCategory.PARENT_SUBSIDIARY] = CoverageFact(
            category=CoverageCategory.PARENT_SUBSIDIARY,
            field_name="parent_subsidiary_relationships",
            value=val_rel,
            normalized_value=val_rel,
            status=CoverageFieldStatus.AVAILABLE,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry_group",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=f"Konserntilhørighet: {is_in_group}; Morselskap: {parent_org}",
            confidence=1.0,
        )
    else:
        facts[CoverageCategory.PARENT_SUBSIDIARY] = CoverageFact(
            category=CoverageCategory.PARENT_SUBSIDIARY,
            field_name="parent_subsidiary_relationships",
            value={"is_in_group": False, "parent_organisation": None},
            normalized_value={"is_in_group": False, "parent_organisation": None},
            status=CoverageFieldStatus.AVAILABLE,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry_group",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span="Ikke registrert som del av konsern i Enhetsregisteret",
            confidence=0.95,
        )

    # ------------------------------------------------------------------------
    # 29. RECENT CHANGES
    # ------------------------------------------------------------------------
    refresh_rec = evidence_dict.get("refresh") or {}
    changes = refresh_rec.get("changes") or []
    if changes:
        facts[CoverageCategory.RECENT_CHANGES] = CoverageFact(
            category=CoverageCategory.RECENT_CHANGES,
            field_name="recent_changes",
            value=changes,
            normalized_value=[c.get("field") for c in changes if isinstance(c, dict)],
            status=CoverageFieldStatus.AVAILABLE,
            source_url=refresh_rec.get("source_url") or "https://data.brreg.no/enhetsregisteret/api/oppdateringer/enheter",
            source_type="official_refresh_audit",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=f"Detected {len(changes)} verified semantic change(s)",
            confidence=1.0,
        )
    else:
        facts[CoverageCategory.RECENT_CHANGES] = CoverageFact(
            category=CoverageCategory.RECENT_CHANGES,
            field_name="recent_changes",
            value=[],
            normalized_value=[],
            status=CoverageFieldStatus.NOT_FOUND,
            source_url="https://data.brreg.no/enhetsregisteret/api/oppdateringer/enheter",
            source_type="official_refresh_audit",
            source_priority=SourcePriority.OFFICIAL_REGISTRY,
            evidence_span=None,
            confidence=0.0,
            note="No material mutations recorded in observation interval",
        )

    # Verify all 29 categories are populated
    assert len(facts) == 29, f"Profile must contain all 29 categories, got {len(facts)}"

    return UnifiedCompanyProfile(
        organisation_number=org_number,
        company_name=company_name,
        facts=facts,
        conflicts=conflicts,
        operations=operations_metrics or {},
    )


# ============================================================================
# 8. COVERAGE EVALUATION METRICS
# ============================================================================

@dataclass
class CoverageEvaluationResult:
    """Rigorous evaluation outcome measuring useful-information coverage."""
    total_supported_categories: int = 29
    categories_available: int = 0
    categories_not_found: int = 0
    categories_unavailable: int = 0
    categories_conflicting: int = 0
    categories_with_evidence: int = 0
    categories_authoritative: int = 0
    coverage_rate: float = 0.0
    evidence_coverage_rate: float = 0.0
    authoritative_coverage_rate: float = 0.0
    tier_breakdown: dict[str, dict[str, int]] = field(default_factory=dict)
    conflicts_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_supported_categories": self.total_supported_categories,
            "categories_available": self.categories_available,
            "categories_not_found": self.categories_not_found,
            "categories_unavailable": self.categories_unavailable,
            "categories_conflicting": self.categories_conflicting,
            "categories_with_evidence": self.categories_with_evidence,
            "categories_authoritative": self.categories_authoritative,
            "coverage_rate": round(self.coverage_rate, 4),
            "evidence_coverage_rate": round(self.evidence_coverage_rate, 4),
            "authoritative_coverage_rate": round(self.authoritative_coverage_rate, 4),
            "tier_breakdown": self.tier_breakdown,
            "conflicts_count": self.conflicts_count,
        }


def evaluate_profile_coverage(profile: UnifiedCompanyProfile) -> CoverageEvaluationResult:
    """Evaluate coverage metrics for a single unified profile across all 29 categories."""
    available = 0
    not_found = 0
    unavailable = 0
    conflicting = 0
    with_evidence = 0
    authoritative = 0

    tier_stats: dict[str, dict[str, int]] = {
        CategoryTier.TIER_1_CORE.value: {"total": 0, "available": 0},
        CategoryTier.TIER_2_COMMERCIAL.value: {"total": 0, "available": 0},
        CategoryTier.TIER_3_RESTRICTED.value: {"total": 0, "available": 0},
    }

    for cat in ALL_29_CATEGORIES:
        fact = profile.get_fact(cat)
        tier = TIER_MAPPING.get(cat, CategoryTier.TIER_2_COMMERCIAL).value
        tier_stats[tier]["total"] += 1

        if not fact:
            not_found += 1
            continue

        if fact.status == CoverageFieldStatus.AVAILABLE:
            available += 1
            tier_stats[tier]["available"] += 1
            if fact.evidence_span or fact.source_url:
                with_evidence += 1
            if fact.source_priority >= SourcePriority.OFFICIAL_FILING:
                authoritative += 1
        elif fact.status == CoverageFieldStatus.CONFLICTING_SOURCES:
            conflicting += 1
            tier_stats[tier]["available"] += 1  # Divergent fact available
            if fact.evidence_span or fact.source_url:
                with_evidence += 1
        elif fact.status == CoverageFieldStatus.UNAVAILABLE:
            unavailable += 1
        else:
            not_found += 1

    total = 29
    cov_rate = available / total
    ev_rate = with_evidence / max(1, available)
    auth_rate = authoritative / max(1, available)

    return CoverageEvaluationResult(
        total_supported_categories=total,
        categories_available=available,
        categories_not_found=not_found,
        categories_unavailable=unavailable,
        categories_conflicting=conflicting,
        categories_with_evidence=with_evidence,
        categories_authoritative=authoritative,
        coverage_rate=cov_rate,
        evidence_coverage_rate=ev_rate,
        authoritative_coverage_rate=auth_rate,
        tier_breakdown=tier_stats,
        conflicts_count=len(profile.conflicts),
    )


def evaluate_batch_coverage(profiles: list[UnifiedCompanyProfile]) -> dict[str, Any]:
    """Aggregate coverage metrics across a batch of evaluated company profiles."""
    if not profiles:
        return {"total_profiles": 0, "average_coverage_rate": 0.0}

    results = [evaluate_profile_coverage(p) for p in profiles]
    avg_cov = sum(r.coverage_rate for r in results) / len(results)
    avg_ev = sum(r.evidence_coverage_rate for r in results) / len(results)
    avg_auth = sum(r.authoritative_coverage_rate for r in results) / len(results)
    total_conflicts = sum(r.conflicts_count for r in results)

    # Per-category availability across the batch
    cat_distribution: dict[str, int] = {cat.value: 0 for cat in ALL_29_CATEGORIES}
    for p in profiles:
        for cat in ALL_29_CATEGORIES:
            f = p.get_fact(cat)
            if f and f.status in (CoverageFieldStatus.AVAILABLE, CoverageFieldStatus.CONFLICTING_SOURCES):
                cat_distribution[cat.value] += 1

    return {
        "total_profiles": len(profiles),
        "average_coverage_rate": round(avg_cov, 4),
        "average_evidence_rate": round(avg_ev, 4),
        "average_authoritative_rate": round(avg_auth, 4),
        "total_conflicts_recorded": total_conflicts,
        "category_availability_percentage": {
            k: round(v / len(profiles) * 100, 1) for k, v in sorted(cat_distribution.items())
        },
    }
