<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-3 — Task-Ledger
Status: aktiv · Branch: feature/ops-3 · Review: pro Task
Spec: docs/features/ops-3.md (Roadmap R-0859, R-0862, R-0896, R-0865, R-0986, R-0956, R-0987)
Heavy: linux-full — `scripts/update.sh` im Diff: der Sammellauf über `main` fährt `upgrade-path`
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@7364679e`, vor dem Bauen neu greppen. Neue Meldungen englisch, CHANGELOG umlautfrei.
Der PR ändert `scripts/update.sh`: Kevin merged. `security` bei T1.

### T1 — .env-Prüfung: englische Meldungen mit Zeilennummer (R-0862, R-0865)  [x]
Komponente: scripts · Dateien: scripts/update.sh, scripts/tests/update_test.sh, changelog.d/ops-3.md, docs/admin/installation.html, docs/en/admin/installation.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @01e60447 2026-10-30T12:23:02+01:00
Review: approve (.ah-out/review/ops-3/T1.verdict.json)
Änderung: Die `die`-Meldungen von `check_env_templates` (`scripts/update.sh:194-247`) werden englisch und nennen die Zeile der `.env` statt des Schlüssels. Die Fälle in `update_test.sh`, die die Texte prüfen, ziehen mit; ein neuer Fall belegt, dass die Meldung keinen Text aus der Zeile enthält.
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test
Doku: changelog.d/ops-3.md (neutral), docs/admin/installation.html + EN (Updates)

### T2 — migrate_env: auskommentierter Schlüssel zählt nicht (R-0896)  [x]
Komponente: scripts · Dateien: scripts/update.sh, scripts/tests/update_test.sh, changelog.d/ops-3.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @c64ef833 2026-10-30T12:46:20+01:00
Review: approve (.ah-out/review/ops-3/T2.verdict.json)
Beweis: Code-Lesung `scripts/update.sh:684` (`grep -qE "^#?[[:space:]]*${key}="`); `.env.example:93-95` verlangt die aktive Zeile · Dedup-Key: bug:scripts:update.sh:migrate-env-commented-key
Änderung: `migrate_env` zählt nur aktive Zeilen (wie Compose sie liest) als vorhanden und hängt einen nur auskommentierten Schlüssel aus `.env.example` an. Der Kommentar im Rollback (`:729-730`) beschreibt `CA_ROOT_PASSPHRASE` richtig. Test (erst rot): `.env` mit `# CA_ROOT_PASSPHRASE=` → nach dem Update steht eine aktive Zeile `CA_ROOT_PASSPHRASE=`.
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test
Doku: changelog.d/ops-3.md

### T3 — Rollback: Signale während der Rücknahme, Text mit --no-rollback (R-0986, R-0956)  [x]
Komponente: scripts · Dateien: scripts/update.sh, scripts/tests/update_test.sh, changelog.d/ops-3.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @89e12f14 2026-10-30T13:20:18+01:00
Review: approve (.ah-out/review/ops-3/T3.verdict.json)
Beweis: Code-Lesung `scripts/update.sh:650-665` (nur `on_signal` setzt `trap '' INT TERM HUP`), `rollback_before_deploy` `:592`, `rollback_after_deploy` `:709` · Dedup-Key: bug:ops:update.sh:rollback_after_deploy-traps
Änderung: Beide Rollback-Funktionen ignorieren INT/TERM/HUP von ihrem Beginn an, gleich aus welchem Pfad sie kommen. Der Signalpfad mit `--no-rollback` nennt, was je nach Stand wirklich stehen bleibt (während des Tauschs, nach `pin_images`). Test (erst rot): ein Signal während eines Rollbacks aus einem Fehlerpfad bricht ihn nicht ab; der `--no-rollback`-Text nach `pin_images`.
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test
Doku: changelog.d/ops-3.md

### T4 — update_test: Rollback nach dem Start, migriert und unvollständig, Stopp scheitert (R-0987)  [x]
Komponente: scripts · Dateien: scripts/tests/update_test.sh, scripts/update.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @32c761a8 2026-10-30T13:30:24+01:00
Review: approve (.ah-out/review/ops-3/T4.verdict.json)
Änderung: Zwei Fälle zu Abschnitt 45 (`update_test.sh:1442`): Datenbank migriert und ein Restore-Schritt scheitert → Meldung „UNVOLLSTAENDIG“ mit Restore-Weg; `docker compose stop` scheitert → Migrationsstand unbestätigt, Stack-Stopp gemeldet.
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test
Doku: keine (nur Tests)
Abhängt von: T3

### T5 — Installations-Doku: Passwortdatei ohne Shell-History (R-0859)  [ ]
Komponente: scripts · Dateien: docs/admin/installation.html, docs/en/admin/installation.html
Änderung: Bei `--admin-password-file` (`installation.html:97`, EN `:78`) steht, wie man die Datei mit `umask 077` und `read -s` (oder einem Editor) anlegt und nach der Installation löscht.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/installation.html + EN
Task-Review: am Ende

## Entscheidungen
