<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 8b — Generatoren — Task-Ledger
Status: erledigt (11/11 Tasks + T12–T16 aus PR-Review und Aufsicht; die Ausschluss-Strategie fuer `negative_data_rejection` ist als eigener Punkt offen, siehe T3 — sie blockiert nichts) · Branch: feature/harness-stufe-8b · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/harness-stufe-8b.md
Fast-Suite: lokal · Warm-Profil: desktop
Lane: Worktree `../AdminHelper-harness-stufe-8b`, parallel zu `feature/harness-stufe-4` — die `.devenv.sh` dieser Lane setzt `AH_VENV=/tmp/ah-venv-8b` (eigener Dev-venv, damit T1 nicht in den venv der anderen Lane installiert); vor jedem Lauf `source .devenv.sh`. Die Lane hat seit 2026-09-18 auch eine **eigene Test-DB** (`adminhelper_lane8b`): die geteilte `adminhelper_test` hat zweimal einen Lauf entwertet, weil die `pg_engine`-Fixture der anderen Lane am Ende per `drop_all` abräumt — mitten im fremden Lauf heisst das `Relation users existiert nicht`, also verworfen, nicht rot.
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

### T3 — Server: Schemathesis mit Auth-Matrix  [x]
Komponente: apps/server · Dateien: apps/server/tests/test_schemathesis.py (neu, SPDX), apps/server/tests/schemathesis_exclude.toml (neu), apps/server/tests/conftest.py (Marker `schemathesis`, Fixture für die fünf Auth-Kontexte)
Änderung: `schema = schemathesis.openapi.from_asgi("/openapi.json", app)`; ein parametrisierter Test je Auth-Kontext: Admin-JWT (Login), Read-Key, Read-Write-Key, Server-gebundener Key mit **fremdem** `server_id`, `X-Internal-Key`; Checks `not_a_server_error`, `response_schema_conformance`, `negative_data_rejection`, `ignored_auth`, `use_after_free`, `ensure_resource_availability`; `@settings(max_examples=int(os.environ.get("AH_SCHEMATHESIS_EXAMPLES", "5")), deadline=None)`; Ausschlüsse nur aus `schemathesis_exclude.toml` (Felder `operation_id`, `reason`, `until`), die der Test einliest und über `schema.exclude(operation_id=…)` anwendet; gegen die Test-DB (`db_session`-Override). Erstlauf-Funde als Liste in der Task-Annotation; > 5 Ausschlüsse ⇒ `[?]`.
Verify: bash scripts/dev/verify.sh server --strict -- -m schemathesis
Doku: keine (T11)
Abhängt von: T2

**Stand:** Test gebaut, committet und **grün bei der ausgelieferten Beispielzahl**: `275 passed in 4:04` (`AH_SCHEMATHESIS_EXAMPLES=5`, 55 von 78 Operationen × 5 Kontexte), und `bash scripts/dev/verify.sh server --strict` → `run.sh[quick]: 4 passed, 0 failed, 13 skipped, 2 test-skips, 0 reruns`. **Diese Zahlen sind der Stand von T3 und seit T12/T13 überholt** — dort steht die aktuelle Evidenz (vier Kontexte statt fünf, check-granulare Ausschlüsse, 252 statt 275 Tests). `[?]` bleibt: 24 Ausschlüsse sind weit über der Ledger-Grenze von fünf je Dienst, und die zwei Hebel, die die Liste kurz machen würden, sind Kevins Entscheidung (unten).

**Nachtrag `derandomize=True`:** Ohne das war die Suite pro Lauf eine andere — **Hypothesis zieht ohne diese Einstellung bei jedem Lauf einen neuen Seed**, ein Lauf war grün, der nächste rot auf einer Operation, die niemand angefasst hatte (real beobachtet: `6 failed, 299 passed` direkt nach einem `305 passed`). Die Spec hatte das als CI-Profil vorgesehen; hier gilt es für jeden Lauf, die Tiefe kommt über `AH_SCHEMATHESIS_EXAMPLES`, nicht über Zufall.

**Nachtrag zu T2:** Der `schemathesis`-Schritt reicht `$AH_ARGS` nicht mehr durch. Er selektiert über seinen Marker; ein `verify.sh server --strict -- tests/eine_datei.py` hätte ihm sonst genau diese eine Datei vorgesetzt, in der kein Schemathesis-Test steht ⇒ „nichts gesammelt" ⇒ SKIP ⇒ unter `--strict` ein Loch in einem Lauf, der damit nichts zu tun hat.

**Zwei Korrekturen an der Spec** (beide verifiziert, nicht vermutet):
- `schemathesis.openapi.from_asgi(...)` aus der Spec ist hier unbrauchbar: es holt `/openapi.json` über den Transport und startet damit schon beim **Import** den App-Lifespan, dessen Startup die `users`-Tabelle abfragt — zur Collect-Zeit existiert sie nicht. Stattdessen `from_dict(app.openapi())` + `schema.app = app`: kein Request, kein Lifespan, dieselben 78 Operationen.
- Anders als der conftest-`TestClient` führt der Schemathesis-Transport den Lifespan **aus**; dessen `_ensure_admin` schreibt durch die echte Engine am Rollback vorbei, der nächste Test stirbt am Unique-Constraint auf `users.username`. Die Fixture neutralisiert `_run_startup_tasks`.
- Von den sechs Checks liegt nur `not_a_server_error` in `schemathesis.checks`; die anderen fünf gibt es in 4.27 nur unter `schemathesis.specs.openapi.checks` (kein öffentlicher Alias).

**Erstlauf 2026-09-18** (`AH_SCHEMATHESIS_EXAMPLES=1`, alle fünf Kontexte): `29 failed, 361 passed in 344s`. Kein Sicherheitsfund — die beiden auffälligen Fälle sind nachgeprüft:
- `POST /api/connections` ohne Auth ⇒ **401** in allen Varianten; der `ignored_auth`-Treffer ist ein **False Positive**.
- `POST /api/auth/logout` ohne Token ⇒ **200 „Abgemeldet"**; die Route tut dabei nichts. Schema deklariert Auth, Route verlangt keine — Mismatch, kein Loch.

| Klasse | Treffer | Bewertung |
|---|---|---|
| `negative_data_rejection` | 11 | Pydantic v2 Lax-Modus (`is_admin: 0` ⇒ `False`, `dashboard_port`, `trustCert`, `ids`). Framework-Design, kein Defekt — trifft systematisch jede Route mit bool/int-Feldern |
| `ignored_auth` | 7 | 5× `logout` (derselbe Befund je Kontext) + 1× `connections` (False Positive, s. o.) |
| `response_schema_conformance` | 4 | **Echte Vertragsbrüche**: `GET/POST /api/api-keys`, `POST /api/hooks`, `POST /api/connections` — deckt sich mit **R-0043** (Routen ohne `response_model`) |

