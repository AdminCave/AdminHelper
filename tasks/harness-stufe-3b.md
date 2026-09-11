<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 3b — Nachträge aus dem ersten Wochenlauf — Task-Ledger (Kurz)
Status: aktiv · Branch: feature/harness-stufe-3b · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: tasks/harness-stufe-3.md (Abschnitte T15a, F1) und docs/features/harness-stufe-3.md — Kurz-Ledger, keine eigene Spec
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: keine (der nächste Wochenlauf ist der reale Beweis für T1)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: R-0031, R-0032, R-0033, R-0034 · Hängt ab von: R-0003 (gemergt, PR #12)
Beabsichtigte Semantik gegen docs/: `docs/developer/cicd.html` „Test-Aggregator": unter `--strict` ist ein übersprungener Pflicht-Schritt ein Fehler — auf der Box wie auf der Dev-Box. Heute gilt das auf der Box nur für die Default-Menge ohne schwere Schritte.

### T1 — AH_REQUIRED erreicht die Box, schwere Schritte sind dort Pflicht  [ ]
Komponente: scripts/tests · Dateien: scripts/tests/crabbox_iter.sh, scripts/tests/run.sh, scripts/tests/run_flags_test.sh
Änderung: `crabbox_iter.sh` reicht `AH_REQUIRED` mit derselben Charset-Prüfung wie `AH_ONLY` an die Box durch; `run.sh`: ist `AH_REQUIRED` **nicht** gesetzt und der Layer `integration`, `e2e` oder `all`, erweitert sich die Required-Menge automatisch um die schweren Step-Ids dieses Layers (`integration_stack`, `backup_restore`, `sse_push_e2e`, `agent_monitoring`, `repo_build`, `upgrade-path`, `web-playwright`, `desktop-e2e-smoke`, die `desktop_e2e_*`-Schritte) — gedruckt in `required (strict):`. Ein gesetztes `AH_REQUIRED` gewinnt unverändert (Dev-Box). Test: Fixture-Lauf `all --strict` mit einem heavy Self-SKIP ⇒ `strict-failed: upgrade-path (SKIP)`; mit `AH_REQUIRED="ruff"` ⇒ grün. Kopf-Kommentar von `run.sh` und `crabbox_iter_flags_test.sh` (Durchreichung) nachziehen.
Verify: `bash scripts/tests/run_flags_test.sh` → `N passed, 0 failed`; `bash scripts/tests/crabbox_iter_flags_test.sh` → `N passed, 0 failed`; `bash scripts/tests/run.sh unit --strict --only scripts` → Exit 0
Doku: DEVELOPMENT.md Absatz „AH_REQUIRED" (Box-Regel), docs/developer/cicd.html DE+EN ein Satz

### T2 — test_migrations_smoke: Teardown ohne FORCE  [ ]
Komponente: apps/server · Dateien: apps/server/tests/test_migrations_smoke.py (ggf. apps/monitoring/tests/test_migrations_smoke.py, falls gleiches Muster)
Änderung: alle Verbindungen zur Wegwerf-DB schließen (`engine.dispose()` bzw. Session-Ende) **bevor** `DROP DATABASE` läuft; `WITH (FORCE)` entfernen. Damit braucht die Rolle kein `pg_signal_backend`. Falls monitoring dasselbe Muster hat, dort gleich mit.
Verify: `bash scripts/dev/verify.sh server --strict -- tests/test_migrations_smoke.py` fünfmal in Folge grün (Schleife im Aufruf des Builders, Ergebnis im Ledger); `grep -c 'WITH (FORCE)' apps/server/tests/test_migrations_smoke.py` → 0
Doku: keine (intern)

### T3 — heavy.sh: deps-audit-Dedup „offen bis grün", history.csv robust  [ ]
Komponente: scripts/tests · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Änderung: Dedup-Schlüssel für die REL-Zeile `deps-audit` ist der Workflow + Zustand „rot", nicht das Run-Datum: solange die letzte `seen.md`-Zeile `deps-audit` offen ist, wird keine neue Roadmap-Zeile erzeugt, nur `history.csv`; ein grüner `audit.yml`-Lauf schließt den Eintrag (`seen.md`-Zeile `resolved <datum>`). `history.csv`: Felder mit Komma, Anführungszeichen oder Zeilenumbruch werden RFC-4180-gequotet (Schrittnamen kommen aus Assertions-Texten). Tests: zwei rote Läufe ⇒ eine Zeile; grün ⇒ resolved; Schrittname mit Komma ⇒ parsebare Zeile (`python3 -c "import csv"` im Test).
Verify: `bash scripts/tests/heavy_test.sh` → `N passed, 0 failed`; `shellcheck --severity=warning scripts/tests/heavy.sh` leer
Doku: DEVELOPMENT.md Wochenlauf-Absatz ein Satz (Dedup-Regel)

### T4 — Rollen-Setup im Capstone: keine Paket-Upgrades auf der Fat-Box, längere Zeitgrenzen  [x] (`--no-upgrade` im Bootstrap; fünf Grenzen auf 3000 s — moncheck, rpm, tunnel, visitor und zusätzlich agentbox, gleiche Fehlerklasse; Serverbox bleibt 2700 s; Review approve)
Komponente: scripts/tests · Dateien: scripts/tests/crabbox_bootstrap.sh, scripts/tests/crabbox_multibox.sh
Änderung: Befund Wochenlauf 2026-09-11: das Setup der moncheck- und der tunnel-Box wurde von der äußeren `timeout`-Grenze abgebrochen (crabbox: „workspace owner release failed … context canceled"), weil `apt-get install -y` auf der bereits hydrierten Fat-Box alle schon installierten Pakete auf `noble-updates` **hochzog** (u. a. 25 MB webkit2gtk) und zusätzlich auf das apt-Rennen wartete; acht der acht Capstone-Fehler waren Folgen dieser zwei Abbrüche. Fix: `apt-get install -y --no-install-recommends --no-upgrade …` im Bootstrap (installiert nur Fehlendes; die Fat-Box braucht nichts), Setup-Zeitgrenzen `moncheckbox start` 1500 → 3000 s und `tunnelbox`/`visitorbox`/`agentbox_rpm` 1800 → 3000 s; im Kommentar beides begründen.
Verify: `shellcheck --severity=warning scripts/tests/crabbox_bootstrap.sh scripts/tests/crabbox_multibox.sh` leer; `grep -c -- '--no-upgrade' scripts/tests/crabbox_bootstrap.sh` ≥ 1; `grep -c 'timeout 3000 crabbox run' scripts/tests/crabbox_multibox.sh` ≥ 4; realer Beweis: nächster Wochenlauf, Capstone ohne „context canceled" im multibox.log
Doku: keine (crabbox-Ära; die Regel „Klone upgraden nie" wandert in Stufe 2 nach bootstrap_linux.sh)

### T5 — heavy.sh: Capstone-Urteil nennt die Ursache, wenn der Lauf lief  [ ]
Komponente: scripts/tests · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Änderung: Liegt eine `crabbox_multibox:`-Summary-Zeile vor, lautet der UNVERIFIED-Grund nicht „the capstone could not run", sondern „capstone infra: crabbox brach das Setup von N Box(en) ab (<slugs>); M ok, K failed — die K Fehler folgen dem Abbruch"; die Abbruch-Marker (`workspace owner release failed`, `context canceled`, `lease attempt 3/3 … failed`) werden aus dem multibox-Log gezählt und je Box in der Schritt-Tabelle als `infra` eingetragen, damit `history.csv` nicht `capstone,-,infra` allein trägt. Test: Fixture-Log mit einem Abbruch-Marker und drei Folge-FAILs ⇒ Grund nennt die Box, drei `infra`-Zeilen.
Verify: `bash scripts/tests/heavy_test.sh` → `N passed, 0 failed` (Fall capstone-infra-mit-summary)
Doku: DEVELOPMENT.md Wochenlauf-Absatz ein Satz
