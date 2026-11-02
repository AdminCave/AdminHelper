<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-5 — Task-Ledger
Status: geplant · Branch: feature/ops-5 · Review: pro Task
Spec: docs/features/ops-5.md (Roadmap R-1017, R-1028, R-1002, R-1003, R-1027, R-1008)
Heavy: linux-full — `scripts/update.sh`, `scripts/install.sh`, `scripts/restore.sh` und `scripts/backup.sh` im Diff: der Sammellauf über `main` fährt `upgrade-path` und `backup-restore`. Kein `scenario`: kein Cross-Host-, Agent- oder PKI-Pfad. Kein `windows`.
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zeilenangaben `origin/main@f03bbf14`, vor dem Bauen neu greppen. Neue Meldungen englisch, CHANGELOG umlautfrei.
Der PR ändert `scripts/update.sh`, `scripts/install.sh` und `scripts/agent-install.sh`: Kevin merged. `security` bei
T1, T2, T4, T5. T2 neutral: Titel, Commit, Doku und `changelog.d/ops-5.md` ohne Angriffspfad.

### T1 — backup.sh: Passphrase-Filter lässt den Quote eines anderen Schlüssels stehen (R-1017)  [ ]
Komponente: scripts · Dateien: scripts/backup.sh, scripts/diagnostics.sh, scripts/tests/restore_guard_test.sh, scripts/tests/diagnostics_test.sh, changelog.d/ops-5.md
Beweis: `.env` mit `A="x 'CA_ROOT_PASSPHRASE=geheim"` und `B=1` durch den Filter (`scripts/backup.sh:254-287`) → `env.sanitized` `A="x '` / `B=1`, der Quote von `A` bleibt offen (Probe 2026-11-02 auf `origin/main@f03bbf14`) · Dedup-Key: ref:scripts:backup.sh:filter-cuts-closing-quote
Änderung: Ein Treffer, den der Filter nur hinter einem Quote liest und der im geschlossenen Wert eines anderen Schlüssels liegt (wie compose ihn liest), endet vor dessen schließendem Quote; die Passphrase geht weiter in jeder Form, die Tests 15–19 prüfen. Ändert das den gemeinsamen Tokenizer-Text, zieht `diagnostics.sh` byte-gleich mit (Test (r)). Test (erst rot) in `restore_guard_test.sh`: obige `.env` → `A="x '"` oder ohne den Wertrest, aber mit geschlossenem Quote, `B=1` unverändert, kein Byte von `geheim`.
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test diagnostics_test
Doku: changelog.d/ops-5.md

### T2 — restore.sh: übernommene .env nur mit Schlüsseln der Anwendung, Images vor der Rückfrage (R-1028)  [ ]
Komponente: scripts · Dateien: scripts/restore.sh, scripts/tests/restore_guard_test.sh, scripts/tests/diagnostics_test.sh, docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/ops-5.md
Beweis: siehe `tasks/private/` (R-1028, Beleg `backup_restore_test` 2026-10-31) · Refuter: security install-restore T6 2026-10-31 · Dedup-Key: siehe Roadmap R-1028
Änderung: Neutral nach Roadmap-Zeile R-1028: beim Bau von `env.new` (`scripts/restore.sh:57-59`) mit einer dritten, markierten Kopie des Tokenizer-Texts (Test (r) hält alle drei gleich); vor „Fortfahren?“ nennt `restore.sh` bei `FRESH=1` die Image-Werte der übernommenen `.env`. Externe Doku (Compose-Umgebungsvariablen) vor dem Bau lesen. Tests (erst rot) in `restore_guard_test.sh` nach der Zeile; `compose_names --env-file` sieht nur die bereinigte Datei.
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test diagnostics_test
Doku: docs/admin/betrieb.html:107 + docs/en/admin/operations.html:74 (frischer Host: übernommen werden die Schlüssel der Anwendung, Images vor der Rückfrage) · changelog.d/ops-5.md (neutral)
Abhängt von: T1

