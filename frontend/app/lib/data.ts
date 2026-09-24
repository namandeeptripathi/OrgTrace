import { CompanyEnvelope, CompanyProfile, RunReport } from "./types";
import * as fs from "fs";
import * as path from "path";

/**
 * Data loading utilities for the OrgTrace frontend.
 *
 * Reads pre-generated JSONL / JSON artifacts from the `out/` directory
 * at the repository root. This is a server-side module only.
 */

const OUT_DIR = path.resolve(process.cwd(), "..", "out");

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

// ─── Cached Data ───

let _envelopes: CompanyEnvelope[] | null = null;
let _profiles: CompanyProfile[] | null = null;
let _report: RunReport | null | undefined = undefined;

export function getEnvelopes(): CompanyEnvelope[] {
  if (!_envelopes) {
    _envelopes = readJsonlFile<CompanyEnvelope>("envelopes.jsonl");
  }
  return _envelopes;
}

export function getProfiles(): CompanyProfile[] {
  if (!_profiles) {
    _profiles = readJsonlFile<CompanyProfile>("profiles.jsonl");
  }
  return _profiles;
}

export function getRunReport(): RunReport | null {
  if (_report === undefined) {
    _report = readJsonFile<RunReport>("run-report.json");
  }
  return _report;
}

// ─── Search / Lookup ───

export function searchProfiles(
  query: string,
  limit: number = 50
): CompanyProfile[] {
  const q = query.trim().toLowerCase();
  if (!q) return getProfiles().slice(0, limit);

  const profiles = getProfiles();

  // Exact org number match goes first
  const exact = profiles.find(
    (p) => p.organisation_number === q.replace(/\s/g, "")
  );
  if (exact) return [exact];

  // Name match
  const matches = profiles
    .filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.organisation_number.includes(q) ||
        p.industry_label?.toLowerCase().includes(q) ||
        p.municipality?.toLowerCase().includes(q)
    )
    .slice(0, limit);

  return matches;
}

export function getProfileByOrgNumber(
  orgNumber: string
): CompanyProfile | null {
  return (
    getProfiles().find((p) => p.organisation_number === orgNumber) ?? null
  );
}

export function getEnvelopeByOrgNumber(
  orgNumber: string
): CompanyEnvelope | null {
  return (
    getEnvelopes().find((e) => e.organisation_number === orgNumber) ?? null
  );
}

// ─── Aggregate Stats ───

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

export function getDashboardStats(): DashboardStats {
  const profiles = getProfiles();
  const report = getRunReport();

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

  const legalFormCounts: Record<string, number> = {};
  for (const p of profiles) {
    const lf = p.legal_form || "Unknown";
    legalFormCounts[lf] = (legalFormCounts[lf] || 0) + 1;
  }

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
