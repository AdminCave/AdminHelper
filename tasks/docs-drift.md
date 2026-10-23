<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Doku-Drift: Entwicklerweg, Troubleshooting-Befehle des Agents, Visitor-Generator, Kommentare zum mTLS-Default — Task-Ledger
Status: erledigt · Branch: feature/docs-drift · Review: pro Task
Spec: docs/features/docs-drift.md (Roadmap R-0669, R-0731, R-0584, R-0387)
Heavy: linux-full — der Diff berührt `apps/gateway` (nur Kommentare in `nginx.conf` und `docker-entrypoint.sh`, T6) und `apps/agent` (nur eine neue Testdatei, T5); CLAUDE.md §5 nennt Gateway und Agent, der Sammellauf über `main` zeigt, dass das Gateway mit der kommentierten `nginx.conf` startet (`integration-stack`). Kein `scenario`: keine Zeile Konfiguration, kein FRP-Datenpfad, keine Provisionierung, keine PKI ändert sich; kein `windows`: der neue Go-Test läuft im PR im CI-Job `agent-windows` mit
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Die Entwickler-Doku (DE+EN gleich) startet Server, Web, Desktop und Agent so, wie `DEVELOPMENT.md` es tut,
und beschreibt Proxy, Monitoring-Weiterleitung, Bäume und `generate_visitor_toml` wie der Code. (2) Der Vite-Dev-Server
proxied nur `/api` auf `http://127.0.0.1:8080`. (3) Das Troubleshooting nennt nur Agent-Befehle, die es gibt; ein
Go-Test prüft jede Agent-Befehlszeile der Doku gegen die CLI. (4) Die Kommentare nennen den mTLS-Default richtig; im
Server pinnt ein Test ihn. Zeilenangaben: origin/main@e2304a8b; der builder greppt sie vor dem Schreiben neu.

Für alle Tasks:
- Die Tasks sind unabhängig; jede ändert eigene Dateien. Reihenfolge T1 … T7 ist nur Vorschlag.
- Nur die in der Spec unter „Betroffene Komponenten & Dateien“ genannten Abschnitte ändern (parallele Vorhaben
  ändern andere Abschnitte derselben Seiten, etwa den Abschnitt „Diagnose-Bundle“ des Troubleshootings).
- DE und EN sagen dasselbe; Code-Blöcke behalten den Stil ihrer Datei (`&&` roh in `docs/developer/index.html`,
  `&amp;&amp;` in `docs/en/developer/index.html`).
- Jede Doku-Task fährt zusätzlich `python3 scripts/dev/doc-smoke.py --paths --env --strict` (Exit 0, Ergebnis in den
  Commit-Body).
- `apps/gateway/*` und `apps/server/app/core/identity.py` stehen auf `scripts/dev/review-risk.txt`: T6 und T7 bekommen
  zusätzlich `security`.
- Neue Code-Strings und Kommentare englisch. CHANGELOG-Einträge umlautfrei wie die vorhandenen.
- Sicherheitsfunde, die beim Bauen auffallen, gehören nicht in Commit, Ledger oder Doku, sondern als Meldung an die
  Session.

