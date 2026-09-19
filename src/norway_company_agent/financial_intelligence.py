from __future__ import annotations

import hashlib
import io
import json
import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Generic, TypeVar

from pypdf import PdfReader

from .evidence import evidence
from .identity_engine import canonicalize_org_number, normalize_legal_name
from .official import (
    BRREG_ACCOUNT_PDF,
    BRREG_ACCOUNT_YEARS,
    BRREG_ACCOUNTS,
    _get,
    accounting_obligation_assessment,
)
from .profile_extraction import ExtractedField, FieldStatus

T = TypeVar("T")

# ============================================================================
# 1. DATA MODELS & ENUMS
# ============================================================================

class FinancialAccountType(str, Enum):
    SELSKAP = "SELSKAP"      # Standalone company annual accounts (primary anchor)
    KONSERN = "KONSERN"      # Consolidated corporate group accounts
    OTHER = "OTHER"


@dataclass
class FinancialReportingPeriod:
    start_date: str | None = None
    end_date: str | None = None
    year: int | None = None
    months: int | None = 12

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "year": self.year,
            "months": self.months,
        }


@dataclass
class FinancialStatement:
    record_id: str | int | None
    account_type: str
    period: FinancialReportingPeriod
    currency: str
    revenue: ExtractedField[float | int]
    operating_profit: ExtractedField[float | int]
    profit_before_tax: ExtractedField[float | int]
    net_profit: ExtractedField[float | int]
    total_assets: ExtractedField[float | int]
    total_equity: ExtractedField[float | int]
    total_debt: ExtractedField[float | int]
    source_url: str | None = None
    source_type: str = "official_regnskapsregisteret"
    evidence_span: str | None = None
    confidence: float = 1.0
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "account_type": self.account_type,
            "period": self.period.to_dict(),
            "currency": self.currency,
            "revenue": self.revenue.to_dict(),
            "operating_profit": self.operating_profit.to_dict(),
            "profit_before_tax": self.profit_before_tax.to_dict(),
            "net_profit": self.net_profit.to_dict(),
            "total_assets": self.total_assets.to_dict(),
            "total_equity": self.total_equity.to_dict(),
            "total_debt": self.total_debt.to_dict(),
            "source_url": self.source_url,
            "source_type": self.source_type,
            "evidence_span": self.evidence_span,
            "confidence": round(self.confidence, 3),
            "note": self.note,
        }


@dataclass
class FinancialPdfDocument:
    year: str
    url: str
    document_type: str = "annual_accounts_filing"
    source_type: str = "official_brreg_copy"
    sha256: str | None = None
    is_official_filing: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "year": self.year,
            "url": self.url,
            "document_type": self.document_type,
            "source_type": self.source_type,
            "sha256": self.sha256,
            "is_official_filing": self.is_official_filing,
        }


@dataclass
class CompanyFinancialProfile:
    organisation_number: str
    company_name: str
    accounting_obligation: dict[str, Any] = field(default_factory=dict)
    latest_accounts: FinancialStatement | None = None
    historical_accounts: list[FinancialStatement] = field(default_factory=list)
    financial_pdfs: list[FinancialPdfDocument] = field(default_factory=list)
    available_filing_years: list[str] = field(default_factory=list)
    overall_status: str = "complete"

    def to_dict(self) -> dict[str, Any]:
        return {
            "organisation_number": self.organisation_number,
            "company_name": self.company_name,
            "accounting_obligation": self.accounting_obligation,
            "latest_accounts": self.latest_accounts.to_dict() if self.latest_accounts else None,
            "historical_accounts": [acc.to_dict() for acc in self.historical_accounts],
            "financial_pdfs": [pdf.to_dict() for pdf in self.financial_pdfs],
            "available_filing_years": self.available_filing_years,
            "overall_status": self.overall_status,
        }


# ============================================================================
# 2. EXTRACTION & NORMALIZATION HELPERS
# ============================================================================

