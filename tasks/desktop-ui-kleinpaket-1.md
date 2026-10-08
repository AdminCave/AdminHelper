<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-UI-Kleinpaket 1: Export-Passwort wie dokumentiert, ein veralteter E2E-Kommentar — Task-Ledger
Status: bereit · Branch: feature/desktop-ui-kleinpaket-1 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-08 (kleines Fund-Paket aus R-0219 und R-0221, von Kevin am 2026-10-08 in der Triage angenommen; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0219, R-0221 (Kurz-Ledger ohne Spec)
Heavy: none — eine Eingabeprüfung und zwei Texte in der Desktop-UI, dazu ein Kommentar in einer E2E-Spec; der Export-Pfad selbst und keine Journey ändern sich.
DoD je Task: CLAUDE.md (Tests grün, eslint/prettier und svelte-check sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-08 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus zwei Zeilen, die Kevin in der Triage vom
2026-10-08 angenommen hat; beide stammen aus der Erkundung zu R-0212. Zeilenangaben main@7129dc57.

### T1 — Browser-Export verlangt mindestens 12 Zeichen, wie Rust und die Doku (R-0219)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/SettingsModal.export.test.ts, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped · contracts: 1 ok @4a7d3071 2026-10-08T14:23:16+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: `onExportBrowserCert` prüft heute `browserCertPassword.length < 8` (`SettingsModal.svelte:140`). Rust verlangt
12 Zeichen (`check_export_password`, `enrollment.rs:539–540`, früh aufgerufen in `export_browser_p12`, `:582`).
- Die Prüfung zählt künftig Zeichen wie Rust (`chars().count()`, also Code Points: `[...password].length < 12`),
  nicht UTF-16-Einheiten.
- Die Texte `settings.browserCert.passwordTooShort` (DE `dictionaries.ts:228`, EN `:822`) nennen 12 Zeichen.
- Damit erreicht ein Passwort mit 8–11 Zeichen Rust nicht mehr und landet nicht in der allgemeinen Meldung
  `settings.browserCert.error` („angemeldet und Server erreichbar?“, DE `:231`, EN `:825`). Der Nutzer liest stattdessen
  „mindestens 12 Zeichen“.

Neue Testdatei mit SPDX-Kopf (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later`), nach dem Muster
von `Login.trust.test.ts` (Bridge, Session und `@tauri-apps/plugin-dialog` gemockt):
- 11 Zeichen: Die Meldung nennt 12, es öffnen sich weder der Speichern-Dialog noch `exportBrowserP12`.
- 12 Zeichen: Dialog und `exportBrowserP12` laufen.
- 6 Zeichen außerhalb der BMP (12 UTF-16-Einheiten) werden abgelehnt wie in Rust.

CHANGELOG unter `[Unreleased]` → `### Fixed`, eine Zeile.
Beweis:
- main@7129dc57 `sed -n 140p apps/desktop/ui/src/components/SettingsModal.svelte` → `if (browserCertPassword.length < 8) {`
- `sed -n 540p apps/desktop/src-tauri/src/enrollment.rs` → `if password.chars().count() < 12 {`
- Ein Passwort mit 8–11 Zeichen endet im `catch` mit `settings.browserCert.error` (`SettingsModal.svelte:161–162`).
  Gefunden von der Erkundung zu R-0212 (Worker B, 2026-10-07).

HEAD: 7129dc57
Semantik: `docs/admin/benutzer.html:77`: „Ein Passwort (mind. 12 Zeichen) vergeben und *Exportieren* klicken“; EN
`docs/en/admin/users.html:71`: „Choose a password (at least 12 characters) and click *Export*“. Die Doku stimmt, die UI
weicht ab.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: CHANGELOG.md (Fixed); benutzer/users nennen die 12 schon

### T2 — Veralteter Kommentar in `tunnel-start.live.js` (R-0221)  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/tunnel-start.live.js
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped @2c247b66 2026-10-08T14:24:04+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Der Kommentar `tunnel-start.live.js:21–23` begründet die Registrierung über die Bridge damit, das
GUI-Formular reiche das Vertrauen in selbstsignierte Zertifikate nicht durch („the GUI enroll form doesn't pass it“).
Seit `Login.svelte:116–124` reicht es `allowSelfSignedCerts` durch.
- Der Kommentar nennt den heutigen Grund: Die Registrierung ist Vorbereitung, nicht das, was die Spec prüft. Sie läuft
  über die Bridge mit ausdrücklichem Vertrauen, damit die Spec nicht von der Einstellung abhängt, die das Formular liest.
- Kein Code ändert sich.

Beweis: main@7129dc57 `sed -n 22p apps/desktop/e2e/test/specs/tunnel-start.live.js` → „(the GUI enroll form doesn't
pass it)“; `sed -n 116,124p apps/desktop/ui/src/components/Login.svelte` reicht `allowSelfSignedCerts` an
`enrollWithToken` durch.
HEAD: 7129dc57
Semantik: keine Stelle in docs/ — gesucht nach dem Vertrauen beim GUI-Enrollment; maßgeblich ist der Kommentar in
`Login.svelte:116` („Passes allowSelfSignedCerts through like the login path does“).
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Kommentar)
