<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Doku-Drift, zweites Bündel — Task-Ledger
Status: erledigt · Branch: feature/docs-drift-bundle-2 · Review: pro Task
Spec: docs/features/docs-drift-bundle-2.md (Roadmap R-0829, R-0841, R-0848, R-0849, R-0850, R-0853, R-0863, R-0866, R-0874, R-0898, R-0904)
Heavy: linux-full — `docker-compose.yml` ändert nur Kommentare; läuft im Sammellauf über `main`. Kein scenario, kein windows: kein Datenpfad, kein plattformspezifischer Code
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, Doku im selben Commit, SPDX bei neuen Dateien). Task-Prüfer: reviewer mit `model: "sonnet"` (Kevin 2026-10-29); Branch-Abschlussprüfung Opus.
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Für alle Tasks: die Zeilenangaben der Roadmap sind verrutscht; jede Aussage vor dem Schreiben an Code und Doku neu
greppen und die Codestelle lesen. Ist eine Stelle schon richtig, die Task mit `mark-skip` und Beleg schließen.
Verhaltensänderung oder Fund außerhalb der Zeile: melden, nicht bauen. Doku DE+EN gemeinsam.

### T1 — Compose- und Entrypoint-Kommentare zur mTLS-Phase und zum Identitäts-Header (R-0848, R-0904)  [x]
Komponente: scripts · Dateien: docker-compose.yml, apps/server/docker-entrypoint.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @64ff21ee 2026-10-29T12:47:58+01:00
Review: approve (.ah-out/review/docs-drift-bundle-2/T1.verdict.json)
Änderung: `docker-compose.yml` (`:211` „permissive mTLS this phase; CERT_REQUIRED in A8“, `:227-229` „permissive window … before arming“) auf den Stand „mTLS ab Installation scharf, `MTLS_ENFORCE=false` nur für manuellen Erst-Bootstrap“ (`scripts/install.sh:11-12`). `docker-compose.yml:46-49` und `docker-entrypoint.sh:48-51`: nicht „nobody can reach this socket“, sondern: andere Compose-Dienste erreichen `server:8080`; der Schutz ist die Prüfung der Gegenstelle in `apps/server/app/identity.py` (`_peer_is_gateway`). Nur Kommentare.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: keine (nur Kommentare)
Dedup-Key: bug:docs:docker-compose.yml:permissive-window-comment

### T2 — Installation und Umgebung: „permissiv“ und SMTP für Monitoring (R-0841, R-0829)  [x]
Komponente: scripts · Dateien: docs/admin/installation.html, docs/en/admin/installation.html, .env.example, README.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @06a8f019 2026-10-29T12:53:50+01:00
Review: approve (.ah-out/review/docs-drift-bundle-2/T2.verdict.json)
Änderung: `installation.html:161` (EN `:113`) „Aktuell läuft die Datenebene permissiv“ auf „scharf seit 0.29.0, `MTLS_ENFORCE=true`“ (Stand `betrieb.html:333`). `.env.example` (SMTP-Block ab `:146`, dazu `MTLS_ENFORCE` `:116-127` gegenlesen): SMTP gilt für Hub **und** Monitoring, Ports nicht nur 587/465 (jeder andere STARTTLS), `SMTP_CA_FILE` nennen. README-Env-Tabelle (`Configuration (env)` im Monitoring-Abschnitt): SMTP_* und `SMTP_CA_FILE` aufnehmen, Verweis auf `operations.html` statt Kopie.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/installation.html, docs/en/admin/installation.html, README.md
Dedup-Key: bug:docs:installation.html:permissive

