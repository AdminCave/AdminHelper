<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Doku-Fixes: Projektbäume, Agent-Deployment, Hook-Helfer — Task-Ledger
Status: aktiv · Branch: feature/doc-fixes · Review: pro Task
Spec: Roadmap R-0489, R-0490
Heavy: none — nur Doku und ein hermetischer Server-Test über `docs/examples`; keine API-, Gateway-, PKI-, Agent-, Compose- oder Install-Änderung
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Zwei BUG-Zeilen als Paket (Kevin 2026-10-18). Das Soll ist der Code: Jede Task nennt unter `Semantik:` die
Code-Stelle und die falsche Doku-Stelle mit Zitat; der builder greppt beide vor dem Schreiben neu (Zeilen:
main@a23a4387). Doku hat keinen roten Test, außer in T4: `Beweis:` ist ein grep, der auf `HEAD:` die veralteten
Stellen zeigt. `verify.sh` kennt keine Komponente, die die echte Doku prüft; `Verify:` von T1–T3 ist der formale Lauf
`scripts -- doc_smoke_test` (prüft den Checker an Fixtures). Den echten Check fährt der builder bei T1–T3 zusätzlich,
`python3 scripts/dev/doc-smoke.py --paths --env --strict` mit Exit 0, Ergebnis in den Commit-Body (in der PR-CI
`.github/workflows/ci.yml:874`). Feste Zählwerte werden nicht nachgezählt, sondern fallen weg (wie doc-drift und
R-0383). Kein CHANGELOG-Eintrag: Doku- und Beispielkorrektur ohne Verhaltensänderung (wie doc-drift).

Disjunkt zu doc-drift (`feature/doc-drift`, R-0386/R-0388/R-0442/R-0444, nicht gemergt). Dieselben Dateien README.md,
DEVELOPMENT.md und `docs/{,en/}admin/agent-deployment.html`, aber andere Abschnitte. doc-drift ändert (Zeilen auf
main@a23a4387): README `:106`, `:109`, `:440-441`, `:463`, `:476-477`, `:480`; DEVELOPMENT `:1397-1398`, `:1421`,
`:1434-1435`, `:1437`, `:1439`; DE agent-deployment `:39`, `:136`; EN `:148`. Diese Zeilen und ihre Abschnitte bleiben
unberührt: Monitoring- und Desktop-Block der Bäume, DE „Was macht der Agent?“ `:36-41`, DE Provisionierungs-Prosa `:136`
und `:147-150`, EN `:132` und `:148-151`. Zwischen einem eigenen Hunk und einer doc-drift-Zeile bleiben mindestens zwei
unveränderte Zeilen. Probe 2026-10-18: mit einer Zeile Abstand konfligiert git, mit zwei nicht. T1 und T2 schließen nur
mit `git -C <wt> merge-tree --write-tree HEAD feature/doc-drift` mit Exit 0 ab.

Nicht in diesem Ledger: (a) R-0489 „Modell-Liste in desktop.html“ (`docs/developer/desktop.html:57`, es fehlen
`ansible`, `maintenance`, `monitoring`, `shared`) liegt im Baum `:38-64`, den doc-drift T3 neu schreibt. (b) Der Rest der
agent-deployment-Gliederung berührt doc-drift-Zeilen und folgt erst nach dessen Merge: EN ohne „What does the agent
do?“, EN `:148` mit Metrik-Push und Upgrade-Hinweis (DE: `:38`, `:40`), EN `:148` „or the Windows service
(auto-start)“ (provision registriert unter Windows keinen Dienst, `apps/agent/internal/monitor/platform_windows.go:13-14`).

