"""IT/Security producer - collects evidence, then enqueues four audits.

Every command run here is read-only and runs in THIS process, under the command
guard, rather than inside an agent. `npm audit` and `pip list --outdated` report;
they do not install. The audit jobs themselves get no Bash at all - codex runs
them under `-s read-only`.

Weekly by default. These audits are slow, and a codebase that changed by three
commits does not produce different findings than it did yesterday.
"""

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared import REPO_ROOT, log_line  # noqa: E402

TEAM = "security"

CMD_TIMEOUT = 180


def _run(cmd: list[str], *, timeout: int = CMD_TIMEOUT) -> str:
    """Run a read-only command, returning stdout. Never raises."""
    try:
        res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True,
                             text=True, timeout=timeout, encoding="utf-8",
                             errors="replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        log_line("producer", f"security: {cmd[0]} failed: {e!r}")
        return ""
    # npm audit exits non-zero when it finds vulnerabilities - that is the
    # normal, useful case, so stdout is taken regardless of return code.
    return res.stdout or ""


def changed_files() -> list[str]:
    """Tracked files touched recently, plus anything currently staged/dirty."""
    out = set()
    recent = _run(["git", "log", "--since=14.days", "--name-only",
                   "--pretty=format:", "-n", "200"])
    out.update(ln.strip() for ln in recent.splitlines() if ln.strip())
    dirty = _run(["git", "status", "--porcelain"])
    for ln in dirty.splitlines():
        if len(ln) > 3:
            out.add(ln[3:].strip().strip('"'))
    return sorted(p for p in out if p)


# Local dev ports worth checking: the dashboard (3000) and common sibling-app ports.
HOST_PORTS = (3000, 3100, 3200, 5173, 5525)


def _listening_sockets() -> str:
    """Listening sockets on the pinned ports, with their bind address.

    LISTEN rows only: established connections would put remote peers' addresses
    into a vault report for no benefit.
    """
    if sys.platform == "win32":
        raw = _run(["netstat", "-ano", "-p", "TCP"]) + _run(
            ["netstat", "-ano", "-p", "TCPv6"])
    else:
        raw = _run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"])
    rows = []
    for ln in raw.splitlines():
        if "LISTEN" not in ln.upper():
            continue
        if any(f":{port} " in ln + " " for port in HOST_PORTS):
            rows.append(" ".join(ln.split()))
    return "\n".join(sorted(set(rows))) or "(no listener on the pinned ports)"


def _network_and_firewall() -> str:
    """Network profiles and the firewall rules that admit node inbound.

    Windows only. Interface alias and category, not the network (SSID) name.
    The port-filter cmdlet needs admin, so rules are matched by program.
    """
    if sys.platform != "win32":
        return f"(not collected on {sys.platform})"
    script = (
        "Get-NetConnectionProfile | Select-Object InterfaceAlias,NetworkCategory"
        " | Format-Table -AutoSize | Out-String -Width 200;"
        " Get-NetFirewallApplicationFilter | Where-Object { $_.Program -match"
        " 'node\\.exe' } | Get-NetFirewallRule | Where-Object Enabled -eq 'True'"
        " | Select-Object DisplayName,Direction,Action,Profile"
        " | Format-Table -AutoSize | Out-String -Width 200"
    )
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 script]).strip() or "(collection failed)"


def _dashboard_auth_probe() -> str:
    """Does /ops answer with no credentials? Status code only.

    Measured from outside rather than read from .env: the producer has no
    business opening the secrets file, and what matters is what the server
    actually does.
    """
    req = urllib.request.Request("http://127.0.0.1:3000/ops", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            code = resp.status
    except urllib.error.HTTPError as e:
        code = e.code
    except (urllib.error.URLError, OSError) as e:
        return f"no response from 127.0.0.1:3000 ({type(e).__name__})"
    meaning = {200: "served without credentials (auth off)",
               401: "credentials required (auth on)"}.get(code, "unexpected")
    return f"GET /ops without credentials -> HTTP {code}: {meaning}"


def _dev_script() -> str:
    try:
        pkg = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "(package.json unreadable)"
    scripts = pkg.get("scripts") or {}
    return "\n".join(f"{k}: {v}" for k, v in scripts.items()
                     if k.startswith("dev"))


def host_evidence() -> dict:
    """Read-only facts about how this machine exposes the dashboard."""
    return {
        "platform": sys.platform,
        "listening": _listening_sockets(),
        "network_firewall": _network_and_firewall(),
        "tailscale_serve": _run(["tailscale", "serve", "status"]).strip()
        or "(tailscale not available)",
        "auth_probe": _dashboard_auth_probe(),
        "dev_scripts": _dev_script(),
    }


def plan() -> list[dict]:
    changed = changed_files()

    npm_audit = ""
    if (REPO_ROOT / "package.json").exists():
        npm_audit = _run(["npm", "audit", "--json"], timeout=300)

    pip_outdated = _run([sys.executable, "-m", "pip", "list", "--outdated"],
                        timeout=300)

    common = {"runtime": "codex", "sensitivity": "internal"}
    return [
        {"kind": "sec.secret_scan", **common,
         "payload": {"changed_files": changed}},
        {"kind": "sec.stale_docs", **common,
         "payload": {}},
        {"kind": "sec.dependency_audit", **common,
         "payload": {"npm_audit": npm_audit, "pip_outdated": pip_outdated}},
        {"kind": "sec.dead_code", **common,
         "payload": {}},
        {"kind": "sec.host_config", **common,
         "payload": host_evidence()},
    ]
