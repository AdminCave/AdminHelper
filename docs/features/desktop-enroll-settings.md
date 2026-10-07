<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Gerät registrieren aus den Einstellungen (R-0212)

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
(`SettingsModal.svelte:129`) und dann die Meldung. Diese steht aber im Block `{#if mode === 'server' &&
deviceEnrolled}` (`:355`), der im selben Moment verschwindet.

## Ziel und Nicht-Ziele

**Ziel:**
- Ein angemeldeter Nutzer ohne Identität registriert sein Gerät in den Einstellungen mit einem Einmal-Token, ohne
  sich abzumelden.
- Die Texte zum Zurücksetzen und Registrieren nennen den Weg, den es gibt.
- Die Meldung nach dem Zurücksetzen wird sichtbar.

**Nicht-Ziele:**
- Kein neuer Tauri-Command und keine Rust-Änderung, keine Server-Arbeit.
- Keine Selbstbedienung ohne Admin-Token (der Endpoint dafür bleibt wie bei R-0204 zurückgehalten).
- Keine Status-Zeile mit Name und Ablaufdatum der Identität (offene Frage 3).
- Kein eigener Fehlercode für „mTLS erzwungen, kein Zertifikat“ beim Login.
- Das Login-Formular bleibt, wie es ist, bis auf seine Texte.

## Heutiger Stand

**Registrierung im UI.** Alles liegt inline in `Login.svelte`:
- `mode = 'login' | 'enroll'` (`:20`) wird über `switchMode` umgeschaltet (`:38`).
- Der Link hat `data-action="enroll-switch"` (`:259`).
- Das Token-Formular steht bei `:269`.
- Bei Erfolg zeigt es `login.enroll.done` und springt zurück zum Login (`:126`).
- Fehler laufen über `surfaceError` (`:133`), mit Trust-Dialog bei `ERR_TLS_UNKNOWN_ISSUER`.
- Der Wrapper ist `enrollWithToken(serverUrl, token, allowSelfSigned?)` in `lib/bridge/index.ts:106`. Er ruft den
  Command `enroll_with_token` auf (`commands.rs:103`).

**Einstellungen.** `components/SettingsModal.svelte` ist ein Overlay ohne Tabs. Es ist nur aus der App-Shell
erreichbar, im Modus `server` also nur mit Session.
- `deviceEnrolled` liest `isDeviceEnrolled()` bei jedem Öffnen neu (`:91`).
- Davon hängt nur der Reset-Block ab (`:355`).
- Den Browser-Export (A5c) gibt es (`:318`).

**Was die Bridge über die Identität verrät.** `is_device_enrolled` liefert nur ein Bool, nämlich „Schlüssel und
Zertifikat liegen im Keyring“. Dazu kommt `pinned_ca_fingerprint`. Name und Ablaufdatum der Identität erreicht die UI
heute nicht.

**Was `enroll_with_token` mit einer vorhandenen Identität tut.** Es erzeugt einen neuen Schlüssel, löst ein und
überschreibt die Einträge im Keyring: erst den Schlüssel, dann das Zertifikat (`enrollment.rs:157`). Rückfrage gibt
es keine, eine zweite Identität daneben auch nicht.

**Tests:**
- `components/Login.trust.test.ts` ist das Muster für Komponententests. Es nutzt `vi.mock('$lib/bridge')`,
  `vi.hoisted` und spricht Elemente über `data-action` an.
- Für `SettingsModal` gibt es nur den Mount-Smoke (`mount.smoke.test.ts`). Ein Aufruf beim Öffnen braucht dort
  `try/catch`, wie schon `isDeviceEnrolled`.
- `lib/bridge/ipc.inventory.test.ts` verlangt für jeden registrierten Command einen `invoke` in `bridge/index.ts`.
  Ein zweiter Aufrufer des bestehenden Wrappers ändert daran nichts.
- Die Live-E2E zur Registrierung decken nur den Login-Screen ab: `enroll-form.live.js` mit ungültigem Token,
  `enroll-trust-dialog.live.js`. Den Erfolgsfall gibt es nur per direktem `invoke`, in `tunnel-start.live.js`
  und `live.js` (`enrollIfAsked`).