def _parse_period(period_data: Any) -> FinancialReportingPeriod:
    """Parse reporting period dates and compute year/months duration."""
    if isinstance(period_data, dict):
        start = period_data.get("fraDato")
        end = period_data.get("tilDato")
        year = None
        if end and re.search(r"^\d{4}", str(end)):
            year = int(str(end)[:4])
        elif start and re.search(r"^\d{4}", str(start)):
            year = int(str(start)[:4])

        months = 12
        if start and end and len(start) >= 7 and len(end) >= 7:
            try:
                y1, m1 = int(start[:4]), int(start[5:7])
                y2, m2 = int(end[:4]), int(end[5:7])
                computed = (y2 - y1) * 12 + (m2 - m1) + 1
                if 1 <= computed <= 36:
                    months = computed
            except (ValueError, IndexError):
                pass

        return FinancialReportingPeriod(
            start_date=start,
            end_date=end,
            year=year,
            months=months,
        )
    elif period_data and str(period_data).isdigit():
        return FinancialReportingPeriod(
            start_date=f"{period_data}-01-01",
            end_date=f"{period_data}-12-31",
            year=int(period_data),
            months=12,
        )

    return FinancialReportingPeriod()


def _make_financial_field(
    field_name: str,
    raw_val: Any,
    currency: str,
    source_url: str | None,
    source_type: str,
    confidence: float = 1.0,
) -> ExtractedField[float | int]:
    """Create typed ExtractedField preserving zero as a valid value and None as missing.

    CRITICAL INVARIANT:
    A value of 0 or 0.0 is a substantive numerical result (e.g. 0 revenue, 0 profit)
    and must be returned as FieldStatus.FOUND with value=0.
    A missing or None value is NOT zero, and must be returned as FieldStatus.NOT_FOUND with value=None.
    """
    if raw_val is not None and isinstance(raw_val, (int, float)):
        return ExtractedField(
            field_name=field_name,
            value=raw_val,
            status=FieldStatus.FOUND,
            source_url=source_url,
            source_type=source_type,
            evidence_span=f"{field_name}: {raw_val} {currency}",
            confidence=confidence,
        )

    return ExtractedField(
        field_name=field_name,
        value=None,
        status=FieldStatus.NOT_FOUND,
        source_url=source_url,
        source_type=source_type,
        confidence=confidence,
        note=f"{field_name} not reported in filing",
    )


# ============================================================================
# 3. OFFICIAL ACCOUNTS INGESTION (Regnskapsregisteret)
# ============================================================================

def extract_official_accounts(
    records_body: Any,
    org: str,
    source_url: str | None = None,
) -> list[FinancialStatement]:
    """Ingest and normalize official accounts from Regnskapsregisteret JSON.

    Preserves exact numeric values (including 0 and negative figures) and strictly
    marks missing metrics as NOT_FOUND with value=None.
    """
    canonical_org = canonicalize_org_number(org) or org
    endpoint_url = source_url or BRREG_ACCOUNTS.format(org=canonical_org)

    raw_records = records_body
    if isinstance(records_body, dict):
        raw_records = records_body.get("records") or records_body.get("regnskap") or [records_body]
    elif not isinstance(records_body, list):
        raw_records = []

    statements: list[FinancialStatement] = []

    for item in raw_records:
        if not isinstance(item, dict):
            continue

        record_id = item.get("id")
        account_type_raw = str(item.get("regnskapstype") or "SELSKAP").upper()
        account_type = (
            FinancialAccountType.KONSERN.value
            if "KONSERN" in account_type_raw
            else FinancialAccountType.SELSKAP.value
        )
        currency = str(item.get("valuta") or "NOK").upper()
        period = _parse_period(item.get("regnskapsperiode") or item.get("period"))

        # Extract line items: support both raw BRREG nested structure and pre-normalized dicts
        revenue_val = (
            item.get("revenue")
            if "revenue" in item
            else _get(item, "resultatregnskapResultat", "driftsresultat", "driftsinntekter", "sumDriftsinntekter")
        )
        operating_profit_val = (
            item.get("operating_result")
            if "operating_result" in item
            else _get(item, "resultatregnskapResultat", "driftsresultat", "driftsresultat")
        )
        profit_before_tax_val = (
            item.get("profit_before_tax")
            if "profit_before_tax" in item
            else _get(item, "resultatregnskapResultat", "ordinaertResultatFoerSkattekostnad")
        )
        net_profit_val = (
            item.get("annual_result")
            if "annual_result" in item
            else _get(item, "resultatregnskapResultat", "aarsresultat")
        )
        total_assets_val = (
            item.get("assets")
            if "assets" in item
            else _get(item, "eiendeler", "sumEiendeler")
        )
        total_equity_val = (
            item.get("equity")
            if "equity" in item
            else _get(item, "egenkapitalGjeld", "egenkapital", "sumEgenkapital")
        )
        total_debt_val = (
            item.get("debt")
            if "debt" in item
            else _get(item, "egenkapitalGjeld", "gjeldOversikt", "sumGjeld")
        )

        source_type = "official_regnskapsregisteret"
        statement = FinancialStatement(
            record_id=record_id,
            account_type=account_type,
            period=period,
            currency=currency,
            revenue=_make_financial_field("revenue", revenue_val, currency, endpoint_url, source_type),
            operating_profit=_make_financial_field("operating_profit", operating_profit_val, currency, endpoint_url, source_type),
            profit_before_tax=_make_financial_field("profit_before_tax", profit_before_tax_val, currency, endpoint_url, source_type),
            net_profit=_make_financial_field("net_profit", net_profit_val, currency, endpoint_url, source_type),
            total_assets=_make_financial_field("total_assets", total_assets_val, currency, endpoint_url, source_type),
            total_equity=_make_financial_field("total_equity", total_equity_val, currency, endpoint_url, source_type),
            total_debt=_make_financial_field("total_debt", total_debt_val, currency, endpoint_url, source_type),
            source_url=endpoint_url,
            source_type=source_type,
            evidence_span=f"Official Regnskapsregisteret filing for period ending {period.end_date or period.year} ({account_type})",
            confidence=1.0,
        )
        statements.append(statement)

    # Sort statements chronologically descending: newest period first,
    # prioritizing SELSKAP (standalone) over KONSERN for the same year
    def _sort_key(s: FinancialStatement) -> tuple[int, int]:
        year = s.period.year or 0
        type_priority = 1 if s.account_type == FinancialAccountType.SELSKAP.value else 0
        return (year, type_priority)

    statements.sort(key=_sort_key, reverse=True)
    return statements


