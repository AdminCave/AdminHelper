<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-Einstellungen: Statuszeile „Registriert als X bis Y“ — Task-Ledger
Status: geplant · Branch: feature/device-identity-status · Review: pro Task
Spec: docs/features/device-identity-status.md (Roadmap R-0240)
Heavy: linux-full — Desktop-Journey: `settings-enroll.live.js` prüft die neue Zeile gegen den echten Issuer und Keyring; läuft im Sammellauf (`/feature-build` §5)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Command `device_identity`: Name und Ablauf aus dem Geräte-Zertifikat  [ ]
Komponente: desktop · Dateien: apps/desktop/src-tauri/src/enrollment.rs, apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/main.rs, apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/bridge/index.ts, docs/developer/desktop.html, docs/en/developer/desktop.html
Änderung: `enrollment.rs` liest den Leaf aus `enroll|cert` (wie `leaf_fingerprint` `:235`) und gibt CN und `not_after` (RFC 3339, UTC) zurück; `None` ohne Schlüssel oder Zertifikat wie `is_enrolled` (`:211`), Fehler bei unlesbarem PEM oder fehlendem CN; `needs_renewal` (`:491`) nutzt denselben Leaf-Helfer. Struct `DeviceIdentity` (serde camelCase, `pub`-Felder) in `models.rs`, Command `device_identity` in `commands.rs` nach dem Vorbild `pinned_ca_fingerprint` (`:75`), registriert in `main.rs` (`:31`, `:112`); TS-Interface und Wrapper `deviceIdentity()` in `bridge/`. cargo-Tests mit rcgen-Zertifikaten und In-Memory-Keyring: CN und `not_after` aus einer Fullchain, kein CN und Müll-PEM → Fehler, fehlender Schlüssel oder fehlendes Zertifikat → `None`, camelCase auf der Leitung. IPC-Inventar und Parität laufen in der vitest-Suite mit.
Verify: bash scripts/dev/verify.sh desktop --strict
Doku: docs/developer/desktop.html + docs/en/developer/desktop.html (Command-Tabelle `:86`)

### T2 — Statuszeile im Einstellungs-Modal, vier Zustände  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/SettingsModal.svelte, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/SettingsModal.identity.test.ts, apps/desktop/ui/src/components/SettingsModal.enroll.test.ts, apps/desktop/ui/src/components/SettingsModal.export.test.ts, docs/admin/benutzer.html, docs/en/admin/users.html, CHANGELOG.md
Änderung: Im Identitäts-Zweig (`SettingsModal.svelte:405`) eine Zeile nach dem Vorbild `sm-session-row` (`:358`) mit den vier Zuständen aus der Spec (gültig, ≤ 14 Tage Rest, abgelaufen als Warnung, unlesbar mit festem Text), Datum per `toLocaleDateString(currentLocale(), …)`; der Aufruf von `deviceIdentity()` steht im try/catch (der Mount-Smoke-Test lässt jede Bridge-Funktion werfen). Neu laden beim Öffnen, nach dem Registrieren (`:158`) und nach dem Zurücksetzen (`:139`). i18n-Schlüssel DE und EN (`dictionaries.ts:222` / `:838`). Neue Datei `SettingsModal.identity.test.ts` (SPDX-Header): die vier Zustände mit `vi.setSystemTime`, keine Zeile ohne Identität, Zeile nach dem Registrieren, weg nach dem Zurücksetzen; die Bridge-Mocks der beiden bestehenden Modal-Tests bekommen `deviceIdentity`.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: docs/admin/benutzer.html (`:97`) + docs/en/admin/users.html (`:91`) · CHANGELOG (Added)
Abhängt von: T1

### T3 — Live-E2E: die Zeile zeigt den echten Namen und ein künftiges Datum  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/settings-enroll.live.js
Änderung: Nach `registerInSettings` (`:41`) prüfen, dass die Zeile „admin“ und ein Datum in der Zukunft zeigt; nach Zurücksetzen und erneutem Registrieren (`:128`) noch einmal. Der echte Beweis (Issuer-CN, Keyring, Parsen zusammen) kommt aus dem Sammellauf; das Verify hier ist der Lint der E2E-Specs.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Test)
Abhängt von: T2
