<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Ausstellungsregister und Widerruf pro Gerät — Task-Ledger
Status: aktiv · Branch: feature/device-certificate-register · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Freigabe: Kevin, 2026-10-11 (Phase B mit F1–F8 wie empfohlen: Übergang ab Installation des Registers, Sperre auch permissiv, ERR_CERT_REVOKED, Restrisiko Handshake/frps hingenommen, der Agent-Hinweis aus R-0280 in T10); gesetzt von der Aufsicht adminhelper-ac
Spec: Roadmap R-0224, R-0279, R-0280
Heavy: linux-full + scenario --enforce --agents 1 --desktop — PKI-, mTLS- und Provisionierungs-Pfad über mehrere Dienste: `run.sh integration` (Enroll und Renew über das Gateway, Migration im Stack und im `upgrade-path`, Postgres-Fall im `stack-pytest`) und `run.sh e2e` (Desktop: Registrieren, Zurücksetzen, Neu-Registrieren) auf einer Pool-VM; dazu vor dem Merge ein Multibox-Lauf `--enforce --agents 1 --desktop`, weil die Prüfung am Server und am Issuer nur mit echtem mTLS über das Gateway greift und Agent und Desktop dort eigene Zertifikate tragen. Der Multibox-Lauf ist ask-first, die Aufsicht holt ihn.
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber, gofmt und go vet, cargo fmt und clippy -D warnings, svelte-check, ESLint und Prettier sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-11 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Die Richtung ist entschieden (Kevin hat die
Designfragen am 2026-10-10 an die Aufsicht übergeben, sie hat wie empfohlen entschieden). Zeilenangaben
origin/main@8e31cf71. Review je Task nach `review.sh risk`: Opus für Migration, ca-issuer und Server-Auth (T1–T7),
sonst Sonnet; am Ende ein Opus-Review über den ganzen Branch.

**Die Funktion:** Jedes ausgestellte Client-Zertifikat wird erfasst, und gesperrt wird pro Gerät.
- **Register:** Der ca-issuer hält jede Ausstellung fest: Fingerprint (SHA-256 über DER), Seriennummer, Laufzeit, Art
  (`desktop`, `browser`, `agent`) und eine **Geräte-Linie**. Ein Gerät bekommt sie beim Registrieren, ein Renew erbt sie.
- **Prüfung:** Server und Renew prüfen jedes vorgelegte Zertifikat. Gesperrt ist es, wenn seine Linie gesperrt ist, wenn
  es unter den Widerruf seines Benutzers fällt oder wenn es nicht erfasst ist (außer im Übergang). Der Server antwortet
  dann mit 403 und dem Code `ERR_CERT_REVOKED`, unabhängig von `MTLS_ENFORCE`.
- **Widerruf eines Benutzers ist ein Zeitpunkt:** Löschen sperrt alle bis dahin ausgestellten Zertifikate dieses
  Benutzers. Ein später gleichnamig angelegter Benutzer bekommt neue, die alten bleiben gesperrt.
- **Ablösen:** Neu-Registrieren nennt das vorige Zertifikat dieses Geräts (`replaces`), dessen Linie wird gesperrt.
  „Geräte-Identität zurücksetzen“ sperrt zuerst die eigene Linie am Server, dann löscht es lokal. Neu-Provisionieren
  eines Agents ersetzt Zertifikat und API-Key des bisherigen.
- **Admins** listen und sperren die Geräte eines Benutzers per API.
- **Übergang:** Zertifikate, die vor dem Update ausgestellt wurden, gelten 90 Tage ab dem Update weiter und werden beim
  ersten Kontakt erfasst. Danach gilt nur noch, was erfasst ist.

### T1 — Server: Tabellen des Registers, Migration und Aufräumen (R-0224)  [x]
Komponente: server · Dateien: apps/server/alembic/versions/3f9c2a7e5b1d_add_certificate_register.py, apps/server/app/modules/enrollment/models.py, apps/server/app/modules/hooks/scheduler.py, apps/server/app/scheduler_main.py, apps/server/tests/test_certificate_register.py, apps/server/tests/test_migrations_smoke.py
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped @8bfcba7f 2026-10-11T08:39:50+02:00
Review: approve (opus), 3 nits in derselben Runde behoben
Änderung: Neue Revision `3f9c2a7e5b1d` (Vorgänger `8bdf9641a51f`, Stil wie
`9aa48c0eaecb_add_enrollment_tokens_revoked_identities.py`) mit drei Tabellen, die Modelle in `enrollment/models.py`
(Zeitspalten naive UTC, Konvention F7 `models.py:29-33`):
- `device_lines`: `id` (UUID, PK), `subject_id`, `scope`, `kind`, `legacy` (Boolean, Default false), `created_at`,
  `revoked_at`, `revoked_reason` (`replaced`, `self`, `admin`); Index auf (`subject_id`, `scope`).