### T1 — Web: Vite-Dev-Proxy nur `/api` auf `127.0.0.1:8080`, Parität mit dem OpenAPI-Snapshot (R-0669)  [x]
Komponente: web · Dateien: apps/web/vite.config.ts, apps/web/src/vite-config.test.ts, docs/developer/webui.html, docs/en/developer/webui.html, CHANGELOG.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @20a9f66d 2026-10-22T13:40:16+02:00
Review: approve (.ah-out/review/docs-drift/T1.verdict.json)
Änderung: `server.proxy` (`apps/web/vite.config.ts:60-64`) wird `{ '/api': 'http://127.0.0.1:8080' }`; `/auth` und `/health` entfallen (am Server gibt es sie nicht: alle Pfade in `apps/server/tests/openapi.snapshot.json` beginnen mit `/api/`). Sonst bleibt die Datei, auch der Block `preview`. Neue Testdatei `apps/web/src/vite-config.test.ts` mit SPDX-Header wie die übrigen `*.test.ts` und `// @vitest-environment node`: lädt die Config mit `loadConfigFromFile({ command: 'serve', mode: 'development' }, <absoluter Pfad zu apps/web/vite.config.ts>)` aus `vite` (Spec, Externe Integrationen) und liest die Pfade aus `apps/server/tests/openapi.snapshot.json` (`node:fs`). Assertions: (a) jeder Schlüssel von `server.proxy` ist Präfix (gleich oder gefolgt von `/`) mindestens eines Snapshot-Pfads; (b) jeder Snapshot-Pfad liegt unter einem Schlüssel; (c) jedes Ziel ist `http://127.0.0.1:8080` (Kommentar: der Startbefehl in `DEVELOPMENT.md:761`); (d) der Snapshot hat mindestens 40 Pfade (heute 58), damit ein leerer oder falsch gelesener Snapshot nicht grün wird. Zuerst rot: (a) und (c) auf HEAD. Doku in derselben Task: `docs/developer/webui.html:99` / EN `:99` — Vite läuft auf Port 5173 und proxied `/api` auf `http://127.0.0.1:8080`, den lokal gestarteten Server (Link auf „Lokale Entwicklung“ in `./index.html`); `:98` / EN `:98` „Sourcemaps an“ / „sourcemaps on“ → ohne Sourcemaps (`sourcemap: false`, `vite.config.ts:55`). Der Rest von `:98` bleibt.
Verify: bash scripts/dev/verify.sh web --strict -- src/vite-config.test.ts
Doku: docs/developer/webui.html:98-99 + docs/en/developer/webui.html:98-99 · CHANGELOG.md (Fixed, umlautfrei: der Vite-Dev-Server des Web-Panels proxied nur noch `/api`, auf `http://127.0.0.1:8080`, den Port, auf dem DEVELOPMENT.md und die Entwickler-Doku den Server starten; `/auth` und `/health` gibt es am Server nicht. Doku: Web-UI fuer Entwickler (DE+EN))
Beweis: origin/main@e2304a8b · Probe (Python 3.13.5): Präfixe aus `apps/web/vite.config.ts:61-63` gegen die Pfade von `apps/server/tests/openapi.snapshot.json` → `/auth` 0 von 58, `/api` 58 von 58, `/health` 0 von 58, Ziel `http://localhost:8000`; dreimal identisch (gleiche md5). Startbefehl: `DEVELOPMENT.md:761` `--host 127.0.0.1 --port 8080`
Orakel: contract — Proxy-Präfixe gegen den OpenAPI-Snapshot des Servers; ein Präfix ohne Route oder ein Pfad ohne Präfix macht den Test rot
Dedup-Key: bug:docs:developer:dev-path-drift
HEAD: e2304a8b
Semantik: `DEVELOPMENT.md:761` — „DATA_DIR=../data uvicorn app.main:app --reload --host 127.0.0.1 --port 8080“; `docs/developer/server.html:202` — „uvicorn lauscht plain-HTTP auf <code>8080</code>“

### T2 — Entwickler-Übersicht: Startbefehle wie DEVELOPMENT.md, `apps/frps/` im Baum (R-0669)  [x]
Komponente: scripts · Dateien: docs/developer/index.html, docs/en/developer/index.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @eed26622 2026-10-22T13:46:55+02:00
Review: approve (.ah-out/review/docs-drift/T2.verdict.json)
Änderung: Abschnitt „Lokale Entwicklung“ (`docs/developer/index.html:88-99`, EN „Local Development“ `:61-77`), DE und EN mit denselben Befehlen, jeder Block ab Repo-Wurzel: Server `cd apps/server && python3 -m venv .venv && . .venv/bin/activate`, `pip install -r requirements-dev.txt`, `DATA_DIR=../data uvicorn app.main:app --reload --host 127.0.0.1 --port 8080` (wie `DEVELOPMENT.md:37-44`, `:756-762`; ein Kommentar: braucht Postgres, `DATABASE_URL` und Erstanmeldung siehe `DEVELOPMENT.md`); Web `cd apps/web && npm ci && npm run dev` (EN bisher `npm install`); Desktop `cd apps/desktop/ui && npm ci`, dann `cd ../src-tauri && cargo tauri dev` (`DEVELOPMENT.md:847-852`); Agent `cd apps/agent && go run ./cmd/adminhelper-agent version` (EN bisher `run`, der Dauerbetrieb). Kein `uv` mehr. Repo-Bäume (`docs/developer/index.html:62-83`, EN `:46-57`): eine Zeile `apps/frps/` nach `gateway/` (DE „frps-Image (FRP-Server unter einem Supervisor)“, EN „frps image (FRP server under a supervisor)“, wie `docs/admin/betrieb.html:186`). Sonst bleiben beide Abschnitte; nicht `:106` (Gateway-Absatz, den ändert ein anderes Vorhaben).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Task ist die Doku (DE+EN); kein CHANGELOG
Beweis: origin/main@e2304a8b · `git ls-files apps/server | grep -cE 'pyproject.toml|uv.lock'` → `0`; `test -e apps/desktop/desktop` → fehlt (Ziel von `cd ../desktop` aus `apps/desktop/ui`); `docs/en/developer/index.html:64` ohne `--port` → uvicorn-Default 8000 (uvicorn 0.53.0, `Config(port=8000)`); `ls apps/frps` → `Dockerfile`, `frps-supervisor.sh`, in keinem der beiden Bäume
Dedup-Key: bug:docs:developer:dev-path-drift
HEAD: e2304a8b
Semantik: Soll ist `DEVELOPMENT.md:37-44` („python3 -m venv .venv … pip install -r requirements-dev.txt“), `:756-762` (Server auf `127.0.0.1:8080`), `:847-852` („cd apps/desktop/src-tauri“, „cargo tauri dev“), `:889` („go run ./cmd/adminhelper-agent version“)

