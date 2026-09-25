"""Stage 22: Production FastAPI Application for OrgTrace.

Stateless, competition-safe API exposing company intelligence, evidence chains,
and execution telemetry for consumption by the Next.js production frontend.
"""

from __future__ import annotations

import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logger = logging.getLogger("norway_company_agent.api")

# Determine base paths
ROOT_DIR = Path(__file__).resolve().parents[2]
OUT_DIR = Path(os.environ.get("ORGTRACE_OUT_DIR", str(ROOT_DIR / "out")))


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.load_if_needed()
    yield


app = FastAPI(
    title="OrgTrace API",
    version="0.1.0",
    docs_url=None if os.environ.get("ORGTRACE_ENV", "production").lower() == "production" else "/docs",
    redoc_url=None,
    lifespan=lifespan,
)

# ─── CORS Configuration ───
env = os.environ.get("ORGTRACE_ENV", "production").lower()
cors_origins_raw = os.environ.get("CORS_ORIGINS", "").strip()

allowed_origins: list[str] = []
if cors_origins_raw:
    for item in cors_origins_raw.split(","):
        cleaned = item.strip().rstrip("/")
        if cleaned:
            allowed_origins.append(cleaned)

if env != "production":
    # In non-production, include localhost defaults if not explicitly configured
    default_dev_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]
    for dev_origin in default_dev_origins:
        if dev_origin not in allowed_origins:
            allowed_origins.append(dev_origin)
