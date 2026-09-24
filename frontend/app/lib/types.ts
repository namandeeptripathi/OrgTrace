/* ─── Core Data Types for OrgTrace Frontend ─── */

export interface Address {
  adresse?: string;
  postnummer?: string;
  poststed?: string;
  kommune?: string;
  land?: string;
}

export interface ShareCapital {
  amount: number;
  currency: string;
  shares: number;
}

export interface EvidenceRecord {
  field: string;
  status: "available" | "unavailable" | "timeout" | "rate_limited" | "not_found" | "parse_failed" | "not_attempted" | "blocked_policy" | "blocked_robots";
  source_type: string;
  source_class: string;
  source_url: string;
  retrieved_at: string;
  value?: Record<string, unknown>;
  note?: string;
}

export interface RunMetrics {
  requests: number;
  bytes: number;
  latencies_ms: number[];
}

export interface ChangeSummary {
  by_severity: Record<string, number>;
  by_category: Record<string, number>;
}

export interface ChangeIntelligence {
  company: { organization_number: string; name: string };
  status: string;
  previous_snapshot: string | null;
  current_snapshot: string;
  total_changes: number;
  material_changes: number;
  summary: ChangeSummary;
  changes: ChangeItem[];
}

export interface ChangeItem {
  field: string;
  category: string;
  severity: string;
  old_value: unknown;
  new_value: unknown;
  description: string;
}

export interface SupportingEvidence {
  evidence_id: string;
  source_name: string;
  source_url?: string;
  relevance?: string;
}

export interface ExplanationField {
  field_name: string;
  summary: string;
  reasoning: string;
  confidence: "high" | "medium" | "low";
  uncertainty: string | null;
  supporting_evidence: SupportingEvidence[];
}

export interface Explanations {
  organisation_number: string;
  company_name: string;
  overall_confidence: string;
  metrics: {
    grounded_rate: number;
    evidence_coverage: number;
    unsupported_claim_rate: number;
  };
  explanations: Record<string, ExplanationField> | ExplanationField[];
  generated_at: string;
}

export type ProfileStatus = "complete" | "partial" | "failed" | "unknown";

export interface CompanyProfile {
  organisation_number: string;
  name: string;
  legal_form: string;
  employees: number | null;
  bankrupt: boolean;
  liquidating: boolean;
  municipality: string;
  municipality_number: string;
  industry_code: string;
  industry_label: string;
  website: string;
  latest_submitted_accounts: string;
  registration_date: string;
  founding_date: string;
  business_address: Address | null;
  postal_address: Address | null;
  phone: string | null;
  email: string | null;
  vat_registered: boolean;
  purpose: string;
  activity: string;
  share_capital: ShareCapital | null;
  is_in_group: boolean;
  parent_organisation: string | null;
  secondary_industry_code: string | null;
  secondary_industry_label: string | null;
  evidence: Record<string, EvidenceRecord>;
  run_metrics: RunMetrics;
  change_intelligence: ChangeIntelligence;
  explanations: Explanations;
  status: ProfileStatus;
}

export interface ModuleState {
  state: string;
  retry_count: number;
  final_timestamp: string;
}

export interface CompanyEnvelope {
  run_id: string;
  organisation_number: string;
  state: string;
  started_at: string;
  completed_at: string;
  modules: Record<string, ModuleState>;
  profile: CompanyProfile;
  status: ProfileStatus;
}

export interface BatchSummary {
  attempted: number;
  successful: number;
  partial: number;
  failed: number;
}

export interface ExecutionGuard {
  max_requests: number;
  requests_used: number;
  remaining_requests: number;
  max_cost: number;
  cost_incurred: number;
  remaining_cost: number;
  max_runtime_seconds: number;
  elapsed_seconds: number;
  remaining_seconds: number;
  reduced_mode_entered: boolean;
  stopped_reason: string | null;
  domain_requests: Record<string, number>;
  failures_by_category: Record<string, number>;
  request_limit: number;
  tracked_requests: number;
  actual_external_requests: number;
  request_budget_remaining: number;
  request_budget_consumed_percent: number;
}

export interface RunReport {
  run_id: string;
  started_at: string;
  completed_at: string;
  expected_count: number;
  emitted_envelopes: number;
  modules: string[];
  registry: {
    registry_snapshot_sha256: string;
    registry_rows_scanned: number;
    requested: number;
    selected: number;
    missing: number;
  };
  operations: {
    requests: number;
    bytes: number;
    p50_ms: number;
    p95_ms: number;
    actual_external_requests: number;
    tracked_requests: number;
  };
  validation: {
    passed: boolean;
    checks: Record<string, boolean>;
    invalid_states: unknown[];
  };
  batch_summary: BatchSummary;
  execution_guard: ExecutionGuard;
  change_intelligence: {
    total_evaluated: number;
    with_material_changes: number;
    initial_observations: number;
  };
  explanations: {
    total_evaluated: number;
    avg_grounded_rate: number;
    avg_evidence_coverage: number;
  };
  request_budget: {
    request_limit: number;
    actual_external_requests: number;
    tracked_requests: number;
    request_budget_remaining: number;
    request_budget_consumed_percent: number;
  };
}
