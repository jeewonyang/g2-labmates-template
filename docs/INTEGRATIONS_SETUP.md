# Integrations Setup

Each integration keeps its secrets in `.claude/data/secrets/` (gitignored,
and blocked from agent reads by the Phase 8 credential hook). The agent code
only ever sees returned data — never the tokens.

Check status any time: `python .claude/scripts/query.py status`

---

## 1. Google: Gmail + Calendar + Drive (priority 1)

**Decide which Google account to connect before you start.** A personal account
is usually the simpler choice: organization (Workspace) tenants often restrict
which OAuth apps can be authorized and may require admin approval, while a
personal account lets you create and consent to your own OAuth client with no
gatekeeper. The trade-off is that the agent then sees only that account's mail
and calendar — see section 2b for options if your work mail lives elsewhere.
One OAuth client and one token cover all three APIs.

### Steps
1. Go to [Google Cloud Console](https://console.cloud.google.com/) signed in as
   your **personal** Google account. Create a new project (e.g. "second-brain").
2. **Enable APIs** (APIs & Services → Library): Gmail API, Google Calendar API,
   Google Drive API.
3. **OAuth consent screen** (APIs & Services → OAuth consent screen):
   - User type: **External** (personal accounts can't use Internal).
   - Fill in app name + your email.
   - **Publish the app to "Production."** If you leave it in "Testing," Google
     expires the refresh token every 7 days and you'll have to re-auth weekly.
     (Publishing a personal-use app that stays under Google's unverified-app
     limits does not require going through full verification.)
4. **Create credentials** (APIs & Services → Credentials → Create → OAuth client
   ID): application type **Desktop app**. Download the JSON.
5. Save it as `.claude/data/secrets/credentials.json`.
6. Run: `python .claude/scripts/setup_auth.py google` — a browser opens, you
   consent to Gmail+Calendar+Drive, and the token is saved to
   `.claude/data/secrets/google_token.json`.

### Scopes requested (all up front — changing later forces re-consent)
`gmail.readonly`, `gmail.compose`, `calendar.readonly`, `drive.readonly`.
`gmail.compose` lets the agent create **drafts**; it never sends (Advisor mode).

### Test
```
python .claude/scripts/query.py gmail unread
python .claude/scripts/query.py calendar upcoming 48
python .claude/scripts/query.py drive list
```

---

## 2. Slack — read-only monitoring (re-added 2026-07-08)

Re-added for **reply-drafting only** — no chat bot (that stays removed). The
integration reads messages needing a reply so `/draft-replies` can draft them.

### Steps
1. If your Slack app still exists at [api.slack.com/apps](https://api.slack.com/apps),
   open it; otherwise create one (From scratch → your workspace).
2. **OAuth & Permissions → User Token Scopes** (a bot can't see your DMs):
   `channels:history`, `channels:read`, `groups:history`, `groups:read`,
   `im:history`, `im:read`, `mpim:history`, `mpim:read`, `users:read`.
3. **Install to Workspace** → copy the **User OAuth Token** (`xoxp-...`).
4. Create `.claude/data/secrets/slack.env`:
   ```
   SLACK_USER_TOKEN=xoxp-...
   ```
   (No bot/app tokens needed — read-only, no chat bot.)

### Test
```
python .claude/scripts/query.py slack whoami
python .claude/scripts/query.py slack needs-response
```

## 2b. Work email via Microsoft 365 (optional)

If your work mail lives in an organization's Microsoft 365 tenant, expect
reading it to be blocked by default: org tenants usually deny third-party
Microsoft Graph access without admin consent, so a Graph app without the
`Mail.Read` permission gets HTTP 403 on every mail query even when other
permissions (files, sites, profile) work fine.

Options, all requiring some tenant-side cooperation:
- **Admin consent:** have your IT department grant `Mail.Read` to a Graph app
  registration (an existing connector app, or a new registration you create).
  Cleanest path, but it needs an admin.
- **IMAP + app password:** if the tenant allows IMAP with an app-specific
  password, a small Python IMAP reader can pull mail without any Graph consent.
- **Forwarding:** forward work mail to the connected personal mailbox —
  simplest, no admin needed, but it mixes work mail into the personal account.

Until one is set up, `/draft-replies` simply skips the work mailbox.

## 3. GitHub (priority 3)

A **classic** PAT — fine-grained PATs still can't call the Notifications API.

### Steps
1. GitHub → Settings → Developer settings → Personal access tokens →
   **Tokens (classic)** → Generate new token (classic).
2. Scopes: check **notifications** and **repo**. Expiration: your call
   (set a calendar reminder if it expires).
3. Create `.claude/data/secrets/github.env`:
   ```
   GITHUB_TOKEN=ghp_...
   ```

### Test
```
python .claude/scripts/query.py github notifications
python .claude/scripts/query.py github assigned
python .claude/scripts/query.py github reviews
```

## 4. Papers — no auth

arXiv needs none (be polite: ≤1 req/3s). Semantic Scholar works keyless but
rate-limits hard; request a free key later. Watchlist keywords live in USER.md.
