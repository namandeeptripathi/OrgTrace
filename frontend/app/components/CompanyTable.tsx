"use client";

import { useState, useMemo, useRef } from "react";
import Link from "next/link";
import { CompanyProfile } from "../lib/types";
import { formatOrgNumber, formatNumber, statusLabel } from "../lib/format";

interface CompanyTableProps {
  profiles: Array<
    Pick<
      CompanyProfile,
      "organisation_number" | "name" | "legal_form" | "status"
    > & {
      industry_label?: string | null;
      municipality?: string | null;
      website?: string | null;
    }
  >;
}

const PAGE_SIZE = 100;

export function CompanyTable({ profiles }: CompanyTableProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "complete" | "partial" | "failed">("all");
  const [currentPage, setCurrentPage] = useState(1);
  const tableContainerRef = useRef<HTMLDivElement>(null);

  // Status counts across all profiles
  const counts = useMemo(() => {
    let complete = 0;
    let partial = 0;
    let failed = 0;
    for (const p of profiles) {
      if (p.status === "complete") complete++;
      else if (p.status === "partial") partial++;
      else if (p.status === "failed") failed++;
    }
    return { all: profiles.length, complete, partial, failed };
  }, [profiles]);

  // Filter across the full 1,000 profiles
  const filteredProfiles = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    const cleanQ = q.replace(/\s+/g, "");

    return profiles.filter((p) => {
      // 1. Status filter
      if (statusFilter !== "all" && p.status !== statusFilter) {
        return false;
      }

      // 2. Search query filter across name, org number, industry, municipality, and legal form
      if (!q) return true;

      const name = (p.name || "").toLowerCase();
      const org = (p.organisation_number || "").replace(/\s+/g, "");
      const ind = (p.industry_label || "").toLowerCase();
      const mun = (p.municipality || "").toLowerCase();
      const form = (p.legal_form || "").toLowerCase();

      return (
        name.includes(q) ||
        org.includes(cleanQ) ||
        ind.includes(q) ||
        mun.includes(q) ||
        form.includes(q)
      );
    });
  }, [profiles, searchQuery, statusFilter]);

  // Pagination computations
  const totalItems = filteredProfiles.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));
  const safePage = Math.min(Math.max(1, currentPage), totalPages);

  const startIndex = totalItems === 0 ? 0 : (safePage - 1) * PAGE_SIZE + 1;
  const endIndex = Math.min(safePage * PAGE_SIZE, totalItems);

  const paginatedProfiles = useMemo(() => {
    const from = (safePage - 1) * PAGE_SIZE;
    return filteredProfiles.slice(from, from + PAGE_SIZE);
  }, [filteredProfiles, safePage]);

  // Handlers
  const handleSearchChange = (val: string) => {
    setSearchQuery(val);
    setCurrentPage(1);
  };

  const handleStatusChange = (status: "all" | "complete" | "partial" | "failed") => {
    setStatusFilter(status);
    setCurrentPage(1);
  };

  const handlePageChange = (newPage: number) => {
    const target = Math.min(Math.max(1, newPage), totalPages);
    setCurrentPage(target);
    if (tableContainerRef.current) {
      const rect = tableContainerRef.current.getBoundingClientRect();
      const targetY = window.scrollY + rect.top - 80;
      if (window.scrollY > targetY) {
        window.scrollTo({ top: targetY, behavior: "smooth" });
      }
    }
  };

  // Generate page numbers for navigation buttons
  const pageNumbers = useMemo(() => {
    if (totalPages <= 10) {
      return Array.from({ length: totalPages }, (_, i) => i + 1);
    }
    const pages: (number | "...")[] = [];
    pages.push(1);
    const start = Math.max(2, safePage - 2);
    const end = Math.min(totalPages - 1, safePage + 2);

    if (start > 2) pages.push("...");
    for (let i = start; i <= end; i++) {
      pages.push(i);
    }
    if (end < totalPages - 1) pages.push("...");
    pages.push(totalPages);
    return pages;
  }, [totalPages, safePage]);

  return (
    <div ref={tableContainerRef} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
      {/* ─── Controls Header ─── */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "16px",
        }}
      >
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <h2 className="text-heading" style={{ margin: 0 }}>
              Profiled Companies
            </h2>
            <span
              className="badge badge-neutral"
              style={{ fontSize: "0.75rem", padding: "2px 8px" }}
            >
              {totalItems === profiles.length
                ? `${formatNumber(startIndex)}–${formatNumber(endIndex)} of ${formatNumber(profiles.length)}`
                : `${formatNumber(startIndex)}–${formatNumber(endIndex)} of ${formatNumber(totalItems)} (${formatNumber(profiles.length)} total)`}
            </span>
          </div>
          <p className="text-caption" style={{ marginTop: "4px" }}>
            Showing {PAGE_SIZE} companies per page · Page {safePage} of {totalPages}
          </p>
        </div>

        {/* Filter controls */}
        <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "12px" }}>
          {/* Status filter pills */}
          <div className="tab-nav" style={{ padding: "2px" }}>
            <button
              type="button"
              className={`tab-item ${statusFilter === "all" ? "active" : ""}`}
              onClick={() => handleStatusChange("all")}
              style={{ fontSize: "0.75rem", padding: "4px 10px" }}
            >
              All ({formatNumber(counts.all)})
            </button>
            <button
              type="button"
              className={`tab-item ${statusFilter === "complete" ? "active" : ""}`}
              onClick={() => handleStatusChange("complete")}
              style={{ fontSize: "0.75rem", padding: "4px 10px" }}
            >
              Complete ({formatNumber(counts.complete)})
            </button>
            <button
              type="button"
              className={`tab-item ${statusFilter === "partial" ? "active" : ""}`}
              onClick={() => handleStatusChange("partial")}
              style={{ fontSize: "0.75rem", padding: "4px 10px" }}
            >
              Partial ({formatNumber(counts.partial)})
            </button>
          </div>

          {/* Table search input */}
          <div style={{ position: "relative", minWidth: "260px" }}>
            <svg
              aria-hidden="true"
              style={{
                position: "absolute",
                left: "12px",
                top: "50%",
                transform: "translateY(-50%)",
                width: "16px",
                height: "16px",
                color: "var(--text-tertiary)",
                pointerEvents: "none",
              }}
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              viewBox="0 0 24 24"
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => handleSearchChange(e.target.value)}
              placeholder="Filter 1,000 companies..."
              style={{
                width: "100%",
                padding: "8px 32px 8px 36px",
                background: "var(--bg-elevated)",
                border: "1px solid var(--border-default)",
                borderRadius: "var(--radius-md)",
                color: "var(--text-primary)",
                fontSize: "0.8125rem",
                outline: "none",
                transition: "border-color var(--transition-fast)",
              }}
              onFocus={(e) => (e.target.style.borderColor = "var(--accent-blue)")}
              onBlur={(e) => (e.target.style.borderColor = "var(--border-default)")}
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => handleSearchChange("")}
                style={{
                  position: "absolute",
                  right: "8px",
                  top: "50%",
                  transform: "translateY(-50%)",
                  background: "transparent",
                  border: "none",
                  color: "var(--text-tertiary)",
                  cursor: "pointer",
                  fontSize: "14px",
                  padding: "2px 6px",
                  borderRadius: "50%",
                }}
                title="Clear filter"
              >
                ✕
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ─── Table Container ─── */}
      <div className="surface-elevated" style={{ overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: "48px", textAlign: "center" }}>#</th>
                <th>Company</th>
                <th>Org Number</th>
                <th>Industry</th>
                <th>Municipality</th>
                <th>Form</th>
                <th style={{ textAlign: "center" }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {paginatedProfiles.length === 0 ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: "center", padding: "48px 24px" }}>
                    <div style={{ color: "var(--text-secondary)", marginBottom: "8px" }}>
                      No companies match your filter criteria.
                    </div>
                    {(searchQuery || statusFilter !== "all") && (
                      <button
                        type="button"
                        className="btn-secondary"
                        style={{ fontSize: "0.75rem", padding: "6px 14px", marginTop: "8px" }}
                        onClick={() => {
                          setSearchQuery("");
                          setStatusFilter("all");
                          setCurrentPage(1);
                        }}
                      >
                        Reset filters
                      </button>
                    )}
                  </td>
                </tr>
              ) : (
                paginatedProfiles.map((p, i) => {
                  const globalIndex = (safePage - 1) * PAGE_SIZE + i + 1;
                  return (
                    <tr
                      key={p.organisation_number}
                      className="animate-in"
                      style={{ animationDelay: `${Math.min(i * 10, 200)}ms` }}
                    >
                      <td
                        style={{
                          textAlign: "center",
                          color: "var(--text-tertiary)",
                          fontSize: "0.75rem",
                          fontFamily: "var(--font-mono, monospace)",
                        }}
                      >
                        {globalIndex}
                      </td>
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
                        <span
                          className="text-body truncate-line"
                          style={{ maxWidth: "220px", display: "inline-block" }}
                        >
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
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* ─── Pagination Footer ─── */}
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "14px 20px",
            borderTop: "1px solid var(--border-subtle)",
            background: "rgba(22, 24, 31, 0.4)",
            gap: "14px",
          }}
        >
          {/* Current Range / Page info */}
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span className="text-body" style={{ fontSize: "0.8125rem", color: "var(--text-secondary)" }}>
              Showing{" "}
              <strong style={{ color: "var(--text-primary)" }}>
                {formatNumber(startIndex)}–{formatNumber(endIndex)}
              </strong>{" "}
              of{" "}
              <strong style={{ color: "var(--text-primary)" }}>
                {formatNumber(totalItems)}
              </strong>{" "}
              companies
            </span>
            <span style={{ color: "var(--border-default)" }}>·</span>
            <span className="text-caption" style={{ color: "var(--text-tertiary)" }}>
              Page {safePage} of {totalPages}
            </span>
          </div>

          {/* Navigation Buttons */}
          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            {/* Previous Button */}
            <button
              type="button"
              onClick={() => handlePageChange(safePage - 1)}
              disabled={safePage <= 1}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                padding: "6px 12px",
                background: safePage <= 1 ? "transparent" : "var(--bg-surface)",
                color: safePage <= 1 ? "var(--text-tertiary)" : "var(--text-primary)",
                border: "1px solid",
                borderColor: safePage <= 1 ? "var(--border-subtle)" : "var(--border-default)",
                borderRadius: "var(--radius-sm)",
                fontSize: "0.8125rem",
                fontWeight: 500,
                cursor: safePage <= 1 ? "not-allowed" : "pointer",
                opacity: safePage <= 1 ? 0.4 : 1,
                transition: "all var(--transition-fast)",
              }}
            >
              ← Previous
            </button>

            {/* Page number buttons */}
            <div style={{ display: "flex", alignItems: "center", gap: "4px" }}>
              {pageNumbers.map((pageNum, idx) => {
                if (pageNum === "...") {
                  return (
                    <span
                      key={`ellipsis-${idx}`}
                      style={{
                        padding: "0 6px",
                        color: "var(--text-tertiary)",
                        fontSize: "0.8125rem",
                      }}
                    >
                      …
                    </span>
                  );
                }

                const isActive = pageNum === safePage;
                return (
                  <button
                    key={`page-${pageNum}`}
                    type="button"
                    onClick={() => handlePageChange(pageNum as number)}
                    style={{
                      minWidth: "32px",
                      height: "32px",
                      padding: "0 6px",
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      borderRadius: "var(--radius-sm)",
                      fontSize: "0.8125rem",
                      fontWeight: isActive ? 600 : 400,
                      background: isActive ? "var(--gradient-primary)" : "transparent",
                      color: isActive ? "#ffffff" : "var(--text-secondary)",
                      border: isActive ? "none" : "1px solid var(--border-subtle)",
                      boxShadow: isActive ? "0 2px 8px rgba(99, 130, 255, 0.35)" : "none",
                      cursor: "pointer",
                      transition: "all var(--transition-fast)",
                    }}
                  >
                    {pageNum}
                  </button>
                );
              })}
            </div>

            {/* Next Button */}
            <button
              type="button"
              onClick={() => handlePageChange(safePage + 1)}
              disabled={safePage >= totalPages}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                padding: "6px 12px",
                background: safePage >= totalPages ? "transparent" : "var(--bg-surface)",
                color: safePage >= totalPages ? "var(--text-tertiary)" : "var(--text-primary)",
                border: "1px solid",
                borderColor: safePage >= totalPages ? "var(--border-subtle)" : "var(--border-default)",
                borderRadius: "var(--radius-sm)",
                fontSize: "0.8125rem",
                fontWeight: 500,
                cursor: safePage >= totalPages ? "not-allowed" : "pointer",
                opacity: safePage >= totalPages ? 0.4 : 1,
                transition: "all var(--transition-fast)",
              }}
            >
              Next →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
