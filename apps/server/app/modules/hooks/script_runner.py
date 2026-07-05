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
    headers             dict            safe-listed request headers only (no
                                        Authorization/Cookie/X-Forwarded-*)
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
import signal
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
# instead of piling up. Acquire/release wrap only the blocking worker communicate().
_MAX_CONCURRENT_HOOKS = 8
_HOOK_ACQUIRE_TIMEOUT = 10
_hook_semaphore = threading.BoundedSemaphore(_MAX_CONCURRENT_HOOKS)

# Hard cap on the bytes read from a hook's stdout/stderr. communicate() buffers the worker's output
# unbounded, so a hook writing directly to fd 1/2 (os.write(1, b"x"*10**10), a flooding subprocess)
# past the worker's own log cap could OOM the parent server — a public-webhook-triggered DoS (4.139).
_MAX_HOOK_OUTPUT_BYTES = 8 * 1024 * 1024

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
    payload = json.dumps(
        {
            "script": script,
            "context": context,
        },
        default=str,
    )

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
    # Run the worker in its OWN process group (start_new_session) so a timeout can kill the
    # WHOLE tree, not just the direct child: hook scripts get real builtins and can spawn
    # grandchildren (os.system, subprocess, multiprocessing) that would otherwise be orphaned and
    # keep running unbounded past the timeout (4.69).
    proc = subprocess.Popen(
        [sys.executable, _WORKER_SCRIPT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=server_dir,
        env=worker_env,
        start_new_session=True,
    )
    # Read stdout/stderr in threads with a hard byte budget instead of communicate(): the latter
    # buffers unbounded, so a hook flooding fd 1/2 past the worker's log cap could OOM the parent
    # (4.139). Once a reader hits the budget it stops; the full pipe then blocks the worker, which
    # the timeout (or the over-budget check below) kills.
    out_holder: list[str] = []
    err_holder: list[str] = []

    def _drain(stream, holder):
        data = stream.read(_MAX_HOOK_OUTPUT_BYTES + 1)
        holder.append(data)
        if len(data) > _MAX_HOOK_OUTPUT_BYTES:
            # Over budget: the reader stops here, so the worker will block on a full pipe. Kill it
            # now so proc.wait() returns at once instead of burning the whole timeout.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    t_out = threading.Thread(target=_drain, args=(proc.stdout, out_holder), daemon=True)
    t_err = threading.Thread(target=_drain, args=(proc.stderr, err_holder), daemon=True)
    t_out.start()
    t_err.start()
    try:
        try:
            proc.stdin.write(payload)
            proc.stdin.close()
        except BrokenPipeError:
            pass  # worker died before reading stdin; its stderr explains why
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Kill the entire process group (the worker plus any grandchildren it spawned); with
        # start_new_session the pgid equals proc.pid. Then reap so no zombie is left behind.
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        return {
            "success": False,
            "result": {},
            "logs": [f"Script abgebrochen: Timeout nach {timeout}s"],
            "error": f"Timeout nach {timeout}s",
        }
    finally:
        _hook_semaphore.release()

    # Bound the join: proc.wait() only reaps the direct child, so a hook that backgrounds a
    # grandchild inheriting fd 1/2 keeps the pipe open past the worker's exit — an unbounded join
    # would hang this request thread indefinitely (bypassing the timeout). If a reader is still
    # alive after the timeout, kill the whole group (start_new_session ⇒ pgid == proc.pid) to close
    # the inherited write-ends, then re-join — this preserves the runtime bound 4.69 guarantees.
    t_out.join(timeout=timeout)
    t_err.join(timeout=timeout)
    if t_out.is_alive() or t_err.is_alive():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        # Bounded again: a grandchild that escaped the killpg (a hook that double-forked into its own
        # session while holding fd 1) would otherwise hang the final join forever. Abandon such a
        # reader — a leaked daemon thread + one fd — rather than hang the request thread; the holder
        # guard below tolerates the unread stream. Only reachable by a pathological trusted-admin
        # hook, never by the webhook caller, but this keeps the runtime bound absolute.
        t_out.join(timeout=timeout)
        t_err.join(timeout=timeout)
    out = out_holder[0] if out_holder else ""
    err = err_holder[0] if err_holder else ""

    if len(out) > _MAX_HOOK_OUTPUT_BYTES or len(err) > _MAX_HOOK_OUTPUT_BYTES:
        # A stream blew the budget (the drain thread already SIGKILLed the worker; kill again as a
        # belt-and-braces fallback in case that raced).
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        return {
            "success": False,
            "result": {},
            "logs": [],
            "error": "Hook-Ausgabe zu gross (Limit ueberschritten)",
        }

    if proc.returncode != 0:
        stderr = err.strip()
        return {
            "success": False,
            "result": {},
            "logs": [stderr] if stderr else ["Script mit Fehler beendet"],
            "error": stderr or "Unbekannter Fehler",
        }

    try:
        result = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return {
            "success": False,
            "result": {},
            "logs": [out[:4096]] if out else [],
            "error": "Ungueltige Worker-Ausgabe",
        }

    return result
