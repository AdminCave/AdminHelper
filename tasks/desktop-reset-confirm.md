<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: Rückfragen zum Zurücksetzen im App-Dialog — Task-Ledger
Status: geplant · Branch: feature/desktop-reset-confirm · Review: am Ende
Spec: Roadmap R-0395
Heavy: linux-full — Desktop-Journeys (Geräte-Identität und Pin zurücksetzen, Login-Screen); `settings-enroll.live.js` läuft im Sammellauf (`desktop_e2e_tunnel.sh`); keine Plattform- oder Rust-Änderung, daher kein `windows`
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-16: `/feature-plan --kurz R-0395` (Fund aus der Installation v0.45.0 auf Fedora). Am Gate entschieden: Die drei Rückfragen bestätigt künftig der App-eigene `confirmDialog` (`components/ui/ConfirmDialog.svelte`), den die Monitoring-Modals schon beim Löschen nutzen, nicht mehr der native Dialog aus `@tauri-apps/plugin-dialog`. Es braucht keine neue Tauri-Berechtigung, die Unit-Tests kommen ohne Plugin-Mock aus, und der Live-Test klickt den Knopf samt Bestätigung. Sichtbar: ein In-App-Modal statt des OS-Dialogs. Den Bestätigungstext behalten die bisherigen i18n-Schlüssel, der Bestätigungsknopf trägt den bisherigen Dialogtitel (etwa „Geräte-Identität zurücksetzen“). Aus einem offenen Modal (Einstellungen) aufgerufen, schließt Escape nur den obersten Dialog (`Modal.svelte:13-17`, `modalStack`), wie bei `MaintenanceModal.svelte:139`.

### T1 — Login-Screen: Rückfragen im App-Dialog  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/App.svelte, apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/components/Login.svelte, apps/desktop/ui/src/components/Login.binding.test.ts, apps/desktop/ui/src/components/Login.revoked.test.ts, apps/desktop/ui/src/components/Login.pin.test.ts, apps/desktop/ui/src/components/Login.mtls.test.ts, apps/desktop/ui/src/components/Login.trust.test.ts
Änderung: `<ConfirmDialog />` wandert von `AppShell.svelte:302` nach `App.svelte`, außerhalb des `{#if}`, damit ihn auch der Login-Screen hat. `Login.svelte` ruft an beiden Stellen (`:81` Pin/CA-Pin mit MITM-Warnung, `:120` `resetIdentity`) `confirmDialog` statt `confirm` aus `@tauri-apps/plugin-dialog` (Import `:18` fällt weg). Die Login-Tests mocken statt des Plugins das Modul `./ui/ConfirmDialog.svelte` (`confirmDialog`). Neuer Test: Der Reset-Knopf bei `ERR_CERT_REVOKED` öffnet die Rückfrage; Bestätigen ruft `resetDeviceIdentity`, Abbrechen ruft es nicht. Die Änderungen an den übrigen Testdateien sind nur der Mock-Tausch.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/Login
Doku: keine (intern; „mit Gefahren-Bestätigung“ in `docs/developer/desktop.html:131` stimmt weiter)
Beweis: Kevin 2026-10-16, Installation v0.45.0 auf Fedora: „Geräte-Identität zurücksetzen“ und „Pin zurücksetzen“ ohne Reaktion, Ausweg nur `secret-tool clear`. main@aa7decf6: `apps/desktop/src-tauri/capabilities/default.json` erlaubt nur `dialog:allow-save`. Lokal an den gepinnten Versionen nachgelesen: `@tauri-apps/plugin-dialog` 2.7.1 `dist-js/index.js:199-210` `confirm` ruft `messageCommand`; Crate `tauri-plugin-dialog` 2.7.1 (`Cargo.lock`) `permissions/confirm.toml`: `allow-confirm` erlaubt `commands.allow = ["message"]`. Das `await confirm(…)` steht vor dem `try` (`Login.svelte:81`, `:120`, `SettingsModal.svelte:172`), die Ablehnung verschwindet still. Die Unit-Tests mocken das Plugin und sehen es deshalb nicht.
Dedup-Key: bug:desktop:capabilities/default.json:dialog-allow-message
HEAD: aa7decf6
Semantik: docs/developer/desktop.html:131 — „Den UI-Button <em>„Geräte-Identität zurücksetzen"</em> gibt es an zwei Orten: in den Einstellungen (Server-Modus, nur sichtbar wenn registriert und angemeldet; mit Gefahren-Bestätigung) und auf dem Login-Screen bei <code>ERR_CA_PIN_MISMATCH</code> (ebenfalls mit Gefahren-Bestätigung), <code>ERR_CERT_USER_MISMATCH</code> und <code>ERR_CERT_REVOKED</code> (mit Bestätigung).“

### T2 — Einstellungen: Rückfrage im App-Dialog, Export nennt die Ursache, Vertragstest der Dialog-Berechtigungen  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/components/SettingsModal.identity.test.ts, apps/desktop/ui/src/components/SettingsModal.export.test.ts, apps/desktop/ui/src/components/SettingsModal.enroll.test.ts, apps/desktop/ui/src/capabilities.test.ts, CHANGELOG.md
Änderung: `onResetDeviceIdentity` (`SettingsModal.svelte:172`) ruft `confirmDialog`; aus dem Import `:28` fällt `confirm` weg, `save` bleibt. Der Browser-Export (`:249`, `catch` ohne Fehler) zeigt hinter `settings.browserCert.error` die Ursache (`errMsg(err)`), wie die übrigen Fehlerpfade des Modals. Tests: Rückfrage bestätigen → `resetDeviceIdentity`, abbrechen → nicht; ein abgelehnter Export zeigt seine Ursache. Neuer Vertragstest `src/capabilities.test.ts` (SPDX-Header): Jede Funktion, die eine Datei unter `src/` aus `@tauri-apps/plugin-dialog` importiert, ist in `src-tauri/capabilities/default.json` erlaubt (`save` → `dialog:allow-save`, `open` → `dialog:allow-open`, `message`/`ask`/`confirm` → `dialog:allow-message`, `dialog:allow-ask` oder `dialog:allow-confirm`; `dialog:default` deckt alle). Die Assertion darf nicht leer sein, mindestens `save` muss gefunden werden. Auf HEAD ist der Test rot (`confirm` ohne Berechtigung), nach T1 und T2 grün. CHANGELOG unter `### Fixed`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/SettingsModal src/capabilities.test.ts
Doku: CHANGELOG.md (Fixed)
Abhängt von: T1
Orakel: contract — genutzte Dialog-Befehle gegen die Capability
Dedup-Key: bug:desktop:capabilities/default.json:dialog-allow-message

### T3 — Live-Test setzt die Identität über den Knopf zurück  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/settings-enroll.live.js
Änderung: Der dritte Schritt von `settings-enroll.live.js` (`:128`) setzt die Identität heute per `invoke('reset_device_identity')` zurück (`:139`), am Knopf vorbei; deshalb fiel der Fehler im Sammellauf nie auf. Neu: Einstellungen öffnen, „Geräte-Identität zurücksetzen“ klicken, im App-Dialog bestätigen, die Meldung `settings.resetDeviceId.done` abwarten. Die bisherigen Assertions bleiben: Widerruf durch das Gerät selbst (`revoked_reason === 'self'`), `device_identity` leer, erneute Registrierung, neuer frpc. `scripts/` bleibt unberührt.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (intern)
Abhängt von: T2
Dedup-Key: bug:desktop:capabilities/default.json:dialog-allow-message
