<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Doku-Fixes 2: Agent-Deployment EN, Web-Panel- und Server-Doku, VNC — Task-Ledger
Status: bereit · Branch: feature/doc-fixes-2 · Review: pro Task
Spec: Roadmap R-0521, R-0522, R-0523
Heavy: none — nur Doku unter `docs/` und der Beschreibungstext `bundle.longDescription` in `tauri.conf.json`; keine API-, Gateway-, PKI-, Agent-, Compose-, Install- oder Desktop-Journey-Änderung
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Hängt ab von: doc-fixes (R-0489, R-0490, `feature/doc-fixes`). Erst nach dessen Merge bauen und `origin/main` hineinmergen: doc-fixes T2 gliedert `docs/{,en/}admin/agent-deployment.html` neu (EN-Lead `:34`, EN `:45`, Windows, Prüfen, Upgrade) und ändert `docs/admin/index.html:91`, `:99`. Die Zeilen unten gelten für main@81764c43; der builder greppt sie nach dem Merge neu.

Drei BUG-Zeilen als Doku-Paket (Kevin 2026-10-19: „Ein Doku-Paket danach“). Das Soll ist der Code: Jede Task nennt
unter `Semantik:` die Code-Stelle und die falsche Doku-Stelle mit Zitat. Doku hat keinen roten Test: `Beweis:` ist ein
grep, der auf `HEAD:` die Stellen zeigt und nach der Task leer ist; wo etwas fehlt, zählt eine Positiv-Probe vorher 0
und danach die neuen Stellen. `Verify:` von T1–T3 ist der formale Lauf `scripts -- doc_smoke_test` (prüft den Checker an
Fixtures); T4 fährt `ipc.inventory.test.ts`, das `desktop.html` DE+EN liest; T5 baut desktop-rs. Bei T1–T4 fährt der
builder zusätzlich `python3 scripts/dev/doc-smoke.py --paths --env --strict` mit Exit 0, Ergebnis in den Commit-Body (in
der PR-CI `.github/workflows/ci.yml:874`). Feste Zählwerte werden nicht nachgezählt, sondern fallen weg (wie doc-drift
und doc-fixes). Kein CHANGELOG für T1–T4: reine Doku-Korrektur ohne Verhaltensänderung (wie doc-drift). T5 trägt eine
Zeile, weil die Beschreibung im ausgelieferten Desktop-Paket steht.

Disjunkt zu R-0430 (`feature/desktop-session-ports`): Dessen T5 und T11 ändern in `docs/{,en/}developer/desktop.html`
die Command-Tabelle (Event-Zeile, auf main `:93`), TOFU (`:109-119`), Server-Mode-Flow (`:125-136`) und Connect-Flow
(`:137-146`), R-0524 den RDP-Race-Guard (`:98`); T4 hier ändert nur `:57` und `:72`. `tauri.conf.json` fasst R-0430 nicht
an. Nicht in diesem Ledger: `docs/admin/frp-tunnel.html:99` DE+EN nennt VNC als Ziel eines STCP-Tunnels, das stimmt;
`CHANGELOG.md:2391` und `tasks/doc-drift.md` sind Geschichte; der Code-Kommentar `apps/desktop/src-tauri/src/sync.rs:45-48`
(„the server may also hold vnc/custom ones“) ist keine Doku und liegt in einer Datei, die R-0430 umbaut.