Betroffene Operationen (17): GET/POST `/api/api-keys` · GET/POST `/api/connections` · POST `/api/connections/import` · POST/PUT `/api/ansible/playbooks[/{id}]` · POST `/api/auth/logout` · POST/PUT `/api/frp/tunnels[/{id}]` · POST `/api/frp/server-config` · POST `/api/hooks` · POST `/api/monitoring/agent/{server_id}/report` · POST `/api/notifications/read` · POST/PUT `/api/servers[/{id}]` · POST `/api/users`

**Kevins Entscheidung — drei Wege:**
1. `negative_data_rejection` für die Python-Dienste abschalten (ein begründeter Eintrag statt elf): Pydantics Koerzierung ist Framework-Design. Danach bleiben 5 Operationen auszuschließen (4× R-0043, 1× logout) — genau an der Ledger-Grenze.
2. Alle 17 Operationen einzeln in `schemathesis_exclude.toml` mit Grund und `until`. Ehrlich, aber der Test fuzzt dann nur noch 61 von 78 Operationen.
3. Produktcode anpassen (strict-mode-Felder, `response_model` nachziehen) — liegt außerhalb von 8b („kein Produktcode" im Ledger-Kopf) und gehört als eigene Roadmap-Zeile hinter R-0043.

**Review-Urteil (Opus, Risikopfad Auth): `request_changes`.** Drei Blocker, davon zwei noch offen:

1. **Grün-Evidenz galt der falschen Konfiguration.** Verifiziert wurde mit `AH_SCHEMATHESIS_EXAMPLES=1`, ausgeliefert sind **5** lokal und **20** in CI — und dort ist die Suite rot. Ursache ist ein **echter Produktfehler**, unabhängig vom Fuzzer per TestClient reproduziert: `user_id: int` ist in `users/router.py` nicht begrenzt, ab `2**31` läuft die Postgres-Abfrage in `NumericValueOutOfRange`, ungefangen ⇒ **HTTP 500**.
   `user_id=2147483647 → 404` · `user_id=2147483648 → 500` · `user_id=2**53 → 500`, je bei `DELETE` und `PUT /api/users/{user_id}`.
   Das trifft vermutlich **jeden** `int`-Pfadparameter des Servers ⇒ Roadmap-Zeile (eigene Klasse, nicht R-0043). Offen: Ausschluss mit dieser echten Begründung **oder** Produktfix.
2. **Die Fuzz-Tests liefen doppelt** — kein `-m "not schemathesis"` in den drei pytest-Schritten, also fuhr `run.sh quick` sie zweimal und der CI-Job `server` (15-min-Budget, 20 Beispiele, plus `--cov`) hätte sein Budget gerissen. **Behoben** in `run.sh` (3 Stellen) und `ci.yml` (3 Jobs).
3. **Die Ausschluss-Begründungen waren sachlich falsch.** Fünf Treffer standen als „Route ohne `response_model`" (R-0043) in der TOML — **alle fünf Routen haben eines** (`api_keys/router.py:18,23`, `hooks/router.py:125`, `connections/router.py:52,67`). Die Vermutung wurde ungeprüft übernommen; damit wäre ein selbst als „echter Vertragsbruch" eingestufter Fund hinter einer erfundenen Ursache geparkt — genau das Versagen, das die TOML-Mechanik verhindern soll. Offen: echte Abweichung je Treffer ermitteln (Lauf ohne Ausschlüsse bei 5 Beispielen) und eintragen, oder Ausschluss streichen.

**Kevins Entscheidung 2026-09-21 — beide Punkte umgesetzt:**

1. **`ignored_auth` laeuft nur noch dort, wo das Schema die Auth deklariert.** Server: an fuer `admin_jwt` (HTTPBearer steht im Schema), per `excluded_checks` aus fuer die drei Key-Kontexte. Monitoring und CA-Issuer: ganz aus der Check-Liste, weil beide Apps ueberhaupt kein Security-Scheme deklarieren. Das ersetzt drei Operations-Ausschluesse durch eine Check-Abwahl — die Operationen werden jetzt wieder von den uebrigen Checks geprueft, statt ganz zu fehlen.
2. **`foreign_bound_key` gestrichen.** Der Fuzzer generiert zufaellige `server_id`-Pfadparameter und trifft nie eine existierende, der Kontext verhielt sich auf jeder Route wie `read_write_key`. Die Eigenschaft, die er vorgab zu pruefen, wird an genau zwei Stellen durchgesetzt, und jede hat ihren eigenen handgeschriebenen Test mit geseedeten Ids: `frp/provision_router.py::_require_server_scope` in `tests/test_frp_provision_authz.py`, der Scope-Filter in `connections/router.py:47` in `tests/test_connections_isolation.py`.

**Wirkung:** Server `204 passed in 3:03` statt `265 passed in 4:00` (−24 % Laufzeit, ein Kontext weniger), Monitoring `111 passed in 36s`, CA-Issuer `9 passed` **ohne einen einzigen Ausschluss**.

**Dabei gefunden — ein Fehler in allen drei Suiten:** Der ASGI-Transport schreibt seine eigenen Default-Header (`user-agent`, `Accept`, …) **in das uebergebene Dict**. Da die Fixture ein Dict je Kontext haelt und alle Beispiele eines Tests es teilen, wuchs der Header-Satz im Lauf der Ausfuehrung — spaetere Beispiele bekamen etwas anderes gesendet als fruehere, und im Monitoring fuehrte das zu einem Fehlschlag, der nichts mit der API zu tun hatte. Jetzt bekommt jedes Beispiel eine Kopie.

**Noch offen (dritter Hebel, unveraendert bei Kevin):** `negative_data_rejection` stellt 17 der 27 Ausschluesse. Zwei davon sind seit heute als **dieselbe blinde Stelle** wie bei `ignored_auth` belegt: Der Check laesst den `Authorization`-Header weg und erwartet eine Ablehnung — aber die Fixture setzt die Auth-Header von aussen ueber `headers=`, der Request geht also authentifiziert raus und die 200 gilt ihm als „schema-widrige Daten akzeptiert". Die uebrigen messen ueberwiegend echt (Pydantics lax-Koerzierung im Body, belegt an `is_admin`, `dashboard_port`, `ids`, `trustCert`) — aber nicht alle: `GET /api/connections` hat gar keinen Body und ist, einzeln nachgefahren, **nur** die Header-Blindstelle. Wie viele der Einträge rein daran haengen, ist nicht ausgezaehlt; die Begruendungen der vier in dieser Runde angefassten stammen jetzt aus je einem eigenen Lauf. Ohne diesen Check blieben **10 Ausschluesse**: fuenf echte 500er, vier echte Vertragsbrueche, ein logout-Schema-Mismatch.

**Die urspruengliche Vorlage (erledigt, zur Nachvollziehbarkeit):**

- **`ignored_auth` prüft in vier von fünf Kontexten keine Authentifizierung.** Schemathesis 4.27 zählt nur **schema-deklarierte** Security-Parameter; die App deklariert allein `HTTPBearer` (68 von 78 Operationen), `X-API-Key` liest `core/auth.py:186` von Hand aus den Headern. Für `read_key`, `read_write_key`, `foreign_bound_key` und `internal_key` degeneriert der Check zu „hat 2xx geantwortet" — der „False Positive" auf `POST /api/connections` war systematisch, nicht zufällig. Sauber wäre `excluded_checks=[ignored_auth]` für die vier Nicht-JWT-Kontexte statt ganzer Operations-Ausschlüsse.
- **`foreign_bound_key` beweist das IDOR nicht, das sein Name behauptet.** `api_key.server_id` wird nur an zwei Stellen ausgewertet (`connections/router.py:47`, `frp/provision_router.py:39`); Schemathesis generiert zufällige `server_id`-Pfadparameter und trifft nie eine existierende Id, also antworten alle drei Key-Kontexte gleich mit 403. Der Kontext kostet 61 Tests ohne eigene Aussage. Entweder den Pfadparameter auf eine geseedete Id lenken, oder den Kontext streichen und im Docstring auf `test_frp_provision_authz.py` verweisen. (Derselbe Hebel entschärft die Laufzeit unten: `read_key` und `read_write_key` unterscheiden sich nur auf ~5 Routen, auf den übrigen ~70 sind es drei identische Läufe.)

**Erstlauf 2026-09-18, Lane-eigene DB, 5 Beispiele, ohne Ausschlüsse: `35 failed, 355 passed` über 23 Operationen.** Klassen: 14× `negative_data_rejection` (Pydantic-Koerzierung), 7× `ignored_auth` (davon 5× dieselbe logout-Route, 1× Check-Artefakt), 4× `response_schema_conformance`. Dazu zwei **echte Produktfehler** derselben Klasse:

| Fund | Beleg | Bewertung |
|---|---|---|
| `DELETE`/`PUT /api/users/{user_id}` → **HTTP 500** ab `user_id ≥ 2**31` | unabhängig per TestClient reproduziert: `2147483647 → 404`, `2147483648 → 500`, `2**53 → 500` | `user_id: int` unbegrenzt, Postgres-`INTEGER` läuft in `NumericValueOutOfRange`, ungefangen |
| `POST /api/enrollment/token/for` → **HTTP 500** bei NUL-Byte im Benutzernamen | `parameters = [{'username_1': '\x00', …}]` im Lauf-Log | Postgres erlaubt kein `0x00` in Textwerten, der psycopg-Fehler läuft ungefangen durch |
| `POST /api/connections/import` → **Vertragsbruch** | Antwort-Body `message` + `rejected` bei HTTP 422, Schema deklariert dort FastAPIs `HTTPValidationError` mit `detail: array` | ein Client, der dem Schema folgt, parst die Fehlermeldung falsch |
| `GET /api/notifications` → **HTTP 500** bei einem Paginierungs-Parameter ≥ 2**63 | im Lauf vom 2026-09-21 aufgetaucht | dieselbe Klasse, aber ueber einen **Query**-Parameter statt einen Pfadparameter — die Luecke ist breiter als nur die Pfad-Ids |

**Das ist ein Befund, nicht vier:** Eingaben, die erst in der DB-Schicht scheitern (Integer-Überlauf, NUL-Byte), werden nicht am Rand abgefangen. Solange diese Klasse offen ist, fördert jede Änderung an Lauf-Bedingungen ein weiteres Symptom zutage — der zweite 500er tauchte bei einem Lauf mit anderer Beispielzahl auf, der dritte zwei Tage später bei normaler Weiterarbeit, der vierte und fünfte erst, als die Ausschlüsse check-granular wurden (T12). Pfad-Ids, Textfelder und Paginierungs-Parameter sind betroffen — die Randvalidierung fehlt an allen drei Stellen. **Roadmap-Zeile: Randvalidierung für DB-feindliche Eingaben.** (Korrektur zur ersten Fassung dieses Ledgers: die vier `response_schema_conformance`-Treffer sind **nicht** R-0043 — alle betroffenen Routen haben ein `response_model`; die Ursache ist bei `connections/import` belegt, bei `api-keys`/`hooks` noch offen und im TOML als solche markiert.)

**Zweiter `[?]`-Punkt — Laufzeit:** 78 Operationen × 5 Kontexte × **1** Beispiel = **5:44 min**. Der lokale Default ist 5 Beispiele. Die Spec-Zusage „quick bleibt unter einer Minute" ist mit der vollen Auth-Matrix nicht haltbar: entweder läuft `schemathesis` nur in CI/weekly (nicht im lokalen `quick`), oder die Matrix wird lokal auf einen Kontext gekürzt und die volle Matrix bleibt dem Wochenlauf.

### T4 — Monitoring: Schemathesis  [x]
Komponente: apps/monitoring · Dateien: apps/monitoring/tests/test_schemathesis.py (neu, SPDX), apps/monitoring/tests/schemathesis_exclude.toml (neu), apps/monitoring/tests/conftest.py (Marker)
Änderung: wie T3 mit den Kontexten Agent-Key (`require_agent`), Internal-Key (`require_internal`) und anonym; SQLite-Override aus `client_db`; VictoriaMetrics-Aufrufe wie in `client_db` gestubbt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- -m schemathesis
Doku: keine (T11)
Abhängt von: T2

### T5 — CA-Issuer: Schemathesis  [x]
Komponente: apps/ca-issuer · Dateien: apps/ca-issuer/tests/test_schemathesis.py (neu, SPDX), apps/ca-issuer/tests/schemathesis_exclude.toml (neu)
Änderung: App über `build_issuer` mit Memory-Store; Kontexte: ohne Header, mit `x-client-verify: SUCCESS` + Test-Zertifikat (Fixture aus den bestehenden Tests); Checks wie T3.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- -m schemathesis
Doku: keine (T11)
Abhängt von: T2
Ergebnis: `9 passed` (3 Operationen × 3 Kontexte) — **kein Ausschluss noetig**, die Liste ist leer. Kontexte: ohne Header, Gateway-Verdikt ohne Zertifikat, Verdikt mit echtem Zertifikat; das sind genau die drei Formen, die `/renew` auseinanderhalten muss (der Issuer terminiert kein mTLS selbst, er vertraut `x-client-verify` plus dem escapten PEM). `ignored_auth` ist auch hier nicht in der Check-Liste — die App deklariert kein Security-Scheme. Die Fixture oeffnet den TestClient als Context-Manager: `app.state.issuer` entsteht erst im Lifespan, und Schemathesis startet den erst beim ersten Request.

## C — Hypothesis (genau drei Ziele)

### T6 — FRP-TOML-Round-Trip  [x]
Komponente: apps/server · Dateien: apps/server/tests/test_frp_toml_roundtrip.py (neu, SPDX)
Änderung: Strategien für `FrpServerConfig`/Tunnel-Modelle aus den Pydantic-Feldern (`st.builds` mit Text ohne `_TOML_BREAKERS` für Strings, `extra_config` mit Bare-Keys und str/bool/int/float-Werten); `generate_frps_toml`/`generate_frpc_toml`/`generate_visitor_toml` ⇒ `tomllib.loads` ⇒ Felder identisch (Adresse, Ports, Namen, `extra_config`-Werte); zweiter Test: jeder String **mit** Breaker wird von `_reject_toml_breakers` abgelehnt (`ValueError`). `@example`-Pins für die Grenzfälle (leerer String, `=` im Wert, Unicode). Mutanten-Gegenprobe im Worktree: Validator deaktiviert ⇒ rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_toml_roundtrip.py
Doku: keine (intern)
Abhängt von: T1
Ergebnis: `6 passed, 2 xfailed`. **Zwei Funde, beide als strikter xfail mit `raises=` gepinnt** — ohne `raises` zaehlt jede Exception als erwarteter Fehlschlag, der Test bliebe nach einem Fix still `xfail` statt `XPASS`, die „Erinnerung" haette also nie ausgeloest:
1. `_reject_toml_breakers` lehnt `ord(c) < 0x20` ab, aber **nicht U+007F** — TOML verbietet DEL in einem Basic String genauso, das erzeugte frps.toml ist dann unparsbar. Kein Injection-Pfad, reine Verfuegbarkeit.
2. Ein `extra_config`-Schluessel, den der Generator **selbst** schreibt (`auth`, `webServer`, `transport`), wird ein zweites Mal ausgegeben ⇒ `TOMLDecodeError: Cannot overwrite a value`. Das Schema nimmt den Schluessel an, die Datei ist danach unlesbar. Selbe Klasse wie 1; Produktfix liegt ausserhalb von 8b ⇒ beide Roadmap-Kandidaten.

Abgedeckt sind jetzt **beide Tunnel-Zweige**: die erste Fassung liess `_tunnel()` auf `tunnel_type="tcp"` stehen — ein Wert, den das Schema (`Literal["stcp","https"]`) gar nicht zulaesst —, wodurch `secretKey`, `allowUsers` und `customDomains` nie erzeugt wurden, also genau die Interpolationen, um die es geht. Dazu ein Test, der eine Kopplung festhaelt: `allowUsers` wird unescaped interpoliert und ist nur deshalb sicher, weil `_USERNAME_PATTERN` (users/schemas.py, zwei Module entfernt) keine Anfuehrungszeichen zulaesst — wer das Muster lockert, bricht hier und nicht erst im Tunnel.

### T7 — Line-Protocol-Round-Trip  [x]
Komponente: apps/monitoring · Dateien: apps/monitoring/tests/test_victoria_roundtrip.py (neu, SPDX)
Änderung: Test-eigener Parser für `measurement,tags value=X ts` (Escapes `\ `, `\,`, `\=`, `\\`); Property: `format_line(m, tags, v, ts)` ⇒ parse ⇒ `(m', tags', v', ts')` mit `m'`/`tags'` gleich den kontrollzeichen-normalisierten Eingaben, `v'` gleich, `ts'` gleich; Text-Strategien mit Leerzeichen, Komma, Gleich, Backslash, Steuerzeichen; Typfehler (`bool`, `nan`) ⇒ Exception wie dokumentiert. `@example`-Pins. Gegenprobe: eine Escape-Zeile in `_esc_tag` entfernen ⇒ rot.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_victoria_roundtrip.py
Doku: keine (intern)
Abhängt von: T1
Ergebnis: `5 passed`. Der Test-Parser fand zuerst einen Fehler **in sich selbst** (er unescapte schon beim ersten Split, sodass der zweite Split ein vom Writer escaptes Komma als Trenner las und einen Tag-Wert in zwei Tags zerriss) — gefunden vom `@example`-Pin mit der Injection-Zeile, nicht vom Zufall. Splitten und Unescapen sind jetzt getrennt. Der Writer selbst hielt allen generierten Eingaben stand.

### T8 — is_private_url: Properties und Parser-Differential  [x]
Komponente: apps/server · Dateien: apps/server/tests/test_ssrf_properties.py (neu, SPDX)
Änderung: `_resolve` per `monkeypatch` durch eine Funktion ersetzt, die eine generierte Adresse liefert; Property über `st.ip_addresses()` (v4/v6): private/loopback/link-local/reserved/multicast/unspecified/`_BLOCKED_NETWORKS` ⇒ `True`, sonst `False` (Orakel: `ipaddress`-Attribute); IPv4-mapped-IPv6 ⇒ wie die v4-Adresse. Differential: für URLs aus `st.from_regex` stimmt der Hostname, den der Guard an `_resolve` gibt, mit `urllib.parse.urlsplit(url).hostname` überein; Fehlerpfade (kein Host, `ValueError`) ⇒ `True`. Der Paritätstest aus 8a bleibt unberührt (kein Produktcode).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ssrf_properties.py tests/test_ssrf_parity.py
Doku: keine (intern)
Abhängt von: T1
Ergebnis: `7 passed`. Kein Fund — der Guard stimmt für alle generierten v4/v6-Adressen mit dem `ipaddress`-Orakel überein, IPv4-mapped wird wie die eingebettete v4 bewertet, und alle drei Aufgeber-Pfade (None, unparsbare Antwort, kein Host) schliessen zu. **Das Parser-Differential wurde umgebaut:** Die Task-Vorlage nennt `urlsplit` als Vergleich — der beweist nichts, weil `urlparse` intern `urlsplit` aufruft und beide per Konstruktion nie abweichen koennen. Verglichen wird jetzt gegen **`httpx.URL(url).host`**, also gegen den Parser, den der tatsaechliche Fetch benutzt (`script_worker.py::_safe_http_get` → `httpx.stream`): lesen Guard und Client denselben String verschieden, prueft der Guard eine Adresse und geholt wird eine andere. Die Strategie erzeugt die Formen, an denen URL-Parser bekanntlich auseinandergehen (Userinfo, zweites `@`, IPv6 in Klammern, Backslash statt Slash, Prozent-Encoding, leerer Port). **Ergebnis: keine Abweichung** — kein Bypass auf diesem Weg. Zweite Abweichung: statt der `monkeypatch`-Fixture ein Context-Manager (`patch.object`) — eine function-scoped Fixture wird **einmal pro Test** gesetzt, nicht pro generiertem Beispiel; Hypothesis' Health-Check weist das zu Recht ab, und ihn zu unterdrücken wäre die schlechtere Antwort gewesen.

## D — Concurrency und Alembic

### T9 — Postgres-Concurrency für execute_check  [x]
Komponente: apps/monitoring · Dateien: apps/monitoring/tests/test_check_engine_concurrency.py (neu, SPDX), scripts/tests/run.sh (`test_skip_is_required`-Eintrag)
Änderung: `DATABASE_URL`-gegattert wie `test_migrations_smoke.py`; eigene Engine, Schema per `Base.metadata.create_all` in einer Wegwerf-DB (`CREATEDB`-Rolle wie beim Server); ein Check mit `fail_count` = 2 und zwei Threads mit `threading.Barrier`, die `execute_check` gleichzeitig mit einem roten Ergebnis ausführen (Checker per `monkeypatch` gestubbt); Erwartung: `fail_count` == 4 und genau **ein** Alert-Dispatch (Dispatcher gestubbt und gezählt). Gegenprobe: `.with_for_update()` entfernen ⇒ rot (Lost Update: 3 oder Doppel-Alert). `run.sh`: unter `--strict` ist der Skip nur ohne `DATABASE_URL` erlaubt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_engine_concurrency.py
Doku: keine (intern)
Abhängt von: T1
Ergebnis: `2 passed`, **beide Locks per Mutation belegt** (je im Wegwerf-Worktree, nie im Builder-Tree):
- `.with_for_update()` aus `check_engine.execute_check` entfernt ⇒ `fail_count is 3, expected 4`
- `.with_for_update()` aus dem Claim in `alerter.process_alert` entfernt ⇒ `2 notifications sent, expected exactly 1`

**Korrektur nach dem Review:** Die erste Fassung behauptete, *ein* Test belege beide Locks. Das war falsch, und der Reviewer hat es mit einer eigenen Mutationsprobe widerlegt: Die Verzoegerung sitzt in `execute_check`, also sind die beiden Writer dort bereits serialisiert, wenn sie `process_alert` erreichen — deren Claims ueberlappen nie, und der Test blieb ohne den alerter-Lock gruen. Der zweite Lock hat jetzt seinen eigenen Test, der zwei Dispatches direkt in das Claim-Fenster fuehrt (Verzoegerung in `resolve_notification`, zwischen dem sperrenden SELECT und dem Commit). Das ist auch die realistischere Form: Scheduler und Agent-Push dispatchen aus eigenen Sessions, ohne gemeinsamen Row-Lock davor.

Zwei Dinge, die die Task-Vorlage so nicht vorsah:
1. **Die Barriere am Start reicht nicht.** Erste Fassung: beide Threads treffen sich vor `execute_check`. Der Mutant **ueberlebte** — bis zur Lock-Stelle liegt genug Arbeit (Query, Checker, Metrik-Schreiben), dass die Threads sich von selbst serialisieren. Die Ueberlappung muss IM kritischen Abschnitt erzwungen werden: `apply_result` ist fuer den Test um 0,5 s verzoegert, damit beide SELECTs offen sind, bevor der erste committet. Ohne diese Zeile beweist der Test nichts — und sah trotzdem gruen aus.
2. **„Genau ein Alert-Dispatch" misst die falsche Stelle.** Beide Writer *submitten* legitim einen Dispatch; `execute_check` sagt das selbst („a stale read here only costs a no-op task"). At-most-once entsteht erst im Claim unter `FOR UPDATE` in `alerter.process_alert` — der auf SQLite ebenfalls ein No-op ist. Der Test faehrt deshalb den **echten** Dispatch-Pfad und stubbt nur den Kanal-Versand; gezaehlt werden gesendete Benachrichtigungen, nicht Submissions. Damit deckt er zwei Locks ab statt einem.

