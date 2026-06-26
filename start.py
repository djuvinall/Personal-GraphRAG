"""
start.py — Single launcher for all Personal GraphRAG services.

Starts in order:
  1. Dashboard   (FastAPI,  port WEB_UI_PORT  / default 5000)
  2. MCP server  (FastMCP,  port PMEM_PORT    / default 8000)
  3. ngrok       (tunnel → MCP server port)

Ctrl-C shuts all three down cleanly.

Environment variables (same as the individual servers):
  WEB_UI_PASSWORD    Dashboard password (open / no auth if unset)
  WEB_UI_SECRET      Session signing key
  WEB_UI_PORT        Dashboard port (default 5000)
  PMEM_PORT          MCP server port (default 8000)
  PMEM_EMBED_BACKEND hash | ollama (default ollama)
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT    = Path(__file__).parent
SERVERS = ROOT / "servers"
PYTHON  = sys.executable            # same venv Python that launched this script

MCP_PORT  = int(os.environ.get("PMEM_PORT",    "8000"))
DASH_PORT = int(os.environ.get("WEB_UI_PORT",  "5000"))

# ── helpers ───────────────────────────────────────────────────────────────────

def _ngrok_url(timeout: int = 20) -> str | None:
    """Poll ngrok's local management API until an HTTPS tunnel URL appears."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://localhost:4040/api/tunnels", timeout=2) as r:
                data = json.loads(r.read())
                for t in data.get("tunnels", []):
                    if t.get("proto") == "https":
                        return t["public_url"]
        except Exception:
            pass
        time.sleep(0.5)
    return None


def _pipe_output(stream, label: str) -> None:
    """Read lines from a subprocess stream and print them with a label prefix."""
    try:
        for raw in stream:
            line = raw.decode(errors="replace").rstrip()
            if line:
                print(f"  [{label}] {line}", flush=True)
    except Exception:
        pass


def _start(cmd: list[str], label: str) -> subprocess.Popen:
    """Spawn a subprocess and stream its stdout+stderr to this terminal with a label."""
    print(f"  starting {label}…")
    p = subprocess.Popen(
        cmd, cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,   # merge stderr into stdout
    )
    # Background thread so output appears without blocking the launcher
    t = threading.Thread(target=_pipe_output, args=(p.stdout, label), daemon=True)
    t.start()
    return p


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    procs: list[tuple[str, subprocess.Popen]] = []

    def shutdown(sig=None, frame=None) -> None:
        print("\nShutting down…")
        for _label, p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        time.sleep(1)
        for _label, p in procs:
            if p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass
        sys.exit(0)

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    print()
    print("─" * 52)
    print("  Personal GraphRAG — starting services")
    print("─" * 52)

    # 1. Dashboard
    procs.append(("Dashboard", _start(
        [PYTHON, str(SERVERS / "dashboard.py")], "Dashboard"
    )))
    time.sleep(2)   # let it bind (and surface any startup errors) before continuing

    # 2. MCP server
    procs.append(("MCP server", _start(
        [PYTHON, str(SERVERS / "mcp_server.py")], "MCP server"
    )))
    time.sleep(2)   # let it bind before ngrok connects

    # 3. ngrok — kill any stale tunnel from a previous run first
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/f", "/im", "ngrok.exe"],
                       capture_output=True)   # silent — fine if nothing to kill
    else:
        subprocess.run(["pkill", "-f", "ngrok"], capture_output=True)
    time.sleep(0.5)

    try:
        procs.append(("ngrok", _start(
            ["ngrok", "http", str(MCP_PORT)], "ngrok"
        )))
    except FileNotFoundError:
        print("  ⚠  ngrok not found in PATH — skipping tunnel")
        print("     Install from https://ngrok.com/download and add to PATH.")
        ngrok_url = None
    else:
        print("  waiting for ngrok tunnel…")
        ngrok_url = _ngrok_url(timeout=20)

    # ── startup summary ───────────────────────────────────────────────────────
    print()
    print("─" * 52)
    print(f"  Dashboard   →  http://localhost:{DASH_PORT}")
    print(f"  MCP server  →  http://localhost:{MCP_PORT}  (local only)")

    if ngrok_url:
        print(f"  ngrok URL   →  {ngrok_url}")
        print()
        print("  Paste into Claude.ai connector (OAuth blank):")
        print(f"    {ngrok_url}")
    else:
        print("  ngrok URL   →  (check http://localhost:4040)")

    print("─" * 52)
    print("  Ctrl-C to stop all services")
    print()

    # ── watch for unexpected exits ─────────────────────────────────────────────
    while True:
        for label, p in procs:
            if p.poll() is not None:
                print(f"\n  ⚠  {label} exited (code {p.returncode}) — shutting down all")
                shutdown()
        time.sleep(1)


if __name__ == "__main__":
    main()
