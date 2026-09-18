<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 8b — Generatoren — Task-Ledger
Status: aktiv · Branch: feature/harness-stufe-8b · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/harness-stufe-8b.md
Fast-Suite: lokal · Warm-Profil: desktop
Lane: Worktree `../AdminHelper-harness-stufe-8b`, parallel zu `feature/harness-stufe-4` — die `.devenv.sh` dieser Lane setzt `AH_VENV=/tmp/ah-venv-8b` (eigener Dev-venv, damit T1 nicht in den venv der anderen Lane installiert); vor jedem Lauf `source .devenv.sh`. Die Test-DB `adminhelper_test` bleibt geteilt: nie zwei Server-Suiten gleichzeitig.
Heavy: keine im Abschluss (kein Cross-Host-Pfad, kein Produktcode); der nächste Wochenlauf fährt den `schemathesis`-Schritt mit 100 Beispielen auf der Box
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: R-0005 · Hängt ab von: R-0004 (gemergt, PR #18) · Parallel-tauglich zu Stufe 4: ja (disjunkt bis auf DEVELOPMENT.md/CHANGELOG)
Regel: Erstlauf-Funde von Schemathesis werden triagiert, nicht ausgeschlossen — mehr als fünf nötige Ausschlüsse je Dienst ⇒ `[?]` mit Liste. Nur ein Testlauf zur Zeit (Server-Suite teilt die Test-DB).

## A — Abhängigkeiten und Schritt

### T1 — requirements-dev.txt für alle drei Python-Dienste  [x]
Komponente: apps/server, apps/monitoring, apps/ca-issuer · Dateien: apps/server/requirements-dev.txt, apps/monitoring/requirements-dev.txt (neu), apps/ca-issuer/requirements-dev.txt (neu), scripts/tests/run.sh (Install-Zeilen), .github/workflows/ci.yml (Install-Zeilen), .gitignore
Änderung: `hypothesis>=6.168`, `schemathesis>=4.27`, `pytest-alembic>=0.12` in `apps/server/requirements-dev.txt`; neue Dev-Dateien für Monitoring (`-r requirements.in`, `pytest`, `pytest-cov`, `hypothesis`, `schemathesis`, `pytest-alembic`) und CA-Issuer (`-r requirements.in`, `pytest`, `httpx`, `schemathesis`); `run.sh` und `ci.yml` installieren je Dienst `-r requirements-dev.txt`; `.hypothesis/` in `.gitignore`.
Verify: bash scripts/tests/run.sh unit --strict --only server monitoring ca-issuer
Doku: DEVELOPMENT.md „Python-Dependencies & Lockfiles" (ein Satz: Dev-Deps je Dienst)
Ergebnis: Dev-Deps je Dienst; run.sh/ci.yml installieren nur noch `-r requirements-dev.txt`. hypothesis 6.168.0, schemathesis 4.27.3, pytest-alembic 0.12.1 installiert. quick --strict grün: monitoring/ca-issuer/server je `3 passed, 0 failed`, scripts `5 passed, 0 failed`.

### T2 — run.sh-Schritt `schemathesis`, Beispielzahl, heavy.sh-Zeile  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/heavy.sh (eine Env-Zeile), .github/workflows/ci.yml (Env `AH_SCHEMATHESIS_EXAMPLES=20`), scripts/tests/run_flags_test.sh
Änderung: Schritt `schemathesis` im `unit`-Layer, Key `server monitoring ca-issuer` (läuft, wenn einer der Keys gewählt ist), dep-gated auf `python3 -c "import schemathesis"` im jeweiligen Venv, in `AH_REQUIRED_DEFAULT`; führt `pytest -q -m schemathesis` je Dienst aus (Marker aus T3–T5), `AH_SCHEMATHESIS_EXAMPLES` Default 5; `heavy.sh` exportiert `AH_SCHEMATHESIS_EXAMPLES=100` für den Box-Lauf; `ci.yml` setzt 20 in den drei Python-Jobs. `run_flags_test`: Schritt-Id in den Erwartungen, Self-SKIP ohne Paket ⇒ `strict-failed: schemathesis (SKIP)`.
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: keine (T11)
Abhängt von: T1
Review-Notiz aus T1 (nit): der `||`-Fallback des ca-issuer-Zweigs in run.sh installiert nur `pytest cryptography` — ohne fastapi/sqlalchemy/httpx. Schon vor 8b unzureichend; wenn der Schemathesis-Schritt dort greift, hier mitprüfen.
Ergebnis: Schritt `schemathesis` im unit-Layer (Name = Id, damit die Zeile `strict-failed: schemathesis (SKIP)` lautet), dep-gated auf `import schemathesis`, fährt nur die per `--only` gewählten Dienste; pytest-Exit 5 („no tests collected") wird 75 = self-SKIP, nie PASS. `AH_SCHEMATHESIS_EXAMPLES` 5/20/100. run_flags_test: 6 neue Fälle (Schritt-Id, dep-Gate, und die rc-Akkumulation über mehrere Dienste in beiden Richtungen), `72 passed, 0 failed`; iter_flags_test: 3 neue Fälle für Forward/Validierung, `27 passed, 0 failed`. verify.sh scripts --strict: `5 passed, 0 failed, 12 skipped`.
Zusatz gegenüber der Dateiliste: **scripts/vm/iter.sh** musste mit — es reicht nur eine Allowlist von AH_*-Variablen an die Box weiter, ohne den Forward bliebe heavy.sh' 100 auf der Dev-Box hängen und der Wochenlauf fuzzte mit 5, während der Report „tief" behauptet.
[?] Offen für den Abschluss: `AH_REQUIRED` aus Kevins `.devenv.sh` überschreibt `AH_REQUIRED_DEFAULT` und kennt `schemathesis` nicht — der Schritt ist auf der Dev-Box daher **nicht** Pflicht (auf Box und in CI schon, dort ist AH_REQUIRED ungesetzt). Nach T5 einmal mit erweitertem Satz gegenfahren; Kevins Datei ist per-Host und gitignored, das ist seine Zeile.

## B — Schemathesis

### T3 — Server: Schemathesis mit Auth-Matrix  [ ]
Komponente: apps/server · Dateien: apps/server/tests/test_schemathesis.py (neu, SPDX), apps/server/tests/schemathesis_exclude.toml (neu), apps/server/tests/conftest.py (Marker `schemathesis`, Fixture für die fünf Auth-Kontexte)
Änderung: `schema = schemathesis.openapi.from_asgi("/openapi.json", app)`; ein parametrisierter Test je Auth-Kontext: Admin-JWT (Login), Read-Key, Read-Write-Key, Server-gebundener Key mit **fremdem** `server_id`, `X-Internal-Key`; Checks `not_a_server_error`, `response_schema_conformance`, `negative_data_rejection`, `ignored_auth`, `use_after_free`, `ensure_resource_availability`; `@settings(max_examples=int(os.environ.get("AH_SCHEMATHESIS_EXAMPLES", "5")), deadline=None)`; Ausschlüsse nur aus `schemathesis_exclude.toml` (Felder `operation_id`, `reason`, `until`), die der Test einliest und über `schema.exclude(operation_id=…)` anwendet; gegen die Test-DB (`db_session`-Override). Erstlauf-Funde als Liste in der Task-Annotation; > 5 Ausschlüsse ⇒ `[?]`.
Verify: bash scripts/dev/verify.sh server --strict -- -m schemathesis
Doku: keine (T11)
Abhängt von: T2

### T4 — Monitoring: Schemathesis  [ ]
Komponente: apps/monitoring · Dateien: apps/monitoring/tests/test_schemathesis.py (neu, SPDX), apps/monitoring/tests/schemathesis_exclude.toml (neu), apps/monitoring/tests/conftest.py (Marker)
Änderung: wie T3 mit den Kontexten Agent-Key (`require_agent`), Internal-Key (`require_internal`) und anonym; SQLite-Override aus `client_db`; VictoriaMetrics-Aufrufe wie in `client_db` gestubbt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- -m schemathesis
Doku: keine (T11)
Abhängt von: T2

### T5 — CA-Issuer: Schemathesis  [ ]
Komponente: apps/ca-issuer · Dateien: apps/ca-issuer/tests/test_schemathesis.py (neu, SPDX), apps/ca-issuer/tests/schemathesis_exclude.toml (neu)
Änderung: App über `build_issuer` mit Memory-Store; Kontexte: ohne Header, mit `x-client-verify: SUCCESS` + Test-Zertifikat (Fixture aus den bestehenden Tests); Checks wie T3.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- -m schemathesis
Doku: keine (T11)
Abhängt von: T2

## C — Hypothesis (genau drei Ziele)

### T6 — FRP-TOML-Round-Trip  [ ]
Komponente: apps/server · Dateien: apps/server/tests/test_frp_toml_roundtrip.py (neu, SPDX)
Änderung: Strategien für `FrpServerConfig`/Tunnel-Modelle aus den Pydantic-Feldern (`st.builds` mit Text ohne `_TOML_BREAKERS` für Strings, `extra_config` mit Bare-Keys und str/bool/int/float-Werten); `generate_frps_toml`/`generate_frpc_toml`/`generate_visitor_toml` ⇒ `tomllib.loads` ⇒ Felder identisch (Adresse, Ports, Namen, `extra_config`-Werte); zweiter Test: jeder String **mit** Breaker wird von `_reject_toml_breakers` abgelehnt (`ValueError`). `@example`-Pins für die Grenzfälle (leerer String, `=` im Wert, Unicode). Mutanten-Gegenprobe im Worktree: Validator deaktiviert ⇒ rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_toml_roundtrip.py
Doku: keine (intern)
Abhängt von: T1

### T7 — Line-Protocol-Round-Trip  [ ]
Komponente: apps/monitoring · Dateien: apps/monitoring/tests/test_victoria_roundtrip.py (neu, SPDX)
Änderung: Test-eigener Parser für `measurement,tags value=X ts` (Escapes `\ `, `\,`, `\=`, `\\`); Property: `format_line(m, tags, v, ts)` ⇒ parse ⇒ `(m', tags', v', ts')` mit `m'`/`tags'` gleich den kontrollzeichen-normalisierten Eingaben, `v'` gleich, `ts'` gleich; Text-Strategien mit Leerzeichen, Komma, Gleich, Backslash, Steuerzeichen; Typfehler (`bool`, `nan`) ⇒ Exception wie dokumentiert. `@example`-Pins. Gegenprobe: eine Escape-Zeile in `_esc_tag` entfernen ⇒ rot.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_victoria_roundtrip.py
Doku: keine (intern)
Abhängt von: T1

### T8 — is_private_url: Properties und Parser-Differential  [ ]
Komponente: apps/server · Dateien: apps/server/tests/test_ssrf_properties.py (neu, SPDX)
Änderung: `_resolve` per `monkeypatch` durch eine Funktion ersetzt, die eine generierte Adresse liefert; Property über `st.ip_addresses()` (v4/v6): private/loopback/link-local/reserved/multicast/unspecified/`_BLOCKED_NETWORKS` ⇒ `True`, sonst `False` (Orakel: `ipaddress`-Attribute); IPv4-mapped-IPv6 ⇒ wie die v4-Adresse. Differential: für URLs aus `st.from_regex` stimmt der Hostname, den der Guard an `_resolve` gibt, mit `urllib.parse.urlsplit(url).hostname` überein; Fehlerpfade (kein Host, `ValueError`) ⇒ `True`. Der Paritätstest aus 8a bleibt unberührt (kein Produktcode).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ssrf_properties.py tests/test_ssrf_parity.py
Doku: keine (intern)
Abhängt von: T1

## D — Concurrency und Alembic

### T9 — Postgres-Concurrency für execute_check  [ ]
Komponente: apps/monitoring · Dateien: apps/monitoring/tests/test_check_engine_concurrency.py (neu, SPDX), scripts/tests/run.sh (`test_skip_is_required`-Eintrag)
Änderung: `DATABASE_URL`-gegattert wie `test_migrations_smoke.py`; eigene Engine, Schema per `Base.metadata.create_all` in einer Wegwerf-DB (`CREATEDB`-Rolle wie beim Server); ein Check mit `fail_count` = 2 und zwei Threads mit `threading.Barrier`, die `execute_check` gleichzeitig mit einem roten Ergebnis ausführen (Checker per `monkeypatch` gestubbt); Erwartung: `fail_count` == 4 und genau **ein** Alert-Dispatch (Dispatcher gestubbt und gezählt). Gegenprobe: `.with_for_update()` entfernen ⇒ rot (Lost Update: 3 oder Doppel-Alert). `run.sh`: unter `--strict` ist der Skip nur ohne `DATABASE_URL` erlaubt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_engine_concurrency.py
Doku: keine (intern)
Abhängt von: T1

### T10 — pytest-alembic für Server und Monitoring  [ ]
Komponente: apps/server, apps/monitoring · Dateien: apps/server/tests/test_alembic_builtin.py (neu, SPDX), apps/server/tests/conftest.py (Fixtures `alembic_config`, `alembic_engine`), apps/monitoring/tests/test_alembic_builtin.py (neu, SPDX), apps/monitoring/tests/conftest.py
Änderung: Fixtures zeigen auf `alembic.ini`/`script_location` der App und auf eine Wegwerf-DB (Server: `pg_engine`-Mechanik; Monitoring: `DATABASE_URL`-gegattert); die vier eingebauten Tests werden importiert (`from pytest_alembic.tests import test_single_head_revision, test_upgrade, test_model_definitions_match_ddl, test_up_down_consistency`); je ein Seed-Test mit `alembic_runner.migrate_up_before(<rev>)` + `insert_into` + `migrate_up_one` für `f1a2b3c4d5e6_uniq_frp_tunnel_visitor_port` (Server) und `b1a2c3d4e5f6_uniq_template_assignment` (Monitoring) — die bestehenden Smoke-Tests bleiben; doppelte Aussagen werden nicht entfernt (Historie), aber der neue Test ist der, der `insert_into` nutzt.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_alembic_builtin.py   und   bash scripts/dev/verify.sh monitoring --strict -- tests/test_alembic_builtin.py
Doku: keine (intern)
Abhängt von: T1

## E — Doku

### T11 — Doku  [ ]
Komponente: docs · Dateien: DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Änderung: DEVELOPMENT.md Absatz „Generatoren" (Schritt `schemathesis`, `AH_SCHEMATHESIS_EXAMPLES`, Ausschlussliste, Hypothesis-Pins und `.hypothesis/`, Concurrency-Gatter); cicd.html DE+EN eine Tabellenzeile im Gate-Abschnitt; CHANGELOG Unreleased/Added.
Verify: python3 scripts/dev/doc-smoke.py --strict   und   bash scripts/tests/run.sh lint --strict --only scripts
Doku: alle genannten
Abhängt von: T2

## Abschluss
- `bash scripts/tests/run.sh quick --strict` grün (mit dem neuen Schritt); `bash scripts/dev/verify.sh all --strict` grün.
- Mutanten-Gegenproben aus der Spec im Wegwerf-Worktree, Ergebnis in den PR-Body.
- Erstlauf-Funde (Schemathesis) als Roadmap-Kandidaten im PR-Body; Ausschlüsse mit Grund in den TOML-Dateien.
