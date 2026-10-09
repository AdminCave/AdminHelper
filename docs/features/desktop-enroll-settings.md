<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Gerät registrieren aus den Einstellungen (R-0212, R-0220, R-0222)

## Problem / Motivation

Seit ADR 0003 und R-0040 (#85) registriert sich der Desktop nur mit einem Einmal-Token, den ein Admin ausstellt. Den
Einstieg gibt es nur auf dem Login-Screen (`Login.svelte:259`, „Erstes Mal? Gerät mit Token einrichten“). Wer im
Modus `server` ohne erzwungenes mTLS angemeldet ist und noch keine Identität hat, erreicht ihn nur über Abmelden.
Genau diese Nutzer treffen auf den Hinweis aus R-0203, sobald sie einen Tunnel starten (`frpc.rs:111`).

Dazu kommen die Texte rund ums Zurücksetzen der Identität. Sie sagen „anmelden / registrieren“, obwohl Anmelden
nichts registriert:
- Hinweis `settings.resetDeviceId.hint`: `dictionaries.ts:214`, EN `:809`.
- Bestätigung `settings.resetDeviceId.confirm`: `:216`, EN `:811`.
- Erfolgsmeldung `settings.resetDeviceId.done`: `:218`, EN `:813`.

Die Erfolgsmeldung sieht heute niemand. `onResetDeviceIdentity` setzt erst `deviceEnrolled = false`
(`SettingsModal.svelte:129`) und dann die Meldung (`:130`). Diese steht aber im Block `{#if mode === 'server' &&
deviceEnrolled}` (`:360`), der im selben Moment verschwindet.

In der Triage vom 2026-10-08 kamen zwei Funde aus der Erkundung zu diesem Vorhaben dazu:
- **R-0220:** `enroll_with_token` über eine vorhandene Identität (heute nur über das Login-Formular) schreibt erst
  den neuen Schlüssel, dann das Zertifikat (`store_identity`, `enrollment.rs:156-164`, aufgerufen aus `:243`). Ein Abbruch dazwischen
  hinterlässt den neuen Schlüssel neben dem alten Zertifikat. Unter erzwungenem mTLS sperrt sich das Gerät damit aus.
- **R-0222:** Bei erzwungenem mTLS antwortet das Gateway einem Gerät ohne Identität schon auf den Login mit 400. Der
  Login zeigt dann nur „Login fehlgeschlagen (400 …)“ mit dem Rumpf der Fehlerseite (`auth.rs:49-55`), aber keinen
  Weg zum Token.

## Ziel und Nicht-Ziele

**Ziel:**
- Ein angemeldeter Nutzer ohne Identität registriert sein Gerät in den Einstellungen mit einem Einmal-Token, ohne
  sich abzumelden. Danach startet der Tunnel.
- Die Texte zum Zurücksetzen und Registrieren nennen den Weg, den es gibt, mit einem Begriff je Sprache.
- Die Meldung nach dem Zurücksetzen wird sichtbar.
- Eine Registrierung über eine vorhandene Identität hinterlässt nie ein unpassendes Paar aus Schlüssel und
  Zertifikat (R-0220).
- Verlangt der Server ein Geräte-Zertifikat, sagt der Login das und führt zum Token-Formular (R-0222).

**Nicht-Ziele:**
- Kein neuer Tauri-Command, keine Server- und keine Gateway-Arbeit.
- Kein „Neu registrieren“ über eine vorhandene Identität in den Einstellungen; der Weg ist „zurücksetzen, dann
  registrieren“.
- Keine Selbstbedienung ohne Admin-Token (ADR 0003, R-0040; der Endpoint dafür bleibt wie bei R-0204 zurückgehalten).
- Keine Status-Zeile mit Name und Ablaufdatum der Identität; sie steht als eigene FEAT-Zeile in der Roadmap.
- Das Login-Formular bleibt, wie es ist, bis auf seine Texte und den Hinweis aus R-0222.
- Die datierte News auf der Startseite (`docs/index.html:413`, EN `:411`) bleibt, wie sie ist. Sie beschreibt das
  damalige Release.

## Heutiger Stand

**Registrierung im UI.** Alles liegt inline in `Login.svelte`:
- `mode = 'login' | 'enroll'` (`:20`) wird über `switchMode` umgeschaltet (`:38`).
- Der Link hat `data-action="enroll-switch"` (`:259`).
- Bei Erfolg zeigt es `login.enroll.done` und springt zurück zum Login (`:127`).
- Fehler laufen über `surfaceError` (`:133`), mit Trust-Dialog bei `ERR_TLS_UNKNOWN_ISSUER` (`:135`).
- Der Wrapper ist `enrollWithToken(serverUrl, token, allowSelfSigned?)` in `lib/bridge/index.ts:106`. Er ruft den
  Command `enroll_with_token` auf (`commands.rs:103`).

**Einstellungen.** `components/SettingsModal.svelte` ist ein Overlay ohne Tabs. Es ist nur aus der App-Shell
erreichbar, im Modus `server` also nur mit Session.
- `deviceEnrolled` liest `isDeviceEnrolled()` bei jedem Öffnen neu (`:91`).
- Davon hängt nur der Reset-Block ab (`:360`).
- Den Browser-Export (A5c) gibt es (`:322`). Seit #96 (R-0219) verlangt er 12 Zeichen wie das Backend.

**Was die Bridge über die Identität verrät.** `is_device_enrolled` liefert nur ein Bool, nämlich „Schlüssel und
Zertifikat liegen im Keyring“ (`enrollment.rs:178-180`). Dazu kommt `pinned_ca_fingerprint`. Name und Ablaufdatum
der Identität erreicht die UI heute nicht.

**Was `enroll_with_token` mit einer vorhandenen Identität tut.** Es erzeugt einen neuen Schlüssel (`:233`), löst den
Token ein und schreibt dann über `store_identity` (`:156-164`) Schlüssel, Zertifikat und CA-Kette nacheinander in
den Keyring. Rückfrage gibt es keine, eine zweite Identität daneben auch nicht. Der Keyring kann kein Paar atomar
tauschen. Die Erneuerung (`renew`, `:348`) umgeht das, indem sie den Schlüssel behält (`csr_for_existing_key`,
`:126-135`). `clear_identity` (`:205-211`) löscht alle drei Einträge.

**Was der Login bei erzwungenem mTLS sieht.** Mit `MTLS_ENFORCE=true` setzt das Gateway `ssl_verify_client on`
(`apps/gateway/docker-entrypoint.sh:39`). Für einen Client ohne Zertifikat kennt nginx den
Fehler 496 („a client has not presented the required certificate“, nginx-Doku `ngx_http_ssl_module`, „Error
Processing“). Ausgeliefert wird er als Status 400 mit der Standardseite „400 No required SSL certificate was sent“
(nginx-Quelltext `src/http/ngx_http_special_response.c`, `ngx_http_error_496_page` und `NGX_HTTPS_NO_CERT` →
`NGX_HTTP_BAD_REQUEST`). ADR 0001 (A8-Enforcement) hielt genau diese Antwort am 2026-06-12 gegen den laufenden Stack
fest; seitdem ist sie nicht erneut geprüft. `login` (`auth.rs:34`) macht daraus
`Login fehlgeschlagen (<status>): <Rumpf>` (`:49-55`).

**Tests:**
- `components/Login.trust.test.ts` ist das Muster für den Login. Es nutzt `vi.mock('$lib/bridge')`, `vi.hoisted`
  und spricht Elemente über `data-action` an.
- `components/SettingsModal.export.test.ts` (seit #96) ist das Muster für die Einstellungen: Bridge, Session und
  `@tauri-apps/plugin-dialog` gemockt.
- `lib/bridge/ipc.inventory.test.ts` verlangt für jeden registrierten Command einen `invoke` in `bridge/index.ts`.
  Ein zweiter Aufrufer des bestehenden Wrappers ändert daran nichts.
- Die Rust-Tests in `enrollment.rs` laufen ohne Keyring; `renew_reuses_the_existing_key` (`:636`) prüft die
  Schlüsselwahl an der reinen Funktion. Für die Schreibfolge gibt es keinen Test.
- Die Live-E2E zur Registrierung decken nur den Login-Screen ab: `enroll-form.live.js` mit ungültigem Token,
  `enroll-trust-dialog.live.js`. Den Erfolgsfall gibt es nur per direktem `invoke`, in `tunnel-start.live.js`.
- `desktop_e2e_tunnel.sh` läuft ohne Erzwingung (`e2e_init false`, `:39`) und mintet einen Token über
  `python -m app.cli mint-enroll-token` (`:55`). `run.sh e2e` nimmt jedes `scripts/tests/desktop_e2e_*.sh` mit.

## Entwurf

**Ort.** Im Identitäts-Block der Einstellungen (`SettingsModal.svelte:360`), im Modus `server`:
- **ohne Identität:** ein Hinweis, das Feld „Enrollment-Token“ und der Knopf „Gerät registrieren“;
- **mit Identität:** wie heute „Geräte-Identität zurücksetzen“.

In `local` und `sync` erscheint der Block nicht, dort gibt es nichts zu registrieren.

**Ablauf in den Einstellungen.**
1. Der Knopf ruft `enrollWithToken(<Server-URL der Session>, token, allowSelfSignedCerts)` auf. Die Einstellung
   „Selbstsignierte erlauben“ steht im selben Overlay.
2. Bei Erfolg ist das Gerät registriert, das Feld leert sich, eine Meldung erscheint, und der Block zeigt das
   Zurücksetzen. Danach startet die Einstellung den Tunnel über `startIfServerMode()` (`lib/stores/tunnel.ts:36`),
   denn frpc liest die Identität nur beim Start (`export_identity`, `frpc.rs:123`). Vorher stoppt sie einen noch
   laufenden Tunnel (`stop()`): Das Zurücksetzen leert den Keyring, nicht den frpc-Prozess, und ein Start neben dem
   laufenden scheitert an „frpc laeuft bereits“ (`start_frpc`). Ohne laufenden frpc ist das Stoppen ein No-op.
3. Ein Fehler erscheint inline, wie die anderen Fehler der Einstellungen; der Tunnel startet dann nicht.
4. Die Erfolgsmeldung des Zurücksetzens steht außerhalb des Identitäts-Zweigs und wird damit sichtbar. Nach dem
   Zurücksetzen erscheint im selben Block das Token-Feld.

Die Registrierung selbst braucht keinen Login, sie läuft über Port 8444. Nicht verifiziert ist, ob die App bei
erzwungenem mTLS nach dem Zurücksetzen angemeldet bleibt, wenn API-Aufrufe scheitern. Fällt sie auf den Login
zurück, führt dort der Hinweis aus R-0222 zum Token-Formular.

**Schreibfolge beim Registrieren (R-0220).** `enroll_with_token` löst zuerst den Token ein. Erst danach löscht es die
alte Identität, das Zertifikat zuerst, dann schreibt es Schlüssel, CA-Kette und zuletzt das Zertifikat. Als registriert
gilt das Gerät (`is_enrolled`: Schlüssel und Zertifikat) damit erst, wenn alles liegt, und nach dem ersten Löschen
nicht mehr (`replace_identity`).
- Schlägt das Löschen fehl, bricht es vor dem Schreiben ab.
- Ein Abbruch nach dem Löschen lässt das Gerät ohne Identität zurück, nie mit einem unpassenden Paar. Mit einem
  neuen Token registriert es sich dann wieder, in den Einstellungen oder auf dem Login-Screen.
- Den Schlüssel übernimmt `enroll_with_token` nicht, anders als `renew`. Ein fehlender Eintrag beim Löschen (erste
  Registrierung) ist kein Fehler.
- Die Erneuerung bleibt, wie sie ist.

**Hinweis beim Login (R-0222).** `login` erkennt genau die Antwort von nginx: Status 400 und im Rumpf
„No required SSL certificate was sent“. Daraus wird ein fester Code nach dem Muster von `ERR_TLS_UNKNOWN_ISSUER`:
`ERR_MTLS_CERT_REQUIRED: …`, gefolgt von einer englischen Erklärung. Jede andere Antwort bleibt wie heute.
- Der Login leitet die Prüfung aus dem Fehlertext ab (`$derived`, wie die Pin-Prüfungen daneben), nicht aus einem
  Zweig in `surfaceError`. So greift sie auch beim Wiederholen nach dem Vertrauensdialog, das den Fehler direkt setzt.
- Bei diesem Code zeigt er einen eigenen Hinweis (`login.mtlsRequired`, DE und EN), nicht den rohen Text.
- Daneben steht ein Knopf, der zum Token-Formular wechselt (`switchMode('enroll')`). Der gleich beschriftete Knopf
  unter dem Formular entfällt, solange der Hinweis steht.
- Ändert nginx den Text, fällt der Login auf die heutige Meldung zurück; er bricht nicht.

**Texte, DE und EN:**
- Deutsch durchgehend „registrieren“ statt „enrollen“ oder „einrichten“; „Enrollment-Token“ bleibt, so heißt es
  in API und `install.sh`.
- Englisch durchgehend „Reset device identity“.
- Hinweis, Bestätigung und Meldung des Zurücksetzens nennen den Einmal-Token vom Admin und den Eintrag in den
  Einstellungen statt „anmelden“.
- Der Login-Link heißt „Gerät mit Token registrieren“ / „Enroll this device with a token“, ohne „Erstes Mal?“: Nach
  einem Zurücksetzen ist es nicht das erste Mal.
- Die Doku-Stellen, die diese Labels zitieren, ziehen mit.

**Kein neuer Command.** Wiederverwendet werden `enrollWithToken`, `isDeviceEnrolled`, `startIfServerMode` und `stop`
(der Command `stop_tunnel`). Das
IPC-Inventar und der Typ-Paritätstest bleiben unverändert.

## Betroffene Komponenten und Dateien

- `apps/desktop/ui/src/components/SettingsModal.svelte`: der Identitäts-Block, der Tunnelstart.
- `apps/desktop/ui/src/components/Login.svelte`: der Hinweis bei `ERR_MTLS_CERT_REQUIRED`.
- `apps/desktop/ui/src/lib/i18n/dictionaries.ts`: neue Schlüssel `settings.enroll.*` und `login.mtlsRequired`, neue
  Texte für `settings.resetDeviceId.*`, `login.enroll.*` und `login.resetDeviceId` (DE und EN).
- `apps/desktop/src-tauri/src/enrollment.rs`: die Schreibfolge in `enroll_with_token`.
- `apps/desktop/src-tauri/src/auth.rs`: die Fehlerabbildung im Login.
- Neu: `apps/desktop/ui/src/components/SettingsModal.enroll.test.ts` und `Login.mtls.test.ts` (vitest, SPDX).
- Neu: `apps/desktop/e2e/test/specs/settings-enroll.live.js` (SPDX), angemeldet in
  `scripts/tests/desktop_e2e_tunnel.sh`, mit einem zweiten Token.
- Doku:
  - `docs/admin/benutzer.html` / `docs/en/admin/users.html`;
  - `docs/admin/troubleshooting.html` / EN;
  - `docs/admin/installation.html` / EN (das Label dort passt heute nicht zur UI);
  - `docs/admin/betrieb.html` / `docs/en/admin/operations.html` und `README.md` (zitieren das Login-Label);
  - `docs/developer/desktop.html` / EN;
  - dazu `CHANGELOG.md`.

## Datenmodell / API / Migrationen

Keine. Kein Server-Endpoint, keine Migration, kein neuer Tauri-Command, keine Änderung an `capabilities/`. Zwischen
Rust und UI kommt ein Fehlercode dazu (`ERR_MTLS_CERT_REQUIRED`). Er reist wie `ERR_TLS_UNKNOWN_ISSUER` im Text des
Fehlers, nicht in einem eigenen Typ.

## Trade-offs und Alternativen

- **Ort:**
  - Der Identitäts-Block, entschieden: kleinster Eingriff, Registrieren und Zurücksetzen liegen beieinander.
  - Ein eigener Abschnitt „Geräte-Identität“ mit Status, Registrieren, Zurücksetzen und Browser-Export baut die
    Ansicht sichtbar um und lohnt erst mit einer Status-Zeile.
- **Neu registrieren über eine vorhandene Identität:** entschieden ist „nur zurücksetzen, dann registrieren“, also
  ein Weg ohne stillen Wechsel der Identität. „Neu registrieren nach Bestätigung“ wäre ein zweiter Weg mit eigenen
  Zuständen und Tests.
- **Schreibfolge (R-0220):**
  - „Erst löschen, dann schreiben“, entschieden: Ein unpassendes Paar entsteht nie. Schlimmstenfalls braucht das
    Gerät einen neuen Token.
  - Den vorhandenen Schlüssel wiederverwenden wie `renew`: Bei einem Abbruch bliebe die alte Identität intakt, aber
    alte und neue Identität teilten den Schlüssel.
  - Ein unpassendes Paar erst beim Laden erkennen: repariert hinterher, verhindert nichts.
- **Erkennen des mTLS-400 (R-0222):**
  - Rust erkennt genau die nginx-Antwort, entschieden: präzise und als reine Funktion testbar.
  - Jede 400 ohne Identität in der UI als Hinweis zu deuten, wäre eine Heuristik.
  - Eine eigene JSON-Antwort des Gateways wäre der sauberste Vertrag, aber eine Gateway-Änderung.
- **Status-Zeile:** „Registriert als X bis Y“ braucht einen neuen Command mit Struct in `models.rs`, Interface in
  `types.ts`, Wrapper und Inventar-Eintrag. Sie steht als eigene FEAT-Zeile in der Roadmap.

## Risiken und Rollback

- **Ein Token für einen anderen Benutzer** registriert das Gerät unter dessen Namen; der Name kommt aus dem Token.
  Die Einstellungen zeigen ihn ohne Status-Zeile nicht an.
- **Das Login-Formular** überschreibt eine vorhandene Identität weiter, jetzt aber ohne unpassendes Paar (R-0220).
  Die Einstellungen bieten das Überschreiben nicht an.
- **Ein Abbruch nach dem Löschen** (R-0220) lässt das Gerät ohne Identität. Der eingelöste Token ist verbraucht,
  es braucht einen neuen vom Admin.
- **Der Text der nginx-Seite** (R-0222) ist die einzige Kopplung an das Gateway. Ändert er sich, zeigt der Login die
  heutige Meldung. Ein Test hält den erkannten Text fest.
- **Rollback:** die Commits zurücknehmen. Daten und Keyring bleiben unberührt.

## Doku-Impact

- `benutzer.html` / `users.html`: ein Satz, dass ein angemeldeter Nutzer sein Gerät in den Einstellungen registriert.
- Die Stellen, die „neu anmelden/registrieren“ sagen oder Labels wörtlich zitieren: `troubleshooting`,
  `installation`, `developer/desktop.html`, jeweils DE und EN.
- `troubleshooting.html` / EN: ein Eintrag zum Login-Hinweis bei erzwungenem mTLS (R-0222).
- Der CHANGELOG unter Added (der Eintrag in den Einstellungen) und Fixed (die unsichtbare Meldung, R-0220, R-0222).

## Entscheidungen (2026-10-09)

Kevin hat F1 bis F4 beantwortet, die Aufsicht (adminhelper-ac) F5 bis F7 und die Teststrategie; alle wie empfohlen.

1. **Was die Einstellungen zeigen** (Kevin): ohne Identität das Token-Feld „Gerät registrieren“, mit Identität nur
   „Zurücksetzen“; kein „Neu registrieren“. In `local` und `sync` nichts.
2. **Tunnel** (Kevin): nach erfolgreicher Registrierung automatisch starten.
3. **Status-Zeile** (Kevin): nicht jetzt, eigene FEAT-Zeile.
4. **Begriffe** (Kevin): ein Begriff je Sprache wie unter „Texte“; die Doku, die Labels zitiert, zieht mit.
5. **Schreibfolge, R-0220** (Aufsicht): erst die alte Identität löschen, dann schreiben; den Schlüssel nicht
   wiederverwenden.
6. **mTLS-400, R-0222** (Aufsicht): Rust erkennt genau die nginx-Antwort und meldet `ERR_MTLS_CERT_REQUIRED`; der
   Login zeigt Hinweis und Knopf. Keine Gateway-Änderung.
7. **News auf der Startseite** (Aufsicht): bleibt unverändert.

**Teststrategie** (Aufsicht): Für R-0222 reichen Unit-Tests, in Rust (Status und Rumpf ergeben den Code) und als
Komponententest im Login. Heavy bleibt `linux-full` für die Desktop-Journey. Ein Multibox-Lauf mit `--enforce`, der
den Hinweis live zeigen könnte, ist nicht eingeplant. Er bliebe ask-first.

**Nachbesserung aus dem Branch-Review** (Aufsicht, 2026-10-09): Die Reihenfolge „Tunnel stoppen, dann starten“ nach
einem Zurücksetzen prüft heute nur der Komponententest. Die Live-E2E setzt die Identität vor dem Login zurück, dort
läuft noch kein frpc. Eine Live-E2E für diese Journey steht als eigene Roadmap-Zeile.
