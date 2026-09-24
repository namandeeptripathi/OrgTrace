import Link from "next/link";

export default function NotFound() {
  return (
    <div
      className="animate-in"
      style={{
        textAlign: "center",
        padding: "80px 0",
      }}
    >
      <div
        style={{
          width: "64px",
          height: "64px",
          margin: "0 auto 24px",
          borderRadius: "var(--radius-xl)",
          background: "rgba(248, 113, 113, 0.1)",
          border: "1px solid rgba(248, 113, 113, 0.2)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: "1.5rem",
        }}
      >
        ?
      </div>
      <h1
        className="text-display"
        style={{ marginBottom: "12px", fontSize: "1.5rem" }}
      >
        Company Not Found
      </h1>
      <p className="text-body" style={{ marginBottom: "24px" }}>
        The organisation number you searched for is not in our current dataset.
      </p>
      <Link href="/" className="btn-primary" style={{ textDecoration: "none" }}>
        ← Back to Search
      </Link>
    </div>
  );
}
