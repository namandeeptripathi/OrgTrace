/**
 * Formatting utilities for the OrgTrace frontend.
 */

/** Format org number as 999 999 999 */
export function formatOrgNumber(org: string): string {
  const digits = org.replace(/\D/g, "");
  if (digits.length !== 9) return org;
  return `${digits.slice(0, 3)} ${digits.slice(3, 6)} ${digits.slice(6)}`;
}

/** Format bytes to human-readable */
export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

/** Format seconds to mm:ss or h:mm:ss */
export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  return `${m}m ${s}s`;
}

/** Format ISO date to readable form */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

/** Format ISO datetime to readable form */
export function formatDateTime(iso: string | null | undefined): string {
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

/** Format number with thousands separator */
export function formatNumber(n: number): string {
  return n.toLocaleString("en-GB");
}

/** Format percentage */
export function formatPercent(value: number, decimals: number = 1): string {
  return `${(value * 100).toFixed(decimals)}%`;
}

/** Format currency */
export function formatCurrency(
  amount: number,
  currency: string = "NOK"
): string {
  return new Intl.NumberFormat("nb-NO", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount);
}

/** Compute confidence color class */
export function confidenceColor(
  confidence: string
): "green" | "amber" | "red" | "neutral" {
  switch (confidence) {
    case "high":
      return "green";
    case "medium":
      return "amber";
    case "low":
      return "red";
    default:
      return "neutral";
  }
}

/** Map status to display label */
export function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    complete: "Complete",
    partial: "Partial",
    failed: "Failed",
    not_found: "Not Found",
    timeout: "Timeout",
    rate_limited: "Rate Limited",
    blocked_policy: "Blocked",
    blocked_robots: "Robots Blocked",
    source_error: "Source Error",
    budget_exhausted: "Budget Exhausted",
    not_attempted: "Not Attempted",
    unavailable: "Unavailable",
    available: "Available",
    INITIAL_OBSERVATION: "Initial Observation",
  };
  return labels[status] || status;
}

/** Map evidence status to badge variant */
export function evidenceBadgeVariant(
  status: string
): "green" | "amber" | "red" | "neutral" {
  if (status === "available") return "green";
  if (status === "not_found" || status === "not_attempted") return "neutral";
  if (status === "timeout" || status === "rate_limited") return "amber";
  return "red";
}
