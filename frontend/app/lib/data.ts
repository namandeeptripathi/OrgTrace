import { CompanyEnvelope, CompanyProfile, RunReport } from "./types";
import * as fs from "fs";
import * as path from "path";
import * as child_process from "child_process";

/**
 * Data loading utilities for the OrgTrace frontend.
 *
 * Supports two runtime modes:
 * 1. Production API mode: When NEXT_PUBLIC_API_URL is configured, fetches from FastAPI backend.
 * 2. Local fallback mode: When NEXT_PUBLIC_API_URL is absent, reads pre-generated JSONL / JSON
 *    artifacts from the `../out/` directory.
 */

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_URL || "").trim().replace(/\/$/, "");
const OUT_DIR = path.resolve(process.cwd(), "..", "out");

// ─── HTTP API Client (Production / Remote) ───

async function fetchApi<T>(endpoint: string): Promise<T | null> {
  try {
    const res = await fetch(`${API_BASE_URL}${endpoint}`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) {
      if (res.status !== 404) {
        console.warn(`[OrgTrace API] Status ${res.status} on ${endpoint}`);
      }
      return null;
    }
    return (await res.json()) as T;
  } catch (err) {
    console.warn(`[OrgTrace API] Network error on ${endpoint}:`, err);
    return null;
  }
}

// ─── Local Filesystem Reader (Local Development Fallback) ───

function readJsonlFile<T>(filename: string): T[] {
  const filePath = path.join(OUT_DIR, filename);
  if (!fs.existsSync(filePath)) return [];
  const content = fs.readFileSync(filePath, "utf-8");
  return content
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => JSON.parse(line) as T);
}

function readJsonFile<T>(filename: string): T | null {
  const filePath = path.join(OUT_DIR, filename);
  if (!fs.existsSync(filePath)) return null;
  const content = fs.readFileSync(filePath, "utf-8");
  return JSON.parse(content) as T;
}

let _localEnvelopes: CompanyEnvelope[] | null = null;
let _localProfiles: CompanyProfile[] | null = null;
let _localReport: RunReport | null | undefined = undefined;

function getEnvelopesLocal(): CompanyEnvelope[] {
  if (!_localEnvelopes) {
    _localEnvelopes = readJsonlFile<CompanyEnvelope>("envelopes.jsonl");
  }
  return _localEnvelopes;
}

function getProfilesLocal(): CompanyProfile[] {
  if (!_localProfiles || _localProfiles.length === 0) {
    // 1. Primary: read from out/profiles.jsonl
    _localProfiles = readJsonlFile<CompanyProfile>("profiles.jsonl");

    // 2. Secondary fallback: extract directly from benchmark-data.tar.gz
    if (!_localProfiles || _localProfiles.length === 0) {
      try {
        const tarPath = path.resolve(process.cwd(), "..", "data", "benchmark-data.tar.gz");
        if (fs.existsSync(tarPath)) {
          const stdout = child_process.execSync(`tar -xOzf "${tarPath}" profiles.jsonl`, {
            maxBuffer: 30 * 1024 * 1024,
            encoding: "utf-8",
          });
          _localProfiles = stdout
            .split("\n")
            .filter((line) => line.trim())
            .map((line) => JSON.parse(line) as CompanyProfile);
        }
      } catch {
        // ignore
      }
    }

    // 3. Tertiary fallback: bundled fallback JSON
    if (!_localProfiles || _localProfiles.length === 0) {
      try {
        const fallbackPath = path.resolve(process.cwd(), "app", "data", "profiles-fallback.json");
        if (fs.existsSync(fallbackPath)) {
          const content = fs.readFileSync(fallbackPath, "utf-8");
          _localProfiles = JSON.parse(content) as CompanyProfile[];
        }
      } catch {
        // ignore
      }
    }
  }
  return _localProfiles || [];
}

function getRunReportLocal(): RunReport | null {
  if (_localReport === undefined) {
    _localReport = readJsonFile<RunReport>("run-report.json");
  }
  return _localReport;
}

function searchProfilesLocal(query: string, limit: number = 50): CompanyProfile[] {
  const q = query.trim().toLowerCase();
  if (!q) return getProfilesLocal().slice(0, limit);

  const profiles = getProfilesLocal();
  const exact = profiles.find(
    (p) => p.organisation_number === q.replace(/\s/g, "")
  );
  if (exact) return [exact];

  return profiles
    .filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.organisation_number.includes(q) ||
        p.industry_label?.toLowerCase().includes(q) ||
        p.municipality?.toLowerCase().includes(q)
    )
    .slice(0, limit);
}

function getProfileByOrgNumberLocal(orgNumber: string): CompanyProfile | null {
  return (
    getProfilesLocal().find((p) => p.organisation_number === orgNumber) ?? null
  );
}

