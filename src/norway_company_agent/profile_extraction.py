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

    def to_dict(self) -> dict[str, Any]:
        return {
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


# ============================================================================
# 2. STRUCTURED DATA & HTML EXTRACTION UTILITIES
# ============================================================================

EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_REGEX = re.compile(r"(?:\+47\s*)?(?:[2-9]\d{1}(?:\s*\d{2}){3}|[2-9]\d{2}(?:\s*\d{2}){2}|[2-9]\d{7})")
NORWEGIAN_POSTAL_REGEX = re.compile(r"\b(\d{4})\s+([A-ZÆØÅa-zæøå\s-]+)\b")

CAREERS_PATH = re.compile(r"/(?:karriere|careers|jobs|jobb|stillinger|ledige-stillinger|work-with-us)(?:/|$)", re.I)
NEWS_PATH = re.compile(r"/(?:news|press|aktuelt|nyheter|pressemeldinger|artikler|blog)(?:/|$)", re.I)

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

    # 5. Fallback to official registry industry label if present
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

    # 3. Official registry address fallback
    reg_addr = profile.get("business_address") or profile.get("forretningsadresse") or profile.get("postal_address") or profile.get("postadresse")
    if isinstance(reg_addr, dict):
        raw_addr = reg_addr.get("adresse")
        if isinstance(raw_addr, list):
            addr_str = ", ".join(str(x) for x in raw_addr if x)
        elif raw_addr:
            addr_str = str(raw_addr)
        else:
            addr_str = None
        address = address or addr_str
        postal_code = postal_code or reg_addr.get("postnummer")
        city = city or reg_addr.get("poststed") or reg_addr.get("kommune")
        country = country or reg_addr.get("land") or "Norge"
    elif profile.get("municipality") and not city:
        city = profile.get("municipality")

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
        evidence_str = "; ".join(filter(None, [
            f"address: {address}" if address else None,
            f"postal: {postal_code} {city}" if postal_code else None,
            f"phone: {phone}" if phone else None,
            f"email: {email}" if email else None,
        ]))
        return ExtractedField(
            field_name="contact",
            value=contact_dict,
            status=FieldStatus.FOUND,
            source_url=source_url or "https://data.brreg.no/enhetsregisteret/api/enheter",
            source_type="website_and_registry" if website_value else "official_registry",
            evidence_span=evidence_str,
            confidence=0.9 if (phone or email or address) else 0.75,
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

    # 1. Official BRREG subunits (underenheter)
    reg_locations = ((profile.get("evidence") or {}).get("locations", {}).get("value") or {}).get("locations") or []
    for loc in reg_locations:
        name = loc.get("name")
        addr_dict = loc.get("address") or {}
        addr_line = addr_dict.get("adresse") if isinstance(addr_dict, dict) else str(addr_dict)
        if isinstance(addr_line, list):
            addr_line = ", ".join(addr_line)
        post_code = addr_dict.get("postnummer") if isinstance(addr_dict, dict) else None
        city = addr_dict.get("poststed") or addr_dict.get("kommune") if isinstance(addr_dict, dict) else None

        key = f"{normalize_legal_name(name)}|{normalize_legal_name(addr_line)}|{post_code}"
        if key not in seen:
            seen.add(key)
            locations.append({
                "name": name,
                "address": addr_line,
                "postal_code": post_code,
                "city": city,
                "country": "Norge",
                "source": "official_subunit",
            })

    # 2. Structured data (LocalBusiness, location)
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

            key = f"{normalize_legal_name(name)}|{normalize_legal_name(street)}|{post_code}"
            if key not in seen and (name or street):
                seen.add(key)
                locations.append({
                    "name": name,
                    "address": street,
                    "postal_code": post_code,
                    "city": city,
                    "country": country,
                    "source": "website_jsonld",
                })

    # 3. Main address as primary location if none found
    if not locations and profile.get("municipality"):
        locations.append({
            "name": profile.get("name"),
            "address": None,
            "postal_code": None,
            "city": profile.get("municipality"),
            "country": "Norge",
            "source": "official_registry",
        })

    if locations:
        return ExtractedField(
            field_name="locations",
            value=locations,
            status=FieldStatus.FOUND,
            source_url=homepage_url or "https://data.brreg.no/enhetsregisteret/api/underenheter",
            source_type="official_subunits_and_website",
            evidence_span=f"Extracted {len(locations)} verified company location(s)",
            confidence=0.9,
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

    # 1. Official BRREG roles (roller)
    reg_roles = ((profile.get("evidence") or {}).get("roles", {}).get("value") or {}).get("roles") or []
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
                    "source": "official_roles",
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
                                    "source": "website_jsonld",
                                })

    # 3. Website team / leadership page
    if website_value:
        for page in website_value.get("pages", []):
            p_url = str(page.get("url") or "").lower()
            if any(term in p_url for term in ("ledelse", "management", "team", "about", "om-oss")):
                p_text = str(page.get("main_text_excerpt") or "")
                # Look for patterns like "Navn Navnesen, Daglig leder" or "Navn Navnesen - CEO"
                for line in p_text.splitlines():
                    line_clean = line.strip()
                    for role_kw in ("daglig leder", "ceo", "styreleder", "cfo", "cto", "gründer", "founder"):
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
                                    "source": "website_team_page",
                                })

    if leadership:
        return ExtractedField(
            field_name="leadership",
            value=leadership,
            status=FieldStatus.FOUND,
            source_url=homepage_url or "https://data.brreg.no/enhetsregisteret/api/enheter/roller",
            source_type="official_roles_and_website",
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
        source_url=homepage_url,
        source_type="company_website",
        note="Inspected but no explicit leadership or executive positions identified",
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
    careers_page = next((p for p in pages if CAREERS_PATH.search(urllib.parse.urlparse(str(p.get("url") or "")).path)), None)

    # Also inspect links or HTML if available
    careers_url = str(careers_page.get("url") or "") if careers_page else None

    if not careers_page:
        # Check priority links or page text for career references
        main_text = " ".join([str(website_value.get("main_text_excerpt") or ""), *[str(p.get("main_text_excerpt") or "") for p in pages]])
        if re.search(r"\b(?:ledige\s+stillinger|karriere|work\s+with\s+us|jobb\s+hos\s+oss)\b", main_text, re.IGNORECASE):
            return ExtractedField(
                field_name="careers",
                value={"has_careers_page": True, "careers_url": None, "hiring_active": None, "openings": []},
                status=FieldStatus.FOUND,
                source_url=homepage_url,
                source_type="website_text",
                evidence_span="Career/job mentions found in site content",
                confidence=0.75,
            )
        return ExtractedField(
            field_name="careers",
            value={"has_careers_page": False, "careers_url": None, "hiring_active": False, "openings": []},
            status=FieldStatus.NOT_FOUND,
            source_url=homepage_url,
            source_type="company_website",
            note="No careers page or hiring indicators detected",
        )

    # Analyze careers page text for active job postings
    careers_text = str(careers_page.get("main_text_excerpt") or "")
    openings: list[str] = []
    hiring_active = False

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

    careers_data = {
        "has_careers_page": True,
        "careers_url": careers_url,
        "hiring_active": hiring_active,
        "openings": openings[:10],
    }

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

    for page in pages:
        p_url = str(page.get("url") or "")
        path = urllib.parse.urlparse(p_url).path
        if NEWS_PATH.search(path):
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
            })

    if news_items:
        return ExtractedField(
            field_name="news",
            value=news_items[:10],
            status=FieldStatus.FOUND,
            source_url=homepage_url,
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
    employees_field = extract_employees(profile, website_value, structured_data, homepage_url)
    careers_field = extract_careers(profile, website_value, homepage_url)
    news_field = extract_news(profile, website_value, homepage_url)

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
    )
