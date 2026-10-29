<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Fehlervertrag Server → Clients: Maschinencode als Feld, strukturierte Fehler über die Desktop-IPC

Stand des Codes: `origin/main@237b450a`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/fehlervertrag.md`. Roadmap R-0664 (REF), R-0662 (BUG), R-0709 (REF). Entscheidung Kevin 2026-10-22: Der Server
liefert in Fehlerantworten ein **optionales** Feld `code` (Maschinencode wie `ERR_CERT_REVOKED`) zusätzlich zu
`detail`; Web und Desktop werten `code` statt Textpräfixen aus; Rust reicht Status und Code strukturiert über die IPC
ans UI. Additiv, alte Clients bleiben unberührt.

## Problem / Motivation

1. **Maschinencodes stehen im Text (R-0664).** Die drei 403 der Zertifikatsprüfung tragen ihren Code als Präfix in
   `detail`: `CERT_USER_MISMATCH`, `CERT_SERVER_MISMATCH`, `CERT_REVOKED` (`apps/server/app/core/identity.py:108-128`),
   geworfen als `HTTPException` (`:153`, `:172`, `:225`). FastAPI schreibt eine `HTTPException` als
   `{"detail": …}`; ein 422 trägt dagegen eine Liste (`apps/server/app/main.py:409-423`). Die Clients lesen den Code aus
   dem Text: der Desktop-Rust prüft beim Zurücksetzen der Geräte-Identität `body.contains("ERR_CERT_REVOKED")` irgendwo
   im Body (`apps/desktop/src-tauri/src/enrollment.rs:443-446`), die Desktop-UI `error.includes('ERR_CERT_REVOKED')`
   in einer Meldung, die den rohen Body enthält („Login fehlgeschlagen (403 Forbidden): {"detail":"ERR_CERT_REVOKED: …"}“,
   `apps/desktop/src-tauri/src/auth.rs:57-61`, `apps/desktop/ui/src/components/Login.svelte:79-82`). Das Web zeigt
   `detail` samt Präfix (`apps/web/src/lib/api/client.ts:118`, `:126-140`).

2. **Nicht-2xx des Proxys als Text (R-0662).** `proxy::forward` macht aus jeder Nicht-2xx-Antwort
   `AppError::Validation("HTTP <status>: <redigierter roher Body>")` (`apps/desktop/src-tauri/src/proxy.rs:69-75`). Die
   Statusleiste zeigt so JSON, ein 422 als Array; die UI verzweigt per `msg.startsWith('HTTP 409')`
   (`apps/desktop/ui/src/lib/stores/infra.ts:123`, `apps/desktop/ui/src/components/monitoring/BuiltinUpdateModal.svelte:135`).
   `apps/desktop/ui/src/lib/api/request.ts:12-13` behauptet „Behaviour mirrors apps/web/src/lib/api/client.ts“; das Web
   liest aber `detail` (`client.ts:126-140`).

3. **Nackte Strings an der IPC-Grenze (R-0709).** `impl Serialize for AppError` schreibt `to_string()`
   (`apps/desktop/src-tauri/src/error.rs:95-99`); jeder Command-Fehler kommt als String im UI an. Die UI leitet alles
   aus dem Text ab (`apps/desktop/ui/src/lib/utils/errors.ts:12-14`, `Login.svelte:71-82`, `:186-187`), und die Codes
   dürfen irgendwo im Text stehen („buried in the reqwest source chain“, `apps/desktop/src-tauri/src/tofu.rs:266-270`):
   ein Server-Text, der einen Code nur enthält, löst die Hilfen des Anmeldebildschirms aus (Pin zurücksetzen,
   Geräte-Identität zurücksetzen, Vertrauensdialog). `AppError::SessionExpired` schreibt „Session expired, please sign
   in again“ (`error.rs:90`), die UI vergleicht mit der Konstante `'SESSION_EXPIRED'` (`errors.ts:31`;
   `apps/desktop/ui/src/lib/stores/monitoring.ts:194`, `:246`, `:260`, `:273`, `:386`): nie gleich, das Monitoring
   meldet nach dem Ende der Sitzung einen Fehler, obwohl `session-expired` schon zur Anmeldung führt
   (`apps/desktop/ui/src/lib/stores/settings.ts:118-122`). `AppError::Validation` steht an 167 Stellen (grep an
   `237b450a`), darunter HTTP-Status, Sitzungswechsel und frpc-Konfiguration.

## Ziel & Nicht-Ziele

Ziel:
- **Server:** Eine Fehlerantwort, auf die ein Client reagieren soll, trägt `{"detail": …, "code": "ERR_…"}`. `detail`
  bleibt byte-gleich (alte Clients). Heute die drei 403 der Zertifikatsprüfung. Der Mechanismus ist allgemein
  (`CodedHTTPException`), jede andere Antwort bleibt unverändert, auch der 422.
- **Web:** `ApiError` trägt `code`; schickt der Server `code`, ist die Meldung `detail` ohne das führende `<code>: `.
- **Desktop-Rust:** `AppError::code()` liefert einen stabilen Code; ein Command lehnt mit `{code, message, status?}`
  ab. Nicht-2xx des Proxys und der Anmeldung werden `AppError::Http { status, code, message }`, `message` aus `detail`
  wie `errorDetail` im Web. Die eigenen Codes (`ERR_TLS_UNKNOWN_ISSUER`, `ERR_TOFU_PIN_MISMATCH`, `ERR_CA_PIN_MISMATCH`,
  `ERR_MTLS_CERT_REQUIRED`) kommen aus dem Fehlertyp, nicht aus dem Text. `revoked_by` liest `code`.
- **Desktop-UI:** Die Bridge macht aus jeder Ablehnung ein `Error` (`IpcError` mit `code`/`status`, wenn Rust sie
  liefert). Die UI verzweigt nur noch über `errCode(err)`/`errStatus(err)`; angezeigt wird weiter `errMsg(err)`.

Nicht-Ziele (YAGNI):
- Keine Änderung des OpenAPI-Dokuments (offene Frage 2); keine neuen Codes für andere Fehler (die 409-Fälle des
  Desktops verzweigen über `status`).
- Das Präfix in `detail` bleibt; es zu entfernen ist ein späteres Vorhaben, wenn kein Client es mehr liest.
- Keine Umsortierung der übrigen `AppError::Validation`-Stellen: neue Varianten nur, wo ein Verbraucher verzweigt oder
  ein Status reist (`Http`, `MtlsCertRequired`). Kein `thiserror` (die Tauri-Doku empfiehlt es, verlangt es nicht; das
  Projekt schreibt `Display` von Hand).
- Keine Übersetzung der deutschen Rust-Meldungen in der englischen UI (Teil des Titels von R-0662, nicht der Abhilfe):
  braucht UI-Texte je Code; Folgezeile.
- Die Enrollment-Fehler mit rohem Body (`enrollment.rs:539-544`, `:569-574`, `:628-633`) behalten Kontext, Status und
  redigierten Body (Anzeige im Registrierungsbereich, nicht in der Statusleiste); Folgezeile. `notifications.rs:183`,
  `tunnel.rs:54`, `frpc.rs:281`, `:967`, `auth.rs:84-88` (`fetch_me`) und `auth.rs:159-163` (`try_refresh`, nur Log)
  bleiben.
- Gateway: Die nginx-Seite für ein fehlendes Client-Zertifikat bleibt HTML; der Desktop erkennt sie wie heute
  (`auth.rs:37-55`).

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | server | `apps/server/app/core/errors.py` (neu), `apps/server/app/main.py`, `apps/server/tests/test_error_code.py` (neu) |
| T2 | server | `apps/server/app/core/identity.py`, `apps/server/tests/test_certificate_check.py`, `apps/server/tests/test_cert_user_binding.py`, `apps/server/tests/test_mtls_scope.py`, `docs/developer/api-reference.html`, `docs/en/developer/api-reference.html`, `CHANGELOG.md` |
| T3 | web | `apps/web/src/lib/api/client.ts`, `apps/web/src/lib/api/types.ts`, `apps/web/src/lib/api/client.test.ts`, `docs/developer/webui.html`, `docs/en/developer/webui.html`, `CHANGELOG.md` |
| T4 | desktop-ui | `apps/desktop/ui/src/lib/utils/errors.ts`, `apps/desktop/ui/src/lib/utils/errors.test.ts`, `apps/desktop/ui/src/lib/bridge/index.ts`, `apps/desktop/ui/src/lib/bridge/invoke.test.ts` (neu) |
| T5 | desktop-rs | `apps/desktop/src-tauri/src/error.rs`, `apps/desktop/src-tauri/src/tofu.rs`, `docs/developer/desktop.html`, `docs/en/developer/desktop.html` |
| T6 | desktop-rs | `apps/desktop/src-tauri/src/error.rs`, `apps/desktop/src-tauri/src/proxy.rs`, `docs/developer/desktop.html`, `docs/en/developer/desktop.html`, `CHANGELOG.md` |
| T7 | desktop-rs | `apps/desktop/src-tauri/src/error.rs`, `apps/desktop/src-tauri/src/auth.rs`, `CHANGELOG.md` |
| T8 | desktop-rs | `apps/desktop/src-tauri/src/enrollment.rs` |
| T9 `[?]` | desktop-rs | `apps/desktop/src-tauri/src/error.rs`, `apps/desktop/src-tauri/src/enrollment.rs`, `docs/developer/desktop.html`, `docs/en/developer/desktop.html`, `CHANGELOG.md` |
| T10 | desktop-ui | `apps/desktop/ui/src/components/Login.svelte`, `Login.trust.test.ts`, `Login.pin.test.ts`, `Login.mtls.test.ts`, `Login.revoked.test.ts` (alle unter `apps/desktop/ui/src/components/`), `CHANGELOG.md` |
| T11 | desktop-ui | `apps/desktop/ui/src/components/Login.svelte`, `Login.revoked.test.ts`, `Login.binding.test.ts`, `Login.dialog.test.ts`, `CHANGELOG.md` |
| T12 | desktop-ui | `apps/desktop/ui/src/lib/stores/infra.ts`, `apps/desktop/ui/src/lib/stores/infra.test.ts`, `apps/desktop/ui/src/components/monitoring/BuiltinUpdateModal.svelte`, `apps/desktop/ui/src/components/monitoring/BuiltinUpdateModal.test.ts`, `apps/desktop/ui/src/lib/api/request.ts` |
| T13 | desktop-ui | `apps/desktop/ui/src/lib/utils/errors.ts`, `apps/desktop/ui/src/lib/utils/errors.test.ts`, `apps/desktop/ui/src/lib/stores/monitoring.ts`, `apps/desktop/ui/src/lib/stores/monitoring.test.ts`, `CHANGELOG.md` |

Risikopfade (`scripts/dev/review-risk.txt`): `identity.py` (T2), `tofu.rs` (T5, nur Test), `auth.rs` (T7),
`enrollment.rs` (T8, T9) — dort zusätzlich `security`. `commands.rs` ändert sich nicht: alle 40 Commands liefern
`Result<_, AppError>` (grep an `237b450a`), die neue Form kommt allein über `impl Serialize`.

## Datenmodell / API / Migrationen

**Server.** Keine Migration, keine Route. Neu `CodedHTTPException(HTTPException)` mit `code`; ein Handler dafür
schreibt `{"detail": <detail>, "code": <code>}` mit Status und Headern der Exception. Starlette 1.3.1 (gepinnt in
`apps/server/requirements.txt`) sucht den Handler entlang der MRO (`starlette/_exception_handler.py:16-20`), die
Unterklasse gewinnt also vor dem Standard-Handler für `HTTPException`; alle anderen `HTTPException` bleiben
`{"detail": …}`. `detail` der drei 403 bleibt wörtlich wie heute; `auth_router.py:129-140` fängt und wirft die
Exception unverändert weiter.

**OpenAPI.** Unverändert: keine Route dokumentiert eine 403; die 82 Operationen in `tests/openapi.snapshot.json`
nennen nur 2xx und 422. T1 und T2 fahren `tests/test_openapi_snapshot.py` im `Verify:` mit. Probe (oasdiff 1.32.0,
`oasdiff breaking` gegen den Snapshot von `237b450a`): (A) neues Schema `ErrorResponse {detail, code?}` als 403 an
einer Operation, (B) optionales `code` in `HTTPValidationError` (67 Operationen), (C) 403 mit `ErrorResponse` an allen
82 Operationen — je 0 error, 0 warning; nur INFO (`response-non-success-status-added`,
`response-optional-property-added`). Eine Dokumentation im Schema wäre also für `openapi-breaking.sh` kein ERR (offene
Frage 2).

**Web.** `ApiError(status, message, detail?, code?)`; `code` nur, wenn der Body ein `code` der Form
`^ERR_[A-Z0-9_]{1,64}$` trägt.

**Desktop-IPC.** Ein Command, der scheitert, lehnt mit diesem JSON ab:

```
{ "code": "<stabiler Code>", "message": "<Text für den Menschen>", "status": <HTTP-Status, nur bei AppError::Http> }
```

| `code` | Quelle | `status` | Verbraucher in der UI |
|---|---|---|---|
| `ERR_VALIDATION`, `ERR_IO`, `ERR_CONNECTION`, `ERR_KEYRING`, `ERR_JSON` | gleichnamige Variante | – | – |
| `ERR_NETWORK` | `Network` ohne einen der drei folgenden | – | – |
| `ERR_TLS_UNKNOWN_ISSUER` | `Network`, `UnknownIssuer` in der Kette (`error.rs:13-37`) | – | Vertrauensdialog (`Login.svelte:185-193`) |
| `ERR_TOFU_PIN_MISMATCH` | `Network`, `rustls::Error::General` des TOFU-Verifiers (`tofu.rs:271-276`) | – | Pin zurücksetzen (`Login.svelte:72`) |
| `ERR_CA_PIN_MISMATCH` | `Network`, `General` des CA-Pins (`enrollment.rs:707-715`) | – | Geräte-Identität zurücksetzen (`Login.svelte:71`) |
| `ERR_SESSION_EXPIRED` | `SessionExpired` | – | Monitoring ohne Fehlermeldung (`monitoring.ts`) |
| `ERR_MTLS_CERT_REQUIRED` | neue Variante `MtlsCertRequired` (`auth.rs:48-55`) | – | Hinweis Registrieren (`Login.svelte:76`) |
| `ERR_HTTP` | neue Variante `Http` ohne gültigen Server-Code | ja | 409 über `status` (`infra.ts`, `BuiltinUpdateModal.svelte`) |
| Server-Code (`ERR_CERT_REVOKED`, `ERR_CERT_USER_MISMATCH`, …) | `Http` mit `code` aus dem Body | ja | Hinweise der Anmeldung (`Login.svelte:79-82`) |

`message` ist bei `Http` der Text aus `detail` (String; bei einer Liste die `msg`-Texte mit `; `; sonst
`HTTP <status>`), ohne führendes `<code>: `, durch `diagnostics::redact_body` (`diagnostics.rs:108-116`); bei allen
anderen Varianten `to_string()` wie heute (die eigenen Codes bleiben im Text, `errMsg` entfernt sie wie bisher).
`Display` von `Http` ist `HTTP <status>: <message>` (Log). Die UI wird mit der App gebündelt, Rust und UI haben also
keinen Versionsversatz. Die Desktop-E2E-Specs lesen eine Ablehnung als `String((e && e.message) || e)`
(`apps/desktop/e2e/test/specs/logout.live.js:25`, gleich in den anderen Specs) und bleiben mit der Objektform gültig.

## Externe Integrationen

- **Tauri** (https://v2.tauri.app/develop/calling-rust/#error-handling, gelesen 2026-10-22): Alles, was ein Command
  zurückgibt, auch der Fehler, muss `serde::Serialize` implementieren; scheitert der Command, lehnt das Promise ab; das
  Beispiel serialisiert den Fehler als Objekt (`{ kind, message }`) und das Frontend erhält genau dieses Objekt. Was
  bei Tauris eigenen Fehlern ankommt, sagt die Seite nicht. Im Quelltext belegt (tauri 2.11.5 laut `Cargo.lock`,
  `src/ipc/mod.rs:240-253`): ein Command-Fehler wird `serde_json::to_value(err)`, ein Fehler von Tauri selbst
  (`crate::Error`, etwa „invalid args `x` for command `y`“) ein JSON-String. Die Bridge muss also beide Formen annehmen.
- **FastAPI/Starlette**: Handler-Suche entlang der MRO, Quelltext Starlette 1.3.1 (oben). Sonst keine externe
  Schnittstelle.

## Trade-offs & Alternativen

1. **Wo der Code steht (Server).** (a) Eigenes Feld `code` neben `detail`, `detail` unverändert — **Kevins
   Entscheidung**, additiv. (b) `detail` als Objekt — bricht jeden heutigen Client. (c) Header — kein Client liest ihn.
2. **IPC-Form.** (a) `{code, message, status?}`, `code` immer gesetzt — **Empfehlung**: die UI verzweigt an einer
   Stelle, der Status reist nur, wo es einen gibt. (b) Tauris Beispiel `{kind, message}` mit getrenntem `code` — zwei
   Felder für dieselbe Frage. (c) String behalten und `ERR_…` vorne anstellen — das Problem von R-0709.
3. **Wo die UI die Form liest.** (a) Ein Wrapper um `invoke` in `bridge/index.ts`, der jede Ablehnung in ein `Error`
   (`IpcError`) wandelt — **Empfehlung**: alle `invoke` stehen dort (`bridge/ipc.inventory.test.ts:108-117`), `errMsg`
   und `errRaw` funktionieren unverändert. (b) Jeder Aufrufer prüft selbst — 40 Aufrufe von `invoke`.
4. **Reihenfolge Desktop.** Erst die Bridge (T4, nimmt String und Objekt), dann die Objektform in Rust (T5), dann die
   Verbraucher (T10–T13): jeder Commit bleibt lauffähig. Andersherum zeigte die UI nach T5 „[object Object]“.
5. **Pin-Codes aus der Kette.** `code()` sucht in der Quellkette ein `rustls::Error::General`, dessen Text mit
   `ERR_TOFU_PIN_MISMATCH: ` oder `ERR_CA_PIN_MISMATCH: ` beginnt — beides schreiben nur unsere Verifier, kein Server
   kann es setzen. Alternative `rustls::Error::Other` mit eigenem Typ: sauberer, ändert aber die Verifier auf zwei
   Risikopfaden, die desktop-blocking gerade umbaut.
6. **Server-Codes ohne `code` (alter Server).** Siehe offene Frage 1 (T9).

## Risiken & Rollback

- Ein Server kann über `code` die Hilfen des Anmeldebildschirms auslösen. Das ist der Vertrag (er sagt heute schon
  „Zertifikat widerrufen“); neu ist, dass ein bloßer Text es nicht mehr kann. Rust nimmt nur Codes der Form
  `^ERR_[A-Z0-9_]{1,64}$`, die UI wertet nur bekannte Codes aus.
- Ohne T9 erkennt ein neuer Desktop gegen einen Server vor T2 die Zertifikatscodes nicht mehr: die Anmeldung zeigt den
  Text, aber keinen Knopf; das Zurücksetzen der Geräte-Identität meldet bei einem schon widerrufenen Gerät „nur auf
  diesem Gerät“ statt „widerrufen“.
- Parallele Vorhaben ändern dieselben Dateien (Kopf des Ledgers, „Hängt ab von“); nach dem Hereinmergen von
  `origin/main` den ganzen Testordner der gemeinsamen Komponente fahren.
- Rollback: jede Task ist ein Commit ohne Datenänderung; Revert genügt. Wird T5 zurückgenommen, müssen T6–T13 mit.

## Doku-Impact

T2: `docs/developer/api-reference.html` „Fehler-Format“ (DE+EN): das optionale `code`, die drei Codes, Clients
verzweigen auf `code`; CHANGELOG (Added). T3: `docs/developer/webui.html:79` (DE+EN) ein Satz zu `ApiError`; CHANGELOG
(Changed). T5/T6/T9: `docs/developer/desktop.html` nach der Command-Tabelle (`:186`, DE+EN) ein Absatz zur Fehlerform.
T6, T7, T10, T11, T13: CHANGELOG. T1, T4, T8, T12: keine (intern).

## Offene Fragen

1. **T9 — Rückfall für Server ohne `code`?** Soll der Desktop, wenn der Body kein gültiges `code` trägt, die drei
   Zertifikatscodes noch am **Anfang** von `detail` erkennen (verankert, nur `ERR_CERT_REVOKED`,
   `ERR_CERT_USER_MISMATCH`, `ERR_CERT_SERVER_MISMATCH`)? Empfehlung: **ja, befristet** — es gibt keine dokumentierte
   Versionsregel zwischen Server und Desktop und keinen Auto-Updater; ohne Rückfall verliert ein neuer Desktop gegen
   einen älteren Server die Hinweise der Anmeldung und das „widerrufen“ beim Zurücksetzen. Der Rückfall ist enger als
   heute (Anfang von `detail`, drei Codes, statt irgendwo im Body). Trade-off: er liest für diesen Übergang doch einen
   Textpräfix, gegen den Wortlaut „statt Textpräfixen“; Entfernen als eigene Roadmap-Zeile nach einem Release. Bei
   „nein“: T9 `[~]`, T8 bleibt wie gebaut.
2. **`code` im OpenAPI-Dokument?** Der Plan dokumentiert `code` in der API-Referenz und pinnt es per Test, nicht im
   Schema. Alternative: ein Schema `ErrorResponse` als 403 an allen Operationen — für oasdiff nur INFO (Probe oben),
   aber ein großer Snapshot-Diff gegen jedes parallele Server-Vorhaben, und er behauptete eine 403 auch, wo keine
   kommt. Empfehlung: nein. Blockiert keine Task; bei „ja“ eine Zusatz-Task nach T2.
3. **Web zeigt den Text ohne `ERR_…: `** (T3), wenn der Server `code` schickt — wie der Desktop seit R-0276. Der Plan
   baut das als Teil von „Web wertet `code` aus“; blockiert nichts.
