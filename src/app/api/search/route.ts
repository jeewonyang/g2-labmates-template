import { NextResponse } from "next/server";
import { globalSearch } from "@/lib/services/search";

/**
 * GET /api/search?q=... — same-origin search for the command palette.
 * Not part of the external capture API; no bearer token required because it's
 * only called by the app's own client components.
 */
export async function GET(req: Request) {
  const q = new URL(req.url).searchParams.get("q") ?? "";
  const results = await globalSearch(q);
  return NextResponse.json({ results });
}