# ============================================================================
# 4. FINANCIAL PDF DETECTION & PARSING
# ============================================================================

FINANCIAL_PDF_PATTERNS = re.compile(
    r"(?i)(?:aarsrapport|årsrapport|arsrapport|delårsrapport|delarsrapport|delaarsrapport|annual[-_]?report|financial[-_]?report|regnskap|interim[-_]?report).*?\.pdf$"
)


def extract_financial_pdfs(
    history_body: Any,
    org: str,
    website_value: dict[str, Any] | None = None,
) -> list[FinancialPdfDocument]:
    """Detect official filing copies and first-party annual report PDFs."""
    canonical_org = canonicalize_org_number(org) or org
    pdf_docs: list[FinancialPdfDocument] = []
    seen_urls: set[str] = set()

    # 1. Official BRREG filing copies
    years: list[str] = []
    if isinstance(history_body, dict):
        years = history_body.get("years") or []
        for pdf_entry in history_body.get("pdfs") or []:
            url = str(pdf_entry.get("url") or "")
            year = str(pdf_entry.get("year") or "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                pdf_docs.append(FinancialPdfDocument(
                    year=year,
                    url=url,
                    document_type="annual_accounts_filing",
                    source_type="official_brreg_copy",
                    is_official_filing=True,
                ))
    elif isinstance(history_body, list):
        years = sorted({str(y) for y in history_body if str(y).isdigit()})

    for year in reversed(years):
        url = BRREG_ACCOUNT_PDF.format(org=canonical_org, year=year)
        if url not in seen_urls:
            seen_urls.add(url)
            pdf_docs.append(FinancialPdfDocument(
                year=year,
                url=url,
                document_type="annual_accounts_filing",
                source_type="official_brreg_copy",
                is_official_filing=True,
            ))

    # 2. Company website financial / annual report PDFs
    if website_value:
        pages = website_value.get("pages", [])
        for page in pages:
            url = str(page.get("url") or "")
            parsed_path = urllib.parse.urlparse(url).path
            if FINANCIAL_PDF_PATTERNS.search(parsed_path):
                if url not in seen_urls:
                    seen_urls.add(url)
                    year_match = re.search(r"\b(20\d{2})\b", parsed_path)
                    pdf_year = year_match.group(1) if year_match else "unknown"
                    doc_type = "interim_report" if "delårs" in parsed_path.lower() or "interim" in parsed_path.lower() else "annual_report"
                    pdf_docs.append(FinancialPdfDocument(
                        year=pdf_year,
                        url=url,
                        document_type=doc_type,
                        source_type="company_website_ir",
                        is_official_filing=False,
                    ))

    return pdf_docs


