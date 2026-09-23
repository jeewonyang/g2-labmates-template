import { NextResponse } from "next/server";
import { authorizeOps } from "@/lib/auth";
import {
  dismissExecutiveDigest,
  restoreExecutiveDigests,
} from "@/lib/services/executive-digest";

export async function POST(request: Request) {
  const auth = authorizeOps(request);
  if (!auth.ok) {
    return NextResponse.json(
      { error: auth.message },
      { status: auth.status },
    );
  }

  const body = (await request.json().catch(() => null)) as
    | { action?: string; key?: string }
    | null;

  if (body?.action === "dismiss" && typeof body.key === "string") {
    await dismissExecutiveDigest(body.key);
    return NextResponse.json({ ok: true });
  }

  if (body?.action === "restore") {
    await restoreExecutiveDigests();
    return NextResponse.json({ ok: true });
  }

  return NextResponse.json(
    { error: "Unsupported CEO Brief action." },
    { status: 400 },
  );
}
