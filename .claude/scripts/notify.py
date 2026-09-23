"""Windows toast notifications (with logging fallback).

Uses the Windows Runtime toast API via a PowerShell snippet - no extra Python
packages needed. Every notification is also appended to the notify log so
nothing is lost if toasts are disabled by Focus Assist.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared import log_line  # noqa: E402

_PS_TEMPLATE = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$template = @"
<toast><visual><binding template="ToastGeneric"><text>{title}</text><text>{body}</text></binding></visual></toast>
"@
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("Second Brain").Show($toast)
"""


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def toast(title: str, body: str) -> bool:
    """Show a Windows toast. Returns True on success; always logs."""
    log_line("notify", f"{title}: {body}")
    script = _PS_TEMPLATE.replace("{title}", _xml_escape(title[:80])) \
                         .replace("{body}", _xml_escape(body[:220]))
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=30)
        ok = result.returncode == 0
        if not ok:
            log_line("notify", f"toast failed: {result.stderr.decode(errors='replace')[:200]}")
        return ok
    except Exception as e:
        log_line("notify", f"toast error: {e!r}")
        return False


if __name__ == "__main__":
    ok = toast("Second Brain", "Notification test - your heartbeat can reach you.")
    print("toast shown:", ok)
