# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Hook-Posture (Befund #4): die exec()-'Sandbox' war wirkungslos (admin-gated,
kein unauth-RCE). Fix = EHRLICHE Posture + Teil-Haertung:

- Das minimierte env entfernt ADMIN_PASSWORD/MONITOR_API_KEY/REDIS_URL aus dem
  Hook-Prozess (echte Reduktion des Secret-Footprints).
- ABER: Hooks sind vertrauenswuerdiger Admin-Code mit DB-Zugriff. SECRET_KEY
  (via app.core.config bzw. DATA_DIR/.secret_key) und DB-Creds (DATABASE_URL)
  bleiben fuer einen Hook erreichbar. Das wird hier BEWUSST mit-getestet, damit
  keine falsche Schutz-Behauptung entsteht (genau der Fehler, den der alte
  Pseudo-Sandbox-Code gemacht hat).
"""

from app.modules.hooks.script_runner import run_hook_script


def test_admin_password_not_inherited_by_worker():
    # ADMIN_PASSWORD ist env-only (nicht datei-/config-persistiert) -> die
    # env-Minimierung entfernt es WIRKLICH aus dem Hook-Prozess.
    res = run_hook_script(
        "import os\nlog(os.environ.get('ADMIN_PASSWORD', '__ABSENT__'))",
        "webhook",
        {},
    )
    assert res["success"] is True, res
    assert res["logs"] == ["__ABSENT__"], res["logs"]


def test_admin_password_not_reachable_in_process():
    # Gegenprobe zur Ehrlichkeit: ADMIN_PASSWORD ist auch in-process nicht
    # rekonstruierbar (config liest es nur aus dem env -> leer im Worker).
    res = run_hook_script(
        "import app.core.config as c\nlog(c.ADMIN_PASSWORD or '__EMPTY__')",
        "webhook",
        {},
    )
    assert res["success"] is True, res
    assert res["logs"] == ["__EMPTY__"], res["logs"]


def test_secret_key_reachable_in_process_BY_DESIGN():
    # EHRLICHKEITS-ANKER: ein trusted Hook KANN den SECRET_KEY lesen (der Worker
    # importiert beim Start app.core.config, das SECRET_KEY aus DATA_DIR/.secret_key
    # aufloest). Das minimierte env schuetzt SECRET_KEY NICHT. Wer das jemals zu
    # echter Isolation aendert, MUSS diesen Test bewusst anpassen — er verhindert,
    # dass jemand faelschlich 'SECRET_KEY ist isoliert' behauptet.
    res = run_hook_script(
        "import app.core.config as c\nlog('present' if c.SECRET_KEY else 'absent')",
        "webhook",
        {},
    )
    assert res["success"] is True, res
    assert res["logs"] == ["present"], res["logs"]


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
