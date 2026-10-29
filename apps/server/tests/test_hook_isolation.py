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
import pathlib
import signal
import stat
import time

from app.core import config
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
    # is bounded and the process group is killed to close the inherited pipe. The grandchild
    # (sleep 30) far outlives the bounded join.
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


# R-0778: the script backgrounds `sleep 40`, which inherits the worker's stdout and stderr and
# outlives the worker, and writes its PID so the test can end it: in a session of its own it
# survives the runner's killpg.
_SLEEP_CMDLINE = b"sleep\x0040\x00"


def _background_sleep_script(pid_file, new_session):
    return (
        "import subprocess\n"
        "from pathlib import Path\n"
        f"proc = subprocess.Popen(['sleep', '40'], start_new_session={new_session})\n"
        f"Path({str(pid_file)!r}).write_text(str(proc.pid))\n"
        "result['ok'] = True\n"
    )


def _kill_background_sleep(pid_file):
    # Only the sleep the script started: once it is gone, its PID may belong to another process.
    try:
        pid = int(pid_file.read_text())
        with open(f"/proc/{pid}/cmdline", "rb") as cmdline:
            if cmdline.read() != _SLEEP_CMDLINE:
                return
        os.kill(pid, signal.SIGKILL)
    except (FileNotFoundError, ProcessLookupError):
        pass


def test_hook_run_with_a_background_process_in_its_own_session_ends_soon(tmp_path):
    # The killpg after the first grace does not reach a process in its own session, so the
    # readers stay blocked; the runner gives up after the second grace instead of after twice
    # the timeout per reader.
    pid_file = tmp_path / "sleep.pid"
    start = time.monotonic()
    try:
        run_hook_script(_background_sleep_script(pid_file, True), "webhook", {}, timeout=5)
        elapsed = time.monotonic() - start
    finally:
        _kill_background_sleep(pid_file)
    assert elapsed < 10, f"run waited for a background process in its own session: {elapsed:.1f}s"


def test_hook_run_with_a_background_process_ends_soon_with_the_result(tmp_path):
    # In the worker's process group the killpg after the first grace ends the background process,
    # the pipe closes and the runner still gets the worker's output.
    pid_file = tmp_path / "sleep.pid"
    start = time.monotonic()
    try:
        res = run_hook_script(_background_sleep_script(pid_file, False), "webhook", {}, timeout=5)
        elapsed = time.monotonic() - start
    finally:
        _kill_background_sleep(pid_file)
    assert elapsed < 8, f"run waited for a background process: {elapsed:.1f}s"
    assert res["success"] is True, res
    assert res["result"] == {"ok": True}, res


def test_hook_run_keeps_the_result_a_background_process_in_its_own_session_holds_open(tmp_path):
    # R-0846: the worker has written its result before it exits; the background process keeps the
    # pipe open past both graces, and the runner still evaluates what it read until then.
    pid_file = tmp_path / "sleep.pid"
    try:
        res = run_hook_script(_background_sleep_script(pid_file, True), "webhook", {}, timeout=5)
    finally:
        _kill_background_sleep(pid_file)
    assert res["success"] is True, res
    assert res["result"] == {"ok": True}, res


def test_hook_reader_grace_is_one_deadline_for_both_streams(monkeypatch):
    # A grandchild holds stdout and stderr open past the worker's exit. Both readers share one
    # grace: the second join gets what is left of it, so the held run takes one grace longer
    # than a plain run, not two. Measured against a plain run, as a worker's start time varies.
    import time

    import app.modules.hooks.script_runner as sr

    def timed(script):
        start = time.monotonic()
        run_hook_script(script, "webhook", {}, timeout=5)
        return time.monotonic() - start

    grace = 1.0
    monkeypatch.setattr(sr, "_READER_GRACE_SECONDS", grace)
    timed("result['ok'] = True")  # warm-up: the first worker start is the slow one
    plain = timed("result['ok'] = True")
    held = timed("import subprocess\nsubprocess.Popen(['sleep', '30'])\nresult['ok'] = True")
    extra = held - plain
    assert 0.8 * grace <= extra < 1.6 * grace, f"expected one grace, took {extra:.1f}s longer"