### T1 — R-0521: Agent-Deployment EN mit „What does the agent do?“, Provisionierung wie DE  [x]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @192ec608 2026-10-19T11:18:38+02:00
Review: approve (.ah-out/review/doc-fixes-2/T1.verdict.json)
Änderung: Nach dem Merge von doc-fixes neu greppen.
(1) EN bekommt zwischen Lead (`:34`) und Schnell-Rollout (`:36`) den Abschnitt „What does the agent do?“ mit denselben drei Punkten wie DE `:36-41` (Monitoring, FRP-Client, Updates).
(2) EN `:148` sagt dasselbe wie DE `:147`. Was dort darüber hinausgeht, wandert in die Punkte aus (1):
- Metrik-Push („Metrics are then pushed tunnel-free …“, Monitor-Key im Header `X-API-Key`, kein eigener Monitoring-Port nötig) in den Punkt Monitoring, in beiden Sprachen.
- „<em>Upgrade note:</em>“ (`MONITOR_URL`) in den Punkt Updates.
- Der Satz zum Client-Zertifikat aus dem Enrollment in den Punkt FRP-Client, so wie DE `:39` ihn sagt. Der Halbsatz „the server no longer runs an FRP CA of its own“ entfällt; DE hat ihn nicht, `docs/developer/server.html:142` trägt ihn.
(3) EN `:148` streicht „or the Windows service (auto-start)“: provision aktiviert nur unter Linux den Timer, den Windows-Dienst richtet `service install` ein (Abschnitt Windows aus doc-fixes T2).
(4) Nit aus dem Branch-Review von doc-drift (Zeile R-0523): „Without an active tunnel it stops and disables <code>frpc.service</code>“ nennt das Subjekt, „… the agent stops …“, denn gemeint ist der Agent, nicht der Server.
(5) Der Punkt Updates macht in beiden Sprachen keine eigene Aussage über Upgrades mehr („Konfig und Service werden bei Upgrades nicht überschrieben“, DE `:40`). Er verweist auf den Abschnitt Upgrade, den doc-fixes T2 in beiden Sprachen gleich fasst; fehlt dort ein Anker, bekommt die Überschrift einen. Der Hinweis zum einmaligen Neu-Provisionieren (`MONITOR_URL`) bleibt.
Sonst bleibt die Seite, wie doc-fixes sie hinterlässt.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/agent-deployment.html + docs/en/admin/agent-deployment.html (die Task ist die Doku); kein CHANGELOG
Beweis: main@81764c43 · `grep -n -E '<p>After provisioning the agent enables' docs/en/admin/agent-deployment.html | grep -o -E '^[0-9]+:|or the Windows service \(auto-start\)|tunnel-free|MONITOR_URL|ca-issuer|Without an active tunnel it stops'` → `148:` und die fünf Phrasen, nach der Task nur noch die Zeilennummer · `grep -c -E '<h2[^>]*>What does the agent do\?</h2>' docs/en/admin/agent-deployment.html` → `0`, danach `1` · `grep -n -o 'Konfig und Service werden bei Upgrades nicht überschrieben' docs/admin/agent-deployment.html` → `:40`, danach leer
Dedup-Key: bug:docs:agent-deployment.html:rest-after-doc-drift
HEAD: 81764c43
Semantik: Soll ist der Code und die DE-Seite:
- `apps/agent/internal/monitor/platform_linux.go:12-13` (`systemctl enable --now adminhelper-agent.timer`), `apps/agent/internal/monitor/platform_windows.go:9-15` (provision registriert unter Windows nichts, nur der Hinweis auf `service install`).
- `apps/agent/internal/monitor/report.go:118`, `:159` (Push an `<url>/agent/<id>/report` mit `X-API-Key`), `apps/server/app/modules/provisioning/router.py:175`, `:212` (Monitor-Key je Server).
- DE `docs/admin/agent-deployment.html:147` — „er aktiviert <code>adminhelper-agent.timer</code>“ und „Ohne aktiven Tunnel stoppt und deaktiviert er <code>frpc.service</code>“ (er: der Agent); DE `:36` — „Was macht der Agent?“ mit `:38-40`.
Falsche Doku-Stelle: EN `:148` — „After provisioning the agent enables the <code>adminhelper-agent.timer</code> systemd unit (Linux) or the Windows service (auto-start).“ und „the server no longer runs an FRP CA of its own. Without an active tunnel it stops and disables <code>frpc.service</code>“.

