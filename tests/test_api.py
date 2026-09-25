"""Unit tests for OrgTrace FastAPI production deployment endpoints."""

import os
import unittest
from unittest.mock import patch
from fastapi import HTTPException

from norway_company_agent.api import (
    app,
    get_batch,
    get_company,
    get_stats,
    health,
    search_companies,
    store,
)


class ApiEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Force load store from repo out directory
        store.load_if_needed()

    def test_health_endpoint(self):
        res = health()
        self.assertEqual(res, {"status": "ok", "version": "0.1.0"})

    def test_stats_endpoint(self):
        data = get_stats()
        self.assertIn("totalProfiles", data)
        self.assertIn("complete", data)
        self.assertIn("topIndustries", data)
        self.assertIn("topMunicipalities", data)
        self.assertIsInstance(data["topIndustries"], list)

    def test_companies_search_default_and_limit(self):
        data = search_companies(q="", limit=5)
        self.assertIn("results", data)
        self.assertIn("total", data)
        self.assertLessEqual(len(data["results"]), 5)

    def test_companies_search_with_query(self):
        if store.profiles:
            first_org = store.profiles[0]["organisation_number"]
            data = search_companies(q=first_org, limit=10)
            self.assertEqual(len(data["results"]), 1)
            self.assertEqual(data["results"][0]["organisation_number"], first_org)

    def test_company_lookup_valid(self):
        if store.profiles:
            org = store.profiles[0]["organisation_number"]
            data = get_company(org=org)
            self.assertIn("profile", data)
            self.assertEqual(data["profile"]["organisation_number"], org)

    def test_company_lookup_invalid_format(self):
        with self.assertRaises(HTTPException) as ctx:
            get_company(org="invalid123")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("9 digits", ctx.exception.detail)

    def test_company_lookup_not_found(self):
        with self.assertRaises(HTTPException) as ctx:
            get_company(org="999999999")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_batch_report_endpoint(self):
        data = get_batch()
        self.assertIn("run_id", data)
        self.assertIn("request_budget", data)


if __name__ == "__main__":
    unittest.main()
