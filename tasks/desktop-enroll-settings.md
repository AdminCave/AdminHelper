<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Gerät registrieren aus den Einstellungen — Task-Ledger
Status: geplant · Branch: feature/desktop-enroll-settings · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/desktop-enroll-settings.md (Roadmap R-0212)
Heavy: linux-full — eine Desktop-Journey ändert sich (Registrierung aus den Einstellungen); `run.sh integration` und die Desktop-E2E mit `settings-enroll.live.js` über `desktop_e2e_tunnel.sh` auf einer Pool-VM.
DoD je Task: CLAUDE.md (Tests grün, eslint/prettier und svelte-check sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-07 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus R-0212, von Kevin am 2026-10-07
angenommen, mit Gate bei Kevin. Das Ledger plant die Empfehlungen der offenen Fragen der Spec. Weicht Kevins Antwort
ab, ändert sich T1 bzw. entfällt T3. Kein Rust, kein Server, kein neuer Tauri-Command. Zeilenangaben main@a6e544dc.

### T1 — Einstellungen: Token-Feld im Identitäts-Block, wenn das Gerät keine Identität hat  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/SettingsModal.enroll.test.ts, CHANGELOG.md, docs/admin/benutzer.html, docs/en/admin/users.html
Änderung: Der Block `{#if mode === 'server' && deviceEnrolled}` (`SettingsModal.svelte:355`) wird `{#if mode === 'server'}`:
- **mit Identität:** wie heute das Zurücksetzen;
- **ohne Identität:** ein Hinweis, das Token-Feld und der Knopf.
Der Knopf ruft `enrollWithToken(<Server-URL der Session>, token, allowSelfSignedCerts)` über die Bridge
(`lib/bridge/index.ts:106`). Bei Erfolg setzt er `deviceEnrolled = true`, leert das Feld und zeigt `settings.enroll.done`.
Ein Fehler erscheint wie die anderen Fehler der Einstellungen. Die Erfolgsmeldung des Zurücksetzens wandert aus dem
Identitäts-Zweig, damit sie sichtbar wird.
Texte: neue Schlüssel `settings.enroll.hint` und `settings.enroll.done` (DE und EN). Wiederverwendet werden
`login.enroll.token`, `.token.placeholder`, `.submit` und `.working`.
Test, neue Datei mit SPDX-Kopf (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later`), nach dem Muster
von `Login.trust.test.ts` (Bridge gemockt, Elemente über `data-action`):
- ohne Identität erscheint das Feld;
- der Knopf ruft `enrollWithToken` mit URL, Token und Einstellung;
- nach Erfolg erscheint das Zurücksetzen samt Meldung;
- ein Fehler erscheint inline, das Feld bleibt;
- mit Identität gibt es kein Feld;
- nach dem Zurücksetzen ist die Meldung sichtbar und das Feld erscheint.
Doku: In `benutzer.html` / `users.html` ein Satz, dass ein angemeldeter Nutzer sein Gerät unter Einstellungen
registriert; dazu CHANGELOG unter Added (der Eintrag) und Fixed (die unsichtbare Meldung).
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: docs/admin/benutzer.html + docs/en/admin/users.html · CHANGELOG.md

### T2 — Texte: Zurücksetzen nennt den Token-Weg, ein Begriff für Registrieren  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/i18n/dictionaries.ts, docs/admin/benutzer.html, docs/en/admin/users.html, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, docs/admin/installation.html, docs/en/admin/installation.html, docs/developer/desktop.html, docs/en/developer/desktop.html
Änderung (nach offener Frage 6):
- `settings.resetDeviceId.hint`, `.confirm` und `.done` (DE `dictionaries.ts:214–219`, EN `:809–813`) nennen den
  Einmal-Token vom Admin und den Eintrag in den Einstellungen statt „anmelden / registrieren“.
- Deutsch durchgehend „registrieren“: `login.enroll.submit`, `.working`, `.done`, `login.resetDeviceId`.
- Englisch durchgehend „Reset device identity“ (`login.resetDeviceId`, EN `:902`).
- Der Login-Link `login.enroll.switch` heißt „Gerät mit Token registrieren“ / „Enroll this device with a token“.
Die Doku-Stellen, die diese Labels zitieren oder „neu anmelden/registrieren“ sagen, ziehen mit:
- `benutzer.html:93` / `users.html:87`;
- `troubleshooting.html:73` / EN `:74`;
- `installation.html:99` / EN `:76`, wo das Label heute nicht zur UI passt;
- `developer/desktop.html:129` / EN `:129`.
Test: Die i18n-Parität (`lib/i18n/i18n.test.ts`) deckt die Schlüssel ab. Die Komponententests sprechen Elemente über
`data-action` an und hängen nicht am Wortlaut.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: benutzer/users · troubleshooting · installation · developer/desktop (je DE + EN)
Abhängt von: T1

### T3 — Nach der Registrierung den Tunnel starten  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/components/SettingsModal.enroll.test.ts
Änderung: Nur bei Ja zu offener Frage 4, sonst `ledger.sh mark-skip` mit Verweis auf die Antwort. Nach erfolgreicher
Registrierung startet die Einstellung den Tunnel über `startIfServerMode()` (`lib/stores/tunnel.ts:36`), weil frpc
die Identität nur beim Start liest (`frpc.rs:220`). Test: Nach Erfolg wird `startIfServerMode` gerufen, nach einem
Fehler nicht.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: keine (der Satz in benutzer/users aus T1 reicht)
Abhängt von: T1

### T4 — Live-E2E: Registrierung aus den Einstellungen  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/settings-enroll.live.js, scripts/tests/desktop_e2e_tunnel.sh
Änderung: Neue Spec mit SPDX-Kopf. Der Ablauf:
1. Die Spec setzt eine vorhandene Identität über die Bridge (`reset_device_identity`) zurück, nicht über den nativen
   Dialog.
2. Sie meldet sich an, öffnet die Einstellungen, gibt den Token ein und registriert.
3. Sie prüft, dass danach das Zurücksetzen erscheint (bei T3 auch, dass der Tunnel startet).

`desktop_e2e_tunnel.sh` mintet dafür einen zweiten Einmal-Token (`python -m app.cli mint-enroll-token`, wie
`:55`), denn jeder Token gilt nur einmal, und meldet die Spec an. Der Orchestrator läuft ohne Erzwingung
(`e2e_init false`), das ist das Szenario von R-0212.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict (Lint; der echte Lauf ist die Heavy-Zeile)
Doku: keine (Test)
Abhängt von: T1