### T3 — init-secrets.sh: Schlüssel lesen und ersetzen wie Compose (R-1002)  [ ]
Komponente: scripts · Dateien: scripts/init-secrets.sh, scripts/tests/init-secrets_test.sh, changelog.d/ops-5.md
Beweis: Code-Lesung `scripts/init-secrets.sh:41` (`grep -E "^${var}="`) und `:72` (`^#?[[:space:]]*${key}=`); `.env` mit `export POSTGRES_PASSWORD=alt` → zweite Zeile `POSTGRES_PASSWORD=<neu>` · Dedup-Key: bug:scripts:init-secrets.sh:env-read-not-like-compose
Änderung: `is_set_safely` erkennt `KEY` in jeder Form, die Compose liest (`^[[:space:]]*(export[[:space:]]+)?KEY[[:space:]]*[=:]`, wie `migrate_env` in `update.sh`), und liest den Wert danach; `upsert` entfernt dieselben Formen (und die auskommentierte) vor dem Anhängen. Tests (erst rot): `export POSTGRES_PASSWORD=alt`, `POSTGRES_PASSWORD = alt` und `POSTGRES_PASSWORD: alt` bleiben unverändert und einzig; ein leeres `export SECRET_KEY=` wird ersetzt, ohne zweite Zeile.
Verify: bash scripts/dev/verify.sh scripts --strict -- init-secrets_test
Doku: changelog.d/ops-5.md

### T4 — update.sh: Schreibfehler ohne Terminal wie getrennte Sitzung (R-1003)  [ ]
Komponente: scripts · Dateien: scripts/update.sh, scripts/tests/update_test.sh, docs/admin/installation.html, docs/en/admin/installation.html, changelog.d/ops-5.md
Beweis: Code-Lesung `scripts/update.sh:74-75` (`log`/`die` schreiben auf stderr ohne Fehlerbehandlung), `:655-690` (nur INT/TERM/HUP haben Traps); Test (erst rot): `update.sh` mit stdout/stderr in eine Pipe, deren Leser während des Tauschs endet → heute Ende ohne Rollback und ohne `backups/update-*.log` · Dedup-Key: bug:ops:update.sh:no-tty-sigpipe
Änderung: SIGPIPE wird ignoriert. Scheitert ein Schreiben auf stdout/stderr, geht die Ausgabe in `backups/update-<zeit>.log` (`hup_to_log`), und ab dem Tausch läuft das Skript wie nach SIGHUP in den Rollback; davor endet es ohne Änderung, die Meldung im Log. Tests (erst rot): Leser endet während des Pulls → zurückgerollt, 0600-Log mit „interrupted“; Leser endet vor dem Tausch → nichts geändert, Log vorhanden.
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test
Doku: docs/admin/installation.html:227 + docs/en/admin/installation.html:180 (getrennte Sitzung auch ohne Terminal) · changelog.d/ops-5.md

### T5 — install.sh: vorhandene .env vor dem ersten Compose-Aufruf prüfen (R-1027)  [ ]
Komponente: scripts · Dateien: scripts/install.sh, scripts/update.sh, scripts/tests/install_test.sh, docs/admin/installation.html, docs/en/admin/installation.html, changelog.d/ops-5.md
Beweis: Code-Lesung `scripts/install.sh:262-263` (`cat "$err"` der Compose-Ausgabe) und `:414`; `install_test.sh` mit vorab geschriebener `.env`, deren Zeile `GEHEIM-WERT` ohne `=` hält, und einem Compose-Stub, der sie wie Compose zitiert → heute erscheint `GEHEIM-WERT` auf stderr · Dedup-Key: BUG:scripts:install.sh:compose_stderr
Änderung: `check_env_templates` und seine Helfer (`scripts/update.sh:82-247`) stehen als markierter Block (`# >>> env check` … `# <<< env check`) byte-gleich in `install.sh`; `install.sh` ruft die Prüfung vor `install_state`, wenn eine `.env` da ist. Ein Test in `install_test.sh` hält beide Blöcke gleich. Tests (erst rot): obige `.env` → Abbruch mit Zeilennummer, kein Byte des Werts, Compose-Stub nicht aufgerufen; gültige vorab geschriebene `.env` → Lauf wie bisher.
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test update_test
Doku: docs/admin/installation.html + EN (install prüft eine vorhandene `.env` wie update) · changelog.d/ops-5.md

### T6 — agent-install.sh: Einzeiler im Kopf ohne Token auf der Kommandozeile (R-1008)  [ ]
Komponente: scripts · Dateien: scripts/agent-install.sh
Änderung: Der Einzeiler im Kopfkommentar (`scripts/agent-install.sh:9-11`) lässt `--token` weg und sagt, dass das Skript den Token dann verdeckt über `/dev/tty` abfragt; `--token` bleibt für unbeaufsichtigte Rollouts genannt (wie `docs/admin/agent-deployment.html:51`).
Verify: bash scripts/dev/verify.sh scripts --strict -- agent_install_test
Doku: keine (Kommentar; die Doku beschreibt den Weg schon)
