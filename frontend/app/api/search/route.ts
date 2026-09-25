import { NextRequest, NextResponse } from "next/server";
import { searchProfiles } from "../../lib/data";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const q = searchParams.get("q") || "";
  const limit = parseInt(searchParams.get("limit") || "20", 10);

  const profiles = await searchProfiles(q, limit);
  const results = profiles.map((p) => ({
    organisation_number: p.organisation_number,
    name: p.name,
    industry_label: p.industry_label || "",
    municipality: p.municipality || "",
    status: p.status,
    legal_form: p.legal_form,
  }));

  return NextResponse.json({ results, total: results.length });
}