- `issued_certificates`: `fingerprint` (64 Hex-Zeichen, PK), `line_id` (FK auf `device_lines.id`, `ON DELETE CASCADE`,
  Index), `serial` (hex, bis 40 Zeichen), `not_before`, `not_after` (Index), `renewed_from` (Fingerprint, ohne FK),
  `created_at`.
- `certificate_register_state`: eine Zeile `id = 1` mit `installed_at`. Die Migration legt sie an; sie ist der
  Startpunkt des Übergangs. Es wird nichts rückerfasst.
- Downgrade entfernt die drei Tabellen.
- **Aufräumen:** Ein Helfer löscht Zertifikate mit `not_after` in der Vergangenheit und danach Linien ohne Zertifikat.
  Er läuft als System-Job alle 6 h, nach dem Muster `cleanup_finished_enrollment_tokens` +
  `schedule_enrollment_token_cleanup` (`hooks/scheduler.py:310-332`), registriert in `scheduler_main.py:68-87`.
- **Tests:**
  - `test_migrations_smoke.py` bekommt einen Datenfall: Nach `upgrade head` gibt es genau eine Zustandszeile, nach
    `downgrade 8bdf9641a51f` keine der drei Tabellen.
  - `test_migration_chain_matches_models` und die pytest-alembic-Fälle bleiben grün.
  - `tests/test_certificate_register.py` (neu, SPDX): Das Aufräumen löscht abgelaufene Zertifikate und leere Linien und
    lässt gültige stehen; eine gesperrte Linie mit gültigem Zertifikat bleibt.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_certificate_register.py tests/test_migrations_smoke.py tests/test_alembic_builtin.py tests/test_scheduler_reconcile.py
Doku: keine (intern; Schema-Liste in T13)

### T2 — Server: Der Widerruf eines Benutzers wird ein Zeitpunkt (R-0224)  [x]
Komponente: server · Dateien: apps/server/app/modules/enrollment/models.py, apps/server/app/modules/users/router.py, apps/server/app/core/identity.py, apps/server/tests/test_identity_revocation.py, apps/server/tests/test_mtls_scope.py, CHANGELOG.md, apps/server/app/modules/notifications/stream.py, apps/server/tests/test_stream.py
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped · contracts: 1 ok @10acad6e 2026-10-11T09:08:04+02:00
Review: request_changes (opus, 1 wichtig: Stream-Weitergabe ungetestet) behoben, r2 approve (opus)
Änderung: `revoked_identities.revoked_at` wird zum Zeitpunkt, ab dem die Zertifikate eines CN und Scopes nicht mehr gelten.
- `revoke_identity` (`models.py:83-96`) wird zum Upsert: Ein erneuter Widerruf setzt `revoked_at` auf jetzt.
- `clear_revocation` (`models.py:99-107`) und sein Aufruf beim Neuanlegen eines Benutzers (`users/router.py:63-65`)
  entfallen.
- `ClientIdentity` (`identity.py:50-60`) bekommt `not_before` (am Ende, Default `None`); `get_client_identity` liest es
  aus dem schon geparsten Leaf (`:86`, `not_valid_before_utc` ohne tzinfo).
- Die Prüfung in `require_scope` sperrt ein Zertifikat, wenn `revoked_at >= not_before`. Ohne `not_before` (nur bei
  handgebauter Identität in Tests) gilt ein Eintrag wie bisher als Sperre.
- **Tests:**
  - Namensvetter: Das Zertifikat des früheren Benutzers (notBefore vor dem Löschen) bleibt gesperrt, ein neues nach dem
    Neuanlegen gilt.
  - Erneutes Löschen zieht den Zeitpunkt nach.
  - Der Helfer `_client_cert_pem` in `test_mtls_scope.py` bekommt `not_before` als Parameter.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_identity_revocation.py tests/test_mtls_scope.py tests/test_cert_user_binding.py tests/test_stream.py
