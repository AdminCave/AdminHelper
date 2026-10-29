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

Note: the whole context is JSON-serialised into the worker (json.dumps with default=str), so
only JSON-native types survive. Non-native values in event_data (datetime, Decimal, bytes, ORM
objects) reach the hook as their str() form, not as the original type (4.137).
"""

import codecs
import io
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from app.core import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_TIMEOUT_SECONDS = 30

# How long both reader threads together may take to read the rest of the output once the worker
# has exited, before and once more after the process group is killed (see the joins below).
_READER_GRACE_SECONDS = 2

# Defense-in-depth: bound the number of concurrent hook subprocesses so a burst
# of (slow) hooks can't spawn unbounded processes / exhaust the threadpool +
# DB pool. A caller that can't acquire IMMEDIATELY gets a busy error instead of
# piling up — the acquire must never block: the webhook handler runs on the anyio
# threadpool, which FastAPI also uses for sync routes (login, CRUD, health), so a
# parked waiter would bind a thread and stall the server (5.5). Acquire/release
# wrap only the blocking worker communicate().
_MAX_CONCURRENT_HOOKS = 8
_hook_semaphore = threading.BoundedSemaphore(_MAX_CONCURRENT_HOOKS)

# Hard cap on the bytes read from a hook's stdout/stderr. communicate() buffers the worker's output
# unbounded, so a hook writing directly to fd 1/2 (os.write(1, b"x"*10**10), a flooding subprocess)
# past the worker's own log cap could OOM the parent server — a public-webhook-triggered DoS (4.139).
_MAX_HOOK_OUTPUT_BYTES = 8 * 1024 * 1024

# Cap on the error text of a failed run in a log line: the error of a worker that exits non-zero
# is its whole stderr, up to _MAX_HOOK_OUTPUT_BYTES. A traceback ends with the exception, so the
# end of the text is kept.
_LOGGED_ERROR_MAX = 1000

_WORKER_SCRIPT = str(Path(__file__).parent / "script_worker.py")


def _fallback_home() -> str:
    """HOME for a worker whose server has none: DATA_DIR/hooks-home, 0700, made on first use.

    chmod also narrows a directory someone created with wider rights; mkdir alone would keep them.
    """
    home = config.DATA_DIR.resolve() / "hooks-home"
    home.mkdir(mode=0o700, exist_ok=True)
    home.chmod(0o700)
    return str(home)


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
    # HOME/LANG are set so HOME- and locale-sensitive code behaves predictably rather than
    # defaulting oddly (HOME falls back to a private directory, not a world-writable one); a
    # configured egress proxy is forwarded below so a hook's HTTP calls (http_get/http_post)
    # honour it — that's egress/SSRF control, not a secret (4.138).
    # PYTHONNOUSERSITE does for every Python process a script starts what -s does for the worker
    # (see the Popen call).
    server_dir = str(Path(__file__).parents[3])  # server/
    try:
        home = os.environ.get("HOME") or _fallback_home()
    except OSError as exc:
        # The path goes to the server log only: a webhook caller gets this error text back.
        logger.warning("Hook HOME %s unusable: %s", config.DATA_DIR / "hooks-home", exc)
        return {
            "success": False,
            "result": {},
            "logs": [],
            "error": f"Hook HOME unusable: {type(exc).__name__}",
        }
    worker_env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": home,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONPATH": server_dir,
        "PYTHONNOUSERSITE": "1",
        "DATABASE_URL": os.environ.get("DATABASE_URL", ""),
        "DATA_DIR": os.environ.get("DATA_DIR", ""),
    }
    for _proxy_var in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    ):
        if _proxy_var in os.environ:
            worker_env[_proxy_var] = os.environ[_proxy_var]

    if not _hook_semaphore.acquire(blocking=False):
        return {
            "success": False,
            "result": {},
            "logs": ["Server ausgelastet: zu viele gleichzeitige Hook-Ausführungen"],
            "error": "Server ausgelastet (Hook-Limit erreicht)",
        }
    # The permit is held from here on, but the try/finally that releases it only starts after the
    # threads are up. Guard the gap: Popen can fail (fork under memory pressure) and Thread.start
    # can fail (thread exhaustion), and a permit lost there is lost for good — with
    # BoundedSemaphore(_MAX_CONCURRENT_HOOKS) eight such failures disable hooks until restart, and
    # the caller only ever sees the misleading "Server ausgelastet".
    proc = None
    try:
        # Run the worker in its OWN process group (start_new_session) so a timeout can kill the
        # WHOLE tree, not just the direct child: hook scripts get real builtins and can spawn
        # grandchildren (os.system, subprocess, multiprocessing) that would otherwise be orphaned
        # and keep running unbounded past the timeout (4.69).
        # -s leaves out the user site: the image's Python has no venv, so without it the worker
        # would put $HOME/.local/lib/pythonX.Y/site-packages on sys.path and run a usercustomize
        # from there. -I and -E are no option: they ignore PYTHONPATH, which the worker needs to
        # import app.
        proc = subprocess.Popen(
            [sys.executable, "-s", _WORKER_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=server_dir,
            env=worker_env,
            start_new_session=True,
        )
        # Read stdout/stderr in threads with a hard byte budget instead of communicate(): the
        # latter buffers unbounded, so a hook flooding fd 1/2 past the worker's log cap could OOM
        # the parent (4.139). Once a reader hits the budget it stops; the full pipe then blocks the
        # worker, which the timeout (or the over-budget check below) kills.
        out_holder: list[str] = []
        err_holder: list[str] = []

        # The readers collect in chunks rather than in one read to EOF: a background process in a
        # session of its own can hold the pipe open past both graces below, and what the worker
        # wrote before it exited is then still evaluated (R-0846). They decode like the text-mode
        # stream they bypass, which a read on its fd would otherwise wait on for a full count.
        def _drain(stream, holder):
            decoder = io.IncrementalNewlineDecoder(
                codecs.getincrementaldecoder(stream.encoding)(stream.errors), translate=True
            )
            size = 0
            while chunk := os.read(stream.fileno(), 65536):
                text = decoder.decode(chunk)
                holder.append(text)
                size += len(text)
                if size > _MAX_HOOK_OUTPUT_BYTES:
                    # Over budget: the reader stops here, so the worker will block on a full pipe.
                    # Kill it now so proc.wait() returns at once instead of burning the timeout.
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
                    return
            holder.append(decoder.decode(b"", final=True))

        # The payload goes in from a thread too: a worker that does not read stdin would block a
        # write larger than the pipe buffer, and proc.wait(timeout) below would never start (R-0845).
        def _feed():
            try:
                proc.stdin.write(payload)
                proc.stdin.close()
            except OSError:
                pass  # worker died before reading stdin; its stderr explains why

        t_out = threading.Thread(target=_drain, args=(proc.stdout, out_holder), daemon=True)
        t_err = threading.Thread(target=_drain, args=(proc.stderr, err_holder), daemon=True)
        t_in = threading.Thread(target=_feed, daemon=True)
        t_out.start()
        t_err.start()
        t_in.start()
    except BaseException:
        # A worker that started before the failure must not outlive this request either.
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        _hook_semaphore.release()
        raise
    try:
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
    # would hang this request thread indefinitely (bypassing the timeout). The worker has written
    # its output when it exits, so the readers only need a short grace, for both together, to read
    # the rest. If a reader is still alive after it, kill the whole group (start_new_session ⇒
    # pgid == proc.pid) to close the inherited write-ends, then re-join within the same grace.
    # A run so ends after at most timeout + 2 × _READER_GRACE_SECONDS (34 s at the default): the
    # gateway closes /api/... after 60 s without a response (nginx's default proxy_read_timeout,
    # apps/gateway/nginx.conf sets none for it), and /api/hooks/trigger and /api/hooks/{id}/run
    # answer only after the run.
    deadline = time.monotonic() + _READER_GRACE_SECONDS
    t_out.join(timeout=_READER_GRACE_SECONDS)
    t_err.join(timeout=max(0.0, deadline - time.monotonic()))
    if t_out.is_alive() or t_err.is_alive():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        # Bounded again: a grandchild that escaped the killpg (a hook that double-forked into its own
        # session while holding fd 1) would otherwise hang the final join forever. Abandon such a
        # reader — a leaked daemon thread + one fd — rather than hang the request thread; what it
        # has read so far is evaluated below. Only reachable by a pathological trusted-admin
        # hook, never by the webhook caller, but this keeps the bound of
        # timeout + 2 × _READER_GRACE_SECONDS above absolute.
        deadline = time.monotonic() + _READER_GRACE_SECONDS
        t_out.join(timeout=_READER_GRACE_SECONDS)
        t_err.join(timeout=max(0.0, deadline - time.monotonic()))
    out = "".join(out_holder)
    err = "".join(err_holder)

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


def failed_run_error(result: dict) -> str | None:
    """The error text of a failed run, shortened for a log line; None for a successful run."""
    if result.get("success") is True:
        return None
    error = str(result.get("error") or "unknown error")
    if len(error) > _LOGGED_ERROR_MAX:
        return "…" + error[-_LOGGED_ERROR_MAX:]
    return error