### T1 — R-0489: Server- und Web-Block in README und DEVELOPMENT wie der Code  [x]
Komponente: scripts · Dateien: README.md, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @6545b606 2026-10-19T09:25:36+02:00
Review: approve (.ah-out/review/doc-fixes/T1.verdict.json)
Änderung: (1) DEVELOPMENT `:1391-1392` zählt alle zwölf Module unter `apps/server/app/modules/` auf wie README `:432-433`; es fehlen `audit`, `enrollment`, `notifications`, `provisioning`. „12 Module“ (`:1387`) bleibt, die Zahl stimmt und die vollständige Liste daneben belegt sie. (2) Der Web-Block nennt keine festen Zählwerte und keine unvollständigen Aufzählungen mehr: README `:455` („9 API modules + 6 stores“), `:456` („5 production pages“), `:457` („9 modal components“), `:459` (Playwright mit 2 von 5 Specs); DEVELOPMENT `:1412` („9 Module (client + 7 Domain-Wrapper + types)“), `:1413` („6 Stores“), `:1415` („5 Produktiv-Pages“), `:1416` („9 Modal-Komponenten“), `:1417` (3 von 5 Specs). Heute sind es 7 Stores, 10 Modals und 5 Specs. Alles andere im Server-Block sowie Monitoring-, Agent- und Desktop-Block bleibt unverändert (Monitoring und Desktop gehören doc-drift T2).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: README.md, DEVELOPMENT.md (die Task ist die Doku; README gibt es nur englisch, DEVELOPMENT nur deutsch)
Beweis: main@a23a4387 · `grep -n -E '#   ansible, monitoring_proxy$|[0-9]+ Module \(|# 6 Stores$|[0-9]+ Produktiv-Pages|[0-9]+ Modal-Komponenten|[0-9]+ API modules|[0-9]+ production pages|[0-9]+ modal components|Playwright \(' README.md DEVELOPMENT.md` → README `:455`, `:456`, `:457`, `:459`, DEVELOPMENT `:1392`, `:1412`, `:1413`, `:1415`, `:1416`, `:1417`; nach der Task leer
Dedup-Key: bug:docs:development.md:module-count-drift
HEAD: a23a4387
Semantik: Soll ist der Code. `git ls-files apps/server/app/modules` zeigt zwölf Module: ansible, api_keys, audit, connections, enrollment, frp, hooks, monitoring_proxy, notifications, provisioning, servers, users. `apps/web/src/lib/stores/` hat 7 Stores (mit `theme.ts`), `apps/web/src/modals/` hat 10 Modals, `apps/web/tests/e2e/` hat 5 Specs (`authz`, `crud`, `login`, `smoke`, `theme`). Falsche Doku-Stellen: `DEVELOPMENT.md:1387` „FastAPI-Backend (modularer Monolith, 12 Module)“ mit der Liste `:1391-1392` „users, connections, servers, frp, hooks, api_keys, / ansible, monitoring_proxy“, dazu README `:455` „9 API modules + 6 stores“ und DEVELOPMENT `:1416` „9 Modal-Komponenten“.