Doku: CHANGELOG (Changed); Admin-Doku in T14
Test-Löschung: apps/server/tests/test_identity_revocation.py::test_clear_revocation_removes_row — der Helfer `clear_revocation` entfällt mit seinem Aufruf; apps/server/tests/test_identity_revocation.py::test_create_user_clears_a_stale_revocation — das Neuanlegen räumt nichts mehr, ersetzt durch den Namensvetter-Fall mit eigenem Namen
Assertion-Änderung: apps/server/tests/test_identity_revocation.py::test_revoke_identity_is_idempotent — die Aussage fragt den Zeitpunkt des Widerrufs ab statt Ja/Nein; apps/server/tests/test_identity_revocation.py::test_scope_is_part_of_the_revocation_key — ebenso; apps/server/tests/test_identity_revocation.py::test_delete_user_revokes_its_access_identity — ebenso; apps/server/tests/test_identity_revocation.py::test_delete_server_revokes_its_tunnel_identity — ebenso

### T3 — ca-issuer: Jede Ausstellung wird erfasst, `replaces` löst das vorige Zertifikat ab (R-0224)  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/db.py, apps/ca-issuer/app/tokens.py, apps/ca-issuer/app/issuer.py, apps/ca-issuer/app/main.py, apps/ca-issuer/tests/test_enroll_renew.py, apps/ca-issuer/tests/test_db_token_store.py, apps/server/tests/test_certificate_register_view.py, docker-compose.yml
Evidenz: run.sh[quick] ca-issuer server: 5 passed, 0 failed, 13 skipped · contracts: 1 ok @ee5cc8e8 2026-10-11T09:40:57+02:00
Review: request_changes (opus, 1 wichtig: Pflichtfeld-Regel im Vertragstest) behoben, r2 approve (opus)
Änderung:
- **Core-Sicht** (`db.py:31-51`) um die drei Tabellen aus T1 und `revoked_identities.revoked_at` erweitern.
  `tests/test_certificate_register_view.py` im Server (neu, SPDX) hält die Sicht am Server-Modell fest: Jede Spalte der
  Sicht gibt es im Modell. Muster ist `tests/test_enrollment_hash_lockstep.py`, die Quelle wird per `ast` gelesen, nicht
  importiert.
- **Enroll in einer Transaktion:** CSR prüfen (vor dem Token, wie heute). Dann in einem `engine.begin()`: Token
  verbrauchen, Leaf signieren, eine neue Linie und den Zertifikatseintrag anlegen (Fingerprint und Seriennummer aus dem
  Leaf in `issuer.py:72-82`) und `replaces` anwenden. Scheitert ein Schritt, bleibt der Token unverbraucht.
  - Die Art kommt aus dem Grant: `tunnel` → `agent`, `access` mit `browser` → `browser`, sonst `desktop`.
- **`replaces`:** optionales Feld in `EnrollRequest` (`main.py:112-114`), 64 Hex-Zeichen, sonst 422. Trägt die Linie des
  genannten Zertifikats Subjekt und Scope des Grants, wird sie gesperrt (`replaced`). Sonst geschieht nichts, und die
  Antwort ist dieselbe.
- Der `TokenStore`-Vertrag (`tokens.py:31-40`) und `InMemoryTokenStore` (`:49-85`) bekommen dieselben Operationen; der
  In-Memory-Store hält das Register im Speicher.
- Docstring `db.py:5-9`, Kommentar `docker-compose.yml:232-233` und Kommentar `test_db_token_store.py:104` sagen, wem die
  Tabellen gehören und was der Issuer liest und schreibt.
- **Tests:**
  - Enroll erfasst das Zertifikat; der gespeicherte Fingerprint ist der SHA-256 über DER des ausgegebenen Leafs.
  - Ein Browser-Grant ergibt Art `browser`.
  - `replaces` sperrt die eigene Linie und lässt eine Linie eines anderen Subjekts und einen unbekannten Fingerprint
    unberührt.
  - Ein Fehler nach dem Verbrauch lässt den Token gültig.
  - Die Fälle laufen gegen den DB-Store (sqlite wie `test_db_token_store.py`) und den In-Memory-Store.
