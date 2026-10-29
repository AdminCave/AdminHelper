<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Doku-Nachzüge: hingenommene Restrisiken, Drift zwischen Doku und Code, CHANGELOG-Glättung — Task-Ledger
Status: erledigt · Branch: feature/docs-residual-risks · Review: pro Task
Spec: docs/features/docs-residual-risks.md (Roadmap R-0798, R-0453, R-0754, R-0758, R-0769, R-0770, R-0791, R-0794, R-0595, R-0782, R-0602, R-0609, R-0732, R-0792, R-0601)
Heavy: linux-full — `docker-compose.yml` (nur ein Kommentar) und das Monitoring-Image (`apps/monitoring/docker-entrypoint.sh`, zwei Meldungstexte) in T10, bei Kevins Ja zu T15 `apps/desktop/src-tauri/src/frpc.rs` (Desktop-Tunnel); läuft im Sammellauf über `main`. Kein scenario: weder FRP-Konfiguration noch Visitor-TOML noch Datenpfad ändern sich, T15 ändert nur, wann der Desktop seinen frpc stoppt (Unit-Test). Kein windows über die PR-CI hinaus: kein plattformspezifischer Code
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Die zwei hingenommenen Restrisiken stehen in der Doku, wie der Code sich verhält: ein von VictoriaMetrics
abgelehnter Stapel kostet auch fremde Zeilen (R-0798, Kevin 2026-10-22: hinnehmen, ein Satz, DE + EN); Benutzer
löschen oder Gerät widerrufen sperrt die API, nicht den Tunnel, wirksam ist erst das Rotieren der `secretKey`s und von
`auth.token` (R-0453). (2) Die Doku-Drift aus R-0754, R-0758, R-0609, R-0794, R-0769, R-0770, R-0602, R-0792 ist
behoben, die CHANGELOG-Einträge zu R-0551 und R-0659 sind vor dem nächsten Release genau (R-0595, R-0782). (3)
`apps/data/` ist ignoriert (R-0791), `docs/examples` bleibt frei von Adressen außerhalb RFC 5737 (R-0601),
Compose-Kommentar und Entrypoint-Meldungen stimmen (R-0732). (4) Auf Kevins Ja stoppt der Desktop frpc bei einem 403
auf das Visitor-Bundle (T15). Zeilenangaben: origin/main@b25c65a6, für #265 `origin/feature/monitoring-io@13f340e4`;
der builder greppt sie vor dem Schreiben neu.

Für alle Tasks:
- Reihenfolge und Abhängigkeiten: T1 und T2 erst, wenn PR #265 (`monitoring-io`) auf `main` und `main` in diesen
  Branch gemergt ist; T11 erst nach dem Merge von `feature/docs-drift` (bringt `apps/web/src/vite-config.test.ts` und
  ändert `docs/en/developer/index.html`); T14 erst nach dem Merge von PR #262 (`desktop-ui-fixes`, bringt den Eintrag
  zu R-0659); T6 nach T5 (Anker); T15 nach T7 und nur nach Kevins Antwort. Alle übrigen sind unabhängig.
- Risikopfade (`scripts/dev/review-risk.txt`): `docker-compose.yml` (T10) und `apps/desktop/src-tauri/src/frpc.rs`
  (T15) bekommen zusätzlich `security`.
- Doku-Tasks (Komponente `scripts`, Verify `doc_smoke_test`): der builder fährt zusätzlich
  `python3 scripts/dev/doc-smoke.py --paths --env --strict` (Exit 0, Ergebnis in den Commit-Body). DE und EN gleiche
  Stelle, gleicher Inhalt; Regeln `.claude/rules/docs.md`. HTML-Entities wie in der jeweiligen Datei.
- Parallele Branches ändern dieselben Dateien an anderen Stellen (Spec, Betroffene Komponenten): vor dem Bau
  `git fetch` und `origin/main` hineinmergen, nur die genannten Absätze anfassen.
- Neue Code-Strings und Kommentare englisch; CHANGELOG umlautfrei (ae/oe/ue), Gedankenstrich „—“, neue Einträge unter
  `## [Unreleased]`. CHANGELOG nur T15 (T13 und T14 korrigieren bestehende Einträge); T1–T12 ändern kein Verhalten
  für Nutzer.
- Öffentliches Repo: keine Homelab-Namen, keine echten Adressen (nur RFC 5737), keine Sicherheitsfunde über das
  hinaus, was die Spec nennt.