`run.sh`: Eintrag in `test_skip_is_required` — der Skip ist nur ohne `DATABASE_URL` erlaubt, sonst waere der einzige Test dieses Locks in CI stumm uebersprungen.

### T10 — pytest-alembic für Server und Monitoring  [x]
Komponente: apps/server, apps/monitoring · Dateien: apps/server/tests/test_alembic_builtin.py (neu, SPDX), apps/server/tests/conftest.py (Fixtures `alembic_config`, `alembic_engine`), apps/monitoring/tests/test_alembic_builtin.py (neu, SPDX), apps/monitoring/tests/conftest.py
Änderung: Fixtures zeigen auf `alembic.ini`/`script_location` der App und auf eine Wegwerf-DB (Server: `pg_engine`-Mechanik; Monitoring: `DATABASE_URL`-gegattert); die vier eingebauten Tests werden importiert (`from pytest_alembic.tests import test_single_head_revision, test_upgrade, test_model_definitions_match_ddl, test_up_down_consistency`); je ein Seed-Test mit `alembic_runner.migrate_up_before(<rev>)` + `insert_into` + `migrate_up_one` für `f1a2b3c4d5e6_uniq_frp_tunnel_visitor_port` (Server) und `b1a2c3d4e5f6_uniq_template_assignment` (Monitoring) — die bestehenden Smoke-Tests bleiben; doppelte Aussagen werden nicht entfernt (Historie), aber der neue Test ist der, der `insert_into` nutzt.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_alembic_builtin.py   und   bash scripts/dev/verify.sh monitoring --strict -- tests/test_alembic_builtin.py
Doku: keine (intern)
Abhängt von: T1
Ergebnis: **je `5 passed`** (Server und Monitoring, mit gesetztem `DATABASE_URL` gegen die Lane-DB) — die vier eingebauten Tests plus je ein Seed-Test. Ohne `DATABASE_URL` skippen sie; `run.sh` traegt den Skip jetzt in `test_skip_is_required`, damit CI sie nicht stumm ueberspringt.

