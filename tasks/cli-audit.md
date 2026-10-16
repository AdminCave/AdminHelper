<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server-CLI schreibt Audit-Einträge — Task-Ledger
Status: bereit · Branch: feature/cli-audit · Review: am Ende
Spec: Roadmap R-0397
Heavy: linux-full — `apps/server/app/cli.py` ist der Bootstrap-Weg von `scripts/install.sh` (`create-admin`, `mint-enroll-token`, `install.sh:287-289`); Install läuft im Sammellauf
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-16: `/feature-plan --kurz R-0397`. Am Gate entschieden: Die CLI protokolliert als `Actor("system", None, "cli", None)`, also actor_type `system` mit dem Label `cli`. Kein neuer Actor-Typ, der Filter im Web-Panel (`Audit.svelte:95-100`) findet die Einträge unter `system`; Web und Modell bleiben unverändert. Nicht-Ziel: Webhooks und Benachrichtigungen (`fire_event`) für CLI-Aktionen.

### T1 — Die drei CLI-Befehle schreiben einen Audit-Eintrag  [x]
Komponente: server · Dateien: apps/server/app/cli.py, apps/server/tests/test_cli.py, CHANGELOG.md, docs/admin/betrieb.html, docs/en/admin/operations.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @b8f974cc 2026-10-16T11:42:23+02:00
Review: am Ende (Branch-Review)
Änderung: Eine Modul-Konstante `_CLI_ACTOR = Actor("system", None, "cli", None)`; jeder erfolgreiche Befehl ruft `audit.record` mit diesem Actor:
- `create_admin` (`cli.py:48`): `user.created`, wie der API-Weg (`users/router.py:86-93`), `object_type="user"`, `object_id`/`object_label` des neuen Benutzers, vor dem einen `db.commit()`, damit Benutzer und Eintrag gemeinsam landen.
- `reset_admin` (`cli.py:67`): `user.password_reset`, gleiche Objektfelder, ebenfalls vor dem `db.commit()`.
- `mint_enroll_token` (`cli.py:85`): `enrollment.token.minted_for` wie der API-Weg (`enrollment/router.py:112-119`), `object_type="user"`, `object_id` = Benutzername. Danach ein eigenes `db.commit()`, weil `mint_enrollment_token` selbst schon committet (`enrollment/service.py`).

Abgelehnte Aufrufe (zu kurzes Passwort, Benutzer existiert schon oder fehlt) schreiben keinen Eintrag. stdout bleibt unverändert: `install.sh:289` liest das Token von dort. Tests in `test_cli.py`: je Befehl genau ein `AuditLog` mit Action, `actor_type == "system"`, `actor_label == "cli"` und den Objektfeldern; je ein abgelehnter Aufruf ohne Eintrag. Doku: Der Audit-Absatz in `docs/admin/betrieb.html:127` und `docs/en/admin/operations.html:87` nennt als Actor bisher nur „Benutzer oder API-Key“; er bekommt einen Halbsatz, dass Aktionen der Server-CLI als `system` mit Label `cli` erscheinen. CHANGELOG unter `### Fixed`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_cli.py
Doku: docs/admin/betrieb.html + docs/en/admin/operations.html (Audit-Absatz) · CHANGELOG.md (Fixed)
Beweis: main@aa7decf6 · `grep -c audit apps/server/app/cli.py` → `0`; der API-Weg desselben Vorgangs schreibt `enrollment.token.minted_for` (`enrollment/router.py:114`) bzw. `user.created` (`users/router.py:88`). Ein Test, der nach `create_admin`, `reset_admin` oder `mint_enroll_token` einen `AuditLog`-Eintrag erwartet, ist auf HEAD rot.
Orakel: contract — dieselbe Aktion schreibt auf API- und CLI-Weg einen Audit-Eintrag
Dedup-Key: bug:server:cli.py:no-audit
HEAD: aa7decf6
Semantik: docs/admin/betrieb.html:127 — „Sicherheits- und änderungsrelevante Aktionen werden in einem <strong>append-only Audit-Trail</strong> protokolliert — mit Actor (Benutzer oder API-Key), Quell-IP und Zeitstempel. Erfasst werden u.&nbsp;a. das Anlegen/Ändern/Löschen und die Nutzung von Verbindungen, Änderungen an Servern/Benutzern/API-Keys/FRP/Ansible sowie Logins (Erfolg/Fehlschlag), ein Logout, der eine Sitzung beendet, und der Erst-Admin-Bootstrap.“ (EN `docs/en/admin/operations.html:87`)
