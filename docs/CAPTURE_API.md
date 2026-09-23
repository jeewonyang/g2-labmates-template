# Capture API

The Capture API is the stable, client-agnostic boundary for getting *anything*
into your Second Brain. The web quick-capture box, and (later) the iOS app,
Home/Lock-Screen widget, Share Sheet extension, and Siri Shortcut all funnel
through it. Everything captured lands as a durable **InboxItem**. Automatic
captures are staged in the private filesystem inbox, classified by local
Ollama, independently verified through Agent OS, then filed and converted into
the appropriate Tasks, Notes, Resources, or internal schedule. Manual mode
keeps the original one-click Inbox triage controls.

## Design principles

- **One required field.** Only `rawText` is required. The dumbest client (a
  Siri Shortcut posting a string) works with no other knowledge.
- **Idempotent.** Supply a client-generated `clientId` and retries never create
  duplicates — essential for offline queues that flush on reconnect.
- **Sync-friendly.** `capturedAt` is the client's clock (when the user actually
  captured); `createdAt` is the server's. Ordering and dedup use `capturedAt`.
- **Auth is one narrow gate.** A single bearer token today; swappable for
  per-user keys / OAuth without touching the service layer. See "Auth" below.
- **Private first.** Raw captures are staged under
  `Research-Private/00_Inbox/G2-Captures`; only structured decision metadata is
  sent to the cloud verifier.
- **Transactional apply.** Filesystem provenance, dashboard entities, inbox
  state, and append-only automation events are applied idempotently. A retry
  cannot create a duplicate task.

## Auth

Send a bearer token in the `Authorization` header:

```
Authorization: Bearer <CAPTURE_API_TOKEN>
```

`CAPTURE_API_TOKEN` is read from the server environment (`.env`). Rotate it
before exposing the app beyond localhost. Requests without a valid token get
`401`; if the server has no token configured, `500`.

> Future auth: replace `authorizeCapture()` in `src/lib/auth.ts` with per-user
> API keys (add an `ApiKey` model → `userId`) or verify a JWT from a mobile
> sign-in. The capture service and routes stay unchanged.

## Endpoints

### `POST /api/capture`

Create a single inbox item.

**Body** (`application/json`):

| Field         | Type     | Required | Notes |
|---------------|----------|----------|-------|
| `rawText`     | string   | ✅       | The raw capture. |
| `type`        | enum     |          | `note` \| `task` \| `resource` \| `idea` \| `journal` \| `unknown` (default `unknown`). |
| `parsedTitle` | string   |          | Falls back to the first line of `rawText`. |
| `source`      | enum     |          | `web` \| `ios_app` \| `ios_widget` \| `share_extension` \| `siri_shortcut` \| `manual` \| `api` (default `api`). |
| `automationMode` | enum  |          | `automatic` (default) or `manual`. |
| `sourceUrl`   | string   |          | For shared links. |
| `dueDate`     | ISO date |          | Optional. |
| `tags`        | string[] |          | Created on demand. |
| `projectId`   | string   |          | Pre-file into a project. |
| `areaId`      | string   |          | Pre-file into an area. |
| `metadata`    | object   |          | Arbitrary JSON (device, location, audio ref…). Stored as a JSON string. |
| `clientId`    | string   |          | Idempotency key (min 8 chars). Set this on offline clients. |
| `capturedAt`  | ISO date |          | Client capture time; defaults to now. |

**Responses**
- `201` — created. `{ "item": InboxItem, "deduplicated": false }`
- `200` — idempotent hit (same `clientId` already stored). `{ "item", "deduplicated": true }`
- `400` invalid JSON · `401` bad token · `422` validation error (with `details`).

**Example**

```bash
curl -X POST http://localhost:3000/api/capture \
  -H "Authorization: Bearer $CAPTURE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "rawText": "Read the new methods paper before Friday",
    "type": "task",
    "source": "siri_shortcut",
    "dueDate": "2026-07-10",
    "clientId": "ios-8F2A1C7E-0001"
  }'
```

### `POST /api/capture/batch`

Flush an offline queue in one request.

**Body:** `{ "items": CaptureInput[] }` (1–100 items). Give each item a
`clientId` so the batch is fully idempotent.

**Response:** `{ "created": number, "deduplicated": number, "items": InboxItem[] }`

```bash
curl -X POST http://localhost:3000/api/capture/batch \
  -H "Authorization: Bearer $CAPTURE_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "items": [
    { "rawText": "Idea: control plate per run", "type": "idea", "clientId": "ios-A1" },
    { "rawText": "Buy milk", "type": "task", "clientId": "ios-A2" }
  ] }'
```

### `GET /api/capture?status=inbox`

List captured items (bearer-gated). `status` ∈ `inbox` \| `processed` \|
`archived`. Returns `{ "items": InboxItem[] }`.

## iOS integration guide (future phases 5–6)

The recommended path is a small **SwiftUI app + App Group + Share/Widget
extensions** that all write to a local queue, then POST to `/api/capture`
(single) or `/api/capture/batch` (flush):

1. **App** opens directly to a capture screen → `POST /api/capture`.
2. **Share Sheet extension** receives a URL/text → `POST /api/capture` with
   `source: "share_extension"`, `sourceUrl`.
3. **Home/Lock-Screen widget** deep-links to the capture screen (widgets can't
   do arbitrary network work reliably) → same endpoint.
4. **Siri Shortcut / App Intent** sends dictated text → `source: "siri_shortcut"`.
5. **Offline:** persist captures with a locally generated `clientId` (UUID),
   then flush via `/api/capture/batch` on connectivity. The idempotency key
   makes reflushing safe.

Because `type` and all context fields are optional, you can ship the simplest
possible v1 (just `rawText`) and enrich later — the server contract won't change.

## Data model note

`InboxItem` records where a processed item went (`processedIntoType` +
`processedIntoId`). `CaptureAutomation` stores the current pipeline state and
`AutomationEvent` is the append-only provenance stream shared by the dashboard
and agents. A mixed capture can create multiple linked entities while retaining
one primary processed target. See `prisma/schema.prisma` and `src/lib/types.ts`
for the full vocabularies.

## Automatic pipeline and safety policy

1. Persist the inbox item and automation record.
2. Atomically write an opaque capture file to the private staging inbox.
3. Enqueue `triage.classify` on local Ollama; raw capture text never goes to a
   cloud runtime.
4. Enqueue a sanitized Codex/Claude decision audit. Confirmed and corrected
   proposals auto-approve; uncertainty falls back to the local content-informed
   destination with generated actions suppressed.
5. Choose the bucket root, an existing bucket-relative folder, or propose a
   durable new folder. A new-folder proposal is reviewed first; approval creates
   only the folder and sends the source through local classification and
   metadata-only verification again against the expanded folder map.
6. Copy the source into the reclassified PARA destination and transactionally
   create the dashboard entities.
7. Publish `.claude/data/state/agent-taskflow.json`, which gives every agent the
   same projects, tasks, dates, next actions, and automation status.

Internal G2 task scheduling is automatic. A proposed Google Calendar event
still becomes `admin.schedule_proposal` and requires explicit per-item approval;
the capture pipeline never sends mail, posts messages, deletes files, or
updates/deletes calendar events.

Folder creation is bounded and fail-closed:

- paths are relative to one permitted Vault bucket and at most two levels deep;
- traversal, absolute paths, Windows-reserved names, `Finance`, and `_private`
  are rejected;
- existing folders are preferred when they express the same concept;
- a new folder must be a reusable semantic category, not a one-file container;
- new `10_Projects` folders always require your explicit approval;
- only one folder-creation pass is allowed per source before human review.