- `desktop_e2e_tunnel.sh` läuft ohne Erzwingung (`e2e_init false`) und mintet einen Token über
  `python -m app.cli mint-enroll-token` (`:55`).

## Entwurf (die Empfehlungen der offenen Fragen)

**Ort.** Im Identitäts-Block der Einstellungen (`SettingsModal.svelte:355`), im Modus `server`:
- **ohne Identität:** ein Hinweis, das Feld „Enrollment-Token“ und der Knopf „Gerät registrieren“;
- **mit Identität:** wie heute „Geräte-Identität zurücksetzen“.

Beides sind zwei Seiten derselben Sache und stehen deshalb am selben Platz. Andere Orte wären ein eigener Abschnitt
„Geräte-Identität“ oder der Bereich mit dem Browser-Export; beide sind unten unter Alternativen abgewogen.

**Ablauf.**
1. Der Knopf ruft `enrollWithToken(<Server-URL der Session>, token, allowSelfSignedCerts)` auf. Die Einstellung
   „Selbstsignierte erlauben“ steht im selben Overlay.
2. Bei Erfolg ist das Gerät registriert, das Feld leert sich, eine Meldung erscheint, und der Block zeigt das
   Zurücksetzen (Frage 4: danach den Tunnel starten).
3. Ein Fehler erscheint inline, wie die anderen Fehler der Einstellungen.
4. Die Erfolgsmeldung des Zurücksetzens steht außerhalb des Identitäts-Zweigs und wird damit sichtbar. Nach dem
   Zurücksetzen erscheint im selben Block das Token-Feld.

**Neu registrieren** über eine vorhandene Identität bieten die Einstellungen nicht an (Frage 2). Der Weg ist
„zurücksetzen, dann registrieren“, beides im selben Block. Die Registrierung selbst braucht keinen Login, sie läuft
über Port 8444. Nicht verifiziert ist, ob die App bei erzwungenem mTLS nach dem Zurücksetzen angemeldet bleibt, wenn
API-Aufrufe scheitern. Fällt sie auf den Login zurück, bleibt dort der bisherige Weg.

**Texte, DE und EN** (Frage 6):
- Deutsch durchgehend „registrieren“ statt „enrollen“ oder „einrichten“; „Enrollment-Token“ bleibt, so heißt es
  in API und `install.sh`.
- Englisch durchgehend „Reset device identity“.
- Hinweis, Bestätigung und Meldung des Zurücksetzens nennen den Einmal-Token vom Admin und den Eintrag in den
  Einstellungen statt „anmelden“.
- Der Login-Link verliert „Erstes Mal?“: Nach einem Zurücksetzen ist es nicht das erste Mal.

**Kein neuer Command.** Wiederverwendet werden `enrollWithToken` und `isDeviceEnrolled`. Das IPC-Inventar und der
Typ-Paritätstest bleiben unverändert.

## Betroffene Komponenten und Dateien

- `apps/desktop/ui/src/components/SettingsModal.svelte`: der Identitäts-Block.
- `apps/desktop/ui/src/lib/i18n/dictionaries.ts`: neue Schlüssel `settings.enroll.*` und neue Texte für
  `settings.resetDeviceId.*` und `login.enroll.*` (DE und EN).
- Neu: `apps/desktop/ui/src/components/SettingsModal.enroll.test.ts` (vitest, SPDX).
- Neu: `apps/desktop/e2e/test/specs/settings-enroll.live.js` (SPDX), angemeldet in
  `scripts/tests/desktop_e2e_tunnel.sh`, mit einem zweiten Token.
- Doku: `docs/admin/benutzer.html` / `docs/en/admin/users.html`, `docs/admin/troubleshooting.html` / EN,
  `docs/admin/installation.html` / EN (das Label dort passt heute nicht zur UI), `docs/developer/desktop.html` /
  EN, dazu `CHANGELOG.md`.

## Datenmodell / API / Migrationen

Keine. Kein Server-Endpoint, keine Migration, kein neuer Tauri-Command, keine Änderung an `capabilities/`.
Der Vertrag zwischen UI und Rust bleibt gleich.

## Trade-offs und Alternativen