### T3 — Server-Entwicklerseite: `generate_visitor_toml` wie der Code, Tests ohne `uv` (R-0584, R-0669)  [x]
Komponente: scripts · Dateien: docs/developer/server.html, docs/en/developer/server.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @9e4e802e 2026-10-22T14:08:00+02:00
Review: approve (.ah-out/review/docs-drift/T3.verdict.json)
Änderung: (1) Tabelle „FRP — TOML-Struktur“, Zeile `generate_visitor_toml` (`docs/developer/server.html:111`, EN `:111`), Spalte Inhalt: ein `[[visitors]]`-Block je übergebenem STCP-Tunnel, der eingeschaltet ist, ein Secret und einen `visitor_port` von 1 bis 65535 hat (`without_secretless_stcp`, `without_unbindable_visitor`; einen ausgelassenen Tunnel loggt der Server als Warnung), sortiert nach `visitor_port`, mit `bindAddr = "127.0.0.1"` und `bindPort` = `visitor_port`; die Aufrufer übergeben nur die STCP-Tunnel, die der Nutzer sehen darf (`_visible_stcp_tunnels` in `modules/frp/generate_router.py`). Quelle: `apps/server/app/modules/frp/config_generator.py:95-131`, `:336-356`; `apps/server/app/modules/frp/generate_router.py:40`. (2) Abschnitt „Tests“: `:215` `server/tests/` → `apps/server/tests/` (sonst bleibt der Absatz); Code-Block `:218-220` → `cd apps/server && . .venv/bin/activate` (venv aus „Lokale Entwicklung“ der Übersicht), `pytest -x`, `pytest --cov=app`, Kommentare wie bisher. Andere Zeilen nicht (`:43-46`, `:79-85`, `:161-167`, `:193` ändern andere Vorhaben).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Task ist die Doku (DE+EN); kein CHANGELOG
Beweis: origin/main@e2304a8b · `apps/server/app/modules/frp/config_generator.py:336-339` filtert `without_unbindable_visitor(without_secretless_stcp([… stcp and enabled]))` und sortiert nach `visitor_port`, die Doku `:111` sagt „alle aktiven STCP-Tunnel“; `git ls-files apps/server | grep -cE 'pyproject.toml|uv.lock'` → `0`; `test -d server/tests` (Repo-Wurzel) → fehlt
Dedup-Key: ref:docs:server.html:generate_visitor_toml-wording (dazu bug:docs:developer:dev-path-drift)
HEAD: e2304a8b
Semantik: Soll ist der Code: Docstring `apps/server/app/modules/frp/config_generator.py:319-323` — „Aggregates all STCP tunnels with a secret and a usable visitor port and emits one [[visitors]] block each“; für die Tests `DEVELOPMENT.md:37-44` (venv + pip)

