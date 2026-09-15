<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 8a — Paritäts- und Contract-Gates — Task-Ledger
Status: blockiert · Branch: feature/harness-stufe-8a · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
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

### T4 — Transition-Pipeline nur im check_engine (B3)  [x]
Komponente: apps/monitoring · Dateien: apps/monitoring/app/check_engine.py, apps/monitoring/app/routers/agent.py, apps/monitoring/tests/test_architecture_transitions.py (neu, SPDX)
Änderung: Read-Modify-Write aus `check_engine.py:190-221` (old_status → `next_fail_count` → `effective_status` → Transition-Log → `_dispatch_alert_bg`/`process_alert`) in eine Funktion `apply_result(db, check, ok, message, …)` im `check_engine` ziehen; `routers/agent.py:267-299` ruft sie und verliert seine Kopie samt eigenem `_dispatch_alert_bg`. Danach Architektur-Test (Text-Scan über `apps/monitoring/app/**/*.py`): `next_fail_count(`, `effective_status(` und der Log-String `"Check '%s': %s -> %s (%s)"` kommen außerhalb von `check_engine.py` nicht vor; `_dispatch_alert_bg` ist genau einmal definiert. Nicht-Leer: die Symbole existieren in `check_engine.py`. Bestehende Router-/Engine-Tests bleiben unverändert grün. (Offene Frage 1 der Spec — Empfehlung Refactor.)
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: keine (intern)
Ergebnis: `apply_result(db, check, state, result_status, message, details, now, *, keep_previous_details_when_absent)` im `check_engine`;
`routers/agent.py` ruft sie und hat seine Kopie samt eigenem `_dispatch_alert_bg` verloren (−104 Zeilen). Architektur-Test neu (3 Fälle).
**Zwei Abweichungen von der Vorgabe, beide bewusst:** (1) Signatur heißt `result_status`, nicht `ok` — es gibt keinen Boolean, der Status ist
ein String. (2) Die Vorgabe „bestehende Router-/Engine-Tests bleiben unverändert" ließ sich nicht halten: der geteilte Dispatcher löst die
Session als `database.SessionLocal` auf (nur so greifen die Endpunkt-Suites weiter), deshalb braucht `test_execute_check_corrupt_config_flips_to_unknown`
diesen Patch zusätzlich, sonst zöge der Pool-Thread die echte `DATABASE_URL`; und die Transition-Zeile trägt auf dem Push-Pfad jetzt den Logger-Namen
`monitor.engine` statt `app.routers.agent` — gleiche Meldung, gleiche Eine-Zeile-pro-Übergang-Regel, aber `test_status_transition_is_logged_on_the_push_path`
pinnte den Namen (6 Stellen angepasst). Der Logger-Name ist dokumentiert — und zwar zugunsten der Änderung: `docs/admin/betrieb.html` und `docs/en/admin/operations.html` nennen `monitor.*` als Präfix des Monitoring-Containers; der Push-Pfad loggte mit `app.routers.agent` bisher **außerhalb** dieser Konvention und erfüllt sie jetzt. (Erst im Review bemerkt; meine ursprüngliche Ledger-Aussage „nirgends dokumentiert" war falsch.) Review-Nachtrag: die Scheduler-Hälfte des neuen Parameters war von keinem Test gedeckt — drei Mutationen (Default gedreht, Flag ignoriert, Zuweisung immer bedingt) blieben grün. Zwei Tests in `test_check_engine.py` schließen das; der Scheduler-Fall ruft `apply_result` bewusst OHNE Schlüsselwort, damit auch ein gedrehter Default rot wird. Dazu `is_suppressed(` in die Token-Liste des Architektur-Tests und eine Erkennung für aliasierte Importe (`… as nfc` wäre sonst durchgerutscht).
454 passed, 3 skipped (migrations-smoke: DATABASE_URL nicht gesetzt).

### T5 — SSRF-Guard: DNS-Timeout auf den Server, dann Paritätstest  [x]
Komponente: apps/server · Dateien: apps/server/app/core/ssrf.py, apps/server/tests/test_ssrf_parity.py (neu, SPDX), apps/server/tests/test_ssrf.py (falls vorhanden, sonst neu)
Änderung: `_DNS_RESOLVER`/`_DNS_TIMEOUT_S`-Mechanik aus `apps/monitoring/app/core/ssrf.py` in den Server übernehmen (Test: Resolver-Stub, der länger als der Timeout blockiert, ⇒ `is_private_url` fail-closed innerhalb des Timeouts). Dann Paritätstest: beide Dateien einlesen, Docstrings und Kommentare entfernen, Rest normalisieren und auf Gleichheit prüfen; Allowlist als Liste `(muster, begründung)`, initial leer, mit Assertion `len(allowlist) <= 3`. Nicht-Leer: normalisierter Body ≥ 30 Zeilen. (Offene Frage 2 der Spec.)
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ssrf_parity.py tests/test_ssrf.py
Doku: keine (intern; Timeout ist kein dokumentiertes Verhalten)
Ergebnis: `_DNS_RESOLVER`/`_DNS_TIMEOUT_S` in den Server portiert; `tests/test_ssrf.py` neu mit dem Timeout-Fall (Resolver-Stub schläft 2 s, `_DNS_TIMEOUT_S` auf 0,1 s gepatcht ⇒ fail-closed **und** Rückkehr unter 1 s — fail-closed allein wäre nur die halbe Zusage). Der Paritätstest vergleicht beide Dateien über `ast.unparse` nach Entfernen aller Docstrings: damit hängt er weder an Formatierung noch an Kommentaren, und die beiden Module dürfen sich weiter unterschiedlich erklären. Allowlist leer, Deckel 3. **Abweichung:** Nicht-Leer-Schwelle 25 statt 30 Zeilen — der normalisierte Guard hat real 29 Zeilen, mit 30 wäre der Test ab Zeile eins rot gewesen. Die Range-Tabelle wird bewusst nicht im Server dupliziert (sie steht in `apps/monitoring/tests/test_ssrf.py`, und der Paritätstest bindet den Server daran) — eine zweite Abschrift wäre genau das, was diese Stufe bekämpft. 3 passed.

### T6 — Env-Parität Compose ↔ .env.example ↔ config.py  [x]
Komponente: apps/server · Dateien: apps/server/tests/test_env_parity.py (neu, SPDX)
Änderung: Test nach Spec Trade-off 6: (a) `os.environ.get("X")`/`os.environ["X"]` ohne Default in `apps/{server,monitoring}/app/core/config.py` und `apps/ca-issuer/app/config.py` ⇒ `X` ist in `docker-compose.yml` beim jeweiligen Service gesetzt; (b) jeder `environment:`-Key eines Python-Services in Compose wird vom Code dieses Services gelesen (`os.environ` in `app/**`, plus `LOG_LEVEL` in `logging_config.py`); (c) `${VAR}`-Substitutionen in Compose ⊆ `.env.example`-Keys und umgekehrt (Compose-only-Infra wie `FRP_*_PORT`, `*_IMAGE`, `VM_RETENTION` zählt zu (c), nicht zu (b)). Für (b) zählt als „gelesen" auch `apps/<svc>/docker-entrypoint.sh`; Interpreter-/OS-Variablen (`PYTHON*`, `TZ`, `LANG`, `LC_*`) sind Laufzeit, keine App-Konfiguration, und werden von (b) nicht verlangt — das ist eine feste Regel, keine Ausnahmeliste. **Keine Ausnahmeliste.** Ist eine der drei Mengen beim Erstlauf nicht leer: Task auf `[?]` mit der Liste, Test nicht committen (Roadmap-Regel). Nicht-Leer: ≥ 10 Variablen je Seite.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_env_parity.py
Doku: keine (intern)
(Scan über docker-compose.yml, .env.example, die drei config.py, app/**, docker-entrypoint.sh):
- **(a) leer** — aber nur mit einer Präzisierung der Regel: „ohne Default" muss *pro Datei* gelten, nicht pro Vorkommen.
  `monitoring/config.py` liest `SMTP_PORT` und `ALERT_LOG_RETENTION_DAYS` je einmal mit und einmal ohne Default (die zweite Stelle ist
  ein Log-Aufruf). Pro Vorkommen gewertet wären beide Falschmeldungen. `ALLOW_INSECURE_HUB` hat wirklich nie einen Default — und ist im
  Compose gesetzt. Das ist keine Ausnahmeliste, sondern die korrekte Lesart.
- **(b) 3 Funde:** `DOMAIN` und `EXTRA_SANS` gehen an den Dienst `server`, werden aber von `apps/server/**` und vom Entrypoint nirgends
  gelesen (sie gehören zu ca-issuer/gateway) · `PGPASSWORD` geht an `server` und `scheduler`, deren Entrypoint nur `pg_isready -h -p -U`
  ohne Passwort ruft (bei `monitoring` liest der Entrypoint es wirklich).
- **(c) 3 Funde:** `CA_FRPS_EXTRA_SANS` wird im Compose substituiert, steht aber in keiner Zeile von `.env.example` ·
  `DB_POOL_SIZE` und `DB_MAX_OVERFLOW` sind in `.env.example` dokumentiert, werden aber von keinem Compose-Dienst durchgereicht —
  wer sie in `.env` setzt, ändert nichts. Das ist ein echter Bug, kein Testartefakt.

**Kevin entscheidet (5 Stellen):** tote Compose-Keys entfernen oder belassen (DOMAIN/EXTRA_SANS/PGPASSWORD) · `CA_FRPS_EXTRA_SANS`
in `.env.example` dokumentieren · `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` im Compose verdrahten **oder** aus `.env.example` streichen.
Danach ist der Test in einer Folge-Task in ~20 min gebaut; die Regeln oben sind vollständig.
Ergebnis: **Aufgelöst — alle sechs Funde behoben, Test committet, drei Mengen leer.** Freigabe: Kevin, 2026-09-15 („nochmal anschauen, verifizieren, überlegen wie du es löst und dann auch machen") — die fünf hier geparkten Stellen waren ausdrücklich seine Entscheidung, und dieser Auftrag ist sie. Jeder Fund vorher unabhängig nachgeprüft, nicht aus dem Erstlauf übernommen. **(c) zwei echte Bugs:** `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` stehen in `.env.example` mitsamt Rechenregel (`Gesamt = WEB_CONCURRENCY×(Pool+Overflow)`), werden von `config.py` gelesen und in `database.py` an den SQLAlchemy-Pool gegeben — aber Compose reichte sie nie durch. Der dokumentierte Rat war nicht befolgbar; jetzt gehen sie an `server` und `scheduler`. `CA_FRPS_EXTRA_SANS` wird vom ca-issuer gelesen und von Compose gesetzt, stand aber in keiner Zeile von `.env.example` — jetzt dokumentiert. **(b) drei tote Keys entfernt:** `DOMAIN` und `EXTRA_SANS` beim Dienst `server` (Grep über den ganzen Baum inkl. Dockerfile und Entrypoint: kein einziger Treffer — sie gehören ca-issuer und Gateway) sowie `PGPASSWORD` bei `server` und `scheduler` (deren Entrypoints rufen nur `pg_isready`, das sich nicht authentifiziert; nur `apps/monitoring/docker-entrypoint.sh` ruft wirklich `psql`). **(a) leer** — mit der Präzisierung, die beim Erstlauf aufgefallen war: „ohne Default" ist eine Eigenschaft der **Datei**, nicht des Vorkommens. `monitoring/config.py` liest `SMTP_PORT` einmal mit Default und nennt es einmal ohne, in einer Warnmeldung. Pro Vorkommen gewertet wären das Falschmeldungen; das ist keine Ausnahmeliste, sondern die korrekte Lesart. Gleiches gilt für `ALERT_LOG_RETENTION_DAYS`. Mutations-Proben, alle rot: neue Variable ohne Default, die Compose nicht setzt · toter Compose-Key wieder eingesetzt · Pool-Durchreichung bei **beiden** Diensten entfernt (der Ausgangs-Bug) · `CA_FRPS_EXTRA_SANS` wieder undokumentiert. Nicht-Leer-Boden: ≥ 10 je Seite wie verlangt, je Dienst nur ≥ 5 — der ca-issuer hat ehrlich neun Keys, und ein ehrlich kleiner Block ist kein kaputter Parse. 4 passed.

### T7 — OpenAPI-Snapshot Server  [x]
Komponente: apps/server · Dateien: apps/server/tests/test_openapi_snapshot.py (neu, SPDX), apps/server/tests/openapi.snapshot.json (neu), apps/server/tests/conftest.py
Änderung: `app.openapi()` (aus `app.main`) als JSON mit sortierten Schlüsseln und `indent=2` gegen die Datei; vorher normalisieren: `info.version` auf `"0.0.0"` setzen (die reale Version kommt aus Tag/Build-Arg und würde bei jedem Release Snapshot-Churn erzeugen) und ein etwaiges `servers`-Feld entfernen; Mismatch ⇒ Assertion mit kompaktem `difflib`-Unified-Diff (max. 40 Zeilen) und Hinweis `pytest --update-openapi-snapshot`; die Option in `conftest.py` (`pytest_addoption`) schreibt die Datei neu. Nicht-Leer: ≥ 20 Pfade im Snapshot. Kein DB-Zugriff nötig (App-Import reicht; der Test hängt nicht an `pg_engine`).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_openapi_snapshot.py
Doku: DEVELOPMENT.md Absatz „OpenAPI-Snapshot aktualisieren" (nur einmal, in T7) · CHANGELOG Unreleased/Added
Ergebnis: Snapshot mit **54 Pfaden**; `info.version` auf 0.0.0 normalisiert, `servers` entfernt; die Option `--update-openapi-snapshot` steht am Ende von `conftest.py`, weil der Import-Block dort bewusst unter dem Env-Setup liegt und eine Funktion davor E402 auslösen würde. **Produktcode-Änderung, ohne die der Task nicht erfüllbar war:** der erste volle Lauf war rot, weil der Snapshot **nicht reproduzierbar** war. Ursache über vier `PYTHONHASHSEED`-Werte gemessen: `@router.api_route(/{path:path}, methods=[4])` im Monitoring-Proxy war die einzige Mehr-Methoden-Route im Repo; FastAPI leitet die `operationId` aus `list(route.methods)[0]` ab, also aus einer Set-Iteration. Alle vier Operationen bekamen **dieselbe** ID (laut OpenAPI unzulässig), und welche, entschied das pro Prozess zufällige String-Hashing. Behoben durch vier gestapelte Ein-Methoden-Decorator: vier eindeutige, stabile IDs. **Korrektur aus dem Review:** „405-Verhalten unverändert" stimmte nicht — der Statuscode ja, aber Starlette baut den `Allow`-Header aus der ersten teilweise passenden Route, er nennt jetzt eine Methode statt vier. Kein Client im Repo liest ihn (apps/web, apps/desktop/ui, apps/agent geprüft). Neu dazu: `test_every_operation_has_a_unique_id` — sonst käme die nächste Mehr-Methoden-Route als flaky operationId-Diff zurück statt als benannter Fehlschlag. Gegenprobe: Spec-Hash über drei Seeds identisch (vorher zwei verschiedene). Wegnormalisieren hätte einen echten API-Bug zugedeckt. 2 passed.

### T8 — OpenAPI-Snapshot Monitoring  [x]
Komponente: apps/monitoring · Dateien: apps/monitoring/tests/test_openapi_snapshot.py (neu, SPDX), apps/monitoring/tests/openapi.snapshot.json (neu), apps/monitoring/tests/conftest.py
Änderung: wie T7 für `apps/monitoring/app/main.py`; dieselbe Option `--update-openapi-snapshot`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_openapi_snapshot.py
Doku: keine (Absatz aus T7 gilt für beide)
Abhängt von: T7
Ergebnis: Snapshot mit **26 Pfaden**, dieselbe Option in `apps/monitoring/tests/conftest.py`. Determinismus über zwei `PYTHONHASHSEED`-Werte geprüft — das Monitoring hat keine Mehr-Methoden-Route, also kein T7-Problem. 2 passed.

### T9 — oasdiff-Gate: Skript + hermetischer Test  [x]
Komponente: scripts · Dateien: scripts/dev/openapi-breaking.sh (neu, SPDX), scripts/tests/openapi_breaking_test.sh (neu, SPDX), scripts/tests/run.sh (nur `AH_SCRIPT_TESTS_DEFAULT`)
Änderung: `bash scripts/dev/openapi-breaking.sh <server|monitoring> [--base <ref>]` — Basis-Snapshot per `git show <ref>:apps/<k>/tests/openapi.snapshot.json` (Default `origin/main`, fehlt der Snapshot dort ⇒ „kein Vergleich, neu" Exit 0 mit Meldung), Revision = Arbeitsbaum; `oasdiff breaking <base> <rev> --fail-on ERR --format text`; `oasdiff` fehlt ⇒ Exit 75 (SKIP, unter `--strict` rot). Hermetischer Test mit Fake-`oasdiff` im PATH (Argument-Mitschnitt; Exit 1 ⇒ Skript 1; Exit 0 ⇒ 0; kein Binary ⇒ 75; fehlender Basis-Snapshot ⇒ 0), eingetragen in `AH_SCRIPT_TESTS_DEFAULT`. shellcheck sauber.
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: keine (T10 dokumentiert das Gate)
Abhängt von: T7
Ergebnis: `scripts/dev/openapi-breaking.sh <server|monitoring> [--base <ref>] [--root <dir>]`; `--root` gibt es, damit der hermetische Test gegen ein Fixture-Repo laufen kann. **Über die Vorgabe hinaus, weil es ein Fail-open war:** eine Basis-Ref, die im Checkout nicht auflöst (flacher CI-Klon!), hätte als „kein Vergleich, neu" ⇒ Exit 0 gegolten — das Gate wäre auf jedem PR still grün gewesen. Jetzt prüft das Skript zuerst `git rev-parse --verify` und meldet Exit 2. 11 Fälle im hermetischen Test (fake `oasdiff` mit Argument-Mitschnitt: Exit 1 ⇒ 1, Exit 0 ⇒ 0, kein Binary ⇒ 75, fehlender Basis-Snapshot ⇒ 0, nicht auflösende Ref ⇒ 2, Usage ⇒ 2), eingetragen in `AH_SCRIPT_TESTS_DEFAULT`. Zusätzlich real gegengeprüft: echtes oasdiff 1.32.0 gegen den Server-Snapshot mit einem entfernten Pfad ⇒ `api-path-removed-without-deprecation`, Exit 1. shellcheck sauber. 11 passed, 0 failed.

### T10 — CI-Job openapi-compat  [x]
Komponente: .github · Dateien: .github/workflows/ci.yml, docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: Job `openapi-compat` (ubuntu-latest, `fetch-depth: 0`): Tarball `oasdiff_1.32.0_linux_amd64.tar.gz` vom Release `v1.32.0` laden, SHA-256 aus `checksums.txt` als Literal im Workflow pinnen und prüfen, Binary nach `$RUNNER_TEMP/bin`; dann `bash scripts/dev/openapi-breaking.sh server` und `… monitoring` mit `--base origin/${{ github.base_ref || 'main' }}`. Kommentar im Workflow: warum Tarball statt `go install` (go-Direktive 1.26 vs. Toolchain 1.25, PR #14). Doku-Abschnitt „Paritäts- und Contract-Gates" in cicd.html DE + EN anlegen (Tabelle: Gate · Wahrheit A · Wahrheit B · wo es läuft) — die späteren Tasks tragen dort nur Zeilen nach.
Verify: bash scripts/tests/run.sh lint --strict --only scripts   (shellcheck über die Workflow-Bash-Steps entfällt; die Gate-Logik steckt in T9) — plus nach dem Push: der Job ist im PR-CI grün
Doku: docs/developer/cicd.html DE+EN (neuer Abschnitt) · CHANGELOG Unreleased/Added
Ergebnis: Job `openapi-compat` (ubuntu-latest, `fetch-depth: 0`), Tarball `oasdiff_1.32.0_linux_amd64.tar.gz`, SHA-256 `5b2050787cfee2a9a3ba7b25cb50fe2c5cc45cdf5b96fbc51a4a60107f8b4aad` als Literal im Workflow — aus `checksums.txt` des Release geholt und lokal gegen den echten Tarball mit `sha256sum -c` verifiziert. Kommentar im Workflow erklärt Tarball statt `go install` (go-Direktive 1.26 vs. Toolchain 1.25, PR #14). Abschnitt „Paritäts- und Contract-Gates" in cicd.html DE + EN angelegt (Tabelle Gate · Wahrheit A · Wahrheit B · wo es läuft). **Offen bis zum Push:** dass der Job im echten PR-CI grün ist, kann ich lokal nicht beweisen — das ist die letzte unverifizierte Zusage dieser Task.
Abhängt von: T9

## B — Desktop- und Web-Contracts

### T11 — Tauri-IPC-Inventar  [x]
Komponente: apps/desktop-ui · Dateien: apps/desktop/ui/src/lib/bridge/ipc.inventory.test.ts (neu, SPDX)
Änderung: Vitest liest per `node:fs` (Pfad relativ zu `import.meta.url`) `../src-tauri/src/commands.rs` (Namen nach jedem `#[tauri::command]`), `../src-tauri/src/main.rs` (Einträge in `generate_handler![…]`) und `src/lib/bridge/index.ts` (`invoke<…>('name'`): assertet definiert == registriert, aufgerufen ⊆ registriert, registriert − aufgerufen == Allowlist `{ enroll_device: 'kein UI-Aufrufer; Roadmap-Zeile REF' }`. Nicht-Leer: ≥ 30 Commands, ≥ 30 Aufrufe.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (intern)
Ergebnis: 33 Kommandos definiert, 33 registriert, 32 aufgerufen; einzige Differenz ist `enroll_device` (Allowlist mit Begruendung, Roadmap-Zeile REF). Vier Faelle: Nicht-Leer (je >= 30), definiert == registriert, aufgerufen ist Teilmenge von registriert, registriert minus aufgerufen == Allowlist. Desktop-UI-Suite: 58 Dateien, 369 Tests passed.

### T12 — Serde-Structs ↔ bridge/types.ts  [x]
Komponente: apps/desktop-ui · Dateien: apps/desktop/ui/src/lib/bridge/types.parity.test.ts (neu, SPDX), apps/desktop/ui/src/lib/bridge/types.ts
Änderung: Test parst die `#[derive(… Serialize|Deserialize …)]`-Structs aus `models.rs`, `tunnel.rs` und `ansible.rs` (Felder, `rename_all`, `#[serde(rename = "…")]`, `Option<…>` ⇒ optional) und vergleicht **Feldnamen** je Struct mit dem gleichnamigen `interface` in `types.ts` (Optionalität/Nullbarkeit wird nicht verglichen — serde und TS modellieren `Option<T>` unterschiedlich, das wäre ein Rauschgenerator); Enums (`ConnectionKind`, `SyncMode`, `Rdp*`) als Union-Literale. `RdpErrorPayload` steht auf einer Allowlist „Event, kein Command" mit Begründung. Den heutigen Drift beheben: `tunnelType: string` in `ResolvedConnection` (`types.ts:97-101`). Nicht-Leer: ≥ 10 Struct-Paare.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (intern)
Ergebnis: 15 Serde-Typen aus models.rs/tunnel.rs/ansible.rs geparst (9 Structs + 5 Enums verglichen, `RdpErrorPayload` auf der Allowlist -- Event, kein Command-Ergebnis). `rename_all` und feldweises `serde(rename)` werden angewendet (Settings.sync_url -> url). Optionalitaet wird bewusst NICHT verglichen. Drift behoben: `tunnelType?: string | null` in `ResolvedConnection`. Mutationsprobe: die Zeile wieder entfernt -> Test rot mit `rustOnly: [tunnelType]`, danach byte-genau zurueckgeschrieben (Backup-Kopie, kein git checkout). 4 passed.

### T13 — Playwright-Mock-Contract gegen den Server-Snapshot  [x]
Komponente: apps/web · Dateien: apps/web/tests/e2e/mocks.ts, apps/web/src/lib/api/mocks.contract.test.ts (neu, SPDX)
Änderung: `mocks.ts` exportiert zusätzlich eine Tabelle `MOCK_FIXTURES: Array<{ method, path, status, body }>` (die heutigen Inline-Bodies, keine Verhaltensänderung für `mockApi`; `Page`/`Route` bleiben `import type`, damit der Vitest kein Playwright lädt). Der Vitest lädt `apps/server/tests/openapi.snapshot.json`, findet je Fixture die Operation (Pfad-Template-Matching auf `/api/<path>`), löst `$ref` nach `components.schemas` auf und prüft Schlüsselmengen laut Spec Trade-off 3 (Arrays: Item-Schema gegen erstes Element). Nicht-Leer: ≥ 8 Fixtures zugeordnet; unzuordenbare Fixture = rot.
Verify: bash scripts/dev/verify.sh web --strict
Doku: keine (intern)
Abhängt von: T7
Ergebnis: `MOCK_FIXTURES` (15 Einträge) exportiert; damit Tabelle und `mockApi` nicht auseinanderlaufen, sind die Bodies jetzt gemeinsame Bauer-Funktionen (`makeUser`, `makeApiKey`, `makeHook`, `frpPub`, …), die beide Seiten aufrufen — keine zweite Abschrift. **Drei echte Drifts gefunden und behoben:** `/api/auth/me` lieferte die volle User-Zeile, das Schema ist `UserMe` (id, username, is_admin) · die Hook-Liste und `/toggle` lieferten `script`, das erst `HookDetailResponse` hat (die UI holt es über `GET /api/hooks/{id}`). Geprüft werden Schlüsselmengen laut Spec Trade-off 3, `$ref` wird aufgelöst, Arrays gegen das erste Element. Nebenbefund, nicht behoben (fremde Datei, außerhalb der Fixture-Tabelle): `apps/web/tests/e2e/authz.spec.ts:20` überschreibt `auth/me` mit einem eigenen Body, der ebenfalls `created_at`/`server_ids` enthält. Web-Suite 17 Dateien, 77 Tests passed.

### T14 — sync-from-web.sh --check  [x]
Komponente: apps/desktop-ui · Dateien: apps/desktop/ui/scripts/sync-from-web.sh, .github/workflows/ci.yml, DEVELOPMENT.md
Änderung: Modus `--check` (Spec Trade-off 5): für jedes `export (interface|type|const) Name` des Web-`types.ts` den Block (bis zur nächsten Top-Level-Zeile) extrahieren und byte-identisch im Desktop-`types.ts` erwarten; Abweichungen als Diff je Symbol, Exit 1; der bestehende Guard bleibt. CI-Step im Job `desktop-ui`. Zeigt der Erstlauf Drift in ≤ 3 Typen ⇒ in dieser Task nachziehen (Desktop = Ziel), sonst `[?]` mit der Liste. DEVELOPMENT.md-Absatz zum Skript um `--check` ergänzen.
Verify: bash apps/desktop/ui/scripts/sync-from-web.sh --check
Doku: DEVELOPMENT.md · docs/developer/cicd.html DE+EN Tabellenzeile
Ergebnis: **Aufgelöst — `--check` prüft jetzt die richtige Invariante, ist grün und im CI.** Die Nachprüfung hat die Prämisse widerlegt, nicht den Befund: die beiden Dateien sind **keine gemeinsame Datei mehr**. Das Web-`types.ts` (208 Zeilen, 25 Exporte) beschreibt die Admin-Panel-API (User, ApiKey, Hook, Audit), das Desktop-`types.ts` (573 Zeilen, 58 Exporte) die Client-API (Connection, Monitoring, Notifications, Playbooks). Die Schnittmenge sind **vier** Symbole: `FrpConfig`, `FrpStatus`, `FrpStatusProxy`, `Server`. Nur die sind doppelt gepflegt, nur die können driften — die 21 „fehlenden" Typen sind der Normalfall zweier getrennter Flächen, kein Drift. **Und `Server` ist ebenfalls kein Drift:** gegen den echten Vertrag geprüft — `to_dict()` in `apps/server/app/modules/servers/models.py:41-54` liefert `connections` mit, `GET /api/servers` gibt das unverändert weiter. Die Desktop-Seite hat also recht, die Web-Seite ist eine bewusst schmalere Projektion derselben Antwort. Damit wäre „byte-identisch" die falsche Regel gewesen. **Neue Regel: Teilmenge über der Schnittmenge.** Jede Zeile des Web-Blocks muss im Desktop-Block stehen; das Desktop darf mehr führen. Das fängt den realen Fall (das Web zieht ein neues Server-Feld nach, das Desktop nicht) und lässt die legitime Projektion zu. Boden von drei gemeinsamen Symbolen, damit ein Umbenennen aller Symbole den Guard nicht still leerlaufen lässt. Quell-Exporte ohne Gegenstück werden berichtet, nicht bemängelt. Mutations-Proben: Web bekommt ein Feld, das Desktop nicht hat ⇒ rot · Feld im Web umbenannt ⇒ rot · Desktop-only-Zusatzfeld ⇒ grün (richtig) · gemeinsame Symbole im Desktop umbenannt ⇒ rot (Boden greift). CI-Step im Job `desktop-ui` (direkt hinter dem Checkout — reines bash/awk, braucht kein `npm ci`), Tabellenzeile in cicd.html DE + EN, Abschnitt in DEVELOPMENT.md. **Aus dem Review nachgebessert:** (1) Der Zähl-Boden von drei greift erst, wenn **zwei** der vier Symbole verschwinden — der realistische Fall ist der einzelne Refactor. Die erwartete Menge steht jetzt namentlich als `CHECK_SHARED`; verschwindet eines von einer Seite, ist das ein Fehler. (2) `symbol_block` las bei `export type X = { … };` nur bis zur ersten Feldzeile — und zwar auf beiden Seiten gleich, also **falsch-grün**. Die Endbedingung entscheidet sich jetzt an der Öffnung (`= {` ⇒ Klammer-Regel). (3) Die Verwendungszeile im Kopf sagte noch „byte-identisch". (4) Neu benannt, in Skript, DEVELOPMENT.md und cicd.html DE+EN: **die Löschrichtung ist ungedeckt** — entfernt das Web ein Feld, bleibt die Teilmenge erfüllt und das Desktop behält die Leiche. Das ist die einzige der sechs Drift-Formen, die die Regel nicht fängt. (5) Der Guard hatte keinen eigenen Test, obwohl CLAUDE.md §6 einen verlangt: `scripts/tests/sync_check_test.sh` mit 7 Fällen, registriert in `AH_SCRIPT_TESTS_DEFAULT`. Beide Lücken sind darin gedeckt — nimmt man Fix (1) oder (2) zurück, wird der Test rot. **Korrektur an der Spec:** Problem-Punkt 5 nennt „30 Desktop-only-Exporte", real sind es 54, schon auf `main`. **Nebenbefund für die Roadmap:** `--apply` ist für diese Datei tot — der bestehende Überschreib-Schutz bricht ab, weil das Ziel 54 Exporte hat, die die Quelle nicht kennt, und würde sonst 573 Zeilen durch 208 ersetzen. Entweder das Kopier-Verfahren für `types.ts` streichen und nur `--check` behalten, oder die vier wirklich geteilten Typen in eine dritte Datei ziehen.

### T15 — Svelte-Mount-Smoke Web  [x]
Komponente: apps/web · Dateien: apps/web/src/mount.smoke.test.ts (neu, SPDX)
Änderung: Allowlist von 10 Komponenten ohne Pflicht-Props (Kandidaten: die 5 unter `lib/components/ui`, 2 `layout`, 3 `pages`/`modals`), je `render()` unter jsdom mit `console.error`-Spy; jeder Aufruf von `console.error`/unbehandelte Exception ist rot, `effect_update_depth_exceeded` mit eigener Meldung. Nicht-Leer: 10 Einträge, jede Datei existiert.
Verify: bash scripts/dev/verify.sh web --strict
Doku: keine (intern)
Ergebnis: 10 Komponenten (4 `ui`, 2 `layout`, 3 `modals`, 1 `pages`). **Prämisse aus dem Review korrigiert:** ich hatte geschrieben, Svelte melde `effect_update_depth_exceeded` über `console.error` statt zu werfen — der Reviewer hat mit einer Wegwerf-Komponente das Gegenteil gemessen: Svelte **wirft** aus `render()`, nach rund 20 s. Die eigens gebaute Sonder-Assertion war damit toter Code; sie ist raus, `expect(mount).not.toThrow()` ist der Guard, der `console.error`-Spy das zweite Netz. Dazu `MOUNT_TIMEOUT_MS = 30_000`, sonst käme ein echter Loop als nackter 5-s-Timeout statt als benannter Fehler. **Abweichung von der Vorgabe „ohne Pflicht-Props“:** `Button`, `EmptyState` und `Modal` haben welche und werden mit dem Minimum gemountet. Die sieben Seiten fehlen bewusst — jede lädt beim Mount über ihren Store und bräuchte einen eigenen API-Stub; `pages/Placeholder` ist die einzige ohne Store-Last und deshalb dabei. `ui/ConfirmDialog` ist raus: es hat bereits einen eigenen Mount-Test und rendert im Ruhezustand nichts. Jeder Eintrag ist ein mount-Thunk, weil ein gemeinsamer Tabellentyp für zehn Prop-Typen `any` sein müsste. Nebenbefund: `resolveRoute` setzt einen `*`-Eintrag voraus und wirft ohne ihn. 11 passed.

### T16 — Svelte-Mount-Smoke Desktop-UI  [x]
Komponente: apps/desktop-ui · Dateien: apps/desktop/ui/src/mount.smoke.test.ts (neu, SPDX)
Änderung: wie T15 mit 10 Komponenten aus `src/components/**`, die heute keinen Mount-Test haben; Bridge-Aufrufe per `vi.mock('$lib/bridge')` (bzw. dem Import-Pfad der Komponenten) stubben, wie es die bestehenden 19 Mount-Tests tun.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (intern)
Ergebnis: 10 Komponenten aus `src/components/**` ohne eigenen Mount-Test (StatusBar, TunnelIndicator, NotificationBell, PasswordPrompt, SettingsModal und fünf aus `monitoring/`), alle prop-frei und store-getrieben. **Zwei Review-Funde behoben:** (1) Vier der zehn hingen hinter einem Store-`{#if}` und mounteten zu einem leeren Kommentarknoten — genau der Blank-Window-Fall, den die Datei zu decken behauptet, war für sie nicht gedeckt. Jetzt wird der treibende Store vorher gesetzt (`showStatus`, `settingsModalOpen`, `requestPassword`, server-mode `sessionStore`); gemessen rendern sie 3 / 3 / 21 / 93 Elemente statt 0. (2) Der Satz, die Bridge sei gestubbt, stimmte nicht — gestubbt war `$lib/stores/statusBar`, dessen `reportError` gar nicht auf die Konsole schreibt. Jetzt gibt es einen echten `vi.mock('$lib/bridge')`, der bei jedem Zugriff wirft (Modul-Loader-Proben `then`/`__esModule`/`default` ausgenommen), damit ein künftiger Mount-Aufruf laut scheitert statt still. Dieselbe `effect_update_depth_exceeded`-Korrektur und derselbe `MOUNT_TIMEOUT_MS` wie in T15. 11 passed.

## C — Doku-Gate

### T17 — doc-smoke.py + hermetischer Test  [x]
Komponente: scripts · Dateien: scripts/dev/doc-smoke.py (neu, SPDX), scripts/tests/doc_smoke_test.sh (neu, SPDX), scripts/tests/run.sh (nur `AH_SCRIPT_TESTS_DEFAULT`)
Änderung: Python-Stdlib-Skript: sammelt aus `docs/**/*.html` jedes `<code>…</code>`, das mit `apps/`, `scripts/`, `docs/`, `.github/` oder `.claude/` beginnt (Pfad bis zum ersten Leerzeichen/`[`), und prüft die Existenz im Repo (Verzeichnisse mit `/` am Ende erlaubt); zweite Prüfung: `<code>`-Inhalte der Form `[A-Z][A-Z0-9_]{3,}` gegen die Env-Namen aus `apps/{server,monitoring}/app/core/config.py`, `apps/ca-issuer/app/config.py` und `.env.example` (nur Treffer, die in keiner Quelle vorkommen, gelten als Drift). Ausnahmedatei `scripts/dev/doc-smoke-allow.txt` (eine Zeile je Eintrag mit Begründung nach `#`), das Skript verweigert > 5 Einträge. Flags: `--paths` (Default), `--env`, `--strict`; Ausgabe je Fund `datei:zeile: <eintrag>`. Hermetischer Test mit Fixture-Docs (guter Pfad, kaputter Pfad, Env-Name; Allow-Datei mit 6 Zeilen ⇒ Exit 2). Erstlauf auf `main`: Pfade ⇒ Funde in dieser Task beheben (Doku korrigieren) oder ≤ 5 begründet ausnehmen; Env-Namen ⇒ liefert der Erstlauf > 5, bleibt `--env` bis zur Triage außerhalb des Gates (Task-Vermerk mit Zahl). Nicht-Leer: ≥ 30 Pfade gesammelt.
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: keine (T18)
Ergebnis: `scripts/dev/doc-smoke.py` (nur stdlib) mit `--paths` (Default), `--env`, `--strict`, `--root`; Ausgabe je Fund `datei:zeile: <eintrag>`. Nicht-Leer: < 30 gesammelte Pfade sind Exit 2 („der Scan ist kaputt"), nicht etwa eine saubere Doku. Hermetischer Test mit 11 Fällen über Fixture-Checkouts (inkl. 32 echter Pfade, damit die Untergrenze überhaupt erreicht wird), eingetragen in `AH_SCRIPT_TESTS_DEFAULT`. **Erstlauf Pfade: 4 Funde (2 Pfade × DE/EN), beide in der Doku behoben** — `monitoring_proxy.py` heißt seit dem Paket-Umbau `monitoring_proxy/router.py`; `apps/desktop/src-tauri/src/rdp/race_guard.rs` hat es laut `git log -S` **nie** gegeben, also habe ich nur den Dateiverweis entfernt und die Verhaltensbeschreibung stehen lassen — ob der beschriebene RDP-Race-Guard überhaupt existiert, konnte ich im Code nicht belegen (Roadmap-Kandidat für Kevin). Die Ausnahmedatei ist angelegt und leer. **Erstlauf Env: 129 Treffer, 43 verschiedene Namen** — fast alle keine Env-Variablen (POST, DELETE, INFO, WARNING, RUNNING, SHA256SUMS, ERR_TLS_UNKNOWN_ISSUER, AH_*). Weit über dem Deckel 5, also bleibt `--env` laut Ledger-Regel außerhalb des Gates. 11 passed, 0 failed.

### T18 — doc-smoke als Gate im Job ops-scripts  [x]
Komponente: .github · Dateien: .github/workflows/ci.yml, docs/developer/cicd.html, docs/en/developer/cicd.html, DEVELOPMENT.md
Änderung: Step `python3 scripts/dev/doc-smoke.py --strict` (mit `--env` nur, wenn T17 die Env-Prüfung scharf gestellt hat) im Job `ops-scripts`; Tabellenzeile im Gate-Abschnitt DE + EN; DEVELOPMENT.md ein Absatz (Aufruf, Ausnahmedatei, Deckel 5).
Verify: bash scripts/tests/run.sh unit --strict --only scripts   — plus nach dem Push: Job grün
Doku: docs/developer/cicd.html DE+EN · DEVELOPMENT.md · CHANGELOG Unreleased/Added
Ergebnis: Step `python3 scripts/dev/doc-smoke.py --strict` im Job `ops-scripts` — **ohne** `--env`, mit dem Grund als Kommentar im Workflow. Tabellenzeile „Doku-Pfade" im Gate-Abschnitt DE + EN, dazu ein Absatz zu Ausnahmedatei und Deckel; DEVELOPMENT.md-Abschnitt „Doku-Smoke (doc-smoke.py)". **Offen bis zum Push:** dass der Step im echten PR-CI grün ist, kann ich lokal nicht beweisen.
Abhängt von: T17

## Abschluss
- Gesamt: `bash scripts/tests/run.sh quick --strict` grün; `bash scripts/dev/verify.sh all --strict` grün.
- Mutations-Proben aus der Spec („Verify-Prinzip") in einem Wegwerf-Worktree: je Guard eine Mutation ⇒ rot; Ergebnisliste in den PR-Body.
- Roadmap-Zeilen (Kevin, privat): `enroll_device` (REF), Funde aus T6/T14/T17, falls `[?]`.

### Ergebnis des Abschlusses
- `bash scripts/dev/verify.sh all --strict`: **13 passed, 0 failed, 0 skipped, 5 test-skips, 0 reruns** (die fünf
  test-skips sind Vorbedingungen dieser Box: Redis auf :6380 nicht erreichbar, Migrations-Smoke ohne `DATABASE_URL`).
  `bash scripts/tests/run.sh quick --strict` direkt aufgerufen meldet `go agent` als strict-failed, weil `run.sh`
  ohne Wrapper `.devenv.sh` nicht sourct und `go` dann unsichtbar ist — das ist die Umgebung, nicht der Code;
  über `verify.sh` läuft der Schritt grün.
- **Schwere Suite übersprungen, am realen Diff geprüft:** `git diff --name-only main...HEAD` berührt keinen
  Cross-Host-Pfad (kein `apps/gateway`, `apps/ca-issuer`, `apps/agent`, `docker-compose*`, `Dockerfile`,
  `scripts/install|update`, kein FRP/PKI). Das deckt sich mit dem Ledger-Kopf. **Eine Einschränkung, die der Kopf
  nicht kennen konnte:** T7 hat `apps/server/app/modules/monitoring_proxy/router.py` angefasst (eine `api_route`
  mit vier Methoden wurde zu vier Ein-Methoden-Routen). Das ist Produktivcode auf einem Server-API-Pfad. Abgedeckt
  ist es durch die volle Server-Suite (510 passed) und `test_monitoring_ingest_ratelimit.py`; der Integrationsstack
  würde denselben Pfad über das Gateway fahren. **Kevin entscheidet, ob das vor dem Merge einen Single-Box-Lauf
  wert ist.**
- **Mutations-Proben** — je Guard mindestens eine Einzelmutation, alle rot (Wegwerf-Worktree bzw. Backup-Kopie):
  T1 `log` zurück in die Allowlist · `alerts` entfernt · Monitoring-Route umbenannt · leeres `routers/` ·
  `agent-keys` umbenannt. T2 Header in `identity-headers.conf` umbenannt · `HEADER_CERT` im Issuer · `_H_CERT` im
  Server · dritter `$ssl_client_*`-Header · Strips von :8444 nach :443 · nur die Server-Level-Strips gelöscht ·
  `listen 8444` entfernt. T3 Issuer-`_hash` auf sha512 · Server-`hash_api_key` auf sha512 · `hashed_token=raw` ·
  Issuer sucht ohne `_hash` · Decorator über `_hash` · Docstring (muss grün bleiben, ist es). T4 Pipeline-Token
  nach `agent.py` kopiert · Log-String kopiert · zweiter `_dispatch_alert_bg` · `apply_result` umbenannt ·
  `keep_previous_details_when_absent` am Call-Site entfernt · Default gedreht · Flag ignoriert · Zuweisung immer
  bedingt · aliasierter Import ein- und mehrzeilig. T5 Logikzeile in der Server-`ssrf.py` · dieselbe im Monitoring ·
  Kommentar/Format/Docstring (grün) · beide Guards auf Stub. T7 `api_route` wiederhergestellt ⇒ vier Schema-Hashes
  über sieben Seeds. T9 `oasdiff` gegen sich selbst aufgerufen ⇒ Test rot. T12 `tunnelType` wieder entfernt ·
  `Settings.url` umbenannt. T13 Feld im Fixture umbenannt · Pflichtfeld entfernt. T17 gitignorierte Build-Ausgabe ·
  `<code class>` · mehrzeiliger Block · sechster Allowlist-Eintrag.
- **Zwei offene `[?]` für Kevin:** T6 (Env-Parität, 6 Funde) und T14 (`sync-from-web.sh --check`, 22 Funde).
  Deshalb steht der Kopf auf `blockiert`, nicht auf `erledigt`.
- **Roadmap-Kandidaten (privat, Klasse REF):** `enroll_device` ohne UI-Aufrufer · sechs Server-Routen ohne
  `response_model` (`GET/POST /api/users`, `GET/POST/PUT /api/frp/server-config`, `GET /api/frp/status`), die
  darum nicht pinbar sind · `--env` von doc-smoke (43 Namen triagieren) · `authz.spec.ts:20` beschreibt
  `auth/me` ein zweites Mal, ungepinnt.

### Gesamt-Review über den Branch-Diff (`/code-review main...HEAD high`)
13 Befunde, 12 davon behoben; jeder Fix ist unten in der Reihenfolge des Reviews vermerkt.

- **Nicht behoben, Roadmap-Zeile (Klasse SEC/REF) für Kevin:** der geteilte `ThreadPoolExecutor` im SSRF-Guard
  (4 Worker, `apps/{server,monitoring}/app/core/ssrf.py`) macht aus einem hängenden Resolver eine dienstweite
  Sperre: vier gleichzeitige Auflösungen gegen einen blackholed Nameserver belegen alle Worker für den OS-Default,
  jede weitere `is_private_url` läuft in ihren 5-s-Timeout und meldet fail-closed „privat" — also wird **jeder**
  ausgehende Hook-Aufruf abgewiesen, solange das anhält. Die abgelaufenen Futures werden nicht gecancelt, die
  Worker bleiben also auch nach dem Angriff belegt; und die Nicht-Daemon-Threads werden beim Interpreter-Exit
  gejoint, ein SIGTERM hängt entsprechend. **Warum ich das hier nicht anfasse:** der Mechanismus stammt aus dem
  Monitoring (4.111) und ist seit T5 in beiden Diensten identisch — genau das ist der Auftrag dieser Task. Ein
  Umbau müsste beide Dienste betreffen (Semaphore pro Host, gecancelte Futures, Daemon-Threads) und ist eine
  eigene Sicherheits-Task, kein Drive-by in einem Paritäts-Ledger.
- **Behoben:** eine Session-Bezugsstelle im `check_engine` (`database.SessionLocal` überall, die vier Patch-Stellen
  in den Engine-Tests nachgezogen) · der Corrupt-Config-Test stubbt jetzt `_alert_pool` wie seine Nachbarn, statt
  echte Arbeit einzureihen und die Teardown-Race zu gewinnen · der Monitoring-Snapshot-Test hat die
  operationId-Eindeutigkeit und den `exists()`-Riegel seines Server-Zwillings bekommen · `authz.spec.ts` baut den
  `auth/me`-Body aus demselben Helfer wie die Fixture-Tabelle, statt ihn ein zweites Mal zu beschreiben ·
  `types.parity.test.ts` verlangt für jeden serde-Typ ausserhalb der drei gescannten Dateien eine Begründung
  (drei aus `enrollment.rs`, alle nachweislich nicht bridge-kreuzend) · der Proxy-Allowlist-Test assertiert, dass
  er jeden Routen-Decorator lesen kann · `symbol_block` in `sync-from-web.sh` trennt jetzt nach Deklarationsart
  (interface an `^}`, type/const am ersten `;`) — meine erste Fassung des Fixes war selbst falsch und liess den
  `Server`-Drift verschwinden · `--check` meldet eine fehlende Zieldatei einmal statt 25-mal · `shapeOf` im
  Mock-Contract behält die eigenen `properties` neben `anyOf`/`allOf` und der Prüf-Boden ist auf die reale Zahl 8
  gepinnt statt auf ein Minimum · die Boden-Meldung von doc-smoke behauptet nicht mehr „Parser kaputt", wenn
  einfach weniger dokumentiert wurde · `apply_result` sagt im Docstring, dass ein neu angelegter State nicht
  zurückgegeben wird · `ipc.inventory.test.ts` assertiert die Konvention, dass jedes `invoke()` in
  `bridge/index.ts` steht.
