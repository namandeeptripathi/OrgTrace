from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Generic, TypeVar

from bs4 import BeautifulSoup
import extruct

from .evidence import evidence
from .identity_engine import canonicalize_org_number, normalize_legal_name

T = TypeVar("T")

# ============================================================================
# 1. FIELD STATUS & EXTRACTION DATA MODELS
# ============================================================================

class FieldStatus(str, Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    EXTRACTION_FAILED = "extraction_failed"
    CONFLICTING = "conflicting_sources"


@dataclass
class ExtractedField(Generic[T]):
    field_name: str
    value: T | None
    status: FieldStatus
    source_url: str | None = None
    source_type: str = "unknown"
    evidence_span: str | None = None
    confidence: float = 0.0
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "value": self.value,
            "status": self.status.value,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "evidence_span": self.evidence_span,
            "confidence": round(self.confidence, 3),
            "note": self.note,
        }


@dataclass
class ExtractedCompanyProfile:
    organisation_number: str
    company_name: str
    description: ExtractedField[str]
    industry: ExtractedField[dict[str, Any]]
    contact: ExtractedField[dict[str, Any]]
    locations: ExtractedField[list[dict[str, Any]]]
    leadership: ExtractedField[list[dict[str, Any]]]
    employees: ExtractedField[int | str]
    careers: ExtractedField[dict[str, Any]]
    news: ExtractedField[list[dict[str, Any]]]
    structured_data_summary: dict[str, Any] = field(default_factory=dict)
    overall_status: str = "complete"
    # Stage 14 Coverage Expansion fields:
    products_and_services: ExtractedField[list[dict[str, Any]]] = field(
        default_factory=lambda: ExtractedField("products_and_services", [], FieldStatus.UNAVAILABLE, note="Products and services source unavailable")
    )
    customers_and_markets: ExtractedField[dict[str, Any]] = field(
        default_factory=lambda: ExtractedField("customers_and_markets", None, FieldStatus.UNAVAILABLE, note="Customer and market source unavailable")
    )
    certifications: ExtractedField[list[str]] = field(
        default_factory=lambda: ExtractedField("certifications", [], FieldStatus.UNAVAILABLE, note="Certifications source unavailable")
    )
    corporate_governance: ExtractedField[dict[str, Any]] = field(
        default_factory=lambda: ExtractedField("corporate_governance", None, FieldStatus.UNAVAILABLE, note="Corporate governance source unavailable")
    )
    people: ExtractedField[list[dict[str, Any]]] = field(
        default_factory=lambda: ExtractedField("people", [], FieldStatus.UNAVAILABLE, note="People/roles source unavailable")
    )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "organisation_number": self.organisation_number,
            "company_name": self.company_name,
            "description": self.description.to_dict(),
            "industry": self.industry.to_dict(),
            "contact": self.contact.to_dict(),
            "locations": self.locations.to_dict(),
            "leadership": self.leadership.to_dict(),
            "employees": self.employees.to_dict(),
            "careers": self.careers.to_dict(),
            "news": self.news.to_dict(),
            "structured_data_summary": self.structured_data_summary,
            "overall_status": self.overall_status,
        }
        if self.products_and_services is not None:
            data["products_and_services"] = self.products_and_services.to_dict()
        if self.customers_and_markets is not None:
            data["customers_and_markets"] = self.customers_and_markets.to_dict()
        if self.certifications is not None:
            data["certifications"] = self.certifications.to_dict()
        if self.corporate_governance is not None:
            data["corporate_governance"] = self.corporate_governance.to_dict()
        if self.people is not None:
            data["people"] = self.people.to_dict()
        return data


# ============================================================================
# 2. STRUCTURED DATA & HTML EXTRACTION UTILITIES
# ============================================================================

EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_REGEX = re.compile(r"(?:\+47\s*)?(?:[2-9]\d{1}(?:\s*\d{2}){3}|[2-9]\d{2}(?:\s*\d{2}){2}|[2-9]\d{7})")
NORWEGIAN_POSTAL_REGEX = re.compile(r"\b(\d{4})\s+([A-ZÆØÅa-zæøå\s-]+)\b")

CAREERS_PATH = re.compile(
    r"/(?:karriere|careers|career|jobs|jobb|job|stillinger|stilling|ledige-stillinger|ledige_stillinger|jobbe-hos-oss|bli-en-av-oss|arbeide-hos-oss|work-with-us|work_with_us|work|hiring|vacancies|rekruttering)(?:/|$|[?#])",
    re.I,
)
NEWS_PATH = re.compile(
    r"/(?:news|press|presse|aktuelt|nyheter|pressemeldinger|pressemelding|artikler|blog|media|siste-nytt|nyhetsarkiv|medieomtale)(?:/|$|[?#])",
    re.I,
)

LEADERSHIP_ROLES = (
    "ceo", "chief executive officer", "daglig leder", "adm. dir", "administrerende direktør",
    "styreleder", "chair", "chairman", "board chair", "chair of the board", "styrets leder",
    "nestleder", "vice chair", "cfo", "chief financial officer", "økonomidirektør",
    "cto", "chief technology officer", "teknologidirektør", "founder", "co-founder",
    "gründer", "medgründer", "director", "direktør", "managing director", "partner",
)


def _walk_structured_data(data: Any, target_types: set[str]) -> list[dict[str, Any]]:
    """Recursively find schema.org entities matching target_types."""
    results: list[dict[str, Any]] = []
    if isinstance(data, dict):
        kind = data.get("@type")
        kinds = set(kind if isinstance(kind, list) else [kind])
        if kinds & target_types:
            results.append(data)
        for val in data.values():
            results.extend(_walk_structured_data(val, target_types))
    elif isinstance(data, list):
        for item in data:
            results.extend(_walk_structured_data(item, target_types))
    return results


def _extract_all_structured(html: str, base_url: str = "") -> dict[str, Any]:
    """Safely extract JSON-LD, Microdata, and OpenGraph from HTML."""
    if not html.strip():
        return {"json-ld": [], "microdata": [], "opengraph": []}
    try:
        return extruct.extract(html, base_url=base_url, syntaxes=["json-ld", "microdata", "opengraph"])
    except Exception:
        # Fallback manual JSON-LD extraction
        items = []
        soup = BeautifulSoup(html, "lxml")
        for tag in soup.select('script[type="application/ld+json"]'):
            try:
                body = json.loads(tag.get_text())
                items.extend(body if isinstance(body, list) else [body])
            except Exception:
                continue
        return {"json-ld": items, "microdata": [], "opengraph": []}


# ============================================================================
# 3. DOMAIN-SPECIFIC EXTRACTORS
# ============================================================================

