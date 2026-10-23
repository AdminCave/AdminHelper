# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hook posture (finding #4): the exec() 'sandbox' was ineffective (admin-gated,
no unauthenticated RCE). Fix = HONEST posture + partial hardening:

- The minimized env removes ADMIN_PASSWORD/MONITOR_API_KEY/REDIS_URL from the
  hook process (a real reduction of the secret footprint).
- BUT: hooks are trusted admin code with DB access. SECRET_KEY
  (via app.core.config or DATA_DIR/.secret_key) and DB creds (DATABASE_URL)
  remain reachable for a hook. This is DELIBERATELY tested here too so that no
  false protection claim arises (exactly the mistake the old pseudo-sandbox
  code made).
"""

import os

from app.modules.hooks.script_runner import run_hook_script

_PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "no_proxy")


def _unset_server_env(monkeypatch, *names):
    # The setenv seed lets undo() restore the prior state, set or not: delenv alone raises on an
    # unset variable, and with raising=False it records nothing to undo.
    for name in names:
        monkeypatch.setenv(name, os.environ.get(name, ""))
        monkeypatch.delenv(name)


def _worker_env(*names):
    script = "import os\n" + "".join(
        f"log({name!r} + '=' + os.environ.get({name!r}, '__NONE__'))\n" for name in names
    )
    res = run_hook_script(script, "webhook", {})
    assert res["success"] is True, res
    return dict(line.split("=", 1) for line in res["logs"])


def test_admin_password_not_inherited_by_worker():
    # ADMIN_PASSWORD is env-only (not file-/config-persisted) -> the env
    # minimization REALLY removes it from the hook process.
    res = run_hook_script(
        "import os\nlog(os.environ.get('ADMIN_PASSWORD', '__ABSENT__'))",
        "webhook",
        {},
    )
    assert res["success"] is True, res
    assert res["logs"] == ["__ABSENT__"], res["logs"]


def test_admin_password_not_reachable_in_process():
    # Honesty counter-check: ADMIN_PASSWORD is also not reconstructable
    # in-process (config reads it only from the env -> empty in the worker).
    res = run_hook_script(
        "import app.core.config as c\nlog(c.ADMIN_PASSWORD or '__EMPTY__')",
        "webhook",
        {},
    )
    assert res["success"] is True, res
    assert res["logs"] == ["__EMPTY__"], res["logs"]


def test_secret_key_reachable_in_process_BY_DESIGN():
    # HONESTY ANCHOR: a trusted hook CAN read the SECRET_KEY (the worker imports
    # app.core.config at startup, which resolves SECRET_KEY from
    # DATA_DIR/.secret_key). The minimized env does NOT protect SECRET_KEY. Anyone
    # who ever changes this to real isolation MUST deliberately adjust this test —
    # it prevents someone from falsely claiming 'SECRET_KEY is isolated'.
    res = run_hook_script(
        "import app.core.config as c\nlog('present' if c.SECRET_KEY else 'absent')",
        "webhook",
        {},
    )
    assert res["success"] is True, res
    assert res["logs"] == ["present"], res["logs"]


def test_full_builtins_imports_work():
    # Deliberate posture: hooks are trusted code and are allowed to import.
    res = run_hook_script("import json\nlog(json.dumps({'ok': True}))", "webhook", {})
    assert res["success"] is True, res
    assert res["logs"] == ['{"ok": true}'], res["logs"]


def test_legit_hook_api_still_works():
    # Removing the builtin whitelist must not break legitimate hooks.
    res = run_hook_script(
        "result['id'] = uuid4()\nlog('done')\nprint('captured')\nlog(str(len([1, 2, 3])))",
        "webhook",
        {},
    )
    assert res["success"] is True, res
    assert res["result"].get("id")
    assert "done" in res["logs"]
    assert "captured" in res["logs"]
    assert "3" in res["logs"]


def test_hook_output_flood_is_capped():
    # 4.139: a hook flooding fd 1 past the byte budget is rejected with an error, instead of the
    # parent buffering the worker's output unbounded and OOMing (a public-webhook DoS). The drain
    # thread kills the worker on overflow, so this returns promptly (not after the full timeout).
    import time

    start = time.monotonic()
    res = run_hook_script(
        "import os\nos.write(1, b'x' * (16 * 1024 * 1024))",  # 16 MB > 8 MB budget
        "webhook",
        {},
    )
    elapsed = time.monotonic() - start
    assert res["success"] is False, res
    assert "gross" in res["error"].lower(), res
    assert elapsed < 15, f"over-budget hook should be killed promptly, took {elapsed:.1f}s"


def test_hook_backgrounded_grandchild_does_not_hang_parent():
    # 4.139/4.69: a hook backgrounding a subprocess that inherits fd 1/2 and outlives the worker
    # must not hang the parent. proc.wait() only reaps the direct child, so the reader-thread join
    # is bounded and the process group is killed to close the inherited pipe. Short timeout so the
    # bounded join fires quickly; the grandchild (sleep 30) far outlives it.
    import time

    start = time.monotonic()
    run_hook_script(
        "import subprocess\nsubprocess.Popen(['sleep', '30'])\nresult['ok'] = True",
        "webhook",
        {},
        timeout=2,
    )
    elapsed = time.monotonic() - start
    assert elapsed < 10, f"parent hung on the grandchild's inherited pipe, took {elapsed:.1f}s"


def test_hook_worker_env_sets_home_lang_and_forwards_proxy(monkeypatch):
    # 4.138: HOME/LANG are set so HOME- and locale-sensitive code behaves predictably; a configured
    # egress proxy is forwarded so a hook's HTTP calls honour it (egress/SSRF control).
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    res = run_hook_script(
        "import os\n"
        "log('HOME=' + os.environ.get('HOME', '__NONE__'))\n"
        "log('LANG=' + os.environ.get('LANG', '__NONE__'))\n"
        "log('PROXY=' + os.environ.get('HTTPS_PROXY', '__NONE__'))",
        "webhook",
        {},
    )
    assert res["success"] is True, res
    joined = " ".join(res["logs"])
    assert "HOME=__NONE__" not in joined, res
    assert "LANG=__NONE__" not in joined, res
    assert "PROXY=http://proxy.example:3128" in joined, res


def test_hook_worker_env_falls_back_for_home_and_lang(monkeypatch):
    # docs/developer/hooks.html: HOME falls back to /tmp and LANG to C.UTF-8 when the server has
    # neither.
    _unset_server_env(monkeypatch, "HOME", "LANG")
    assert _worker_env("HOME", "LANG") == {"HOME": "/tmp", "LANG": "C.UTF-8"}


# Inside a venv site.ENABLE_USER_SITE is always False, so the tests check the flag that -s and
# PYTHONNOUSERSITE set, not whether a user site gets loaded. The child is a Python process the
# script starts itself; it inherits only the worker's env.
_NO_USER_SITE_SCRIPT = (
    "import os, subprocess, sys\n"
    "log('HOME=' + os.environ.get('HOME', '__NONE__'))\n"
    "log('worker=' + str(sys.flags.no_user_site))\n"
    "child = subprocess.run(\n"
    "    [sys.executable, '-c', 'import sys; print(sys.flags.no_user_site)'],\n"
    "    capture_output=True, text=True, check=True,\n"
    ")\n"
    "log('child=' + child.stdout.strip())\n"
)


def _no_user_site_flags():
    res = run_hook_script(_NO_USER_SITE_SCRIPT, "webhook", {})
    assert res["success"] is True, res
    return dict(line.split("=", 1) for line in res["logs"])


def test_hook_worker_and_its_python_children_run_without_user_site():
    flags = _no_user_site_flags()
    assert (flags["worker"], flags["child"]) == ("1", "1"), flags


def test_hook_worker_env_sets_pythonnousersite():
    assert _worker_env("PYTHONNOUSERSITE") == {"PYTHONNOUSERSITE": "1"}


def test_hook_worker_runs_without_user_site_on_the_home_fallback(monkeypatch):
    # The fallback case: with HOME=/tmp the user site would be a directory any local user can
    # create.
    _unset_server_env(monkeypatch, "HOME")
    flags = _no_user_site_flags()
    assert flags == {"HOME": "/tmp", "worker": "1", "child": "1"}, flags


def test_hook_worker_env_forwards_lowercase_proxy_vars_as_set(monkeypatch):
    _unset_server_env(monkeypatch, *_PROXY_VARS)
    monkeypatch.setenv("http_proxy", "http://192.0.2.10:3128")
    monkeypatch.setenv("https_proxy", "http://192.0.2.11:3128")
    monkeypatch.setenv("no_proxy", "hook-target.example")
    assert _worker_env(*_PROXY_VARS) == {
        "HTTP_PROXY": "__NONE__",
        "HTTPS_PROXY": "__NONE__",
        "NO_PROXY": "__NONE__",
        "http_proxy": "http://192.0.2.10:3128",
        "https_proxy": "http://192.0.2.11:3128",
        "no_proxy": "hook-target.example",
    }


def test_hook_worker_env_leaves_out_proxy_vars_the_server_lacks(monkeypatch):
    # docs/developer/hooks.html: a proxy variable reaches the worker only if the server has it,
    # not as an empty value.
    _unset_server_env(monkeypatch, *_PROXY_VARS)
    assert _worker_env(*_PROXY_VARS) == dict.fromkeys(_PROXY_VARS, "__NONE__")


def test_hook_semaphore_non_blocking_returns_busy_immediately():
    # 5.5: when all hook slots are taken, run_hook_script must return 'busy' IMMEDIATELY instead of
    # parking the anyio threadpool thread (which FastAPI shares with sync routes) for ~10s.
    import time

    import app.modules.hooks.script_runner as sr

    for _ in range(sr._MAX_CONCURRENT_HOOKS):
        assert sr._hook_semaphore.acquire(blocking=False)
    try:
        start = time.monotonic()
        res = sr.run_hook_script("result['ok'] = True", "webhook", {})
        elapsed = time.monotonic() - start
        assert res["success"] is False, res
        assert "ausgelastet" in res["error"].lower(), res
        assert elapsed < 1, f"busy must be immediate, took {elapsed:.1f}s"
    finally:
        for _ in range(sr._MAX_CONCURRENT_HOOKS):
            sr._hook_semaphore.release()


def test_semaphore_busy_returns_server_busy(monkeypatch):
    # 6.82(c): when all concurrent-hook slots are taken, run_hook_script returns the "Server
    # ausgelastet" response instead of spawning yet another worker. Patch the semaphore (rather than
    # exhaust the real one) so no slot leaks into other tests.
    from app.modules.hooks import script_runner

    class _FullSemaphore:
        def acquire(self, blocking=False):
            return False

        def release(self):
            pass

    monkeypatch.setattr(script_runner, "_hook_semaphore", _FullSemaphore())
    res = run_hook_script("log('x')", "webhook", {})
    assert res["success"] is False
    assert "ausgelastet" in res["error"]


def test_database_error_of_a_hook_reports_its_type_only(monkeypatch):
    # A hook stopped by an error of the database layer reports the error's type in `error` and
    # in its log, not the driver's text. The database is a loopback port that is bound but not
    # listening, so the connection is refused at once. libpq names only the address it tried;
    # with two hosts psycopg lists every attempt by its host name, which puts the word into the
    # driver's text (hostaddr skips the name lookup). The hook records that before it re-raises:
    # without it the test would also pass on a driver whose text names nothing.
    import socket

    word = "hookcheckword"
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        monkeypatch.setenv(
            "DATABASE_URL",
            f"postgresql+psycopg://hookcheck@/hookcheck?host={word}a:{port}&host={word}b:{port}"
            "&hostaddr=127.0.0.1,127.0.0.1&connect_timeout=2",
        )
        res = run_hook_script(
            "try:\n"
            "    load_connections()\n"
            "except Exception as exc:\n"
            f"    result['driver_text_has_word'] = {word!r} in str(exc)\n"
            "    raise\n",
            "webhook",
            {},
        )
    assert res["success"] is False, res
    assert res["result"] == {"driver_text_has_word": True}, res
    assert res["error"] == "OperationalError", res
    assert res["logs"] == ["Fehler: OperationalError"], res


def test_psycopg_error_of_a_hook_reports_its_type_only():
    # The same for psycopg used directly, whose errors are not SQLAlchemy's. A connection string
    # the driver cannot parse fails before any connection, and its text quotes the string.
    word = "hookcheckword"
    res = run_hook_script(
        "import psycopg\n"
        "try:\n"
        f"    psycopg.connect({word!r})\n"
        "except Exception as exc:\n"
        f"    result['driver_text_has_word'] = {word!r} in str(exc)\n"
        "    raise\n",
        "webhook",
        {},
    )
    assert res["success"] is False, res
    assert res["result"] == {"driver_text_has_word": True}, res
    assert res["error"] == "ProgrammingError", res
    assert res["logs"] == ["Fehler: ProgrammingError"], res


def test_other_error_of_a_hook_keeps_its_text():
    res = run_hook_script("raise ValueError('payload has no field id')", "webhook", {})
    assert res["success"] is False, res
    assert res["error"] == "payload has no field id", res
    assert res["logs"] == ["Fehler: payload has no field id"], res


def test_worker_nonzero_exit_maps_to_error(monkeypatch):
    # 6.82(d): if the worker process dies with a non-zero code and no JSON on stdout, the runner
    # reports an error instead of crashing on the missing/undecodable output.
    res = run_hook_script("import os\nos._exit(3)", "webhook", {})
    assert res["success"] is False
    assert res["error"]


def test_popen_failure_does_not_leak_the_semaphore_permit(monkeypatch):
    # code-review-fixes T3 (B2): the permit was acquired before Popen, but the
    # try/finally releasing it only started after the reader threads were up. A
    # failing Popen (fork under memory pressure) lost the permit for good — after
    # _MAX_CONCURRENT_HOOKS such failures every hook returned the misleading
    # "Server ausgelastet" until the process restarted.
    import pytest

    from app.modules.hooks import script_runner

    def _boom(*a, **kw):
        raise OSError("Cannot allocate memory")

    monkeypatch.setattr(script_runner.subprocess, "Popen", _boom)
    for _ in range(script_runner._MAX_CONCURRENT_HOOKS + 2):
        with pytest.raises(OSError):
            run_hook_script("log('x')", "webhook", {})
    monkeypatch.undo()

    # The permit pool must be intact: a regular hook still runs.
    res = run_hook_script("log('x')", "webhook", {})
    assert res["success"] is True, res


def test_thread_start_failure_does_not_leak_the_semaphore_permit(monkeypatch):
    # Same unguarded window, second failure mode: Thread.start() raises
    # RuntimeError once the process cannot spawn more threads.
    import pytest

    from app.modules.hooks import script_runner

    def _boom(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(script_runner.threading.Thread, "start", _boom)
    for _ in range(script_runner._MAX_CONCURRENT_HOOKS + 2):
        with pytest.raises(RuntimeError):
            run_hook_script("log('x')", "webhook", {})
    monkeypatch.undo()

    res = run_hook_script("log('x')", "webhook", {})
    assert res["success"] is True, res
