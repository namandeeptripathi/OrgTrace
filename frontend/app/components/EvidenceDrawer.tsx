"use client";

import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import type { EvidenceRecord, SourceVerdict } from "../lib/types";

interface EvidenceDrawerProps {
  evidence: EvidenceRecord | null;
  fieldLabel: string;
  fieldValue: string;
  onClose: () => void;
}

export interface SourceVerdictInfo {
  verdict: SourceVerdict;
  label: string;
  reason: string;
  badgeClass: string;
  icon: string;
  themeColor: string;
  bgColor: string;
  borderColor: string;
}

export function resolveSourceVerdict(evidence: EvidenceRecord | null): SourceVerdictInfo {
  if (!evidence) {
    return {
      verdict: "rejected",
      label: "Rejected",
      reason: "Source fails verification; never use it to support a published fact.",
      badgeClass: "badge-red",
      icon: "✕",
      themeColor: "var(--accent-red)",
      bgColor: "rgba(239, 68, 68, 0.08)",
      borderColor: "rgba(239, 68, 68, 0.25)",
    };
  }

  // 1. Explicit valid backend verdict takes precedence
  let verdict: SourceVerdict;
  let reason = evidence.verdict_reason || evidence.rejection_reason || evidence.note;

  if (evidence.verdict === "confirmed" || evidence.verdict === "unsure" || evidence.verdict === "rejected") {
    verdict = evidence.verdict;
  } else if (evidence.status === "not_found" || evidence.status === "not_applicable") {
    // Explicit not found or not applicable remains rejected
    verdict = "rejected";
    if (!reason) {
      reason = "Source fails verification; never use it to support a published fact.";
    }
  } else {
    // Missing, invalid, or status === "available" without explicit verdict MUST fail safely to "unsure"
    verdict = "unsure";
    if (!reason) {
      reason = "Source retrieval succeeded, but an explicit identity verification verdict is unavailable.";
    }
  }

  if (verdict === "confirmed") {
    return {
      verdict,
      label: "Confirmed",
      reason: reason || "Source supports the associated company fact and passes verification.",
      badgeClass: "badge-green",
      icon: "✓",
      themeColor: "var(--accent-green)",
      bgColor: "rgba(34, 197, 94, 0.08)",
      borderColor: "rgba(34, 197, 94, 0.25)",
    };
  } else if (verdict === "unsure") {
    return {
      verdict,
      label: "Unsure",
      reason: reason || "Source retrieval succeeded, but an explicit identity verification verdict is unavailable.",
      badgeClass: "badge-amber",
      icon: "?",
      themeColor: "var(--accent-amber)",
      bgColor: "rgba(245, 158, 11, 0.08)",
      borderColor: "rgba(245, 158, 11, 0.25)",
    };
  } else {
    return {
      verdict,
      label: "Rejected",
      reason: reason || "Source fails verification; never use it to support a published fact.",
      badgeClass: "badge-red",
      icon: "✕",
      themeColor: "var(--accent-red)",
      bgColor: "rgba(239, 68, 68, 0.08)",
      borderColor: "rgba(239, 68, 68, 0.25)",
    };
  }
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
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

function verificationState(status: string): {
  icon: string;
  label: string;
  className: string;
} {
  switch (status) {
    case "available":
      return { icon: "✓", label: "Available", className: "badge-green" };
    case "not_found":
    case "not_applicable":
      return { icon: "✕", label: "Not Found", className: "badge-neutral" };
    case "not_attempted":
      return { icon: "—", label: "Not Attempted", className: "badge-neutral" };
    case "timeout":
    case "rate_limited":
      return { icon: "⚠", label: "Rate Limited / Timeout", className: "badge-amber" };
    default:
      return { icon: "⚠", label: status, className: "badge-amber" };
  }
}

export function EvidenceDrawer({
  evidence,
  fieldLabel,
  fieldValue,
  onClose,
}: EvidenceDrawerProps) {
  const drawerRef = useRef<HTMLDivElement>(null);
  const [isVisible, setIsVisible] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    requestAnimationFrame(() => setIsVisible(true));

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  function handleBackdropClick(e: React.MouseEvent) {
    if (e.target === e.currentTarget) onClose();
  }

  const verdictInfo = resolveSourceVerdict(evidence);
  const verification = evidence
    ? verificationState(evidence.status)
    : { icon: "—", label: "Unavailable", className: "badge-neutral" };

  if (!mounted || typeof document === "undefined" || !document.body) return null;

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Evidence for ${fieldLabel}`}
      onClick={handleBackdropClick}
      style={{
        position: "fixed",
        top: "var(--header-height, 56px)",
        left: 0,
        right: 0,
        bottom: 0,
        height: "calc(100vh - var(--header-height, 56px))",
        zIndex: 100,
        display: "flex",
        justifyContent: "flex-end",
        background: isVisible ? "rgba(0, 0, 0, 0.5)" : "transparent",
        transition: "background 200ms ease",
      }}
    >
      <div
        ref={drawerRef}
        style={{
          width: "min(460px, 100vw)",
          height: "100%",
          background: "var(--bg-secondary)",
          borderLeft: "1px solid var(--border-default)",
          boxShadow: "var(--shadow-lg)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          transform: isVisible ? "translateX(0)" : "translateX(100%)",
          transition: "transform 250ms cubic-bezier(0.4, 0, 0.2, 1)",
        }}
      >
        {/* Header - Always visible at top of drawer */}
        <div
          style={{
            padding: "20px 24px",
            borderBottom: "1px solid var(--border-subtle)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexShrink: 0,
            background: "var(--bg-secondary)",
            position: "sticky",
            top: 0,
            zIndex: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <h2
              style={{
                fontSize: "1rem",
                fontWeight: 600,
                letterSpacing: "-0.01em",
                color: "var(--text-primary)",
                margin: 0,
              }}
            >
              Evidence Inspector
            </h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close evidence drawer"
            style={{
              width: "32px",
              height: "32px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              background: "var(--bg-elevated)",
              border: "1px solid var(--border-subtle)",
              borderRadius: "var(--radius-sm)",
              color: "var(--text-secondary)",
              cursor: "pointer",
              fontSize: "1rem",
              fontFamily: "inherit",
              transition: "border-color var(--transition-fast)",
            }}
          >
            ✕
          </button>
        </div>

        {/* Content - Scrolls internally when content is long */}
        <div
          style={{
            padding: "24px",
            flex: 1,
            overflowY: "auto",
            minHeight: 0,
          }}
        >
          {/* Fact being inspected */}
          <div style={{ marginBottom: "20px" }}>
            <div
              className="text-caption"
              style={{
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                marginBottom: "6px",
              }}
            >
              {fieldLabel}
            </div>
            <div
              style={{
                fontSize: "1.125rem",
                fontWeight: 600,
                color: "var(--text-primary)",
                marginBottom: "10px",
                wordBreak: "break-word",
              }}
            >
              {fieldValue || "—"}
            </div>
          </div>

          {/* Prominent Source-Level Verdict Card */}
          <div
            style={{
              padding: "16px",
              borderRadius: "var(--radius-md)",
              border: `1px solid ${verdictInfo.borderColor}`,
              background: verdictInfo.bgColor,
              marginBottom: "24px",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: "8px",
              }}
            >
              <span
                style={{
                  fontSize: "0.75rem",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.08em",
                  color: verdictInfo.themeColor,
                }}
              >
                Source-Level Verdict
              </span>
              <span className={`badge ${verdictInfo.badgeClass}`}>
                {verdictInfo.icon} {verdictInfo.label}
              </span>
            </div>
            <div
              style={{
                fontSize: "0.875rem",
                lineHeight: 1.5,
                color: "var(--text-primary)",
                fontWeight: 500,
              }}
            >
              {verdictInfo.reason}
            </div>
          </div>

          {/* Evidence details */}
          {evidence ? (
            <div style={{ display: "grid", gap: "20px" }}>
              {/* Source Details */}
              <DrawerSection title="Source Attribution">
                <DrawerRow
                  label="Source Type"
                  value={evidence.source_class || evidence.source_type}
                />
                <DrawerRow label="Status" value={evidence.status} />
                {evidence.publisher && (
                  <DrawerRow label="Publisher" value={evidence.publisher} />
                )}
                {evidence.source_title && (
                  <DrawerRow label="Title" value={evidence.source_title} />
                )}
                {evidence.source_url && (
                  <div style={{ marginTop: "12px" }}>
                    <a
                      href={evidence.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="btn-secondary"
                      style={{
                        textDecoration: "none",
                        fontSize: "0.8125rem",
                        padding: "8px 14px",
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "6px",
                      }}
                    >
                      Open Source ↗
                    </a>
                  </div>
                )}
              </DrawerSection>

              {/* Retrieval */}
              <DrawerSection title="Retrieval">
                <DrawerRow
                  label="Timestamp"
                  value={formatDateTime(evidence.retrieved_at)}
                />
              </DrawerSection>

              {/* Evidence Excerpt */}
              {evidence.evidence_excerpt && (
                <DrawerSection title="Supporting Evidence Excerpt">
                  <div
                    style={{
                      padding: "10px 14px",
                      background: "var(--bg-elevated)",
                      borderRadius: "var(--radius-sm)",
                      border: "1px solid var(--border-subtle)",
                      fontSize: "0.8125rem",
                      color: "var(--text-secondary)",
                      lineHeight: 1.5,
                    }}
                  >
                    “{evidence.evidence_excerpt}”
                  </div>
                </DrawerSection>
              )}

              {/* Note (if distinct from verdict reason) */}
              {evidence.note && evidence.note !== verdictInfo.reason && (
                <DrawerSection title="Note">
                  <div
                    style={{
                      padding: "10px 14px",
                      background: "rgba(251, 191, 36, 0.06)",
                      borderRadius: "var(--radius-sm)",
                      border: "1px solid rgba(251, 191, 36, 0.15)",
                    }}
                  >
                    <span
                      className="text-body"
                      style={{
                        color: "var(--accent-amber)",
                        fontSize: "0.8125rem",
                      }}
                    >
                      {evidence.note}
                    </span>
                  </div>
                </DrawerSection>
              )}

              {/* Raw data preview */}
              {evidence.value &&
                Object.keys(evidence.value).length > 0 && (
                  <DrawerSection title="Raw Evidence Data">
                    <div
                      style={{
                        background: "var(--bg-elevated)",
                        borderRadius: "var(--radius-sm)",
                        border: "1px solid var(--border-subtle)",
                        padding: "12px",
                        maxHeight: "240px",
                        overflowY: "auto",
                      }}
                    >
                      <pre
                        style={{
                          fontSize: "0.75rem",
                          fontFamily:
                            "'SF Mono', 'Fira Code', monospace",
                          color: "var(--text-secondary)",
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                          margin: 0,
                        }}
                      >
                        {JSON.stringify(evidence.value, null, 2).slice(
                          0,
                          2000
                        )}
                      </pre>
                    </div>
                  </DrawerSection>
                )}
            </div>
          ) : (
            <div
              style={{
                padding: "32px 0",
                textAlign: "center",
              }}
            >
              <div
                style={{
                  width: "48px",
                  height: "48px",
                  margin: "0 auto 16px",
                  borderRadius: "var(--radius-lg)",
                  background: "var(--bg-elevated)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: "1.25rem",
                  color: "var(--text-tertiary)",
                }}
              >
                —
              </div>
              <p className="text-body">
                Evidence unavailable for this field.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}

/* ─── Helper Components ─── */

function DrawerSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div
        className="text-caption"
        style={{
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          marginBottom: "8px",
        }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}

function DrawerRow({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "6px 0",
        gap: "12px",
      }}
    >
      <span
        className="text-body"
        style={{ color: "var(--text-secondary)", fontSize: "0.8125rem" }}
      >
        {label}
      </span>
      <span
        style={{
          color: "var(--text-primary)",
          fontSize: "0.8125rem",
          fontWeight: 500,
          textAlign: "right",
          wordBreak: "break-word",
        }}
      >
        {value}
      </span>
    </div>
  );
}
