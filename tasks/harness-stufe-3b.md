<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 3b — Nachträge aus dem ersten Wochenlauf — Task-Ledger (Kurz)
Status: erledigt (7/7, PR #13) · Branch: feature/harness-stufe-3b · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: tasks/harness-stufe-3.md (Abschnitte T15a, F1) und docs/features/harness-stufe-3.md — Kurz-Ledger, keine eigene Spec
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: keine (der nächste Wochenlauf ist der reale Beweis für T1)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: R-0031, R-0032, R-0033, R-0034 · Hängt ab von: R-0003 (gemergt, PR #12)
Beabsichtigte Semantik gegen docs/: `docs/developer/cicd.html` „Test-Aggregator": unter `--strict` ist ein übersprungener Pflicht-Schritt ein Fehler — auf der Box wie auf der Dev-Box. Heute gilt das auf der Box nur für die Default-Menge ohne schwere Schritte.

### T1 — AH_REQUIRED erreicht die Box, schwere Schritte sind dort Pflicht  [x] (crabbox_iter reicht AH_REQUIRED durch; run.sh: unset oder leer + heavy Layer ⇒ Layer-Ids Pflicht inkl. Guards, GUI-Ids aus demselben Glob wie layer_e2e; heavy.sh setzt die Dev-Box-Menge zurück, AH_REQUIRED_BOX explizit. Der hermetische Test beweist den Fix über die Layer-Guards `integration`/`desktop-e2e-gui` auf dem Bare-PATH statt über einen upgrade-path-Self-SKIP — der Exit-75-Pfad ist derselbe Code; Test-Skill-Caveat T15a durch die Box-Regel ersetzt. Review: 2 wichtig behoben)
Komponente: scripts/tests · Dateien: scripts/tests/crabbox_iter.sh, scripts/tests/run.sh, scripts/tests/run_flags_test.sh
Änderung: `crabbox_iter.sh` reicht `AH_REQUIRED` mit derselben Charset-Prüfung wie `AH_ONLY` an die Box durch; `run.sh`: ist `AH_REQUIRED` **nicht** gesetzt und der Layer `integration`, `e2e` oder `all`, erweitert sich die Required-Menge automatisch um die schweren Step-Ids dieses Layers (`integration_stack`, `backup_restore`, `sse_push_e2e`, `agent_monitoring`, `repo_build`, `upgrade-path`, `web-playwright`, `desktop-e2e-smoke`, die `desktop_e2e_*`-Schritte) — gedruckt in `required (strict):`. Ein gesetztes `AH_REQUIRED` gewinnt unverändert (Dev-Box). Test: Fixture-Lauf `all --strict` mit einem heavy Self-SKIP ⇒ `strict-failed: upgrade-path (SKIP)`; mit `AH_REQUIRED="ruff"` ⇒ grün. Kopf-Kommentar von `run.sh` und `crabbox_iter_flags_test.sh` (Durchreichung) nachziehen.
Verify: `bash scripts/tests/run_flags_test.sh` → `N passed, 0 failed`; `bash scripts/tests/crabbox_iter_flags_test.sh` → `N passed, 0 failed`; `bash scripts/tests/run.sh unit --strict --only scripts` → Exit 0
Doku: DEVELOPMENT.md Absatz „AH_REQUIRED" (Box-Regel), docs/developer/cicd.html DE+EN ein Satz

### T2 — test_migrations_smoke: Teardown ohne FORCE  [x] (Plain-DROP in beiden Smoke-Tests, `engine.dispose()` davor unverändert; Ursache laut Review gegen PG-17-Quellen: Autovacuum-Worker ohne Rolle, FORCE bräuchte pg_signal_backend; Server 3× `3 passed`, Monitoring 2× `3 passed`; zwei Rest-DBs alter FORCE-Abbrüche gedroppt; Review: request_changes → Retry-Schleife gestrichen → approve)
Komponente: apps/server · Dateien: apps/server/tests/test_migrations_smoke.py (ggf. apps/monitoring/tests/test_migrations_smoke.py, falls gleiches Muster)
Änderung: alle Verbindungen zur Wegwerf-DB schließen (`engine.dispose()` bzw. Session-Ende) **bevor** `DROP DATABASE` läuft; `WITH (FORCE)` entfernen. Damit braucht die Rolle kein `pg_signal_backend`. Falls monitoring dasselbe Muster hat, dort gleich mit.
Verify: `bash scripts/dev/verify.sh server --strict -- tests/test_migrations_smoke.py` fünfmal in Folge grün (Schleife im Aufruf des Builders, Ergebnis im Ledger); `grep -c 'WITH (FORCE)' apps/server/tests/test_migrations_smoke.py` → 0
Doku: keine (intern)

### T3 — heavy.sh: deps-audit-Dedup „offen bis grün", history.csv robust  [x] (seen.md-Schlüssel `deps-audit · open|resolved`; rot bei offenem Eintrag ⇒ nur Notiz, grün ⇒ `resolved`, nächster roter Lauf ⇒ neue Zeile; alte Zeilenform `deps-audit · deps-audit` gilt als offen; `csv_field` quotet RFC-4180 für schritt/ergebnis/vm; Tests 4j erweitert + 7f mit Komma und Anführungszeichen im Schrittnamen, Python-csv-Gegenprobe)
Komponente: scripts/tests · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Änderung: Dedup-Schlüssel für die REL-Zeile `deps-audit` ist der Workflow + Zustand „rot", nicht das Run-Datum: solange die letzte `seen.md`-Zeile `deps-audit` offen ist, wird keine neue Roadmap-Zeile erzeugt, nur `history.csv`; ein grüner `audit.yml`-Lauf schließt den Eintrag (`seen.md`-Zeile `resolved <datum>`). `history.csv`: Felder mit Komma, Anführungszeichen oder Zeilenumbruch werden RFC-4180-gequotet (Schrittnamen kommen aus Assertions-Texten). Tests: zwei rote Läufe ⇒ eine Zeile; grün ⇒ resolved; Schrittname mit Komma ⇒ parsebare Zeile (`python3 -c "import csv"` im Test).
Verify: `bash scripts/tests/heavy_test.sh` → `N passed, 0 failed`; `shellcheck --severity=warning scripts/tests/heavy.sh` leer
Doku: DEVELOPMENT.md Wochenlauf-Absatz ein Satz (Dedup-Regel)

### T4 — Rollen-Setup im Capstone: keine Paket-Upgrades auf der Fat-Box, längere Zeitgrenzen  [x] (`--no-upgrade` im Bootstrap; fünf Grenzen auf 3000 s — moncheck, rpm, tunnel, visitor und zusätzlich agentbox, gleiche Fehlerklasse; Serverbox bleibt 2700 s; Review approve)
Komponente: scripts/tests · Dateien: scripts/tests/crabbox_bootstrap.sh, scripts/tests/crabbox_multibox.sh
Änderung: Befund Wochenlauf 2026-09-11: das Setup der moncheck- und der tunnel-Box wurde von der äußeren `timeout`-Grenze abgebrochen (crabbox: „workspace owner release failed … context canceled"), weil `apt-get install -y` auf der bereits hydrierten Fat-Box alle schon installierten Pakete auf `noble-updates` **hochzog** (u. a. 25 MB webkit2gtk) und zusätzlich auf das apt-Rennen wartete; acht der acht Capstone-Fehler waren Folgen dieser zwei Abbrüche. Fix: `apt-get install -y --no-install-recommends --no-upgrade …` im Bootstrap (installiert nur Fehlendes; die Fat-Box braucht nichts), Setup-Zeitgrenzen `moncheckbox start` 1500 → 3000 s und `tunnelbox`/`visitorbox`/`agentbox_rpm` 1800 → 3000 s; im Kommentar beides begründen.
Verify: `shellcheck --severity=warning scripts/tests/crabbox_bootstrap.sh scripts/tests/crabbox_multibox.sh` leer; `grep -c -- '--no-upgrade' scripts/tests/crabbox_bootstrap.sh` ≥ 1; `grep -c 'timeout 3000 crabbox run' scripts/tests/crabbox_multibox.sh` ≥ 4; realer Beweis: nächster Wochenlauf, Capstone ohne „context canceled" im multibox.log
Doku: keine (crabbox-Ära; die Regel „Klone upgraden nie" wandert in Stufe 2 nach bootstrap_linux.sh)

### T5 — heavy.sh: Capstone-Urteil nennt die Ursache, wenn der Lauf lief  [x] (capstone_scan liest die ==-Abschnitte und ordnet FAILs Rollen zu; Abbruch-Marker „workspace owner release failed", „refusing collection and cleanup: context canceled", „lease attempt 3/3" (Rolle aus dem Slug) ⇒ FAILs dieser Rolle `infra` mit Detail `setup abort: <rolle>`; nur Folgefehler ⇒ UNVERIFIED „capstone infra: crabbox brach das Setup von N Rolle(n) ab (…); <Summary> — die K Fehler folgen dem Abbruch"; echter FAIL daneben ⇒ FAIL. Nebenfund behoben: `infra_marker` traf „reLEASE FAILED" der crabbox-Warnung und erklärte den ganzen Capstone für nicht gelaufen; jetzt `\blease failed`. Bewusst „je Rolle" statt „je Box": Slugs sind zufällig, Rollen stabil; verlorene Leases werden über den Slug der Rolle zugeordnet, nicht über den Abschnitt. Tests 7c–7h; Review: 3 wichtig behoben; bekannter Rest: eine `strict: … (no desktop box)`-Folgezeile eines verlorenen Desktop-Leases fällt unter die vorherige Abschnitts-Rolle und zählt konservativ als fail)
Komponente: scripts/tests · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Änderung: Liegt eine `crabbox_multibox:`-Summary-Zeile vor, lautet der UNVERIFIED-Grund nicht „the capstone could not run", sondern „capstone infra: crabbox brach das Setup von N Box(en) ab (<slugs>); M ok, K failed — die K Fehler folgen dem Abbruch"; die Abbruch-Marker (`workspace owner release failed`, `context canceled`, `lease attempt 3/3 … failed`) werden aus dem multibox-Log gezählt und je Box in der Schritt-Tabelle als `infra` eingetragen, damit `history.csv` nicht `capstone,-,infra` allein trägt. Test: Fixture-Log mit einem Abbruch-Marker und drei Folge-FAILs ⇒ Grund nennt die Box, drei `infra`-Zeilen.
Verify: `bash scripts/tests/heavy_test.sh` → `N passed, 0 failed` (Fall capstone-infra-mit-summary)
Doku: DEVELOPMENT.md Wochenlauf-Absatz ein Satz

### T6 — Funde aus dem Abschluss-Review (Merge-Readiness)  [x]
Komponente: scripts/tests · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, DEVELOPMENT.md, CHANGELOG.md, tasks/harness-stufe-3.md
Änderung: (1) Ein `strict-failed`-Schritt im Box-Artefakt (`last-all.json`) endet jetzt als INFRA der Ebene mit Grund und Schrittnamen — vorher lief er als „wrapper exit 1 without a red step" in FAIL, die Doku behauptete UNVERIFIED, und das Weekly-Gate hätte den Capstone hinter einem Infra-Problem gestartet; keine Wiederholungen, Schrittzeilen `infra`. Test 4 arbeitet mit dem Artefakt (`upgrade-path:strict-failed:0`) statt mit einer stdout-Zeile, die der echte Wrapper nie druckt. (2) Die strict-Folgezeile eines verlorenen Desktop-Leases (`strict: … (no desktop box)`) gehört der Box-Rolle, nicht dem vorherigen Abschnitt; Fixture 7h entspricht jetzt der echten multibox-Ausgabe (kein GUI-Header). (3) Ein Name: „Box-Regel" in DEVELOPMENT.md; T15a im Stufe-3-Ledger auf behoben; CHANGELOG Unreleased/Fixed.
Verify: `bash scripts/tests/heavy_test.sh` → `N passed, 0 failed`; `shellcheck --severity=warning scripts/tests/heavy.sh` leer
Doku: DEVELOPMENT.md (Name, Klassifikations-Absatz), CHANGELOG.md
Review: request_changes → Klassifikations-Absatz nachgezogen, Kombination strict-failed + echter fail getestet (INFRA gewinnt, kein Retry, Detail „not classified (layer infra)"); Folge-Kandidat für die Roadmap: `strict-failed: no step ran` und test-skip-strict-failed ohne Step-Ergebnis im Artefakt enden für die `all`-Ebene weiterhin als FAIL, weil die Box-Ausgabe nicht in all.log liegt.

### T7 — Sync-Abbruch als Setup-Abbruch (Fund aus dem Capstone-Beweislauf)  [x]
Komponente: scripts/tests · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, DEVELOPMENT.md
Änderung: Der Capstone-Beweislauf 2026-09-11-2022 (nach T4) endete 22 ok / 3 failed / 0 skipped: kein Setup lief mehr in die Zeitgrenze, kein Paket-Upgrade, aber crabbox scheiterte beim Sync der Tunnel-Box („rsync failed: finish rsync workspace witness: … ambiguous remote state: exit status 74") — das Rollen-Skript lief nie, die drei Tunnel-Assertionen waren Folgen, heavy.sh führte sie als `fail`. Die crabbox-Zeile ist jetzt Abbruch-Marker in `capstone_scan` (Rolle aus dem Abschnitt) und in `infra_marker` für die `all`-Ebene (die Box hat den Baum nie bekommen; im Capstone bewusst nicht als Ganz-Lauf-Marker). Tests 7i (echte Zeilen) und 4p.
Verify: `bash scripts/tests/heavy_test.sh` → `N passed, 0 failed`; `shellcheck --severity=warning scripts/tests/heavy.sh` leer
Doku: DEVELOPMENT.md (Marker-Liste)