else:
    # In production, strictly reject wildcard '*'
    allowed_origins = [o for o in allowed_origins if o != "*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if allowed_origins else ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)


# ─── Global Error Shield (Prevent stack trace / filesystem leakage) ───
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled API exception on %s: %s", request.url.path, exc, exc_info=False)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ─── Data Storage Cache ───
class DataStore:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.profiles: list[dict[str, Any]] = []
        self.profiles_by_org: dict[str, dict[str, Any]] = {}
        self.envelopes_by_org: dict[str, dict[str, Any]] = {}
        self.report: dict[str, Any] | None = None
        self.stats: dict[str, Any] | None = None
        self._loaded = False

    def load_if_needed(self) -> None:
        if self._loaded:
            return
        self.reload()

    def reload(self) -> None:
        self.profiles.clear()
        self.profiles_by_org.clear()
        self.envelopes_by_org.clear()
        self.report = None
        self.stats = None

        # 1. Load profiles
        profiles_path = self.out_dir / "profiles.jsonl"
        if profiles_path.is_file():
            with open(profiles_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        org = record.get("organisation_number")
                        if org:
                            self.profiles.append(record)
                            self.profiles_by_org[str(org)] = record
                    except Exception as e:
                        logger.warning("Skipping corrupted profile line: %s", e)

        # 2. Load envelopes
        envelopes_path = self.out_dir / "envelopes.jsonl"
        if envelopes_path.is_file():
            with open(envelopes_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        org = record.get("organisation_number")
                        if org:
                            self.envelopes_by_org[str(org)] = record
                    except Exception as e:
                        logger.warning("Skipping corrupted envelope line: %s", e)

        # 3. Load report
        report_path = self.out_dir / "run-report.json"
        if report_path.is_file():
            try:
                with open(report_path, "r", encoding="utf-8") as f:
                    self.report = json.load(f)
            except Exception as e:
                logger.warning("Failed to load run report: %s", e)

        # 4. Precompute aggregate dashboard stats
        self.stats = self._compute_stats()
        self._loaded = True
        logger.info(
            "OrgTrace DataStore initialized: %d profiles, %d envelopes, report loaded=%s",
            len(self.profiles),
            len(self.envelopes_by_org),
            self.report is not None,
        )

    def _compute_stats(self) -> dict[str, Any]:
        industry_counts: dict[str, int] = {}
        municipality_counts: dict[str, int] = {}
        complete = 0
        partial = 0
        failed = 0
        with_website = 0

        for p in self.profiles:
            st = p.get("status")
            if st == "complete":
                complete += 1
            elif st == "partial":
                partial += 1
            elif st == "failed":
                failed += 1

            if p.get("website"):
                with_website += 1

            ind = p.get("industry_label") or "Unknown"
            industry_counts[ind] = industry_counts.get(ind, 0) + 1

            mun = p.get("municipality") or "Unknown"
            municipality_counts[mun] = municipality_counts.get(mun, 0) + 1

        top_industries = [
            {"label": k, "count": v}
            for k, v in sorted(industry_counts.items(), key=lambda item: item[1], reverse=True)[:10]
        ]
        top_municipalities = [
            {"label": k, "count": v}
            for k, v in sorted(municipality_counts.items(), key=lambda item: item[1], reverse=True)[:10]
        ]

        explanations = self.report.get("explanations", {}) if self.report else {}
        operations = self.report.get("operations", {}) if self.report else {}
        guard = self.report.get("execution_guard", {}) if self.report else {}

        return {
            "totalProfiles": len(self.profiles),
            "complete": complete,
            "partial": partial,
            "failed": failed,
            "withWebsite": with_website,
            "avgEvidenceCoverage": explanations.get("avg_evidence_coverage", 0.0),
            "avgGroundedRate": explanations.get("avg_grounded_rate", 0.0),
            "totalRequests": operations.get("actual_external_requests", 0),
            "totalBytes": operations.get("bytes", 0),
            "elapsedSeconds": guard.get("elapsed_seconds", 0.0),
            "topIndustries": top_industries,
            "topMunicipalities": top_municipalities,
            "statusBreakdown": [
                {"status": "complete", "count": complete},
                {"status": "partial", "count": partial},
                {"status": "failed", "count": failed},
            ],
        }


store = DataStore(OUT_DIR)


# ─── API Endpoints ───

@app.get("/health")
def health() -> dict[str, str]:
    """Health check endpoint for Railway deployment and monitoring."""
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/stats")
def get_stats() -> dict[str, Any]:
    """Return precomputed aggregate benchmark metrics matching DashboardStats."""
    store.load_if_needed()
    if store.stats is None:
        return store._compute_stats()
    return store.stats


@app.get("/api/companies")
def search_companies(
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """Search and filter company profiles with autocomplete ranking."""
    store.load_if_needed()
    query = q.strip().lower()

    if not query:
        matches = store.profiles[:limit]
        return {"results": matches, "total": len(store.profiles)}

    # Check exact org number match
    clean_org = re.sub(r"\s+", "", query)
    if clean_org in store.profiles_by_org:
        exact = store.profiles_by_org[clean_org]
        return {"results": [exact], "total": 1}

    # Search in name, org number, industry, municipality
    results: list[dict[str, Any]] = []
    for p in store.profiles:
        name = (p.get("name") or "").lower()
        org = (p.get("organisation_number") or "").lower()
        ind = (p.get("industry_label") or "").lower()
        mun = (p.get("municipality") or "").lower()

        if query in name or query in org or query in ind or query in mun:
            results.append(p)
            if len(results) >= limit:
                break

    return {"results": results, "total": len(results)}


@app.get("/api/company/{org}")
def get_company(org: str) -> dict[str, Any]:
    """Retrieve full company profile and canonical evidence envelope."""
    clean_org = org.strip().replace(" ", "")
    if not re.match(r"^\d{9}$", clean_org):
        raise HTTPException(
            status_code=400,
            detail="Invalid organisation number format. Must be exactly 9 digits.",
        )

    store.load_if_needed()
    profile = store.profiles_by_org.get(clean_org)
    envelope = store.envelopes_by_org.get(clean_org)

    if not profile:
        raise HTTPException(status_code=404, detail=f"Company '{clean_org}' not found.")

    return {
        "profile": profile,
        "envelope": envelope,
    }


@app.get("/api/batch")
def get_batch() -> dict[str, Any]:
    """Retrieve execution guard, resource budget, and batch validation report."""
    store.load_if_needed()
    if not store.report:
        raise HTTPException(
            status_code=404,
            detail="No competition batch report available in output directory.",
        )
    return store.report
