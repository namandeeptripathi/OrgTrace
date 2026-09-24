"use client";

import { useState } from "react";
import { EvidenceDrawer } from "./EvidenceDrawer";

interface EvidenceRecord {
  field: string;
  status: string;
  source_type: string;
  source_class: string;
  source_url: string;
  retrieved_at: string;
  value?: Record<string, unknown>;
  note?: string;
}

interface ExplanationField {
  field_name: string;
  summary: string;
  reasoning: string;
  confidence: "high" | "medium" | "low";
  uncertainty: string | null;
  supporting_evidence: { evidence_id: string; source_name: string; source_url?: string }[];
}

interface CompanyClientProps {
  evidence: Record<string, EvidenceRecord>;
  explanations: ExplanationField[];
  overallConfidence: string;
  metrics: {
    grounded_rate: number;
    evidence_coverage: number;
    unsupported_claim_rate: number;
  } | null;
}

function formatPercent(value: number, decimals: number = 1): string {
  return `${(value * 100).toFixed(decimals)}%`;
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function confidenceColor(
  confidence: string
): "green" | "amber" | "red" | "neutral" {
  switch (confidence) {
    case "high": return "green";
    case "medium": return "amber";
    case "low": return "red";
    default: return "neutral";
  }
}

function evidenceBadgeVariant(
  status: string
): "green" | "amber" | "red" | "neutral" {
  if (status === "available") return "green";
  if (status === "not_found" || status === "not_attempted") return "neutral";
  if (status === "timeout" || status === "rate_limited") return "amber";
  return "red";
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    available: "Available",
    not_found: "Not Found",
    not_attempted: "Not Attempted",
    timeout: "Timeout",
    rate_limited: "Rate Limited",
    unavailable: "Unavailable",
  };
  return labels[status] || status;
}