**Die Fixtures liegen in den Testdateien, nicht in conftest.py** (Abweichung von der Vorlage): `alembic_engine` muss auf eine **leere** Datenbank zeigen, waehrend die vorhandene `pg_engine`-Fixture des Servers alle Tabellen vorab anlegt. Zwei Fixtures dieses Namens in einem Paket waeren eine Falle fuer den Test, der die falsche erwischt.

**Gefundene Falle (kostete zwei Anlaeufe):** Eine Engine zu uebergeben genuegt nicht — `alembic/env.py` liest `app.core.config.DATABASE_URL` zur Ausfuehrungszeit und oeffnet seine EIGENE Verbindung. Ohne Patch dieses Attributs migriert die Kette in die konfigurierte Datenbank, waehrend die Testengine auf eine leere schaut (`NoSuchTableError: servers`). Der Migrations-Smoke dokumentiert genau das, in einem Kommentar, den ich erst nach dem Fehlschlag gelesen habe.

Die Seed-Tests pruefen, was auf einer leeren Tabelle unsichtbar bleibt: bei `f1a2b3c4d5e6` behaelt der **aeltere** Tunnel seinen `visitor_port` (der juengere verliert ihn), bei `b1a2c3d4e5f6` ueberlebt die **lexikografisch kleinere** Assignment-Id — beides Entscheidungen der Daten-Migrationen, und beide Migrationen existieren, weil ihr Fehlschlag den Container in eine Crash-Schleife schickt.

