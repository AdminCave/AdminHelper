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

from app.modules.hooks.script_runner import run_hook_script


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
