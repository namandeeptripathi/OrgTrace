"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";

interface SearchResult {
  organisation_number: string;
  name: string;
  industry_label: string;
  municipality: string;
  status: string;
}

export function SearchHero() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const router = useRouter();
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<NodeJS.Timeout>(null);
  const listboxId = "search-listbox";

  const performSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      setIsOpen(false);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/search?q=${encodeURIComponent(q)}&limit=8`
      );
      if (!res.ok) {
        setError("Search failed. Please try again.");
        setResults([]);
        setIsOpen(false);
        return;
      }
      const data = await res.json();
      setResults(data.results || []);
      setIsOpen(true);
      setSelectedIndex(-1);
    } catch {
      setError("Unable to reach the search service.");
      setResults([]);
      setIsOpen(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => performSearch(query), 200);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, performSearch]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  function navigate(org: string) {
    setIsOpen(false);
    router.push(`/company/${org}`);
  }

  /** Try to navigate directly to an org number */
  function handleDirectSubmit() {
    const cleaned = query.trim().replace(/\s/g, "");
    // If exactly 9 digits, navigate directly
    if (/^\d{9}$/.test(cleaned)) {
      navigate(cleaned);
      return;
    }
    // If a dropdown result is selected, navigate to it
    if (selectedIndex >= 0 && results[selectedIndex]) {
      navigate(results[selectedIndex].organisation_number);
      return;
    }
    // If there's exactly one result, navigate to it
    if (results.length === 1) {
      navigate(results[0].organisation_number);
      return;
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter") {
      e.preventDefault();
      if (selectedIndex >= 0 && results[selectedIndex]) {
        navigate(results[selectedIndex].organisation_number);
      } else {
        handleDirectSubmit();
      }
      return;
    }
    if (e.key === "Escape") {
      setIsOpen(false);
      return;
    }
    if (!isOpen || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    }
  }

  return (
    <div
      ref={containerRef}
      style={{ position: "relative", maxWidth: "560px", margin: "0 auto" }}
    >
      <div style={{ position: "relative" }}>
        <svg
          aria-hidden="true"
          style={{
            position: "absolute",
            left: "16px",
            top: "50%",
            transform: "translateY(-50%)",
            width: "20px",
            height: "20px",
            color: "var(--text-tertiary)",
          }}
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          viewBox="0 0 24 24"
        >
          <circle cx={11} cy={11} r={8} />
          <line x1={21} y1={21} x2={16.65} y2={16.65} />
        </svg>
        <input
          id="company-search"
          className="search-input"
          placeholder="Search by name, org number, industry, or municipality…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => results.length > 0 && setIsOpen(true)}
          onKeyDown={handleKeyDown}
          autoComplete="off"
          role="combobox"
          aria-expanded={isOpen}
          aria-controls={listboxId}
          aria-activedescendant={
            selectedIndex >= 0 ? `search-option-${selectedIndex}` : undefined
          }
          aria-label="Search Norwegian companies by name, organisation number, industry, or municipality"
        />
        {loading && (
          <div className="search-spinner" aria-hidden="true" />
        )}
      </div>

      {/* ─── Error State ─── */}
      {error && (
        <div
          role="alert"
          style={{
            marginTop: "8px",
            padding: "10px 14px",
            background: "rgba(248, 113, 113, 0.08)",
            border: "1px solid rgba(248, 113, 113, 0.2)",
            borderRadius: "var(--radius-sm)",
          }}
        >
          <span className="text-body" style={{ color: "var(--accent-red)", fontSize: "0.8125rem" }}>
            {error}
          </span>
        </div>
      )}

      {/* ─── Dropdown Results ─── */}
      {isOpen && results.length > 0 && (
        <div
          id={listboxId}
          role="listbox"
          className="surface-elevated"
          style={{
            position: "absolute",
            top: "calc(100% + 8px)",
            left: 0,
            right: 0,
            zIndex: 100,
            overflow: "hidden",
            animation: "fadeIn 0.15s ease-out",
          }}
        >
          {results.map((r, i) => (
            <button
              key={r.organisation_number}
              id={`search-option-${i}`}
              role="option"
              aria-selected={i === selectedIndex}
              onClick={() => navigate(r.organisation_number)}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: "12px",
                width: "100%",
                padding: "12px 16px",
                background:
                  i === selectedIndex ? "var(--bg-hover)" : "transparent",
                border: "none",
                borderBottom: "1px solid var(--border-subtle)",
                color: "var(--text-primary)",
                cursor: "pointer",
                textAlign: "left",
                fontFamily: "inherit",
                fontSize: "0.875rem",
                transition: "background var(--transition-fast)",
              }}
              onMouseEnter={() => setSelectedIndex(i)}
            >
              <div style={{ minWidth: 0, flex: 1 }}>
                <div className="truncate-line" style={{ fontWeight: 500 }}>
                  {r.name}
                </div>
                <div className="text-caption" style={{ marginTop: "2px" }}>
                  {r.organisation_number} · {r.industry_label || "—"} ·{" "}
                  {r.municipality || "—"}
                </div>
              </div>
              <span
                className={`status-dot ${r.status === "complete" ? "complete" : r.status === "partial" ? "partial" : "failed"}`}
              />
            </button>
          ))}
        </div>
      )}

      {/* ─── No Results ─── */}
      {isOpen && results.length === 0 && query.trim().length > 0 && !loading && !error && (
        <div
          className="surface-elevated"
          style={{
            position: "absolute",
            top: "calc(100% + 8px)",
            left: 0,
            right: 0,
            zIndex: 100,
            padding: "16px",
            textAlign: "center",
          }}
        >
          <span className="text-body">No companies found for &ldquo;{query}&rdquo;</span>
        </div>
      )}
    </div>
  );
}
