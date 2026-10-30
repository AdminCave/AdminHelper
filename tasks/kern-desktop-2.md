<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-desktop-2 — Task-Ledger
Status: bereit · Branch: feature/kern-desktop-2 · Review: am Ende
Spec: docs/features/kern-desktop-2.md (Roadmap R-0842, R-0871)
Heavy: linux-full — Desktop-Journeys: Provisionierungs-Tab und Geräte-Reset
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Für alle Tasks: Zeilenangaben `origin/main@94aba678`, vor dem Schreiben neu greppen. Neue Code-Strings englisch,
CHANGELOG umlautfrei in `changelog.d/kern-desktop-2.md`. `security` zusätzlich bei T1 (SEC) und wo `review.sh risk`
es verlangt.

### T1 — Provisionierungsbefehl fragt den Token ab (R-0842)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.svelte, apps/desktop/ui/src/components/infra/tabs/ProvisioningTab.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, changelog.d/kern-desktop-2.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @d03816dc 2026-10-30T01:29:44+01:00
Review: am Ende (Branch-Review)
Änderung: Der Befehl „Nur provisionieren“ (`ProvisioningTab.svelte:110-114`) trägt `--token-stdin` statt `--token <token>`; der Hinweis `infra.prov.tokenPrompt` (DE+EN) nennt beide Wege (Skript fragt verdeckt, `provision` liest die erste Eingabezeile). Einzelheiten privat. Test zuerst rot: der Befehl enthält `--token-stdin` und nicht den Token.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/infra/tabs/ProvisioningTab.test.ts
Doku: changelog.d/kern-desktop-2.md (der Desktop-Befehl steht in docs/ nicht wörtlich)

### T2 — Zurücksetzen der Geräte-Identität meldet ein gescheitertes Löschen (R-0871)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/enrollment.rs, apps/desktop/src-tauri/src/commands.rs, changelog.d/kern-desktop-2.md, apps/desktop/src-tauri/src/launcher.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @9269f489 2026-10-30T01:42:02+01:00
Review: am Ende (Branch-Review)
Änderung: `clear_identity` (`enrollment.rs:571`) versucht alle drei Einträge und gibt den ersten Fehler von `keyring_store::delete` zurück (Löschen über einen Parameter, wie `tofu::forget_pin_with`, damit ein Test es scheitern lassen kann); `reset_with`/`reset_identity` reichen ihn als Fehler weiter, die Meldung in `reset_device_identity_in` (`commands.rs:151`) nennt einen erfolgten Widerruf am Server. Beweis: Code-Lesung `enrollment.rs:287-291` (`let _ = keyring_store::delete`). Dedup-Key: bug:desktop:enrollment.rs:clear-identity-swallows-delete. Test zuerst rot: ein scheiterndes Löschen → Fehler statt `Ok`.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- enrollment
Doku: changelog.d/kern-desktop-2.md

### T3 — Doc-Kommentare zum gescheiterten Löschen, Test für einen scheiternden Widerruf im Purge (R-0871)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/commands.rs, apps/desktop/src-tauri/src/launcher.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @2614cdeb 2026-10-30T02:01:15+01:00
Review: am Ende (Branch-Review)
Änderung: Fund der Abschlussprüfung: der Doc-Kommentar von `reset_device_identity` (`commands.rs:133`) beschreibt das Löschen noch als best effort; er nennt jetzt den Fehler eines gescheiterten Löschens (Pin bleibt, Reset wiederholbar). Der Doc von `launcher::purge` nennt, dass ein scheiternder `revoke` den Purge vor jedem Löschen stoppt; ein Test belegt das.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- launcher
Doku: keine (nur Doc-Kommentare; Changelog-Eintrag aus T2 deckt das Verhalten)
