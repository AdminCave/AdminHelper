<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server-CLI reset-admin meldet bestehende Sitzungen ab — Task-Ledger
Status: geplant · Branch: feature/cli-reset-sessions · Review: am Ende
Spec: keine eigene Datei (kleines Härtungs-Paket, Reihenfolge Kevin 2026-10-16)
Heavy: linux-full — `apps/server/app/cli.py` ist der Bootstrap- und Recovery-Weg (`scripts/install.sh`, `docs/admin/troubleshooting.html`); läuft im Sammellauf über `main` (`/feature-build` §5)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben: main@b2091886.

### T1 — `reset-admin` setzt die Token-Grenze wie der Passwortwechsel über die API  [ ]
Komponente: server · Dateien: apps/server/app/cli.py, apps/server/tests/test_cli.py, CHANGELOG.md, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html
Änderung: `reset_admin` (`cli.py:80`) setzt neben dem neuen Passwort-Hash (`:92`) auch `user.tokens_valid_after = utcnow_naive()`, wie `update_user` beim Passwortwechsel (`users/router.py:112`); die Token-Prüfung in `core/auth.py:103` weist damit Tokens ab, die vor dem Reset ausgestellt wurden. Test in `test_cli.py` neben `test_reset_admin_updates_password` (`:90`): ein vor dem Reset ausgestelltes Token des Benutzers wird danach von der Token-Prüfung abgewiesen, ein danach ausgestelltes gilt. CHANGELOG (`### Changed`) und `troubleshooting` DE (`:59`) und EN: ein Satz, dass der Reset die bestehenden Sitzungen des Benutzers abmeldet.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_cli.py
Doku: CHANGELOG.md (Changed) · docs/admin/troubleshooting.html + docs/en/admin/troubleshooting.html (DE+EN)
