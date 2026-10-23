<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Doku-Drift: Entwicklerweg, Troubleshooting-Befehle des Agents, Visitor-Generator, Kommentare zum mTLS-Default

Stand des Codes: `origin/main@e2304a8b`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/docs-drift.md`. Roadmap R-0669 (T1–T4), R-0731 (T5), R-0584 (T3), R-0387 (T6, T7).

## Problem / Motivation

1. **Entwicklerweg (R-0669).** Wer der Entwickler-Doku folgt, kommt nicht zu einem laufenden Stand:
   - `docs/developer/index.html:89` und `docs/en/developer/index.html:63-64` starten den Server mit `uv sync` /
     `uv run`; im Repo gibt es weder `pyproject.toml` noch `uv.lock` (`git ls-files apps/server` zeigt nur
     `requirements.in`, `requirements.txt`, `requirements-dev.txt`). Dasselbe in `docs/developer/server.html:219-220`
     und `docs/en/developer/server.html:219-220` (`uv run pytest`). Der Weg im Repo ist venv + pip
     (`DEVELOPMENT.md:37-44`, `:756-762`).
   - `docs/developer/index.html:95-96` / `docs/en/developer/index.html:72-73`: nach `cd apps/desktop/ui` zeigt
     `cd ../desktop` auf `apps/desktop/desktop`, das es nicht gibt. `cargo tauri dev` läuft aus
     `apps/desktop/src-tauri` (`DEVELOPMENT.md:847-852`).
   - Port: `DEVELOPMENT.md:761` und `docs/developer/index.html:89` starten den Server auf `8080`, die EN-Seite
     (`:64`) ohne `--port`, also auf dem Default von uvicorn, `8000` (uvicorn 0.53.0, `Config(port=8000)`). Der
     Vite-Dev-Server des Web-Panels proxied `/auth`, `/api` und `/health` auf `http://localhost:8000`
     (`apps/web/vite.config.ts:58-65`, beschrieben in `docs/developer/webui.html:99`, EN `:99`). Der Server
     bedient nur `/api/*`: alle 58 Pfade in `apps/server/tests/openapi.snapshot.json` beginnen mit `/api/`, alle
     Router-Präfixe beginnen mit `/api/`; `/auth` und `/health` treffen am Server nichts.
   - `docs/developer/webui.html:98` / EN `:98` sagen „Sourcemaps an“; der Build hat `sourcemap: false`
     (`apps/web/vite.config.ts:55`).
   - EN `docs/en/developer/index.html:77` startet den Agent mit `go run ./cmd/adminhelper-agent run`, dem
     Dauerbetrieb (alle 5 Minuten, `apps/agent/cmd/adminhelper-agent/run.go:35`); DE (`:99`) und `DEVELOPMENT.md:889`
     nehmen `version`.
   - Repo-Bäume (`docs/developer/index.html:62-83`, EN `:46-57`) kennen `apps/frps/` nicht (Image-Quelle seit
     2026-10-16, `docs/admin/betrieb.html:186`).
   - `docs/developer/server.html:215` / EN `:215`: „Pytest-Suite unter `server/tests/`“; der Pfad ist
     `apps/server/tests/`.
   - `docs/developer/monitoring.html:49` / EN `:49`: der Server reicht an `/monitor/*` weiter. Es gibt kein Präfix:
     die Router des Monitorings hängen ohne `prefix` ein (`apps/monitoring/app/main.py:153-154`), der Proxy ruft
     `{MONITOR_SERVICE_URL}/{forward_path}` (`apps/server/app/modules/monitoring_proxy/router.py:37`, `:140`;
     Default `http://monitoring:8080`, `apps/server/app/core/config.py:111`). Der Baum (`:62-79`) nennt unter
     `core/` 4 von 10 Modulen (es fehlen `bounds.py`, `logging_config.py`, `middleware.py`, `pagination.py`,
     `ssrf.py`, `time.py`) und auf oberster Ebene `alert_bundle.py` und `check_types.py` nicht.