def extract_description(
    profile: dict[str, Any],
    website_value: dict[str, Any] | None,
    structured_data: dict[str, Any],
    homepage_url: str | None,
) -> ExtractedField[str]:
    """Extract official company description with provenance."""
    # 1. JSON-LD description
    if structured_data:
        org_entities = _walk_structured_data(
            structured_data.get("json-ld", []),
            {"Organization", "Corporation", "LocalBusiness", "WebSite"},
        )
        for org in org_entities:
            desc = org.get("description")
            if isinstance(desc, str) and len(desc.strip()) > 15:
                clean_desc = " ".join(desc.strip().split())
                return ExtractedField(
                    field_name="description",
                    value=clean_desc[:1000],
                    status=FieldStatus.FOUND,
                    source_url=homepage_url,
                    source_type="website_jsonld",
                    evidence_span=clean_desc[:300],
                    confidence=0.95,
                )

    # 2. Meta description / og:description from homepage
    if website_value:
        meta_desc = str(website_value.get("description") or "").strip()
        if len(meta_desc) > 15:
            clean_desc = " ".join(meta_desc.split())
            return ExtractedField(
                field_name="description",
                value=clean_desc[:1000],
                status=FieldStatus.FOUND,
                source_url=homepage_url,
                source_type="website_meta_description",
                evidence_span=clean_desc[:300],
                confidence=0.9,
            )

        # 3. First-party about page text
        for page in website_value.get("pages", []):
            p_url = str(page.get("url") or "")
            if any(keyword in p_url.lower() for keyword in ("om-oss", "om_oss", "about")):
                text = str(page.get("main_text_excerpt") or "").strip()
                if len(text) > 20:
                    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 20]
                    first_para = paragraphs[0] if paragraphs else text
                    clean_para = " ".join(first_para.split())
                    return ExtractedField(
                        field_name="description",
                        value=clean_para[:1000],
                        status=FieldStatus.FOUND,
                        source_url=p_url,
                        source_type="website_about_page",
                        evidence_span=clean_para[:300],
                        confidence=0.85,
                    )

        # 4. Homepage main text excerpt introductory line
        main_text = str(website_value.get("main_text_excerpt") or "").strip()
        if len(main_text) > 30:
            lines = [line.strip() for line in main_text.splitlines() if len(line.strip()) > 30]
            if lines:
                clean_line = " ".join(lines[0].split())
                return ExtractedField(
                    field_name="description",
                    value=clean_line[:1000],
                    status=FieldStatus.FOUND,
                    source_url=homepage_url,
                    source_type="website_homepage_text",
                    evidence_span=clean_line[:300],
                    confidence=0.75,
                )

    # 5. Fallback to official statutory purpose from articles of association
    purpose = profile.get("purpose")
    if purpose and not website_value:
        clean_purpose = " ".join(str(purpose).split())
        return ExtractedField(
            field_name="description",
            value=f"Vedtektsfestet formål: {clean_purpose[:1000]}",
            status=FieldStatus.FOUND,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry_purpose",
            evidence_span=clean_purpose[:300],
            confidence=0.9,
            note="Official statutory corporate purpose from Brønnøysundregistrene",
        )

    # 6. Fallback to registered activity
    activity = profile.get("activity")
    if activity and not website_value:
        clean_act = " ".join(str(activity).split())
        return ExtractedField(
            field_name="description",
            value=f"Registrert aktivitet: {clean_act[:1000]}",
            status=FieldStatus.FOUND,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry_activity",
            evidence_span=clean_act[:300],
            confidence=0.85,
            note="Official registered activity from Brønnøysundregistrene",
        )

    # 7. Fallback to official registry industry label if present
    ind_label = profile.get("industry_label")
    if ind_label and not website_value:
        return ExtractedField(
            field_name="description",
            value=f"Registrert virksomhet: {ind_label}",
            status=FieldStatus.FOUND,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            evidence_span=ind_label,
            confidence=0.7,
        )

    if not website_value and not (structured_data and structured_data.get("json-ld")):
        return ExtractedField(
            field_name="description",
            value=None,
            status=FieldStatus.UNAVAILABLE,
            source_type="company_website",
            note="Website is unavailable or not verified",
        )

    return ExtractedField(
        field_name="description",
        value=None,
        status=FieldStatus.NOT_FOUND,
        source_url=homepage_url,
        source_type="company_website",
        note="Website inspected but no company description found",
    )


def extract_industry(
    profile: dict[str, Any],
    website_value: dict[str, Any] | None,
    structured_data: dict[str, Any],
    homepage_url: str | None,
) -> ExtractedField[dict[str, Any]]:
    """Extract industry with code, label, and authoritative provenance."""
    # 1. Official BRREG registry NACE code & description (primary ground truth)
    ind_code = profile.get("industry_code") or profile.get("industry")
    ind_label = profile.get("industry_label")

    if ind_code or ind_label:
        code_str = str(ind_code) if ind_code else None
        label_str = str(ind_label) if ind_label else None
        return ExtractedField(
            field_name="industry",
            value={"code": code_str, "label": label_str, "system": "NACE / Næringskode"},
            status=FieldStatus.FOUND,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            evidence_span=f"NACE {code_str}: {label_str}" if code_str else label_str,
            confidence=1.0,
        )

    # 2. Structured data JSON-LD (knowsAbout / industry)
    if structured_data:
        org_entities = _walk_structured_data(
            structured_data.get("json-ld", []),
            {"Organization", "Corporation", "LocalBusiness"},
        )
        for org in org_entities:
            industry_val = org.get("industry") or org.get("knowsAbout")
            if industry_val:
                label = industry_val if isinstance(industry_val, str) else ", ".join(str(x) for x in industry_val if isinstance(x, str))
                if label:
                    return ExtractedField(
                        field_name="industry",
                        value={"code": None, "label": label, "system": "schema.org"},
                        status=FieldStatus.FOUND,
                        source_url=homepage_url,
                        source_type="website_jsonld",
                        evidence_span=f"schema.org industry: {label}",
                        confidence=0.85,
                    )

    if not website_value:
        return ExtractedField(
            field_name="industry",
            value=None,
            status=FieldStatus.UNAVAILABLE,
            source_type="official_registry",
            note="Industry information unavailable in registry or website",
        )

    return ExtractedField(
        field_name="industry",
        value=None,
        status=FieldStatus.NOT_FOUND,
        source_url=homepage_url,
        source_type="company_website",
        note="Inspected but no explicit industry categorization found",
    )