## E — Doku

### T11 — Doku  [x]
Komponente: docs · Dateien: DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Änderung: DEVELOPMENT.md Absatz „Generatoren" (Schritt `schemathesis`, `AH_SCHEMATHESIS_EXAMPLES`, Ausschlussliste, Hypothesis-Pins und `.hypothesis/`, Concurrency-Gatter); cicd.html DE+EN eine Tabellenzeile im Gate-Abschnitt; CHANGELOG Unreleased/Added.
Verify: python3 scripts/dev/doc-smoke.py --strict   und   bash scripts/tests/run.sh lint --strict --only scripts
Doku: alle genannten
Abhängt von: T2
Ergebnis: `doc-smoke: documentation matches the tree`. DEVELOPMENT.md bekommt einen eigenen Abschnitt „Generatoren" (Schritt, Beispielzahlen 5/20/100, Ausschlussliste samt Id-Pruefung, `.hypothesis/`, `derandomize`, die Postgres-Gatter); `cicd.html` DE+EN je eine Zeile in der Gate-Tabelle; CHANGELOG unter Unreleased/Added.

### T12 — Nachbesserung aus dem PR-Review (#29)  [x]
**Korrektur einer Begruendung, die mehrfach falsch im Ledger stand:** `pytest-randomly` ist in diesem Repo **nirgends installiert** (weder in einer `requirements-dev.txt` noch im Lane-venv). `-p no:randomly` war in allen Laeufen wirkungslos — pytest ignoriert das Flag fuer ein Plugin, das es nicht gibt. Die beobachtete Flakiness kam von **Hypothesis' eigenem Seed**, und genau den fixiert `derandomize=True`. Aufgefallen beim Nachdenken ueber den CI-Job: die geplante Absicherung `-p no:randomly` dort waere eine Zeile gegen ein Problem gewesen, das es nicht gibt.