### T3 — Betrieb und Troubleshooting zu Compose-Härtung (R-0898)  [x]
Komponente: scripts · Dateien: docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, docs/admin/benutzer.html, docs/en/admin/users.html, docs/admin/betrieb.html, docs/en/admin/operations.html, docker-compose.yml, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @84b49de4 2026-10-29T13:01:58+01:00
Review: approve (.ah-out/review/docs-drift-bundle-2/T3.verdict.json)
Änderung: (1) `troubleshooting.html` (EN `:58-59`, DE gegenlesen): die Logzeile „untrusted proxy“ gibt es nicht; die tatsächliche Warnung aus `identity.py` bzw. der Proxy-Auswertung nennen. (2) `docker-compose.yml:104-105` alter `TRUST_PROXY_HEADERS`-Kommentar an `.env.example` angleichen. (3) `benutzer.html:137` / `users.html:131`: das Docker-Netz gehört nicht in `ALLOWED_IPS`. (4) `betrieb.html` (Override-Beispiel um `:186-195`): `deploy.resources.limits.memory` bricht Compose ab, richtig `mem_limit`. (5) VictoriaMetrics „60 % der Grenze“ (`docker-compose.yml:533`, `betrieb.html`, `operations.html`, CHANGELOG): nur wenn die Grenze unter dem Host-RAM liegt. (6) „Compose v2.6+“ (`installation.html:84`) in der offiziellen Compose-Doku verifizieren (WebFetch), sonst „nicht verifiziert“ in der Zeile melden.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Dateien DE+EN, CHANGELOG
Dedup-Key: ref:docs:troubleshooting.html:compose-hardening-doc-nits

### T4 — Entwickler-Doku: frpc-Platzhalter, Bulk-ZIP-Rückfall, Anmelde-URL (R-0849, R-0850, R-0874)  [x]
Komponente: scripts · Dateien: docs/developer/index.html, docs/en/developer/index.html, docs/developer/server.html, docs/en/developer/server.html, docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @24784a68 2026-10-29T13:09:30+01:00
Review: approve (.ah-out/review/docs-drift-bundle-2/T4.verdict.json)
Änderung: `developer/index.html` Desktop-Block (um `:97-99`): die frpc-Platzhalter-Binary erwähnen (`DEVELOPMENT.md:856-860`, `tauri.conf.json` `externalBin`), mit Verweis statt Kopie. `server.html:111` (`generate_visitor_toml`): Bulk-ZIP-Rückfall nennen (Nutzer ohne Server bekommt eine `visitor.toml` mit allen sichtbaren STCP-Tunneln; Code in `modules/frp/generate_router.py` lesen). `desktop.html:247`: solange keine URL gespeichert ist, geht jede Anmeldung/Registrierung an die URL aus dem Fenster (Code lesen, `workspace`-Modul).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die genannten Dateien DE+EN
Dedup-Key: bug:docs:developer/index.html:frpc-placeholder

### T5 — Agent-Deployment: `--token-stdin` in den manuellen Beispielen (R-0863, nur Doku)  [x]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @1574c40a 2026-10-29T13:13:49+01:00
Review: approve (.ah-out/review/docs-drift-bundle-2/T5.verdict.json)
Änderung: Die zwei manuellen Beispiele (`agent-deployment.html:147-156`, EN `:146-155`, Linux und PowerShell) von `provision --token <…>` auf `--token-stdin` umstellen (Token über stdin; Aufruf in `apps/agent` gegenlesen, Flag-Tabelle `:178` beachten). Nicht in dieser Task: `postinst`, `adminhelper-agent.spec`, `packaging_rpm_test.go` (Install-Paketierung, offen in der Notiz von R-0863).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html
Dedup-Key: ref:docs:agent-deployment-token-stdin-examples

### T6 — Web: Hook-Hinweis nennt UTC (R-0853)  [x]
Komponente: web · Dateien: apps/web/src/lib/i18n/dictionaries.ts, CHANGELOG.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @34028779 2026-10-29T13:17:24+01:00
Review: approve (.ah-out/review/docs-drift-bundle-2/T6.verdict.json)
Änderung: `modal.hook.cronFormat` (DE `:206`, EN `:504`): „(UTC)“ ergänzen, Code von `hooks-hardening` T3 gegenlesen (Cron-Hooks rechnen in UTC). Prüfen, ob ein i18n-Paritätstest greift; kein neuer Test nötig.
Verify: bash scripts/dev/verify.sh web --strict
Doku: CHANGELOG.md (Unreleased, umlautfrei)
Dedup-Key: ref:web:dictionaries.ts:cron-hint-utc