### T2 — R-0522: webui.html beschreibt Baum, Stores und Routen wie der Code  [x]
Komponente: scripts · Dateien: docs/developer/webui.html, docs/en/developer/webui.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @19b6f381 2026-10-19T11:28:45+02:00
Review: approve (.ah-out/review/doc-fixes-2/T2.verdict.json)
Änderung: DE und EN, gleiche Zeilen.
(1) Der Baum `:38-54` nennt nur, was `git ls-files apps/web` zeigt:
- `api/` mit `audit` (`:41`).
- `components/` als `layout/` (Router, Sidebar) und `ui/` (Button, ConfirmDialog, EmptyState, Modal, Toast) statt „Button, Modal, TagChip, Tabs, …“ (`:42`).
- `stores/` mit `theme` und ohne „Runes“ (`:43`).
- `routeGuard.ts` neben `router.ts` (`:45`), `routes.ts` neben `App.svelte`.
- `pages/` mit Audit (`:47`), `modals/` ohne `configs/` (`:48`).
- `tests/e2e/` als Playwright-Specs mit Mocks, ohne Aufzählung einzelner Specs, dazu `tests/live/` (Smoke gegen den echten Stack über `scripts/tests/web_live.sh`) (`:52`).
- `svelte.config.js` statt `.ts` (`:53`).
(2) Beifang auf derselben Seite, derselbe Fund (Audit und theme fehlen, Stores falsch beschrieben):
- Lead `:34` und Produktiv-Routen `:58` nennen das Audit-Log (`#/audit`).
- `:61` beschreibt die Stores als `writable`-Stores aus `svelte/store` mit Methoden statt als „TypeScript-Klasse mit `$state`-Feldern“.
- Die Store-Tabelle `:62-72` bekommt `theme` (Dark/Light, `localStorage.ah-theme`, wie `:82`).
- Die Wrapper-Liste `:76` nennt `audit.ts`.
Feste Zählwerte keine; sonst bleibt die Seite unverändert.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/webui.html + docs/en/developer/webui.html (die Task ist die Doku); kein CHANGELOG
Beweis: main@81764c43 · `grep -n -o -E 'TagChip|Tabs, |configs/|Runes-Stores|runes-based stores|TypeScript-Klasse|TypeScript class|svelte\.config\.ts|login\.spec\.ts, smoke\.spec\.ts\)' docs/developer/webui.html docs/en/developer/webui.html` → je Seite `:42` (2×), `:43`, `:48`, `:52`, `:53`, `:61`; nach der Task leer · `grep -c -E '#/audit|audit\.ts|<code>theme</code></td>' docs/developer/webui.html docs/en/developer/webui.html` → je `0`, danach je mindestens `3`
Dedup-Key: bug:docs:webui.html:stale-tree
HEAD: 81764c43
Semantik: Soll ist der Code:
- `git ls-files apps/web/src apps/web/tests`: `src/lib/components/layout/{Router,Sidebar}.svelte`, `src/lib/components/ui/{Button,ConfirmDialog,EmptyState,Modal,Toast}.svelte`, `src/lib/stores/theme.ts`, `src/lib/api/audit.ts`, `src/lib/routeGuard.ts`, `src/routes.ts`, `src/pages/Audit.svelte`, `src/modals/` ohne Unterordner, `tests/e2e/{authz,crud,login,smoke,theme}.spec.ts` mit `mocks.ts`, `tests/live/smoke.live.spec.ts`; dazu `apps/web/svelte.config.js`.
- `apps/web/src/routes.ts:18` (`'/audit'`), `apps/web/src/lib/stores/users.ts:5`, `:9`, `:16-17` (`writable` und ein Objekt mit `subscribe` und Methoden).
Doku: `docs/developer/webui.html:82` — „kippt &uuml;ber den <code>theme</code>-Store zwischen Dark und Light“; `docs/developer/server.html:61` (`/api/audit`). Falsche Doku-Stellen: `:42` — „Button, Modal, TagChip, Tabs, EmptyState, Toast, ...“, `:48` — „Modal-Komponenten + <code>configs/</code> Subfolder“, `:61` — „Jeder Store ist eine TypeScript-Klasse mit <code>$state</code>-Feldern und Methoden“.

