<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Fehlervertrag Server → Clients: `code` neben `detail`, strukturierte Fehler über die Desktop-IPC — Task-Ledger
Status: erledigt · Branch: feature/fehlervertrag · Review: pro Task
Spec: docs/features/fehlervertrag.md (Roadmap R-0664, R-0662, R-0709; Kevin 2026-10-22: optionales Feld `code` ja)
Heavy: linux-full + scenario --agents 0 --desktop --enforce + windows — linux-full: Server-API (die 403 der Zertifikatsprüfung tragen `code`; `scripts/tests/integration_stack_test.sh:218` prüft 403 `ERR_CERT_REVOKED` am Stack) und jede Desktop-Journey (jeder Command-Fehler kommt als `{code, message, status?}` über die IPC; Login-, Trust- und Proxy-Fehler, `enroll-trust-dialog.live.js`, `logout.live.js:69`); scenario `--desktop --enforce`: Anmeldung und Registrierung des echten Desktops gegen erzwungenes mTLS mit den Zertifikatscodes und `ERR_MTLS_CERT_REQUIRED`, dazu Desktop-Enrollment (`revoked_by`, CLAUDE.md §5), bleibt ask-first; windows: die CI-Jobs (der Pool hat keine Windows-Vorlage), der Fehlertyp ist plattformunabhängig, kein `cfg(windows)`-Code
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Hängt ab von: Vorhaben, die dieselben Dateien ändern; erst nach deren Merge bauen und `origin/main` hineinmergen.
Teil A (T1–T3): server-hardening (`apps/server/app/main.py`, dort T1/T3; `docs/{,en/}developer/api-reference.html`,
dort T6), audit-coverage (`api-reference.html`, dort T9), agent-hardening (`api-reference.html` im Branch-Diff),
auth-sessions (`api-reference.html` T3/T5; `apps/web/src/lib/api/client.ts` T6; `apps/web/src/lib/api/types.ts` T7/T9;
`docs/{,en/}developer/webui.html` T6/T8), web-fixes (PR #261: `client.ts`, `client.test.ts`). Teil B (T4–T13):
desktop-hardening-2 (`apps/desktop/ui/src/lib/bridge/index.ts` T5; `docs/{,en/}developer/desktop.html` T2–T5),
desktop-blocking (`apps/desktop/src-tauri/src/tofu.rs` T9, `enrollment.rs` T8, `desktop.html` T4). Überall
`CHANGELOG.md`. `commands.rs` ändert dieses Vorhaben nicht; neue Commands der beiden Desktop-Vorhaben liefern
`AppError` und bekommen die neue Form von selbst. Teil A und Teil B hängen nicht voneinander ab; der Teil, dessen
Vorgänger zuerst gemergt sind, darf zuerst bauen. Zeilenangaben gelten für `origin/main@237b450a` und werden beim
Baustart neu gegreppt.

Ziel: (1) Der Server liefert bei einem Fehler, auf den ein Client reagieren soll, `{"detail": …, "code": "ERR_…"}`;
`detail` bleibt wörtlich (alte Clients). (2) Das Web trägt `code` in `ApiError` und zeigt den Text ohne `ERR_…: `.
(3) Ein Command des Desktops lehnt mit `{code, message, status?}` ab (Form und Codes: Spec, „Desktop-IPC“); Nicht-2xx
des Proxys und der Anmeldung tragen Status, Server-Code und den Text aus `detail`. (4) Die Desktop-UI verzweigt nur
noch an `errCode(err)`/`errStatus(err)`, nie am Text.

Für alle Tasks:
- Reihenfolge: T1 → T2; T3 frei. T4 → T5 → T6 → T7 → T8 → T9; T10 nach T4, T5, T7; T11 nach T10; T12 nach T4, T6;
  T13 nach T4, T5. T4 vor T5, weil die UI vor T4 eine Objekt-Ablehnung als „[object Object]“ zeigte; T10–T13 nach
  Rust, damit jeder Commit lauffähig bleibt.
- Ein Code hat überall die Form `^ERR_[A-Z0-9_]{1,64}$` (Server-Konstanten, Web T3, Rust T6).
- Risikopfade (`scripts/dev/review-risk.txt`): T2 (`identity.py`), T5 (`tofu.rs`), T7 (`auth.rs`), T8 und T9
  (`enrollment.rs`) bekommen zusätzlich `security`.
- Neue Code-Strings (Kommentare, Fallback-Texte) englisch; bestehende deutsche Texte bleiben.
- Platzhalter: Hosts unter `.example`, Adressen aus RFC 5737.
- Nach dem Hereinmergen von `origin/main` mit einem der Vorgänger den ganzen Testordner der gemeinsamen Komponente
  fahren (server, web, desktop-rs, desktop-ui), nicht nur das `Verify:` der Task.

## Teil A — Server und Web

### T1 — Server: `CodedHTTPException` schreibt `code` neben `detail` (R-0664)  [x]
Komponente: server · Dateien: apps/server/app/core/errors.py, apps/server/app/main.py, apps/server/tests/test_error_code.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @588130f9 2026-10-29T12:58:27+01:00
Review: approve (.ah-out/review/fehlervertrag/T1.verdict.json)
Änderung: Neues Modul `apps/server/app/core/errors.py` (SPDX per `reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later`): `CodedHTTPException(HTTPException)` mit `__init__(self, status_code: int, detail: str, code: str, headers: dict[str, str] | None = None)` und Attribut `code`; ein Handler schreibt `JSONResponse({"detail": exc.detail, "code": exc.code}, status_code=exc.status_code, headers=exc.headers)`; `install_coded_errors(app: FastAPI) -> None` registriert ihn per `app.add_exception_handler`, wie `install_exact_int_bounds` (`apps/server/app/core/openapi.py:36`). `apps/server/app/main.py` ruft `install_coded_errors(app)` neben `install_exact_int_bounds(app)` (`:390`). Ein Kommentar nennt das Warum: `detail` bleibt der Text, den bestehende Clients lesen, `code` ist für den Code der Clients. Starlette 1.3.1 sucht den Handler entlang der MRO (`starlette/_exception_handler.py:16-20`), jede andere `HTTPException` bleibt beim Standard-Handler. Neue `apps/server/tests/test_error_code.py` (SPDX) mit eigener `FastAPI()`-App, `install_coded_errors` und `TestClient`: (a) eine Route wirft `CodedHTTPException(403, "ERR_PROBE: prose", "ERR_PROBE", headers={"X-Probe": "1"})` → Status 403, `resp.json() == {"detail": "ERR_PROBE: prose", "code": "ERR_PROBE"}`, Header `X-Probe: 1`; (b) eine Route wirft `HTTPException(404, "missing")` → `resp.json() == {"detail": "missing"}`; (c) ein 422 dieser App hat kein `code`; (d) `app.main.app` hat für `CodedHTTPException` genau diesen Handler. `tests/test_openapi_snapshot.py` bleibt unverändert grün (kein Schema ändert sich). Zuerst rot: (a)–(d) auf HEAD (das Modul fehlt).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_error_code.py tests/test_openapi_snapshot.py
Doku: keine (die Antwortform beschreibt T2 mit den ersten Codes)
Orakel: contract — Body eines `CodedHTTPException` genau `{detail, code}`, jeder andere Fehler ohne `code`
Dedup-Key: ref:server:identity.py:no-structured-error-code
HEAD: 237b450a

### T2 — Server: die 403 der Zertifikatsprüfung tragen `code` (R-0664)  [x]
Komponente: server · Dateien: apps/server/app/core/identity.py, apps/server/tests/test_certificate_check.py, apps/server/tests/test_cert_user_binding.py, apps/server/tests/test_mtls_scope.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @8a695c88 2026-10-29T13:05:58+01:00
Review: approve (.ah-out/review/fehlervertrag/T2.verdict.json)
Änderung: `apps/server/app/core/identity.py`: die drei Codes als eigene Konstanten neben den Texten `CERT_USER_MISMATCH`, `CERT_SERVER_MISMATCH`, `CERT_REVOKED` (`:108-128`); deren Wortlaut bleibt (bestehende Clients lesen den Präfix: `apps/desktop/src-tauri/src/enrollment.rs:443-446`, `apps/desktop/ui/src/components/Login.svelte:79-82`). Die drei `raise` (`:153`, `:172`, `:225`) werfen `CodedHTTPException(403, <Text>, <Code>)` aus T1. Die Kommentare `:108-109` und `:123-124` nennen das Feld `code` statt des Präfixes als das, woran ein Client verzweigt. Tests: `_assert_revoked` (`tests/test_certificate_check.py:94-96`) und `_assert_mismatch` (`tests/test_cert_user_binding.py:39-41`) prüfen zusätzlich `resp.json()["code"]`; `tests/test_mtls_scope.py:354` und `:392` ebenso mit `ERR_CERT_SERVER_MISMATCH`; die Stream-Tests, die die Exception direkt fangen (`test_certificate_check.py:311-314`, `test_cert_user_binding.py:164-167`), prüfen `exc.value.code`. Je Code ein Test pinnt den ganzen Body: `resp.json() == {"detail": <Text wörtlich wie identity.py:110-113, :117-120 bzw. :125-128 auf 237b450a>, "code": <Code>}`. Zuerst rot: die `code`-Prüfungen auf HEAD (`KeyError`).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_certificate_check.py tests/test_cert_user_binding.py tests/test_mtls_scope.py tests/test_openapi_snapshot.py
Doku: docs/developer/api-reference.html + docs/en/developer/api-reference.html („Fehler-Format“, nach dem Absatz `:222`: ein Fehler, auf den ein Client reagieren soll, trägt zusätzlich `code`, stabil, Form `ERR_…`; `detail` bleibt Text und beginnt aus Kompatibilität mit `<code>: `; heute die 403 `ERR_CERT_REVOKED`, `ERR_CERT_USER_MISMATCH`, `ERR_CERT_SERVER_MISMATCH`; Clients verzweigen an `code`, nie am Text; ein Beispiel-Body) · CHANGELOG.md (Added, umlautfrei: Fehlerantworten tragen ein optionales Feld `code` neben `detail`, heute die 403 der Zertifikatspruefung; `detail` bleibt unveraendert)
Abhängt von: T1
Orakel: contract — der ganze Body je Code, `detail` byte-gleich zu HEAD
Dedup-Key: ref:server:identity.py:no-structured-error-code
HEAD: 237b450a

### T3 — Web: `ApiError.code`, Meldung ohne `ERR_…: ` (R-0664)  [x]
Komponente: web · Dateien: apps/web/src/lib/api/client.ts, apps/web/src/lib/api/types.ts, apps/web/src/lib/api/client.test.ts, docs/developer/webui.html, docs/en/developer/webui.html, CHANGELOG.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @cceb4d6a 2026-10-29T13:10:35+01:00
Review: approve (.ah-out/review/fehlervertrag/T3.verdict.json)
Änderung: `ApiError` (`apps/web/src/lib/api/types.ts:68-78`) bekommt `readonly code: string | undefined` und den vierten Konstruktor-Parameter `code?: string`. In `request` (`apps/web/src/lib/api/client.ts:116-119`): `code` nur, wenn der Body ein `code` als String der Form `^ERR_[A-Z0-9_]{1,64}$` trägt; die Meldung ist `errorDetail(data)` (`:126-140`), bei gesetztem `code` ohne das führende `${code}: `, sonst wie heute; `throw new ApiError(res.status, <Meldung> ?? `HTTP ${res.status}`, data, code)`. Tests im Block `http client error messages` (`client.test.ts:351-394`), `messageOf` liefert dafür den ganzen Fehler: (a) 403 `{detail: 'ERR_CERT_REVOKED: This device certificate is no longer valid.', code: 'ERR_CERT_REVOKED'}` → Meldung ohne Präfix, `code` `'ERR_CERT_REVOKED'`, `status` 403; (b) derselbe Body ohne `code` (Server vor T2) → Meldung mit Präfix wie heute, `code` undefined; (c) `code` `'err_x'`, `42` und ein Code mit 65 Zeichen nach `ERR_` → `code` undefined, Meldung unverändert; (d) `code` gesetzt, `detail` ohne den Präfix → `detail` unverändert; (e) eine 422-Liste mit `code` → die `msg`-Texte wie heute (`:368-385`). Zuerst rot: (a) auf HEAD.
Verify: bash scripts/dev/verify.sh web --strict -- src/lib/api/client.test.ts
Doku: docs/developer/webui.html + docs/en/developer/webui.html (`:79`, ein Satz: ein Nicht-2xx wirft `ApiError(status, message, detail, code)`; `message` ist `detail`, bei 422 die `msg`-Texte, ohne `<code>: `, wenn der Server `code` schickt; `code` ist für den Code, nicht für den Text) · CHANGELOG.md (Changed, umlautfrei: das Web zeigt bei einem Fehler mit Maschinencode den Text ohne das Praefix `ERR_…:`)
Orakel: contract — `code` und Meldung gegen die Antwortform aus T2
Dedup-Key: ref:server:identity.py:no-structured-error-code
HEAD: 237b450a

## Teil B — Desktop

### T4 — Desktop-UI: die Bridge macht aus jeder Ablehnung ein `Error`, `IpcError` mit Code und Status (R-0709)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/utils/errors.ts, apps/desktop/ui/src/lib/utils/errors.test.ts, apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/lib/bridge/invoke.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @13273c5b 2026-10-29T13:18:48+01:00
Review: approve (.ah-out/review/fehlervertrag/T4.verdict.json)
Änderung: `apps/desktop/ui/src/lib/utils/errors.ts`: `export class IpcError extends Error` (`name = 'IpcError'`, `readonly code: string | undefined`, `readonly status: number | undefined`); `export function fromIpc(raw: unknown): Error` — ein Objekt mit String-`code` und String-`message` wird `IpcError(message, code, status)`, `status` nur als Ganzzahl 100–599; ein String (Tauris eigene Fehler, tauri 2.11.5 `src/ipc/mod.rs:249-253`) wird `Error(raw)`; ein `Error` bleibt; alles andere wird ein `Error`, dessen Meldung nicht „[object Object]“ ist (JSON des Werts, gekürzt). `errCode(err)`/`errStatus(err)` lesen `code`/`status` eines `IpcError`, sonst `undefined`. `errMsg`, `errRaw`, `withoutErrorCodes` bleiben. `apps/desktop/ui/src/lib/bridge/index.ts:16`: `invoke` aus `@tauri-apps/api/core` als `tauriInvoke` importieren; eine lokale `invoke<T>(cmd, args?)` ruft sie und wirft bei einer Ablehnung `fromIpc(raw)`; die 40 Aufrufe `invoke<…>('…')` bleiben wörtlich, damit `ipc.inventory.test.ts` (`:88-98`, `:108-117`) sie weiter liest. Neue `apps/desktop/ui/src/lib/bridge/invoke.test.ts` (SPDX wie `ipc.inventory.test.ts`) mit `vi.mock('@tauri-apps/api/core', …)`: (a) Ablehnung `{code: 'ERR_HTTP', message: 'Template already assigned', status: 409}` → `bridge.apiProxy('POST', '/api/x')` lehnt mit `IpcError` ab, `errMsg` `'Template already assigned'`, `errCode` `'ERR_HTTP'`, `errStatus` 409; (b) Ablehnung als String „invalid args `path` for command `api_proxy`: …“ → `Error` mit genau diesem Text, `errCode` undefined; (c) `{code: 5, message: 'x'}` und `{message: 'x'}` → kein `IpcError`, keine Meldung „[object Object]“; (d) `status` `'409'` oder `42` → `errStatus` undefined. `errors.test.ts`: `errCode`/`errStatus` für `IpcError`, `Error` und String. Zuerst rot: (a) und (b) auf HEAD (die Ablehnung kommt roh durch).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/bridge src/lib/utils/errors.test.ts
Doku: keine (intern; die Form beschreibt T5)
Orakel: contract — Ablehnung als Objekt und als String gegen `IpcError`/`Error`
Dedup-Key: ref:desktop:error.rs:string-errors-at-ipc
HEAD: 237b450a

### T5 — Desktop-Rust: `AppError::code()`, Ablehnung als `{code, message}` (R-0709)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/error.rs, apps/desktop/src-tauri/src/tofu.rs, docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @49f8d3d0 2026-10-29T13:30:03+01:00
Review: approve (.ah-out/review/fehlervertrag/T5.verdict.json)
Änderung: `apps/desktop/src-tauri/src/error.rs`: `impl AppError { pub fn code(&self) -> &str }` — `Validation` → `ERR_VALIDATION`, `Io` → `ERR_IO`, `Connection` → `ERR_CONNECTION`, `Keyring` → `ERR_KEYRING`, `Json` → `ERR_JSON`, `SessionExpired` → `ERR_SESSION_EXPIRED`, `Network` → `ERR_TLS_UNKNOWN_ISSUER` bei `is_unknown_issuer` (`:13-37`), `ERR_TOFU_PIN_MISMATCH` bzw. `ERR_CA_PIN_MISMATCH`, wenn die Quellkette (derselbe Gang wie `is_unknown_issuer`, mit `io::Error::get_ref`) ein `rustls::Error::General` trägt, dessen Text mit `ERR_TOFU_PIN_MISMATCH: ` bzw. `ERR_CA_PIN_MISMATCH: ` beginnt (`apps/desktop/src-tauri/src/tofu.rs:271-276`, `apps/desktop/src-tauri/src/enrollment.rs:707-715`), sonst `ERR_NETWORK`. `impl Serialize` (`:95-99`) schreibt statt des Strings das Objekt `{"code": self.code(), "message": self.to_string()}` (private `#[derive(Serialize)]`-Struktur; `status` kommt mit T6). `Display` bleibt, ebenso die Tests auf den Text (`:159-182`, `:186-215`). Ein Kommentar nennt das Warum: Tauri lehnt das Promise mit genau diesem Wert ab, die UI verzweigt nur an `code`. Tests: (a) `serde_json::to_value` je Variante (`Validation`, `Io`, `Connection`, `Keyring`, `Json` aus kaputtem JSON, `SessionExpired`) ist genau `{"code": …, "message": …}`; (b) `unknown_issuer_maps_to_stable_code_and_names_the_setting` (`:159`) zusätzlich `code() == "ERR_TLS_UNKNOWN_ISSUER"` und `"code"` im Objekt; (c) `non_tls_network_errors_keep_the_raw_chain` (`:186`) zusätzlich `code() == "ERR_NETWORK"`; (d) die Kettensuche direkt: Quelle `io::Error` mit `rustls::Error::General("ERR_CA_PIN_MISMATCH: x")` → CA-Code; mit `"ERR_TOFU_PIN_MISMATCH: x"` → TOFU-Code; mit dem Text des Keyring-Falls (`tofu.rs:277-284`, ohne Code) → keiner; mit `"x ERR_CA_PIN_MISMATCH: y"` → keiner; (e) in `tofu.rs`, Modul `tls_handshake`, neben `changed_cert_is_rejected` (`:678`) ein Test mit echtem Handshake (Pin A, Server B), der den `reqwest::Error` behält: `AppError::from(err).code() == "ERR_TOFU_PIN_MISMATCH"`. Zuerst rot: (a) auf HEAD (der Wert ist ein String).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- error:: -- tofu::
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (nach der Command-Tabelle `:186`: scheitert ein Command, lehnt `invoke` mit `{code, message}` ab; die Codes wie in der Spec-Tabelle; die Bridge macht daraus `IpcError`, die UI verzweigt nur an `code`; ein Fehler von Tauri selbst kommt als Text ohne Code)
Abhängt von: T4
Orakel: contract — die Ablehnung je Variante gegen die Spec-Tabelle „Desktop-IPC“
Dedup-Key: ref:desktop:error.rs:string-errors-at-ipc
HEAD: 237b450a

### T6 — Desktop-Rust: Nicht-2xx des Proxys als `AppError::Http` mit Status, Code und Text aus `detail` (R-0662)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/error.rs, apps/desktop/src-tauri/src/proxy.rs, docs/developer/desktop.html, docs/en/developer/desktop.html, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @100a5e55 2026-10-29T13:35:50+01:00
Review: approve (.ah-out/review/fehlervertrag/T6.verdict.json)
Änderung: `error.rs`: neue Variante `Http { status: u16, code: Option<String>, message: String }`, `Display` `HTTP <status>: <message>`, `code()` der Server-Code oder `ERR_HTTP`, im Objekt der IPC zusätzlich `"status"` (nur bei `Http`, sonst fehlt das Feld). Konstruktor `AppError::http(status: u16, body: &str) -> AppError`: liest den Body als JSON; `code` nur ein String der Form `^ERR_[A-Z0-9_]{1,64}$` (ohne Regex-Crate); `detail` als String, als Liste die `msg`-Texte mit `; ` wie `errorDetail` im Web (`apps/web/src/lib/api/client.ts:132-140`); mit `code` ohne das führende `<code>: `; leer, ohne lesbaren Text oder kein JSON → `HTTP <status>`; der Text durch `crate::diagnostics::redact_body` (`apps/desktop/src-tauri/src/diagnostics.rs:108-116`). `apps/desktop/src-tauri/src/proxy.rs:69-75` gibt `AppError::http(status.as_u16(), &text)` mit dem rohen Text zurück (das Redigieren macht `http`). Tests in `error.rs` für `http`: String-`detail`; Liste; Liste ohne `msg` → `HTTP 422`; HTML-Seite → `HTTP 502`, kein `<html>`; `code` mit Präfix → Text ohne Präfix; `code` `"err_x"`, `5` und 65 Zeichen nach `ERR_` → kein Code, Text unverändert; ein JWT in `detail` → `<redacted-jwt>`. In `proxy.rs` über `serve` (`:156-172`) und `signed_in` (`:193-205`), Antworten ohne 401: (a) 409 `{"detail":"Template already assigned"}` → `serde_json::to_value(err) == {"code":"ERR_HTTP","message":"Template already assigned","status":409}`; (b) 403 `{"detail":"ERR_CERT_REVOKED: This device certificate is no longer valid.","code":"ERR_CERT_REVOKED"}` → `code` `ERR_CERT_REVOKED`, Text ohne Präfix, `status` 403; (c) 502 mit HTML → Text `HTTP 502`. Zuerst rot: (a) auf HEAD.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- error:: -- proxy::
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (der Absatz aus T5: `status` bei einer Antwort des Servers, `ERR_HTTP` oder der `code` des Servers, `message` aus `detail`) · CHANGELOG.md (Fixed, umlautfrei: die Statusleiste des Desktops zeigt bei einem Fehler des Servers dessen Text, bei 422 die Feldmeldungen, statt `HTTP <Status>: <roher Body>`; ohne lesbaren Text `HTTP <Status>`)
Abhängt von: T5
Beweis: origin/main@237b450a · Code-Lesung: `proxy.rs:69-75` baut `AppError::Validation(format!("HTTP {}: {}", …))` mit dem redigierten rohen Body, `error.rs:95-99` serialisiert `to_string()`; die UI vergleicht `msg.startsWith('HTTP 409')` (`apps/desktop/ui/src/lib/stores/infra.ts:123`, `apps/desktop/ui/src/components/monitoring/BuiltinUpdateModal.svelte:135`) und zeigt den Text in der Statusleiste (`apps/desktop/ui/src/lib/stores/statusBar.ts:39-43`). Test (a) ist auf HEAD rot (der Wert ist der String „HTTP 409: {…}“)
Orakel: contract — die Ablehnung des Proxys gegen die Spec-Tabelle „Desktop-IPC“
Dedup-Key: bug:desktop:proxy.rs:raw-error-body-to-ui
HEAD: 237b450a
Semantik: keine Stelle in docs/ beschreibt die Meldung (gesucht in `docs/developer/desktop.html`, `api_proxy` `:168`, `:178`); Maßstab `apps/desktop/ui/src/lib/api/request.ts:12` — „Behaviour mirrors apps/web/src/lib/api/client.ts“, das Web liest `detail` (`docs/developer/webui.html:79`, `client.ts:126-140`); Kevin 2026-10-22: Rust reicht Status und Code strukturiert ans UI

### T7 — Desktop-Rust: Ablehnung der Anmeldung als `Http` oder `MtlsCertRequired` (R-0709)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/error.rs, apps/desktop/src-tauri/src/auth.rs, CHANGELOG.md, docs/developer/desktop.html, docs/en/developer/desktop.html
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @82088bdf 2026-10-29T13:43:24+01:00
Review: approve (.ah-out/review/fehlervertrag/T7.verdict.json)
Änderung: `error.rs`: neue Variante `MtlsCertRequired`, `Display` der heutige Text aus `apps/desktop/src-tauri/src/auth.rs:51-54` samt Präfix, `code()` `ERR_MTLS_CERT_REQUIRED`. `login_failure` (`auth.rs:48-61`): die Gateway-Seite → `AppError::MtlsCertRequired`; jede andere Antwort → `AppError::http(status.as_u16(), body)` aus T6. Tests in `auth.rs`: `the_gateway_no_cert_page_becomes_the_stable_code` (`:254`) zusätzlich `code() == "ERR_MTLS_CERT_REQUIRED"`; statt `other_failures_keep_the_status_and_the_body` (`:264`) `other_failures_carry_status_code_and_detail`: 400 `{"detail":"bad request"}` → `Http` 400 ohne Server-Code, Text `bad request`; 401 `{"detail":"Invalid credentials"}` → 401, Text `Invalid credentials`; 403 `{"detail":"ERR_CERT_USER_MISMATCH: The client certificate belongs to another user.","code":"ERR_CERT_USER_MISMATCH"}` → `code()` `ERR_CERT_USER_MISMATCH`, Text ohne Präfix, `status` 403; 403 und 500 mit der nginx-Seite → `Http` mit Text `HTTP 403` bzw. `HTTP 500`, `code()` nicht `ERR_MTLS_CERT_REQUIRED`, kein `<html>`. `other_failures_still_redact_the_body` (`:285`) mit dem Body `{"detail":"token <jwt>"}` → `<redacted-jwt>`, kein JWT; dazu derselbe JWT als Nicht-JSON-Body → Text `HTTP 401`. Zuerst rot: der 403-Fall mit `code` auf HEAD.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- error:: -- auth::
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (IPC-Absatz: `ERR_MTLS_CERT_REQUIRED`, `login` als Quelle von `status`) · CHANGELOG.md (Changed, umlautfrei: die Anmeldung des Desktops zeigt bei einer Ablehnung den Text des Servers statt `Login fehlgeschlagen (<Status>): <roher Body>`)
Abhängt von: T6
Test-Löschung: apps/desktop/src-tauri/src/auth.rs::other_failures_keep_the_status_and_the_body — ersetzt durch other_failures_carry_status_code_and_detail im selben Commit: Status und Code reisen strukturiert statt im Text (gewollte Änderung, R-0662/R-0709, Kevin 2026-10-22)
Orakel: contract — die Ablehnung der Anmeldung gegen die Spec-Tabelle „Desktop-IPC“
Dedup-Key: ref:desktop:error.rs:string-errors-at-ipc
HEAD: 237b450a

### T8 — Desktop-Rust: `revoked_by` liest `code`, nicht den Body-Text (R-0709)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/enrollment.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @b5480ded 2026-10-29T13:46:21+01:00
Review: approve (.ah-out/review/fehlervertrag/T8.verdict.json)
Änderung: `revoked_by` (`apps/desktop/src-tauri/src/enrollment.rs:443-446`): ein 403 zählt als „schon widerrufen“ nur, wenn `AppError::http(403, body).code() == "ERR_CERT_REVOKED"`, also das Feld `code` des Bodys, nicht mehr ein `ERR_CERT_REVOKED` irgendwo im Text. Test `the_server_answer_counts_as_revoked_when_done_or_already_refused` (`:1115-1127`): es bleiben 204 → wahr, 403 `{"detail":"Kein gültiges Client-Zertifikat"}` → falsch, 409 und 502 → falsch; neu 403 `{"detail":"ERR_CERT_REVOKED: no longer valid","code":"ERR_CERT_REVOKED"}` → wahr und 403 `{"detail":"server ERR_CERT_REVOKED","code":"ERR_CERT_USER_MISMATCH"}` → falsch; der Fall 403 `{"detail":"ERR_CERT_REVOKED: no longer valid"}` ohne `code` (`:1117-1120`) wird falsch (gewollt: nur `code` zählt, Kevin 2026-10-22; den Rückfall für Server ohne `code` entscheidet T9). Zuerst rot: der Fall mit `code` `ERR_CERT_USER_MISMATCH` auf HEAD (wahr).
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- enrollment::
Doku: keine (gegen einen Server mit T2 unverändert)
Abhängt von: T6
Beweis: origin/main@237b450a · Code-Lesung `enrollment.rs:445` `body.contains("ERR_CERT_REVOKED")`: 403 `{"detail":"server ERR_CERT_REVOKED","code":"ERR_CERT_USER_MISMATCH"}` zählt als widerrufen; der neue Fall ist auf HEAD rot
Orakel: contract — nur das Feld `code` entscheidet
Dedup-Key: ref:desktop:error.rs:string-errors-at-ipc
HEAD: 237b450a

### T9 — Desktop-Rust: Rückfall für Server ohne `code` (R-0664)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/error.rs, apps/desktop/src-tauri/src/enrollment.rs, docs/developer/desktop.html, docs/en/developer/desktop.html, CHANGELOG.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @7ba4c1d5 2026-10-29T13:50:16+01:00
Review: approve (.ah-out/review/fehlervertrag/T9.verdict.json)
Änderung (Kevin 2026-10-22: ja, befristet): In `AppError::http` (T6): trägt der Body kein gültiges `code` und beginnt `detail` (String) genau mit `ERR_CERT_REVOKED: `, `ERR_CERT_USER_MISMATCH: ` oder `ERR_CERT_SERVER_MISMATCH: `, wird dieser Code der `code` und der Rest der Text. Nur am Anfang und nur diese drei (die schreibt ein Server vor T2, `apps/server/app/core/identity.py:108-128`). Ein Kommentar nennt das Warum und wann der Rückfall geht (kein unterstützter Server ohne `code` mehr). Tests in `error.rs`: die drei Präfixe ohne `code` → Code und Text ohne Präfix; `ERR_TOFU_PIN_MISMATCH: x` ohne `code` → kein Code; `x ERR_CERT_REVOKED: y` → kein Code; ein gültiges `code` im Body gewinnt vor dem Präfix. `enrollment.rs:1115-1127`: 403 `{"detail":"ERR_CERT_REVOKED: no longer valid"}` ohne `code` → wieder wahr. Zuerst rot: die Präfix-Fälle nach T8.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- error:: -- enrollment::
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (Absatz aus T5/T6: ein Satz zum Übergang für Server ohne `code`) · CHANGELOG.md (Changed, ein Satz)
Abhängt von: T8
Orakel: contract — Rückfall nur am Anfang von `detail` und nur für die drei Codes
Dedup-Key: ref:server:identity.py:no-structured-error-code
HEAD: 237b450a

### T10 — Desktop-UI: Anmeldung verzweigt an `code` für Vertrauen, Pins und Registrierung (R-0709)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/Login.svelte, apps/desktop/ui/src/components/Login.trust.test.ts, apps/desktop/ui/src/components/Login.pin.test.ts, apps/desktop/ui/src/components/Login.mtls.test.ts, apps/desktop/ui/src/components/Login.revoked.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @3a0a3801 2026-10-29T13:57:59+01:00
Review: approve (.ah-out/review/fehlervertrag/T10.verdict.json)
Änderung: `apps/desktop/ui/src/components/Login.svelte`: neben `error` (`:43`) ein `errorCode` (`$state<string | undefined>`), gesetzt mit `errCode(err)` überall, wo `error = errRaw(err)` steht (`:112`, `:141`, `:153`, `:238`) und in `surfaceError` (`:185-193`), geleert, wo `error` geleert oder auf einen eigenen Text gesetzt wird (`:59`, `:89`, `:109`, `:130`, `:138`, `:150`, `:197`, `:211`), und für die Wiederholung nach dem Vertrauensdialog (`:246`) mitgeführt. `caPinError`, `pinError`, `mtlsRequired` (`:71-76`) und die Weiche in `surfaceError` (`:187`) lesen nur noch den Code (`ERR_CA_PIN_MISMATCH`, `ERR_TOFU_PIN_MISMATCH`, `ERR_MTLS_CERT_REQUIRED`, `ERR_TLS_UNKNOWN_ISSUER`); `displayError` (`:84`) bleibt; `certUserMismatch`/`certRevoked` folgen in T11. Tests: in `Login.trust.test.ts`, `Login.pin.test.ts`, `Login.mtls.test.ts` und dem CA-Pin-Fall in `Login.revoked.test.ts` (`:142-145`) lehnen die Mocks mit `new IpcError(<bisheriger Text>, '<Code>')` ab statt mit dem Text; neu je Datei ein Gegenfall: ein `IpcError` mit Code `ERR_VALIDATION`, dessen Text den Code nur enthält (etwa `Login fehlgeschlagen: ERR_TOFU_PIN_MISMATCH: …`) → kein Vertrauensdialog, kein Knopf zum Zurücksetzen, kein Hinweis zum Registrieren. Zuerst rot: die Gegenfälle auf HEAD.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/Login
Doku: CHANGELOG.md (Fixed, umlautfrei: die Hilfen des Anmeldebildschirms — Vertrauensdialog, Pin oder Geraete-Identitaet zuruecksetzen, Geraet registrieren — richten sich nur nach dem Code des Fehlers; ein Text, der einen Code nur enthaelt, loest keine mehr aus)
Abhängt von: T4, T5, T7
Beweis: origin/main@237b450a · Code-Lesung `Login.svelte:71-76` und `:186-187` prüfen `includes('ERR_…')` auf dem ganzen Text, der bei einer Ablehnung des Servers dessen Body enthält (`apps/desktop/src-tauri/src/auth.rs:57-61`); die Gegenfälle sind auf HEAD rot
Orakel: contract — die Hilfen hängen am Code, nicht am Text
Dedup-Key: ref:desktop:error.rs:string-errors-at-ipc
HEAD: 237b450a

### T11 — Desktop-UI: Anmeldung verzweigt an `code` für die Zertifikatscodes des Servers (R-0709)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/Login.svelte, apps/desktop/ui/src/components/Login.revoked.test.ts, apps/desktop/ui/src/components/Login.binding.test.ts, apps/desktop/ui/src/components/Login.dialog.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @dbb86c0b 2026-10-29T14:04:05+01:00
Review: approve (.ah-out/review/fehlervertrag/T11.verdict.json)
Änderung: `certUserMismatch` und `certRevoked` (`apps/desktop/ui/src/components/Login.svelte:79-82`) lesen `errorCode` aus T10 (`ERR_CERT_USER_MISMATCH`, `ERR_CERT_REVOKED`). Tests: `Login.revoked.test.ts`, `Login.binding.test.ts` und `Login.dialog.test.ts` lehnen mit `new IpcError(<Text ohne Präfix, wie ihn T7 liefert>, '<Code>', 403)` ab (Konstanten `Login.revoked.test.ts:16-19`, `Login.binding.test.ts:17-18`, `Login.dialog.test.ts:15-16`); neu je Code ein Gegenfall: `IpcError` mit Code `ERR_HTTP`, Status 403 und einem Text, der `ERR_CERT_REVOKED` bzw. `ERR_CERT_USER_MISMATCH` enthält → kein Hinweis, kein Knopf. Die Tests auf `withoutErrorCodes` (`Login.revoked.test.ts:163-165`, `Login.binding.test.ts:127-129`) bleiben. Zuerst rot: die Gegenfälle auf HEAD.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/Login
Doku: CHANGELOG.md (der Eintrag aus T10 nennt auch die Hinweise zum Zertifikat des Geraets: anderer Benutzer, nicht mehr gueltig)
Abhängt von: T10
Beweis: origin/main@237b450a · Code-Lesung `Login.svelte:79-82` prüfen `includes('ERR_CERT_…')` auf dem Text, der den rohen Body enthält (`auth.rs:57-61`); die Gegenfälle sind auf HEAD rot
Orakel: contract — die Hinweise hängen am Code, nicht am Text
Dedup-Key: ref:desktop:error.rs:string-errors-at-ipc
HEAD: 237b450a

### T12 — Desktop-UI: 409 über `errStatus`, `request.ts` sagt, was gilt (R-0662)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/infra.ts, apps/desktop/ui/src/lib/stores/infra.test.ts, apps/desktop/ui/src/components/monitoring/BuiltinUpdateModal.svelte, apps/desktop/ui/src/components/monitoring/BuiltinUpdateModal.test.ts, apps/desktop/ui/src/lib/api/request.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @fa0ea5e3 2026-10-29T14:09:23+01:00
Review: approve (.ah-out/review/fehlervertrag/T12.verdict.json)
Änderung: `apps/desktop/ui/src/lib/stores/infra.ts:123` und `apps/desktop/ui/src/components/monitoring/BuiltinUpdateModal.svelte:135` prüfen `errStatus(err) === 409` statt `msg.startsWith('HTTP 409')`. `apps/desktop/ui/src/lib/api/request.ts:12-16` beschreibt, was gilt: ein Nicht-2xx lehnt mit einem `IpcError` ab (Status, Code, Text aus `detail` wie `errorDetail` im Web), der Kommentar `:44-45` ebenso. Tests: `infra.test.ts:124-132` und `BuiltinUpdateModal.test.ts:292-305` lehnen mit `new IpcError('<Text>', 'ERR_HTTP', 409)` ab, ihr Verhalten bleibt; neu je ein Gegenfall: ein Fehler ohne Status, dessen Text mit `HTTP 409` beginnt (`new Error('HTTP 409: …')`) → als Fehler gemeldet, nicht als Erfolg bzw. „kein Update mehr“. Zuerst rot: die Gegenfälle auf HEAD.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/infra.test.ts src/components/monitoring/BuiltinUpdateModal.test.ts
Doku: keine (den sichtbaren Teil trägt der CHANGELOG-Eintrag von T6)
Abhängt von: T4, T6
Beweis: origin/main@237b450a · Code-Lesung `infra.ts:123`, `BuiltinUpdateModal.svelte:135` verzweigen am Textanfang `HTTP 409`, den `proxy.rs:71-75` schreibt; die Gegenfälle sind auf HEAD rot
Orakel: contract — die 409-Fälle hängen am Status, nicht am Text
Dedup-Key: bug:desktop:proxy.rs:raw-error-body-to-ui
HEAD: 237b450a

### T13 — Desktop-UI: abgelaufene Sitzung über den Code (R-0709)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/utils/errors.ts, apps/desktop/ui/src/lib/utils/errors.test.ts, apps/desktop/ui/src/lib/stores/monitoring.ts, apps/desktop/ui/src/lib/stores/monitoring.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @490e6629 2026-10-29T14:14:38+01:00
Review: approve (.ah-out/review/fehlervertrag/T13.verdict.json)
Änderung: `apps/desktop/ui/src/lib/utils/errors.ts:27-31`: `SESSION_EXPIRED` ist der Code `'ERR_SESSION_EXPIRED'` (wie `AppError::code()` aus T5), neu `isSessionExpired(err)` = `errCode(err) === SESSION_EXPIRED`. `apps/desktop/ui/src/lib/stores/monitoring.ts` (`:8`, `:194`, `:246`, `:260`, `:273`, `:386`) prüft `isSessionExpired(err)` statt `errMsg(err) !== SESSION_EXPIRED`. Tests: `monitoring.test.ts:168-172` lehnt mit `new IpcError('Session expired, please sign in again', 'ERR_SESSION_EXPIRED')` ab (der Text aus `apps/desktop/src-tauri/src/error.rs:90`) → `monitoringError` null, kein `reportError`; Gegenfall: ein `Error` mit dem Text `ERR_SESSION_EXPIRED` ohne Code → gemeldet; `errors.test.ts`: `isSessionExpired` für `IpcError` mit und ohne den Code und für `Error`; `:34-37` bleibt. Zuerst rot: der `IpcError`-Fall auf HEAD (der Text ist nicht `'SESSION_EXPIRED'`).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/monitoring.test.ts src/lib/utils/errors.test.ts
Doku: CHANGELOG.md (Fixed, umlautfrei: nach dem Ende der Sitzung meldet das Monitoring des Desktops keinen Fehler mehr in der Statusleiste; die Anmeldung erscheint wie bisher)
Abhängt von: T4, T5
Beweis: origin/main@237b450a · Code-Lesung: `AppError::SessionExpired` schreibt „Session expired, please sign in again“ (`error.rs:90`), `monitoring.ts:193-194` vergleicht mit `'SESSION_EXPIRED'` (`errors.ts:31`) und meldet deshalb; der `IpcError`-Fall ist auf HEAD rot
Orakel: contract — die abgelaufene Sitzung hängt am Code
Dedup-Key: ref:desktop:error.rs:string-errors-at-ipc
HEAD: 237b450a

### T14 — CHANGELOG-Einträge als Fragment `changelog.d/fehlervertrag.md`  [x]
Komponente: scripts · Dateien: CHANGELOG.md, changelog.d/fehlervertrag.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @8050f560 2026-10-29T16:42:27+01:00
Review: approve (.ah-out/review/fehlervertrag/T14.verdict.json)
Änderung: Seit dem Basis-Merge gilt `changelog.d/` (README dort): die sechs neuen Einträge des Branch (Added „Server: Fehlerantworten tragen ein optionales Feld `code` …“; Changed „Desktop: Anmeldung zeigt den Text des Servers“ und „Web: Fehlertext ohne Maschinencode“; Fixed „Desktop: kein Monitoring-Fehler nach dem Ende der Sitzung“, „Desktop: Hilfen der Anmeldung nur nach dem Code“ und „Desktop: Fehlertext des Servers statt rohem Body“) wandern wortgleich aus `CHANGELOG.md` nach `changelog.d/fehlervertrag.md`; `CHANGELOG.md` ist danach gleich `origin/main`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Dateien dieser Task

## Entscheidungen

- 2026-10-29 T6: `Display` von `AppError::Http` schreibt ohne lesbaren Text nur `HTTP <status>`, sonst `HTTP <status>: <message>` — sonst stünde in Logs `HTTP 502: HTTP 502`; die IPC trägt die message ohne Präfix (Test `http_names_its_status_once`, T7)
- 2026-10-29 T9: `AppError::http` nimmt die Codes, die nur der Client vergibt (`ERR_TLS_UNKNOWN_ISSUER`, `ERR_TOFU_PIN_MISMATCH`, `ERR_CA_PIN_MISMATCH`, `ERR_MTLS_CERT_REQUIRED`), nicht vom Server an — sonst könnte ein Server ab T10 per `code` den Vertrauensdialog oder den Pin-Reset öffnen (security-Hinweis aus T7)
- 2026-10-29 Abschluss (Kevin): Codes, die nicht in `CLIENT_CODES` stehen, darf der Server setzen, auch `ERR_SESSION_EXPIRED` (die UI meldet dann keinen Fehler) und `ERR_CERT_*` (die Anmeldung bietet das Zuruecksetzen mit Bestaetigung an). Hingenommen: der Server konnte dasselbe bisher ueber den Text, er gewinnt dadurch nichts.