2. **Troubleshooting nennt Agent-Befehle, die es nicht gibt (R-0731).** Gegen die CLI (`go run
   ./cmd/adminhelper-agent <cmd> --help` auf `e2304a8b`): `docs/en/admin/troubleshooting.html:63`
   `adminhelper-agent run --verbose` (`run` kennt nur `--once`, global `--log-level`); `docs/admin/troubleshooting.html:119`
   `adminhelper-agent monitor run --dry-run` (`monitor` kennt nur `init` und `push`); dazu
   `docs/en/admin/troubleshooting.html:123` `adminhelper-agent frpc rotate` (`frpc` kennt nur `sync`). Der
   Nachbarsatz `docs/admin/troubleshooting.html:125` ist ebenso falsch: Der Agent erneuert sein Zertifikat nicht bei
   „< 30 Tagen Restlaufzeit“, sondern bei jedem Lauf, sobald die Hälfte der Laufzeit um ist
   (`apps/agent/internal/enroll/renew.go:18-21`, `RenewalFraction = 0.5`; aufgerufen aus
   `apps/agent/cmd/adminhelper-agent/run.go:110-125`), und es gibt keine CRL, die eine Ausstellung blockieren
   könnte (`apps/server/app/modules/enrollment/models.py:87`, „Fast cut-off without CRL“). Probe (Python 3.13.5,
   `<code>`-Blöcke aller `docs/**/*.html` gegen den Befehlsbaum aus `--help`, dreimal identisch): 21 Aufrufe,
   genau diese drei falsch. Kein Test liest die Doku gegen die CLI; für die Box-Skripte gibt es das schon
   (`apps/agent/cmd/adminhelper-agent/box_cli_test.go`, R-0333).

3. **Visitor-Generator (R-0584).** `docs/developer/server.html:111` / EN `:111`: `generate_visitor_toml` „aggregiert
   alle aktiven STCP-Tunnel“. Der Generator nimmt nur eingeschaltete STCP-Tunnel mit Secret und einem
   `visitor_port` von 1 bis 65535, sortiert nach `visitor_port`
   (`apps/server/app/modules/frp/config_generator.py:336-339`, Filter `:95-131`), und die Aufrufer übergeben nur die
   Tunnel, die der Nutzer sehen darf (`_visible_stcp_tunnels`, `apps/server/app/modules/frp/generate_router.py:40`).

4. **Kommentare zum mTLS-Default (R-0387).** Standard ist erzwungen: `apps/server/app/core/config.py:144`
   (`MTLS_ENFORCE` ohne Env `true`), `docker-compose.yml:74`, `:200` (`${MTLS_ENFORCE:-true}`),
   `apps/gateway/docker-entrypoint.sh:37` (leer → `on`). Falsch sind `apps/gateway/nginx.conf:73-76` („"optional" =
   permissive rollout (default)“, „flipping is an operator action once every client holds a cert“),
   `apps/server/app/core/identity.py:18-20` („permissive by default“) und `:233-235` („Permissive (default)“). Dazu
   `apps/gateway/docker-entrypoint.sh:32-33`: „install.sh flips it to false only for the bootstrap window …, then
   back“; `scripts/install.sh:11-12` sagt „There is no "arm" step and no permissive window“, nur `--permissive`
   schreibt `MTLS_ENFORCE=false` (`:24`, `:230`). Im Server pinnt kein Test den Default
   (`apps/server/tests/conftest.py:21` setzt für die Suite `false`); im Gateway tut es
   `scripts/tests/gateway_mtls_test.sh:43` (`check "" "$ENF"`).

## Ziel & Nicht-Ziele

Ziel:
- Die Startbefehle der Entwickler-Doku (DE+EN gleich) sind die aus `DEVELOPMENT.md`: venv + pip, Server auf
  `127.0.0.1:8080`, Desktop aus `apps/desktop/src-tauri`, Agent `version`.
- Der Vite-Dev-Server proxied nur `/api` und auf `http://127.0.0.1:8080`; ein Test hält die Präfixe am
  OpenAPI-Snapshot des Servers.
- Jede Agent-Befehlszeile in `docs/**/*.html` gibt es in der CLI; ein Go-Test prüft das gegen den echten Befehlsbaum.
- `server.html`, `monitoring.html` und die Kommentare beschreiben den Code, wie er ist; der Server-Default von
  `MTLS_ENFORCE` ist durch einen Test gepinnt.

Nicht-Ziele (YAGNI):
- Kein Umbau auf `uv`/`pyproject.toml`; `DEVELOPMENT.md` bleibt, wie es ist.
- Keine Angleichung der Troubleshooting-Seiten über die genannten Stellen hinaus (DE und EN sind verschieden
  gegliedert); keine Prüfung von `README.md`/`DEVELOPMENT.md` durch den neuen Go-Test (Markdown, keine `<code>`-Blöcke;
  beide sind heute richtig).
