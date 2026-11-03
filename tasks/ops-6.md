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

### T3 — update.sh: gescheitertes Backup-first englisch und getestet (R-1050)  [x]
Komponente: scripts · Dateien: scripts/update.sh, scripts/tests/update_test.sh, changelog.d/ops-6.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @9030ce86 2026-11-03T14:55:06+01:00
Review: approve (.ah-out/review/ops-6/T3.verdict.json)
Änderung: Die Meldung beim gescheiterten Backup-first (`./scripts/backup.sh … | tee`) wird englisch; ein Test lässt `backup.sh` scheitern und prüft Abbruch ohne Änderung; die Job-Meldung in der `update_test`-Ausgabe verschwindet.
Beweis: feature/ops-5@787f9377 scripts/update.sh:549, scripts/tests/update_test.sh:1638 · Dedup-Key: BUG:scripts:update.sh:backup_tee_die
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test
Doku: changelog.d/ops-6.md

### T4 — backup.sh: Passphrase-Filter und Maskierung (R-1048, R-1052, R-1049)  [x]
Komponente: scripts · Dateien: scripts/backup.sh, scripts/tests/restore_guard_test.sh, changelog.d/ops-6.md, scripts/diagnostics.sh, scripts/restore.sh, docs/features/ops-6.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @6253eb7e 2026-11-03T16:27:14+01:00
Review: approve (.ah-out/review/ops-6/T4.verdict.json)
Änderung: Der Filter behält das schließende Quote eines Werts auch auf einer Zeile, die wie ein Kommentar aussieht (R-1048); in einer `.env`, die Compose ablehnt, bleibt kein Quote aus der Passphrase stehen (R-1052); Kommentar am Filter umbrechen (R-1049). Tests je Fall, rot ohne Fix.
Beweis: feature/ops-5@7fe85795 scripts/backup.sh ENV_TOK-Filter · Dedup-Key: BUG:scripts:backup.sh:env_filter_comment_quote
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test diagnostics_test
Doku: changelog.d/ops-6.md

### T5 — restore.sh liest die .env wie Compose (R-1047, R-1058)  [x]
Komponente: scripts · Dateien: scripts/restore.sh, scripts/tests/restore_guard_test.sh, changelog.d/ops-6.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @8bc338d9 2026-11-03T16:43:21+01:00
Review: approve (.ah-out/review/ops-6/T5.verdict.json)
Änderung: `role_password` liest den Schlüssel über `ENV_TOK` in jeder Form, die Compose nimmt, und die letzte Anweisung (R-1047); der Schnitt der Compose-Variablen nimmt die ES/EE-Erweiterung aus `backup.sh` auf, `compose_names` gibt `.compose-err` per `cat -v` aus (R-1058). Tests je Fall.
Beweis: feature/ops-5@7fe85795 scripts/restore.sh role_password; feature/ops-5@61afd157 scripts/restore.sh:231 :298 :305 · Dedup-Key: BUG:scripts:restore.sh:role_password, bug:scripts:restore.sh:cut-without-es-ee
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test
Doku: changelog.d/ops-6.md
Abhängt von: T4

### T6 — agent-install.sh: Schlüssel mit designiertem Widerrufer (R-1045)  [x]
Komponente: scripts · Dateien: scripts/agent-install.sh, scripts/tests/agent_install_test.sh, changelog.d/ops-6.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @418ddb33 2026-11-03T16:19:48+01:00
Review: approve (.ah-out/review/ops-6/T6.verdict.json)
Änderung: `primary_fprs` nimmt den ersten `fpr` nach `pub` über `rvk` hinweg, nie über `sub`/`uid` hinaus. Test mit einem Wegwerf-Schlüssel mit Widerrufer (echtes gpg), rot ohne Fix.
Beweis: scripts/agent-install.sh:177, Nachstellung mit Wegwerf-Schluessel pub,rvk,fpr · Dedup-Key: bug:scripts:agent-install.sh:primary_fprs-rvk
Verify: bash scripts/dev/verify.sh scripts --strict -- agent_install_test
Doku: changelog.d/ops-6.md

