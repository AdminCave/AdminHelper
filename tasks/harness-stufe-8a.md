<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 8a — Paritäts- und Contract-Gates — Task-Ledger
Status: aktiv · Branch: feature/harness-stufe-8a · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/harness-stufe-8a.md
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: keine im Abschluss (kein Cross-Host-Pfad); der nächste Wochenlauf nach dem Merge ist der reale Beweis für T4 (agent-monitoring) und T5 (Server-Hooks)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: R-0004 · Hängt ab von: R-0002 (gemergt, PR #11) · Reihenfolge: nach tasks/audit-hygiene.md (gleiche Dateien ci.yml, DEVELOPMENT.md)
Regel für jeden Guard: Nicht-Leer-Assertion mit Mindestzahl (leerer Parse = rot). Mutations-Proben laufen in einem Wegwerf-Worktree, nie im Builder-Tree.

## A — Python-Contracts (Server, Monitoring, CA-Issuer, Gateway)

### T1 — Monitoring-Proxy-Allowlist ↔ Monitoring-Routen  [x]
Komponente: apps/server · Dateien: apps/server/tests/test_monitoring_proxy_allowlist.py (neu, SPDX), apps/server/app/modules/monitoring_proxy/router.py
Änderung: Test nach Muster `test_event_whitelist.py`: liest die Routen-Decorators aller `apps/monitoring/app/routers/*.py` (Regex auf `@router.(get|post|put|delete|patch)("/…")`), bildet die Menge der ersten Pfadsegmente ohne die Server-internen `agent-keys` und `servers` (nur per `X-Internal-Key` direkt gerufen: `provisioning/helpers.py:56`, `servers/router.py:211`), und assertet Gleichheit mit `_ALLOWED_PATH_PREFIXES`. Nicht-Leer: ≥ 5 Segmente. Die toten Einträge `log` und `metrics` aus `_ALLOWED_PATH_PREFIXES` entfernen (keine Route beginnt so; der Test beweist es).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_monitoring_proxy_allowlist.py tests/test_monitoring_ingest_ratelimit.py
Doku: keine (intern)
Ergebnis: Test neu (Routen-Scan == Allowlist, Ausnahmen agent-keys/servers auf Existenz geprüft); `log`/`metrics` aus `_ALLOWED_PATH_PREFIXES` entfernt. Verify-Zeile korrigiert: `tests/test_monitoring_proxy.py` existiert nicht, der reale Proxy-Test ist `tests/test_monitoring_ingest_ratelimit.py`. 3 passed, 0 failed, 10 skipped.

### T2 — Identity-Header-Contract Gateway ↔ Server ↔ CA-Issuer  [x]
Komponente: apps/server · Dateien: apps/server/tests/test_identity_header_contract.py (neu, SPDX)
Änderung: Test liest `apps/gateway/identity-headers.conf` (alle `proxy_set_header X-… $ssl_client_…`-Namen) und die Enroll-Plane-Strips in `apps/gateway/nginx.conf` (`proxy_set_header X-Client-Verify ""` / `X-Client-Cert ""`); assertet: die zwei Client-Cert-Header entsprechen (case-insensitiv) `_H_VERIFY`/`_H_CERT` aus `apps/server/app/core/identity.py` **und** `HEADER_VERIFY`/`HEADER_CERT` aus `apps/ca-issuer/app/config.py` (per Regex aus der Datei, kein Cross-Import); die Enroll-Plane strippt genau diese zwei. Nicht-Leer: genau 2 Client-Header gefunden.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_identity_header_contract.py
Doku: keine (intern)
Ergebnis: Test neu (3 Fälle: genau 2 cert-abgeleitete Header; Gleichheit mit `_H_VERIFY`/`_H_CERT` und — per Regex — `HEADER_VERIFY`/`HEADER_CERT`; :8444 strippt genau diese zwei). Der Enroll-Plane-Block wird per Klammer-Matching aus `nginx.conf` geschnitten, damit ein Strip auf :443 den Test nicht fälschlich grün macht. Kein Drift gefunden. Review-Runde 1 fand eine echte Lücke: die Mengen-Gleichheit galt für den ganzen :8444-Block, also hätte ein Strip *nur* in einer `location` gereicht — nginx vererbt `proxy_set_header` aber nicht mehr, sobald eine Location eigene setzt. Behoben: `_server_level()` schneidet die Location-Blöcke weg, die Assertion gilt jetzt auf Server-Ebene (Gegenprobe im Wegwerf-Worktree: Server-Level-Strips entfernt ⇒ rot). Dazu `_BLANKED` auf den `X-Client-`-Namensraum gefiltert, damit ein späteres `Connection ""` keinen Fehlalarm auslöst. Evidenz für diese Einheit: 3 passed, 0 failed (Verify-Zeile).

### T3 — Enrollment-Hash-Lockstep Server ↔ CA-Issuer  [x]
Komponente: apps/server · Dateien: apps/server/tests/test_enrollment_hash_lockstep.py (neu, SPDX)
Änderung: Test importiert `hash_api_key` (`app/core/auth.py`), liest den Body von `_hash` aus `apps/ca-issuer/app/db.py` als Text und assertet, dass beide dieselbe Formel sind (`hashlib.sha256(<arg>.encode()).hexdigest()`), dass `app/modules/enrollment/service.py` `hash_api_key(` für `hashed_token` aufruft, und dass `hash_api_key("probe")` den bekannten SHA-256-Hex-Wert liefert. Nicht-Leer: beide Funktionsbodies gefunden.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_enrollment_hash_lockstep.py
Doku: keine (intern)
Ergebnis: Test neu, 4 Fälle: normalisierte Funktionskörper von `hash_api_key` und ca-issuer `_hash` gleich · `hash_api_key("probe")` gegen einen unabhängig berechneten SHA-256 · `enrollment/service.py` speichert `hashed_token` darüber · `ca-issuer/app/db.py` sucht den Token darüber. Der letzte Fall kam aus dem Review: ohne ihn blieb der Lockstep einseitig — ersetzt man im Issuer `hashed_token == _hash(token)` durch `== token`, war der Test grün, obwohl Enrollment bricht. Normalisiert wird über `ast` statt per Regex: Docstring und Kommentare fallen weg (ein Docstring auf einer Seite meldete sonst einen Hash-Drift, den es nicht gibt), die Umbenennung des Parameters trifft nur echte Namensreferenzen, und ein Decorator über der Funktion wird zurückgewiesen — er kann das Digest ändern, ohne den Body anzufassen. 4 passed; volle Server-Suite auf sauberer Basis (HEAD + nur diese Datei, im Wegwerf-Worktree gemessen) 504 passed, 2 skipped.

### T4 — Transition-Pipeline nur im check_engine (B3)  [ ]
Komponente: apps/monitoring · Dateien: apps/monitoring/app/check_engine.py, apps/monitoring/app/routers/agent.py, apps/monitoring/tests/test_architecture_transitions.py (neu, SPDX)
Änderung: Read-Modify-Write aus `check_engine.py:190-221` (old_status → `next_fail_count` → `effective_status` → Transition-Log → `_dispatch_alert_bg`/`process_alert`) in eine Funktion `apply_result(db, check, ok, message, …)` im `check_engine` ziehen; `routers/agent.py:267-299` ruft sie und verliert seine Kopie samt eigenem `_dispatch_alert_bg`. Danach Architektur-Test (Text-Scan über `apps/monitoring/app/**/*.py`): `next_fail_count(`, `effective_status(` und der Log-String `"Check '%s': %s -> %s (%s)"` kommen außerhalb von `check_engine.py` nicht vor; `_dispatch_alert_bg` ist genau einmal definiert. Nicht-Leer: die Symbole existieren in `check_engine.py`. Bestehende Router-/Engine-Tests bleiben unverändert grün. (Offene Frage 1 der Spec — Empfehlung Refactor.)
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: keine (intern)

### T5 — SSRF-Guard: DNS-Timeout auf den Server, dann Paritätstest  [ ]
Komponente: apps/server · Dateien: apps/server/app/core/ssrf.py, apps/server/tests/test_ssrf_parity.py (neu, SPDX), apps/server/tests/test_ssrf.py (falls vorhanden, sonst neu)
Änderung: `_DNS_RESOLVER`/`_DNS_TIMEOUT_S`-Mechanik aus `apps/monitoring/app/core/ssrf.py` in den Server übernehmen (Test: Resolver-Stub, der länger als der Timeout blockiert, ⇒ `is_private_url` fail-closed innerhalb des Timeouts). Dann Paritätstest: beide Dateien einlesen, Docstrings und Kommentare entfernen, Rest normalisieren und auf Gleichheit prüfen; Allowlist als Liste `(muster, begründung)`, initial leer, mit Assertion `len(allowlist) <= 3`. Nicht-Leer: normalisierter Body ≥ 30 Zeilen. (Offene Frage 2 der Spec.)
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ssrf_parity.py tests/test_ssrf.py
Doku: keine (intern; Timeout ist kein dokumentiertes Verhalten)

### T6 — Env-Parität Compose ↔ .env.example ↔ config.py  [ ]
Komponente: apps/server · Dateien: apps/server/tests/test_env_parity.py (neu, SPDX)
Änderung: Test nach Spec Trade-off 6: (a) `os.environ.get("X")`/`os.environ["X"]` ohne Default in `apps/{server,monitoring}/app/core/config.py` und `apps/ca-issuer/app/config.py` ⇒ `X` ist in `docker-compose.yml` beim jeweiligen Service gesetzt; (b) jeder `environment:`-Key eines Python-Services in Compose wird vom Code dieses Services gelesen (`os.environ` in `app/**`, plus `LOG_LEVEL` in `logging_config.py`); (c) `${VAR}`-Substitutionen in Compose ⊆ `.env.example`-Keys und umgekehrt (Compose-only-Infra wie `FRP_*_PORT`, `*_IMAGE`, `VM_RETENTION` zählt zu (c), nicht zu (b)). Für (b) zählt als „gelesen" auch `apps/<svc>/docker-entrypoint.sh`; Interpreter-/OS-Variablen (`PYTHON*`, `TZ`, `LANG`, `LC_*`) sind Laufzeit, keine App-Konfiguration, und werden von (b) nicht verlangt — das ist eine feste Regel, keine Ausnahmeliste. **Keine Ausnahmeliste.** Ist eine der drei Mengen beim Erstlauf nicht leer: Task auf `[?]` mit der Liste, Test nicht committen (Roadmap-Regel). Nicht-Leer: ≥ 10 Variablen je Seite.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_env_parity.py
Doku: keine (intern)

### T7 — OpenAPI-Snapshot Server  [ ]
Komponente: apps/server · Dateien: apps/server/tests/test_openapi_snapshot.py (neu, SPDX), apps/server/tests/openapi.snapshot.json (neu), apps/server/tests/conftest.py
Änderung: `app.openapi()` (aus `app.main`) als JSON mit sortierten Schlüsseln und `indent=2` gegen die Datei; vorher normalisieren: `info.version` auf `"0.0.0"` setzen (die reale Version kommt aus Tag/Build-Arg und würde bei jedem Release Snapshot-Churn erzeugen) und ein etwaiges `servers`-Feld entfernen; Mismatch ⇒ Assertion mit kompaktem `difflib`-Unified-Diff (max. 40 Zeilen) und Hinweis `pytest --update-openapi-snapshot`; die Option in `conftest.py` (`pytest_addoption`) schreibt die Datei neu. Nicht-Leer: ≥ 20 Pfade im Snapshot. Kein DB-Zugriff nötig (App-Import reicht; der Test hängt nicht an `pg_engine`).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_openapi_snapshot.py
Doku: DEVELOPMENT.md Absatz „OpenAPI-Snapshot aktualisieren" (nur einmal, in T7) · CHANGELOG Unreleased/Added

### T8 — OpenAPI-Snapshot Monitoring  [ ]
Komponente: apps/monitoring · Dateien: apps/monitoring/tests/test_openapi_snapshot.py (neu, SPDX), apps/monitoring/tests/openapi.snapshot.json (neu), apps/monitoring/tests/conftest.py
Änderung: wie T7 für `apps/monitoring/app/main.py`; dieselbe Option `--update-openapi-snapshot`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_openapi_snapshot.py
Doku: keine (Absatz aus T7 gilt für beide)
Abhängt von: T7

### T9 — oasdiff-Gate: Skript + hermetischer Test  [ ]
Komponente: scripts · Dateien: scripts/dev/openapi-breaking.sh (neu, SPDX), scripts/tests/openapi_breaking_test.sh (neu, SPDX), scripts/tests/run.sh (nur `AH_SCRIPT_TESTS_DEFAULT`)
Änderung: `bash scripts/dev/openapi-breaking.sh <server|monitoring> [--base <ref>]` — Basis-Snapshot per `git show <ref>:apps/<k>/tests/openapi.snapshot.json` (Default `origin/main`, fehlt der Snapshot dort ⇒ „kein Vergleich, neu" Exit 0 mit Meldung), Revision = Arbeitsbaum; `oasdiff breaking <base> <rev> --fail-on ERR --format text`; `oasdiff` fehlt ⇒ Exit 75 (SKIP, unter `--strict` rot). Hermetischer Test mit Fake-`oasdiff` im PATH (Argument-Mitschnitt; Exit 1 ⇒ Skript 1; Exit 0 ⇒ 0; kein Binary ⇒ 75; fehlender Basis-Snapshot ⇒ 0), eingetragen in `AH_SCRIPT_TESTS_DEFAULT`. shellcheck sauber.
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: keine (T10 dokumentiert das Gate)
Abhängt von: T7

### T10 — CI-Job openapi-compat  [ ]
Komponente: .github · Dateien: .github/workflows/ci.yml, docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: Job `openapi-compat` (ubuntu-latest, `fetch-depth: 0`): Tarball `oasdiff_1.32.0_linux_amd64.tar.gz` vom Release `v1.32.0` laden, SHA-256 aus `checksums.txt` als Literal im Workflow pinnen und prüfen, Binary nach `$RUNNER_TEMP/bin`; dann `bash scripts/dev/openapi-breaking.sh server` und `… monitoring` mit `--base origin/${{ github.base_ref || 'main' }}`. Kommentar im Workflow: warum Tarball statt `go install` (go-Direktive 1.26 vs. Toolchain 1.25, PR #14). Doku-Abschnitt „Paritäts- und Contract-Gates" in cicd.html DE + EN anlegen (Tabelle: Gate · Wahrheit A · Wahrheit B · wo es läuft) — die späteren Tasks tragen dort nur Zeilen nach.
Verify: bash scripts/tests/run.sh lint --strict --only scripts   (shellcheck über die Workflow-Bash-Steps entfällt; die Gate-Logik steckt in T9) — plus nach dem Push: der Job ist im PR-CI grün
Doku: docs/developer/cicd.html DE+EN (neuer Abschnitt) · CHANGELOG Unreleased/Added
Abhängt von: T9

## B — Desktop- und Web-Contracts

### T11 — Tauri-IPC-Inventar  [ ]
Komponente: apps/desktop-ui · Dateien: apps/desktop/ui/src/lib/bridge/ipc.inventory.test.ts (neu, SPDX)
Änderung: Vitest liest per `node:fs` (Pfad relativ zu `import.meta.url`) `../src-tauri/src/commands.rs` (Namen nach jedem `#[tauri::command]`), `../src-tauri/src/main.rs` (Einträge in `generate_handler![…]`) und `src/lib/bridge/index.ts` (`invoke<…>('name'`): assertet definiert == registriert, aufgerufen ⊆ registriert, registriert − aufgerufen == Allowlist `{ enroll_device: 'kein UI-Aufrufer; Roadmap-Zeile REF' }`. Nicht-Leer: ≥ 30 Commands, ≥ 30 Aufrufe.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (intern)

### T12 — Serde-Structs ↔ bridge/types.ts  [ ]
Komponente: apps/desktop-ui · Dateien: apps/desktop/ui/src/lib/bridge/types.parity.test.ts (neu, SPDX), apps/desktop/ui/src/lib/bridge/types.ts
Änderung: Test parst die `#[derive(… Serialize|Deserialize …)]`-Structs aus `models.rs`, `tunnel.rs` und `ansible.rs` (Felder, `rename_all`, `#[serde(rename = "…")]`, `Option<…>` ⇒ optional) und vergleicht **Feldnamen** je Struct mit dem gleichnamigen `interface` in `types.ts` (Optionalität/Nullbarkeit wird nicht verglichen — serde und TS modellieren `Option<T>` unterschiedlich, das wäre ein Rauschgenerator); Enums (`ConnectionKind`, `SyncMode`, `Rdp*`) als Union-Literale. `RdpErrorPayload` steht auf einer Allowlist „Event, kein Command" mit Begründung. Den heutigen Drift beheben: `tunnelType: string` in `ResolvedConnection` (`types.ts:97-101`). Nicht-Leer: ≥ 10 Struct-Paare.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (intern)

### T13 — Playwright-Mock-Contract gegen den Server-Snapshot  [ ]
Komponente: apps/web · Dateien: apps/web/tests/e2e/mocks.ts, apps/web/src/lib/api/mocks.contract.test.ts (neu, SPDX)
Änderung: `mocks.ts` exportiert zusätzlich eine Tabelle `MOCK_FIXTURES: Array<{ method, path, status, body }>` (die heutigen Inline-Bodies, keine Verhaltensänderung für `mockApi`; `Page`/`Route` bleiben `import type`, damit der Vitest kein Playwright lädt). Der Vitest lädt `apps/server/tests/openapi.snapshot.json`, findet je Fixture die Operation (Pfad-Template-Matching auf `/api/<path>`), löst `$ref` nach `components.schemas` auf und prüft Schlüsselmengen laut Spec Trade-off 3 (Arrays: Item-Schema gegen erstes Element). Nicht-Leer: ≥ 8 Fixtures zugeordnet; unzuordenbare Fixture = rot.
Verify: bash scripts/dev/verify.sh web --strict
Doku: keine (intern)
Abhängt von: T7

### T14 — sync-from-web.sh --check  [ ]
Komponente: apps/desktop-ui · Dateien: apps/desktop/ui/scripts/sync-from-web.sh, .github/workflows/ci.yml, DEVELOPMENT.md
Änderung: Modus `--check` (Spec Trade-off 5): für jedes `export (interface|type|const) Name` des Web-`types.ts` den Block (bis zur nächsten Top-Level-Zeile) extrahieren und byte-identisch im Desktop-`types.ts` erwarten; Abweichungen als Diff je Symbol, Exit 1; der bestehende Guard bleibt. CI-Step im Job `desktop-ui`. Zeigt der Erstlauf Drift in ≤ 3 Typen ⇒ in dieser Task nachziehen (Desktop = Ziel), sonst `[?]` mit der Liste. DEVELOPMENT.md-Absatz zum Skript um `--check` ergänzen.
Verify: bash apps/desktop/ui/scripts/sync-from-web.sh --check
Doku: DEVELOPMENT.md · docs/developer/cicd.html DE+EN Tabellenzeile

### T15 — Svelte-Mount-Smoke Web  [ ]
Komponente: apps/web · Dateien: apps/web/src/mount.smoke.test.ts (neu, SPDX)
Änderung: Allowlist von 10 Komponenten ohne Pflicht-Props (Kandidaten: die 5 unter `lib/components/ui`, 2 `layout`, 3 `pages`/`modals`), je `render()` unter jsdom mit `console.error`-Spy; jeder Aufruf von `console.error`/unbehandelte Exception ist rot, `effect_update_depth_exceeded` mit eigener Meldung. Nicht-Leer: 10 Einträge, jede Datei existiert.
Verify: bash scripts/dev/verify.sh web --strict
Doku: keine (intern)

### T16 — Svelte-Mount-Smoke Desktop-UI  [ ]
Komponente: apps/desktop-ui · Dateien: apps/desktop/ui/src/mount.smoke.test.ts (neu, SPDX)
Änderung: wie T15 mit 10 Komponenten aus `src/components/**`, die heute keinen Mount-Test haben; Bridge-Aufrufe per `vi.mock('$lib/bridge')` (bzw. dem Import-Pfad der Komponenten) stubben, wie es die bestehenden 19 Mount-Tests tun.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (intern)

## C — Doku-Gate

### T17 — doc-smoke.py + hermetischer Test  [ ]
Komponente: scripts · Dateien: scripts/dev/doc-smoke.py (neu, SPDX), scripts/tests/doc_smoke_test.sh (neu, SPDX), scripts/tests/run.sh (nur `AH_SCRIPT_TESTS_DEFAULT`)
Änderung: Python-Stdlib-Skript: sammelt aus `docs/**/*.html` jedes `<code>…</code>`, das mit `apps/`, `scripts/`, `docs/`, `.github/` oder `.claude/` beginnt (Pfad bis zum ersten Leerzeichen/`[`), und prüft die Existenz im Repo (Verzeichnisse mit `/` am Ende erlaubt); zweite Prüfung: `<code>`-Inhalte der Form `[A-Z][A-Z0-9_]{3,}` gegen die Env-Namen aus `apps/{server,monitoring}/app/core/config.py`, `apps/ca-issuer/app/config.py` und `.env.example` (nur Treffer, die in keiner Quelle vorkommen, gelten als Drift). Ausnahmedatei `scripts/dev/doc-smoke-allow.txt` (eine Zeile je Eintrag mit Begründung nach `#`), das Skript verweigert > 5 Einträge. Flags: `--paths` (Default), `--env`, `--strict`; Ausgabe je Fund `datei:zeile: <eintrag>`. Hermetischer Test mit Fixture-Docs (guter Pfad, kaputter Pfad, Env-Name; Allow-Datei mit 6 Zeilen ⇒ Exit 2). Erstlauf auf `main`: Pfade ⇒ Funde in dieser Task beheben (Doku korrigieren) oder ≤ 5 begründet ausnehmen; Env-Namen ⇒ liefert der Erstlauf > 5, bleibt `--env` bis zur Triage außerhalb des Gates (Task-Vermerk mit Zahl). Nicht-Leer: ≥ 30 Pfade gesammelt.
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: keine (T18)

### T18 — doc-smoke als Gate im Job ops-scripts  [ ]
Komponente: .github · Dateien: .github/workflows/ci.yml, docs/developer/cicd.html, docs/en/developer/cicd.html, DEVELOPMENT.md
Änderung: Step `python3 scripts/dev/doc-smoke.py --strict` (mit `--env` nur, wenn T17 die Env-Prüfung scharf gestellt hat) im Job `ops-scripts`; Tabellenzeile im Gate-Abschnitt DE + EN; DEVELOPMENT.md ein Absatz (Aufruf, Ausnahmedatei, Deckel 5).
Verify: bash scripts/tests/run.sh unit --strict --only scripts   — plus nach dem Push: Job grün
Doku: docs/developer/cicd.html DE+EN · DEVELOPMENT.md · CHANGELOG Unreleased/Added
Abhängt von: T17

## Abschluss
- Gesamt: `bash scripts/tests/run.sh quick --strict` grün; `bash scripts/dev/verify.sh all --strict` grün.
- Mutations-Proben aus der Spec („Verify-Prinzip") in einem Wegwerf-Worktree: je Guard eine Mutation ⇒ rot; Ergebnisliste in den PR-Body.
- Roadmap-Zeilen (Kevin, privat): `enroll_device` (REF), Funde aus T6/T14/T17, falls `[?]`.