function getEnvelopeByOrgNumberLocal(orgNumber: string): CompanyEnvelope | null {
  return (
    getEnvelopesLocal().find((e) => e.organisation_number === orgNumber) ?? null
  );
}

export interface DashboardStats {
  totalProfiles: number;
  complete: number;
  partial: number;
  failed: number;
  withWebsite: number;
  avgEvidenceCoverage: number;
  avgGroundedRate: number;
  totalRequests: number;
  totalBytes: number;
  elapsedSeconds: number;
  topIndustries: { label: string; count: number }[];
  topMunicipalities: { label: string; count: number }[];
  statusBreakdown: { status: string; count: number }[];
}

function getDashboardStatsLocal(): DashboardStats {
  const profiles = getProfilesLocal();
  const report = getRunReportLocal();

  const industryCounts: Record<string, number> = {};
  const municipalityCounts: Record<string, number> = {};
  let complete = 0;
  let partial = 0;
  let failed = 0;
  let withWebsite = 0;

  for (const p of profiles) {
    if (p.status === "complete") complete++;
    else if (p.status === "partial") partial++;
    else if (p.status === "failed") failed++;

    if (p.website) withWebsite++;

    const ind = p.industry_label || "Unknown";
    industryCounts[ind] = (industryCounts[ind] || 0) + 1;

    const mun = p.municipality || "Unknown";
    municipalityCounts[mun] = (municipalityCounts[mun] || 0) + 1;
  }

  const topIndustries = Object.entries(industryCounts)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 10)
    .map(([label, count]) => ({ label, count }));

  const topMunicipalities = Object.entries(municipalityCounts)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 10)
    .map(([label, count]) => ({ label, count }));

  return {
    totalProfiles: profiles.length,
    complete,
    partial,
    failed,
    withWebsite,
    avgEvidenceCoverage: report?.explanations?.avg_evidence_coverage ?? 0,
    avgGroundedRate: report?.explanations?.avg_grounded_rate ?? 0,
    totalRequests: report?.operations?.actual_external_requests ?? 0,
    totalBytes: report?.operations?.bytes ?? 0,
    elapsedSeconds: report?.execution_guard?.elapsed_seconds ?? 0,
    topIndustries,
    topMunicipalities,
    statusBreakdown: [
      { status: "complete", count: complete },
      { status: "partial", count: partial },
      { status: "failed", count: failed },
    ],
  };
}

// ─── Public Async API Data Functions (Universal API / Fallback) ───

export async function getDashboardStats(): Promise<DashboardStats> {
  if (API_BASE_URL) {
    const stats = await fetchApi<DashboardStats>("/api/stats");
    if (stats) return stats;
  }
  return getDashboardStatsLocal();
}

export async function getProfiles(): Promise<CompanyProfile[]> {
  const local = getProfilesLocal();
  if (local && local.length >= 1000) {
    return local;
  }
  if (API_BASE_URL) {
    const data = await fetchApi<{ results: CompanyProfile[]; total: number }>(
      "/api/companies?limit=100"
    );
    if (data && Array.isArray(data.results)) {
      if (local && local.length > data.results.length) return local;
      return data.results;
    }
  }
  return local;
}

export async function getEnvelopes(): Promise<CompanyEnvelope[]> {
  return getEnvelopesLocal();
}

export async function searchProfiles(
  query: string,
  limit: number = 50
): Promise<CompanyProfile[]> {
  const local = searchProfilesLocal(query, limit);
  if (local.length > 0) return local;

  if (API_BASE_URL) {
    const data = await fetchApi<{ results: CompanyProfile[]; total: number }>(
      `/api/companies?q=${encodeURIComponent(query)}&limit=${limit}`
    );
    if (data && Array.isArray(data.results)) return data.results;
  }
  return local;
}

export async function getProfileByOrgNumber(
  orgNumber: string
): Promise<CompanyProfile | null> {
  if (API_BASE_URL) {
    const data = await fetchApi<{ profile: CompanyProfile; envelope: CompanyEnvelope | null }>(
      `/api/company/${encodeURIComponent(orgNumber)}`
    );
    if (data && data.profile) return data.profile;
    return null;
  }
  return getProfileByOrgNumberLocal(orgNumber);
}

export async function getEnvelopeByOrgNumber(
  orgNumber: string
): Promise<CompanyEnvelope | null> {
  if (API_BASE_URL) {
    const data = await fetchApi<{ profile: CompanyProfile | null; envelope: CompanyEnvelope }>(
      `/api/company/${encodeURIComponent(orgNumber)}`
    );
    if (data && data.envelope) return data.envelope;
    return null;
  }
  return getEnvelopeByOrgNumberLocal(orgNumber);
}

export async function getRunReport(): Promise<RunReport | null> {
  if (API_BASE_URL) {
    const report = await fetchApi<RunReport>("/api/batch");
    if (report) return report;
  }
  return getRunReportLocal();
}
