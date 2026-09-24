import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "OrgTrace — Norwegian Company Intelligence",
  description:
    "Evidence-first company intelligence for Norwegian organisations. Verified registry data, financial intelligence, and change tracking.",
  keywords: [
    "Norway",
    "company intelligence",
    "Brønnøysund",
    "registry",
    "due diligence",
    "evidence",
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <div
          style={{
            position: "fixed",
            inset: 0,
            background:
              "radial-gradient(ellipse 80% 50% at 50% -20%, rgba(99, 130, 255, 0.06), transparent)",
            pointerEvents: "none",
            zIndex: 0,
          }}
        />
        <div style={{ position: "relative", zIndex: 1 }}>
          <nav
            style={{
              position: "sticky",
              top: 0,
              zIndex: 50,
              borderBottom: "1px solid var(--border-subtle)",
              background: "rgba(10, 11, 15, 0.85)",
              backdropFilter: "blur(16px)",
              WebkitBackdropFilter: "blur(16px)",
            }}
          >
            <div
              style={{
                maxWidth: "1280px",
                margin: "0 auto",
                padding: "0 24px",
                height: "56px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <Link
                href="/"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "10px",
                  textDecoration: "none",
                  color: "inherit",
                }}
              >
                <div
                  style={{
                    width: "28px",
                    height: "28px",
                    borderRadius: "8px",
                    background: "var(--gradient-primary)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: "14px",
                    fontWeight: 700,
                    color: "white",
                  }}
                >
                  O
                </div>
                <span
                  style={{
                    fontSize: "1rem",
                    fontWeight: 600,
                    letterSpacing: "-0.02em",
                  }}
                >
                  OrgTrace
                </span>
                <span
                  className="badge badge-blue"
                  style={{ fontSize: "0.625rem", padding: "1px 8px" }}
                >
                  NORWAY
                </span>
              </Link>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <Link
                  href="/"
                  className="tab-item"
                  style={{ textDecoration: "none" }}
                >
                  Search
                </Link>
                <Link
                  href="/batch"
                  className="tab-item"
                  style={{ textDecoration: "none" }}
                >
                  Batch Status
                </Link>
              </div>
            </div>
          </nav>
          <main
            style={{
              maxWidth: "1280px",
              margin: "0 auto",
              padding: "32px 24px 80px",
            }}
          >
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
