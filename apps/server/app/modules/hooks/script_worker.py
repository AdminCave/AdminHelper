# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Isolated worker process for hook scripts.

Started by script_runner.py as a subprocess. Receives the script and the
context via stdin (JSON), executes the script and returns the result via
stdout (JSON).

SECURITY MODEL: Hook scripts are TRUSTED code (creatable/editable by admins
only) and run with full Python/server privileges. The subprocess provides
crash/timeout isolation, but is NOT a security sandbox. The minimized env
(script_runner.py) reduces the secret footprint (no ADMIN_PASSWORD/
MONITOR_API_KEY/REDIS_URL), but a hook can still read DB creds (DATABASE_URL) and
the SECRET_KEY (via config or DATA_DIR). Whoever may write hooks can run
arbitrary code — like a plugin or cron job.
"""

import json
import sys
from typing import Any

import httpx


def _safe_http_get(url: str, headers: dict | None = None, timeout: int = 10) -> dict:
    resp = httpx.get(url, headers=headers or {}, timeout=timeout, follow_redirects=True)
    try:
        j = resp.json()
    except Exception:
        j = None
    return {"status": resp.status_code, "body": resp.text, "json": j}


def _safe_http_post(url: str, json_data: Any = None, headers: dict | None = None, timeout: int = 10) -> dict:
    resp = httpx.post(url, json=json_data, headers=headers or {}, timeout=timeout, follow_redirects=True)
    try:
        j = resp.json()
    except Exception:
        j = None
    return {"status": resp.status_code, "body": resp.text, "json": j}


def main() -> None:
    import uuid as _uuid

    # Lazy imports — only when the script needs connections
    from app.modules.connections.storage import load_connections, save_connections

    raw = sys.stdin.read()
    payload = json.loads(raw)

    script = payload["script"]
    context = payload.get("context", {})

    result: dict = {}
    logs: list[str] = []
    max_log_lines = 1000
    max_log_line_length = 4096

    def _log(msg: Any) -> None:
        line = str(msg)[:max_log_line_length]
        if len(logs) < max_log_lines:
            logs.append(line)

    def _print(*args: Any, sep: str = " ", end: str = "\n", **_kwargs: Any) -> None:
        line = sep.join(str(a) for a in args)[:max_log_line_length]
        if len(logs) < max_log_lines:
            logs.append(line)

    namespace: dict[str, Any] = {
        # Hooks are trusted admin code (see module docstring): full builtins.
        # exec() injects __builtins__ automatically when it is missing from
        # globals; the previously filtered __builtins__ was an INEFFECTIVE
        # pseudo-sandbox — every exposed function led back to the real builtins
        # via its __globals__ (__import__). 'print' is overridden so that output
        # ends up in the log.
        "print": _print,
        "load_connections": load_connections,
        "save_connections": save_connections,
        "http_get": _safe_http_get,
        "http_post": _safe_http_post,
        "uuid4": lambda: str(_uuid.uuid4()),
        "log": _log,
        "result": result,
        "logs": logs,
        **context,
    }

    try:
        compiled = compile(script, "<hook_script>", "exec")
        exec(compiled, namespace)  # noqa: S102
        output = {"success": True, "result": result, "logs": logs}
    except Exception as exc:
        logs.append(f"Fehler: {exc}")
        output = {"success": False, "result": result, "logs": logs, "error": str(exc)}

    # Result as JSON to stdout
    sys.stdout.write(json.dumps(output, default=str))


if __name__ == "__main__":
    main()
