"""Interactive OAuth/token setup for integrations. Run once per integration.

Usage:
  python .claude/scripts/setup_auth.py google   # browser consent for Gmail/Cal/Drive
  python .claude/scripts/setup_auth.py status    # show which integrations are ready
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def setup_google() -> int:
    from integrations import google_auth
    if not google_auth.CREDENTIALS_FILE.exists():
        print(f"Missing OAuth client secret: {google_auth.CREDENTIALS_FILE}")
        print("1. Google Cloud Console -> create project (personal account)")
        print("2. Enable Gmail, Calendar, and Drive APIs")
        print("3. OAuth consent screen: External, then PUBLISH to Production")
        print("   (Testing mode expires the refresh token every 7 days)")
        print("4. Create an OAuth client of type 'Desktop app', download the JSON")
        print(f"5. Save it as {google_auth.CREDENTIALS_FILE}")
        print("See docs/INTEGRATIONS_SETUP.md for detail.")
        return 1
    print("Opening browser for Google consent (Gmail + Calendar + Drive)...")
    print("IMPORTANT: on the consent screen, CHECK EVERY box - especially")
    print("'Manage drafts and send emails' / 'Create, read, update drafts'")
    print("(that's the gmail.compose scope needed to draft replies).\n")
    missing_before = google_auth.missing_scopes()
    if missing_before:
        print("The stored token is missing requested permissions, so Google")
        print("will ask for consent again instead of reusing that token.\n")
    google_auth.get_credentials(
        interactive=True, force_consent=bool(missing_before))
    print(f"Token saved to {google_auth.TOKEN_FILE}")

    granted = set(google_auth.granted_scopes())
    missing = [s for s in google_auth.SCOPES if s not in granted]
    if missing:
        print("\nWARNING - some scopes were not granted:")
        for s in missing:
            print(f"  - {s}")
        if any("gmail.compose" in s for s in missing):
            print("gmail.compose is missing -> drafting replies will NOT work.")
            print("Re-run this command and check the drafts permission box.")
        return 1
    print("All requested scopes granted (read Gmail/Calendar/Drive + create drafts).")
    return 0


def main() -> int:
    from integrations import registry
    if len(sys.argv) < 2 or sys.argv[1] == "status":
        print(registry.status())
        return 0
    target = sys.argv[1]
    if target == "google":
        return setup_google()
    print(f"Unknown target: {target}. Try: google | status")
    return 2


if __name__ == "__main__":
    sys.exit(main())