### T4 — Monitoring-Entwicklerseite: Weiterleitung ohne `/monitor`, vollständiger Baum (R-0669)  [x]
Komponente: scripts · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @f3eebbf1 2026-10-22T14:15:51+02:00
Review: approve (.ah-out/review/docs-drift/T4.verdict.json)
Änderung: (1) „Daten-Fluss“ (`docs/developer/monitoring.html:49`, EN `:49`): `-> /monitor/* (X-Internal-Key) ->` wird die Weiterleitung ohne Präfix, `{MONITOR_SERVICE_URL}/{path}` mit `X-Internal-Key` (Default `http://monitoring:8080`); Quelle `apps/server/app/modules/monitoring_proxy/router.py:37`, `:140`, `apps/server/app/core/config.py:111`, Router ohne `prefix` `apps/monitoring/app/main.py:153-154`. Das ASCII-Bild bleibt sonst, wie es ist. (2) „Monitoring-Service-Struktur“ (`:62-79`, EN gleich): `core/` nennt alle zehn Module (`auth.py`, `bounds.py`, `config.py`, `database.py`, `logging_config.py`, `middleware.py`, `pagination.py`, `ssrf.py`, `time.py`, `victoria.py`; bei Bedarf über zwei Zeilen wie `models.py`), dazu neue Zeilen `alert_bundle.py` (Sammelmeldung für Agents, die zusammen ausbleiben oder zurückkehren) und `check_types.py` (Check-Typ-Taxonomie, einzige Quelle, u. a. `push_only`), Beschreibungen nach den Docstrings der Module. Nicht `:142-148` und `:258-264` (feature/monitoring-io ändert sie).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Task ist die Doku (DE+EN); kein CHANGELOG
Beweis: origin/main@e2304a8b · `grep -n include_router apps/monitoring/app/main.py` → `:154` ohne `prefix`; `ls apps/monitoring/app/core/*.py` → 10 Module ohne `__init__.py`, der Baum `:79` nennt 4; `ls apps/monitoring/app/alert_bundle.py apps/monitoring/app/check_types.py` → beide da, im Baum nicht
Dedup-Key: bug:docs:developer:dev-path-drift
HEAD: e2304a8b
Semantik: Soll ist der Code: `apps/server/app/modules/monitoring_proxy/router.py:140` — `target_url = f"{_MONITOR_BASE}/{forward_path}"`

