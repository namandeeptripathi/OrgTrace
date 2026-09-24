import { getRunReport } from "../lib/data";
import {
  formatNumber,
  formatPercent,
  formatBytes,
  formatDuration,
  formatDateTime,
  statusLabel,
} from "../lib/format";

export default function BatchPage() {
  const report = getRunReport();

  if (!report) {
    return (
      <div className="animate-in" style={{ textAlign: "center", padding: "80px 0" }}>
        <h1 className="text-display" style={{ marginBottom: "12px" }}>
          No Batch Data
        </h1>
        <p className="text-body">
          No execution report found. Run the competition batch to generate data.
        </p>
      </div>
    );
  }

  const budgetUsedPercent = report.request_budget.request_budget_consumed_percent / 100;
  const validationPassed = report.validation.passed;

  return (
    <div className="animate-in">
      {/* ─── Header ─── */}
      <div style={{ marginBottom: "32px" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "12px",
            marginBottom: "8px",
          }}
        >
          <h1 className="text-display" style={{ fontSize: "1.75rem" }}>
            Competition Batch
          </h1>
          <span
            className={`badge ${validationPassed ? "badge-green" : "badge-red"}`}
            style={{ fontSize: "0.8125rem", padding: "4px 14px" }}
          >
            {validationPassed ? "✓ Validated" : "✗ Failed Validation"}
          </span>
        </div>
        <div className="text-body">
          Run <span className="text-mono">{report.run_id}</span> ·{" "}
          {formatDateTime(report.started_at)} →{" "}
          {formatDateTime(report.completed_at)}
        </div>
      </div>

      {/* ─── Summary Cards ─── */}
      <div className="grid-stats" style={{ marginBottom: "32px" }}>
        <SummaryCard
          label="Profiles"
          value={formatNumber(report.emitted_envelopes)}
          sub={`of ${formatNumber(report.expected_count)} expected`}
        />
        <SummaryCard
          label="Successful"
          value={formatNumber(report.batch_summary.successful)}
          accent="var(--accent-green)"
          sub={`${formatNumber(report.batch_summary.partial)} partial · ${formatNumber(report.batch_summary.failed)} failed`}
        />
        <SummaryCard
          label="External Requests"
          value={formatNumber(report.operations.actual_external_requests)}
          sub={`of ${formatNumber(report.execution_guard.max_requests)} limit (${formatPercent(budgetUsedPercent, 1)})`}
        />
        <SummaryCard
          label="Execution Time"
          value={formatDuration(report.execution_guard.elapsed_seconds)}
          sub={`of ${formatDuration(report.execution_guard.max_runtime_seconds)} limit`}
        />
        <SummaryCard
          label="Data Transferred"
          value={formatBytes(report.operations.bytes)}
          sub={`P50 ${report.operations.p50_ms}ms · P95 ${report.operations.p95_ms}ms`}
        />
        <SummaryCard
          label="API Cost"
          value={`$${report.execution_guard.cost_incurred.toFixed(2)}`}
          accent="var(--accent-green)"
          sub={`of $${report.execution_guard.max_cost.toFixed(2)} limit`}
        />
      </div>

      {/* ─── Budget Gauges ─── */}
      <section style={{ marginBottom: "32px" }}>
        <h2 className="text-heading" style={{ marginBottom: "16px" }}>
          Budget Utilization
        </h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 280px), 1fr))",
            gap: "16px",
          }}
        >
          <BudgetGauge
            label="Request Budget"
            used={report.execution_guard.requests_used}
            limit={report.execution_guard.max_requests}
            color="var(--accent-blue)"
          />
          <BudgetGauge
            label="Time Budget"
            used={report.execution_guard.elapsed_seconds}
            limit={report.execution_guard.max_runtime_seconds}
            color="var(--accent-purple)"
            formatFn={formatDuration}
          />
          <BudgetGauge
            label="Cost Budget"
            used={report.execution_guard.cost_incurred}
            limit={report.execution_guard.max_cost}
            color="var(--accent-green)"
            formatFn={(v: number) => `$${v.toFixed(2)}`}
          />
        </div>
      </section>

      {/* ─── Validation Checks ─── */}
      <section style={{ marginBottom: "32px" }}>
        <h2 className="text-heading" style={{ marginBottom: "16px" }}>
          Validation Checks
        </h2>
        <div className="surface-elevated" style={{ padding: "20px 24px" }}>
          {Object.entries(report.validation.checks).map(([check, passed]) => (
            <div
              key={check}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "10px 0",
                borderBottom: "1px solid var(--border-subtle)",
              }}
            >
              <span className="text-body" style={{ color: "var(--text-primary)", textTransform: "capitalize" }}>
                {check.replace(/_/g, " ")}
              </span>
              <span
                className={`badge ${passed ? "badge-green" : "badge-red"}`}
              >
                {passed ? "✓ Pass" : "✗ Fail"}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* ─── Intelligence Quality ─── */}
      <section style={{ marginBottom: "32px" }}>
        <h2 className="text-heading" style={{ marginBottom: "16px" }}>
          Intelligence Quality
        </h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 240px), 1fr))",
            gap: "16px",
          }}
        >
          <div className="glass-card" style={{ padding: "20px 24px" }}>
            <div className="text-caption" style={{ marginBottom: "6px" }}>
              Change Intelligence
            </div>
            <div style={{ display: "grid", gap: "8px" }}>
              <QualityRow
                label="Evaluated"
                value={formatNumber(report.change_intelligence.total_evaluated)}
              />
              <QualityRow
                label="Material Changes"
                value={formatNumber(
                  report.change_intelligence.with_material_changes
                )}
              />
              <QualityRow
                label="Initial Observations"
                value={formatNumber(
                  report.change_intelligence.initial_observations
                )}
              />
            </div>
          </div>
          <div className="glass-card" style={{ padding: "20px 24px" }}>
            <div className="text-caption" style={{ marginBottom: "6px" }}>
              Explanations
            </div>
            <div style={{ display: "grid", gap: "8px" }}>
              <QualityRow
                label="Evaluated"
                value={formatNumber(report.explanations.total_evaluated)}
              />
              <QualityRow
                label="Avg Grounded Rate"
                value={formatPercent(report.explanations.avg_grounded_rate)}
                accent="var(--accent-green)"
              />
              <QualityRow
                label="Avg Evidence Coverage"
                value={formatPercent(
                  report.explanations.avg_evidence_coverage
                )}
                accent="var(--accent-blue)"
              />
            </div>
          </div>
          <div className="glass-card" style={{ padding: "20px 24px" }}>
            <div className="text-caption" style={{ marginBottom: "6px" }}>
              Registry
            </div>
            <div style={{ display: "grid", gap: "8px" }}>
              <QualityRow
                label="Rows Scanned"
                value={formatNumber(report.registry.registry_rows_scanned)}
              />
              <QualityRow
                label="Selected"
                value={formatNumber(report.registry.selected)}
              />
              <QualityRow
                label="Missing"
                value={formatNumber(report.registry.missing)}
                accent={
                  report.registry.missing > 0
                    ? "var(--accent-amber)"
                    : undefined
                }
              />
            </div>
          </div>
        </div>
      </section>

      {/* ─── Failures Breakdown ─── */}
      {Object.keys(report.execution_guard.failures_by_category || {}).length >
        0 && (
        <section style={{ marginBottom: "32px" }}>
          <h2 className="text-heading" style={{ marginBottom: "16px" }}>
            Failure Categories
          </h2>
          <div className="surface-elevated" style={{ padding: "20px 24px" }}>
            {Object.entries(report.execution_guard.failures_by_category).map(
              ([cat, count]) => (
                <div
                  key={cat}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "8px 0",
                    borderBottom: "1px solid var(--border-subtle)",
                  }}
                >
                  <span className="text-body" style={{ color: "var(--text-primary)" }}>
                    {statusLabel(cat)}
                  </span>
                  <span
                    className="text-mono"
                    style={{ color: "var(--accent-amber)" }}
                  >
                    {count}
                  </span>
                </div>
              )
            )}
          </div>
        </section>
      )}

      {/* ─── Top Domains ─── */}
      <section>
        <h2 className="text-heading" style={{ marginBottom: "16px" }}>
          Domain Request Distribution
        </h2>
        <div className="surface-elevated" style={{ padding: "20px 24px" }}>
          {Object.entries(report.execution_guard.domain_requests)
            .sort(([, a], [, b]) => b - a)
            .slice(0, 20)
            .map(([domain, count]) => (
              <div
                key={domain}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "6px 0",
                  borderBottom: "1px solid var(--border-subtle)",
                }}
              >
                <span
                  className="text-mono"
                  style={{ color: "var(--text-secondary)", fontSize: "0.8125rem" }}
                >
                  {domain}
                </span>
                <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                  <div
                    style={{
                      width: `${Math.max(4, (count / Math.max(...Object.values(report.execution_guard.domain_requests))) * 120)}px`,
                      height: "4px",
                      background: "var(--accent-blue)",
                      borderRadius: "2px",
                      opacity: 0.6,
                    }}
                  />
                  <span className="text-mono" style={{ minWidth: "40px", textAlign: "right" }}>
                    {count}
                  </span>
                </div>
              </div>
            ))}
        </div>
      </section>
    </div>
  );
}