Komponente: apps/server · Dateien: apps/server/tests/test_schemathesis.py, apps/server/tests/schemathesis_exclude.toml
Verify: bash scripts/dev/verify.sh server --strict
Doku: T11-Stellen mitgezogen

**Blocker: Die Ausschluesse waren operations-, nicht check-granular.** `schema.exclude(operation_id=…)` nimmt eine Operation aus **allen sechs** Checks. 17 der 27 Eintraege standen nur wegen `negative_data_rejection` da — und haben damit `not_a_server_error` auf `POST /api/users`, `POST`/`PUT /api/servers`, den Tunnel- und Connection-Routen stummgeschaltet. Genau die Schreibrouten, auf denen die 500er-Klasse sitzt. Ein frueherer Review hatte das angemerkt; ich hatte es als Entscheidungsvorlage abgelegt statt es zu beheben.

**Umbau:** Jeder Eintrag traegt jetzt entweder `checks = [...]` (die Route antwortet, ein Check hat an der Antwort etwas auszusetzen — nur dieser wird gewaehrt, die Operation bleibt im Lauf) oder `raises = true` (der Aufruf stirbt an einer ungefangenen Exception, bevor eine Response entsteht — dann kann kein Check greifen, und nur hier ist der Ausschluss der ganzen Operation ehrlich). Der Loader wirft bei einem Eintrag ohne beides, bei einem unbekannten Check-Namen und bei einer `operation_id`, die das Schema nicht kennt.

**Was der Umbau freigelegt hat** — 19 Treffer, die vorher unsichtbar waren, darunter **zwei neue Produktfehler**:

| Fund | Beleg |
|---|---|
| `_validate_tags` (frp/schemas.py:65) laeuft als `field_validator(mode="before")` und sieht **rohe** Werte: `t.strip()` auf dict/int/None wirft `AttributeError`, `for t in tags` auf einem bool wirft `TypeError` — ungefangen, also **HTTP 500 statt 422** | unabhaengig reproduziert: `[{"a":1}]`, `[1]`, `[None]`, `True` je ungefangen. **EIN Bug, sechs Routen** — derselbe Validator ist in `ansible`-, `frp`- und `servers`-Schemas je zweimal registriert |
| `POST /api/connections` mit einer `server_id`, zu der es keinen Server gibt ⇒ `ForeignKeyViolation`, ungefangen ⇒ **HTTP 500** | aus dem Lauf vom 2026-09-21 |

Dazu ein Testinfrastruktur-Befund ohne Produktbezug: `POST /api/monitoring/agent/{server_id}/report` laeuft ueber einen prozessweiten `httpx`-Client, den der Lifespan-Shutdown schliesst — danach stirbt jeder weitere Aufruf im Transport. In-process nicht fuzzbar, wie `/templates/tag-sync` auf der Monitoring-Seite.

**Stand:** `260 passed in 4:12`, 27 Eintraege (13 `raises`, 14 check-granular). `verify.sh server --strict` gruen.

### T13 — Der Schritt lief nirgends in CI  [x]
Komponente: .github/workflows, scripts/tests, apps/server · Dateien: .github/workflows/ci.yml, scripts/tests/run.sh, apps/server/tests/schemathesis_exclude.toml, DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Verify: bash scripts/dev/verify.sh server --strict
Doku: die vier Stellen, die „20 im PR-CI" behaupteten

**Blocker, den ich selbst verursacht hatte:** Ich hatte hier und im PR geschrieben, der CI fahre die Suite mit 20 Beispielen. Das war **falsch**. Die drei pytest-Jobs setzten zwar `AH_SCHEMATHESIS_EXAMPLES: "20"`, wählen den Marker aber mit `-m "not schemathesis"` ab — die Variable stand in Jobs, die die Suite nie ausführen. Der Schritt lief in **keinem** CI-Lauf. Die Doku beschrieb an vier Stellen einen Zustand, den es nicht gab.

