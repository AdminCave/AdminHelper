<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop-Einstellungen: Statuszeile „Registriert als X bis Y“ (R-0240)

## Problem / Motivation

Ist das Gerät registriert, zeigen die Einstellungen der Desktop-App nur „zurücksetzen“
(`apps/desktop/ui/src/components/SettingsModal.svelte:405-413`). Für wen das Gerät registriert ist und wie lange
das Zertifikat gilt, sieht niemand. Der Command `is_device_enrolled` (`apps/desktop/src-tauri/src/commands.rs:82`)
liefert nur ein Bool, und `is_enrolled()` (`apps/desktop/src-tauri/src/enrollment.rs:211`) prüft nur, ob Schlüssel
und Zertifikat im Keyring liegen.

Das versteckt zwei echte Fehlerbilder:

- **Abgelaufen:** `is_enrolled` bleibt `true`. Die Erneuerung beim Anmelden weist sich mit dem abgelaufenen
  Zertifikat aus und scheitert, das steht nur im Log. Jeder mTLS-Request scheitert.
- **Erneuerung scheitert still:** Native Leafs gelten 90 Tage; erneuert wird ab der Hälfte der Laufzeit beim
  Anmelden (`enrollment.rs:76`), ein Fehlschlag ist nur `log::warn`. Wer 14 Tage vor Ablauf noch das alte
  Zertifikat hat, bei dem scheitert die Erneuerung seit etwa einem Monat.

R-0212 hat die Zeile als Nicht-Ziel zurückgestellt (`docs/features/desktop-enroll-settings.md:49`); Kevin hat sie
am 2026-10-09 als eigene Zeile angelegt.

## Ziel & Nicht-Ziele

**Ziel:** Im Identitäts-Block der Einstellungen (nur `mode === 'server'` mit Session, nur mit Identität) steht eine
Zeile mit Name und Ablauf des Geräte-Zertifikats, in vier Zuständen (Kevin, 2026-10-15):

| Zustand | DE | EN |
|---|---|---|
| gültig | „Registriert als **{name}** bis {date}“ | „Enrolled as **{name}** until {date}“ |
| ≤ 14 Tage Rest | dazu: „läuft bald ab — die automatische Erneuerung beim Anmelden ist bisher nicht gelungen“ | „expires soon — the automatic renewal at sign-in has not succeeded yet“ |
| abgelaufen (Warnung) | „Registriert als **{name}**, abgelaufen am {date} — zurücksetzen und mit neuem Token registrieren“ | „Enrolled as **{name}**, expired on {date} — reset and enroll with a new token“ |
| unlesbar | „Geräte-Zertifikat nicht lesbar — zurücksetzen und neu registrieren“ | „Device certificate unreadable — reset and enroll again“ |

`{date}` ist nur das Datum in lokaler Zeit, `toLocaleDateString(currentLocale(), {day:'2-digit', month:'2-digit',
year:'numeric'})` (13.01.2027 bzw. 13/01/2027). Ohne Identität gibt es keine Zeile; der Hinweis zum Token-Feld steht
dort schon. Die Zeile lädt beim Öffnen, nach dem Registrieren und nach dem Zurücksetzen neu.

**Nicht-Ziele:** keine Änderung an der Erneuerung selbst (wann, wie, Fehlerweg); kein Abgleich des Namens mit dem
angemeldeten Benutzer (die Zeile „Angemeldet als“ steht direkt darüber, und unter `MTLS_ENFORCE=true` meldet der
Server ohnehin `ERR_CERT_USER_MISMATCH`); kein Ersatz für `is_device_enrolled` (davon hängen
`apps/desktop/e2e/test/lib/live.js:43` und 13 vitest-Fälle ab); keine Server-, Issuer- oder Gateway-Änderung.

## Betroffene Komponenten & Dateien

- **desktop-rs:** `enrollment.rs` (Leaf aus `enroll|cert` lesen wie `leaf_fingerprint` `:235`, CN und `not_after`
  mit `x509-parser 0.18` wie `needs_renewal` `:491`; neuer Helfer, den `needs_renewal` mitbenutzt), `models.rs`
  (Struct `DeviceIdentity` neben `PasswordState`), `commands.rs` (Command `device_identity` nach dem Vorbild
  `pinned_ca_fingerprint` `:75`), `main.rs` (`use`-Liste `:31` und `generate_handler!` `:112`).
