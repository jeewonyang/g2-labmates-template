"""Focused tests for the independent G2 web-host recovery subsystem.

Runs without Task Scheduler registration or administrator access:
    python .claude/scripts/tests/test_web_host_recovery.py
"""

import contextlib
import http.server
import json
import socket
import subprocess
import tempfile
import threading
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / ".claude" / "scripts"
POWERSHELL = "powershell.exe"


def run_ps(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(script), *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=20,
    )


class HealthHandler(http.server.BaseHTTPRequestHandler):
    marker = True

    def do_GET(self):  # noqa: N802 - stdlib handler API
        body = json.dumps({"ok": True, "service": "second-brain"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if self.marker:
            self.send_header("X-G2-Service", "second-brain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


@contextlib.contextmanager
def health_server(marker=True):
    class Handler(HealthHandler):
        pass

    Handler.marker = marker
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_powershell_syntax():
    names = ("run_web_host.ps1", "watch_web_host.ps1",
             "recover_web_host.ps1", "setup_web_host.ps1")
    command = (
        "$bad=$false;"
        + ";".join(
            "$t=$null;$e=$null;"
            f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPTS / name}',"
            "[ref]$t,[ref]$e)|Out-Null;"
            "if($e.Count){$e|ForEach-Object{Write-Error $_};$bad=$true}"
            for name in names
        )
        + ";if($bad){exit 1}"
    )
    result = subprocess.run(
        [POWERSHELL, "-NoLogo", "-NoProfile", "-Command", command],
        cwd=REPO, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_probe_requires_g2_marker():
    script = SCRIPTS / "watch_web_host.ps1"
    with health_server(marker=True) as port:
        good = run_ps(script, "-ProbeOnly", "-HealthUrl",
                      f"http://127.0.0.1:{port}/api/health")
    assert good.returncode == 0, good.stderr
    assert good.stdout.strip() == "healthy"

    with health_server(marker=False) as port:
        wrong = run_ps(script, "-ProbeOnly", "-HealthUrl",
                       f"http://127.0.0.1:{port}/api/health")
    assert wrong.returncode == 1
    assert "marker missing" in wrong.stdout


def test_consecutive_failures_are_tolerated_then_reset():
    script = SCRIPTS / "watch_web_host.ps1"
    with tempfile.TemporaryDirectory() as raw:
        temp = Path(raw)
        state = temp / "state.json"
        log = temp / "watch.log"
        url = f"http://127.0.0.1:{unused_port()}/api/health"
        common = ("-HealthUrl", url, "-FailureThreshold", "2", "-NoRecover",
                  "-StatePath", str(state), "-LogPath", str(log))

        first = run_ps(script, *common)
        assert first.returncode == 0, first.stderr
        assert json.loads(state.read_text(encoding="utf-8-sig"))["consecutiveFailures"] == 1

        second = run_ps(script, *common)
        assert second.returncode == 0, second.stderr
        saved = json.loads(state.read_text(encoding="utf-8-sig"))
        assert saved["consecutiveFailures"] == 0
        assert "Recovery suppressed after 2 failed probes" in log.read_text(
            encoding="utf-8-sig")


def test_recovery_refuses_unattributed_port_owner():
    source = (SCRIPTS / "recover_web_host.ps1").read_text(encoding="utf-8")
    proof = source.index("$isNode -and $isThisRepo")
    refusal = source.index("Refused to stop unowned PID")
    stop = source.index("Stop-Process -Id")
    assert proof < refusal < stop


def test_web_uptime_is_separate_from_agent_scheduler():
    setup = (SCRIPTS / "setup_web_host.ps1").read_text(encoding="utf-8")
    agents = (SCRIPTS / "setup_scheduler.ps1").read_text(encoding="utf-8")
    for name in ("SecondBrain-WebHost", "SecondBrain-WebWatchdog",
                 "SecondBrain-WebRecover"):
        assert name in setup
        assert name not in agents


def test_desktop_launcher_prefers_supervised_recovery():
    launcher = (REPO / "start-second-brain.bat").read_text(encoding="utf-8")
    query = launcher.index('schtasks /Query /TN "SecondBrain-WebRecover"')
    recovery = launcher.index('schtasks /Run /TN "SecondBrain-WebRecover"')
    fallback = launcher.index('\n:fallback')
    direct_start = launcher.index('start "Second Brain server"')
    assert query < recovery < fallback < direct_start


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\nAll {len(tests)} web-host recovery tests passed.")