export function CompanyInteractive({
  evidence,
  explanations,
  metrics,
}: CompanyClientProps) {
  const [drawerState, setDrawerState] = useState<{
    open: boolean;
    ev: EvidenceRecord | null;
    label: string;
    value: string;
  }>({ open: false, ev: null, label: "", value: "" });

  function openDrawer(key: string, ev: EvidenceRecord) {
    const label = key.replace(/_/g, " ");
    const value =
      ev.status === "available"
        ? "Available"
        : statusLabel(ev.status);
    setDrawerState({ open: true, ev, label, value });
  }

  return (
    <>
      {/* ─── Evidence Section ─── */}
      <section style={{ marginBottom: "32px" }}>
        <h2 className="text-heading" style={{ marginBottom: "16px" }}>
          Evidence Chain
        </h2>
        {metrics && (
          <div
            style={{
              display: "flex",
              gap: "24px",
              marginBottom: "16px",
              flexWrap: "wrap",
            }}
          >
            <MiniStat
              label="Evidence Coverage"
              value={formatPercent(metrics.evidence_coverage)}
              color="var(--accent-blue)"
            />
            <MiniStat
              label="Grounded Rate"
              value={formatPercent(metrics.grounded_rate)}
              color="var(--accent-green)"
            />
            <MiniStat
              label="Unsupported Claims"
              value={formatPercent(metrics.unsupported_claim_rate)}
              color={
                metrics.unsupported_claim_rate > 0
                  ? "var(--accent-red)"
                  : "var(--accent-green)"
              }
            />
          </div>
        )}
        <div className="surface-elevated" style={{ padding: "24px" }}>
          <div className="evidence-chain">
            {Object.entries(evidence || {}).map(([key, ev]) => (
              <button
                key={key}
                className="evidence-node evidence-clickable"
                onClick={() => openDrawer(key, ev)}
                aria-label={`Inspect evidence for ${key.replace(/_/g, " ")}`}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  fontFamily: "inherit",
                  color: "inherit",
                  padding: "12px 0",
                  borderRadius: "var(--radius-sm)",
                  transition: "background var(--transition-fast)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "12px",
                    marginBottom: "6px",
                  }}
                >
                  <span
                    className="text-subheading"
                    style={{ textTransform: "capitalize" }}
                  >
                    {key.replace(/_/g, " ")}
                  </span>
                  <span
                    className={`badge badge-${evidenceBadgeVariant(ev.status)}`}
                  >
                    {statusLabel(ev.status)}
                  </span>
                </div>
                <div className="text-caption">
                  Source:{" "}
                  <span style={{ color: "var(--text-accent)" }}>
                    {ev.source_type}
                  </span>
                </div>
                <div className="text-caption">
                  Retrieved: {formatDateTime(ev.retrieved_at)}
                </div>
                {ev.note && (
                  <div
                    className="text-caption"
                    style={{ color: "var(--accent-amber)", marginTop: "4px" }}
                  >
                    ⚠ {ev.note}
                  </div>
                )}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* ─── Explanations Section ─── */}
      {explanations.length > 0 && (
        <section style={{ marginBottom: "32px" }}>
          <h2 className="text-heading" style={{ marginBottom: "16px" }}>
            Intelligence Explanations
          </h2>
          <div style={{ display: "grid", gap: "12px" }}>
            {explanations.map((exp) => {
              const matchingEvidence = findMatchingEvidence(
                exp.field_name,
                evidence
              );
              return (
                <button
                  key={exp.field_name}
                  className="glass-card glass-card-hover"
                  onClick={() => {
                    if (matchingEvidence) {
                      openDrawer(exp.field_name, matchingEvidence);
                    } else {
                      setDrawerState({
                        open: true,
                        ev: null,
                        label: exp.field_name.replace(/_/g, " "),
                        value: exp.summary,
                      });
                    }
                  }}
                  aria-label={`Inspect evidence for ${exp.field_name.replace(/_/g, " ")}`}
                  style={{
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                    padding: "20px 24px",
                    border: "1px solid var(--glass-border)",
                    cursor: "pointer",
                    fontFamily: "inherit",
                    color: "inherit",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: "12px",
                      marginBottom: "8px",
                    }}
                  >
                    <span
                      className="text-subheading"
                      style={{ textTransform: "capitalize" }}
                    >
                      {exp.field_name.replace(/_/g, " ")}
                    </span>
                    <span
                      className={`badge badge-${confidenceColor(exp.confidence)}`}
                    >
                      {exp.confidence}
                    </span>
                  </div>
                  <p className="text-body" style={{ marginBottom: "8px" }}>
                    {exp.summary}
                  </p>
                  <p
                    className="text-body"
                    style={{ fontSize: "0.8125rem", opacity: 0.8 }}
                  >
                    {exp.reasoning}
                  </p>
                  {exp.uncertainty && (
                    <div
                      style={{
                        marginTop: "8px",
                        padding: "8px 12px",
                        background: "rgba(251, 191, 36, 0.06)",
                        borderRadius: "var(--radius-sm)",
                        border: "1px solid rgba(251, 191, 36, 0.15)",
                      }}
                    >
                      <span
                        className="text-caption"
                        style={{ color: "var(--accent-amber)" }}
                      >
                        Uncertainty: {exp.uncertainty}
                      </span>
                    </div>
                  )}
                  {exp.supporting_evidence &&
                    exp.supporting_evidence.length > 0 && (
                      <div
                        style={{
                          marginTop: "10px",
                          display: "flex",
                          gap: "6px",
                          flexWrap: "wrap",
                        }}
                      >
                        {exp.supporting_evidence.map((se, i) => (
                          <span
                            key={i}
                            className="badge badge-neutral"
                            style={{ fontSize: "0.6875rem" }}
                          >
                            {se.source_name}
                          </span>
                        ))}
                      </div>
                    )}
                </button>
              );
            })}
          </div>
        </section>
      )}

      {/* ─── Evidence Drawer ─── */}
      {drawerState.open && (
        <EvidenceDrawer
          evidence={drawerState.ev}
          fieldLabel={drawerState.label}
          fieldValue={drawerState.value}
          onClose={() =>
            setDrawerState({ open: false, ev: null, label: "", value: "" })
          }
        />
      )}
    </>
  );
}

function MiniStat({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color: string;
}) {
  return (
    <div>
      <div className="text-caption">{label}</div>
      <div
        style={{
          fontSize: "1.125rem",
          fontWeight: 700,
          color,
          letterSpacing: "-0.02em",
        }}
      >
        {value}
      </div>
    </div>
  );
}

/** Map an explanation field name to the closest evidence key */
function findMatchingEvidence(
  fieldName: string,
  evidence: Record<string, { field: string; status: string; source_type: string; source_class: string; source_url: string; retrieved_at: string; value?: Record<string, unknown>; note?: string }>
): (typeof evidence)[string] | null {
  // Direct match
  if (evidence[fieldName]) return evidence[fieldName];

  // Common mappings
  const mappings: Record<string, string> = {
    identity: "registry",
    status: "registry",
    industry: "registry",
    address: "registry",
    workforce: "registry",
    website: "website",
    financial_information: "financials",
    financials: "financials",
    company_changes: "registry",
    accounting: "accounting_obligation",
  };
  const mapped = mappings[fieldName];
  if (mapped && evidence[mapped]) return evidence[mapped];

  return null;
}