/* ─── Helper Components ─── */

function SummaryCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="glass-card" style={{ padding: "20px 24px" }}>
      <div className="text-caption" style={{ marginBottom: "6px" }}>
        {label}
      </div>
      <div
        style={{
          fontSize: "1.75rem",
          fontWeight: 700,
          letterSpacing: "-0.03em",
          color: accent || "var(--text-primary)",
          lineHeight: 1.2,
        }}
      >
        {value}
      </div>
      {sub && (
        <div className="text-caption" style={{ marginTop: "4px" }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function BudgetGauge({
  label,
  used,
  limit,
  color,
  formatFn,
}: {
  label: string;
  used: number;
  limit: number;
  color: string;
  formatFn?: (v: number) => string;
}) {
  const pct = Math.min(used / limit, 1);
  const fmt = formatFn || formatNumber;

  return (
    <div className="glass-card" style={{ padding: "20px 24px" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: "10px",
        }}
      >
        <span className="text-subheading">{label}</span>
        <span className="text-caption">{formatPercent(pct, 1)}</span>
      </div>
      <div className="progress-bar" style={{ marginBottom: "8px" }}>
        <div
          className="progress-bar-fill"
          style={{
            width: `${pct * 100}%`,
            background: color,
          }}
        />
      </div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span className="text-caption">Used: {fmt(used)}</span>
        <span className="text-caption">Limit: {fmt(limit)}</span>
      </div>
    </div>
  );
}

function QualityRow({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: string;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
      }}
    >
      <span className="text-body" style={{ color: "var(--text-secondary)" }}>
        {label}
      </span>
      <span
        style={{
          fontWeight: 600,
          fontSize: "0.875rem",
          color: accent || "var(--text-primary)",
        }}
      >
        {value}
      </span>
    </div>
  );
}