def extract_contact(
    profile: dict[str, Any],
    website_value: dict[str, Any] | None,
    structured_data: dict[str, Any],
    homepage_url: str | None,
) -> ExtractedField[dict[str, Any]]:
    """Extract and normalize contact details (address, phone, email, postal code)."""
    address = None
    postal_code = None
    city = None
    country = "Norge"
    phone = None
    email = None
    evidence_parts: list[str] = []
    source_url = homepage_url

    # 1. Structured data (JSON-LD PostalAddress, ContactPoint)
    if structured_data:
        org_entities = _walk_structured_data(
            structured_data.get("json-ld", []),
            {"Organization", "Corporation", "LocalBusiness", "PostalAddress", "ContactPoint"},
        )
        for item in org_entities:
            addr = item.get("address")
            if isinstance(addr, dict):
                address = addr.get("streetAddress") or address
                postal_code = addr.get("postalCode") or postal_code
                city = addr.get("addressLocality") or city
                country = addr.get("addressCountry") or country
            elif isinstance(item, dict) and item.get("@type") == "PostalAddress":
                address = item.get("streetAddress") or address
                postal_code = item.get("postalCode") or postal_code
                city = item.get("addressLocality") or city
                country = item.get("addressCountry") or country

            if item.get("telephone") and not phone:
                phone = str(item["telephone"]).strip()
            if item.get("email") and not email:
                email = str(item["email"]).strip()

    # 2. Text extraction from contact / about / homepage
    if website_value:
        combined_text = " ".join([
            str(website_value.get("title") or ""),
            str(website_value.get("main_text_excerpt") or ""),
            *[str(p.get("main_text_excerpt") or "") for p in website_value.get("pages", [])],
        ])

        # Extract email if not yet found
        if not email:
            email_matches = EMAIL_REGEX.findall(combined_text)
            clean_emails = [
                e.lower() for e in email_matches
                if not any(e.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"))
                and "example.com" not in e and "domain.com" not in e
            ]
            if clean_emails:
                email = clean_emails[0]
                evidence_parts.append(f"email:{email}")

        # Extract phone if not yet found
        if not phone:
            phone_matches = PHONE_REGEX.findall(combined_text)
            if phone_matches:
                clean_phone = re.sub(r"\s+", " ", phone_matches[0]).strip()
                phone = clean_phone
                evidence_parts.append(f"phone:{phone}")

        # Extract postal code and city if not yet found
        if not postal_code or not city:
            post_match = NORWEGIAN_POSTAL_REGEX.search(combined_text)
            if post_match:
                postal_code = postal_code or post_match.group(1).strip()
                city = city or post_match.group(2).strip()
                evidence_parts.append(f"postal:{postal_code} {city}")

    # 3. Official registry address (authoritative legal headquarters)
    reg_addr = profile.get("business_address") or profile.get("forretningsadresse") or profile.get("postal_address") or profile.get("postadresse")
    statutory_address = None
    statutory_postal = None
    statutory_city = None
    statutory_country = "Norge"

    if isinstance(reg_addr, dict):
        raw_addr = reg_addr.get("adresse")
        if isinstance(raw_addr, list):
            statutory_address = ", ".join(str(x) for x in raw_addr if x)
        elif raw_addr:
            statutory_address = str(raw_addr)
        statutory_postal = reg_addr.get("postnummer")
        statutory_city = reg_addr.get("poststed") or reg_addr.get("kommune")
        statutory_country = reg_addr.get("land") or "Norge"
    elif isinstance(reg_addr, str) and reg_addr.strip():
        statutory_address = reg_addr.strip()
        statutory_postal = profile.get("postal_code") or profile.get("postnummer")
        statutory_city = profile.get("city") or profile.get("poststed") or profile.get("municipality")

    # Authoritative statutory address takes precedence for registered office
    address_divergence = None
    if city and statutory_city and city.strip().lower() != statutory_city.strip().lower():
        address_divergence = {
            "operational_address": f"{address or ''}, {postal_code or ''} {city}".strip(", "),
            "registered_headquarters": f"{statutory_address or ''}, {statutory_postal or ''} {statutory_city}".strip(", "),
            "divergence_type": "operational_office_vs_registered_headquarters",
        }

    address = statutory_address or address
    postal_code = statutory_postal or postal_code
    city = statutory_city or city or profile.get("municipality")
    country = statutory_country or country

    # 4. Registry phone and email fallbacks
    if not phone and profile.get("phone"):
        phone = str(profile.get("phone")).strip()
        evidence_parts.append(f"registry_phone:{phone}")
    if not email and profile.get("email"):
        email = str(profile.get("email")).strip()
        evidence_parts.append(f"registry_email:{email}")

    # Normalize address string
    if isinstance(address, list):
        address = ", ".join(str(x) for x in address if x)
    if isinstance(address, str):
        address = address.strip()

    # Check if any contact detail was found
    has_contact = any(x is not None for x in (address, postal_code, city, phone, email))
    if has_contact:
        contact_dict = {
            "address": address,
            "postal_code": postal_code,
            "city": city,
            "country": country,
            "phone": phone,
            "email": email,
        }
        if address_divergence:
            contact_dict["address_divergence"] = address_divergence
        evidence_str = "; ".join(filter(None, [
            f"address: {address}" if address else None,
            f"postal: {postal_code} {city}" if postal_code else None,
            f"phone: {phone}" if phone else None,
            f"email: {email}" if email else None,
            f"divergence: {address_divergence['divergence_type']}" if address_divergence else None,
        ]))
        return ExtractedField(
            field_name="contact",
            value=contact_dict,
            status=FieldStatus.FOUND,
            source_url=source_url or "https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="website_and_registry" if website_value else "official_registry",
            evidence_span=evidence_str,
            confidence=0.95 if (phone or email or address) else 0.75,
        )

    if not website_value and not reg_addr and not (structured_data and structured_data.get("json-ld")):
        return ExtractedField(
            field_name="contact",
            value=None,
            status=FieldStatus.UNAVAILABLE,
            source_type="company_website",
            note="Contact information source is unavailable",
        )

    return ExtractedField(
        field_name="contact",
        value=None,
        status=FieldStatus.NOT_FOUND,
        source_url=source_url,
        source_type="company_website",
        note="Inspected but no address or contact details found",
    )


def extract_locations(
    profile: dict[str, Any],
    website_value: dict[str, Any] | None,
    structured_data: dict[str, Any],
    homepage_url: str | None,
) -> ExtractedField[list[dict[str, Any]]]:
    """Extract company locations/offices/branches without customer confusion."""
    locations: list[dict[str, Any]] = []
    seen: set[str] = set()

    evidence_dict = profile.get("evidence") or {}
    locations_ev = evidence_dict.get("locations") or {}
    locations_val = locations_ev.get("value") or {}
    reg_locations = locations_val.get("locations") or []
    locations_url = locations_ev.get("source_url") or f"https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={profile.get('organisation_number')}&size=1000"
    locations_retrieved = locations_ev.get("retrieved_at")

    registry_ev = evidence_dict.get("registry") or evidence_dict.get("registry_live") or {}
    registry_url = registry_ev.get("source_url") or f"https://data.brreg.no/enhetsregisteret/api/enheter/{profile.get('organisation_number')}"
    registry_retrieved = registry_ev.get("retrieved_at")

    # 1. Official BRREG subunits (underenheter)
    for loc in reg_locations:
        name = loc.get("name") or profile.get("name")
        addr_dict = loc.get("address") or {}
        if isinstance(addr_dict, dict):
            raw_addr = addr_dict.get("adresse") or []
            addr_line = ", ".join(raw_addr) if isinstance(raw_addr, list) else str(raw_addr or "")
            post_code = addr_dict.get("postnummer")
            city = addr_dict.get("poststed") or addr_dict.get("kommune")
        else:
            addr_line = str(addr_dict) if addr_dict else ""
            post_code = None
            city = None

        key = f"{normalize_legal_name(name)}|{normalize_legal_name(addr_line)}|{post_code or ''}|{city or ''}"
        if key not in seen:
            seen.add(key)
            ind = loc.get("industry")
            ind_dict = None
            if isinstance(ind, dict):
                ind_dict = {"kode": ind.get("kode"), "beskrivelse": ind.get("beskrivelse")}
            elif ind:
                ind_dict = {"kode": str(ind), "beskrivelse": None}

            locations.append({
                "organisation_number": loc.get("organisation_number") or loc.get("organisasjonsnummer"),
                "name": name,
                "address": addr_line or None,
                "postal_code": post_code or None,
                "city": city or None,
                "country": "Norge",
                "industry": ind_dict,
                "employees": loc.get("employees"),
                "location_type": "subunit",
                "is_headquarters": False,
                "source": "official_subunit",
                "source_url": locations_url,
                "retrieved_at": locations_retrieved,
            })

    # 2. Main registered business address (headquarters / registered office)
    main_addr = profile.get("business_address") or profile.get("address")
    if main_addr:
        if isinstance(main_addr, dict):
            raw_m_addr = main_addr.get("adresse") or main_addr.get("street") or []
            m_addr_line = ", ".join(raw_m_addr) if isinstance(raw_m_addr, list) else str(raw_m_addr or "")
            m_post_code = main_addr.get("postnummer") or main_addr.get("postal_code")
            m_city = main_addr.get("poststed") or main_addr.get("city") or main_addr.get("kommune") or profile.get("municipality")
        elif isinstance(main_addr, str) and main_addr.strip():
            m_addr_line = main_addr.strip()
            m_post_code = None
            m_city = profile.get("municipality")
        else:
            m_addr_line = None
            m_post_code = None
            m_city = profile.get("municipality")

        m_key = f"{normalize_legal_name(profile.get('name'))}|{normalize_legal_name(m_addr_line)}|{m_post_code or ''}|{m_city or ''}"
        if m_key not in seen and (m_addr_line or m_city):
            seen.add(m_key)
            locations.insert(0, {
                "organisation_number": profile.get("organisation_number"),
                "name": profile.get("name"),
                "address": m_addr_line or None,
                "postal_code": m_post_code or None,
                "city": m_city or None,
                "country": "Norge",
                "industry": {
                    "kode": profile.get("industry_code"),
                    "beskrivelse": profile.get("industry_label"),
                } if profile.get("industry_code") else None,
                "employees": profile.get("employees"),
                "location_type": "registered_office",
                "is_headquarters": True,
                "source": "official_registry",
                "source_url": registry_url,
                "retrieved_at": registry_retrieved,
            })

    # 3. Structured data (LocalBusiness, location)
    if structured_data:
        local_biz = _walk_structured_data(
            structured_data.get("json-ld", []),
            {"LocalBusiness", "Store", "Restaurant"},
        )
        for biz in local_biz:
            name = biz.get("name")
            addr = biz.get("address")
            street = addr.get("streetAddress") if isinstance(addr, dict) else None
            post_code = addr.get("postalCode") if isinstance(addr, dict) else None
            city = addr.get("addressLocality") if isinstance(addr, dict) else None
            country = addr.get("addressCountry") if isinstance(addr, dict) else "Norge"

            key = f"{normalize_legal_name(name)}|{normalize_legal_name(street)}|{post_code or ''}|{city or ''}"
            if key not in seen and (name or street):
                seen.add(key)
                locations.append({
                    "organisation_number": profile.get("organisation_number"),
                    "name": name or profile.get("name"),
                    "address": street,
                    "postal_code": post_code,
                    "city": city,
                    "country": country,
                    "industry": None,
                    "employees": None,
                    "location_type": "website_location",
                    "is_headquarters": False,
                    "source": "website_jsonld",
                    "source_url": homepage_url,
                    "retrieved_at": (evidence_dict.get("website") or {}).get("retrieved_at"),
                })

    # 4. Main address fallback if no locations found at all
    if not locations and profile.get("municipality"):
        locations.append({
            "organisation_number": profile.get("organisation_number"),
            "name": profile.get("name"),
            "address": None,
            "postal_code": None,
            "city": profile.get("municipality"),
            "country": "Norge",
            "industry": {
                "kode": profile.get("industry_code"),
                "beskrivelse": profile.get("industry_label"),
            } if profile.get("industry_code") else None,
            "employees": profile.get("employees"),
            "location_type": "registered_office",
            "is_headquarters": True,
            "source": "official_registry",
            "source_url": registry_url,
            "retrieved_at": registry_retrieved,
        })

    if locations:
        return ExtractedField(
            field_name="locations",
            value=locations,
            status=FieldStatus.FOUND,
            source_url=locations_url if reg_locations else (homepage_url or registry_url),
            source_type="official_subunits_and_website" if reg_locations else "official_registry",
            evidence_span=f"Extracted {len(locations)} verified company location(s)",
            confidence=0.95 if reg_locations else 0.85,
        )

    if not website_value and not reg_locations:
        return ExtractedField(
            field_name="locations",
            value=None,
            status=FieldStatus.UNAVAILABLE,
            source_type="official_subunits",
            note="Location sources are unavailable",
        )

    return ExtractedField(
        field_name="locations",
        value=[],
        status=FieldStatus.NOT_FOUND,
        source_url=homepage_url,
        source_type="company_website",
        note="Inspected but no distinct offices or branch locations found",
    )


def extract_leadership(
    profile: dict[str, Any],
    website_value: dict[str, Any] | None,
    structured_data: dict[str, Any],
    homepage_url: str | None,
) -> ExtractedField[list[dict[str, Any]]]:
    """Extract leadership, key executives, and founders, avoiding arbitrary employees."""
    leadership: list[dict[str, Any]] = []
    seen: set[str] = set()

    roles_ev = (profile.get("evidence") or {}).get("roles", {})
    roles_url = roles_ev.get("source_url") or f"https://data.brreg.no/enhetsregisteret/api/enheter/{profile.get('organisation_number') or ''}/roller"
    roles_retrieved = roles_ev.get("retrieved_at")

    # 1. Official BRREG roles (roller)
    reg_roles = (roles_ev.get("value") or {}).get("roles") or []
    for r in reg_roles:
        if r.get("inactive"):
            continue
        name = r.get("name")
        role_desc = r.get("role") or r.get("group") or "Registered role"
        if not name:
            continue
        # Filter for leadership roles
        lower_role = role_desc.lower()
        if any(keyword in lower_role for keyword in ("leder", "styre", "direktør", "adm", "ceo", "chair")):
            key = f"{normalize_legal_name(name)}|{normalize_legal_name(role_desc)}"
            if key not in seen:
                seen.add(key)
                leadership.append({
                    "name": name,
                    "role": role_desc,
                    "role_code": r.get("role_code"),
                    "group": r.get("group"),
                    "last_changed": r.get("last_changed"),
                    "inactive": False,
                    "organisation_number": r.get("organisation_number") or profile.get("organisation_number"),
                    "source": "official_roles",
                    "source_url": roles_url,
                    "retrieved_at": roles_retrieved,
                })

    # 2. Structured data (founder, executiveDirector, officer)
    if structured_data:
        org_entities = _walk_structured_data(
            structured_data.get("json-ld", []),
            {"Organization", "Corporation"},
        )
        for org in org_entities:
            for field_name, default_role in (("founder", "Founder"), ("foundingPerson", "Founder"), ("employee", None)):
                persons = org.get(field_name) or []
                if isinstance(persons, dict):
                    persons = [persons]
                for p in persons:
                    if isinstance(p, dict) and p.get("name"):
                        p_name = p.get("name")
                        p_role = p.get("jobTitle") or default_role
                        if p_role and any(keyword in p_role.lower() for keyword in LEADERSHIP_ROLES):
                            key = f"{normalize_legal_name(p_name)}|{normalize_legal_name(p_role)}"
                            if key not in seen:
                                seen.add(key)
                                leadership.append({
                                    "name": p_name,
                                    "role": p_role,
                                    "role_code": None,
                                    "group": "Website Leadership",
                                    "last_changed": None,
                                    "inactive": False,
                                    "organisation_number": profile.get("organisation_number"),
                                    "source": "website_jsonld",
                                    "source_url": homepage_url,
                                    "retrieved_at": (profile.get("evidence") or {}).get("website", {}).get("retrieved_at"),
                                })

    # 3. Website team / leadership page
    if website_value:
        w_retrieved = website_value.get("retrieved_at") or (profile.get("evidence") or {}).get("website", {}).get("retrieved_at")
        for page in website_value.get("pages", []):
            p_url = str(page.get("url") or "").lower()
            if any(term in p_url for term in ("ledelse", "management", "team", "about", "om-oss")):
                p_text = str(page.get("main_text_excerpt") or "")
                # Look for patterns like "Navn Navnesen, Daglig leder" or "Navn Navnesen - CEO"
                for line in p_text.splitlines():
                    line_clean = line.strip()
                    for role_kw in (
                        "daglig leder", "adm. dir", "administrerende direktør", "ceo",
                        "chief executive officer", "styreleder", "styrets leder", "chair",
                        "chairman", "board chair", "cfo", "cto", "gründer", "founder", "managing director",
                    ):
                        pattern = rf"^([A-ZÆØÅ][a-zæøå]+(?:\s+[A-ZÆØÅ][a-zæøå]+)+)[\s,:\-]+({re.escape(role_kw)})\b"
                        match = re.search(pattern, line_clean, re.IGNORECASE)
                        if match:
                            l_name = match.group(1).strip()
                            l_role = match.group(2).strip().title()
                            key = f"{normalize_legal_name(l_name)}|{normalize_legal_name(l_role)}"
                            if key not in seen:
                                seen.add(key)
                                leadership.append({
                                    "name": l_name,
                                    "role": l_role,
                                    "role_code": None,
                                    "group": "Website Leadership",
                                    "last_changed": None,
                                    "inactive": False,
                                    "organisation_number": profile.get("organisation_number"),
                                    "source": "website_team_page",
                                    "source_url": p_url,
                                    "retrieved_at": page.get("retrieved_at") or w_retrieved,
                                })

    if leadership:
        return ExtractedField(
            field_name="leadership",
            value=leadership,
            status=FieldStatus.FOUND,
            source_url=roles_url if reg_roles else (homepage_url or "https://data.brreg.no/enhetsregisteret/api/enheter/roller"),
            source_type="official_roles_and_website" if reg_roles else "company_website",
            evidence_span=f"Extracted {len(leadership)} verified leadership role(s)",
            confidence=0.95,
        )

    if not website_value and not reg_roles:
        return ExtractedField(
            field_name="leadership",
            value=None,
            status=FieldStatus.UNAVAILABLE,
            source_type="official_roles",
            note="Official roles and website sources are unavailable",
        )

    return ExtractedField(
        field_name="leadership",
        value=[],
        status=FieldStatus.NOT_FOUND,
        source_url=homepage_url or roles_url,
        source_type="company_website",
        note="Inspected but no explicit leadership or executive positions identified",
    )


def extract_people(
    profile: dict[str, Any],
    website_value: dict[str, Any] | None,
    structured_data: dict[str, Any],
    homepage_url: str | None,
) -> ExtractedField[list[dict[str, Any]]]:
    """Extract people and roles preserving official BRREG statutory roles as authoritative."""
    people: list[dict[str, Any]] = []
    seen: set[str] = set()
    seen_official_names: set[str] = set()

    roles_ev = (profile.get("evidence") or {}).get("roles", {})
    roles_status = roles_ev.get("status")
    roles_url = roles_ev.get("source_url") or f"https://data.brreg.no/enhetsregisteret/api/enheter/{profile.get('organisation_number') or ''}/roller"
    roles_retrieved = roles_ev.get("retrieved_at")

    # 1. Official BRREG roles (authoritative ground truth)
    reg_roles = (roles_ev.get("value") or {}).get("roles") or []
    for r in reg_roles:
        name = r.get("name")
        if not name:
            continue
        role_desc = r.get("role") or r.get("group") or "Registered role"
        role_code = r.get("role_code")
        group = r.get("group")
        group_code = r.get("group_code")
        last_changed = r.get("last_changed")
        inactive = bool(r.get("inactive"))
        org_nr = r.get("organisation_number") or profile.get("organisation_number")

        key = f"{normalize_legal_name(name)}|{role_code or ''}|{normalize_legal_name(role_desc)}"
        if key not in seen:
            seen.add(key)
            seen_official_names.add(normalize_legal_name(name))
            people.append({
                "name": name,
                "role": role_desc,
                "role_code": role_code,
                "group": group,
                "group_code": group_code,
                "last_changed": last_changed,
                "inactive": inactive,
                "organisation_number": org_nr,
                "source": "official_roles",
                "source_url": roles_url,
                "retrieved_at": roles_retrieved,
            })

    # 2. Enrich from structured data (founder, executiveDirector, officer) if not in official roles
    if structured_data:
        org_entities = _walk_structured_data(
            structured_data.get("json-ld", []),
            {"Organization", "Corporation"},
        )
        for org in org_entities:
            for field_name, default_role in (("founder", "Founder"), ("foundingPerson", "Founder"), ("employee", None)):
                persons = org.get(field_name) or []
                if isinstance(persons, dict):
                    persons = [persons]
                for p in persons:
                    if isinstance(p, dict) and p.get("name"):
                        p_name = p.get("name")
                        p_role = p.get("jobTitle") or default_role
                        if p_name and normalize_legal_name(p_name) not in seen_official_names:
                            key = f"{normalize_legal_name(p_name)}|{normalize_legal_name(p_role or '')}"
                            if key not in seen:
                                seen.add(key)
                                people.append({
                                    "name": p_name,
                                    "role": p_role or "Team Member",
                                    "role_code": None,
                                    "group": "Website Organization",
                                    "group_code": None,
                                    "last_changed": None,
                                    "inactive": False,
                                    "organisation_number": profile.get("organisation_number"),
                                    "source": "website_jsonld",
                                    "source_url": homepage_url,
                                    "retrieved_at": (profile.get("evidence") or {}).get("website", {}).get("retrieved_at"),
                                })

    # 3. Enrich from website leadership/team page if not in official roles
    if website_value:
        w_retrieved = website_value.get("retrieved_at") or (profile.get("evidence") or {}).get("website", {}).get("retrieved_at")
        for page in website_value.get("pages", []):
            p_url = str(page.get("url") or "")
            if any(term in p_url.lower() for term in ("ledelse", "management", "team", "about", "om-oss")):
                p_text = str(page.get("main_text_excerpt") or "")
                for line in p_text.splitlines():
                    line_clean = line.strip()
                    for role_kw in (
                        "daglig leder", "adm. dir", "administrerende direktør", "ceo",
                        "chief executive officer", "styreleder", "styrets leder", "chair",
                        "chairman", "board chair", "cfo", "cto", "gründer", "founder", "managing director",
                    ):
                        pattern = rf"^([A-ZÆØÅ][a-zæøå]+(?:\s+[A-ZÆØÅ][a-zæøå]+)+)[\s,:\-]+({re.escape(role_kw)})\b"
                        match = re.search(pattern, line_clean, re.IGNORECASE)
                        if match:
                            l_name = match.group(1).strip()
                            l_role = match.group(2).strip().title()
                            if normalize_legal_name(l_name) not in seen_official_names:
                                key = f"{normalize_legal_name(l_name)}|{normalize_legal_name(l_role)}"
                                if key not in seen:
                                    seen.add(key)
                                    people.append({
                                        "name": l_name,
                                        "role": l_role,
                                        "role_code": None,
                                        "group": "Website Team",
                                        "group_code": None,
                                        "last_changed": None,
                                        "inactive": False,
                                        "organisation_number": profile.get("organisation_number"),
                                        "source": "website_team_page",
                                        "source_url": p_url,
                                        "retrieved_at": page.get("retrieved_at") or w_retrieved,
                                    })

    if people:
        return ExtractedField(
            field_name="people",
            value=people,
            status=FieldStatus.FOUND,
            source_url=roles_url if reg_roles else homepage_url,
            source_type="official_roles" if reg_roles else "company_website",
            evidence_span=f"Extracted {len(people)} verified person/role record(s)",
            confidence=1.0 if reg_roles else 0.85,
        )

    if not website_value and (roles_status in {"unavailable", None} and not reg_roles):
        return ExtractedField(
            field_name="people",
            value=None,
            status=FieldStatus.UNAVAILABLE,
            source_type="official_roles",
            note="Official roles and website sources are unavailable",
        )

    return ExtractedField(
        field_name="people",
        value=[],
        status=FieldStatus.NOT_FOUND,
        source_url=roles_url if roles_status == "not_found" else homepage_url,
        source_type="official_roles" if roles_status == "not_found" else "company_website",
        note="Inspected but no registered roles or people identified",
    )


def extract_employees(
    profile: dict[str, Any],
    website_value: dict[str, Any] | None,
    structured_data: dict[str, Any],
    homepage_url: str | None,
) -> ExtractedField[int | str]:
    """Extract employee count or exact range without estimation."""
    # 1. Official BRREG registry employee count (authoritative)
    reg_employees = profile.get("employees")
    if reg_employees is not None:
        try:
            count = int(reg_employees)
            return ExtractedField(
                field_name="employees",
                value=count,
                status=FieldStatus.FOUND,
                source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
                source_type="official_registry",
                evidence_span=f"Antall ansatte i Brønnøysundregisteret: {count}",
                confidence=1.0,
            )
        except ValueError:
            pass

    # 2. Structured data numberOfEmployees
    if structured_data:
        org_entities = _walk_structured_data(
            structured_data.get("json-ld", []),
            {"Organization", "Corporation", "LocalBusiness"},
        )
        for org in org_entities:
            num = org.get("numberOfEmployees")
            if isinstance(num, (int, float)):
                return ExtractedField(
                    field_name="employees",
                    value=int(num),
                    status=FieldStatus.FOUND,
                    source_url=homepage_url,
                    source_type="website_jsonld",
                    evidence_span=f"schema.org numberOfEmployees: {int(num)}",
                    confidence=0.9,
                )
            elif isinstance(num, dict):
                # QuantitativeValue (minValue, maxValue)
                min_v = num.get("minValue")
                max_v = num.get("maxValue")
                if min_v is not None and max_v is not None:
                    range_str = f"{min_v}-{max_v}"
                    return ExtractedField(
                        field_name="employees",
                        value=range_str,
                        status=FieldStatus.FOUND,
                        source_url=homepage_url,
                        source_type="website_jsonld",
                        evidence_span=f"schema.org numberOfEmployees: {range_str}",
                        confidence=0.85,
                    )

    # 3. Explicit text extraction from website
    if website_value:
        combined_text = " ".join([
            str(website_value.get("main_text_excerpt") or ""),
            *[str(p.get("main_text_excerpt") or "") for p in website_value.get("pages", [])],
        ])

        # Match phrases like "vi er 45 ansatte", "over 100 ansatte", "11-50 ansatte", "more than 50 employees"
        text_patterns = (
            (r"\b(\d+)\s*-\s*(\d+)\s+(?:ansatte|employees)\b", "range"),
            (r"\b(?:over|mer enn|more than)\s+(\d+)\s+(?:ansatte|employees)\b", "over"),
            (r"\b(?:vi\s+er(?:\s+i\s+dag)?\s+|har\s+|teller\s+|ca\.?\s+|omtrent\s+|totalt\s+)?(\d+)\s+(?:ansatte|medarbeidere|employees)\b", "exact"),
        )
        for pat, mode in text_patterns:
            m = re.search(pat, combined_text, re.IGNORECASE)
            if m:
                if mode == "range":
                    val_str = f"{m.group(1)}-{m.group(2)}"
                    return ExtractedField(
                        field_name="employees",
                        value=val_str,
                        status=FieldStatus.FOUND,
                        source_url=homepage_url,
                        source_type="website_text",
                        evidence_span=m.group(0),
                        confidence=0.85,
                    )
                else:
                    count = int(m.group(1))
                    val_out = f">{count}" if mode == "over" else count
                    return ExtractedField(
                        field_name="employees",
                        value=val_out,
                        status=FieldStatus.FOUND,
                        source_url=homepage_url,
                        source_type="website_text",
                        evidence_span=m.group(0),
                        confidence=0.85,
                    )

    if not website_value and reg_employees is None:
        return ExtractedField(
            field_name="employees",
            value=None,
            status=FieldStatus.UNAVAILABLE,
            source_type="official_registry",
            note="Employee count is unavailable",
        )

    return ExtractedField(
        field_name="employees",
        value=None,
        status=FieldStatus.NOT_FOUND,
        source_url=homepage_url,
        source_type="company_website",
        note="Inspected but no explicit employee count stated",
    )


def extract_careers(
    profile: dict[str, Any],
    website_value: dict[str, Any] | None,
    homepage_url: str | None,
) -> ExtractedField[dict[str, Any]]:
    """Detect careers page and active openings without assuming hiring from presence alone."""
    if not website_value:
        return ExtractedField(
            field_name="careers",
            value=None,
            status=FieldStatus.UNAVAILABLE,
            source_type="company_website",
            note="Website is unavailable or unverified",
        )

    pages = website_value.get("pages", [])
    careers_page = next(
        (
            p for p in pages
            if CAREERS_PATH.search(urllib.parse.urlparse(str(p.get("url") or "")).path)
            or urllib.parse.urlparse(str(p.get("url") or "")).netloc.lower().startswith(("karriere.", "jobb."))
        ),
        None,
    )

    # Collect outbound ATS links from verified company pages
    ats_links: list[dict[str, Any]] = list(website_value.get("outbound_career_links") or [])
    for p in pages:
        for lk in (p.get("outbound_career_links") or []):
            if not any(existing.get("url") == lk.get("url") for existing in ats_links):
                ats_links.append(lk)

    w_retrieved = (profile.get("evidence") or {}).get("website", {}).get("retrieved_at")

    if not careers_page:
        # Check if an outbound ATS careers link is present on verified company pages
        if ats_links:
            best_ats = ats_links[0]
            ats_url = best_ats["url"]
            source_page = best_ats.get("source_url") or homepage_url
            careers_data = {
                "has_careers_page": True,
                "careers_url": ats_url,
                "ats_careers_url": ats_url,
                "ats_platform": best_ats.get("platform"),
                "hiring_active": None,  # Portal exists, but do NOT infer active hiring merely from ATS presence
                "openings": [],
                "source_url": source_page,
                "retrieved_at": w_retrieved,
            }
            return ExtractedField(
                field_name="careers",
                value=careers_data,
                status=FieldStatus.FOUND,
                source_url=source_page,
                source_type="external_ats_link",
                evidence_span=f"Outbound ATS careers link to {ats_url} ({best_ats.get('platform')})",
                confidence=0.9,
            )

        # Check priority links or page text for career references
        main_text = " ".join([str(website_value.get("main_text_excerpt") or ""), *[str(p.get("main_text_excerpt") or "") for p in pages]])
        if re.search(r"\b(?:ledige\s+stillinger|karriere|work\s+with\s+us|jobb\s+hos\s+oss|jobbe\s+hos\s+oss|bli\s+en\s+av\s+oss|arbeide\s+hos\s+oss)\b", main_text, re.IGNORECASE):
            return ExtractedField(
                field_name="careers",
                value={
                    "has_careers_page": True,
                    "careers_url": None,
                    "hiring_active": None,
                    "openings": [],
                    "source_url": homepage_url,
                    "retrieved_at": w_retrieved,
                },
                status=FieldStatus.FOUND,
                source_url=homepage_url,
                source_type="website_text",
                evidence_span="Career/job mentions found in site content",
                confidence=0.75,
            )
        return ExtractedField(
            field_name="careers",
            value={
                "has_careers_page": False,
                "careers_url": None,
                "hiring_active": False,
                "openings": [],
                "source_url": homepage_url,
                "retrieved_at": w_retrieved,
            },
            status=FieldStatus.NOT_FOUND,
            source_url=homepage_url,
            source_type="company_website",
            note="No careers page or hiring indicators detected",
        )

    # Analyze careers page text for active job postings
    careers_url = str(careers_page.get("url") or "")
    careers_text = str(careers_page.get("main_text_excerpt") or "")
    openings: list[str] = []
    hiring_active: bool | None = False

    # Check for active openings indicators vs "ingen ledige stillinger"
    if re.search(r"\bingen\s+ledige\s+stillinger\b|\bno\s+open\s+positions\b|\bcurrently\s+not\s+hiring\b", careers_text, re.IGNORECASE):
        hiring_active = False
    elif re.search(r"\b(?:ledige\s+stillinger|åpne\s+stillinger|open\s+positions|we\s+are\s+hiring|vi\s+søker)\b", careers_text, re.IGNORECASE):
        hiring_active = True
        # Extract potential position titles (lines following "vi søker" or bulleted items)
        for line in careers_text.splitlines():
            clean = line.strip()
            if 5 < len(clean) < 60 and any(clean.lower().startswith(prefix) for prefix in ("- ", "* ", "• ")):
                openings.append(clean.lstrip("-*• "))
    elif ats_links:
        # Internal careers page links out to ATS, but does not state specific active openings in text
        hiring_active = None

    careers_data = {
        "has_careers_page": True,
        "careers_url": careers_url,
        "hiring_active": hiring_active,
        "openings": openings[:10],
        "source_url": careers_url,
        "retrieved_at": careers_page.get("retrieved_at") or w_retrieved,
    }
    if ats_links:
        careers_data["ats_careers_url"] = ats_links[0]["url"]
        careers_data["ats_platform"] = ats_links[0].get("platform")

    return ExtractedField(
        field_name="careers",
        value=careers_data,
        status=FieldStatus.FOUND,
        source_url=careers_url,
        source_type="website_careers_page",
        evidence_span=f"Careers page at {careers_url} (active_hiring={hiring_active})",
        confidence=0.9,
    )


def extract_news(
    profile: dict[str, Any],
    website_value: dict[str, Any] | None,
    homepage_url: str | None,
) -> ExtractedField[list[dict[str, Any]]]:
    """Extract recent meaningful company news and press activity."""
    if not website_value:
        return ExtractedField(
            field_name="news",
            value=None,
            status=FieldStatus.UNAVAILABLE,
            source_type="company_website",
            note="Website is unavailable or unverified",
        )

    news_items: list[dict[str, Any]] = []
    pages = website_value.get("pages", [])
    w_retrieved = (profile.get("evidence") or {}).get("website", {}).get("retrieved_at")

    for page in pages:
        p_url = str(page.get("url") or "")
        parsed = urllib.parse.urlparse(p_url)
        if NEWS_PATH.search(parsed.path) or parsed.netloc.lower().startswith(("news.", "nyheter.", "presse.")):
            title = str(page.get("title") or "Nyhet").strip()
            snippet = str(page.get("main_text_excerpt") or "").strip()[:300]
            # Try finding date in snippet or title (e.g. 2024-05-12, 12.05.2024)
            date_match = re.search(r"\b(\d{4}[-/]\d{2}[-/]\d{2}|\d{2}\.\d{2}\.\d{4})\b", f"{title} {snippet}")
            date_str = date_match.group(1) if date_match else None

            news_items.append({
                "title": title,
                "url": p_url,
                "date": date_str,
                "snippet": snippet,
                "source": "website_news_page",
                "source_url": p_url,
                "retrieved_at": page.get("retrieved_at") or w_retrieved,
            })

    if news_items:
        return ExtractedField(
            field_name="news",
            value=news_items[:10],
            status=FieldStatus.FOUND,
            source_url=news_items[0]["url"] if len(news_items) == 1 else homepage_url,
            source_type="website_news_pages",
            evidence_span=f"Extracted {len(news_items)} news/press item(s)",
            confidence=0.9,
        )

    return ExtractedField(
        field_name="news",
        value=[],
        status=FieldStatus.NOT_FOUND,
        source_url=homepage_url,
        source_type="company_website",
        note="Inspected but no dedicated news or press releases found",
    )


# ============================================================================
# 3.5. STAGE 14 COVERAGE EXTENSION EXTRACTORS
# ============================================================================

CERTIFICATION_PATTERNS = [
    (re.compile(r"\bISO\s*9001\b", re.I), "ISO 9001 (Quality Management)"),
    (re.compile(r"\bISO\s*14001\b", re.I), "ISO 14001 (Environmental Management)"),
    (re.compile(r"\bISO\s*27001\b", re.I), "ISO 27001 (Information Security)"),
    (re.compile(r"\bISO\s*45001\b", re.I), "ISO 45001 (Occupational Health & Safety)"),
    (re.compile(r"\bISO\s*22000\b", re.I), "ISO 22000 (Food Safety)"),
    (re.compile(r"\bISO\s*13485\b", re.I), "ISO 13485 (Medical Devices)"),
    (re.compile(r"\bMiljøfyrtårn\b", re.I), "Miljøfyrtårn (Eco-Lighthouse)"),
    (re.compile(r"\bStartBANK\b", re.I), "StartBANK"),
    (re.compile(r"\bAchilles\b", re.I), "Achilles"),
    (re.compile(r"\bEcoVadis\b", re.I), "EcoVadis"),
    (re.compile(r"\bMesterbedrift\b", re.I), "Mesterbedrift"),
    (re.compile(r"\bSvanemerket\b", re.I), "Svanemerket (Nordic Swan Ecolabel)"),
    (re.compile(r"\bFSC(?:-sertifisert)?\b", re.I), "FSC (Forest Stewardship Council)"),
    (re.compile(r"\bPEFC\b", re.I), "PEFC (Programme for the Endorsement of Forest Certification)"),
    (re.compile(r"\bDebio\b|\bØkologisk\s+landbruk\b", re.I), "Debio (Økologisk sertifisering)"),
    (re.compile(r"\bCE-merk(?:et|ing)\b", re.I), "CE-merket"),
    (re.compile(r"\bFairtrade\b", re.I), "Fairtrade"),
]


def extract_products_and_services(
    profile: dict[str, Any],
    website_value: dict[str, Any] | None,
    structured_data: dict[str, Any],
    homepage_url: str | None,
) -> ExtractedField[list[dict[str, Any]]]:
    """Extract company products, offerings, and commercial services without fabrication."""
    products: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 1. Structured data (Product, Service, Offer, ItemList)
    if structured_data:
        entities = _walk_structured_data(
            structured_data.get("json-ld", []),
            {"Product", "Service", "Offer", "SoftwareApplication"},
        )
        for item in entities:
            name = item.get("name")
            desc = item.get("description")
            category = item.get("category") or item.get("@type")
            if isinstance(name, str) and len(name.strip()) > 1:
                clean_name = name.strip()
                clean_desc = desc.strip()[:300] if isinstance(desc, str) else None
                key = clean_name.lower()
                if key not in seen:
                    seen.add(key)
                    products.append({
                        "name": clean_name,
                        "description": clean_desc,
                        "category": str(category) if category else None,
                        "source": "website_jsonld",
                    })

    # 2. First-party pages (/tjenester, /produkter, /services, /losninger)
    if website_value:
        pages = website_value.get("pages", [])
        for page in pages:
            p_url = str(page.get("url") or "")
            path = urllib.parse.urlparse(p_url).path.lower()
            if any(term in path for term in ("tjenester", "produkter", "services", "products", "losninger", "solutions")):
                page_title = str(page.get("title") or "").strip()
                page_text = str(page.get("main_text_excerpt") or "").strip()
                if page_title and page_title.lower() not in ("tjenester", "produkter", "services", "products", "våre tjenester", "hjem"):
                    key = page_title.lower()
                    if key not in seen and len(page_title) < 100:
                        seen.add(key)
                        products.append({
                            "name": page_title,
                            "description": page_text[:200] if page_text else None,
                            "category": "service" if "tjenest" in path else "product",
                            "source": "website_product_page",
                        })
                # Check for bulleted lists or subheadings in page text
                lines = [line.strip() for line in page_text.splitlines() if line.strip()]
                for line in lines:
                    if any(line.startswith(b) for b in ("- ", "* ", "• ")) and 4 < len(line) < 100:
                        item_name = line.lstrip("-*• ").strip()
                        key = item_name.lower()
                        if key not in seen:
                            seen.add(key)
                            products.append({
                                "name": item_name,
                                "description": None,
                                "category": "offering",
                                "source": "website_offering_list",
                            })
                            if len(products) >= 15:
                                break

    # 3. Fallback to statutory purpose/activity if specific products/services are enumerated
    purpose = profile.get("purpose")
    if not products and purpose:
        purpose_str = str(purpose).strip()
        if any(prefix in purpose_str.lower() for prefix in ("salg av", "utvikling", "drift av", "tjenester innen", "produksjon av", "handel med")):
            products.append({
                "name": purpose_str[:120],
                "description": purpose_str[:300],
                "category": "statutory_purpose",
                "source": "official_registry_purpose",
            })

    if products:
        return ExtractedField(
            field_name="products_and_services",
            value=products[:15],
            status=FieldStatus.FOUND,
            source_url=homepage_url or "https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="website_and_registry" if website_value else "official_registry",
            evidence_span=f"Extracted {len(products)} product(s)/service(s)",
            confidence=0.9 if website_value else 0.8,
        )

    if not website_value and not purpose:
        return ExtractedField(
            field_name="products_and_services",
            value=[],
            status=FieldStatus.UNAVAILABLE,
            source_type="company_website",
            note="Products and services information source is unavailable",
        )

    return ExtractedField(
        field_name="products_and_services",
        value=[],
        status=FieldStatus.NOT_FOUND,
        source_url=homepage_url,
        source_type="company_website",
        note="Inspected website but no explicit product or service catalog identified",
    )


def extract_customers_and_markets(
    profile: dict[str, Any],
    website_value: dict[str, Any] | None,
    structured_data: dict[str, Any],
    homepage_url: str | None,
) -> ExtractedField[dict[str, Any]]:
    """Extract target audience, geographic scope, and customer references without speculation."""
    target_audience = None
    geographic_scope = None
    references: list[str] = []
    seen_refs: set[str] = set()

    # 1. Structured data (areaServed, audience)
    if structured_data:
        entities = _walk_structured_data(
            structured_data.get("json-ld", []),
            {"Organization", "Corporation", "LocalBusiness"},
        )
        for ent in entities:
            area = ent.get("areaServed")
            if isinstance(area, str) and area.strip():
                geographic_scope = area.strip()
            elif isinstance(area, dict) and area.get("name"):
                geographic_scope = str(area.get("name")).strip()
            elif isinstance(area, list):
                names = [x.get("name") if isinstance(x, dict) else str(x) for x in area if x]
                if names:
                    geographic_scope = ", ".join(names[:5])

            aud = ent.get("audience")
            if isinstance(aud, str) and aud.strip():
                target_audience = aud.strip()
            elif isinstance(aud, dict) and aud.get("audienceType"):
                target_audience = str(aud.get("audienceType")).strip()

    # 2. Website reference pages (/referanser, /kunder, /cases, /prosjekter) & text analysis
    if website_value:
        combined_text = " ".join([
            str(website_value.get("title") or ""),
            str(website_value.get("description") or ""),
            str(website_value.get("main_text_excerpt") or ""),
            *[str(p.get("main_text_excerpt") or "") for p in website_value.get("pages", [])],
        ])

        # Geographic scope detection
        if not geographic_scope:
            if re.search(r"\b(?:globalt|worldwide|internasjonalt|international|europa|europe)\b", combined_text, re.IGNORECASE):
                geographic_scope = "Internasjonalt / Globalt"
            elif re.search(r"\b(?:norden|nordic|skandinavia|scandinavia)\b", combined_text, re.IGNORECASE):
                geographic_scope = "Norden / Skandinavia"
            elif re.search(r"\b(?:hele\s+norge|nasjonalt|over\s+hele\s+landet)\b", combined_text, re.IGNORECASE):
                geographic_scope = "Norge (nasjonalt)"
            elif profile.get("municipality"):
                geographic_scope = f"{profile.get('municipality')}, Norge (lokalt/regionalt)"

        # Target audience detection (B2B, B2C, public sector)
        if not target_audience:
            b2b = bool(re.search(r"\b(?:b2b|bedriftsmarkedet|offentlig\s+sektor|næringslivet|for\s+bedrifter)\b", combined_text, re.IGNORECASE))
            b2c = bool(re.search(r"\b(?:b2c|privatmarkedet|forbruker|forbrukerkunder|privatkunder)\b", combined_text, re.IGNORECASE))
            if b2b and b2c:
                target_audience = "B2B & B2C (Næringsliv og privatpersoner)"
            elif b2b:
                target_audience = "B2B (Bedrifts- og organisasjonsmarkedet)"
            elif b2c:
                target_audience = "B2C (Forbrukermarkedet)"

        # Reference customers/cases from pages
        for page in website_value.get("pages", []):
            p_url = str(page.get("url") or "")
            path = urllib.parse.urlparse(p_url).path.lower()
            if any(term in path for term in ("referanser", "kunder", "cases", "clients", "portfolio", "prosjekter")):
                p_text = str(page.get("main_text_excerpt") or "")
                for line in p_text.splitlines():
                    clean = line.strip()
                    if any(clean.startswith(b) for b in ("- ", "* ", "• ")) and 3 < len(clean) < 80:
                        ref_name = clean.lstrip("-*• ").strip()
                        key = ref_name.lower()
                        if key not in seen_refs:
                            seen_refs.add(key)
                            references.append(ref_name)
                            if len(references) >= 10:
                                break

    # 3. Registry fallback for geographic scope
    if not geographic_scope and profile.get("municipality"):
        geographic_scope = f"{profile.get('municipality')}, Norge"

    has_data = bool(target_audience or geographic_scope or references)
    if has_data:
        val = {
            "target_audience": target_audience,
            "geographic_scope": geographic_scope,
            "references": references[:10],
        }
        return ExtractedField(
            field_name="customers_and_markets",
            value=val,
            status=FieldStatus.FOUND,
            source_url=homepage_url or "https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="website_and_registry" if website_value else "official_registry",
            evidence_span=f"Scope: {geographic_scope}; Audience: {target_audience}; References: {len(references)}",
            confidence=0.85,
        )

    if not website_value:
        return ExtractedField(
            field_name="customers_and_markets",
            value=None,
            status=FieldStatus.UNAVAILABLE,
            source_type="company_website",
            note="Customer and market information source is unavailable",
        )

    return ExtractedField(
        field_name="customers_and_markets",
        value=None,
        status=FieldStatus.NOT_FOUND,
        source_url=homepage_url,
        source_type="company_website",
        note="Inspected website but no explicit target market or reference customers found",
    )


def extract_certifications(
    profile: dict[str, Any],
    website_value: dict[str, Any] | None,
    homepage_url: str | None,
    *,
    html: str | None = None,
) -> ExtractedField[list[str]]:
    """Extract verified third-party quality, environmental, and industry certifications."""
    if not website_value and not html:
        return ExtractedField(
            field_name="certifications",
            value=[],
            status=FieldStatus.UNAVAILABLE,
            source_type="company_website",
            note="Website unavailable for certification verification",
        )

    text_parts = [
        str((website_value or {}).get("title") or ""),
        str((website_value or {}).get("description") or ""),
        str((website_value or {}).get("main_text_excerpt") or ""),
        *[str(p.get("main_text_excerpt") or "") for p in (website_value or {}).get("pages", [])],
    ]
    if html:
        text_parts.append(html)
    combined_text = " ".join(text_parts)

    found_certs: list[str] = []
    seen: set[str] = set()

    for pattern, label in CERTIFICATION_PATTERNS:
        if pattern.search(combined_text):
            if label not in seen:
                seen.add(label)
                found_certs.append(label)

    if found_certs:
        return ExtractedField(
            field_name="certifications",
            value=found_certs,
            status=FieldStatus.FOUND,
            source_url=homepage_url,
            source_type="website_certifications",
            evidence_span=f"Verified certifications: {', '.join(found_certs)}",
            confidence=0.95,
        )

    return ExtractedField(
        field_name="certifications",
        value=[],
        status=FieldStatus.NOT_FOUND,
        source_url=homepage_url,
        source_type="company_website",
        note="Inspected website but no standard certifications identified",
    )


def extract_corporate_governance(
    profile: dict[str, Any],
    homepage_url: str | None = None,
) -> ExtractedField[dict[str, Any]]:
    """Extract statutory corporate governance, registration timeline, capital, and group hierarchy."""
    reg_date = profile.get("registration_date")
    founding_date = profile.get("founding_date")
    vat_reg = profile.get("vat_registered")
    share_cap = profile.get("share_capital")
    is_in_group = profile.get("is_in_group")
    parent_org = profile.get("parent_organisation")
    org_form = profile.get("organisation_form") or profile.get("orgform")

    # Board and auditor from roles if available in profile evidence
    reg_roles = ((profile.get("evidence") or {}).get("roles", {}).get("value") or {}).get("roles") or []
    board_members: list[dict[str, Any]] = []
    auditor: str | None = None

    for r in reg_roles:
        if r.get("inactive"):
            continue
        name = r.get("name")
        role = r.get("role") or r.get("group") or ""
        if not name:
            continue
        lower_role = role.lower()
        if "revisor" in lower_role:
            auditor = name
        elif any(k in lower_role for k in ("styre", "board", "chair")):
            board_members.append({"name": name, "role": role})

    has_governance = any(x is not None for x in (reg_date, founding_date, vat_reg, share_cap, is_in_group, parent_org, org_form)) or bool(board_members) or bool(auditor)

    if has_governance:
        gov_data = {
            "registration_date": str(reg_date) if reg_date else None,
            "founding_date": str(founding_date) if founding_date else None,
            "organisation_form": org_form,
            "vat_registered": bool(vat_reg) if vat_reg is not None else None,
            "share_capital": share_cap,
            "currency": "NOK" if share_cap is not None else None,
            "is_in_group": bool(is_in_group) if is_in_group is not None else None,
            "parent_organisation": parent_org,
            "board_members": board_members[:10],
            "auditor": auditor,
        }
        return ExtractedField(
            field_name="corporate_governance",
            value=gov_data,
            status=FieldStatus.FOUND,
            source_url="https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="official_registry",
            evidence_span=f"OrgForm: {org_form}; RegDate: {reg_date}; ShareCapital: {share_cap} NOK; Group: {is_in_group}",
            confidence=1.0,
        )

    return ExtractedField(
        field_name="corporate_governance",
        value=None,
        status=FieldStatus.UNAVAILABLE,
        source_type="official_registry",
        note="Statutory governance records unavailable",
    )


# ============================================================================
# 4. MAIN EXTRACTION PIPELINE
# ============================================================================

def extract_company_profile(
    profile: dict[str, Any],
    *,
    html: str | None = None,
) -> ExtractedCompanyProfile:
    """Extract comprehensive, evidence-attributed company profile without guessing."""
    org_number = str(profile.get("organisation_number") or "").strip()
    company_name = str(profile.get("name") or "").strip()

    evidence_dict = profile.get("evidence") or {}
    website_record = evidence_dict.get("website") or {}
    website_value = website_record.get("value") if website_record.get("status") == "available" else None

    homepage_url = None
    if website_value:
        homepage_url = website_value.get("final_url") or website_record.get("source_url")

    # Structured data parsing
    structured_data: dict[str, Any] = {}
    if html:
        structured_data = _extract_all_structured(html, base_url=homepage_url or "")
    elif website_value:
        # Use structured_organisations if pre-extracted, or empty
        pre_structured = website_value.get("structured_organisations") or []
        structured_data = {"json-ld": pre_structured, "microdata": [], "opengraph": []}

    # Extract all domains
    description_field = extract_description(profile, website_value, structured_data, homepage_url)
    industry_field = extract_industry(profile, website_value, structured_data, homepage_url)
    contact_field = extract_contact(profile, website_value, structured_data, homepage_url)
    locations_field = extract_locations(profile, website_value, structured_data, homepage_url)
    leadership_field = extract_leadership(profile, website_value, structured_data, homepage_url)
    people_field = extract_people(profile, website_value, structured_data, homepage_url)
    employees_field = extract_employees(profile, website_value, structured_data, homepage_url)
    careers_field = extract_careers(profile, website_value, homepage_url)
    news_field = extract_news(profile, website_value, homepage_url)
    products_field = extract_products_and_services(profile, website_value, structured_data, homepage_url)
    customers_field = extract_customers_and_markets(profile, website_value, structured_data, homepage_url)
    certifications_field = extract_certifications(profile, website_value, homepage_url, html=html)
    governance_field = extract_corporate_governance(profile, homepage_url)

    structured_summary = {
        "json_ld_entities_count": len(structured_data.get("json-ld", [])),
        "microdata_entities_count": len(structured_data.get("microdata", [])),
        "opengraph_records_count": len(structured_data.get("opengraph", [])),
    }

    return ExtractedCompanyProfile(
        organisation_number=org_number,
        company_name=company_name,
        description=description_field,
        industry=industry_field,
        contact=contact_field,
        locations=locations_field,
        leadership=leadership_field,
        employees=employees_field,
        careers=careers_field,
        news=news_field,
        structured_data_summary=structured_summary,
        overall_status="complete",
        products_and_services=products_field,
        customers_and_markets=customers_field,
        certifications=certifications_field,
        corporate_governance=governance_field,
        people=people_field,
    )
