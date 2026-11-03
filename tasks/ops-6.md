<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ops-6 — Task-Ledger
Status: aktiv · Branch: feature/ops-6 · Review: pro Task
Spec: docs/features/ops-6.md (Roadmap R-1051, R-1049, R-1057, R-1050, R-1048, R-1052, R-1047, R-1058, R-1045)
Heavy: linux-full — `scripts/install.sh`, `scripts/update.sh`, `scripts/backup.sh` und `scripts/restore.sh` im Diff: der Sammellauf über `main` fährt `upgrade-path` und `backup-restore`. Kein `scenario`: `agent-install.sh` ändert nur das Lesen der gpg-Ausgabe, das `agent_install_test` mit echtem gpg prüft. Kein `windows`.
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@e1944a88`. Der PR ändert `scripts/install.sh`, `scripts/update.sh` und `scripts/agent-install.sh`: Kevin merged.

### T1 — Compose-Fehlermeldungen in install.sh und update.sh vereinheitlichen (R-1051, R-1049)  [x]
Komponente: scripts · Dateien: scripts/install.sh, scripts/update.sh, scripts/tests/install_test.sh, scripts/tests/update_test.sh, changelog.d/ops-6.md, docs/admin/installation.html, docs/en/admin/installation.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @34328023 2026-11-03T14:26:39+01:00
Review: approve (.ah-out/review/ops-6/T1.verdict.json)
Änderung: Fehlermeldungen von `docker compose` gehen in beiden Skripten über einen gemeinsamen Weg im env-check-Block (gleicher Text in beiden, der bestehende Test hält ihn gleich); Kopfkommentar des Blocks auf Zeilenbreite umbrechen (R-1049). Tests für die Ausgabe. Details nur in `tasks/private/`.
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test update_test
Doku: docs/admin/installation.html + EN · changelog.d/ops-6.md

### T2 — install.sh prüft --admin-user vor dem Start (R-1057)  [x]
Komponente: scripts · Dateien: scripts/install.sh, scripts/tests/install_test.sh, changelog.d/ops-6.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @5b2652f6 2026-11-03T14:35:51+01:00
Review: approve (.ah-out/review/ops-6/T2.verdict.json)
Änderung: `--admin-user` wird beim Lesen der Argumente gegen `_USERNAME_PATTERN` und die Länge 3–64 geprüft (wie `apps/server/app/cli.py:55`); ein anderer Name endet mit Exit 2, bevor etwas geändert wird. Test für gültige und ungültige Namen.
Beweis: feature/kern-server-5@dca0432c apps/server/app/cli.py:54 + scripts/install.sh --admin-user · Dedup-Key: bug:scripts:install.sh:admin-user-unchecked
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test
Doku: changelog.d/ops-6.md

### T3 — update.sh: gescheitertes Backup-first englisch und getestet (R-1050)  [ ]
Komponente: scripts · Dateien: scripts/update.sh, scripts/tests/update_test.sh, changelog.d/ops-6.md
Änderung: Die Meldung beim gescheiterten Backup-first (`./scripts/backup.sh … | tee`) wird englisch; ein Test lässt `backup.sh` scheitern und prüft Abbruch ohne Änderung; die Job-Meldung in der `update_test`-Ausgabe verschwindet.
Beweis: feature/ops-5@787f9377 scripts/update.sh:549, scripts/tests/update_test.sh:1638 · Dedup-Key: BUG:scripts:update.sh:backup_tee_die
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test
Doku: changelog.d/ops-6.md

### T4 — backup.sh: Passphrase-Filter und Maskierung (R-1048, R-1052, R-1049)  [ ]
Komponente: scripts · Dateien: scripts/backup.sh, scripts/tests/restore_guard_test.sh, changelog.d/ops-6.md
Änderung: Der Filter behält das schließende Quote eines Werts auch auf einer Zeile, die wie ein Kommentar aussieht (R-1048); die Maskierung einer kaputten `.env` trifft nur den betroffenen Teil (R-1052); Kommentar am Filter umbrechen (R-1049). Tests je Fall, rot ohne Fix.
Beweis: feature/ops-5@7fe85795 scripts/backup.sh ENV_TOK-Filter · Dedup-Key: BUG:scripts:backup.sh:env_filter_comment_quote
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test
Doku: changelog.d/ops-6.md

### T5 — restore.sh liest die .env wie Compose (R-1047, R-1058)  [ ]
Komponente: scripts · Dateien: scripts/restore.sh, scripts/tests/restore_guard_test.sh, changelog.d/ops-6.md
Änderung: `role_password` liest den Schlüssel über `ENV_TOK` in jeder Form, die Compose nimmt, und die letzte Anweisung (R-1047); der Schnitt der Compose-Variablen nimmt die ES/EE-Erweiterung aus `backup.sh` auf, `compose_names` gibt `.compose-err` per `cat -v` aus (R-1058). Tests je Fall.
Beweis: feature/ops-5@7fe85795 scripts/restore.sh role_password; feature/ops-5@61afd157 scripts/restore.sh:231 :298 :305 · Dedup-Key: BUG:scripts:restore.sh:role_password, bug:scripts:restore.sh:cut-without-es-ee
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test
Doku: changelog.d/ops-6.md
Abhängt von: T4

### T6 — agent-install.sh: Schlüssel mit designiertem Widerrufer (R-1045)  [ ]
Komponente: scripts · Dateien: scripts/agent-install.sh, scripts/tests/agent_install_test.sh, changelog.d/ops-6.md
Änderung: `primary_fprs` nimmt den ersten `fpr` nach `pub` über `rvk` hinweg, nie über `sub`/`uid` hinaus. Test mit einem Wegwerf-Schlüssel mit Widerrufer (echtes gpg), rot ohne Fix.
Beweis: scripts/agent-install.sh:177, Nachstellung mit Wegwerf-Schluessel pub,rvk,fpr · Dedup-Key: bug:scripts:agent-install.sh:primary_fprs-rvk
Verify: bash scripts/dev/verify.sh scripts --strict -- agent_install_test
Doku: changelog.d/ops-6.md

## Entscheidungen
- T1 (2026-11-03): Die neue `$`-Regel lehnt nur ab, was Compose selbst bemaengelt (Warnung "variable is not set" oder Abbruch durch `?`), ausgewertet wie Compose: zuerst die Umgebung (gesetzt oder leer, vor jeder Zeile der Datei), dann frühere Keys; spätere und Keys ohne Wert gelten nicht, Default/Alternative/WORD nur, wo Compose sie auswertet. Ein Wert mit Template gilt für `:` als möglicherweise leer (vorsichtige Seite). Belegt mit Proben gegen echtes `docker compose config`; die erste Fassung prüfte die Umgebung nach den früheren Keys (Prüferfund, behoben, Differentialfälle mit Umgebung). Der Differentialtest 32 zählt die Warnung jetzt als Ablehnung. Eine Zeile mit leerem Key setzt keinen Namen.