**Entscheidung (Kevin, Option A):** ein **eigener Job** statt der Suite in den drei bestehenden. Begründung: eigenes Budget (20 min, ein Postgres-Service für alle drei Dienste), eigenes Verdikt — ein rotes „Schema fuzzing" sagt „eine Route antwortet etwas, das ihr Schema nicht beschreibt", statt in einer fremden Suite unterzugehen; und ein Job, der alle drei Dienste in **einem** `run.sh`-Aufruf fährt, kann nicht auseinanderdriften. Der Preis ist ein vierter Postgres-Service im PR-CI.

**Beispielzahl 5, nicht 20.** Ursprünglich waren 20 geplant. Dagegen spricht: eine andere Beispielzahl durchsucht eine **andere** Datenmenge — ein CI, das rot wird, wo lokal alles grün ist, und dessen Fund niemand ohne Env-Variable nachstellt. Tiefe ist die Aufgabe des Wochenlaufs (100, `heavy.sh`). Der PR-CI prüft dasselbe wie die Entwicklerin.

**Die CI-Simulation war beim ersten Anlauf rot und hat zwei echte Probleme gefunden:**

| Problem | Ursache | Fix |
|---|---|---|
| `GET /api/audit` mit NUL-Byte im Query-Parameter ⇒ **HTTP 500** | `psycopg.DataError` aus dem Treiber, ungefangen — dieselbe Klasse wie auf `/api/enrollment/token/for`, andere Route | Eintrag mit `raises = true`; Produktfehler als Roadmap-Kandidat im PR |
| `DATABASE_URL` erreichte die Monitoring-Suite | Der CI-Job exportiert es global (der Server braucht es); `run.sh` ließ es für die anderen Dienste nur *ungesetzt*, statt es zu **entfernen** | `unset DATABASE_URL` je Dienst außer `apps/server` |

Der zweite Punkt ist der wichtigere: Monitoring ist per Design eine SQLite-Suite, und ein geerbtes `DATABASE_URL` hätte sie still gegen ein Postgres gefahren, für das sie nicht geschrieben ist.

**Siebter Produktfund, beim Gate-Lauf dieser Task:** `POST /api/notifications/read` mit einer Id jenseits von BIGINT im **Request-Body** ⇒ HTTP 500. `notifications/router.py:90` reicht `data.ids` ungeprüft in `Notification.id.in_()`, Postgres lehnt den Parameter ab (`NumericValueOutOfRange`), ungefangen. Unabhängig reproduziert ohne Testfixtures: `2**63-1` wird akzeptiert, `2**63` und `-(2**63)-1` nicht. Damit ist die Randvalidierungs-Lücke auf **allen drei** Eingangswegen belegt — Pfadparameter (`user_id`), Query (`skip`/`limit`), Body (`ids`). Eintrag mit `raises = true`.

**Korrektur zweier Begründungen, die falsch im Ledger standen:**
1. `pytest-randomly` ist in diesem Repo **nirgends installiert**. `-p no:randomly` war in allen Läufen wirkungslos — pytest ignoriert das Flag für ein Plugin, das es nicht gibt.
2. „`derandomize=True` macht jeden Lauf zum selben Lauf" ist **zu stark**. Belegt ist: derselbe Baum und dieselbe Auswahl liefern dieselben Daten (zwei Läufe hintereinander, `252 passed` in 238 s und 234 s). Aber Hypothesis 6.168 speist zusätzlich die **Literale der geladenen Quelldateien** in die Generierung ein (Cache je Datei unter `.hypothesis/constants/`, nachgesehen: er enthält die Strings der jeweiligen Modul-Quelle). Deshalb fand derselbe Testsatz den `2**63`-Fall im vollen Lauf und nicht bei einem `-k`-Lauf derselben Operation. **Ein Lauf auf einem geänderten Baum ist eine neue Suche, kein Nachlauf der alten** — das erklärt die „spontanen" Funde besser als jede Seed-Erzählung. Welcher Anteil daran genau welchen Wert erzeugt hat, ist nicht nachgemessen.

**Stand:** `bash scripts/dev/verify.sh server --strict` → `run.sh[quick]: 4 passed, 0 failed, 13 skipped, 2 test-skips, 0 reruns` (server pytest `543 passed, 2 skipped, 2 xfailed`, schemathesis `252 passed`). Der exakte CI-Befehl zuvor lokal simuliert: `256 passed` (server, vor dem siebten Fund) · `111 passed` (monitoring) · `9 passed` (ca-issuer), zusammen 4:46 — im 20-Minuten-Budget.

### T14 — Die Hypothesis-Ziele hingen nicht am Seed  [x]
Komponente: apps/server, apps/monitoring · Dateien: apps/server/tests/conftest.py, apps/monitoring/tests/conftest.py, DEVELOPMENT.md, docs/features/harness-stufe-8b.md
Verify: bash scripts/tests/run.sh quick --strict --only monitoring ca-issuer scripts
Doku: DEVELOPMENT.md nennt das Profil; zwei „Beim Bau abgewichen"-Zeilen in der Spec

DEVELOPMENT.md behauptete „Die Suiten laufen `derandomize`" — das galt nur für die drei **Schemathesis**-Suiten, die es je Test setzen. Die drei **Hypothesis**-Ziele (FRP-TOML, Line-Protocol, SSRF) zogen bei jedem Lauf einen neuen Seed. Aus der Aufsicht als WICHTIG gemeldet; ich mache die Doku-Aussage wahr, statt sie abzuschwächen.

Umsetzung als **Profil** (`register_profile("gate", derandomize=True)` + `load_profile`) in der jeweiligen `conftest.py`, nicht als 17 einzelne Decorator-Argumente: die Test-eigenen `@settings` setzen nur `max_examples`/`deadline` und erben den Rest vom geladenen Profil. Nachgewiesen: alle sechs SSRF-Tests melden `derandomize=True` bei unverändertem `max_examples` (10/100/200/300).

Der Block steht **hinter** den Imports. Davor kostete er 20 × E402: Ruff duldet vor den Imports nur `os.environ`-Mutationen, und ein `register_profile()` dort färbt jeden folgenden Import rot.

