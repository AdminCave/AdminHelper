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

from app.core.ssrf import is_private_url

# Cap the reflected body so a large internal response can't flood the worker's
# memory (the hook may echo it back through the result dict).
_MAX_BODY = 1_000_000


def _read_capped_body(resp: httpx.Response) -> tuple[str, Any]:
    # Stream the body and abort once it exceeds _MAX_BODY, instead of resp.text loading the WHOLE
    # response into the worker's RAM first (a gigabyte target -> OOM, made worse when the hook
    # echoes it back through the result dict) and only THEN slicing it — the slice was too late
    # (4.70).
    body = b""
    for chunk in resp.iter_bytes():
        body += chunk
        if len(body) > _MAX_BODY:
            raise ValueError(f"Antwort zu gross (> {_MAX_BODY} Bytes)")
    text = body.decode(resp.encoding or "utf-8", "replace")
    try:
        parsed = json.loads(text) if text else None
    except ValueError:
        parsed = None
    return text, parsed


def _safe_http_get(url: str, headers: dict | None = None, timeout: int = 10) -> dict:
    # The URL can come straight from an attacker-controlled webhook payload, so guard
    # against SSRF and never follow a redirect into an internal target (3.37).
    if is_private_url(url):
        raise ValueError(f"Zieladresse nicht erlaubt (SSRF-Schutz): {url}")
    with httpx.stream(
        "GET", url, headers=headers or {}, timeout=timeout, follow_redirects=False
    ) as resp:
        text, j = _read_capped_body(resp)
        return {"status": resp.status_code, "body": text, "json": j}


def _safe_http_post(
    url: str, json_data: Any = None, headers: dict | None = None, timeout: int = 10
) -> dict:
    if is_private_url(url):
        raise ValueError(f"Zieladresse nicht erlaubt (SSRF-Schutz): {url}")
    with httpx.stream(
        "POST",
        url,
        json=json_data,
        headers=headers or {},
        timeout=timeout,
        follow_redirects=False,
    ) as resp:
        text, j = _read_capped_body(resp)
        return {"status": resp.status_code, "body": text, "json": j}


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
    }
    # Merge the event context WITHOUT letting it shadow an injected helper or the return
    # bindings: **context merged last would let a context key named result/logs/http_get/print
    # override the helper (or the result reference), breaking the hook silently. Reject a
    # collision instead — the current fixed context keys can't hit one, but a future event key
    # that matches a helper name would otherwise fail silently (4.71).
    _RESERVED = {
        "print",
        "load_connections",
        "save_connections",
        "http_get",
        "http_post",
        "uuid4",
        "log",
        "result",
        "logs",
    }
    try:
        for _k, _v in context.items():
            if _k in _RESERVED:
                raise ValueError(f"Kontext-Schluessel {_k!r} kollidiert mit einem Hook-Helfer")
            namespace[_k] = _v
        compiled = compile(script, "<hook_script>", "exec")
        exec(compiled, namespace)  # noqa: S102
        # Read result/logs back from the NAMESPACE, not the local names: a hook that rebinds
        # `result = {...}` (instead of result[...] = ...) only rebinds the namespace entry, so the
        # local `result` would stay the empty dict and the output would be silently lost
        # (success=True, result={}). Same for logs (4.71).
        output = {"success": True, "result": namespace["result"], "logs": namespace["logs"]}
    except Exception as exc:
        namespace["logs"].append(f"Fehler: {exc}")
        output = {
            "success": False,
            "result": namespace["result"],
            "logs": namespace["logs"],
            "error": str(exc),
        }

    # Result as JSON to stdout
    sys.stdout.write(json.dumps(output, default=str))


if __name__ == "__main__":
    main()
