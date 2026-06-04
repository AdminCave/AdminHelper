# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hook-Posture (Befund #4): die exec()-'Sandbox' war wirkungslos (admin-gated,
kein unauth-RCE). Fix = ehrliche Posture + Haertung:
- Secrets werden dem Hook-Subprozess NICHT vererbt (minimiertes env).
- Hooks sind vertrauenswuerdiger Admin-Code mit vollen Builtins (Import erlaubt).

Diese Tests verankern beide Eigenschaften. test_secret_*_not_inherited schlaegt
ohne die env-Minimierung fehl (Secret wuerde vom Hauptprozess geerbt).
"""

from app.modules.hooks.script_runner import run_hook_script


def test_secret_key_not_inherited_by_worker():
    res = run_hook_script(
        "import os\nlog(os.environ.get('SECRET_KEY', '__ABSENT__'))",
        "webhook",
        {},
    )
    assert res["success"] is True, res
    assert res["logs"] == ["__ABSENT__"], res["logs"]


def test_admin_password_not_inherited_by_worker():
    res = run_hook_script(
        "import os\nlog(os.environ.get('ADMIN_PASSWORD', '__ABSENT__'))",
        "webhook",
        {},
    )
    assert res["success"] is True, res
    assert res["logs"] == ["__ABSENT__"], res["logs"]


def test_full_builtins_imports_work():
    # Bewusste Posture: Hooks sind trusted code und duerfen importieren.
    res = run_hook_script("import json\nlog(json.dumps({'ok': True}))", "webhook", {})
    assert res["success"] is True, res
    assert res["logs"] == ['{"ok": true}'], res["logs"]


def test_legit_hook_api_still_works():
    # Entfernen der Builtin-Whitelist darf legitime Hooks nicht brechen.
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