Verify: bash scripts/dev/verify.sh ca-issuer server --strict
Doku: keine (intern; Doku in T13)
Abhängt von: T1

### T4 — ca-issuer: Renew prüft gegen das Register, den Zeitpunkt und den Übergang (R-0224)  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/issuer.py, apps/ca-issuer/app/db.py, apps/ca-issuer/app/tokens.py, apps/ca-issuer/tests/test_enroll_renew.py, apps/ca-issuer/tests/test_db_token_store.py
Evidenz: run.sh[quick] ca-issuer: 4 passed, 0 failed, 14 skipped @b42e24bf 2026-10-11T09:57:24+02:00
Review: request_changes (opus, 3 wichtig: Subject-Parse, Cutoff nach dem Signieren, Ed25519-Testpfad) behoben, r2 approve (opus)
Änderung:
- Die Signatur des vorgelegten Zertifikats wird nur gegen das Intermediate seiner OU geprüft (`issuer.py:46-70`).
- **Die Regel**, für Server und Renew dieselbe:
  - gesperrt bei Widerruf mit `revoked_at >= notBefore` (T2);
  - gesperrt, wenn die Linie gesperrt ist;
  - ein nicht erfasstes Zertifikat gilt nur, wenn es vor `installed_at` ausgestellt wurde und der Übergang (90 Tage ab
    `installed_at`) noch läuft. Dann wird es erfasst: neue Linie mit `legacy`, die Art aus Scope und Laufzeit wie heute
    (`issuer.py:142-145`). Sonst ist es gesperrt.
- Alles in einer Transaktion mit einer Zeilensperre auf der Linie (`SELECT … FOR UPDATE`): prüfen, gegebenenfalls
  erfassen, signieren, den Nachfolger mit derselben Linie und `renewed_from` einfügen. Ein Widerruf der Linie wartet auf
  die Sperre.
- `is_active` (`db.py:116-122`) wird zur Prüfung des Zeitpunkts.
- **Tests:**
  - Ein erfasstes Zertifikat erneuert sich: gleiche Linie, `renewed_from` gesetzt.
  - Gesperrte Linie: 403.
  - Zeitpunkt: Das alte Zertifikat bleibt gesperrt, ein neues nach dem Neuanlegen erneuert sich.
  - Nicht erfasst und im Übergang: wird erfasst und erneuert.
  - Nicht erfasst nach dem Übergang: 403. Nicht erfasst und nach `installed_at` ausgestellt: 403.
  - Ein Leaf mit OU `access`, signiert vom tunnel-Intermediate: 403.
  - **Postgres-Fall** (`AH_TEST_DB`, Muster `test_concurrent_consume_only_one_wins`): Ein Widerruf der Linie während eines
    Renew lässt keinen Nachfolger an der Sperre vorbei.
Verify: bash scripts/dev/verify.sh ca-issuer --strict
Doku: keine (intern; Doku in T13)
Abhängt von: T3
Assertion-Änderung: apps/ca-issuer/tests/test_db_token_store.py::test_is_active_until_revoked — die Prüfung des Widerrufs wird ein Zeitpunkt und bekommt das notBefore des Zertifikats

### T5 — Server: Jedes vorgelegte Zertifikat wird gegen das Register geprüft (R-0224)  [x]
Komponente: server · Dateien: apps/server/app/core/identity.py, apps/server/app/core/auth.py, apps/server/app/modules/users/auth_router.py, apps/server/app/modules/notifications/stream.py, apps/server/tests/conftest.py, apps/server/tests/test_certificate_check.py, apps/server/tests/test_mtls_scope.py, apps/server/tests/test_stream.py, apps/server/tests/test_cert_user_binding.py, CHANGELOG.md, apps/server/app/modules/enrollment/models.py
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped · contracts: 1 ok @04f7bcd3 2026-10-11T10:45:36+02:00
Review: request_changes (opus, 2 wichtig: permissiver Scope-Guard und get_current_user ungetestet) behoben, r2 approve (opus)
Änderung:
- `ClientIdentity` bekommt `fingerprint` (am Ende, Default `None`). `get_client_identity` berechnet ihn aus dem geparsten
  Leaf (SHA-256 über DER, hex klein). Kein neuer Gateway-Header; `tests/test_identity_header_contract.py` bleibt.