### T5 — Troubleshooting: nur Agent-Befehle, die es gibt; Go-Test prüft die Doku gegen die CLI (R-0731)  [x]
Komponente: agent · Dateien: apps/agent/cmd/adminhelper-agent/docs_cli_test.go, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, CHANGELOG.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @21edcaaa 2026-10-23T06:26:08+02:00
Review: approve (.ah-out/review/docs-drift/T5.verdict.json)
Änderung: Neue Testdatei `apps/agent/cmd/adminhelper-agent/docs_cli_test.go` (`package main`, SPDX-Header wie `box_cli_test.go:1-3`), nutzt `parseCalls` und `checkCall` aus `box_cli_test.go` unverändert. `TestDocsCallTheAgentCLIAsItIs`: liest alle `*.html` unter `../../../../docs` (wie `box_cli_test.go:217`), nimmt den Inhalt jedes `<code…>…</code>` (wie `scripts/dev/doc-smoke.py`: Tags entfernt, `html.UnescapeString`, `\r\n` → `\n`), schneidet je Zeile einen Shell-Kommentar ab (`#` am Zeilenanfang oder nach Leerraum) und gibt `parseCalls` nur Zeilen, in denen `adminhelper-agent` als eigenes Wort von einem Token gefolgt wird, das mit `[a-z-]` beginnt (so bleiben `sudo apt install adminhelper-agent`, `<code>adminhelper-agent</code>`, `adminhelper-agent.timer` und `bin/adminhelper-agent (ELF amd64)` draußen); jeder Eintrag in `unknown` und jeder Fehler von `checkCall` ist ein `t.Errorf` mit Datei und Zeile der Doku. Untergrenze: mindestens 18 gefundene Aufrufe (heute 21 vor der Korrektur; der builder setzt sie knapp unter die echte Zahl nach der Korrektur), sonst Fehler. `TestDocsCLICheckCanFail` über eine HTML-Fixture im Test: `<pre><code>sudo adminhelper-agent run --verbose   # x</code></pre>`, `adminhelper-agent monitor run --dry-run` und `adminhelper-agent frpc rotate` → je ein Fehler; `sudo adminhelper-agent run --once --log-level debug`, `sudo adminhelper-agent provision \` + `    --url https://srm.example.com \` + `    --token &lt;provision-token&gt;`, `cd a &amp;&amp; sudo adminhelper-agent diagnostics` → keiner; `sudo apt install adminhelper-agent     # later` → kein Aufruf. Doku (DE+EN gleich, Befehl wie `docs/admin/agent-deployment.html:195` plus `--log-level debug`): (1) `docs/en/admin/troubleshooting.html:63` → `sudo adminhelper-agent run --once --log-level debug   # one run by hand, with debug output`; `docs/admin/troubleshooting.html:106-111` bekommt denselben Schritt („ein Durchlauf von Hand mit Debug-Ausgabe“). (2) `docs/admin/troubleshooting.html:119` „Agent-Debug: …“ → derselbe Befehl auf dem Ziel-Host; EN „Monitoring ingest dropping samples“ (`:111-118`) bekommt ihn als Agent-Seite im Code-Block. (3) `docs/en/admin/troubleshooting.html:123` (`frpc rotate`) und `docs/admin/troubleshooting.html:125` („< 30 Tagen“, „CRL“): Client-Zertifikat des Agents prüfen mit `openssl x509 -in /etc/adminhelper/identity/agent.crt -noout -enddate` (wie `:110`, EN `:66`); der Agent erneuert es bei jedem Lauf selbst, sobald die Hälfte seiner Laufzeit um ist (`apps/agent/internal/enroll/renew.go:18-21`, `apps/agent/cmd/adminhelper-agent/run.go:110-125`); scheitert das, steht `Cert-Renew Fehler` im Journal des Dienstes. Keine CRL (`apps/server/app/modules/enrollment/models.py:87`). Nicht der Abschnitt „Diagnose-Bundle“ (DE ab `:140`, EN ab `:127`; ändert feature/ops-scripts-hardening). Zuerst rot: `TestDocsCallTheAgentCLIAsItIs` auf HEAD mit genau den drei Funden.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestDocs
Doku: docs/admin/troubleshooting.html + docs/en/admin/troubleshooting.html (die Abschnitte oben) · CHANGELOG.md (Fixed, umlautfrei: das Troubleshooting nennt nur Agent-Befehle, die es gibt: `sudo adminhelper-agent run --once --log-level debug` statt `run --verbose` und `monitor run --dry-run`; die Erneuerung des Agent-Zertifikats wie im Code statt `frpc rotate`; ein Test prueft jede Agent-Befehlszeile der Doku gegen die CLI. Doku: Troubleshooting (DE+EN))
Beweis: origin/main@e2304a8b · Probe (Python 3.13.5, `<code>`-Blöcke aller `docs/**/*.html` gegen den Befehlsbaum aus `--help`) → 21 Aufrufe, 3 Funde: `admin/troubleshooting.html:119` `monitor run --dry-run` (unbekannter Unterbefehl `run`), `en/admin/troubleshooting.html:63` `run --verbose` (unbekannter Flag), `en/admin/troubleshooting.html:123` `frpc rotate` (unbekannter Unterbefehl); dreimal identisch (gleiche md5). CLI (go1.26.9, `go run ./cmd/adminhelper-agent … --help`): `run` nur `--once`, global `--log-level`; `monitor` nur `init`, `push`; `frpc` nur `sync`
Orakel: contract — jede Agent-Befehlszeile in `docs/**/*.html` gegen den echten Cobra-Baum (Helfer-Prozess aus `box_cli_test.go`)
Dedup-Key: bug:docs:troubleshooting:nonexistent-agent-flags
HEAD: e2304a8b
Semantik: `docs/admin/agent-deployment.html:195` — „sudo adminhelper-agent run --once          # ein Durchlauf von Hand: Sync + Push“; `apps/agent/cmd/adminhelper-agent/main.go:35-36` — `--log-level`, „Log-Level: debug, info, warn, error“

### T6 — Gateway: Kommentare nennen den mTLS-Default richtig (R-0387)  [x]
Komponente: scripts · Dateien: apps/gateway/nginx.conf, apps/gateway/docker-entrypoint.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @35bdf039 2026-10-23T06:33:47+02:00
Review: approve (.ah-out/review/docs-drift/T6.verdict.json)
Änderung: Nur Kommentare. (1) `apps/gateway/nginx.conf:73-76`: der Modus kommt aus `MTLS_ENFORCE` (A8); `on` = CERT_REQUIRED ist der Default (`MTLS_ENFORCE` leer, `true` oder ein unbekannter Wert), `optional` nur mit `MTLS_ENFORCE=false`; die App entscheidet in beiden Fällen je Route über den Header. „permissive rollout (default)“ und „flipping is an operator action once every client holds a cert“ entfallen. (2) `apps/gateway/docker-entrypoint.sh:32-33`: statt „install.sh flips it to false only for the bootstrap window …, then back“: `scripts/install.sh` lässt den Default; nur `--permissive` schreibt `MTLS_ENFORCE=false` in die `.env` (`scripts/install.sh:24`, `:230`). Der Block `case … esac` (`:37-53`) bleibt Byte für Byte, `scripts/tests/gateway_mtls_test.sh` liest ihn per `awk`. Keine Zeile außerhalb der Kommentare; nicht `nginx.conf:60-70` (feature/compose-hardening fügt dort `limit_conn_zone` ein).
Verify: bash scripts/dev/verify.sh scripts --strict -- gateway_mtls_test
Doku: keine (Kommentare)
Beweis: origin/main@e2304a8b · Code-Lesung: `apps/gateway/docker-entrypoint.sh:37` `${MTLS_ENFORCE:-true}`, `docker-compose.yml:74`, `:200` `${MTLS_ENFORCE:-true}`, `scripts/tests/gateway_mtls_test.sh:43` `check "" "$ENF"` (leer → `ssl_verify_client on;`) gegen `apps/gateway/nginx.conf:74` „"optional" = permissive rollout (default)“; `scripts/install.sh:11-12` „There is no "arm" step and no permissive window“ gegen `apps/gateway/docker-entrypoint.sh:32-33`
Dedup-Key: bug:gateway:nginx.conf:mtls-default-comment
HEAD: e2304a8b
Semantik: `docs/admin/betrieb.html:262` — „Die Datenebene (<code>:443</code>) läuft seit 0.29.0 per Default <strong>scharf</strong> (<code>MTLS_ENFORCE=true</code>)“

