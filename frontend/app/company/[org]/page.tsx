import { notFound } from "next/navigation";
import { getProfileByOrgNumber, getEnvelopeByOrgNumber } from "../../lib/data";
import {
  formatOrgNumber,
  formatDate,
  formatDateTime,
  formatNumber,
  formatCurrency,
  statusLabel,
  confidenceColor,
} from "../../lib/format";
import { ExplanationField } from "../../lib/types";
import { CompanyInteractive } from "../../components/CompanyInteractive";

interface PageProps {
  params: Promise<{ org: string }>;
}

export default async function CompanyPage({ params }: PageProps) {
  const { org } = await params;
  const profile = getProfileByOrgNumber(org);
  const envelope = getEnvelopeByOrgNumber(org);

  if (!profile) return notFound();

  const addr = profile.business_address;
  const explanationsList: ExplanationField[] = profile.explanations
    ? Array.isArray(profile.explanations.explanations)
      ? (profile.explanations.explanations as ExplanationField[])
      : Object.values(
          profile.explanations.explanations as Record<string, ExplanationField>
        )
    : [];

  const overallConfidence =
    profile.explanations?.overall_confidence || "unknown";
  const metrics = profile.explanations?.metrics || null;
  const hasPreviousSnapshot = !!profile.change_intelligence?.previous_snapshot;

  return (
    <div className="animate-in">
      {/* ─── Header ─── */}
      <div style={{ marginBottom: "32px" }}>
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: "16px",
            flexWrap: "wrap",
          }}
        >
          <div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "12px",
                marginBottom: "8px",
                flexWrap: "wrap",
              }}
            >
              <h1 className="text-display" style={{ fontSize: "1.75rem" }}>
                {profile.name}
              </h1>
              <span
                className={`badge ${
                  profile.status === "complete"
                    ? "badge-green"
                    : profile.status === "partial"
                      ? "badge-amber"
                      : "badge-red"
                }`}
              >
                <span
                  className={`status-dot ${profile.status}`}
                  style={{ width: "6px", height: "6px" }}
                />
                {statusLabel(profile.status)}
              </span>
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "16px",
                flexWrap: "wrap",
              }}
            >
              <span className="text-mono" style={{ color: "var(--text-secondary)" }}>
                {formatOrgNumber(profile.organisation_number)}
              </span>
              <span className="badge badge-neutral">{profile.legal_form}</span>
              {profile.bankrupt && (
                <span className="badge badge-red">Bankrupt</span>
              )}
              {profile.liquidating && (
                <span className="badge badge-amber">Liquidating</span>
              )}
              {profile.vat_registered && (
                <span className="badge badge-blue">VAT Registered</span>
              )}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <span
              className={`badge badge-${confidenceColor(overallConfidence)}`}
              style={{ fontSize: "0.8125rem", padding: "4px 14px" }}
            >
              {overallConfidence.charAt(0).toUpperCase() +
                overallConfidence.slice(1)}{" "}
              Confidence
            </span>
          </div>
        </div>
      </div>

      {/* ─── Key Info Cards ─── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 280px), 1fr))",
          gap: "16px",
          marginBottom: "32px",
        }}
      >
        {/* Company Details */}
        <div className="glass-card" style={{ padding: "24px" }}>
          <h3
            className="text-subheading"
            style={{ marginBottom: "16px", color: "var(--text-accent)" }}
          >
            Company Details
          </h3>
          <div style={{ display: "grid", gap: "12px" }}>
            <InfoRow label="Industry" value={profile.industry_label || "Unavailable"} />
            <InfoRow
              label="Industry Code"
              value={profile.industry_code || "Unavailable"}
            />
            {profile.secondary_industry_code && (
              <InfoRow
                label="Secondary"
                value={`${profile.secondary_industry_code} — ${profile.secondary_industry_label}`}
              />
            )}
            <InfoRow
              label="Municipality"
              value={
                profile.municipality
                  ? `${profile.municipality} (${profile.municipality_number || "—"})`
                  : "Unavailable"
              }
            />
            <InfoRow
              label="Founded"
              value={formatDate(profile.founding_date)}
            />
            <InfoRow
              label="Registered"
              value={formatDate(profile.registration_date)}
            />
            <InfoRow
              label="Latest Accounts"
              value={profile.latest_submitted_accounts || "Unavailable"}
            />
            {profile.is_in_group && (
              <InfoRow label="Group" value="Part of a corporate group" />
            )}
          </div>
        </div>

        {/* Contact & Address */}
        <div className="glass-card" style={{ padding: "24px" }}>
          <h3
            className="text-subheading"
            style={{ marginBottom: "16px", color: "var(--text-accent)" }}
          >
            Contact & Address
          </h3>
          <div style={{ display: "grid", gap: "12px" }}>
            {addr ? (
              <>
                <InfoRow label="Street" value={addr.adresse || "Unavailable"} />
                <InfoRow
                  label="Postal"
                  value={
                    addr.postnummer && addr.poststed
                      ? `${addr.postnummer} ${addr.poststed}`
                      : "Unavailable"
                  }
                />
                <InfoRow label="Country" value={addr.land || "Unavailable"} />
              </>
            ) : (
              <InfoRow label="Address" value="Unavailable" />
            )}
            <InfoRow label="Phone" value={profile.phone || "Unavailable"} />
            <InfoRow label="Email" value={profile.email || "Unavailable"} />
            {profile.website ? (
              <InfoRow
                label="Website"
                value={
                  <a
                    href={profile.website}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      color: "var(--text-accent)",
                      textDecoration: "none",
                    }}
                  >
                    {profile.website}
                  </a>
                }
              />
            ) : (
              <InfoRow label="Website" value="Unavailable" />
            )}
          </div>
        </div>

        {/* Capital & Financial */}
        <div className="glass-card" style={{ padding: "24px" }}>
          <h3
            className="text-subheading"
            style={{ marginBottom: "16px", color: "var(--text-accent)" }}
          >
            Capital & Financial
          </h3>
          <div style={{ display: "grid", gap: "12px" }}>
            {profile.share_capital ? (
              <>
                <InfoRow
                  label="Share Capital"
                  value={formatCurrency(
                    profile.share_capital.amount,
                    profile.share_capital.currency
                  )}
                />
                <InfoRow
                  label="Shares"
                  value={formatNumber(profile.share_capital.shares)}
                />
              </>
            ) : (
              <InfoRow label="Share Capital" value="Unavailable" />
            )}
            <InfoRow
              label="Employees"
              value={
                profile.employees !== null
                  ? formatNumber(profile.employees)
                  : "Unavailable"
              }
            />
          </div>

          {profile.purpose && (
            <div style={{ marginTop: "20px" }}>
              <div
                className="text-caption"
                style={{
                  marginBottom: "6px",
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                }}
              >
                Purpose
              </div>
              <p
                className="text-body"
                style={{
                  fontSize: "0.8125rem",
                  lineHeight: "1.5",
                  maxHeight: "120px",
                  overflow: "hidden",
                }}
              >
                {profile.purpose}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ─── Interactive Evidence & Explanations (Client Component) ─── */}
      <CompanyInteractive
        evidence={profile.evidence || {}}
        explanations={explanationsList}
        overallConfidence={overallConfidence}
        metrics={metrics}
      />

      {/* ─── Change Intelligence ─── */}
      <section style={{ marginBottom: "32px" }}>
        <h2 className="text-heading" style={{ marginBottom: "16px" }}>
          Change Intelligence
        </h2>
        <div className="glass-card" style={{ padding: "24px" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "12px",
              marginBottom: "16px",
            }}
          >
            <span className="badge badge-blue">
              {statusLabel(profile.change_intelligence?.status || "unknown")}
            </span>
            <span className="text-caption">
              Snapshot:{" "}
              {formatDateTime(profile.change_intelligence?.current_snapshot)}
            </span>
          </div>

          {!hasPreviousSnapshot && (
            <p className="text-body">
              No previous snapshot available. This is the initial observation for this company.
            </p>
          )}

          {hasPreviousSnapshot && profile.change_intelligence?.total_changes === 0 && (
            <p className="text-body">
              No changes detected since the previous snapshot.
            </p>
          )}

          {hasPreviousSnapshot && (profile.change_intelligence?.total_changes ?? 0) > 0 && (
            <div>
              <div
                style={{
                  display: "flex",
                  gap: "24px",
                  marginBottom: "12px",
                }}
              >
                <MiniStat
                  label="Total Changes"
                  value={String(profile.change_intelligence!.total_changes)}
                  color="var(--accent-amber)"
                />
                <MiniStat
                  label="Material"
                  value={String(profile.change_intelligence!.material_changes)}
                  color="var(--accent-red)"
                />
              </div>
              {profile.change_intelligence!.changes.map((c, i) => (
                <div
                  key={i}
                  className="surface"
                  style={{ padding: "12px 16px", marginBottom: "8px" }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                      marginBottom: "4px",
                    }}
                  >
                    <span className="text-subheading" style={{ textTransform: "capitalize" }}>
                      {c.field?.replace(/_/g, " ")}
                    </span>
                    <span
                      className={`badge ${
                        c.severity === "CRITICAL" || c.severity === "HIGH"
                          ? "badge-red"
                          : c.severity === "MEDIUM"
                            ? "badge-amber"
                            : "badge-neutral"
                      }`}
                    >
                      {c.severity}
                    </span>
                  </div>
                  <p className="text-body">{c.description}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* ─── Module States (from envelope) ─── */}
      {envelope && (
        <section>
          <h2 className="text-heading" style={{ marginBottom: "16px" }}>
            Pipeline Modules
          </h2>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 200px), 1fr))",
              gap: "12px",
            }}
          >
            {Object.entries(envelope.modules).map(([name, mod]) => (
              <div key={name} className="surface" style={{ padding: "16px" }}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    marginBottom: "8px",
                  }}
                >
                  <span
                    className="text-subheading"
                    style={{ textTransform: "capitalize" }}
                  >
                    {name.replace(/_/g, " ")}
                  </span>
                  <span
                    className={`status-dot ${
                      mod.state === "complete"
                        ? "complete"
                        : mod.state === "not_found"
                          ? "unknown"
                          : "failed"
                    }`}
                  />
                </div>
                <div className="text-caption">
                  State: {statusLabel(mod.state)}
                </div>
                {mod.retry_count > 0 && (
                  <div className="text-caption" style={{ color: "var(--accent-amber)" }}>
                    Retries: {mod.retry_count}
                  </div>
                )}
                <div className="text-caption">
                  {formatDateTime(mod.final_timestamp)}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

/* ─── Helper Components ─── */

function InfoRow({
  label,
  value,
}: {
  label: string;
  value: string | React.ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        gap: "12px",
      }}
    >
      <span className="text-caption" style={{ flexShrink: 0, minWidth: "100px" }}>
        {label}
      </span>
      <span
        className="text-body"
        style={{
          textAlign: "right",
          color: "var(--text-primary)",
          fontSize: "0.8125rem",
          wordBreak: "break-word",
        }}
      >
        {value}
      </span>
    </div>
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
