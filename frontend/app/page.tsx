import { getDashboardStats, getProfiles } from "./lib/data";
import { formatNumber } from "./lib/format";
import { SearchHero } from "./components/SearchHero";
import { CompanyTable } from "./components/CompanyTable";
import { StatsGrid } from "./components/StatsGrid";

export default async function HomePage() {
  const stats = await getDashboardStats();
  const profiles = await getProfiles();

  return (
    <div className="animate-in">
      {/* ─── Hero ─── */}
      <section style={{ textAlign: "center", marginBottom: "48px" }}>
        <h1
          className="text-display"
          style={{
            marginBottom: "12px",
            background: "linear-gradient(135deg, #f0f1f5 0%, #9a9db0 100%)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
            backgroundClip: "text",
          }}
        >
          Norwegian Company Intelligence
        </h1>
        <p
          className="text-body"
          style={{ maxWidth: "520px", margin: "0 auto 32px" }}
        >
          Evidence-first intelligence for {formatNumber(stats.totalProfiles)}{" "}
          Norwegian organisations. Verified registry data, financial
          intelligence, and change tracking.
        </p>
        <SearchHero />
      </section>

      {/* ─── Key Metrics ─── */}
      <StatsGrid stats={stats} />

      {/* ─── Company Table ─── */}
      <section style={{ marginTop: "40px" }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: "16px",
          }}
        >
          <h2 className="text-heading">Profiled Companies</h2>
          <span className="text-caption">
            {formatNumber(profiles.length)} total
          </span>
        </div>
        <CompanyTable profiles={profiles.slice(0, 50)} />
      </section>
    </div>
  );
}
