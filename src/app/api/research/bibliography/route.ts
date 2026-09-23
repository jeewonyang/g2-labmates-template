import { bibliographyAsCsl } from "@/lib/services/research";

const TARGET_ID = /^[a-z0-9_-]{1,200}$/i;

export async function GET(request: Request) {
  const params = new URL(request.url).searchParams;
  const legacyProjectId = params.get("projectId") || "";
  const targetType = params.get("targetType") || (legacyProjectId ? "project" : "");
  const targetId = params.get("targetId") || legacyProjectId;
  if (
    !["project", "resource", "area"].includes(targetType) ||
    !TARGET_ID.test(targetId)
  ) {
    return Response.json(
      { error: "A valid project or resource target is required." },
      { status: 400 },
    );
  }
  const csl = await bibliographyAsCsl({
    type: targetType as "project" | "resource" | "area",
    id: targetId,
  });
  return new Response(JSON.stringify(csl, null, 2), {
    headers: {
      "Content-Type": "application/vnd.citationstyles.csl+json; charset=utf-8",
      "Content-Disposition": `attachment; filename="rho-bibliography-${targetType}-${targetId}.json"`,
      "Cache-Control": "no-store",
    },
  });
}
