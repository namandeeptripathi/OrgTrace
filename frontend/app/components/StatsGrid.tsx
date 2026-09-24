import { DashboardStats } from "../lib/data";
import { formatNumber, formatPercent, formatBytes, formatDuration } from "../lib/format";

interface StatsGridProps {
  stats: DashboardStats;
}

function StatCard({
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

export function StatsGrid({ stats }: StatsGridProps) {
  const completionRate =
    stats.totalProfiles > 0
      ? (stats.complete / stats.totalProfiles)
      : 0;

  return (
    <div className="grid-stats">
      <StatCard
        label="Total Profiles"
        value={formatNumber(stats.totalProfiles)}
        sub={`${formatNumber(stats.complete)} complete`}
      />
      <StatCard
        label="Completion Rate"
        value={formatPercent(completionRate, 1)}
        accent={completionRate > 0.8 ? "var(--accent-green)" : "var(--accent-amber)"}
        sub={`${formatNumber(stats.partial)} partial · ${formatNumber(stats.failed)} failed`}
      />
      <StatCard
        label="Evidence Coverage"
        value={formatPercent(stats.avgEvidenceCoverage, 1)}
        accent="var(--accent-blue)"
        sub={`${formatPercent(stats.avgGroundedRate, 1)} grounded`}
      />
      <StatCard
        label="External Requests"
        value={formatNumber(stats.totalRequests)}
        sub={`${formatBytes(stats.totalBytes)} transferred`}
      />
      <StatCard
        label="Websites Found"
        value={formatNumber(stats.withWebsite)}
        sub={`of ${formatNumber(stats.totalProfiles)} profiled`}
      />
      <StatCard
        label="Execution Time"
        value={formatDuration(stats.elapsedSeconds)}
        sub="Total runtime"
      />
    </div>
  );
}
