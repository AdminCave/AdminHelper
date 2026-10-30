<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Desktop: Token-Abfrage im Provisionierungsbefehl, Fehler beim Zurücksetzen der Geräte-Identität

Zug `kern-desktop-2` (Roadmap R-0842, R-0871). Stand des Codes: `origin/main@94aba678`. Pfade ohne Präfix liegen
unter `apps/desktop/`.

## Problem / Motivation

1. **Provisionierungsbefehl (R-0842).** Der Provisionierungs-Tab zeigt neben dem Einzeiler (`agent-install.sh`, fragt
   den Token selbst ab, desktop-hardening-3 T9) einen zweiten Befehl für Hosts mit installiertem Paket
   (`ui/src/components/infra/tabs/ProvisioningTab.svelte:110-114`). Er übergibt den Token noch mit `--token`. Der
   Agent kann ihn seit `--token-stdin` (`apps/agent/cmd/adminhelper-agent/main.go:129-138`) auch abfragen; das
   Install-Skript nutzt das schon. Einzelheiten privat.
2. **Zurücksetzen der Geräte-Identität (R-0871, BUG).** `clear_identity` (`src-tauri/src/enrollment.rs:571-578`)
   löscht die drei Keyring-Einträge über `forget` (`:287-291`), das den Fehler von `keyring_store::delete` mit
   `let _ =` verwirft. Scheitert das Löschen, bleibt die Identität im Keyring, und `reset_device_identity` meldet
   Erfolg. `purge_identity` (`:584-591`) und `tofu::forget_pin` (R-0748) geben den Fehler schon zurück.

## Ziel & Nicht-Ziele

- Ziel: Der zweite Befehl lautet `sudo adminhelper-agent provision --url … --token-stdin --server-id … [--ca-fp …]`;
  der Token steht nur im Token-Feld des Tabs, der Hinweis nennt beide Wege.
- Ziel: Ein gescheitertes Löschen beim Zurücksetzen ist ein Fehler, den die UI zeigt; der Widerruf am Server (falls
  geschehen) steht in der Meldung.
- Nicht-Ziel: `forget` an anderen Aufrufstellen (`:482`, `KEYRING_REPLACES` nach einem Enroll) ändern; der Einzeiler
  bleibt, wie er ist.
- Nicht-Ziel: ein Rückfall auf `--token` für Agents ohne `--token-stdin` im Desktop-Befehl; ein solcher Agent
  meldet die unbekannte Option, das Paket-Update (oder der Einzeiler) hilft.

## Betroffene Komponenten & Dateien

- Desktop-UI: `ui/src/components/infra/tabs/ProvisioningTab.svelte`, `ui/src/components/infra/tabs/ProvisioningTab.test.ts`,
  `ui/src/lib/i18n/dictionaries.ts` (`infra.prov.tokenPrompt`, DE+EN).
- Desktop-Backend: `src-tauri/src/enrollment.rs` (`clear_identity`, `reset_with`, `reset_identity`),
  `src-tauri/src/commands.rs` (`reset_device_identity_in`).

## Datenmodell / API / Migrationen

Keine Migration. Tauri-IPC: `reset_device_identity` liefert bei einem gescheiterten Löschen einen Fehler (bisher nie);
Form des Fehlers wie die übrigen `AppError::Keyring`. Kein Wire-Format nach außen.

## Externe Integrationen

Keine neue. `--token-stdin` ist eine Option unseres Agents (`main.go`), kein externes Protokoll.

## Trade-offs & Alternativen

- Token per stdin statt Umgebungsvariable: der Agent kennt nur `--token`/`--token-stdin`; eine Variable bräuchte eine
  Agent-Änderung. Empfehlung: stdin.
- Fehler bei `clear_identity` vs. bestmögliches Weiterlöschen: alle drei Einträge versuchen, den ersten Fehler
  melden; so bleibt kein Eintrag nur deshalb liegen, weil ein anderer scheiterte.

## Risiken & Rollback

- Ein Agent älter als `--token-stdin` lehnt den Befehl ab (sichtbar, kein stiller Fehlschlag). Rollback: Revert.
- Der Reset meldet jetzt Fehler, die bisher verschluckt wurden; die UI-Pfade für Fehler gibt es seit kern-desktop-1
  (R-0870).

## Doku-Impact

`docs/admin/agent-deployment.html` (DE+EN) beschreibt `provision` mit `--token-stdin` schon; der Desktop-Befehl ist dort
nicht wörtlich zitiert. Änderung nur im Hinweistext des Tabs und im Changelog.

## Offene Fragen

Keine.
