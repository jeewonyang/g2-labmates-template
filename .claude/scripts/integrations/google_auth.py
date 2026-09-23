"""Shared Google OAuth for Gmail, Calendar, and Drive (personal account).

One OAuth "Desktop app" client + one token file cover all three APIs. Per
the owner's decision, these integrations use their PERSONAL Google account rather
than an organization account - so this is an External OAuth app. To avoid the 7-day
refresh-token expiry that hits External apps in "Testing" mode, publish the
consent screen to "Production" (see docs/INTEGRATIONS_SETUP.md).

Files (all under .claude/data/secrets/, gitignored, blocked by Phase 8):
- credentials.json : the OAuth client secret you download from Google Cloud
- google_token.json: the stored access/refresh token (created on first auth)

Request ALL scopes up front: adding a scope later invalidates the token and
forces re-consent.
"""

import os
import sys
from pathlib import Path

# oauthlib raises on ANY scope change - including Google merely REORDERING the
# granted scopes, or granular consent dropping one. Relax so the flow completes;
# we verify the important scopes explicitly in check_granted_scopes() instead.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import DATA  # noqa: E402

SECRETS = DATA / "secrets"
CREDENTIALS_FILE = SECRETS / "credentials.json"
TOKEN_FILE = SECRETS / "google_token.json"

# All scopes needed across Gmail + Calendar + Drive, requested together.
# Two write scopes, both deliberate and both gated behind human approval:
#   gmail.compose   creates DRAFTS only. gmail.send is not requested and must
#                   never be added - Advisor mode's core promise.
#   calendar.events inserts events. Added 2026-07-26 when the owner authorized
#                   calendar creation as the second outbound write; reached only
#                   from admin_schedule_proposal.apply(), after approval on /ops.
#
# SCOPES is what we ASK FOR at consent. It is deliberately NOT used to load an
# existing token - see get_credentials(). Adding calendar.events on 2026-07-26
# and then passing the widened list to Credentials.from_authorized_user_file()
# made Google reject the refresh with `invalid_scope`, which broke Gmail and
# Calendar READS as well, not just the new write. A token is loaded with the
# scopes it was actually granted; the widened list only takes effect at the next
# interactive consent (`python .claude/scripts/setup_auth.py google`).
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",   # read messages
    "https://www.googleapis.com/auth/gmail.compose",     # create drafts (never send)
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",   # insert only; see above
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_credentials(*, interactive: bool = False,
                    force_consent: bool = False):
    """Return valid Google credentials, refreshing or running consent as needed.

    interactive=False (default): only use/refresh an existing token; raise if
    none exists (safe for headless heartbeat runs).
    interactive=True: run the local-server consent flow if needed (setup_auth).
    force_consent=True: ignore a valid stored token and run consent again. This
    is required after adding scopes; a valid old token cannot gain them through
    refresh.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    creds = None
    if TOKEN_FILE.exists() and not force_consent:
        # Load with the scopes the token ACTUALLY has, not the scopes we would
        # like it to have. Passing the wider SCOPES list here makes the refresh
        # fail with `invalid_scope` and takes every Google read down with it.
        # A missing write scope should degrade one feature, not the integration.
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE))

    if creds and creds.valid and not force_consent:
        return creds

    if creds and creds.expired and creds.refresh_token and not force_consent:
        try:
            creds.refresh(Request())
            _save(creds)
            return creds
        except Exception:
            if not interactive:
                raise

    if not interactive:
        raise RuntimeError(
            "No valid Google token. Run: python .claude/scripts/setup_auth.py google")

    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"Missing {CREDENTIALS_FILE}. Download an OAuth 'Desktop app' client "
            "secret from Google Cloud Console and save it there. "
            "See docs/INTEGRATIONS_SETUP.md.")

    from google_auth_oauthlib.flow import InstalledAppFlow
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    _save(creds)
    return creds


def _save(creds) -> None:
    SECRETS.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")


def granted_scopes() -> list[str]:
    """Scopes the stored token actually carries. Empty if there is no token."""
    import json
    try:
        return list(json.loads(
            TOKEN_FILE.read_text(encoding="utf-8")).get("scopes") or [])
    except (OSError, ValueError):
        return []


def has_scope(scope: str) -> bool:
    return scope in granted_scopes()


def require_scope(scope: str, feature: str) -> None:
    """Fail with an actionable message instead of an opaque Google 403."""
    if has_scope(scope):
        return
    raise PermissionError(
        f"{feature} needs the {scope} scope, which this token does not have. "
        f"Re-consent once with: python .claude/scripts/setup_auth.py google")


def missing_scopes() -> list[str]:
    """Requested scopes the current token lacks. Drives setup_auth's warning."""
    granted = set(granted_scopes())
    return [s for s in SCOPES if s not in granted]


def build_service(api: str, version: str, *, interactive: bool = False):
    from googleapiclient.discovery import build
    return build(api, version, credentials=get_credentials(interactive=interactive),
                 cache_discovery=False)


def granted_scopes() -> list[str]:
    """Scopes actually present on the saved token (empty if no token)."""
    import json
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8")).get("scopes", [])
    except (OSError, ValueError):
        return []


def is_configured() -> bool:
    return TOKEN_FILE.exists() or CREDENTIALS_FILE.exists()
