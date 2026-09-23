import { NextResponse } from "next/server";
import { authorizeCapture } from "@/lib/auth";
import { createInboxItem, listInboxItems } from "@/lib/services/capture";
import { captureInputSchema } from "@/lib/validators";

/**
 * POST /api/capture — create a single inbox item from any client.
 * Auth: `Authorization: Bearer <CAPTURE_API_TOKEN>`.
 * Body: see captureInputSchema (only `rawText` is required).
 *
 * Returns 200 (not 201) on an idempotent hit so retried offline syncs are
 * indistinguishable-but-safe; 201 when a new item is created.
 */
export async function POST(req: Request) {
  const auth = authorizeCapture(req);
  if (!auth.ok) return NextResponse.json({ error: auth.message }, { status: auth.status });

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const parsed = captureInputSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "Validation failed", details: parsed.error.flatten() },
      { status: 422 }
    );
  }

  const { item, deduplicated } = await createInboxItem(parsed.data);
  return NextResponse.json(
    { item, deduplicated },
    { status: deduplicated ? 200 : 201 }
  );
}

/** GET /api/capture?status=inbox — list captured items (bearer-gated). */
export async function GET(req: Request) {
  const auth = authorizeCapture(req);
  if (!auth.ok) return NextResponse.json({ error: auth.message }, { status: auth.status });

  const status = new URL(req.url).searchParams.get("status") ?? "inbox";
  const items = await listInboxItems(status);
  return NextResponse.json({ items });
}