def _parse_norwegian_amount(amount_str: str) -> float | int | None:
    """Safely parse Norwegian financial number format (e.g. '12 500 000', '12.500.000', '-350 000')."""
    cleaned = amount_str.strip().replace(" ", "").replace("\xa0", "")
    is_negative = False
    if cleaned.startswith("-") or cleaned.startswith("−"):
        is_negative = True
        cleaned = cleaned.lstrip("-−")
    elif cleaned.startswith("(") and cleaned.endswith(")"):
        is_negative = True
        cleaned = cleaned[1:-1]

    # Replace Norwegian decimal comma if present
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif re.search(r"\.\d{1,2}$", cleaned):
        pass
    else:
        cleaned = cleaned.replace(".", "")

    try:
        val = float(cleaned)
        if is_negative:
            val = -val
        return int(val) if val.is_integer() else val
    except ValueError:
        return None


def extract_financials_from_pdf(
    pdf_bytes_or_text: bytes | str,
    org: str,
    year: str,
    source_url: str,
) -> FinancialStatement | None:
    """Extract financial metrics from PDF document with exact-entity verification."""
    canonical_org = canonicalize_org_number(org) or org

    # Extract text
    if isinstance(pdf_bytes_or_text, bytes):
        try:
            reader = PdfReader(io.BytesIO(pdf_bytes_or_text), strict=False)
            pages_text = []
            for p in reader.pages[:100]:
                pages_text.append(p.extract_text() or "")
            text = "\n".join(pages_text)
        except Exception:
            return None
    else:
        text = str(pdf_bytes_or_text)

    # EXACT-ENTITY IDENTITY SAFEGUARD:
    # Document must contain the 9-digit organisation number to prevent parent/subsidiary confusion
    clean_digits = re.sub(r"\D", "", text)
    if canonical_org not in clean_digits:
        return None

    currency = "NOK"
    if re.search(r"\b(?:EUR|euro)\b", text, re.I):
        currency = "EUR"
    elif re.search(r"\b(?:USD|dollars?)\b", text, re.I):
        currency = "USD"

    # Multiplier: check if numbers are in thousands (tusen / TNOK) or millions (MNOK)
    multiplier = 1
    if re.search(r"\b(?:tall\s+i\s+tusen|i\s+tusen|tusen\s+kroner|TNOK)\b", text, re.I):
        multiplier = 1_000
    elif re.search(r"\b(?:tall\s+i\s+millioner|i\s+millioner|MNOK)\b", text, re.I):
        multiplier = 1_000_000

    def _extract_metric(patterns: list[str]) -> tuple[float | int | None, str | None]:
        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
            if match:
                raw_amt = match.group(1)
                parsed = _parse_norwegian_amount(raw_amt)
                if parsed is not None:
                    final_val = parsed * multiplier
                    span = match.group(0).strip()[:150]
                    return final_val, span
        return None, None

    num_pattern = r"([−\-(\s]?[0-9][0-9\s.,\xa0]{0,14}\)?)"

    # Line item patterns
    rev_val, rev_span = _extract_metric([
        rf"(?:sum\s+driftsinntekter|driftsinntekter|salgsinntekter|total\s+revenue)[\s:]+{num_pattern}",
    ])
    op_val, op_span = _extract_metric([
        rf"(?:driftsresultat|operating\s+profit|driftsresultat\s*\(ebit\))[\s:]+{num_pattern}",
    ])
    pbt_val, pbt_span = _extract_metric([
        rf"(?:ordinært\s+resultat\s+før\s+skattekostnad|resultat\s+før\s+skatt|profit\s+before\s+tax)[\s:]+{num_pattern}",
    ])
    net_val, net_span = _extract_metric([
        rf"(?:årsresultat|aarsresultat|net\s+profit|periodens\s+resultat)[\s:]+{num_pattern}",
    ])
    assets_val, assets_span = _extract_metric([
        rf"(?:sum\s+eiendeler|totale\s+eiendeler|total\s+assets)[\s:]+{num_pattern}",
    ])
    equity_val, equity_span = _extract_metric([
        rf"(?:sum\s+egenkapital|total\s+equity)[\s:]+{num_pattern}",
    ])
    debt_val, debt_span = _extract_metric([
        rf"(?:sum\s+gjeld|totale\s+forpliktelser|total\s+liabilities)[\s:]+{num_pattern}",
    ])

    has_any = any(x is not None for x in (rev_val, op_val, pbt_val, net_val, assets_val, equity_val, debt_val))
    if not has_any:
        return None

    period = FinancialReportingPeriod(
        start_date=f"{year}-01-01" if year.isdigit() else None,
        end_date=f"{year}-12-31" if year.isdigit() else None,
        year=int(year) if year.isdigit() else None,
        months=12,
    )

    source_type = "official_annual_report_pdf"
    return FinancialStatement(
        record_id=f"pdf-{canonical_org}-{year}",
        account_type=FinancialAccountType.SELSKAP.value,
        period=period,
        currency=currency,
        revenue=_make_financial_field("revenue", rev_val, currency, source_url, source_type, 0.9),
        operating_profit=_make_financial_field("operating_profit", op_val, currency, source_url, source_type, 0.9),
        profit_before_tax=_make_financial_field("profit_before_tax", pbt_val, currency, source_url, source_type, 0.9),
        net_profit=_make_financial_field("net_profit", net_val, currency, source_url, source_type, 0.9),
        total_assets=_make_financial_field("total_assets", assets_val, currency, source_url, source_type, 0.9),
        total_equity=_make_financial_field("total_equity", equity_val, currency, source_url, source_type, 0.9),
        total_debt=_make_financial_field("total_debt", debt_val, currency, source_url, source_type, 0.9),
        source_url=source_url,
        source_type=source_type,
        evidence_span=f"Extracted from annual report PDF for {year} (exact org {canonical_org} verified)",
        confidence=0.9,
    )