**Abweichungen zur Spec** (dort als „Beim Bau abgewichen" vermerkt, statt den Plan still umzuschreiben): das Profil heißt `gate` statt `ci` und ist **immer** aktiv, nicht nur in CI — ein Profil, das nur in CI derandomisiert, erzeugt genau den Fund, den lokal niemand nachstellt. Und die geplante `deadline` von 200 ms je Beispiel gibt es nicht: eine Deadline macht aus einem *langsamen* Beispiel ein *fehlgeschlagenes* und misst auf einer Box mit paralleler Lane die Last statt den Code; begrenzt wird über `max_examples`.

### T15 — Derselbe Fund in Monitoring, und eine Zusage, die dort nicht galt  [x]
Komponente: apps/monitoring · Dateien: apps/monitoring/tests/schemathesis_exclude.toml, apps/monitoring/tests/test_schemathesis.py
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: keine — DEVELOPMENT.md beschrieb bereits den Zustand, den diese Task herstellt

**Achter Fund, dieselbe Klasse, anderer Dienst:** `GET /checks?offset=9223372036854775808` ⇒ HTTP 500. `routers/checks.py:112` deklariert `offset: int = Query(0, ge=0)` — eine **untere** Schranke ohne obere; der Wert geht ungeprüft in LIMIT/OFFSET. Unter SQLite (Testumgebung) `OverflowError: Python int too large to convert to SQLite INTEGER`, unter Postgres (Produktion) `NumericValueOutOfRange` — beides ungefangen. Dieselbe Deklaration steht an drei Stellen (`checks.py:112`, `checks.py:325`, `alerts.py:29`). Eintrag mit `raises = true`.

**Die Doku versprach für alle Dienste etwas, das nur zwei taten.** DEVELOPMENT.md: „Der Test prüft jede `operation_id` gegen das Schema: ein Tippfehler dort schließt nichts aus und sagt nichts, also ist er ein Fehler." Server und CA-Issuer taten das, **Monitoring nicht** — dort war die Liste ungeprüft, ein Tippfehler hätte still nichts ausgeschlossen. Nachgezogen (`_KNOWN_IDS` aus demselben `_RAW_SCHEMA`, das die Suite fuzzt; eine unbekannte Id ist ein `ValueError` beim Import). Gegenprobe gefahren: die zwei echten Ids treffen beide etwas, der Mutant `list_checks_checks_gett` wird als unbekannt gemeldet.

Das ist dieselbe Sorte Fund wie T14 — nicht der Code war falsch, sondern die Zusage über ihn. Beide standen seit T11 in der Doku.

**Stand:** `bash scripts/dev/verify.sh monitoring --strict` → `run.sh[quick]: 4 passed, 0 failed, 13 skipped, 10 test-skips, 0 reruns`; `… ca-issuer --strict` → `4 passed, 0 failed, 13 skipped, 0 test-skips, 0 reruns`.

### T16 — Das SSRF-Orakel holte seine Antwort aus dem Geprüften  [x]
Komponente: apps/server, apps/monitoring · Dateien: apps/server/tests/test_ssrf_properties.py, apps/server/tests/test_schemathesis.py, apps/monitoring/tests/test_schemathesis.py, apps/server/tests/test_alembic_builtin.py, apps/monitoring/tests/test_alembic_builtin.py, apps/monitoring/tests/test_check_engine_concurrency.py
Verify: bash scripts/dev/verify.sh server --strict · bash scripts/dev/verify.sh monitoring --strict
Doku: keine (Testinterna)

**WICHTIG 6:** `_oracle_is_private` importierte `_BLOCKED_NETWORKS` aus `app.core.ssrf` — also aus genau dem Code, den es prüfen soll. Ein Orakel, das seine Antwort vom Prüfling bezieht, stimmt mit ihm **konstruktionsbedingt** überein, auch wenn der Prüfling falsch ist: hätte jemand `100.64.0.0/10` aus der Sperrliste genommen, wäre die Suite grün geblieben. Die beiden Netze stehen jetzt als Literale im Test (`0.0.0.0/8`, CGNAT) — sie sind das, was der Guard über die `ipaddress`-Kategorien hinaus sperrt, und diese Politik ist das, was der Test festnagelt.

**Gegenprobe gefahren** (Mutation an der Implementierung, per Text zurückgesetzt, kein `git checkout`): CGNAT aus `_BLOCKED_NETWORKS` entfernt ⇒ `2 failed, 5 passed` (`test_verdict_matches_the_ipaddress_categories`, `test_one_private_address_among_many_is_enough`); zurückgesetzt ⇒ `7 passed`. Vorher hätte dieselbe Mutation **nichts** ausgelöst.

**NIT 8:** Drei Postgres-gegatterte Suiten sprangen nur ab, wenn `DATABASE_URL` *leer* war. Ein `DATABASE_URL` auf SQLite hätte sie **laufen** lassen — und `FOR UPDATE` ist dort ein No-op, der Concurrency-Test hätte grün gemeldet, ohne je ein Lock geprüft zu haben. Das ist genau die Lücke, wegen der es den Test gibt. Gate jetzt `not DB_URL.startswith("postgres")` in beiden `test_alembic_builtin.py` und in `test_check_engine_concurrency.py`.

**NIT 9:** `app.dependency_overrides.clear()` in den Schemathesis-Fixtures räumt **jeden** Override der App weg, auch den einer Nachbar-Fixture. Jetzt `pop(get_db, None)` — zurückgenommen wird nur, was diese Fixture gesetzt hat.

**Stand:** `verify.sh server --strict` → `4 passed, 0 failed, 13 skipped, 2 test-skips, 0 reruns` (`543 passed, 2 skipped, 2 xfailed` + `252 passed` schemathesis); `verify.sh monitoring --strict` → `4 passed, 0 failed, 13 skipped, 10 test-skips, 0 reruns` (`468 passed, 10 skipped` + `108 passed`); `verify.sh ca-issuer --strict` → `4 passed, 0 failed`; `verify.sh scripts --strict` → `5 passed, 0 failed, 12 skipped`.

**Offen aus der Aufsicht:** WICHTIG 5 — adminhelper-04 schlägt einen Test `exclusions_still_hold` vor, der je `raises`-Eintrag prüft, ob der Ausschluss noch nötig ist. In der vorgeschlagenen Form (ein beliebiges Beispiel, das sterben soll) wäre er sofort rot: ein `raises`-Eintrag heisst „stirbt bei **bestimmten** Eingaben", nicht „stirbt immer". Tragfähig wäre eine gespeicherte Probe je Eintrag (Schemathesis druckt sie als `Reproduce with: curl …`), dann meldet sich ein obsolet gewordener Ausschluss von selbst. Das ist eine eigene Task — Vorschlag für die Roadmap, nicht für diesen PR.

## Abschluss
- `bash scripts/tests/run.sh quick --strict` grün (mit dem neuen Schritt); `bash scripts/dev/verify.sh all --strict` grün.
- Mutanten-Gegenproben aus der Spec im Wegwerf-Worktree, Ergebnis in den PR-Body.
- Erstlauf-Funde (Schemathesis) als Roadmap-Kandidaten im PR-Body; Ausschlüsse mit Grund in den TOML-Dateien.
