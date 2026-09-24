"use client";

import Link from "next/link";
import { CompanyProfile } from "../lib/types";
import { formatOrgNumber, statusLabel } from "../lib/format";

interface CompanyTableProps {
  profiles: CompanyProfile[];
}

export function CompanyTable({ profiles }: CompanyTableProps) {
  return (
    <div
      className="surface-elevated"
      style={{ overflow: "hidden" }}
    >
      <div style={{ overflowX: "auto" }}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Company</th>
              <th>Org Number</th>
              <th>Industry</th>
              <th>Municipality</th>
              <th>Form</th>
              <th style={{ textAlign: "center" }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {profiles.map((p, i) => (
              <tr
                key={p.organisation_number}
                className="animate-in"
                style={{ animationDelay: `${Math.min(i * 20, 400)}ms` }}
              >
                <td>
                  <Link
                    href={`/company/${p.organisation_number}`}
                    className="company-link"
                  >
                    {p.name}
                  </Link>
                </td>
                <td>
                  <span className="text-mono" style={{ color: "var(--text-secondary)" }}>
                    {formatOrgNumber(p.organisation_number)}
                  </span>
                </td>
                <td>
                  <span className="text-body truncate-line" style={{ maxWidth: "200px", display: "inline-block" }}>
                    {p.industry_label || "—"}
                  </span>
                </td>
                <td style={{ color: "var(--text-secondary)" }}>
                  {p.municipality || "—"}
                </td>
                <td>
                  <span className="badge badge-neutral">{p.legal_form}</span>
                </td>
                <td style={{ textAlign: "center" }}>
                  <span
                    className={`badge ${
                      p.status === "complete"
                        ? "badge-green"
                        : p.status === "partial"
                          ? "badge-amber"
                          : "badge-red"
                    }`}
                  >
                    <span
                      className={`status-dot ${p.status}`}
                      style={{ width: "6px", height: "6px" }}
                    />
                    {statusLabel(p.status)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