# ============================================================================
# 5. MAIN FINANCIAL INTELLIGENCE PIPELINE
# ============================================================================

def build_company_financial_profile(
    profile: dict[str, Any],
    *,
    official_accounts_data: Any = None,
    official_history_data: Any = None,
    website_data: Any = None,
    pdf_content: bytes | str | None = None,
    pdf_year: str | None = None,
    pdf_url: str | None = None,
) -> CompanyFinancialProfile:
    """Build comprehensive, evidence-attributed financial profile for a company.

    Enforces that missing metrics are never converted to zero.
    """
    raw_org = str(profile.get("organisation_number") or "").strip()
    org = canonicalize_org_number(raw_org) or raw_org
    name = str(profile.get("name") or "").strip()

    # 1. Official accounting obligation assessment
    obligation = (profile.get("evidence") or {}).get("accounting_obligation")
    if obligation is None:
        obligation = accounting_obligation_assessment(profile)

    # 2. Ingest official accounts
    accounts_source = official_accounts_data
    if accounts_source is None:
        accounts_source = ((profile.get("evidence") or {}).get("financials") or {}).get("value")

    statements = extract_official_accounts(accounts_source, org)

    # 3. Detect financial PDFs (official filing copies + website IR)
    history_source = official_history_data
    if history_source is None:
        history_source = ((profile.get("evidence") or {}).get("financial_history") or {}).get("value")

    website_source = website_data
    if website_source is None:
        website_record = (profile.get("evidence") or {}).get("website") or {}
        if website_record.get("status") == "available":
            website_source = website_record.get("value")

    pdfs = extract_financial_pdfs(history_source, org, website_source)

    # 4. Extract from PDF if provided
    if pdf_content:
        year_to_use = pdf_year or (pdfs[0].year if pdfs else "unknown")
        url_to_use = pdf_url or (pdfs[0].url if pdfs else BRREG_ACCOUNT_PDF.format(org=org, year=year_to_use))
        pdf_statement = extract_financials_from_pdf(pdf_content, org, year_to_use, url_to_use)
        if pdf_statement:
            # If no statements existed, or this year is newer, integrate
            existing_years = {s.period.year for s in statements if s.period.year}
            if pdf_statement.period.year not in existing_years:
                statements.append(pdf_statement)
                statements.sort(key=lambda s: s.period.year or 0, reverse=True)

    available_years = [
        str(s.period.year) for s in statements if s.period.year
    ] or [p.year for p in pdfs if p.year and p.year.isdigit()]
    available_years = sorted(list(set(available_years)), reverse=True)

    latest = statements[0] if statements else None

    # Determine overall status
    if latest:
        overall_status = "complete"
    elif pdfs:
        overall_status = "partial"
    elif obligation.get("value", {}).get("classification") == "threshold_or_activity_dependent":
        overall_status = "exempt_or_threshold_dependent"
    else:
        overall_status = "no_accounts_available"

    return CompanyFinancialProfile(
        organisation_number=org,
        company_name=name,
        accounting_obligation=obligation,
        latest_accounts=latest,
        historical_accounts=statements,
        financial_pdfs=pdfs,
        available_filing_years=available_years,
        overall_status=overall_status,
    )