def test_hook_run_at_the_default_timeout_ends_before_the_gateway_gives_up():
    # The gateway closes /api/... after 60 s without a response (nginx's default
    # proxy_read_timeout; apps/gateway/nginx.conf sets none for it), and /api/hooks/trigger and
    # /api/hooks/{id}/run answer only after the run, which takes at most the timeout plus one
    # reader grace before and one after the killpg.
    import app.modules.hooks.script_runner as sr

    assert sr.SCRIPT_TIMEOUT_SECONDS + 2 * sr._READER_GRACE_SECONDS < 60


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


def test_hook_worker_env_falls_back_for_home_and_lang(monkeypatch, tmp_path):
    # docs/developer/hooks.html: HOME falls back to a private directory under DATA_DIR and LANG to
    # C.UTF-8 when the server has neither.
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    _unset_server_env(monkeypatch, "HOME", "LANG")
    assert _worker_env("HOME", "LANG") == {"HOME": str(tmp_path / "hooks-home"), "LANG": "C.UTF-8"}


def test_hook_home_fallback_is_created_0700(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    _unset_server_env(monkeypatch, "HOME")
    previous = os.umask(0)
    try:
        assert _worker_env("HOME") == {"HOME": str(tmp_path / "hooks-home")}
    finally:
        os.umask(previous)
    home = tmp_path / "hooks-home"
    assert home.is_dir()
    assert stat.S_IMODE(home.stat().st_mode) == 0o700


def test_hook_home_fallback_with_wider_rights_is_narrowed_to_0700(monkeypatch, tmp_path):
    home = tmp_path / "hooks-home"
    home.mkdir()
    home.chmod(0o777)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    _unset_server_env(monkeypatch, "HOME")
    assert _worker_env("HOME") == {"HOME": str(home)}
    assert stat.S_IMODE(home.stat().st_mode) == 0o700


def test_hook_home_fallback_that_is_not_a_directory_fails_the_run(monkeypatch, tmp_path, caplog):
    # The caller sees the exception type only; the path is in the server log.
    (tmp_path / "hooks-home").write_text("")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    _unset_server_env(monkeypatch, "HOME")
    res = run_hook_script("result['ok'] = True", "webhook", {})
    assert res["success"] is False, res
    assert res["error"] == "Hook HOME unusable: FileExistsError", res
    assert str(tmp_path) not in repr(res)
    assert str(tmp_path / "hooks-home") in caplog.text


def test_a_relative_data_dir_gives_an_absolute_hook_home(monkeypatch, tmp_path):
    # The worker runs with cwd=server_dir, so a relative HOME would point elsewhere.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", pathlib.Path("data"))
    (tmp_path / "data").mkdir()
    _unset_server_env(monkeypatch, "HOME")
    assert _worker_env("HOME") == {"HOME": str(tmp_path.resolve() / "data" / "hooks-home")}


def test_server_home_is_passed_through_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("HOME", "/srv/somewhere")
    assert _worker_env("HOME") == {"HOME": "/srv/somewhere"}
    assert not (tmp_path / "hooks-home").exists()


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


def test_hook_worker_is_started_with_the_no_user_site_flag(monkeypatch):
    # -s on its own, so the env var is not the only thing keeping the user site out.
    import subprocess

    import app.modules.hooks.script_runner as sr

    argvs = []
    real_popen = subprocess.Popen

    def recording_popen(args, *a, **kw):
        argvs.append(args)
        return real_popen(args, *a, **kw)

    monkeypatch.setattr(sr.subprocess, "Popen", recording_popen)
    res = run_hook_script("result['ok'] = True", "webhook", {})
    assert res["success"] is True, res
    [argv] = argvs
    assert argv[1] == "-s", argv


def test_hook_worker_env_sets_pythonnousersite():
    assert _worker_env("PYTHONNOUSERSITE") == {"PYTHONNOUSERSITE": "1"}


def test_hook_worker_runs_without_user_site_on_the_home_fallback(monkeypatch, tmp_path):
    # The fallback case: the user site would sit under the fallback HOME.
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    _unset_server_env(monkeypatch, "HOME")
    flags = _no_user_site_flags()
    assert flags == {"HOME": str(tmp_path / "hooks-home"), "worker": "1", "child": "1"}, flags


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