- Keine Änderung an Verhalten von Server, Gateway, Agent oder Web-Build; T6/T7 ändern nur Kommentare (T7 dazu einen
  Test).
- Die „permissive rollout“-Kommentare im Agent (`apps/agent/internal/provision/provision.go:136`,
  `apps/agent/internal/enroll/client.go:30`) beschreiben die Geschichte und behaupten keinen Default; sie bleiben.
- Veraltete Versionsangaben im EN-Tech-Stack (`docs/en/developer/index.html:38-40`) und die Kommentare zur
  „Phase 11“ in `apps/web/vite.config.ts:48-54` gehören zu keiner der Zeilen (Bericht an die Session).

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien | Zeile |
|---|---|---|---|
| T1 | web | `apps/web/vite.config.ts`, `apps/web/src/vite-config.test.ts` (neu), `docs/developer/webui.html`, `docs/en/developer/webui.html`, `CHANGELOG.md` | R-0669 |
| T2 | scripts | `docs/developer/index.html`, `docs/en/developer/index.html` | R-0669 |
| T3 | scripts | `docs/developer/server.html`, `docs/en/developer/server.html` | R-0584, R-0669 |
| T4 | scripts | `docs/developer/monitoring.html`, `docs/en/developer/monitoring.html` | R-0669 |
| T5 | agent | `apps/agent/cmd/adminhelper-agent/docs_cli_test.go` (neu), `docs/admin/troubleshooting.html`, `docs/en/admin/troubleshooting.html`, `CHANGELOG.md` | R-0731 |
| T6 | scripts | `apps/gateway/nginx.conf`, `apps/gateway/docker-entrypoint.sh` | R-0387 |
| T7 | server | `apps/server/app/core/identity.py`, `apps/server/tests/test_mtls_scope.py` | R-0387 |

Geänderte Abschnitte je Doku-Datei (für Merges mit parallelen Vorhaben): `developer/index.html` DE `:62-99` (Baum und
„Lokale Entwicklung“), EN `:46-77`; `developer/webui.html` DE+EN `:98-99` („Build & Deployment“);
`developer/server.html` DE+EN `:111` (Tabelle „FRP — TOML-Struktur“) und `:215-220` („Tests“);
`developer/monitoring.html` DE+EN `:49` („Daten-Fluss“) und `:62-79` („Monitoring-Service-Struktur“);
`admin/troubleshooting.html` DE `:105-127` („Agent meldet sich nicht mehr“, „Monitoring zeigt keine Daten“,
„FRP-Tunnel bricht ab“), EN `:61-66` und `:109-125` („Agent doesn't check in“, „Monitoring ingest dropping samples“,
„FRP visitor connect hangs“). Kein Abschnitt „Diagnose-Bundle“ (den ändert feature/ops-scripts-hardening).

Risikopfade (`scripts/dev/review-risk.txt`): T6 (`apps/gateway/*`) und T7 (`apps/server/app/core/identity.py`)
bekommen zusätzlich `security`.

## Datenmodell / API / Migrationen

Keine Migration, keine Route, kein Schema. OpenAPI bleibt gleich: `require_scope` ist keine Route, sein Docstring
geht nicht in die Beschreibung einer Route ein. Kein Vertrags-Drift Server ↔ Web ↔ Desktop ↔ Agent: T1 ändert nur
den Dev-Server von Vite (nicht den Build, nicht `vite preview`), T5 nur einen Test im Agent.

## Externe Integrationen

- Vite `server.proxy` (vite.dev/config/server-options, gelesen 2026-10-22): `Record<string, string | ProxyOptions>`,
  die String-Form `'/foo': 'http://localhost:4567'` leitet `/foo…` an das Ziel weiter. Die Seite zu `server.host`
  warnt, dass `localhost` je nach System anders aufgelöst wird; deshalb `127.0.0.1` wie im Startbefehl
  (`--host 127.0.0.1`, `DEVELOPMENT.md:761`).
- Vite `loadConfigFromFile(configEnv, configFile?, configRoot?, …)` (vite.dev/guide/api-javascript, gelesen
  2026-10-22): „Load a Vite config file manually with Rolldown“, liefert `{ path, config, dependencies } | null`. Der
  Test in T1 lädt die Config damit wie `vite` selbst (Vite 8.1.6, Vitest 4.1.11 laut `apps/web/package-lock.json`).
  Ob ein direkter `import` von `vite.config.ts` unter Vitest `__dirname` hat: nicht verifiziert, daher nicht der Weg.