### T2 — R-0489: Agent-Deployment DE und EN gleich gegliedert, Windows wie der Code  [x]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/admin/index.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d5be6559 2026-10-19T09:39:30+02:00
Review: approve (.ah-out/review/doc-fixes/T2.verdict.json)
Änderung: Beide Sprachen bekommen dieselbe Abschnittsfolge, außerhalb der doc-drift-Stellen (Kopf): Lead · (DE: Was macht der Agent?) · Schnell-Rollout · Paket installieren (Debian/Ubuntu) · Paket installieren (Rocky/Alma/RHEL) · Paket-Repo · Windows · Erst-Provisionierung mit Callout Ansible/cloud-init · Subcommand-Referenz · Prüfen mit Logs · Upgrade mit Callout Migration. Im Einzelnen:
(1) Der Lead DE `:34` nennt für Windows die einzelne `.exe` statt „MSI/ZIP“. EN `:34` sagt dasselbe wie DE.
(2) EN `:47` und `:56` bekommen Überschriften wie DE: „Install the package (Debian/Ubuntu)“ und „Install the package (Rocky/Alma/RHEL)“; Fedora nennt `scripts/agent-install.sh:7` nicht.
(3) Windows steht in beiden Sprachen in einem eigenen Abschnitt vor der Provisionierung. DE zieht von `:177-184` hinter den Callout, der bei `:133` endet; EN bleibt bei `:128`. Inhalt nach dem Code:
- Das Release enthält `adminhelper-agent-windows-x86_64.exe`, kein MSI und keinen Installer. Das MSI auf der Release-Seite gehört zum Desktop-Client.
- In einer PowerShell als Administrator kopiert `service install` die Binary nach `%ProgramFiles%\AdminHelper\adminhelper-agent.exe`, registriert den Dienst `AdminHelper-Agent` (Autostart, LocalSystem, Neustart nach 60 s) und startet ihn.
- Danach wird provisioniert wie im nächsten Abschnitt.
- Einen frpc-Dienst richtet der Agent unter Windows nicht ein.
DE Erst-Provisionierung Schritt 2 (`:139-145`) bekommt den PowerShell-Befehl wie EN `:141-146`; EN `:141-146` bleibt.
(4) Ansible/cloud-init: EN streicht den letzten Satz von `:45` und bekommt hinter `:151` den Callout wie DE `:152-155`, mit Anker `#quick-rollout`.
(5) Prüfen: DE `:186` und EN `:173` bekommen dieselbe Überschrift und dieselben Befehle: Timer-Status, `frpc.service` (nur mit aktivem Tunnel), `journalctl`, `adminhelper-agent run --once`.
(6) Upgrade: EN bekommt den Abschnitt wie DE `:201-202`. Beide nennen `apt upgrade`/`dnf upgrade` und nicht mehr `/etc/adminhelper/agent.toml`, denn die Datei gibt es nicht. Stattdessen:
- Der Agent schreibt beim Provisionieren `/etc/adminhelper/monitor.conf`, `/etc/adminhelper/identity/`, `/etc/frp/adminhelper.conf` und `/etc/frp/frpc.toml`. Das Paket liefert sie nicht aus, sie bleiben.
- Bei jedem Install und Upgrade aktiviert das Paket den Timer neu, `frpc.service` nur bei vorhandener `frpc.toml`.
Darunter steht in beiden der Migrations-Callout von EN `:188-191`: Replaces/Conflicts (DEB) bzw. Obsoletes/Conflicts (RPM), die Alt-Units entfernt postinst. „preserves the config“ bleibt nur, wenn postinst oder spec es tragen.
(7) Beifang: `docs/admin/index.html:91` „Bereitgestellt als DEB, RPM oder MSI“ und `:99` „via apt/dnf oder MSI“ nennen die `.exe` statt MSI. Der EN-Index nennt kein MSI.
Die Provisionierungs-Prosa bleibt unverändert; in DE kommt in Schritt 2 nur der PowerShell-Block aus (3) dazu.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/agent-deployment.html + docs/en/admin/agent-deployment.html, docs/admin/index.html (die Task ist die Doku)
Beweis: main@a23a4387 · `grep -n -o -E 'signiertes MSI|MSI/ZIP|oder MSI|Grab the latest MSI|the installer registers the Windows service|agent\.toml|<h2>(Debian / Ubuntu|RHEL / Rocky / Fedora|Verification)</h2>|natural Ansible/cloud-init building block' docs/admin/agent-deployment.html docs/en/admin/agent-deployment.html docs/admin/index.html` → DE `:34`, `:178`, `:202`, EN `:45`, `:47`, `:56`, `:129` (2×), `:173`, Index `:91`, `:99`; nach der Task leer
Dedup-Key: bug:docs:development.md:module-count-drift bug:docs:agent-deployment.html:de-en-structure
HEAD: a23a4387
Semantik: Soll ist der Code:
- `.github/workflows/release.yml:177` (`adminhelper-agent-windows-x86_64.exe`) und `:237` (MSI nur für den Desktop-Client).
- `apps/agent/internal/service/service_windows.go`: `:17` (`AdminHelper-Agent`), `:28` (`%ProgramFiles%\AdminHelper`), `:47-55` (`sc create … start= auto, obj= LocalSystem`), `:60` (Recovery), `:68` (Start).
- `apps/agent/internal/monitor/platform_windows.go:13-14`: provision registriert keinen Dienst, nur ein Hinweis auf `service install`.
- `apps/agent/internal/frpc/platform_windows.go:9-15`: kein frpc-Dienst unter Windows.
- `apps/agent/internal/config/paths.go:17`, `:19`, `:23`, `:30`.
- `apps/agent/deb/DEBIAN/postinst:12-18` und `:24-28`, `apps/agent/deb/DEBIAN/control:7-8`, `apps/agent/rpm/adminhelper-agent.spec:19-24` und `%post` `:56-73`.
Doku-Stellen: `docs/developer/agent.html:159` — „Kopiert die Binary nach <code>%ProgramFiles%\AdminHelper\</code>, registriert via <code>sc create</code> (<code>binPath=&lt;exe&gt; run</code>, <code>start= auto</code>, <code>obj= LocalSystem</code>)“. Für gleiche Inhalte in DE und EN `.claude/rules/docs.md:16` — „zweisprachiges HTML (`docs/…` DE, `docs/en/…` EN)“. Falsch heute: DE `:178` „wird als signiertes MSI verteilt“, EN `:129` „the installer registers the Windows service“, DE `:202` „die Konfig (<code>/etc/adminhelper/agent.toml</code>)“.

