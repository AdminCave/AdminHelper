# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Isolierter Worker-Prozess fuer Hook-Scripts.

Wird von script_runner.py als Subprozess gestartet. Empfaengt das Script
und den Kontext via stdin (JSON), fuehrt das Script aus und gibt das
Ergebnis via stdout (JSON) zurueck.

SICHERHEITSMODELL: Hook-Skripte sind VERTRAUENSWUERDIGER Code (nur von Admins
anleg-/editierbar) und laufen mit vollen Python-/Server-Rechten. Der Subprozess
liefert Crash-/Timeout-Isolation, ist aber KEINE Security-Sandbox. Secrets werden
dem Subprozess nicht vererbt (siehe script_runner.py). Wer Hooks schreiben darf,
kann beliebigen Code ausfuehren — wie ein Plugin oder Cron-Job.
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

    # Lazy imports — nur wenn das Script Connections braucht
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
        # Hooks sind vertrauenswuerdiger Admin-Code (siehe Modul-Docstring): volle
        # Builtins. exec() injiziert __builtins__ automatisch, wenn es im globals
        # fehlt; der frueher gefilterte __builtins__ war eine WIRKUNGSLOSE
        # Pseudo-Sandbox — jede exponierte Funktion fuehrte ueber ihr __globals__
        # zurueck zu den echten Builtins (__import__). 'print' wird ueberschrieben,
        # damit Ausgaben im Log landen.
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

    # Ergebnis als JSON nach stdout
    sys.stdout.write(json.dumps(output, default=str))


if __name__ == "__main__":
    main()