### T1 — Monitoring-Entwicklerseite: Stapelverlust bei Antworten unter 500 als hingenommenes Restrisiko (R-0798)  [x]
Komponente: scripts · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ec21fca9 2026-10-29T09:42:08+01:00
Review: approve (.ah-out/review/docs-residual-risks/T1.verdict.json)
Änderung: Im Absatz zum Schreibweg (nach #265 `docs/developer/monitoring.html:263`, EN `:263`) hinter dem Satz zur 4xx-Antwort ein Satz, DE und EN gleich: Ein Stapel trägt die Zeilen aller Checks und Agent-Reports, die seit dem letzten POST anfielen, also auch die anderer Server; lehnt VictoriaMetrics ihn wegen einer einzigen ungültigen Zeile ab, sind bis zu 10&nbsp;000 Zeilen verloren, darunter fremde. Dasselbe gilt für jede andere Antwort unter 500, die nicht 2xx ist, auch eine Weiterleitung (3xx; der Client folgt ihr nicht). Das ist ein hingenommenes Restrisiko (Kevin 2026-10-22); die WARNING-Zeile von `monitor.victoria` nennt Status und Zahl der verlorenen Zeilen. Kein Satz zu einem Verhalten von VictoriaMetrics, das die Spec nicht belegt (Spec, Externe Integrationen: der Normalmodus verwirft den ganzen Body laut Probe, die Doku schweigt; ob VictoriaMetrics selbst 3xx sendet, ist nicht verifiziert). Werte am Code nach #265 neu greppen: `_MAX_BATCH_LINES` (`apps/monitoring/app/core/victoria.py:22`), `batch = self._pending[:_MAX_BATCH_LINES]` (`:181`), `resp.is_success` (`:203`), `if resp.status_code < 500:` (`:205`), Log-Text (`:207`).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Task ist die Doku; kein CHANGELOG (Kevin: hinnehmen, kein Code)
Abhängt von: PR #265 auf `main` und in diesen Branch gemergt
Beweis: origin/feature/monitoring-io@13f340e4 · `git show origin/feature/monitoring-io:apps/monitoring/app/core/victoria.py | grep -n '_MAX_BATCH_LINES = \|status_code < 500\|is_success'` → `:22`, `:203`, `:205`; `git show origin/feature/monitoring-io:docs/developer/monitoring.html | sed -n 263p | grep -c 'anderer\|10&nbsp;000 Zeilen verloren\|3xx'` → 0. Probe gegen VictoriaMetrics v1.144.0 (Image aus `docker-compose.yml:407`), dreimal identisch: Body aus zwei gültigen Zeilen und `probe_bad,check_id=x value=1i,` → HTTP 400, 0 gültige Reihen gespeichert; mit `Stream-Mode: 1` → HTTP 204, 2 Reihen
Orakel: contract — der Satz gegen den Fehlerpfad von `_send` und die Stapelbildung in `_run`
Dedup-Key: bug:monitoring:victoria-4xx-batch-loss
HEAD: b25c65a6
Semantik: Kevin 2026-10-22: „Den Verlust bei 4xx-Antworten von VictoriaMetrics hinnehmen und in einem Satz dokumentieren (DE + EN).“

### T2 — Monitoring-Admin-Seite: Labels und Beispielabfrage wie im Code (R-0754)  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @e2d31bbf 2026-10-29T09:48:36+01:00
Review: approve (.ah-out/review/docs-residual-risks/T2.verdict.json)
Änderung: `docs/admin/monitoring.html:230` (EN `:230`), die zwei Sätze zu Labels und Debug-Zugriff: Check-Ergebnisse tragen `check_id`, `check_type`, `name` und bei Server-Checks `server_id` (`apps/monitoring/app/core/victoria.py:155-157`); die Agent-Metriken `monitor_agent_*` tragen `server_id`, Platten dazu `mount`, Temperaturen `sensor` (`apps/monitoring/app/routers/agent.py:124`, `:139`, `:147`). `device` nur, wenn #265 es nicht entfernt hat (nach #265 schreibt der Agent-Report keine SMART-Zeilen mehr, `agent.py:126-128` auf dem Branch). VictoriaMetrics speichert das Feld `value` als `<measurement>_value`; die Beispielabfrage wird `…/api/v1/query?query=monitor_check_status_value` statt `up` (ohne Self-Scrape gibt es `up` nicht, `docker-compose.yml:416`; Reihenname `apps/monitoring/app/routers/checks.py:481`). Nach #265 alle Label-Stellen neu greppen (`git grep -n 'tags = \|_tags = ' apps/monitoring/app`).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Task ist die Doku; kein CHANGELOG
Abhängt von: PR #265 auf `main` und in diesen Branch gemergt
Beweis: origin/main@b25c65a6 · `sed -n 230p docs/admin/monitoring.html | grep -o '<code>server</code>, <code>check</code>, <code>type</code>'` → ein Treffer; `sed -n 155,157p apps/monitoring/app/core/victoria.py` → `tags = {"check_id": …, "check_type": …, "name": …}` plus `server_id`; `sed -n 124p apps/monitoring/app/routers/agent.py` → `base_tags = {"server_id": server_id}`; `git grep -n 'retentionPeriod\|selfScrape' docker-compose.yml` → nur `:416` `-retentionPeriod`
Orakel: contract — Labelnamen der Doku gegen die `tags`-Dicts, die `format_line` bekommt
Dedup-Key: bug:docs:monitoring.html:labels-drift
HEAD: b25c65a6

### T3 — Server-Entwicklerseite: Event-Liste wie im Code (R-0758)  [x]
Komponente: scripts · Dateien: docs/developer/server.html, docs/en/developer/server.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @2014a819 2026-10-29T10:12:49+01:00
Review: approve (.ah-out/review/docs-residual-risks/T3.verdict.json)
Änderung: Die Liste „Aktive Event-Typen“ (`docs/developer/server.html:164-171`, EN gleiche Zeilen): `api_key.created`, `api_key.deleted` raus (kein `fire_event` dafür, `apps/server/app/modules/api_keys/router.py`); neu `server.startup` (`apps/server/app/main.py:382`) und `alert.triggered` (`apps/server/app/modules/notifications/router.py:208-209`). Die übrigen Einträge stimmen (`git grep -n -A1 'fire_event(' apps/server/app`). Nur diese Liste; die Abschnitte, die `feature/docs-drift` T3 und `feature/compose-hardening` T11 ändern, bleiben.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Task ist die Doku; kein CHANGELOG
Beweis: origin/main@b25c65a6 · `git grep -n -A1 'fire_event(' apps/server/app | grep -o '"[a-z_]*\.[a-z_.]*"' | sort -u` → 20 Events, darunter `"server.startup"` und `"alert.triggered"`, keins mit `api_key`; `grep -n 'api_key\.created\|server\.startup\|alert\.triggered' docs/developer/server.html` → nur `:168` `api_key.created`
Orakel: contract — Liste der Doku gegen die `fire_event`-Literale
Dedup-Key: bug:docs:server.html:event-list-drift
HEAD: b25c65a6
Semantik: `docs/developer/hooks.html:53`, `:58` nennen `server.startup` und `alert.triggered` schon als Events für Hooks.

### T4 — Betrieb: Logger des Schedulers vollständig (R-0609)  [x]
Komponente: scripts · Dateien: docs/admin/betrieb.html, docs/en/admin/operations.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @18283d92 2026-10-29T10:20:32+01:00
Review: approve (.ah-out/review/docs-residual-risks/T4.verdict.json)
Änderung: `docs/admin/betrieb.html:124` / `docs/en/admin/operations.html:83`, Punkt `app.modules.hooks.scheduler`: neben gescheiterten Schedule-Hooks (Name, Fehlertext) auch die Warnung zu einem Schedule-Hook mit unlesbarem Intervall (einmal je Hook, `apps/server/app/modules/hooks/scheduler.py:210-215`) und die System-Jobs (Aufräumen von Blacklist, Enrollment- und Provision-Token, Zertifikats-Register, Audit, Benachrichtigungen, Outbox-Versand, frps-Überwachung; Ergebnis als INFO, ein Fehler mit Traceback, `:262-275`, Jobs `:304-467`); weiter im Log des `scheduler`-Dienstes. Die Job-Liste vor dem Schreiben neu greppen (`grep -n '_run_in_session("' apps/server/app/modules/hooks/scheduler.py`).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Task ist die Doku; kein CHANGELOG
Beweis: origin/main@b25c65a6 · `grep -n 'logger\.' apps/server/app/modules/hooks/scheduler.py` → `:137`, `:139` (Hooks), `:210` (Intervall), `:272`, `:274` (System-Jobs); `sed -n 124p docs/admin/betrieb.html` nennt nur „gescheiterte Schedule-Hooks mit Namen und Fehlertext“
Orakel: contract — Beschreibung des Loggers gegen seine Aufrufe
Dedup-Key: ref:docs:betrieb:scheduler-logger-scope
HEAD: b25c65a6

### T5 — FRP-Tunnel-Doku: Vertrauenskette wie im Code, Abschnitt „Zugang zum Tunnel entziehen“ (R-0794, R-0453)  [x]
Komponente: scripts · Dateien: docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, docs/adr/0001-unified-pki-and-secure-deployment.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @87fd0717 2026-10-29T10:40:16+01:00
Review: approve (.ah-out/review/docs-residual-risks/T5.verdict.json)
Änderung: (1) `docs/admin/frp-tunnel.html:54` (EN `:54`), `trustedCaFile`: frpc (Agent, Desktop) vertraut der `tunnel`-Kette; frps vertraut der `tunnel`-Kette und dem `access`-Intermediate, weil der Desktop-Visitor sein `access`-Zertifikat vorlegt (`apps/ca-issuer/app/main.py:54-56`, `apps/ca-issuer/app/storage.py:264`). (2) ADR 0001 Tabelle D2 (`docs/adr/0001-unified-pki-and-secure-deployment.md:34`): „Agent pinnt die Root“ → der Agent vertraut nur seiner Kettendatei `ca.crt` (Intermediate + Root, `apps/agent/internal/enroll/enroll.go:39`, `apps/agent/internal/httpclient/httpclient.go:77-92`); die ADR ist nur deutsch. (3) Neuer Abschnitt `<h2 id="revoke-access">Zugang zum Tunnel entziehen</h2>` (EN „Revoking tunnel access“, gleiche `id`) hinter „FRP `auth.token` rotieren“ (`:65-76`): Benutzer löschen, ein Gerät widerrufen, eine Server-Zuordnung oder die Admin-Rolle entziehen sperrt die API, aber nicht den Tunnel. frps prüft beim Verbindungsaufbau nur, ob das Client-Zertifikat zur Kette passt, keine Sperre (`apps/server/app/modules/frp/config_generator.py:153-156`; frp kennt keine Sperrliste, Spec). Die Visitor-Konfiguration eines Benutzers trägt `auth.token` und den `secretKey` jedes STCP-Tunnels, den er sieht (`config_generator.py:331`, `:354`; ein Admin sieht alle aktiven STCP-Tunnel, sonst die seiner Server, `apps/server/app/modules/frp/generate_router.py:40-61`); der Desktop hält sie, solange der Tunnel läuft, und eine Kopie bleibt gültig. Wer sie hat, erreicht diese Tunnel, bis ihre `secretKey`s rotiert sind (Verweis auf den Absatz „Zum Rotieren …“ unter Tunneltypen, `:102`), und frps, bis sein Zertifikat abläuft oder `auth.token` rotiert ist (Verweis auf den Abschnitt davor, mit dessen Wartungsfenster). Handlung: die `secretKey`s aller Tunnel rotieren, die der Benutzer sah; soll er frps gar nicht mehr erreichen, `auth.token` rotieren. Keine Aussage dazu, was der Desktop bei 403 tut (T15), keine Zertifikatslaufzeiten (ändern sich in `feature/ca-issuer-lifetime`).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Task ist die Doku; kein CHANGELOG
Beweis: origin/main@b25c65a6 · `sed -n 54p docs/admin/frp-tunnel.html` → „beidseitig die <code>tunnel</code>-Kette“; `sed -n 54,57p apps/ca-issuer/app/main.py` → `extra_trust=(intermediates["access"],)`; `sed -n 34p docs/adr/0001-unified-pki-and-secure-deployment.md` → „Agent pinnt die Root“, `sed -n 39p apps/agent/internal/enroll/enroll.go` → `CAFileName = "ca.crt" // pinned trust bundle intermediate + root`; `grep -n 'Widerruf\|löschen\|entzieh' docs/admin/frp-tunnel.html` → keiner
Orakel: contract — Doku gegen `ensure_frps_cert`, `NewMTLS`, `generate_visitor_toml` und `_visible_stcp_tunnels`
Dedup-Key: bug:docs:ca-chain-drift
HEAD: b25c65a6
Semantik: R-0453: „wirksame Sperre nur serverseitig: secretKeys der fuer ihn sichtbaren Tunnel und ggf. frps-Token rotieren. Abschnitt in benutzer.html/users.html und frp-tunnel.html (DE+EN)“; „deaktivieren“ gibt es im Code nicht (`apps/server/app/modules/users/models.py`, kein `is_active`), die Doku spricht von Löschen, Widerrufen und Entziehen.

### T6 — Benutzer-Doku: Löschen und Widerrufen sperren die API, nicht den Tunnel (R-0453)  [x]
Komponente: scripts · Dateien: docs/admin/benutzer.html, docs/en/admin/users.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @e009097f 2026-10-29T10:45:41+01:00
Review: approve (.ah-out/review/docs-residual-risks/T6.verdict.json)
Änderung: Abschnitt „Geräte und Widerruf“ (`docs/admin/benutzer.html:104-112`, EN `docs/en/admin/users.html:98-106`): ein Satz nach der Liste, DE und EN: Löschen und Widerrufen sperren die API sofort; einen Tunnel, dessen Visitor-Konfiguration der Benutzer schon hat, sperren sie nicht. Verweis auf `frp-tunnel.html#revoke-access` (DE `docs/admin/frp-tunnel.html`, EN `docs/en/admin/frp-tunnel.html`). Sonst nichts an diesem Abschnitt; `feature/compose-hardening` T12 ändert die Datei an anderer Stelle.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Task ist die Doku; kein CHANGELOG
Abhängt von: T5
Beweis: origin/main@b25c65a6 · `grep -n 'Tunnel\|secretKey\|auth.token' docs/admin/benutzer.html` → kein Treffer im Abschnitt `:104-112`; `sed -n 174p apps/server/app/modules/users/router.py` → `revoke_identity(db, user.username, SCOPE_ACCESS)` (nur die Identität, kein FRP-Geheimnis)
Orakel: contract — Doku gegen `delete_user` und die FRP-Konfiguration
Dedup-Key: feat:docs:deactivate-user-rotate-secrets
HEAD: b25c65a6

### T7 — Desktop-Doku: Pin-Verifier-Meldungen, Tunnel-Abgleich nach 401/403, TOFU-Text in der EN-Fehlersuche (R-0769, R-0770, R-0453)  [x]
Komponente: scripts · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, docs/en/admin/troubleshooting.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @fff0e837 2026-10-29T11:01:07+01:00
Review: approve (.ah-out/review/docs-residual-risks/T7.verdict.json)
Änderung: (1) `docs/developer/desktop.html:240` (EN `:240`), letzter Satz: Die Pin-Verifier liefern nie rohes `UnknownIssuer`; ein geänderter Pin meldet sich mit stabilem Code (`ERR_TOFU_PIN_MISMATCH`, `apps/desktop/src-tauri/src/tofu.rs:271-274`; `ERR_CA_PIN_MISMATCH`, `apps/desktop/src-tauri/src/enrollment.rs:708-711`), ein unbrauchbarer Schlüsselbund mit einer Meldung ohne Code (`tofu.rs:276-283`). (2) `:259` (EN `:259`), der Satz „jeder andere Fehler (Netz, 5xx, 401 nach gescheitertem Refresh, …) lässt den laufenden frpc unangetastet“: Scheitert die Erneuerung der Sitzung, endet die Sitzung und mit ihr frpc (`apps/desktop/src-tauri/src/session.rs:320-332`, `apps/desktop/src-tauri/src/main.rs:199-206`); jeder andere Fehler (Netz, 5xx, ein 401 trotz erneuerter Sitzung, ein 403, eine von der Allow-List abgewiesene TOML) lässt den laufenden frpc stehen (`apps/desktop/src-tauri/src/frpc.rs:277-287`). (3) `docs/en/admin/troubleshooting.html:73`: statt `AdminHelper TOFU: … changed` den echten (deutschen) Text zitieren: `ERR_TOFU_PIN_MISMATCH: AdminHelper TOFU: Das Server-Zertifikat für … hat sich seit dem ersten Verbinden geändert …` (`tofu.rs:272-274`); die DE-Seite zitiert schon deutsch und bleibt. `feature/docs-drift` T5 ändert dieselbe EN-Datei an anderen Zeilen (`:63`, `:123`).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Task ist die Doku; kein CHANGELOG
Beweis: origin/main@b25c65a6 · `sed -n 240p docs/developer/desktop.html | grep -o 'ihre eigenen <code>ERR_\*</code>-Meldungen'` → ein Treffer, `sed -n 277,283p apps/desktop/src-tauri/src/tofu.rs` → Meldung ohne `ERR_`; `sed -n 259p docs/developer/desktop.html | grep -o '401 nach gescheitertem Refresh'` → ein Treffer, `sed -n 204,205p apps/desktop/src-tauri/src/main.rs` → `on_sign_in_change` → `frpc::stop_frpc`; `sed -n 73p docs/en/admin/troubleshooting.html | grep -o 'AdminHelper TOFU: … changed'` → ein Treffer, `sed -n 272p apps/desktop/src-tauri/src/tofu.rs` → deutscher Text
Orakel: contract — Doku gegen die Meldungstexte der Verifier und den Stopp bei Sitzungsende
Dedup-Key: bug:docs:desktop.html:tofu-err-codes
HEAD: b25c65a6
Semantik: R-0770 (Dedup `bug:docs:troubleshooting.html:mismatch-text`) und der 401-Teil von R-0453 gehören in dieselbe Task, weil sie dieselben Dateien treffen.

### T8 — Desktop-Kommentare: Pin-Verifier-Meldungen und Test-Helfer wie der Code (R-0769)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/error.rs, apps/desktop/src-tauri/src/session.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @8c7ef7aa 2026-10-29T11:01:27+01:00
Review: approve (.ah-out/review/docs-residual-risks/T8.verdict.json)
Änderung: Nur Kommentare, englisch. (1) `apps/desktop/src-tauri/src/error.rs:7-12`, Doc-Kommentar von `is_unknown_issuer`: Die TOFU- und Enrolled-CA-Verifier geben eigene `General`-Meldungen zurück (ein geänderter Pin mit stabilem `ERR_*`-Code, ein unbrauchbarer Schlüsselbund ohne Code), nie `UnknownIssuer`; die Aussage „matching it is unambiguous“ bleibt. (2) `apps/desktop/src-tauri/src/session.rs:1218-1219`, Doc-Kommentar von `get_allowing_self_signed`: ein GET, das das selbstsignierte Zertifikat des Test-Servers annimmt, gleich was die Sitzung gewählt hat; der Pin ist vorab gesetzt (`serve_self_signed`, `:1183-1187`), es ist also kein erster Kontakt. Kein Code, kein Test ändert sich.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- session::
Doku: keine (Kommentare; die Doku-Seite trägt T7)
Beweis: origin/main@b25c65a6 · `sed -n 11,12p apps/desktop/src-tauri/src/error.rs` → „map it to their own `ERR_*` General messages“, `sed -n 276,283p apps/desktop/src-tauri/src/tofu.rs` → Kommentar „No ERR_TOFU_PIN_MISMATCH“ und Meldung ohne Code; `sed -n 1218p apps/desktop/src-tauri/src/session.rs` → „trusts the server's certificate on first use“, `sed -n 1187p` → `seed_cached_pin`
Orakel: contract — Kommentar gegen den Code, den er beschreibt
Dedup-Key: bug:docs:desktop.html:tofu-err-codes
HEAD: b25c65a6

### T9 — Dev-Setup: `apps/data/` ignoriert, Monitoring-DB-Fallback in DEVELOPMENT.md (R-0791, R-0602)  [x]
Komponente: scripts · Dateien: .gitignore, scripts/tests/gitignore_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @da22960f 2026-10-29T11:06:35+01:00
Review: approve (.ah-out/review/docs-residual-risks/T9.verdict.json)
Änderung: (1) `.gitignore` neben `/data/` (`:115`): `/apps/data/` mit einem Kommentar (Dev-Server aus `apps/server` mit `DATA_DIR=../data`, `DEVELOPMENT.md:762`, `:1435`, schreibt `.secret_key` und `.bootstrap_token` dorthin). (2) `scripts/tests/gitignore_test.sh`, Block „the real .gitignore“: `apps/data/.secret_key` und `apps/data/.bootstrap_token` sind ignoriert (Helfer `ignored "$G" <layout> <pfad>`; ein Layout-Wert außer `dir`/`symlink` legt nichts an, der Pfad muss für `check-ignore` nicht existieren), dazu `apps/server/app/main.py` nicht ignoriert (Gegenprobe, dass die neue Zeile nicht zu weit greift). Zuerst rot: die zwei neuen Assertions auf HEAD (rc=1). (3) `DEVELOPMENT.md`, Abschnitt „### Monitoring (lokal ohne Docker)“ (`:894-907`): ein Absatz wie der zum Server (`:771`): Ohne `DATABASE_URL` meldet sich der Monitoring-Dienst mit dem Dev-Fallback `adminhelper:adminhelper@localhost:5432/adminhelper_monitor` an (`apps/monitoring/app/core/config.py:57-66`); hat die Rolle ein eigenes Passwort (Abschnitt „Python-Tests lokal (ohne Docker)“, `:173`), scheitert das, dann `DATABASE_URL` mit Passwort setzen; die Datenbank `adminhelper_monitor` legt lokal niemand an (das tut nur der Container-Entrypoint). Stil des Abschnitts (ae/oe/ue wie dort).
Verify: bash scripts/dev/verify.sh scripts --strict -- gitignore_test
Doku: DEVELOPMENT.md (in dieser Task); kein CHANGELOG
Beweis: origin/main@b25c65a6 · `git check-ignore -v apps/data/.secret_key; echo $?` → keine Ausgabe, `1`; `grep -n 'DATA_DIR=../data' DEVELOPMENT.md` → `:762`, `:1435`; `sed -n 894,907p DEVELOPMENT.md | grep -c 'DATABASE_URL'` → 0
Orakel: contract — `git check-ignore` gegen die Pfade, die der dokumentierte Startbefehl schreibt
Dedup-Key: bug:dev:data-dir-not-ignored
HEAD: b25c65a6
Semantik: R-0602 (Dedup `ref:docs:development-monitoring-db-fallback`) in derselben Task, weil sie dieselbe Datei trifft. `feature/docs-drift` übernimmt `DATA_DIR=../data` in `docs/developer/index.html` (DE `:92`, EN `:65`); die `.gitignore`-Zeile deckt auch diese Kopien, ohne dass T9 an docs-drift hängt.

### T10 — Compose-Kommentar und englische Meldungen des Monitoring-Entrypoints (R-0732)  [x]
Komponente: server · Dateien: docker-compose.yml, apps/monitoring/docker-entrypoint.sh, apps/server/tests/test_images_exec_only.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @c7ba607f 2026-10-29T11:08:56+01:00
Review: approve (.ah-out/review/docs-residual-risks/T10.verdict.json)
Änderung: (1) `docker-compose.yml:85-87`, letzter Satz des Kommentars: statt „Only the monitoring entrypoint runs psql and needs it.“ etwa „Only the monitoring entrypoint opens a session (psycopg, to create its database) and needs it.“ Nur dieser Kommentar; `feature/compose-hardening` und `feature/smtp-hardening` ändern die Datei an anderen Stellen. (2) `apps/monitoring/docker-entrypoint.sh:51` und `:54`, die zwei Meldungen des Python-Heredocs (seit PR #255 neu): `[entrypoint] Creating database {name}...` und `[entrypoint] ERROR: database {name}: {exc}`; die deutschen `echo`-Zeilen davor und danach sind Alt-Bestand und bleiben. (3) `apps/server/tests/test_images_exec_only.py:347` und `:357` auf die neuen Texte. Zuerst rot: (3) allein auf HEAD.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_images_exec_only.py
Doku: keine (Kommentar und Log-Texte; keine Doku zitiert sie, `git grep -n 'Lege Datenbank' -- docs` leer); kein CHANGELOG
Assertion-Änderung: apps/server/tests/test_images_exec_only.py::test_the_entrypoint_of_monitoring_creates_its_database_once — die erwarteten Meldungen sind jetzt englisch, Form und Prüfung bleiben gleich
Beweis: origin/main@b25c65a6 · `sed -n 87p docker-compose.yml` → „Only the monitoring entrypoint runs psql“; `grep -n 'psql' apps/monitoring/docker-entrypoint.sh` → keiner, `grep -n 'psycopg.connect' apps/monitoring/docker-entrypoint.sh` → `:48`, der Kommentar `:33` sagt selbst „Through psycopg, not psql“; `sed -n 51p;54p apps/monitoring/docker-entrypoint.sh` → deutsche Texte
Orakel: contract — Kommentar gegen den Entrypoint; Meldungstexte gegen die Test-Assertions
HEAD: b25c65a6

### T11 — Entwickler-Übersicht EN und Vite-Kommentare: Versionen und Build-Weg wie heute (R-0792)  [x]
Komponente: web · Dateien: docs/en/developer/index.html, apps/web/vite.config.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @aba4087b 2026-10-29T11:11:32+01:00
Review: approve (.ah-out/review/docs-residual-risks/T11.verdict.json)
Änderung: (1) `docs/en/developer/index.html:38-39` (Tech-Stack-Karten): „FastAPI 0.11“ → „FastAPI“, „Vite 5“ → „Vite“, wie die DE-Seite, die keine Versionen nennt (nach docs-drift `docs/developer/index.html`, Tech-Stack-Karten); die Lockdateien sind die Quelle (`apps/server/requirements.txt:239` `fastapi==0.138.0`, `apps/web/package-lock.json` Vite 8.1.6). Testzahlen bleiben (keine Zeile). (2) `apps/web/vite.config.ts:48-49`: statt „Waehrend der Migration … Erst in Phase 11 auf '../server/frontend' umstellen“ englisch: Vite baut nach `dist/`; das Root-`Dockerfile` (Stage `frontend-build`) kopiert `dist/` ins Server-Image, das es unter `frontend/` ausliefert (`Dockerfile:4`, `:40`). `:52`: „after the cutover to ../server/frontend they'd be served publicly“ → „the server image serves the build publicly“. Kein Wert der Konfiguration ändert sich.
Verify: bash scripts/dev/verify.sh web --strict -- src/vite-config.test.ts
Doku: die Task ist die Doku (EN); kein CHANGELOG
Abhängt von: `feature/docs-drift` auf `main` und in diesen Branch gemergt (bringt `src/vite-config.test.ts`, ändert `docs/en/developer/index.html`)
Beweis: origin/main@b25c65a6 · `sed -n 38,39p docs/en/developer/index.html | grep -o 'FastAPI 0.11\|Vite 5'` → zwei Treffer; `grep -n '^fastapi==' apps/server/requirements.txt` → `0.138.0`; `sed -n 48,49p apps/web/vite.config.ts` → „Erst in Phase 11“; `grep -n 'frontend' Dockerfile` → `:40` `COPY --from=frontend-build /build/dist/ ./frontend/`
Orakel: contract — Doku und Kommentare gegen Lockdateien und Dockerfile
Dedup-Key: ref:docs:stale-versions-comments
HEAD: b25c65a6

### T12 — Hook-Beispiele: Test hält `docs/examples` frei von Adressen außerhalb RFC 5737 (R-0601)  [x]
Komponente: server · Dateien: apps/server/tests/test_hook_examples.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @53b585bf 2026-10-29T11:11:49+01:00
Review: approve (.ah-out/review/docs-residual-risks/T12.verdict.json)
Änderung: Neben `test_example_http_helper_keywords_match_worker_signature` (`:32`): ein Helfer `_foreign_ipv4(text) -> list[str]` findet jede gepunktete Vierergruppe (`(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])`) und gibt die zurück, die keine IPv4-Adresse in `192.0.2.0/24`, `198.51.100.0/24` oder `203.0.113.0/24` ist (`ipaddress`; eine Gruppe, die keine gültige Adresse ist, zählt als Fund). Test (a): über jede Datei unter `docs/examples` (rekursiv, als Text) ist die Liste leer; die Meldung nennt Datei und Adresse. Test (b), Gegenprobe des Helfers: `198.18.0.1` (RFC 2544) und `8.8.8.8` werden gemeldet, `192.0.2.1`, `198.51.100.7`, `203.0.113.255` und `1.2.3` nicht. Der Modul-Docstring bekommt einen Satz zum zweiten Zweck. IPv6 prüft der Test nicht (Spec, Nicht-Ziele). Zuerst rot: (a) mit einer Probe-Zeile `10.0.0.1` in einer Kopie eines Beispiels (nur lokal, nicht committet; Ergebnis in den Commit-Body).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hook_examples.py
Doku: keine (Test); kein CHANGELOG
Beweis: origin/main@b25c65a6 · `git grep -nE '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b' -- docs/examples` → nur `webhook_http_import.py:24`, `:25` (`192.0.2.1`, `192.0.2.2`); `grep -rn 'ipaddress\|5737' apps/server/tests/test_hook_examples.py` → keiner
Orakel: property — keine Adresse unter `docs/examples` außerhalb der drei Dokumentationsnetze; Gegenprobe (b) zeigt, dass der Prüfer fallen kann
Dedup-Key: idee:docs:examples-rfc5737-guard
HEAD: b25c65a6

### T13 — CHANGELOG: Eintrag zu R-0551 nennt das Windows-Verhalten (R-0595)  [x]
Komponente: scripts · Dateien: CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @90c7baae 2026-10-29T11:17:25+01:00
Review: approve (.ah-out/review/docs-residual-risks/T13.verdict.json)
Änderung: Im Eintrag „Desktop: „Passwort merken“ im Server-Workspace nur fuer Verbindungen, die der Server fuehrt (R-0551)“ (`CHANGELOG.md:665-670`, Abschnitt `## [0.46.0]`) den Halbsatz „fuer eine noch nicht gespeicherte gilt das getippte Passwort nur fuer diesen Start“ ergänzen: „… nur fuer diesen Start (unter Windows verwirft der Desktop es, und mstsc fragt selbst)“ (`apps/desktop/src-tauri/src/connection/mod.rs:25-31`). Der Eintrag bleibt in seinem Abschnitt (Korrektur, kein neues Verhalten). Umlautfrei; der builder prüft `git diff -U0 CHANGELOG.md` auf ä/ö/ü/ß in hinzugefügten Zeilen (Ausgabe in eine Datei, dann greppen; leer).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Task ist der CHANGELOG
Beweis: origin/main@b25c65a6 · `sed -n 669,670p CHANGELOG.md` → „gilt das getippte Passwort nur fuer diesen Start“ ohne Windows; `sed -n 25,31p apps/desktop/src-tauri/src/connection/mod.rs` → `#[cfg(target_os = "windows")] let password: Option<&str> = { let _ = password; None };`
Orakel: contract — Eintrag gegen den Windows-Zweig in `connection/mod.rs`
Dedup-Key: bug:docs:changelog:r0551-windows-wording
HEAD: b25c65a6
Semantik: Der Eintrag zu R-0431 im selben Abschnitt (`CHANGELOG.md:143`) sagt schon „ein nur getipptes fragt mstsc wie bisher selbst ab“. Der Release-Text von v0.46.0 auf GitHub ändert sich durch den Commit nicht.

### T14 — CHANGELOG: Eintrag zu R-0659 wie der Code (R-0782)  [x]
Komponente: scripts · Dateien: CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ba06307d 2026-10-29T11:22:52+01:00
Review: approve (.ah-out/review/docs-residual-risks/T14.verdict.json)
Änderung: Erst nach dem Merge von PR #262. Den Eintrag „Desktop: der RDP-Start gibt Bildschirmgroesse und Skalierungsfaktor mit (R-0659)“ per `grep -n 'R-0659' CHANGELOG.md` finden (Abschnitt, in dem er dann steht). Der Satz „Unter Linux nimmt die Fenstergroesse „Eingepasst" die Groesse des Bildschirms statt immer 1088x720“ wird: „Unter Linux nimmt der Fenstermodus „Eingepasst" 85 % der Bildschirmbreite und 85 % der Hoehe abzueglich 80 Pixel, mindestens 1024x720, statt immer 1088x720“. Werte vor dem Schreiben an `fit_window_size` (`apps/desktop/src-tauri/src/connection/rdp_logic.rs`, auf dem Branch `:128-141`) und am Label (`settings.rdp.windowMode` „Fenstermodus“, `apps/desktop/ui/src/lib/i18n/dictionaries.ts`) prüfen. Umlaut-Prüfung wie T13.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Task ist der CHANGELOG
Abhängt von: PR #262 auf `main` und in diesen Branch gemergt
Beweis: origin/feature/desktop-ui-fixes · `git show origin/feature/desktop-ui-fixes:CHANGELOG.md | grep -n 'R-0659'` → Eintrag mit „die Groesse des Bildschirms“; `git show origin/feature/desktop-ui-fixes:apps/desktop/src-tauri/src/connection/rdp_logic.rs | sed -n 128,141p` → Faktor 0.85, Abzug 80, Minimum 1024x720
Orakel: contract — Eintrag gegen `fit_window_size` und das UI-Label
Dedup-Key: bug:docs:changelog:r0659-wording
HEAD: b25c65a6

### T15 — Desktop: 403 auf das Visitor-Bundle stoppt frpc wie 404 (R-0453, optional)  [x]
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @f20fb539 2026-10-29T11:26:40+01:00
Review: approve (.ah-out/review/docs-residual-risks/T15.verdict.json)
Entscheidung: Kevin 2026-10-23: (a) 403 wie 404, frpc stoppt; nur frpc.rs, kein IPC-Vertrag.
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/frpc.rs, docs/developer/desktop.html, docs/en/developer/desktop.html, CHANGELOG.md
Änderung: Variante (a). `carries_bundle` (`apps/desktop/src-tauri/src/frpc.rs:277-287`) gibt für `FORBIDDEN` wie für `NOT_FOUND` `Ok(false)` zurück; damit führt der Abgleich auf `stopped` (kein neues Ergebnis, kein IPC-Vertrag: `apps/desktop/src-tauri/src/models.rs:180-187`, UI `apps/desktop/ui/src/lib/stores/tunnel.ts:216-227`). Doc-Kommentare `frpc.rs:271-276` und `:1186-1189` mitziehen (403: der Server verweigert dem Gerät oder Benutzer den Zugang, etwa nach Widerruf; 401 trotz erneuerter Sitzung bleibt ein Fehler). Tests: neuer `refresh_403_means_no_tunnels` (`carries_bundle(FORBIDDEN)` → `Ok(false)`), in `refresh_500_and_every_other_failure_is_an_error` (`:2045-2049`) fällt 403 aus der Liste. Zuerst rot: der neue Test auf HEAD. Doku: der Satz zu `:259` aus T7 nennt 403 bei `stopped`. CHANGELOG (Changed, umlautfrei): Verweigert der Server dem Desktop das Visitor-Bundle (403, etwa nach Widerruf des Geraets oder Loeschen des Benutzers), stoppt der Desktop seinen Tunnel beim naechsten Abgleich.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- frpc::tests::refresh_
Doku: docs/developer/desktop.html:259 + docs/en/developer/desktop.html:259 · CHANGELOG.md
Abhängt von: T7, Kevins Antwort
Assertion-Änderung: apps/desktop/src-tauri/src/frpc.rs::refresh_500_and_every_other_failure_is_an_error — 403 ist kein Fehler mehr, sondern „keine Tunnel“; der neue Test refresh_403_means_no_tunnels pinnt das
Beweis: origin/main@b25c65a6 · `sed -n 2045,2049p apps/desktop/src-tauri/src/frpc.rs` → `for code in [500, 502, 503, 401, 403]` mit `carries_bundle(status).is_err()`; `sed -n 1187,1189p apps/desktop/src-tauri/src/frpc.rs` → ein Fehler „leaves the running frpc alone“; `sed -n 225p apps/server/app/core/identity.py` → 403 `CERT_REVOKED` für ein widerrufenes Zertifikat
Orakel: contract — `carries_bundle` gegen die Antworten von `gen_visitor_bundle` hinter `require_scope`
Dedup-Key: feat:docs:deactivate-user-rotate-secrets
HEAD: b25c65a6
Semantik: R-0453, optionaler Teil: „optional Desktop stoppt den Tunnel bei 403 oder endgueltig abgelehntem Refresh“; Status-Notiz: „optionaler Desktop-Stopp bei 403 beim Plan entscheiden (Kevin 2026-10-17)“. Der Teil „endgültig abgelehnter Refresh“ ist gebaut (`apps/desktop/src-tauri/src/session.rs:320-332`, `apps/desktop/src-tauri/src/main.rs:199-206`); offen ist nur 403.
