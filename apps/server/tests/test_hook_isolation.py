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