- Cobra (v1.10.2, `apps/agent/go.mod`): der Go-Test nutzt den vorhandenen Helfer-Prozess aus
  `box_cli_test.go` (`checkCall`: `adminhelper-agent <words> --help`, Usage-Zeile und Flag-Tabelle), keine neue
  Cobra-API.

## Trade-offs & Alternativen

1. **Beweis für die Doku-Befehle des Agents (T5).** (a) Go-Test, der die `<code>`-Blöcke aller `docs/**/*.html`
   liest und jede `adminhelper-agent …`-Zeile mit `parseCalls`/`checkCall` aus `box_cli_test.go` gegen den echten
   Befehlsbaum prüft — **Empfehlung**: rot auf HEAD mit genau den drei Funden, hält künftige Doku fest, nutzt einen
   geprüften Parser, läuft in jeder PR-CI (Job `agent`, auch auf Windows). (b) Nur die Doku ändern, Verify
   `doc_smoke_test` — beweist nichts über die Befehle. (c) Prüfung in `scripts/dev/doc-smoke.py` — Harness-Pfad
   (`scripts/dev/*`), bräuchte die CLI als Binary.
2. **Proxy-Ziel (T1).** `http://127.0.0.1:8080` statt `localhost:8080`: gleicher Host wie der Startbefehl, keine
   Abhängigkeit von der Auflösung von `localhost`. Nur `/api`: alle Routen des Servers liegen darunter;
   `/assets` und `/fonts` liefert im Dev-Modus Vite selbst.
3. **Test für den Proxy (T1).** (a) Parität mit `apps/server/tests/openapi.snapshot.json` (jedes Präfix trifft
   mindestens einen Pfad, jeder Pfad liegt unter einem Präfix) plus Pin des Ziels — **Empfehlung**: fängt genau die
   Klasse des Fehlers (Präfix ohne Route). (b) Kein Test, Ausnahme „Framework-Wiring“ — ließe `/auth`/`/health`
   wiederkehren.
4. **Pin des Server-Defaults (T7).** Unterprozess mit `sys.executable -c "from app.core import config; …"` ohne
   `MTLS_ENFORCE` im Env — **Empfehlung**: misst den echten Import, ändert den Zustand der laufenden Suite nicht.
   Alternative `importlib.reload(config)` verstellt `config.MTLS_ENFORCE` für alle folgenden Tests.
5. **Erweiterungen innerhalb der Zeilen.** Mitgenommen, weil derselbe Fehler auf derselben Seite oder im selben
   Kommentarblock: EN `frpc rotate` und DE „< 30 Tagen/CRL“ (T5, R-0731), `apps/frps/` im Baum, „Sourcemaps an“,
   `server/tests/`, EN-Agent `run` (T1–T3, R-0669), `docker-entrypoint.sh:32-33` und `identity.py:233-235` (T6, T7,
   R-0387). Ohne sie bliebe auf denselben Seiten falsche Doku neben der korrigierten.

## Risiken & Rollback

- T1 ändert den Dev-Server-Proxy: wer den Server lokal bewusst auf `8000` startet, muss auf `8080` gehen (wie in
  `DEVELOPMENT.md`). Build, `vite preview` und die Playwright-Journeys (gemockte Routen) bleiben unberührt.
- T5: Der Go-Test macht künftige Doku, die einen Agent-Befehl nennt, den es (noch) nicht gibt, im Job `agent` rot.
  Das ist gewollt; Vorhaben, die einen Befehl samt Doku einführen (etwa `--token-stdin` in
  feature/ops-install-hardening), sind im selben Branch grün.
- T6/T7: nur Kommentare und ein Test; Revert genügt. Jede Task ist ein eigener Commit ohne Datenänderung.

## Doku-Impact

Die Tasks T2–T4 sind selbst Doku (DE+EN), ohne CHANGELOG. T1: `docs/developer/webui.html` + EN, CHANGELOG (Fixed).
T5: Troubleshooting DE+EN, CHANGELOG (Fixed). T6, T7: keine (Kommentare).

## Offene Fragen

Keine an Kevin: Jede Änderung legen die Zeilen fest (R-0669: „venv+pip wie DEVELOPMENT.md, Vite-Proxy auf 8080 und
/api, Baum korrigieren“; R-0731: „sudo adminhelper-agent run --once --log-level debug … DE und EN angleichen“).
Die Erweiterungen (Trade-off 5) und die beiden neuen Tests sind Entscheidungen der Planung.