- **Eine Prüfung** mit der Regel aus T4 läuft überall, wo eine verifizierte Identität ausgewertet wird:
  - `require_scope`, statt `_is_revoked` (`identity.py:125-134`, `:157-170`);
  - die Stellen aus `require_cert_user`: `get_current_user`, der Bearer-Zweig von `ApiKeyOrUser`, Login, Refresh,
    Bootstrap und das Öffnen des Streams;
  - der Reauth des Streams (`stream.py:36-53`) mit dem Fingerprint.
  - Je Request gibt es ein Ergebnis (Zwischenspeicher in `request.state`).
- **Übernahme beim ersten Kontakt:** Ein nicht erfasstes Zertifikat im Übergang wird über die DB-Session der Anfrage
  erfasst und sofort committet (parallel: `ON CONFLICT DO NOTHING` auf den Fingerprint); im Stream über `SessionLocal`
  wie der Reauth.
- **Antwort:** 403 mit `ERR_CERT_REVOKED: This device certificate is no longer valid. Reset the device identity and
  register the device again.`, auch bei `MTLS_ENFORCE=false`. Ohne verifizierte Identität gibt es nichts zu prüfen.
  Ohne Fingerprint (handgebaute Identität) gilt das Zertifikat als nicht erfasst und nicht übernehmbar.
- **`tests/conftest.py`:** Die Zustandszeile liegt so, dass die Ad-hoc-Zertifikate der bestehenden Tests als vor dem
  Register ausgestellt gelten (`installed_at` nach dem Erzeugen, Übergang offen). Die neuen Tests setzen sie selbst.
- **Tests** in `tests/test_certificate_check.py` (neu, SPDX):
  - erfasst und gültig 200; Linie gesperrt 403 mit Code;
  - Zeitpunkt (alt 403, neu 200);
  - nicht erfasst im Übergang: 200 und danach erfasst; nicht erfasst nach dem Übergang 403; nicht erfasst und nach
    `installed_at` ausgestellt 403;
  - gesperrt auch permissiv;
  - Login, Refresh und das Öffnen des Streams mit gesperrtem Zertifikat 403;
  - der Agent-Push mit gesperrtem tunnel-Zertifikat 403;
  - Reauth beendet einen Stream, dessen Linie gesperrt wurde.
  - In `test_cert_user_binding.py` bekommt der Stream-Fall die Prüfung als Monkeypatch (der Fake hat keine DB).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_certificate_check.py tests/test_mtls_scope.py tests/test_stream.py tests/test_cert_user_binding.py tests/test_identity_revocation.py tests/test_identity_header_contract.py
Doku: CHANGELOG (Changed); Admin- und Entwickler-Doku in T13/T14
Abhängt von: T1, T2
Test-Löschung: apps/server/tests/test_mtls_scope.py::test_permissive_allows_revoked_identity — ein gesperrtes Zertifikat wird künftig auch permissiv abgelehnt, ersetzt durch den Fall in test_certificate_check.py
Assertion-Änderung: apps/server/tests/test_mtls_scope.py::test_enforced_allows_non_revoked_identity — die Identität trägt Fingerprint und notBefore eines erfassten Zertifikats; apps/server/tests/test_stream.py::test_ok_when_valid_and_not_revoked — der Reauth bekommt den Fingerprint; apps/server/tests/test_stream.py::test_ends_when_jwt_blacklisted — ebenso; apps/server/tests/test_stream.py::test_ends_when_identity_revoked — ebenso; apps/server/tests/test_stream.py::test_unverified_identity_skips_revocation_check — ebenso

### T6 — Server: Selbst-Widerruf und Geräteliste für Admins (R-0224)  [x]
Komponente: server · Dateien: apps/server/app/modules/enrollment/router.py, apps/server/app/modules/enrollment/models.py, apps/server/app/modules/users/router.py, apps/server/tests/test_device_api.py, apps/server/tests/openapi.snapshot.json, docs/developer/api-reference.html, docs/en/developer/api-reference.html, CHANGELOG.md, apps/server/app/modules/users/schemas.py
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped · contracts: 1 ok @f799c3bb 2026-10-11T11:25:46+02:00
Review: request_changes (opus, 2 wichtig: legacy in der Liste, Audit bei schon gesperrter Linie) behoben, r2 approve (opus)
Änderung: Drei Routen:
- `POST /api/enrollment/self/revoke` sperrt die Linie des vorgelegten Zertifikats (`self`), Antwort 204.
  - Nachweis ist die verifizierte Identität allein (mTLS), kein JWT: Der Desktop setzt auch am Anmeldebildschirm zurück.
  - Eigener Guard `require_scope(SCOPE_ACCESS)` an der Route; der Router hat keinen (`main.py:288-290`).
  - Ein nicht erfasstes Zertifikat im Übergang wird erfasst und gesperrt. Ohne verifizierte Identität 409.
