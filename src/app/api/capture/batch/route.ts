import { NextResponse } from "next/server";
import { authorizeCapture } from "@/lib/auth";
import { createInboxItemsBatch } from "@/lib/services/capture";
import { captureBatchSchema } from "@/lib/validators";

/**
 * POST /api/capture/batch — sync a queue of offline-captured items at once.
 * Body: { items: CaptureInput[] }. Each item should carry a `clientId` so the
 * per-item idempotency guarantee applies across the whole batch.
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

  const parsed = captureBatchSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: "Validation failed", details: parsed.error.flatten() },
      { status: 422 }
    );
  }

  const results = await createInboxItemsBatch(parsed.data.items);
  return NextResponse.json({
    created: results.filter((r) => !r.deduplicated).length,
    deduplicated: results.filter((r) => r.deduplicated).length,
    items: results.map((r) => r.item),
  });
}
