"use client";

import { useState, useEffect, useRef } from "react";
import { createPortal } from "react-dom";

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

interface EvidenceDrawerProps {
  evidence: EvidenceRecord | null;
  fieldLabel: string;
  fieldValue: string;
  onClose: () => void;
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
      return { icon: "✓", label: "Verified", className: "badge-green" };
    case "not_found":
    case "not_attempted":
      return { icon: "—", label: "Unavailable", className: "badge-neutral" };
    case "timeout":
    case "rate_limited":
      return { icon: "⚠", label: "Partial", className: "badge-amber" };
    default:
      return { icon: "⚠", label: "Partial", className: "badge-amber" };
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
    // Animate in
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
          width: "min(440px, 100vw)",
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
          <div style={{ marginBottom: "24px" }}>
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
              }}
            >
              {fieldValue || "—"}
            </div>
            <span className={`badge ${verification.className}`}>
              {verification.icon} {verification.label}
            </span>
          </div>

          {/* Evidence details */}
          {evidence ? (
            <div style={{ display: "grid", gap: "20px" }}>
              {/* Source */}
              <DrawerSection title="Source">
                <DrawerRow
                  label="Source Type"
                  value={evidence.source_class || evidence.source_type}
                />
                <DrawerRow label="Status" value={evidence.status} />
                {evidence.source_url && (
                  <div style={{ marginTop: "8px" }}>
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
                        gap: "6px",
                      }}
                    >
                      Open Source ↗
                    </a>
                  </div>
                )}
              </DrawerSection>

              {/* Retrieval */}
              <DrawerSection title="Retrieved">
                <DrawerRow
                  label="Timestamp"
                  value={formatDateTime(evidence.retrieved_at)}
                />
              </DrawerSection>

              {/* Note */}
              {evidence.note && (
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
        }}
      >
        {value}
      </span>
    </div>
  );
}