- **desktop-ui:** `src/lib/bridge/types.ts` (Interface), `src/lib/bridge/index.ts` (Wrapper `deviceIdentity()`),
  `src/components/SettingsModal.svelte` (Zeile nach dem Vorbild `sm-session-row` `:358`, Neuladen an `:139`/`:158`),
  `src/lib/i18n/dictionaries.ts` (DE ab `:222`, EN ab `:838`), neue Tests `SettingsModal.identity.test.ts`, die
  Bridge-Mocks in `SettingsModal.enroll.test.ts` und `SettingsModal.export.test.ts`.
- **desktop-e2e:** `apps/desktop/e2e/test/specs/settings-enroll.live.js` (nach `registerInSettings` `:41`).

## Datenmodell / API / Migrationen

Neuer Tauri-Command `device_identity() -> Result<Option<DeviceIdentity>, AppError>`:

- `None`, wenn Schlüssel oder Zertifikat fehlen (dieselbe Regel wie `is_enrolled`);
- `Some(DeviceIdentity { name, not_after })` mit `name` = CN des Leafs (der Issuer setzt ihn auf die Subject-ID,
  `apps/ca-issuer/app/issuer.py:119`) und `not_after` als RFC-3339-String in UTC (Vorbild `frpc.rs:308`);
- `Err`, wenn das Zertifikat nicht parst oder keinen CN hat; die UI zeigt dann den festen Text „nicht lesbar“, nie
  den Rohfehler.

Serde `camelCase` (`notAfter`); IPC-Inventar (`ipc.inventory.test.ts`) und Paritätstest (`types.parity.test.ts`)
verlangen Registrierung, Aufrufer in `index.ts` und das TS-Gegenstück in derselben Änderung. Kein Server-Vertrag,
keine Migration.

## Externe Integrationen

Tauri v2, „Calling Rust from the Frontend“ (https://v2.tauri.app/develop/calling-rust/): Rückgabewerte und Fehler
müssen `serde::Serialize` implementieren; ein einziger `invoke_handler`. Dass `Option::None` als `null` ankommt, ist
nur durch das Vorbild im Repo (`pinned_ca_fingerprint`) belegt, in der Doku nicht verifiziert.

## Trade-offs & Alternativen

- **Neuer Command statt `is_device_enrolled` erweitern** (empfohlen): Der alte bleibt für E2E-Helfer und 13
  vitest-Fälle; die Kosten sind ein zweiter IPC-Aufruf beim Öffnen. Erweitern hieße, alle Aufrufer umzubauen.
- **Zustände im Frontend aus `notAfter` ableiten** (empfohlen) statt eines Zustands-Enums aus Rust: Der
  Paritätstest liest nur Unit-Varianten, und „bald“/„abgelaufen“ hängen an der Uhr der Anzeige.
- **Uhrzeit weglassen:** Bei 90 Tagen Laufzeit ist sie Rauschen (Kevin).

## Risiken & Rollback

Nur lesend auf dem Keyring; ein Fehler im Parsen zeigt „nicht lesbar“, ändert aber keinen Zustand. Rollback: Revert
des Merge-Commits. Risiko: ein Bridge-Mock ohne `deviceIdentity` lässt den try/catch still „nicht lesbar“ zeigen; die
Mocks der bestehenden Modal-Tests werden deshalb mitgezogen.

## Doku-Impact

Sichtbare Änderung: Benutzer-Doku DE `docs/admin/benutzer.html` (Registrieren in den Einstellungen, `:97`) und EN
`docs/en/admin/users.html` (`:91`); Entwickler-Doku `docs/developer/desktop.html:86` und
`docs/en/developer/desktop.html:86` (Command-Tabelle); CHANGELOG unter Added.

## Offene Fragen

Keine. Textform, Datumsformat, Abgelaufen, Bald-ablaufend (≤ 14 Tage) und Unlesbar hat Kevin am 2026-10-15
entschieden.