### T3 — R-0490: hooks.html nennt die injizierten Helfer  [ ]
Komponente: scripts · Dateien: docs/developer/hooks.html, docs/en/developer/hooks.html
Änderung: Hinter den Absatz `:71` kommt (DE und EN) eine Liste der Namen, die der Worker jedem Script bereitstellt (`apps/server/app/modules/hooks/script_worker.py:125-141`):
- `load_connections()` liefert die Verbindungen als Liste von Dicts, `save_connections(list)` schreibt sie per Upsert, `uuid4()` liefert einen String.
- `http_get(url, headers=None, timeout=10)` und `http_post(url, json_data=None, headers=None, timeout=10)` liefern `{"status", "body", "json"}`. Sie lehnen interne und nicht auflösbare Ziele ab (SSRF-Schutz, `:56-62`, `:74-80`), folgen keinem Redirect, und die Antwort ist auf 1 000 000 Bytes begrenzt (`:31`).
- `result` (Dict), `logs` (Liste), `log(msg)` und `print(...)`: `log` und `print` schreiben ins Log, höchstens 1000 Zeilen zu je 4096 Zeichen (`:112-113`, `:115-124`).
- Ein Context-Key mit dem Namen eines Helfers bricht den Hook mit Fehler ab (`:147-161`).
`:71` selbst bekommt nur einen Verweis auf die Liste. Environment-Modell und Fehlerverhalten bleiben unverändert.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/hooks.html + docs/en/developer/hooks.html (die Task ist die Doku)
Beweis: main@a23a4387 · `grep -n -o -E '<code>(load_connections|save_connections|http_get|uuid4)' docs/developer/hooks.html docs/en/developer/hooks.html` → leer (`http_post` steht nur im JSON-Beispiel `:68`); nach der Task stehen alle vier Namen in beiden Dateien
Dedup-Key: bug:docs:hooks.html:injected-helpers
HEAD: a23a4387
Semantik: Soll ist der Code. `apps/server/app/modules/hooks/script_worker.py:125-141` bindet im `namespace` `print`, `load_connections`, `save_connections`, `http_get`, `http_post`, `uuid4`, `log`, `result` und `logs`. Dazu die Signaturen `:52` und `:70-71`, `_RESERVED` `:147-157` und der Docstring `apps/server/app/modules/hooks/script_runner.py:19-27`. Falsche Doku-Stelle: `docs/developer/hooks.html:71` — „Ausgaben laufen über das <code>result</code>-Dict und <code>log(...)</code>“, EN `:71` — „output goes through the <code>result</code> dict and <code>log(...)</code>“.

### T4 — Beifang zu R-0490: Hook-Beispiele rufen `http_post` mit `json_data`  [ ]
Komponente: server · Dateien: apps/server/tests/test_hook_examples.py, docs/examples/event_hook_notify.py, docs/examples/webhook_http_import.py
Änderung: Neuer Test `apps/server/tests/test_hook_examples.py`, SPDX-Header per `reuse annotate`. Der Test:
- liest jede Datei unter `docs/examples/*.py` (Repo-Wurzel über `Path(__file__).resolve().parents[3]`; eine leere Liste ist ein Fehler),
- sucht mit `ast` die Aufrufe von `http_get` und `http_post`,
- prüft, dass jedes Schlüsselwort ein Parameter von `script_worker._safe_http_get` bzw. `_safe_http_post` ist (`inspect.signature`),
- nennt in der Meldung Datei, Zeile, Argument und die erlaubten Namen.
Auf HEAD ist er rot an `event_hook_notify.py:35` (`json=`). Danach wird `json=` zu `json_data=` in `event_hook_notify.py:35` und in den Kopfkommentaren `event_hook_notify.py:16` und `webhook_http_import.py:29`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hook_examples.py
Doku: docs/examples/event_hook_notify.py, docs/examples/webhook_http_import.py (die Task ist die Doku); kein CHANGELOG
Beweis: main@a23a4387 · `grep -n -E 'http_post\([^)]*json=' docs/examples/*.py` → `event_hook_notify.py:16`, `:35`, `webhook_http_import.py:29`; der neue Test ist vor der Änderung an den Beispielen dreimal identisch rot und nennt `event_hook_notify.py:35` mit `json`; danach grün, der grep leer
Orakel: contract — Aufrufe in den Beispielen gegen die Signatur der Worker-Helfer
Dedup-Key: bug:docs:examples:http-post-json-kwarg
HEAD: a23a4387
Semantik: Soll ist der Code. `apps/server/app/modules/hooks/script_worker.py:70-71` definiert `_safe_http_post(url, json_data=None, headers=None, timeout=10)` ohne `**kwargs`. `json=` wirft deshalb `TypeError`, und das Beispiel loggt das im `except` als Fehler. Falsche Doku-Stelle: `docs/examples/event_hook_notify.py:16` — „http_post(url, json=None, headers=None, timeout=10)“. Das JSON-Beispiel `docs/developer/hooks.html:68` nutzt schon `json_data=`.
