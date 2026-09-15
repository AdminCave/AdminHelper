<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 8a — Paritäts- und Contract-Gates (VM-freie Orakel)

Roadmap-Zeile R-0004 · Quelle: `tasks/private/autonomy-roadmap.md` §Stufe 8 (8a) und F1 §5a · Stand 2026-09-14.

## Problem / Motivation

Zwei der Fehlerklassen, die in der Release-Historie am häufigsten durchgerutscht sind, brauchen
keine VM, um gefunden zu werden: **„Kopie driftet"** (dieselbe Wahrheit an zwei Stellen, eine wird
geändert) und **„Vertrag bricht still"** (ein Feld, ein Header, ein Pfad ändert sich auf einer Seite).
Heute prüft das nur ein einziger Test dieser Art (`apps/server/tests/test_event_whitelist.py`) und
der CI-Job `frp-consistency`. Die Exploration für diese Spec hat auf `main` (11ab6dc8) bereits fünf
reale Drifts gefunden, die keiner der bestehenden Tests sieht:

1. `ResolvedConnection` (`apps/desktop/src-tauri/src/tunnel.rs:28-32`) hat vier Felder, das TS-Gegenstück
   in `apps/desktop/ui/src/lib/bridge/types.ts:97-101` nur drei — `tunnelType` fehlt.
2. Die Status-Transition-Pipeline (`next_fail_count`, `effective_status`, Transition-Log,
   `_dispatch_alert_bg`) existiert zweimal: `apps/monitoring/app/check_engine.py:190-221` und als
   Kopie in `apps/monitoring/app/routers/agent.py:267-299`.
3. `apps/server/app/core/ssrf.py` sagt „Mirrors the monitoring service's guard", hat aber den
   DNS-Timeout (5 s, `ThreadPoolExecutor`) des Monitoring-Originals nicht — ein hängender Resolver
   blockiert den Webhook-Pfad bis zum OS-Default.
4. `_ALLOWED_PATH_PREFIXES` im Monitoring-Proxy enthält `log` und `metrics`; keine Monitoring-Route
   beginnt so (sie existieren nur als `alerts/log` und `checks/{id}/metrics`).
5. `apps/desktop/ui/scripts/sync-from-web.sh` bricht heute ab: das Desktop-`types.ts` (573 Zeilen) hat
   30 Exporte, die das Web-`types.ts` (208 Zeilen) nicht kennt — die „gemeinsame" Datei ist keine mehr.

Dazu ein registrierter Tauri-Command ohne UI-Aufrufer (`enroll_device`, `commands.rs:105`) und
39 Repo-Pfade in `docs/**/*.html`, die niemand gegen den Baum prüft.

## Ziel & Nicht-Ziele

**Ziel.** Jede der genannten Wahrheiten bekommt einen Test, der bei einer Einzelmutation rot wird und
in Sekunden ohne VM läuft (PR-CI + `run.sh quick`). Gefundene Drifts werden im selben Ledger behoben,
wo das klein ist; sonst als Roadmap-Zeile triagiert. Kein Guard ohne Nicht-Leer-Assertion (ein Test,
der nichts einliest, ist grün und wertlos).

**Nicht-Ziele.** Keine Generatoren (Schemathesis/Hypothesis = Stufe 8b). Keine OpenAPI-Snapshots
für den CA-Issuer (Factory `build_issuer`, drei Routen — kein Drift-Risiko, YAGNI). Kein Zusammenlegen
von Web- und Desktop-Modulen (bewusst getrennt laut `sync-from-web.sh`). Keine i18n-Arbeit — die
Keyset-Parität DE/EN existiert in beiden Frontends bereits (`apps/web/src/lib/i18n/i18n.test.ts:30-49`,
`apps/desktop/ui/src/lib/i18n/i18n.test.ts:85-104`). Keine Linter-Welle. Kein neuer CI-Job für den
Desktop-E2E. **Danach (nicht hier):** die `lib/api/types.ts` beider Frontends gegen den Server-OpenAPI-Snapshot
prüfen — das wäre das bessere Orakel als der Web↔Desktop-Vergleich aus T14, braucht aber einen TS-Interface-Parser
(Roadmap-Zeile IDEE).