### T3 — R-0522: server.html, Router-Übersicht ohne Zählwert und vollständig  [x]
Komponente: scripts · Dateien: docs/developer/server.html, docs/en/developer/server.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @a921f9cb 2026-10-19T11:37:51+02:00
Review: approve (.ah-out/review/doc-fixes-2/T3.verdict.json)
Änderung: DE und EN, gleiche Zeilen. Geprüft auf main@81764c43: `apps/server/app/main.py:450-471` bindet 18 Router ein, `apps/server/app/modules/` hat 12 Module, die Tabelle 12 Zeilen.
(1) `:52` wird zahlenlos: „12 Top-Level-Router“ bzw. „Twelve top-level routers“ fällt weg. Der Satz sagt, dass die Module unter `apps/server/app/modules/` ihre Router mitbringen und `apps/server/app/main.py` sie einbindet.
(2) Beifang, derselbe Fund: Die Tabelle `:53-69` bekommt die Zeilen, die heute fehlen:
- `/api/notifications` (`modules/notifications/`): Feed, `/unread-count`, `/read`, SSE `/stream`, dazu `/api/users/me/notification-prefs`; Verweis auf den Abschnitt Notification-Hub.
- `/api/internal`: Service-zu-Service mit `X-Internal-Key`, `GET /servers` aus `modules/servers/router.py` für den Tag-Sync des Monitorings und `POST /events` aus `modules/notifications/router.py`.
(3) Der Callout `:73` widerspricht der `/api/audit`-Zeile `:61`: `audit` fällt aus dem Titel, und der Satz „Ein dedizierter Audit-Log-Router existiert (Stand v0.23.2) nicht; Logging erfolgt über Python-Logging und Hook-Events“ (EN „There is no dedicated audit-log router as of v0.23.2; …“) entfällt.
Sonst bleibt die Seite unverändert; feste Zählwerte keine.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/server.html + docs/en/developer/server.html (die Task ist die Doku); kein CHANGELOG
Beweis: main@81764c43 · `grep -n -o -E '12 Top-Level-Router|Twelve top-level routers|<code>alerts</code>/<code>audit</code>/<code>settings</code>|Audit-Log-Router existiert|no dedicated audit-log router' docs/developer/server.html docs/en/developer/server.html` → DE `:52`, `:73` (2×), EN `:52`, `:73` (2×); nach der Task leer · `grep -c -E '<td><code>/api/(notifications|internal)' docs/developer/server.html docs/en/developer/server.html` → je `0`, danach je `2`
Dedup-Key: bug:docs:webui.html:stale-tree
HEAD: 81764c43
Semantik: Soll ist der Code: `apps/server/app/main.py:450-471` (18 `include_router`, darunter `audit_router` `:454`, die Notification-Router `:466-469`, `servers_internal_router` `:470`), `apps/server/app/modules/notifications/router.py:39-41`, `apps/server/app/modules/notifications/stream.py:26`, `apps/server/app/modules/servers/router.py:66`, `git ls-files apps/server/app/modules` (12 Module). Doku: `docs/developer/server.html:190` — „Clients holen den Feed über <code>GET /api/notifications</code>“, `:185` — „<code>POST /api/internal/events</code> (Auth <code>X-Internal-Key</code>“, `:61` (`/api/audit`). Falsche Doku-Stellen: `:52` — „12 Top-Level-Router unter <code>apps/server/app/modules/</code>“, `:73` — „Ein dedizierter Audit-Log-Router existiert (Stand v0.23.2) nicht“.

### T4 — R-0523: Doku nennt nur SSH, RDP und Web; api/-Zeile in desktop.html vollständig  [x]
Komponente: desktop-ui · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, docs/index.html, docs/en/index.html, docs/admin/index.html, docs/en/admin/index.html
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @e95f312b 2026-10-19T11:42:32+02:00
Review: approve (.ah-out/review/doc-fixes-2/T4.verdict.json)
Änderung: Sechs Ein-Zeilen-Korrekturen. `ipc.inventory.test.ts` liest `desktop.html` DE+EN.
(1) VNC fällt weg; jede Stelle nennt nur die drei Arten, die der Server kennt:
- `docs/developer/desktop.html:72` DE+EN: „(ssh/rdp/vnc/web/custom, …)“ wird „(ssh/rdp/web, …)“; `custom` gibt es auch nicht.
- `docs/index.html:213` und `docs/en/index.html:211`: „RDP, SSH, VNC und HTTP“ ohne VNC.
- `docs/admin/index.html:86`: „RDP-, SSH-, VNC- oder HTTP-Sessions“ ohne VNC.
- `docs/en/admin/index.html:40`: „RDP/SSH/VNC launcher“ wird „RDP/SSH/web launcher“.
(2) `docs/developer/desktop.html:57` DE+EN: Die `api/`-Zeile nennt auch `notifications.ts` und `request.ts`.
(3) Beifang, ein Zählwert wie in T3: `docs/en/admin/index.html:38` „9 routers“ wird zahlenlos.
Sonst nichts; die übrigen Abschnitte von `desktop.html` gehören R-0430 und R-0524 (Kopf).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/bridge/ipc.inventory.test.ts
Doku: die Task ist die Doku (DE+EN); kein CHANGELOG
Beweis: main@81764c43 · `git grep -n -o -i -w vnc -- docs README.md DEVELOPMENT.md ':!docs/admin/frp-tunnel.html' ':!docs/en/admin/frp-tunnel.html'` → `docs/admin/index.html:86`, `docs/developer/desktop.html:72`, `docs/en/admin/index.html:40`, `docs/en/developer/desktop.html:72`, `docs/en/index.html:211`, `docs/index.html:213`; `grep -n -o -E '9 routers|/custom' docs/en/admin/index.html docs/developer/desktop.html docs/en/developer/desktop.html` → EN-Index `:38`, `desktop.html` je `:72`; beide nach der Task leer · `grep -c -E 'notifications\.ts.*request\.ts|request\.ts.*notifications\.ts' docs/developer/desktop.html docs/en/developer/desktop.html` → je `0`, danach je `1`
Dedup-Key: bug:docs:desktop.html:vnc-connection-kind
HEAD: 81764c43
Semantik: Soll ist der Code: `apps/server/app/modules/connections/schemas.py:45` (`kind: Literal["ssh", "rdp", "web"]`), `apps/desktop/src-tauri/src/connection/mod.rs:24-35` (Ssh, Rdp, Web), `git ls-files apps/desktop/ui/src/lib/api` (mit `notifications.ts` und `request.ts`), `apps/server/app/main.py:450-471`. Doku: `docs/developer/desktop.html:43` — „connection/       RDP/SSH/Web-Launcher“, `docs/examples/webhook_add_connection.py:31` — „connection.kind muss ssh, rdp oder web sein“. Falsche Doku-Stellen: `docs/developer/desktop.html:72` — „(ssh/rdp/vnc/web/custom, server-seitiges CRUD)“, `docs/index.html:213` — „Verbindungsaufbau via RDP, SSH, VNC und HTTP“.

### T5 — R-0523: Paketbeschreibung des Desktop-Clients ohne VNC  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/tauri.conf.json, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @49ae4d00 2026-10-19T11:51:23+02:00
Review: approve (.ah-out/review/doc-fixes-2/T5.verdict.json)
Änderung: `bundle.longDescription` (`tauri.conf.json:36`) sagt „(RDP, SSH, HTTP)“ statt „(RDP, SSH, VNC, HTTP)“; der Rest des Texts bleibt, auch die Sprache.
- Der Text landet im Desktop-Paket: Das DEB schreibt ihn als Fortsetzung von `Description:` in `control` (tauri-bundler `crates/tauri-bundler/src/bundle/linux/debian.rs`, gelesen 2026-10-19). Ob RPM und MSI ihn nutzen, ist nicht verifiziert. Das Release baut `--bundles deb,rpm` (`.github/workflows/release.yml:75`).
- CHANGELOG `[Unreleased]` → `### Fixed` (`:347`) bekommt eine Zeile, umlautfrei: Die Paketbeschreibung des Desktop-Clients nennt kein VNC mehr; der Client oeffnet SSH-, RDP- und Web-Verbindungen (R-0523).
- Der desktop-rs-Lauf baut die Crate. Dabei liest `tauri_build::build()` (`build.rs`) bzw. `tauri::generate_context!()` (`main.rs:141`) die `tauri.conf.json`; kaputtes JSON bricht den Build.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: CHANGELOG.md
Beweis: main@81764c43 · `grep -n -o VNC apps/desktop/src-tauri/tauri.conf.json` → `:36`; nach der Task leer
Dedup-Key: bug:docs:desktop.html:vnc-connection-kind
HEAD: 81764c43
Semantik: wie T4: `apps/server/app/modules/connections/schemas.py:45`, `apps/desktop/src-tauri/src/connection/mod.rs:24-35`; Doku `docs/developer/desktop.html:43` — „connection/       RDP/SSH/Web-Launcher“. Falsche Stelle: `apps/desktop/src-tauri/tauri.conf.json:36` — „Verwaltet Remote-Verbindungen (RDP, SSH, VNC, HTTP)“.
