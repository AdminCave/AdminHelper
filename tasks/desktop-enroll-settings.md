<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Gerät registrieren aus den Einstellungen — Task-Ledger
Status: aktiv · Branch: feature/desktop-enroll-settings · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Freigabe: Kevin, 2026-10-09 (Stufen-Plan, im Chat mit der Aufsicht; F1–F4 Kevin, F5–F7 und Teststrategie Aufsicht, siehe Spec „Entscheidungen (2026-10-09)“)
Spec: docs/features/desktop-enroll-settings.md (Roadmap R-0212, R-0220, R-0222)
Heavy: linux-full — eine Desktop-Journey ändert sich (Registrierung aus den Einstellungen, danach Tunnelstart); `run.sh integration` und `run.sh e2e` mit der Desktop-GUI-E2E, darin `settings-enroll.live.js` über `desktop_e2e_tunnel.sh`, auf einer Pool-VM. Ein Multibox-Lauf mit `--enforce`, der den Login-Hinweis aus R-0222 live zeigen könnte, ist nicht eingeplant und bliebe ask-first.
DoD je Task: CLAUDE.md (Tests grün, eslint/prettier und svelte-check bzw. cargo fmt und clippy sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-07 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus R-0212, von Kevin am 2026-10-07
angenommen. Nachgezogen 2026-10-09 nach den Entscheidungen (Spec, „Entscheidungen“): F1 bis F4 Kevin, F5 bis F7 und
die Teststrategie die Aufsicht. Dazu kamen R-0220 und R-0222 aus der Triage vom 2026-10-08. Sechs Tasks, also gibt
Kevin den Plan frei. Kein neuer Tauri-Command, kein Server, kein Gateway. Zeilenangaben main@81c8efe9.

### T1 — Einstellungen: Token-Feld, wenn das Gerät keine Identität hat; danach startet der Tunnel  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/SettingsModal.enroll.test.ts, CHANGELOG.md, docs/admin/benutzer.html, docs/en/admin/users.html
Änderung (F1, F2): Der Block `{#if mode === 'server' && deviceEnrolled}` (`SettingsModal.svelte:360`) wird
`{#if mode === 'server'}`:
- **mit Identität:** wie heute das Zurücksetzen, kein „Neu registrieren“;
- **ohne Identität:** ein Hinweis, das Token-Feld und der Knopf „Gerät registrieren“.

Der Knopf ruft `enrollWithToken(<Server-URL der Session>, token, allowSelfSignedCerts)` über die Bridge
(`lib/bridge/index.ts:106`).
- **Bei Erfolg:** `deviceEnrolled = true`, das Feld leert sich, `settings.enroll.done` erscheint. Danach ruft er
  `startIfServerMode()` (`lib/stores/tunnel.ts:36`), denn frpc liest die Identität nur beim Start
  (`export_identity`, `frpc.rs:123`).
- **Bei einem Fehler:** Er erscheint wie die anderen Fehler der Einstellungen, und der Tunnel startet nicht.
- Die Erfolgsmeldung des Zurücksetzens (`:130`) wandert aus dem Identitäts-Zweig, damit sie sichtbar wird.

Texte: neue Schlüssel `settings.enroll.hint` und `settings.enroll.done` (DE und EN), schon mit „registrieren“.
Wiederverwendet werden `login.enroll.token`, `.token.placeholder`, `.submit` und `.working`.

Test, neue Datei mit SPDX-Kopf (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later`). Muster ist
`SettingsModal.export.test.ts`: Bridge, Session und Dialog gemockt, dazu `$lib/stores/tunnel`. Die Fälle:
- ohne Identität erscheint das Feld;
- der Knopf ruft `enrollWithToken` mit URL, Token und Einstellung;
- nach Erfolg erscheinen das Zurücksetzen und die Meldung, und `startIfServerMode` wurde gerufen;
- ein Fehler erscheint inline, das Feld bleibt, `startIfServerMode` wurde nicht gerufen;
- mit Identität gibt es kein Feld;
- nach dem Zurücksetzen ist die Meldung sichtbar, und das Feld erscheint.

Doku: In `benutzer.html` / `users.html` ein Satz, dass ein angemeldeter Nutzer sein Gerät unter Einstellungen
registriert. Dazu CHANGELOG unter Added (der Eintrag samt Tunnelstart) und Fixed (die unsichtbare Meldung).
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: docs/admin/benutzer.html + docs/en/admin/users.html · CHANGELOG.md

### T2 — Texte: Zurücksetzen nennt den Token-Weg, ein Begriff je Sprache  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/i18n/dictionaries.ts, docs/admin/benutzer.html, docs/en/admin/users.html, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, docs/admin/installation.html, docs/en/admin/installation.html, docs/developer/desktop.html, docs/en/developer/desktop.html
Änderung (F4):
- `settings.resetDeviceId.hint`, `.confirm` und `.done` (DE `dictionaries.ts:214-219`, EN `:809-813`) nennen den
  Einmal-Token vom Admin und den Eintrag in den Einstellungen statt „anmelden / registrieren“.
- Deutsch durchgehend „registrieren“: `login.enroll.submit` (`:302`), `.working` (`:303`), `.done` (`:305`),
  `login.resetDeviceId` (`:308`). „Enrollment-Token“ bleibt.
- Englisch durchgehend „Reset device identity“ (`login.resetDeviceId`, EN `:902`).
- Der Login-Link `login.enroll.switch` (DE `:299`, EN `:893`) heißt „Gerät mit Token registrieren“ / „Enroll this
  device with a token“, ohne „Erstes Mal?“.

Die Doku-Stellen, die diese Labels zitieren oder „neu anmelden/registrieren“ sagen, ziehen mit:
- `benutzer.html:93` / `users.html:87`;
- `troubleshooting.html:73` / EN `:74`;
- `installation.html:99` / EN `:76`, wo das Label heute nicht zur UI passt („Mit Token enrollen“ / „Enroll with
  token“);
- `developer/desktop.html:129` / EN `:129`.

Test: Die i18n-Parität (`lib/i18n/i18n.test.ts`) deckt die Schlüssel ab. Kein Test prüft den Wortlaut dieser Texte;
die Komponententests sprechen Elemente über `data-action` an.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: benutzer/users · troubleshooting · installation · developer/desktop (je DE + EN)
Abhängt von: T1

### T3 — R-0220: Registrierung über eine vorhandene Identität löscht erst, dann schreibt  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/enrollment.rs, CHANGELOG.md
Änderung (F5): Heute schreibt `enroll_with_token` (`enrollment.rs:228-244`) über `store_identity` (`:156-164`) erst
den neuen Schlüssel, dann Zertifikat und CA-Kette. Ein Abbruch dazwischen lässt den neuen Schlüssel neben dem alten
Zertifikat zurück.
Künftig:
- `enroll_with_token` löst zuerst den Token ein.
- Danach löscht es die Einträge der alten Identität (Schlüssel, Zertifikat, CA). Ein fehlender Eintrag ist kein
  Fehler; `keyring_store::delete` behandelt das unter Unix und Windows schon so.
- Schlägt das Löschen fehl, bricht es vor dem Schreiben ab.
- Erst dann schreibt es Schlüssel, Zertifikat und CA-Kette.
- Den Schlüssel übernimmt es nicht. Die Erneuerung (`renew`, `:348`) bleibt, wie sie ist.

Test: Der Keyring fehlt in den Rust-Tests. Die Folge steht deshalb in einer Funktion, die Löschen und Setzen als
Parameter bekommt; `enroll_with_token` reicht `keyring_store::delete` und `set` hinein. Ein Test zeichnet die Aufrufe
auf und bricht nach jedem Schritt ab. Er verlangt:
- es gibt nie den neuen Schlüssel neben dem alten Zertifikat;
- ein Abbruch nach dem Löschen hinterlässt keine Identität;
- ein Fehler beim Löschen schreibt nichts;
- ohne alte Identität (alles fehlt) endet die Folge mit dem vollständigen neuen Paar.

`renew_reuses_the_existing_key` (`:636`) bleibt grün.
CHANGELOG unter Fixed, eine Zeile: Eine Registrierung über eine vorhandene Identität hinterlässt bei einem Abbruch
kein unpassendes Paar mehr, sondern schlimmstenfalls ein Gerät ohne Identität, das einen neuen Token braucht.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: CHANGELOG.md

### T4 — R-0222: Der Login erkennt die nginx-400 ohne Zertifikat und meldet `ERR_MTLS_CERT_REQUIRED`  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/auth.rs
Änderung (F6): Der Fehlerzweig von `login` (`auth.rs:49-55`) läuft über eine reine Funktion aus Status und Rumpf.
- Status 400 und im Rumpf „No required SSL certificate was sent“ ergeben
  `AppError::Validation("ERR_MTLS_CERT_REQUIRED: <englische Erklärung>")`. Der Code ist fest, die Erklärung darf
  sich ändern, wie bei `ERR_TLS_UNKNOWN_ISSUER` (`error.rs`).
- Jede andere Antwort bleibt `Login fehlgeschlagen (<status>): <Rumpf>`, mit `redact_body` wie heute.

Das ist die Standardseite von nginx für Fehler 496 („a client has not presented the required certificate“), die als
400 ausgeliefert wird (`src/http/ngx_http_special_response.c`, `ngx_http_error_496_page`). Gegen den Stack ist das
nicht verifiziert.

Test in `auth.rs` (Teststrategie der Aufsicht: Unit-Tests reichen):
- 400 mit der nginx-Seite ergibt den Code;
- 400 mit anderem Rumpf und 401 ergeben die heutige Meldung;
- derselbe Text unter einem anderen Status ergibt ebenfalls die heutige Meldung.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: keine (die sichtbare Wirkung beschreibt T5)

### T5 — R-0222: Der Login zeigt bei `ERR_MTLS_CERT_REQUIRED` Hinweis und Knopf zum Token-Formular  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/Login.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/Login.mtls.test.ts, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, CHANGELOG.md
Änderung (F6): `surfaceError` (`Login.svelte:133`) erkennt `ERR_MTLS_CERT_REQUIRED` wie schon `ERR_TLS_UNKNOWN_ISSUER`
(`:135`).
- Statt des rohen Texts zeigt es den Hinweis `login.mtlsRequired` (DE und EN): Der Server verlangt ein
  Geräte-Zertifikat; das Gerät registriert sich mit einem Einmal-Token vom Admin.
- Daneben steht ein Knopf mit eigenem `data-action`, der zum Token-Formular wechselt (`switchMode('enroll')`, `:38`).
- Andere Fehler zeigen weiter den Text.

Test, neue Datei mit SPDX-Kopf, nach dem Muster von `Login.trust.test.ts`:
- `login` scheitert mit dem Code: Der Hinweis erscheint, der Code nicht, und der Knopf öffnet das Token-Formular;
- ein anderer Fehler zeigt den Text und keinen Hinweis.

Doku:
- In `troubleshooting.html` / EN ein Eintrag: Meldet der Login, der Server verlange ein Geräte-Zertifikat, ist mTLS
  erzwungen; das Gerät registriert sich mit einem Einmal-Token vom Admin.
- CHANGELOG unter Fixed.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: docs/admin/troubleshooting.html + docs/en/admin/troubleshooting.html · CHANGELOG.md
Abhängt von: T4

### T6 — Live-E2E: Registrierung aus den Einstellungen, danach läuft der Tunnel  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/settings-enroll.live.js, scripts/tests/desktop_e2e_tunnel.sh
Änderung: Neue Spec mit SPDX-Kopf. Der Ablauf:
1. Die Spec setzt eine vorhandene Identität über die Bridge (`reset_device_identity`) zurück, nicht über den nativen
   Dialog.
2. Sie meldet sich an, öffnet die Einstellungen, gibt den Token ein und registriert.
3. Sie prüft, dass danach das Zurücksetzen erscheint und die Tunnel-Anzeige `connected` erreicht (`data-status`, wie
   `tunnel-start.live.js:46`).

`desktop_e2e_tunnel.sh` mintet dafür einen zweiten Einmal-Token (`python -m app.cli mint-enroll-token`, wie `:55`),
denn jeder Token gilt nur einmal, und fährt die Spec. Der Orchestrator läuft ohne Erzwingung (`e2e_init false`,
`:39`); das ist das Szenario von R-0212.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict (Lint; der echte Lauf ist die Heavy-Zeile)
Doku: keine (Test)
Abhängt von: T1
