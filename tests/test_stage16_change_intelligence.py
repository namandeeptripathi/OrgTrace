"""Stage 16: Freshness & Change Intelligence Unit and Integration Tests.

Validates:
1. Field normalization (strings, URLs, numbers, dates, addresses).
2. Missing data rule: Missing data is NEVER a change (e.g. 42 -> None is VALUE_UNAVAILABLE, not 42 -> 0).
3. Field comparison engine: structured change output with categories, types, materiality, severity, confidence.
4. Status change detection: ACTIVE -> DISSOLVED / BANKRUPT / UNDER_LIQUIDATION (CRITICAL).
5. Industry change detection: NACE codes preferred over label variations.
6. Website change detection: canonical domains, crawl failure distinction (WEBSITE_UNAVAILABLE, not removed).
7. Address change detection: structured components, formatting noise vs real city relocations.
8. Employee change detection: delta and percentage thresholds (42 -> 43 non-material vs 42 -> 120 material).
9. Financial change handling: period-by-period comparison (new period available vs same-period restatement).
10. Registration information & Identity conflict: org number mismatch is IDENTITY_CONFLICT (CRITICAL).
11. First observation handling: INITIAL_OBSERVATION with zero false alarms.
12. End-to-end integration test with evidence verification and clean report schema.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from norway_company_agent.change_intelligence import (
    CanonicalProfile,
    ChangeCategory,
    ChangeEvidence,
    ChangeRecord,
    ChangeReport,
    ChangeType,
    CompanySnapshot,
    MaterialitySeverity,
    SnapshotClaim,
    WORKFORCE_HIGH_SEVERITY_PERCENTAGE,
    WORKFORCE_LARGE_MOVEMENT_DELTA,
    WORKFORCE_MIN_ABSOLUTE_DELTA,
    WORKFORCE_MIN_PERCENTAGE_DELTA,
    analyze_profile_changes,
    compare_canonical_profiles,
    normalize_address_components,
    normalize_canonical_snapshot,
    normalize_date_iso,
    normalize_domain_canonical,
    normalize_number_value,
    normalize_string_field,
    normalize_url_canonical,
)


class Stage16NormalizationTests(unittest.TestCase):
    """Test suite for field-aware semantic normalization."""

    def test_string_normalization_whitespace_and_casing(self):
        s1 = "Example AS"
        s2 = " example as "
        s3 = "EXAMPLE AS"
        # normalize_string_field trims and collapses whitespace
        self.assertEqual(normalize_string_field(s1), "Example AS")
        self.assertEqual(normalize_string_field(s2), "example as")
        # Casefold comparison for general entity name equivalence
        self.assertEqual(normalize_string_field(s1).casefold(), normalize_string_field(s2).casefold())
        self.assertEqual(normalize_string_field(s1).casefold(), normalize_string_field(s3).casefold())

    def test_url_normalization_canonical(self):
        urls = [
            "https://example.no",
            "https://example.no/",
            "http://example.no/",
            "https://www.example.no/",
            "http://www.example.no",
        ]
        expected = "https://example.no"
        for u in urls:
            self.assertEqual(normalize_url_canonical(u), expected)

    def test_url_normalization_preserves_meaningful_paths(self):
        u1 = "https://example.no/about"
        u2 = "https://example.no/contact"
        self.assertNotEqual(normalize_url_canonical(u1), normalize_url_canonical(u2))
        self.assertEqual(normalize_url_canonical("https://example.no/about/"), "https://example.no/about")

    def test_domain_canonical_extraction(self):
        self.assertEqual(normalize_domain_canonical("https://example.no"), "example.no")
        self.assertEqual(normalize_domain_canonical("http://www.example.no/portal/"), "example.no")
        self.assertEqual(normalize_domain_canonical("examplegroup.no"), "examplegroup.no")
        self.assertNotEqual(
            normalize_domain_canonical("https://example.no"),
            normalize_domain_canonical("https://examplegroup.no"),
        )

    def test_number_normalization(self):
        self.assertEqual(normalize_number_value(42), 42)
        self.assertEqual(normalize_number_value(42.0), 42)
        self.assertEqual(normalize_number_value("42"), 42)
        self.assertEqual(normalize_number_value(" 42 "), 42)
        self.assertEqual(normalize_number_value(42.5), 42.5)
        self.assertEqual(normalize_number_value("42.5"), 42.5)
        self.assertEqual(normalize_number_value("42,5"), 42.5)
        self.assertIsNone(normalize_number_value(None))
        self.assertIsNone(normalize_number_value(""))

    def test_date_iso_normalization(self):
        dates = [
            "2026-01-15",
            "15.01.2026",
            "2026/01/15",
            "15/01/2026",
            "2026-01-15T00:00:00Z",
            "2026-01-15 12:30:00",
        ]
        for d in dates:
            self.assertEqual(normalize_date_iso(d), "2026-01-15")

    def test_address_normalization(self):
        addr1 = {"street": "Exampleveien 10", "city": "Oslo", "postal_code": "0150", "country": "Norway"}
        addr2 = {"street": "Exampleveien 10,", "city": " Oslo ", "postal_code": " 0150 ", "country": "Norge"}
        norm1 = normalize_address_components(addr1)
        norm2 = normalize_address_components(addr2)

        self.assertEqual(norm1["street"], "Exampleveien 10")
        self.assertEqual(norm2["street"], "Exampleveien 10")
        self.assertEqual(norm1["city"], "Oslo")
        self.assertEqual(norm2["city"], "Oslo")
        self.assertEqual(norm1["postal_code"], "0150")
        self.assertEqual(norm2["postal_code"], "0150")
        self.assertEqual(norm1["country"], "Norway")
        self.assertEqual(norm2["country"], "Norway")
        self.assertEqual(norm1, norm2)


class Stage16ChangeIntelligenceTests(unittest.TestCase):
    """Test suite covering the 12 primary change intelligence & false-positive scenarios."""

    def setUp(self):
        self.base_profile = {
            "organisation_number": "923609016",
            "name": "Equinor Energy AS",
            "status": "ACTIVE",
            "industry_code": "06.100",
            "industry_label": "Utvinning av raaolje",
            "website": "https://www.equinor.com",
            "address": {
                "street": "Forusbeen 50",
                "postal_code": "4035",
                "city": "STAVANGER",
                "country": "Norway",
            },
            "employees": 1000,
            "financials": {
                "2024": {
                    "period": "2024",
                    "revenue": 50000000000,
                    "profit": 10000000000,
                    "currency": "NOK",
                }
            },
            "registration": {
                "legal_form": "AS",
                "registered": "2000-01-01",
                "status": "ACTIVE",
            },
            "observed_at": "2026-01-01T00:00:00Z",
            "evidence": {
                "registry": {
                    "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
                    "retrieved_at": "2026-01-01T00:00:00Z",
                    "status": "available",
                }
            },
        }

    # Scenario 1: String normalization (no false change)
    def test_scenario_01_string_normalization_no_change(self):
        current = dict(self.base_profile)
        current["name"] = " equinor energy as "
        report = analyze_profile_changes(self.base_profile, current)
        self.assertEqual(report.status, "NO_CHANGES")
        self.assertEqual(report.material_changes, 0)
        name_changes = [c for c in report.changes if c.field == "name"]
        self.assertEqual(len(name_changes), 0)

    # Scenario 2: URL normalization (trailing slash / www / scheme -> no false change)
    def test_scenario_02_url_normalization_no_change(self):
        current = dict(self.base_profile)
        current["website"] = "http://equinor.com/"
        report = analyze_profile_changes(self.base_profile, current)
        self.assertEqual(report.material_changes, 0)
        web_changes = [c for c in report.changes if c.field == "website"]
        self.assertEqual(len(web_changes), 0)

    # Scenario 3: Real website change (example.no -> examplegroup.no)
    def test_scenario_03_real_website_change_detected(self):
        current = dict(self.base_profile)
        current["website"] = "https://www.equinorgroup.no"
        report = analyze_profile_changes(self.base_profile, current)
        self.assertEqual(report.status, "CHANGES_DETECTED")
        web_changes = [c for c in report.changes if c.field == "website"]
        self.assertEqual(len(web_changes), 1)
        ch = web_changes[0]
        self.assertEqual(ch.category, ChangeCategory.WEBSITE)
        self.assertEqual(ch.change_type, ChangeType.MODIFIED)
        self.assertTrue(ch.material)
        self.assertEqual(ch.severity, MaterialitySeverity.MEDIUM)
        self.assertEqual(ch.previous, "https://www.equinor.com")
        self.assertEqual(ch.current, "https://www.equinorgroup.no")

    # Scenario 4: Missing employee data (42 -> None is VALUE_UNAVAILABLE, NOT 42 -> 0)
    def test_scenario_04_missing_employee_data_never_zero_or_removal(self):
        prev = dict(self.base_profile)
        prev["employees"] = 42
        curr = dict(self.base_profile)
        curr["employees"] = None  # Crawl failed or field absent
        report = analyze_profile_changes(prev, curr)
        emp_changes = [c for c in report.changes if c.field == "employees"]
        self.assertEqual(len(emp_changes), 1)
        ch = emp_changes[0]
        self.assertEqual(ch.change_type, ChangeType.VALUE_UNAVAILABLE)
        self.assertFalse(ch.material)
        self.assertEqual(ch.severity, MaterialitySeverity.NONE)
        self.assertEqual(ch.previous, 42)
        self.assertIsNone(ch.current)
        self.assertIn("not treated as 0", ch.explanation)

    # Scenario 5: Address formatting (punctuation noise -> no change)
    def test_scenario_05_address_formatting_noise_suppressed(self):
        prev = dict(self.base_profile)
        prev["address"] = {"street": "Exampleveien 10", "city": "Oslo", "postal_code": "0150", "country": "Norway"}
        curr = dict(self.base_profile)
        curr["address"] = {"street": "Exampleveien 10,", "city": " Oslo ", "postal_code": "0150", "country": "Norway"}
        report = analyze_profile_changes(prev, curr)
        addr_changes = [c for c in report.changes if c.category == ChangeCategory.ADDRESS]
        self.assertEqual(len(addr_changes), 0)

    # Scenario 6: Real address relocation (Oslo -> Bergen)
    def test_scenario_06_real_address_relocation_is_material(self):
        prev = dict(self.base_profile)
        prev["address"] = {"street": "Storgata 1", "city": "Oslo", "postal_code": "0150", "country": "Norway"}
        curr = dict(self.base_profile)
        curr["address"] = {"street": "Bryggen 5", "city": "Bergen", "postal_code": "5003", "country": "Norway"}
        report = analyze_profile_changes(prev, curr)
        self.assertEqual(report.status, "CHANGES_DETECTED")
        city_changes = [c for c in report.changes if c.field == "address.city"]
        self.assertEqual(len(city_changes), 1)
        ch = city_changes[0]
        self.assertEqual(ch.category, ChangeCategory.ADDRESS)
        self.assertTrue(ch.material)
        self.assertEqual(ch.severity, MaterialitySeverity.HIGH)
        self.assertEqual(ch.previous, "Oslo")
        self.assertEqual(ch.current, "Bergen")

    # Scenario 7: Employee change thresholds (42 -> 43 low vs 42 -> 120 material)
    def test_scenario_07_workforce_thresholds(self):
        prev = dict(self.base_profile)
        prev["employees"] = 42

        # 42 -> 43: small fluctuation (delta=+1, +2.4%) -> LOW severity, material=False
        curr_small = dict(self.base_profile)
        curr_small["employees"] = 43
        report_small = analyze_profile_changes(prev, curr_small)
        ch_small = [c for c in report_small.changes if c.field == "employees"][0]
        self.assertEqual(ch_small.change_type, ChangeType.INCREASE)
        self.assertFalse(ch_small.material)
        self.assertEqual(ch_small.severity, MaterialitySeverity.LOW)
        self.assertEqual(ch_small.details["delta"], 1)

        # 42 -> 120: significant workforce movement (delta=+78, +185.7%) -> HIGH severity, material=True
        curr_large = dict(self.base_profile)
        curr_large["employees"] = 120
        report_large = analyze_profile_changes(prev, curr_large)
        ch_large = [c for c in report_large.changes if c.field == "employees"][0]
        self.assertEqual(ch_large.change_type, ChangeType.INCREASE)
        self.assertTrue(ch_large.material)
        self.assertEqual(ch_large.severity, MaterialitySeverity.HIGH)
        self.assertEqual(ch_large.details["delta"], 78)

    # Scenario 8: Status changes (ACTIVE -> DISSOLVED / BANKRUPT / UNDER_LIQUIDATION -> CRITICAL)
    def test_scenario_08_status_transition_critical(self):
        # ACTIVE -> DISSOLVED
        curr_dissolved = dict(self.base_profile)
        curr_dissolved["status"] = "DISSOLVED"
        report_d = analyze_profile_changes(self.base_profile, curr_dissolved)
        ch_d = [c for c in report_d.changes if c.field == "status"][0]
        self.assertEqual(ch_d.category, ChangeCategory.STATUS)
        self.assertTrue(ch_d.material)
        self.assertEqual(ch_d.severity, MaterialitySeverity.CRITICAL)

        # ACTIVE -> BANKRUPT
        curr_bankrupt = dict(self.base_profile)
        curr_bankrupt["status"] = "BANKRUPT"
        report_b = analyze_profile_changes(self.base_profile, curr_bankrupt)
        ch_b = [c for c in report_b.changes if c.field == "status"][0]
        self.assertEqual(ch_b.severity, MaterialitySeverity.CRITICAL)

        # ACTIVE -> UNDER_LIQUIDATION
        curr_liq = dict(self.base_profile)
        curr_liq["status"] = "UNDER_LIQUIDATION"
        report_l = analyze_profile_changes(self.base_profile, curr_liq)
        ch_l = [c for c in report_l.changes if c.field == "status"][0]
        self.assertEqual(ch_l.severity, MaterialitySeverity.CRITICAL)

    # Scenario 9: Industry classification (NACE code comparison vs label wording)
    def test_scenario_09_industry_code_preferred_over_label(self):
        prev = dict(self.base_profile)
        prev["industry_code"] = "62.010"
        prev["industry_label"] = "Software development"

        # Identical code, slightly varied wording -> UNCHANGED
        curr_same_code = dict(self.base_profile)
        curr_same_code["industry_code"] = "62.010"
        curr_same_code["industry_label"] = "Dataprogrammering og systemutvikling"
        report_same = analyze_profile_changes(prev, curr_same_code)
        ind_changes_same = [c for c in report_same.changes if c.category == ChangeCategory.INDUSTRY]
        self.assertEqual(len(ind_changes_same), 0)

        # Different code (62.010 -> 68.200) -> MATERIAL CHANGE (HIGH)
        curr_diff_code = dict(self.base_profile)
        curr_diff_code["industry_code"] = "68.200"
        curr_diff_code["industry_label"] = "Utleie av egen eller leid fast eiendom"
        report_diff = analyze_profile_changes(prev, curr_diff_code)
        ind_changes_diff = [c for c in report_diff.changes if c.category == ChangeCategory.INDUSTRY]
        self.assertEqual(len(ind_changes_diff), 1)
        ch = ind_changes_diff[0]
        self.assertTrue(ch.material)
        self.assertEqual(ch.severity, MaterialitySeverity.HIGH)
        self.assertIn("62.010", str(ch.previous))
        self.assertIn("68.200", str(ch.current))

    # Scenario 10: Financial reporting period handling
    def test_scenario_10_financial_periods_distinguish_new_vs_restatement(self):
        prev = dict(self.base_profile)
        prev["financials"] = {
            "2024": {
                "period": "2024",
                "revenue": 10000000,
                "profit": 2000000,
            }
        }

        # Case A: New reporting period becomes available (2025)
        curr_new_period = dict(self.base_profile)
        curr_new_period["financials"] = {
            "2024": {
                "period": "2024",
                "revenue": 10000000,
                "profit": 2000000,
            },
            "2025": {
                "period": "2025",
                "revenue": 12000000,
                "profit": 2500000,
            },
        }
        report_new = analyze_profile_changes(prev, curr_new_period)
        fin_changes = [c for c in report_new.changes if c.category == ChangeCategory.FINANCIAL]
        self.assertEqual(len(fin_changes), 1)
        ch_new = fin_changes[0]
        self.assertEqual(ch_new.change_type, ChangeType.NEW_PERIOD_AVAILABLE)
        self.assertEqual(ch_new.field, "financials.2025")
        self.assertTrue(ch_new.material)
        self.assertEqual(ch_new.severity, MaterialitySeverity.MEDIUM)
        # Note: 2024 was NOT reported as changed!
        changes_2024 = [c for c in report_new.changes if "2024" in c.field]
        self.assertEqual(len(changes_2024), 0)

        # Case B: Same period revision (2024 revenue 10M -> 11M)
        curr_restate = dict(self.base_profile)
        curr_restate["financials"] = {
            "2024": {
                "period": "2024",
                "revenue": 11000000,  # Restated from 10M
                "profit": 2000000,
            }
        }
        report_restate = analyze_profile_changes(prev, curr_restate)
        fin_restate = [c for c in report_restate.changes if c.category == ChangeCategory.FINANCIAL]
        self.assertEqual(len(fin_restate), 1)
        ch_res = fin_restate[0]
        self.assertEqual(ch_res.change_type, ChangeType.MODIFIED)
        self.assertEqual(ch_res.field, "financials.2024.revenue")
        self.assertEqual(ch_res.previous, 10000000)
        self.assertEqual(ch_res.current, 11000000)
        self.assertTrue(ch_res.material)
        self.assertIn("restatement", ch_res.explanation)

    # Scenario 11: Identity conflict (different organisation numbers)
    def test_scenario_11_identity_conflict_requires_validation(self):
        prev = dict(self.base_profile)
        prev["organisation_number"] = "123456789"
        curr = dict(self.base_profile)
        curr["organisation_number"] = "987654321"

        report = analyze_profile_changes(prev, curr)
        self.assertEqual(report.status, "IDENTITY_CONFLICT")
        self.assertEqual(report.material_changes, 1)
        ch = report.changes[0]
        self.assertEqual(ch.category, ChangeCategory.IDENTITY)
        self.assertEqual(ch.change_type, ChangeType.IDENTITY_CONFLICT)
        self.assertEqual(ch.severity, MaterialitySeverity.CRITICAL)
        self.assertEqual(ch.confidence, 1.0)
        self.assertIn("CRITICAL IDENTITY CONFLICT", ch.explanation)

    # Scenario 12: Website unavailable (failed crawl is NOT website removal)
    def test_scenario_12_website_crawl_failure_is_not_removal(self):
        prev = dict(self.base_profile)
        prev["website"] = "https://example.no"

        curr = dict(self.base_profile)
        curr["website"] = None
        curr["evidence"] = {
            "website": {
                "status": "failed",
                "note": "Connection timeout after 15s",
                "source_url": "https://example.no",
            }
        }

        report = analyze_profile_changes(prev, curr)
        web_changes = [c for c in report.changes if c.field == "website"]
        self.assertEqual(len(web_changes), 1)
        ch = web_changes[0]
        self.assertEqual(ch.change_type, ChangeType.VALUE_UNAVAILABLE)
        self.assertFalse(ch.material)
        self.assertEqual(ch.severity, MaterialitySeverity.NONE)
        self.assertIn("not reported as removed", ch.explanation)

    # Scenario 13: First observation handling
    def test_scenario_13_first_observation_handled_gracefully(self):
        report = analyze_profile_changes(None, self.base_profile)
        self.assertEqual(report.status, "INITIAL_OBSERVATION")
        self.assertEqual(report.total_changes, 0)
        self.assertEqual(report.material_changes, 0)
        self.assertIsNone(report.previous_snapshot)
        self.assertIsNotNone(report.current_snapshot)


class Stage16IntegrationTests(unittest.TestCase):
    """End-to-end integration and evidence verification tests."""

    def test_end_to_end_pipeline_with_evidence_verification(self):
        old_profile = {
            "organisation_number": "923609016",
            "name": "Norsk Havbruk AS",
            "status": "ACTIVE",
            "industry_code": "03.210",
            "website": "https://norskhavbruk.no",
            "address": {"city": "Bergen", "street": "Havneveien 1"},
            "employees": 50,
            "financials": {
                "2024": {"revenue": 20000000, "profit": 3000000}
            },
            "evidence": {
                "registry": {
                    "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
                    "retrieved_at": "2025-01-01T00:00:00Z",
                    "status": "available",
                }
            },
            "observed_at": "2025-01-01T00:00:00Z",
        }

        # Current profile with 3 distinct changes:
        # 1. Status: ACTIVE -> UNDER_LIQUIDATION (CRITICAL)
        # 2. Employees: 50 -> 15 (DECREASE: -35, -70%) (HIGH)
        # 3. Financials: 2025 period added (MEDIUM)
        new_profile = {
            "organisation_number": "923609016",
            "name": "Norsk Havbruk AS",
            "status": "UNDER_LIQUIDATION",
            "industry_code": "03.210",
            "website": "https://norskhavbruk.no/",  # whitespace/slash noise -> ignored
            "address": {"city": "Bergen", "street": "Havneveien 1,"},  # punctuation noise -> ignored
            "employees": 15,
            "financials": {
                "2024": {"revenue": 20000000, "profit": 3000000},
                "2025": {"revenue": 5000000, "profit": -4000000},
            },
            "evidence": {
                "registry": {
                    "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
                    "retrieved_at": "2026-09-24T12:00:00Z",
                    "status": "available",
                    "content_sha256": "feedbeef1234567890abcdef",
                },
                "financials": {
                    "source_url": "https://data.brreg.no/enhetsregisteret/api/enheter/923609016",
                    "retrieved_at": "2026-09-24T12:00:00Z",
                    "status": "available",
                },
            },
            "observed_at": "2026-09-24T12:00:00Z",
        }

        report = analyze_profile_changes(old_profile, new_profile)

        self.assertEqual(report.status, "CHANGES_DETECTED")
        self.assertEqual(report.company["organization_number"], "923609016")
        self.assertEqual(report.company["name"], "Norsk Havbruk AS")

        # Total material changes: exactly 3
        self.assertEqual(report.material_changes, 3)

        # Verify evidence attachment
        for ch in report.changes:
            self.assertTrue(len(ch.evidence) >= 1)
            ev = ch.evidence[0]
            self.assertIsNotNone(ev.source)
            self.assertIsNotNone(ev.url)
            self.assertIsNotNone(ev.observed_at)
            self.assertEqual(ev.supports, "current_value")

        # Verify dictionary serialization
        rep_dict = report.to_dict()
        self.assertIn("summary", rep_dict)
        self.assertEqual(rep_dict["summary"]["by_severity"]["CRITICAL"], 1)
        self.assertEqual(rep_dict["summary"]["by_severity"]["HIGH"], 1)
        self.assertEqual(rep_dict["summary"]["by_severity"]["MEDIUM"], 1)
        self.assertEqual(rep_dict["material_changes"], 3)


if __name__ == "__main__":
    unittest.main()