- **Ort:**
  - Der Identitäts-Block ist die Empfehlung: kleinster Eingriff, Registrieren und Zurücksetzen liegen beieinander.
  - Ein eigener Abschnitt „Geräte-Identität“, der Status, Registrieren, Zurücksetzen und Browser-Export bündelt,
    baut die Ansicht sichtbar um und lohnt erst mit einer Status-Zeile.
  - Der Bereich mit dem Browser-Export hängt am Login. Die Registrierung braucht keinen, die Kopplung wäre also
    willkürlich.
- **Neu registrieren über eine vorhandene Identität:**
  - „Nur zurücksetzen, dann registrieren“ ist die Empfehlung: keine Rust-Änderung, kein stiller Wechsel der Identität.
  - „Neu registrieren nach Bestätigung“ wäre bequemer, verlangt aber eine Rust-Änderung. Beim Überschreiben würde der
    Schlüssel wiederverwendet, damit ein Abbruch zwischen den Schreibvorgängen kein unpassendes Paar hinterlässt.
- **Status-Zeile:** „Registriert als X bis Y“ braucht einen neuen Command mit Struct in `models.rs`, Interface in
  `types.ts`, Wrapper und Inventar-Eintrag. Er ist testbar als reine Funktion über das Zertifikat, wie
  `needs_renewal`. Das lohnt als eigenes Vorhaben.
- **Nur Admin-Token oder Selbstbedienung über die Session:** Nur Token passt zu ADR 0003 und R-0040. Selbstbedienung
  bräuchte wieder einen Rust-Command wie das entfernte `enroll_device` und berührt R-0204.

## Risiken und Rollback

- **Der Token für einen anderen Benutzer** registriert das Gerät unter dessen Namen; der Name kommt aus dem Token.
  Die Einstellungen zeigen ihn ohne Status-Zeile nicht an.
- **Das Login-Formular** überschreibt eine vorhandene Identität weiter wie heute. Die Einstellungen bieten das nicht
  an.
- **Rollback:** die Commits zurücknehmen. Daten und Keyring bleiben unberührt, denn die Einstellungen rufen nur den
  Command, den es schon gibt.

## Doku-Impact

- `benutzer.html` / `users.html`: ein Satz, dass ein angemeldeter Nutzer sein Gerät in den Einstellungen registriert.
- Die Stellen, die „neu anmelden/registrieren“ sagen oder Labels wörtlich zitieren: `troubleshooting`,
  `installation`, `developer/desktop.html`, jeweils DE und EN.
- Der CHANGELOG unter Added (der Eintrag) und Fixed (die unsichtbare Meldung).

## Offene Fragen (am Gate, sichtbares Verhalten: Kevin)

1. **Wann erscheint der Eintrag?** Empfehlung: im Modus `server`, solange das Gerät keine Identität hat. In `local`
   und `sync` nicht, dort gibt es nichts zu registrieren.
2. **Was bei vorhandener Identität?** Empfehlung: nur Zurücksetzen; danach erscheint das Token-Feld. Alternative:
   „Neu registrieren“ nach Bestätigung, mit einer Rust-Änderung, damit das Überschreiben den Schlüssel wiederverwendet.
3. **Status-Zeile „registriert als X bis Y“?** Empfehlung: nicht in diesem Vorhaben, sondern als eigene Zeile. Dafür
   braucht es einen neuen Command.
4. **Nach erfolgreicher Registrierung den Tunnel starten?** Empfehlung: ja. Viele kommen über den Tunnel-Hinweis hierher,
   und der Tunnel liest die Identität nur beim Start.
5. **Nur Admin-Token, keine Selbstbedienung über die Session?** Empfehlung: nur Token, wie ADR 0003 und R-0040.
6. **Begriffe:**
   - Deutsch durchgehend „registrieren“, „Enrollment-Token“ bleibt.
   - Englisch „Reset device identity“ statt daneben „Reset device enrollment“.
   - Der Login-Link heißt „Gerät mit Token registrieren“ / „Enroll this device with a token“, ohne „Erstes Mal?“.

   Empfehlung: ja. Die Doku-Stellen, die Labels zitieren, ziehen mit.
7. **Die datierte News auf der Startseite** (`docs/index.html:413`, EN `:410`) sagt, das Gerät registriere sich beim
   nächsten Verbinden neu. Das galt bis R-0040. Empfehlung: unverändert lassen, sie beschreibt das damalige Release.