### T7 — Desktop-UI: `shell.ts`-Kommentar zu fish und `%` (R-0874)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/utils/shell.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @43fa209c 2026-10-29T13:25:32+01:00
Review: approve (.ah-out/review/docs-drift-bundle-2/T7.verdict.json)
Änderung: Der Kopfkommentar (`:10-13`) verspricht, fish lese jeden Wert unverändert; `%` gilt aber als sicher und `%self` wird in fish zur PID (kein Aufrufer erzeugt so einen Wert). Kommentar an den Stand, fish-Doku zu Variablen und `%self` vorher lesen. Nur Kommentar.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (nur Kommentar)
Dedup-Key: ref:desktop:shell.ts:fish-percent-comment

### T8 — Desktop-Rust: veraltete Kommentare und zwei Test-Lücken (R-0866)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/launcher.rs, apps/desktop/src-tauri/src/frpc.rs, apps/desktop/src-tauri/src/terminal.rs, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @078a1726 2026-10-29T13:37:03+01:00
Review: approve (.ah-out/review/docs-drift-bundle-2/T8.verdict.json)
Änderung: (1) `launcher.rs` Kommentar zum `threading`-Modul (Zeile frisch greppen; `:547-553` ist heute der `DETACHED_PROCESS`-Kommentar) an den Stand. (2) `frpc.rs`: der 401-Test (`:3547`, `serve_one(...).await.0`) verwirft den JoinHandle; joinen, damit ein Fehler im Server-Thread sichtbar wird. (3) `frpc.rs` `stop_left_behind` (`:1135`): Warten auf den freien Admin-Port bekommt einen Test, in einer Gegenprobe rot zu sehen. (4) `terminal.rs` Gegenprobe-Kommentar (`:585`) präzisieren. (5) CHANGELOG-Satz zu „RDP Verbindung fehlgeschlagen“ (`:653-656`) lesen und angleichen. Keine Verhaltensänderung.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: CHANGELOG.md
Dedup-Key: ref:desktop:launcher.rs:stale-threading-comment

## Entscheidungen
- 2026-10-29 T3: `benutzer.html`/`users.html` (Docker-Netz nicht in `ALLOWED_IPS`) und das `mem_limit`-Override in `betrieb.html`/`operations.html` waren schon richtig, nichts geändert — Beleg: `benutzer.html` „nicht das Docker-Netz des Gateways“, Override-Beispiel mit `mem_limit: 8g`.
- 2026-10-29 T3: „Compose v2.6+“ (`installation.html:84`) bleibt unverändert und **nicht verifiziert**: die v2.6.0-Release-Notes nennen keines der genutzten Felder (`sysctls`, `pids_limit`, `mem_limit`, `cap_drop`, `depends_on`-`condition`); welches Feature die Untergrenze trägt, ist offen. Melden an Kevin.
- 2026-10-29 T3: VictoriaMetrics „60 % der Grenze nur bei Grenze < Host-RAM“: die Flag-Doku (`-memory.allowedPercent`, Default 60) sagt nur „system memory“; dass VictoriaMetrics die cgroup-Grenze erkennt, steht dort nicht — die Formulierung folgt der Roadmap-Zeile, in der Doku des Projekts nicht belegt.
- 2026-10-29 T4: `desktop.html:247` (DE+EN) blieb unverändert: der Text deckt `storage::meta_with` (erste URL nur ohne Identität im Schlüsselbund) und `storage::keep_enrolled_url` (Registrierung gibt einer Workspace ohne URL die Ziel-URL, eine fremde URL ist ein Fehler) bereits ab. Bulk-ZIP-Rückfall präzisiert: gilt, wenn **kein** Nutzer einen Server hat (`gen_bulk_zip`), nicht je Nutzer ohne Server wie in R-0850.