- `GET /api/users/{user_id}/devices` (Admin, `get_current_admin`) listet die Linien des Benutzers (Subjekt = Username,
  Scope `access`): `id`, `kind`, `legacy`, `createdAt`, `revokedAt`, `revokedReason` und vom jüngsten Zertifikat
  `fingerprint` und `notAfter`.
- `DELETE /api/users/{user_id}/devices/{device_id}` (Admin) sperrt die Linie (`admin`), Antwort 204. Eine Linie eines
  anderen Benutzers gibt 404.
- Audit `device.revoked` mit dem Grund; beim Selbst-Widerruf ist der Actor der CN.
- `tests/openapi.snapshot.json` neu erzeugen (`--update-openapi-snapshot`). `test_route_auth_gate.py` bleibt grün
  (`require_scope` zählt als Marker).
- **Tests** in `tests/test_device_api.py` (neu, SPDX):
  - Selbst-Widerruf mit eigenem Zertifikat 204, danach 403 mit Code;
  - ohne Zertifikat 409;
  - die Liste zeigt erfasste und übernommene Linien;
  - Admin sperrt 204, danach 403 für dieses Gerät, ein anderes Gerät desselben Benutzers bleibt gültig;
  - ein Nicht-Admin bekommt 403, eine fremde Linie 404;
  - ein Audit-Eintrag je Widerruf.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_device_api.py tests/test_route_auth_gate.py tests/test_openapi_snapshot.py
Doku: docs/developer/api-reference.html + EN (die drei Routen) · CHANGELOG (Added)
Abhängt von: T5

### T7 — Server: Neu-Provisionieren ersetzt den API-Key des Agents (R-0279)  [x]
Komponente: server · Dateien: apps/server/app/modules/provisioning/router.py, apps/server/tests/test_provisioning.py, CHANGELOG.md
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped · contracts: 1 ok @753908b1 2026-10-11T11:45:34+02:00
Review: approve (opus, Aufsicht: Opus fuer T1-T7; risk sagt standard), 3 nits behoben, Wettlauf zweier Aktivierungen als Kandidat gemeldet
Änderung: `POST /api/servers/{id}/provision/activate` löscht vor dem neuen Agent-Key (`router.py:150-158`) alle API-Keys
mit derselben `server_id`, in derselben Transaktion, mit einem Audit-Eintrag.
- Server-gebundene Keys entstehen nur hier; manuell angelegte Keys tragen keine `server_id` (`api_keys/router.py:24-37`).
- **Tests:**
  - Nach einer zweiten Aktivierung (neues Provision-Token) gibt der frühere Key 401 und der neue 200, an einer Route,
    die der Agent nutzt.
  - Ein globaler Key und der Key eines anderen Servers bleiben.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_provisioning.py
Doku: CHANGELOG (Changed); Admin-Doku in T14

### T8 — Desktop-Backend: Neu-Registrieren nennt das vorige Zertifikat, Zurücksetzen widerruft am Server (R-0224)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/enrollment.rs, apps/desktop/src-tauri/src/commands.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @b298c1cf 2026-10-11T12:01:57+02:00
Review: request_changes (opus, 1 wichtig: Export-Regel ungetestet) behoben, r2 approve (opus)
Änderung:
- `EnrollRequest` (`enrollment.rs:52-56`) bekommt `replaces` (nur serialisiert, wenn gesetzt).
- `enroll_with_token` (`:252-277`) liest vor `redeem` den Fingerprint des gespeicherten Leafs (der Fullchain beginnt mit
  dem Leaf; `tofu::fingerprint`, SHA-256 über DER) und schickt ihn mit. `export_browser_p12` (`:608-639`) schickt nie
  `replaces`, jeder Export ist ein eigenes Gerät.