## Betroffene Komponenten & Dateien

| Bereich | Wahrheit A | Wahrheit B | Neuer Test / Gate |
|---|---|---|---|
| Monitoring-Proxy | `apps/server/app/modules/monitoring_proxy/router.py` `_ALLOWED_PATH_PREFIXES` | `apps/monitoring/app/routers/{checks,alerts,templates,maintenance,agent}.py` Routen-Pfade | `apps/server/tests/test_monitoring_proxy_allowlist.py` |
| Identity-Header | `apps/gateway/identity-headers.conf`, `apps/gateway/nginx.conf` (Enroll-Plane strippt) | `apps/server/app/core/identity.py` `_H_VERIFY/_H_CERT`, `apps/ca-issuer/app/config.py` `HEADER_VERIFY/HEADER_CERT` | `apps/server/tests/test_identity_header_contract.py` |
| Enrollment-Hash | `apps/server/app/core/auth.py` `hash_api_key` (von `enrollment/service.py:42` genutzt) | `apps/ca-issuer/app/db.py` `_hash` | `apps/server/tests/test_enrollment_hash_lockstep.py` |
| Transition-Pipeline | `apps/monitoring/app/check_engine.py` | `apps/monitoring/app/routers/agent.py` (Kopie) | `apps/monitoring/tests/test_architecture_transitions.py` |
| SSRF-Guard | `apps/monitoring/app/core/ssrf.py` (74 Z.) | `apps/server/app/core/ssrf.py` (64 Z.) | `apps/server/tests/test_ssrf_parity.py` |
| Env-Parität | `docker-compose.yml`, `.env.example` | `apps/{server,monitoring}/app/core/config.py`, `apps/ca-issuer/app/config.py` (`os.environ.get`, keine BaseSettings) | `apps/server/tests/test_env_parity.py` |
| OpenAPI | `app.openapi()` von `apps/{server,monitoring}/app/main.py` | `apps/{server,monitoring}/tests/openapi.snapshot.json` (neu) | `test_openapi_snapshot.py` je Dienst + `scripts/dev/openapi-breaking.sh` (oasdiff) + CI-Job `openapi-compat` |
| Tauri-IPC | `apps/desktop/src-tauri/src/commands.rs` (33 `#[tauri::command]`), `main.rs:89-123` `generate_handler!` | `apps/desktop/ui/src/lib/bridge/index.ts` (32 `invoke('…')`) | `apps/desktop/ui/src/lib/bridge/ipc.inventory.test.ts` |
| Serde ↔ TS | `models.rs`, `tunnel.rs` (`TunnelMapping`, `ResolvedConnection`), `ansible.rs` (`AnsibleTarget`) | `apps/desktop/ui/src/lib/bridge/types.ts` | `apps/desktop/ui/src/lib/bridge/types.parity.test.ts` |
| Playwright-Mocks | `apps/web/tests/e2e/mocks.ts` (Bodies inline) | `apps/server/tests/openapi.snapshot.json` | `apps/web/src/lib/api/mocks.contract.test.ts` |
| Web → Desktop | `apps/web/src/lib/api/types.ts` | `apps/desktop/ui/src/lib/api/types.ts` | `apps/desktop/ui/scripts/sync-from-web.sh --check` + CI-Step |
| Svelte-Mount | 24 Komponenten in `apps/web/src/{lib/components,modals,pages}` (1 Mount-Test) | 59 in `apps/desktop/ui/src/components` (19 Mount-Tests) | `mount.smoke.test.ts` je Frontend, Allowlist 10 |
| Doku-Pfade | `docs/**/*.html` `<code>apps/…|scripts/…|docs/…|.github/…|.claude/…</code>` (49 Vorkommen, 39 Pfade, 12 Dateien) | Repo-Baum, `config.py`-Env-Namen | `scripts/dev/doc-smoke.py` + Gate im Job `ops-scripts` |

