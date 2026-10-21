<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Dependency Audit 2026-10-21: certifi, rustls-webpki, webpki-roots, vite — Task-Ledger
Status: erledigt · Branch: feature/deps-audit-1021 · Review: am Ende
Spec: Roadmap R-0657
Heavy: linux-full — `rustls-webpki` und `webpki-roots` prüfen die Zertifikatsketten im Desktop-Binary (reqwest `rustls-tls`, mTLS-Client), `vite` baut die Desktop-UI; die Desktop-Journeys laufen im Beta-Sammellauf über `main`, den Session adminhelper-fe direkt nach dem Merge startet. Kein `scenario`: weder FRP-Datenpfad noch PKI-Ausstellung noch Install/Update ändern sich
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-21: R-0657 angenommen, erst der Fix, dann ein einziger Beta-Sammellauf über den Endstand. Der Dependency Audit vom 2026-10-21 (`audit.yml`, Lauf 39580551648, workflow_dispatch über 6f05b316) ist in drei von vier Jobs rot; `govulncheck (agent)` ist grün. Alle drei Funde sind reine Lock-Stände, der Code ändert sich nicht. Trockenläufe im Worktree @e73912f4: `cargo update -p rustls-webpki -p webpki-roots --dry-run` hebt genau diese zwei Pakete (0.103.15 → 0.103.16, 1.0.7 → 1.0.10); `vite` steht in beiden Locks auf 8.0.16 (Bereich `^8.0.16`), die erste nicht betroffene Version ist 8.1.6.

### T1 — certifi 2026.10.19 in den Locks von server und monitoring  [x]
Komponente: server · Dateien: apps/server/requirements.txt, apps/monitoring/requirements.txt, CHANGELOG.md
Evidenz: run.sh[quick] server monitoring: 5 passed, 0 failed, 13 skipped @6278ce52 2026-10-21T15:57:00+02:00
Review: am Ende (Branch-Review)
Änderung: Beide gehashten Locks mit `pip-compile` neu erzeugen, mit genau dem Befehl aus ihrem Kopf plus `--upgrade-package certifi==2026.10.19` (pip-tools 7.6.1, Python 3.12, wie 9ead47da). Im Diff ändern sich nur Version und Hash-Zeilen von `certifi`; ändert sich mehr, nennen und begründen. `requirements.in` bleibt, `apps/ca-issuer` ist laut Audit sauber und bleibt. Orakel: `pip-audit -r apps/<x>/requirements.txt --disable-pip` wie in `audit.yml` meldet vorher PYSEC-2026-4320 und danach nichts; die neuen Locks installieren mit `--require-hashes` in einem Scratch-Venv. Die verlinkten `.venv` des Worktrees gehören dem Haupt-Checkout und werden nicht verändert.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: CHANGELOG.md (Security: certifi 2026.5.20 → 2026.10.19, PYSEC-2026-4320)
Beweis: audit.yml-Lauf 39580551648, Job „pip-audit (server + monitoring + ca-issuer)“: zweimal `Found 1 known vulnerability in 1 package` · `certifi 2026.5.20 PYSEC-2026-4320 2026.10.19`, ca-issuer `No known vulnerabilities found`; `apps/server/requirements.txt:95` und `apps/monitoring/requirements.txt:30` (`certifi==2026.5.20`)
Dedup-Key: rel:deps-audit
HEAD: e73912f4
Semantik: docs/developer/cicd.html:43 — „Wöchentlicher Dependency-Audit (Montag früh, auch manuell per workflow_dispatch): pip-audit (Server- + Monitoring-Locks), cargo audit (Desktop), govulncheck (Agent), npm audit (Web + Desktop-UI)“; Kevin 2026-10-21: das Beta erst mit grünem Audit

### T2 — rustls-webpki 0.103.16 und webpki-roots 1.0.10 im Desktop-Lockfile  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/Cargo.lock, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @5eb8c460 2026-10-21T16:03:47+02:00
Review: am Ende (Branch-Review)
Änderung: `cargo update --manifest-path apps/desktop/src-tauri/Cargo.toml -p rustls-webpki -p webpki-roots` hebt `rustls-webpki` 0.103.15 → 0.103.16 und `webpki-roots` 1.0.7 → 1.0.10; im Diff ändern sich genau die `version`- und `checksum`-Zeilen dieser zwei Pakete, `Cargo.toml` bleibt. Orakel: `cargo audit` im Verzeichnis `apps/desktop/src-tauri` meldet vorher RUSTSEC-2026-0381 und -0382 als Fehler und danach keinen Fehler mehr (die Warnungen, die `audit.yml` heute zulässt, bleiben).
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: CHANGELOG.md (Security: beide Advisories; webpki-roots entzieht den emSign-Zwischenzertifikaten das Vertrauen)
Beweis: audit.yml-Lauf 39580551648, Job „cargo audit (desktop)“: `error: 2 vulnerabilities found!` · `rustls-webpki 0.103.15` RUSTSEC-2026-0382 („Certificate verification may accept distrusted intermediates“, Upgrade to >=0.103.16, <0.104.0-alpha.1) · `webpki-roots 1.0.7` RUSTSEC-2026-0381 („Bundled root certificates allow trust in distrusted emSign intermediates“, Upgrade to >=1.0.10); `apps/desktop/src-tauri/Cargo.lock:3922-3923` und `:5823-5824`
Dedup-Key: rel:deps-audit
HEAD: e73912f4
Semantik: docs/developer/cicd.html:43 — wie T1

### T3 — vite 8.1.6 in web und desktop-ui  [x]
Komponente: web · Dateien: apps/web/package.json, apps/web/package-lock.json, apps/desktop/ui/package.json, apps/desktop/ui/package-lock.json, CHANGELOG.md
Evidenz: run.sh[quick] web desktop-ui: 2 passed, 0 failed, 16 skipped @680f542e 2026-10-21T16:17:53+02:00
Review: am Ende (Branch-Review)
Änderung: In beiden Paketen `vite` auf 8.1.6 heben und die Untergrenze in `package.json` von `^8.0.16` auf `^8.1.6` setzen (wie die Untergrenze bei pyjwt), damit eine betroffene Version nicht mehr auflösbar ist. Im Lock-Diff nur `vite` und, falls 8.1.6 sie verlangt, ihre eigenen Abhängigkeiten; jede weitere Änderung nennen. Die hart verlinkten `node_modules` des Worktrees nur per `npm ci` ersetzen (es löscht den Ordner zuerst), nie in place ändern. Orakel: `npm audit --audit-level=high` wie in `audit.yml` in beiden Verzeichnissen vorher rot (vite), danach grün; dazu `npm run build` in beiden.
Verify: bash scripts/dev/verify.sh web desktop-ui --strict
Doku: CHANGELOG.md (Security: vite 8.0.16 → 8.1.6, nur Dev-Server, nicht ausgeliefert)
Beweis: audit.yml-Lauf 39580551648, Job „npm audit (web + desktop-ui)“: zweimal `vite  8.0.0 - 8.1.5` · `Severity: high` · launch-editor GHSA-698v-4r3x-3vcv, GHSA-r825-w8mm-5pxw, GHSA-587h-7wmj-h5pm · `1 high severity vulnerability`; `apps/web/package-lock.json:3865` und `apps/desktop/ui/package-lock.json:3932` (`node_modules/vite`, 8.0.16)
Dedup-Key: rel:deps-audit
HEAD: e73912f4
Semantik: docs/developer/cicd.html:43 — wie T1