- `reset_device_identity` (`commands.rs:93-98`) wird async. Ist das Gerät registriert, ruft es zuerst
  `POST /api/enrollment/self/revoke` über den mTLS-Client auf, vor `clear_identity` (`enrollment.rs:229-235`), das den
  Client-Cache leert. Dann löscht es lokal.
  - Rückgabe: ob am Server widerrufen wurde.
  - Schlägt der Widerruf fehl, merkt sich der Desktop den Fingerprint und schickt ihn beim nächsten Registrieren als
    `replaces`.
- **Tests** (Rust, in der Datei, Closures wie `replace_identity` `:176-188`):
  - der Body mit und ohne `replaces`;
  - Widerruf vor dem Löschen;
  - nach einem gescheiterten Widerruf trägt das nächste Registrieren den gemerkten Fingerprint;
  - der Export schickt keinen.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: keine (Doku in T14)
Abhängt von: T6

### T9 — Desktop-UI: Hinweise zu Widerruf und gesperrtem Zertifikat (R-0224)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/bridge/index.ts, apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/components/Login.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/lib/utils/errors.ts, apps/desktop/ui/src/components/Login.revoked.test.ts, apps/desktop/ui/src/components/SettingsModal.enroll.test.ts, apps/desktop/ui/src/components/Login.binding.test.ts, apps/desktop/ui/src/components/Login.mtls.test.ts, apps/desktop/ui/src/components/Login.trust.test.ts, CHANGELOG.md, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/bridge/types.parity.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped · contracts: 1 ok @e14f3cb8 2026-10-11T12:21:09+02:00
Review: request_changes (opus, 1 wichtig: Ursache im Nur-lokal-Hinweis) behoben, r2 approve (opus)
Änderung:
- `resetDeviceIdentity` (`bridge/index.ts:93-95`) gibt das Ergebnis aus T8 zurück.
- Einstellungen (`SettingsModal.svelte:121-144`) und Login zeigen nach dem Zurücksetzen, ob am Server widerrufen wurde
  oder nur lokal.
- Der Login zeigt für `ERR_CERT_REVOKED` einen Hinweis mit „Geräte-Identität zurücksetzen“, nach dem Muster von
  `ERR_CERT_USER_MISMATCH`. `ERROR_CODES` (`errors.ts:14-15`) bekommt den Code.
- Texte DE und EN in `dictionaries.ts`.
- Die bestehenden Tests geben im Mock von `resetDeviceIdentity` das Ergebnis zurück.
- **Tests** in `Login.revoked.test.ts` (neu, SPDX):
  - Hinweis und Zurücksetzen ohne den Code;
  - der Hinweis „nur lokal“ in Login und Einstellungen.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: CHANGELOG (Changed); Admin-Doku in T14
Abhängt von: T8

### T10 — Agent: Neu-Provisionieren nennt das vorige Zertifikat (R-0224, R-0280)  [ ]
Komponente: agent · Dateien: apps/agent/internal/enroll/enroll.go, apps/agent/internal/provision/provision.go, apps/agent/internal/provision/provision_test.go, apps/agent/internal/enroll/client.go
Änderung:
- `enroll.Request` (`enroll.go:46-49`) bekommt `Replaces` mit `json:"replaces,omitempty"`.
- `runEnrollment` (`provision.go:240-266`) liest vor `Submit` das Leaf aus `agent.crt`, wenn `enroll.Provisioned(dir)`,
  und schickt dessen Fingerprint (SHA-256 über DER, hex klein, wie `provision.go:218-219`).
- Nachgetragen beim Bau (R-0280, Aufsicht 2026-10-11): Der Hinweis bei abgelaufenem Leaf (`client.go:36`) nennt den
  Befehl, den es gibt: `adminhelper-agent provision --url … --token … --server-id …` statt `enroll --token`.
- **Tests:**
  - Mit vorhandener Identität trägt der Body den Fingerprint des alten Leafs, ohne Identität fehlt das Feld.
  - Muster: `httptest`-Server und `t.Setenv("ADMINHELPER_MONITOR_DIR", t.TempDir())`.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (Doku in T14)
Abhängt von: T3