Registrierung neuer Hermetik-Tests: `AH_SCRIPT_TESTS_DEFAULT` in `scripts/tests/run.sh:455-457`
(Schleife `scripts_block()` 462-488, Exit 75 = SKIP). CI-Muster für Konsistenz-Gates:
Job `frp-consistency` in `.github/workflows/ci.yml` (`::error::` + `exit 1` je Mismatch).

## Datenmodell / API / Migrationen

Keine DB-Änderung, keine Migration, kein neuer Endpunkt. Zwei Verhaltensänderungen im Produktcode,
beide klein und beide Drift-Reparaturen:

- **Server-SSRF bekommt den DNS-Timeout des Monitorings** (5 s, fail-closed). Sichtbar nur, wenn ein
  Resolver hängt: der Webhook-Aufruf schlägt dann nach 5 s fehl statt nach dem OS-Default (~30 s).
- **Monitoring-Ingest (`routers/agent.py`) ruft die Transition-Pipeline des `check_engine` auf**, statt
  sie zu kopieren. Ergebnis je Report identisch (gleiche Funktionen, gleiche Reihenfolge); der
  bestehende Unit-Test des Routers und `test_check_engine.py` sind das Netz, der Wochenlauf
  (`agent-monitoring` im `all`-Layer) der reale Beweis.

Vertrags-Drift Server ↔ Web ↔ Desktop ↔ Agent ist genau das Thema: jeder Test dieser Spec ist eine
Drift-Sonde. Der OpenAPI-Snapshot wird im **selben Commit** wie eine API-Änderung aktualisiert
(Frage 18 der Roadmap: sofort Gate, kein Report-Monat).

## Externe Integrationen

