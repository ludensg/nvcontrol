"""LACT integration.

LACT exposes a JSON API over a unix socket (/run/lactd.sock, see LACT docs/API.md).
NV//CONTROL only uses read-only calls to detect the daemon and its devices; fan curves
and VF tuning are left to LACT's own GUI so we never write LACT's config behind its back.
"""
from __future__ import annotations

import json
import socket
from pathlib import Path

SOCKET = Path("/run/lactd.sock")


def _request(payload: dict, timeout: float = 1.5) -> dict | None:
    if not SOCKET.exists():
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(SOCKET))
            s.sendall((json.dumps(payload) + "\n").encode())
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
        return json.loads(buf.decode() or "null")
    except (OSError, ValueError):
        return None


def ping() -> bool:
    r = _request({"command": "ping"})
    return bool(r and r.get("status") == "ok")


def list_devices() -> list[dict]:
    r = _request({"command": "list_devices"})
    if r and r.get("status") == "ok" and isinstance(r.get("data"), list):
        return r["data"]
    return []


def status() -> tuple[str, str]:
    """(state, message) for the UI."""
    if not SOCKET.exists():
        return "stopped", "lactd socket not found — enable with: sudo systemctl enable --now lactd"
    if ping():
        n = len(list_devices())
        return "ok", f"lactd running, {n} device(s) visible"
    return "denied", ("lactd is running but refused the connection. Add your user/group to "
                      "admin_groups in /etc/lact/config.yaml and restart lactd.")
