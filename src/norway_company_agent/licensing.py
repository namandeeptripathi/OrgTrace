"""Stage 11: Production Source Licensing, Attribution & Provenance Registry.

Provides explicit, machine-readable licensing and attribution metadata for external sources:
- Official Norwegian registries (Brønnøysundregistrene, NLOD 2.0 open data)
- Public legal repositories (Lovdata, public sector information)
- First-party company websites (corporate copyright, factual extraction)
- Commercial APIs (Brave Search API, commercial terms of service)
- Explicit representation of unverified/uncertain licensing (never guessing)
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LicenseType(str, Enum):
    """Classification of external data source licenses."""
    NLOD_2_0 = "NLOD-2.0"  # Norsk lisens for offentlige data
    PUBLIC_SECTOR_INFORMATION = "public_sector_information"
    FIRST_PARTY_COPYRIGHT = "first_party_copyright"
    COMMERCIAL_TERMS_OF_SERVICE = "commercial_terms_of_service"
    PROPRIETARY_RESTRICTED = "proprietary_restricted"
    UNKNOWN_UNVERIFIED = "unknown_unverified"


@dataclass(frozen=True)
class SourceLicenseInfo:
    """Extensible licensing and attribution metadata for a source domain or entity."""
    source_name: str
    domain: str
    license_type: LicenseType
    license_name: str
    attribution_required: bool
    attribution_statement: str
    is_open_data: bool
    terms_url: str | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "domain": self.domain,
            "license_type": self.license_type.value,
            "license_name": self.license_name,
            "attribution_required": self.attribution_required,
            "attribution_statement": self.attribution_statement,
            "is_open_data": self.is_open_data,
            "terms_url": self.terms_url,
            "notes": self.notes,
        }


# Known source license directory
KNOWN_SOURCE_LICENSES: dict[str, SourceLicenseInfo] = {
    "brreg.no": SourceLicenseInfo(
        source_name="Brønnøysundregistrene (Enhetsregisteret / Regnskapsregisteret)",
        domain="brreg.no",
        license_type=LicenseType.NLOD_2_0,
        license_name="Norsk lisens for offentlige data (NLOD 2.0)",
        attribution_required=True,
        attribution_statement="Inneholder data under Norsk lisens for offentlige data (NLOD) tilgjengeliggjort av Brønnøysundregistrene.",
        is_open_data=True,
        terms_url="https://data.norge.no/nlod/no/2.0",
        notes="Official statutory registry of Norwegian corporate entities and annual accounts.",
    ),
    "data.brreg.no": SourceLicenseInfo(
        source_name="Brønnøysundregistrene Open Data API",
        domain="data.brreg.no",
        license_type=LicenseType.NLOD_2_0,
        license_name="Norsk lisens for offentlige data (NLOD 2.0)",
        attribution_required=True,
        attribution_statement="Inneholder data under Norsk lisens for offentlige data (NLOD) tilgjengeliggjort av Brønnøysundregistrene.",
        is_open_data=True,
        terms_url="https://data.norge.no/nlod/no/2.0",
        notes="Direct REST API for Enhetsregisteret and Regnskapsregisteret.",
    ),
    "lovdata.no": SourceLicenseInfo(
        source_name="Lovdata",
        domain="lovdata.no",
        license_type=LicenseType.PUBLIC_SECTOR_INFORMATION,
        license_name="Public Sector Legal Information",
        attribution_required=True,
        attribution_statement="Kilde: Lovdata.",
        is_open_data=True,
        terms_url="https://lovdata.no/info/om",
        notes="Official Norwegian statutory law and court decisions.",
    ),
    "ssb.no": SourceLicenseInfo(
        source_name="Statistisk sentralbyrå (SSB)",
        domain="ssb.no",
        license_type=LicenseType.NLOD_2_0,
        license_name="Norsk lisens for offentlige data (NLOD 2.0)",
        attribution_required=True,
        attribution_statement="Kilde: Statistisk sentralbyrå (SSB).",
        is_open_data=True,
        terms_url="https://www.ssb.no/omssb/om-nettstedet/lisenser",
        notes="Official Norwegian statistical bureau; NACE codes and economic classifications.",
    ),
    "search.brave.com": SourceLicenseInfo(
        source_name="Brave Search API",
        domain="search.brave.com",
        license_type=LicenseType.COMMERCIAL_TERMS_OF_SERVICE,
        license_name="Brave Search API Terms of Service",
        attribution_required=True,
        attribution_statement="Search candidate results provided via Brave Search API.",
        is_open_data=False,
        terms_url="https://brave.com/search/api/",
        notes="Commercial search API; snippets used as candidates only.",
    ),
    "proff.no": SourceLicenseInfo(
        source_name="Proff.no (Eniro)",
        domain="proff.no",
        license_type=LicenseType.PROPRIETARY_RESTRICTED,
        license_name="Proprietary Commercial Database (Restricted)",
        attribution_required=True,
        attribution_statement="Proff.no is a proprietary directory; automated scraping is strictly blocked by policy.",
        is_open_data=False,
        terms_url="https://www.proff.no/om-proff/vilkar",
        notes="Third-party aggregator; prohibited by OrgTrace source policy.",
    ),
    "purehelp.no": SourceLicenseInfo(
        source_name="Purehelp.no",
        domain="purehelp.no",
        license_type=LicenseType.PROPRIETARY_RESTRICTED,
        license_name="Proprietary Commercial Database (Restricted)",
        attribution_required=True,
        attribution_statement="Purehelp.no is a proprietary directory; automated scraping is strictly blocked by policy.",
        is_open_data=False,
        terms_url="https://www.purehelp.no",
        notes="Third-party aggregator; prohibited by OrgTrace source policy.",
    ),
}


def get_source_license_info(
    url_or_domain: str | None,
    source_type: str | None = None,
) -> SourceLicenseInfo:
    """Resolve licensing and attribution metadata for a source URL or domain."""
    if not url_or_domain:
        return SourceLicenseInfo(
            source_name="Unspecified Source",
            domain="",
            license_type=LicenseType.UNKNOWN_UNVERIFIED,
            license_name="Unknown / Unspecified",
            attribution_required=False,
            attribution_statement="",
            is_open_data=False,
            notes="No source URL or domain provided.",
        )

    # Extract hostname
    target = str(url_or_domain).strip().lower()
    if "://" in target:
        try:
            parsed = urllib.parse.urlsplit(target)
            domain = (parsed.hostname or "").lower()
        except Exception:
            domain = target
    else:
        domain = target.split("/")[0].split(":")[0]

    # Direct match in known directory
    if domain in KNOWN_SOURCE_LICENSES:
        return KNOWN_SOURCE_LICENSES[domain]

    # Check parent domain (e.g. sub.brreg.no -> brreg.no)
    parts = domain.split(".")
    if len(parts) > 2:
        parent = ".".join(parts[-2:])
        if parent in KNOWN_SOURCE_LICENSES:
            return KNOWN_SOURCE_LICENSES[parent]

    # First-party company website
    st = (source_type or "").lower()
    if "website" in st or "company_site" in st or "first_party" in st:
        return SourceLicenseInfo(
            source_name=f"First-Party Company Domain ({domain})",
            domain=domain,
            license_type=LicenseType.FIRST_PARTY_COPYRIGHT,
            license_name="First-Party Website Terms / Fair Use for Factual Identification",
            attribution_required=True,
            attribution_statement=f"Attributed to first-party company website ({domain}).",
            is_open_data=False,
            notes="Public first-party corporate website; factual claims extracted under fair use.",
        )

    # Default: Unknown / Unverified licensing (honest representation)
    return SourceLicenseInfo(
        source_name=f"External Source ({domain})",
        domain=domain,
        license_type=LicenseType.UNKNOWN_UNVERIFIED,
        license_name="Unverified External License",
        attribution_required=True,
        attribution_statement=f"Source: {domain}.",
        is_open_data=False,
        notes="Licensing terms could not be independently verified; factual claims only.",
    )