- **oasdiff** (`oasdiff breaking <base> <revision> --fail-on ERR` → Exit 1 bei ERR-Änderungen;
  Formate u. a. `githubactions`, `text`; OpenAPI 3.1 unterstützt) — verifiziert gegen
  `docs/BREAKING-CHANGES.md` des Projekts (2026-09-14). **Alle** Versionen v1.24.0 bis v1.32.0
  verlangen `go 1.26` (Go-Proxy `.mod`, 2026-09-14); die Toolchain des Repos ist 1.25 mit
  `GOTOOLCHAIN=local` — `go install` fiele so wie bei govulncheck (PR #14). Daher: **Release-Tarball
  `oasdiff_1.32.0_linux_amd64.tar.gz` mit SHA-256 aus `checksums.txt`**, gepinnt im Workflow.
- **inline-snapshot** (Roadmap [Q42]) wird **nicht** eingesetzt — siehe Trade-offs.
- Kein FRP-, Tauri-IPC- oder VictoriaMetrics-Wire-Format wird geändert; die Tauri-Tests lesen nur
  Quelltext.

## Trade-offs & Alternativen

1. **OpenAPI-Snapshot: schlichter Gleichheitstest statt inline-snapshot.** `app.openapi()` als sortiertes
   JSON gegen `tests/openapi.snapshot.json`; Aktualisierung über die pytest-Option
   `--update-openapi-snapshot` (conftest `addoption`, ~10 Zeilen). inline-snapshot brächte eine neue
   Abhängigkeit, dessen `external()`-Ablage ist in der Doku nicht ausreichend belegt (Format/Verzeichnis
   unverifiziert), und im CI ist es laut Doku ohnehin `disable` (dann wirkt nur die nackte Gleichheit).
   **Empfehlung:** Gleichheitstest. Trade-off: kein Review-Modus; der Diff ist der `git diff` des Snapshots.
2. **oasdiff als Tarball statt `go install`** (siehe oben). Alternative: eigener `setup-go` mit 1.26 nur
   für diesen Job — koppelt einen Prüfjob an eine zweite Toolchain. **Empfehlung:** Tarball + Checksumme.
3. **Playwright-Mock-Contract ohne neue Abhängigkeit.** Statt JSON-Schema-Validierung (ajv, neue
   devDependency) vergleicht der Test **Schlüsselmengen**: `required`-Felder des Response-Schemas ⊆
   Mock-Body-Keys und Mock-Body-Keys ⊆ `properties` (sofern `additionalProperties` nicht true), `$ref`
   nach `components.schemas` aufgelöst. Findet Feld-Umbenennungen und vergessene Pflichtfelder; keine
   Typprüfung. **Empfehlung:** Schlüsselmengen; ajv erst, wenn ein Typ-Drift real durchrutscht.
4. **Transition-Pipeline: Refactor statt Allowlist.** Ein Architektur-Test mit Ausnahme für `agent.py`
   verrottet (Roadmap: „Ausnahmelisten sind der Ort, an dem solche Tests verrotten"). **Empfehlung:**
   `apply_result()` im `check_engine`, `agent.py` ruft es — B3 aus dem Audit wird damit erledigt.
5. **`sync-from-web.sh --check` als Teilmengen-Parität.** Volle Datei-Identität ist heute unerreichbar
   (30 Desktop-only-Exporte). `--check` prüft: jeder `export interface|type|const` des Web-`types.ts`
   existiert im Desktop-`types.ts` **byte-identisch** (Block-Vergleich). Drift innerhalb der gemeinsamen
   Menge ist das reale Risiko (Server-Typ ändert sich, Web zieht nach, Desktop nicht). **Empfehlung:**
   Teilmenge; Erstlauf-Drift ≤ 3 Typen wird im Ledger behoben, sonst `[?]`.
6. **Env-Parität eng definiert, damit die Ausnahmeliste leer sein kann:** (a) jede von einem Dienst
   gelesene Variable **ohne Default** ist in `docker-compose.yml` für diesen Dienst gesetzt; (b) jede
   Variable, die Compose einem Dienst unter `environment:` gibt, wird von dessen Code gelesen (fängt
   Umbenennungen); (c) jede `${VAR}`-Substitution in Compose steht in `.env.example` und umgekehrt.
   Variablen mit Default, die Compose nicht setzt (`DATA_DIR`, `DB_POOL_SIZE`, …), sind legitim und
   werden nicht gemeldet. Ist die Liste beim Erstlauf trotzdem nicht leer → `[?]`, keine Ausnahmeliste.
7. **Doku-Smoke zweistufig:** Repo-Pfade sind sofort Gate (39 Pfade, klein). Env-Namen (`<code>` in
   Großbuchstaben mit `_`) gegen die drei `config.py` werden im selben Skript geprüft, aber erst Gate,
   wenn der Erstlauf ≤ 5 Ausnahmen liefert (Ausnahmedatei `scripts/dev/doc-smoke-allow.txt`, das Skript
   verweigert mehr als 5 Einträge).

## Risiken & Rollback

- **Snapshot-Reibung:** jede API-Änderung braucht den Snapshot-Update im selben Commit — gewollt
  (Frage 18). Rollback: Test löschen, Snapshot löschen; kein Zustand außerhalb des Repos.
- **Quelltext-Parser (Regex) in Tests** (`commands.rs`, `models.rs`, Router-Decorators, nginx-Conf) sind
  an Formatierung gekoppelt. Gegenmittel: `cargo fmt`/`ruff format` sind Gates, und jeder Parser hat eine
  Nicht-Leer-Assertion mit Mindestzahl (z. B. ≥ 30 Commands), damit ein leerer Parse rot ist statt grün.
- **SSRF-Timeout auf dem Server:** ein `ThreadPoolExecutor` pro Prozess (4 Worker) wie im Monitoring;
  unter `uvicorn`-Workern je Prozess einer. Rollback: `git revert` des Tasks.
- **Monitoring-Refactor:** Verhalten identisch nach Konstruktion; Risiko ist ein übersehener
  Seiteneffekt im Ingest (Alert-Dispatch-Reihenfolge). Netz: Router-Tests, `test_check_engine.py`,
  Wochenlauf `agent-monitoring`. Rollback: `git revert`.
- **oasdiff-Tarball-Pin:** bricht, wenn GitHub das Asset entfernt — dann rot mit klarer Ursache, nicht
  still grün. Der Job hängt nicht an der Go-Toolchain.
- **CI-Laufzeit:** +1 Job (oasdiff, < 1 min), +3 Steps; die Vitest-Dateien laufen in bestehenden Jobs.

## Doku-Impact

Entwicklersichtbar, nicht anwendersichtbar: `docs/developer/cicd.html` DE + EN bekommen einen Abschnitt
„Paritäts- und Contract-Gates" (Liste der Gates, Snapshot-Update-Befehl, oasdiff-Pin);
`DEVELOPMENT.md` zwei Absätze (Snapshot aktualisieren, `sync-from-web.sh --check`, `doc-smoke.py`);
`CHANGELOG.md` Unreleased/Added (Gates) und Fixed (die fünf Drifts). Keine README-Änderung.

## Offene Fragen (Design-Gate)

1. **Transition-Pipeline (Trade-off 4):** Refactor `apply_result()` in `check_engine.py` und Aufruf aus
   `routers/agent.py` — Empfehlung ja. Alternative: Test mit Ausnahme für `agent.py` (verrottet).
2. **SSRF-Timeout auf den Server portieren (Trade-off, Verhaltensänderung 5 s statt OS-Default):**
   Empfehlung ja, weil der Server-Docstring „Mirrors the monitoring service's guard" die Parität
   bereits verspricht. Alternative: Abweichung in die Allowlist mit Begründung „bewusst".
3. **OpenAPI-Snapshot ohne inline-snapshot** (Trade-off 1) — Abweichung von Roadmap [Q42]. Empfehlung ja.
4. **`sync-from-web.sh --check` als Teilmengen-Parität** (Trade-off 5) statt Datei-Identität. Empfehlung ja.
5. **`enroll_device`:** Allowlist-Eintrag im IPC-Test mit Roadmap-Zeile (REF: verdrahten oder entfernen)
   — nicht in diesem Ledger entscheiden. Empfehlung: Roadmap-Zeile, Eintrag bleibt bis zur Entscheidung.
6. **Ablageort `scripts/dev/`** für `doc-smoke.py` und `openapi-breaking.sh` laut Roadmap — das ist ein
   Harness-Pfad (CLAUDE.md Warn-Trigger 4). Alternative: `scripts/tests/`. Empfehlung: `scripts/dev/`
   wie in der Roadmap; die Stufe-4-Schutzliste nennt Dateien einzeln, nicht das Verzeichnis.

## Verify-Prinzip (aus der Roadmap, gilt für jede Task)

Jeder Paritätstest wird bei Einzelmutation rot: Header in `identity-headers.conf` umbenennen;
Präfix aus der Allowlist entfernen; Hash-Funktion im ca-issuer ändern; Feld in `types.ts` umbenennen;
Zeile in einer `ssrf.py` ändern; `enroll_device` aus der Allowlist nehmen; Response-Feld aus dem
Snapshot entfernen (oasdiff rot); Pfad in einer Doku umbenennen (doc-smoke rot); Typ im Web-`types.ts`
ändern (`--check` rot); `$effect`-Selbstabhängigkeit in einer Allowlist-Komponente (Mount-Smoke rot).
Die Mutationen laufen in einem Wegwerf-Worktree, nie im Builder-Tree (CLAUDE.md §7).
