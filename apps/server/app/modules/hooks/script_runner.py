# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Script runner for hooks.

Each script runs in a separate subprocess (its own address space, killable
via timeout). This is crash/timeout isolation, NOT a security sandbox: hook
scripts are trusted admin code (creatable/editable by admins only) and run
with full server privileges — like a cron job.

The minimized env (run_hook_script) keeps ADMIN_PASSWORD, MONITOR_API_KEY and
REDIS_URL out of the hook process. It is, however, NOT complete secret
isolation: a hook needs DB access (DATABASE_URL is inherited) and can also read
the SECRET_KEY via the loaded app.core.config or DATA_DIR/.secret_key. Whoever
may write hooks has full server access.

Available variables in the script (always):
    load_connections()  -> list[dict]   load connections
    save_connections(list[dict])        save connections
    uuid4()             -> str          generate a new UUID
    result              dict            return value to the caller
    logs                list            log output
    log(msg)                            shorthand for logs.append(str(msg))
    http_get(url, ...)  -> dict         HTTP GET with timeout
    http_post(url, ...) -> dict         HTTP POST with timeout

Webhook context:
    payload             dict            JSON body of the request
    headers             dict            HTTP request headers
    params              dict            query parameters

Event context:
    event_type          str             name of the event (e.g. "connection.created")
    event_data          dict            affected resource

Schedule context:
    triggered_at        str             ISO timestamp of the execution
    last_run            str|None        last run (ISO) or None
"""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_TIMEOUT_SECONDS = 30

# Defense-in-depth: bound the number of concurrent hook subprocesses so a burst
# of (slow) hooks can't spawn unbounded processes / exhaust the threadpool +
# DB pool. A caller that can't acquire within the timeout gets a busy error
# instead of piling up. Acquire/release wrap only the blocking subprocess.run.
_MAX_CONCURRENT_HOOKS = 8
_HOOK_ACQUIRE_TIMEOUT = 10
_hook_semaphore = threading.BoundedSemaphore(_MAX_CONCURRENT_HOOKS)

_WORKER_SCRIPT = str(Path(__file__).parent / "script_worker.py")


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------


def run_hook_script(
    script: str,
    hook_type: str,
    context: dict,
    timeout: int = SCRIPT_TIMEOUT_SECONDS,
) -> dict:
    """Run the script in an isolated subprocess and return the result."""
    payload = json.dumps({
        "script": script,
        "context": context,
    }, default=str)

    # Minimized environment: removes ADMIN_PASSWORD, MONITOR_API_KEY and REDIS_URL
    # from the hook process. NOT complete isolation — DATABASE_URL (DB creds) is
    # deliberately inherited (hooks need DB access), and SECRET_KEY stays reachable
    # via DATA_DIR/.secret_key or the loaded config. Hooks = trusted code.
    server_dir = str(Path(__file__).parents[3])  # server/
    worker_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": server_dir,
        "DATABASE_URL": os.environ.get("DATABASE_URL", ""),
        "DATA_DIR": os.environ.get("DATA_DIR", ""),
    }

    if not _hook_semaphore.acquire(timeout=_HOOK_ACQUIRE_TIMEOUT):
        return {
            "success": False,
            "result": {},
            "logs": ["Server ausgelastet: zu viele gleichzeitige Hook-Ausführungen"],
            "error": "Server ausgelastet (Hook-Limit erreicht)",
        }
    try:
        proc = subprocess.run(
            [sys.executable, _WORKER_SCRIPT],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=server_dir,
            env=worker_env,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "result": {},
            "logs": [f"Script abgebrochen: Timeout nach {timeout}s"],
            "error": f"Timeout nach {timeout}s",
        }
    finally:
        _hook_semaphore.release()

    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        return {
            "success": False,
            "result": {},
            "logs": [stderr] if stderr else ["Script mit Fehler beendet"],
            "error": stderr or "Unbekannter Fehler",
        }

    try:
        result = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return {
            "success": False,
            "result": {},
            "logs": [proc.stdout[:4096]] if proc.stdout else [],
            "error": "Ungueltige Worker-Ausgabe",
        }

    return result