### T7 — Server: Docstrings zum mTLS-Default, Default gepinnt (R-0387)  [x]
Komponente: server · Dateien: apps/server/app/core/identity.py, apps/server/tests/test_mtls_scope.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @fe572af1 2026-10-23T06:44:26+02:00
Review: approve (.ah-out/review/docs-drift/T7.verdict.json)
Änderung: (1) Modul-Docstring `apps/server/app/core/identity.py:18-20`: erzwungen ist der Default (`MTLS_ENFORCE` ohne Env oder `true`, `app.core.config`), ein fehlender oder falscher Scope gibt 403; `MTLS_ENFORCE=false` ist der permissive Modus aus dem Rollout (ADR 0002, A3–A7), nur noch für einen manuellen ersten Bootstrap: der Mismatch wird geloggt, die Anfrage läuft weiter. (2) Docstring von `require_scope` (`:233-237`): „Permissive (default)“ → Enforced ist der Default, Permissive mit `MTLS_ENFORCE=false`; Inhalt sonst gleich (wer warnt, wer auf debug bleibt, 403 für ein vom Register abgelehntes Zertifikat in beiden Modi). Code, Log-Texte und `:240` ff. bleiben (feature/server-fixes zieht dort den Körper von `dependency` heraus). (3) Modul-Docstring `apps/server/tests/test_mtls_scope.py:5-10` entsprechend (permissiv mit `MTLS_ENFORCE=false`, erzwungen per Default). (4) Neuer Test in `test_mtls_scope.py`, `test_mtls_enforce_defaults_to_enforced_without_the_env`: Unterprozess `sys.executable -c "from app.core import config; print(config.MTLS_ENFORCE)"`, `cwd` = `apps/server`, Env = `os.environ` ohne `MTLS_ENFORCE`, `DATA_DIR` auf `tmp_path` → Ausgabe `True`; Gegenstück im selben Test mit `MTLS_ENFORCE=false` → `False` (die Probe kann fallen). Keine anderen Werte im Test. Mutations-Gegenprobe in einem eigenen Probe-Worktree (nie im Bau-Worktree, CLAUDE.md §5): Default in `apps/server/app/core/config.py:144` `"true"` → `"false"` → der neue Test rot; Ergebnis in den Commit-Body.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_mtls_scope.py
Doku: keine (Docstrings und Test; das Soll steht in `docs/admin/betrieb.html:262`)
Beweis: origin/main@e2304a8b · Code-Lesung: `apps/server/app/core/config.py:144` `os.environ.get("MTLS_ENFORCE", "true")` gegen `apps/server/app/core/identity.py:18` „``require_scope`` is **permissive** by default“ und `:233` „Permissive (default)“; kein Test pinnt den Default (`apps/server/tests/conftest.py:21` setzt `MTLS_ENFORCE=false` für die Suite)
Orakel: contract — `config.MTLS_ENFORCE` ohne Env ist `True`, mit `false` ist es `False`
Dedup-Key: bug:gateway:nginx.conf:mtls-default-comment
HEAD: e2304a8b
Semantik: `apps/server/app/core/config.py:138-140` — „Enforced by default (true), matching compose (MTLS_ENFORCE:-true) and the docs' "enforced by default since 0.29.0" — the A8 rollout is complete“