### T7 — update_test: Differentialtest unabhaengig von der Compose-Version (R-1051)  [ ]
Komponente: scripts · Dateien: scripts/tests/update_test.sh
Änderung: Test 32 zählt die Warnung „variable is not set“ als Nein von Compose; Compose 2.38.2 (CI-Runner) warnt auch für einen Namen in einem Zweig, den es nicht auswertet (`${ZZ:+$YY}` bei leerem ZZ), v5.6.1 (Dev-Box) nicht, der Wert ist in beiden gleich. Für diese Zeilen zählt nur der Exit von Compose; das Verhalten von update.sh bleibt.
Beweis: PR #384 CI-Lauf 41669842976, Job „Ops scripts“: fünf FAIL in Test 32 (`ab${ZZ:+$YY}`, `ab${zz9q+$zz9r}`, `ab${DOMAIN:-$zz9r}`, `ab${DOMAIN:?$zz9r}`, `E=` + `${E:+$zz9r}`)
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test
Doku: keine (nur Test)

## Entscheidungen
- T1 (2026-11-03): Die neue `$`-Regel lehnt nur ab, was Compose selbst bemaengelt (Warnung "variable is not set" oder Abbruch durch `?`), ausgewertet wie Compose: zuerst die Umgebung (gesetzt oder leer, vor jeder Zeile der Datei), dann frühere Keys; spätere und Keys ohne Wert gelten nicht, Default/Alternative/WORD nur, wo Compose sie auswertet. Ein Wert mit Template gilt für `:` als möglicherweise leer (vorsichtige Seite). Belegt mit Proben gegen echtes `docker compose config`; die erste Fassung prüfte die Umgebung nach den früheren Keys (Prüferfund, behoben, Differentialfälle mit Umgebung). Der Differentialtest 32 zählt die Warnung jetzt als Ablehnung. Eine Zeile mit leerem Key setzt keinen Namen.
- T3 (2026-11-03): Die Jobmeldung „Aufgelegt“ kam von `wait` in `reader_ends_update` (update_test.sh) und ist mit `{ wait; } 2>/dev/null` weg. Die Zeile „│ Aufgelegt“ in der eingerückten Ausgabe von Test 44b bleibt: sie gehört zur Ausgabe von update.sh selbst (bash meldet den per SIGHUP beendeten Pull), die der Test absichtlich zeigt.
- T4 (2026-11-03): R-1048 stand schon auf `main` behoben (61afd157 aus ops-5, Test 15f in `restore_guard_test`; der Fall aus dem Fund ergibt `B="x`, `"`, `F=6`); T4 baut dafür nichts nach. R-1052: liest `tok_exact` eine Zeile, die Compose ablehnt (`tbad`), behält der Filter kein schließendes Quote mehr, die Anweisung geht ganz (Test 15h, rot ohne Fix). `tbad` steht im geteilten Tokenizer, daher auch in `diagnostics.sh` und `restore.sh` (der Gleichheitstest in `diagnostics_test`). Prüferfund: eine Zeile mit leerem Key (`=abc`, `export =1`) nimmt Compose an (Probe rc 0, `bad key=1` rc 1), sie setzt `tbad` daher nicht (Test 15i, rot ohne Fix). security-Fund Runde 2: Compose liest auch den Wert eines leeren Keys ganz, ein gequoteter läuft bis zu seinem schließenden Quote über Zeilen; `tok_exact` liest ihn jetzt wie jeden anderen Wert (Test 15j, rot ohne Fix). Er löst auch `hit` aus: ohne bliebe das schließende Quote seines Werts nicht stehen (Test 15k, rot in der Variante ohne `hit`; `want` liefert für den leeren Key in `diagnostics.sh` und `restore.sh` außerhalb von `ex` nichts). Die Spec-Zeile zu R-1052 ist neutral gefasst, Details in `tasks/private/`. Kevin 2026-11-03: dritte Prüfrunde für T4 zugelassen.
- T5 (2026-11-03): `role_password` liest den Wert ueber `ENV_TOK` wie Compose (letzte Anweisung; ungequotet bis `" #"` ohne Leerraum am Ende, gequotet zwischen den Quotes). Was Compose expandieren oder umdeuten wuerde (`$` ausserhalb einfacher Quotes, Backslash in Quotes) oder nicht lesen kann (offenes Quote, Zeilenumbruch), bricht den Restore mit dem Namen des Schluessels ab, nie mit dem Wert: Expansion und Escapes nachzubauen waere Ueberreichweite. Eine nicht leere Umgebungsvariable hat weiter Vorrang (`${!1:-}`), unveraendert. Der Schnitt der Compose-Variablen nimmt die ES/EE-Erweiterung aus `backup.sh` (Test 27m), `.compose-err` geht per `cat -v` aus (Test 28). Gegenprobe: die sechs neuen Tests rot gegen HEAD.