### T11 — Stack-Test: Erneuern, Ablösen und Selbst-Widerruf über das Gateway (R-0224)  [ ]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh, scripts/tests/stack_pytest.sh
Änderung:
- `integration_stack_test.sh` bekommt nach Schritt 8 (`:146-166`), vor dem Enroll-Burst (`:168`), einen Schritt 8b:
  1. zweites Token für `admin`;
  2. Enroll eines zweiten Schlüssels mit `replaces` = Fingerprint des ersten Zertifikats;
  3. Renew mit dem ersten Zertifikat 403, mit dem neuen ok;
  4. das erste Zertifikat mit JWT auf `/api/servers` 403 mit `ERR_CERT_REVOKED`;
  5. Selbst-Widerruf mit dem neuen 204, danach mit ihm 403.
  - Spätere Schritte, die ein Zertifikat brauchen, bekommen ein frisches.
  - Kopfliste (`:10-15`) und der Kommentar „steps 1-9“ (`:194-195`) ziehen nach.
- `stack_pytest.sh` (`:100-102`) fährt den Postgres-Fall aus T4 als eigenen Schritt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test)
Abhängt von: T4, T5, T6

### T12 — Desktop-E2E: Nach dem Zurücksetzen ist das vorige Gerät gesperrt (R-0224)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/settings-enroll.live.js, apps/desktop/e2e/test/lib/live.js
Änderung: Im dritten Fall von `settings-enroll.live.js` (`:102-134`, Zurücksetzen bei laufendem Tunnel, dann neu
registrieren) fragt die Spec die Geräteliste des Admins ab (`GET /api/users/{id}/devices`):
- Vor dem Zurücksetzen gibt es eine aktive Linie.
- Danach ist sie gesperrt (`self`), und nach dem Neu-Registrieren gibt es eine neue aktive.
- Ein Node-Helfer in `live.js` ruft die API mit dem Admin-JWT auf, nach dem Muster von `injectEvent`.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T6, T8

### T13 — Doku: ADR und Entwickler-Doku zum Register (R-0224)  [ ]
Komponente: scripts · Dateien: docs/adr/0001-unified-pki-and-secure-deployment.md, docs/developer/index.html, docs/en/developer/index.html, docs/developer/server.html, docs/en/developer/server.html
Änderung:
- **ADR 0001:** Statuszeile D4 (`:36`). §3.4 (`:170-184`):
  - Der Widerruf wirkt pro Gerät (Linie) und pro Benutzer als Zeitpunkt.
  - Das Neuanlegen räumt nichts mehr (`:180-181`).
  - Die Grenze (`:182-184`) wird neu gefasst: Server und Issuer prüfen pro Zertifikat. Der TLS-Handshake am Gateway und
    frps prüfen weiter nur die Kette (frp kann keine CRL, V2 `:247-251`).
  - Den Übergang beschreibt ein Satz.
- **Entwickler-Doku (DE+EN):**
  - `index.html`, Abschnitt PKI und mTLS (DE `:101-110`, EN `:79-88`): das Register, `replaces` und der Selbst-Widerruf.
  - `server.html`, Schema-Liste (`:145-154`): die drei Tabellen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die Task ist die Doku
Abhängt von: T5, T6

### T14 — Doku: Admin-Doku zu Geräten, Widerruf und Übergang (R-0224, R-0279)  [ ]
Komponente: scripts · Dateien: docs/admin/benutzer.html, docs/en/admin/users.html, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, docs/admin/betrieb.html, docs/en/admin/operations.html, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html
Änderung (DE und EN):
- `benutzer.html` / `users.html`:
  - Löschen sperrt alle Zertifikate des Benutzers, auch nach einem Neuanlegen gleichen Namens.
  - Geräte lassen sich einzeln per API widerrufen.
  - „Geräte-Identität zurücksetzen“ widerruft am Server; Neu-Registrieren löst das vorige Zertifikat dieses Geräts ab.
- `troubleshooting.html`: ein Eintrag für `ERR_CERT_REVOKED` (Gerät zurücksetzen, neu registrieren) und für den Hinweis
  „nur lokal zurückgesetzt“.
- `betrieb.html` / `operations.html`: der Übergang. Zertifikate von vor dem Update gelten 90 Tage ab dem Update und
  werden beim ersten Kontakt erfasst. Eine `.p12`, die in der Zeit nicht benutzt wurde, wird danach neu exportiert.
- `agent-deployment.html`: Neu-Provisionieren ersetzt Zertifikat und API-Key des bisherigen Agents.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die Task ist die Doku
Abhängt von: T7, T9
