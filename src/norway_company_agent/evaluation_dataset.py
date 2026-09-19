"""Stage 10: Evaluation Dataset.

Provides a deterministic, machine-readable evaluation dataset representing:
- exact Norwegian companies
- ambiguous company names
- subsidiaries
- parent companies
- similarly named companies
- companies with weak web presence
- companies with missing information
- companies with changed information
- external/non-target companies
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CaseCategory(str, Enum):
    """Categorization of evaluation benchmark cases."""
    EXACT_COMPANY = "exact_company"
    AMBIGUOUS_NAME = "ambiguous_name"
    SUBSIDIARY = "subsidiary"
    PARENT_COMPANY = "parent_company"
    SIMILARLY_NAMED = "similarly_named"
    WEAK_WEB_PRESENCE = "weak_web_presence"
    MISSING_INFORMATION = "missing_information"
    CHANGED_INFORMATION = "changed_information"
    EXTERNAL_NON_TARGET = "external_non_target"


@dataclass
class ExpectedOutcome:
    """Explicit ground-truth expectations for an evaluation case."""
    expected_org_number: str | None
    expected_name: str | None
    expected_verdict_status: str  # e.g. "verified", "ambiguous", "rejected", "not_found"
    should_publish_website: bool = False
    expected_website: str | None = None
    should_have_financials: bool = False
    expected_financial_revenue: float | None = None
    expected_leadership: list[str] = field(default_factory=list)
    is_external_target: bool = True
    expected_changes: list[str] = field(default_factory=list)
    allowed_missing_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_org_number": self.expected_org_number,
            "expected_name": self.expected_name,
            "expected_verdict_status": self.expected_verdict_status,
            "should_publish_website": self.should_publish_website,
            "expected_website": self.expected_website,
            "should_have_financials": self.should_have_financials,
            "expected_financial_revenue": self.expected_financial_revenue,
            "expected_leadership": list(self.expected_leadership),
            "is_external_target": self.is_external_target,
            "expected_changes": list(self.expected_changes),
            "allowed_missing_fields": list(self.allowed_missing_fields),
        }


@dataclass
class EvaluationCase:
    """A single deterministic test case in the evaluation dataset."""
    case_id: str
    category: CaseCategory
    description: str
    input_query: dict[str, Any]
    ground_truth: ExpectedOutcome
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category.value,
            "description": self.description,
            "input_query": dict(self.input_query),
            "ground_truth": self.ground_truth.to_dict(),
            "metadata": dict(self.metadata),
        }


def build_deterministic_evaluation_dataset() -> list[EvaluationCase]:
    """Construct the comprehensive 9-category deterministic evaluation dataset."""
    return [
        # 1. Exact Norwegian Company
        EvaluationCase(
            case_id="case-01-exact",
            category=CaseCategory.EXACT_COMPANY,
            description="Established active AS with known official website, accounts, and leadership",
            input_query={
                "organisation_number": "923609016",
                "name": "Norsk Fiskeeksport AS",
                "municipality": "Bergen",
                "website": "https://norskfiske.no",
            },
            ground_truth=ExpectedOutcome(
                expected_org_number="923609016",
                expected_name="Norsk Fiskeeksport AS",
                expected_verdict_status="verified",
                should_publish_website=True,
                expected_website="https://norskfiske.no",
                should_have_financials=True,
                expected_financial_revenue=150000000.0,
                expected_leadership=["Kari Nordmann"],
            ),
        ),

        # 2. Ambiguous Company Name
        EvaluationCase(
            case_id="case-02-ambiguous",
            category=CaseCategory.AMBIGUOUS_NAME,
            description="Generic name matching multiple entities without unique org number",
            input_query={
                "name": "Norsk Fisk",
                "municipality": "Oslo",
            },
            ground_truth=ExpectedOutcome(
                expected_org_number=None,
                expected_name=None,
                expected_verdict_status="ambiguous",
                should_publish_website=False,
                should_have_financials=False,
            ),
        ),

        # 3. Subsidiary Company
        EvaluationCase(
            case_id="case-03-subsidiary",
            category=CaseCategory.SUBSIDIARY,
            description="Operating subsidiary with distinct org number; must not conflate parent holding accounts",
            input_query={
                "organisation_number": "912345678",
                "name": "Fjord Laks Drift AS",
                "parent_name": "Fjord Seafood Group ASA",
                "website": "https://fjordlaks.no",
            },
            ground_truth=ExpectedOutcome(
                expected_org_number="912345678",
                expected_name="Fjord Laks Drift AS",
                expected_verdict_status="verified",
                should_publish_website=True,
                expected_website="https://fjordlaks.no",
                should_have_financials=True,
                expected_financial_revenue=50000000.0,
                allowed_missing_fields=["parent_accounts"],
            ),
        ),

        # 4. Parent Company
        EvaluationCase(
            case_id="case-04-parent",
            category=CaseCategory.PARENT_COMPANY,
            description="Holding entity with consolidated konsern accounts and multiple subsidiaries",
            input_query={
                "organisation_number": "987654321",
                "name": "Fjord Seafood Group ASA",
                "website": "https://fjordgroup.no",
            },
            ground_truth=ExpectedOutcome(
                expected_org_number="987654321",
                expected_name="Fjord Seafood Group ASA",
                expected_verdict_status="verified",
                should_publish_website=True,
                expected_website="https://fjordgroup.no",
                should_have_financials=True,
                expected_financial_revenue=1200000000.0,
                expected_leadership=["Arne Konsernsjef"],
            ),
        ),

        # 5. Similarly Named Companies
        EvaluationCase(
            case_id="case-05-similarly-named",
            category=CaseCategory.SIMILARLY_NAMED,
            description="Company with name very similar to target, must reject false attribution",
            input_query={
                "organisation_number": "999111222",
                "name": "Norsk Fiskeimport AS",  # Similar to Norsk Fiskeeksport
                "municipality": "Oslo",
            },
            ground_truth=ExpectedOutcome(
                expected_org_number="999111222",
                expected_name="Norsk Fiskeimport AS",
                expected_verdict_status="verified",
                should_publish_website=False,
                should_have_financials=False,
            ),
        ),

        # 6. Weak Web Presence
        EvaluationCase(
            case_id="case-06-weak-web",
            category=CaseCategory.WEAK_WEB_PRESENCE,
            description="Company with no website or parked domain; must safely abstain without hallucination",
            input_query={
                "organisation_number": "933444555",
                "name": "Vestland Stillasmontering ENK",
                "municipality": "Voss",
            },
            ground_truth=ExpectedOutcome(
                expected_org_number="933444555",
                expected_name="Vestland Stillasmontering ENK",
                expected_verdict_status="verified",
                should_publish_website=False,
                expected_website=None,
                should_have_financials=False,
                allowed_missing_fields=["website", "financials"],
            ),
        ),

        # 7. Missing Information
        EvaluationCase(
            case_id="case-07-missing-info",
            category=CaseCategory.MISSING_INFORMATION,
            description="Exempt ENK with no statutory annual accounts filing; missing preserved as None, never zero",
            input_query={
                "organisation_number": "944555666",
                "name": "Nordic Design Studio Ola Nordmann",
                "legal_form": "ENK",
            },
            ground_truth=ExpectedOutcome(
                expected_org_number="944555666",
                expected_name="Nordic Design Studio Ola Nordmann",
                expected_verdict_status="verified",
                should_publish_website=False,
                should_have_financials=False,
                expected_financial_revenue=None,
                allowed_missing_fields=["financials", "annual_accounts"],
            ),
        ),

        # 8. Changed Information
        EvaluationCase(
            case_id="case-08-changed-info",
            category=CaseCategory.CHANGED_INFORMATION,
            description="Company that modified its name from AS to ASA; tests refresh correctness",
            input_query={
                "organisation_number": "955666777",
                "name": "Bergen Teknologi ASA",  # Previous: Bergen Teknologi AS
                "previous_name": "Bergen Teknologi AS",
                "website": "https://bergentek.no",
            },
            ground_truth=ExpectedOutcome(
                expected_org_number="955666777",
                expected_name="Bergen Teknologi ASA",
                expected_verdict_status="verified",
                should_publish_website=True,
                expected_website="https://bergentek.no",
                should_have_financials=True,
                expected_changes=["legal_name", "legal_form"],
            ),
        ),

        # 9. External Non-Target Company
        EvaluationCase(
            case_id="case-09-non-target",
            category=CaseCategory.EXTERNAL_NON_TARGET,
            description="Foreign or third-party directory listing that is not a Norwegian target entity",
            input_query={
                "name": "Swedish Fish Export AB",
                "country": "SE",
                "source_url": "https://proff.no/selskap/foreign/123",
            },
            ground_truth=ExpectedOutcome(
                expected_org_number=None,
                expected_name=None,
                expected_verdict_status="rejected",
                is_external_target=False,
                should_publish_website=False,
            ),
        ),
    ]
