# Desktop-Terminal: Rückfrage vor mehrzeiligem Einfügen, Rückmeldung beim Broadcast (kern-terminal-4)

Roadmap: R-1144, R-1175 (beide vor dem Release 0.47.0, R-1110).

## Problem / Motivation

- **R-1144:** Fügt man im AdminHelper-Terminal Text mit Zeilenumbrüchen ein (Rechtsklick, Strg+Umschalt+V, Menü
  des Webviews), gehen alle Zeilen sofort an die Shell. Ohne Bracketed Paste der Gegenseite läuft damit jede Zeile
  bis auf die letzte sofort. Andere Terminals (etwa Windows Terminal) fragen vorher nach; AdminHelper bietet das
  nicht an.
- **R-1175:** `runSnippet` (`apps/desktop/ui/src/lib/stores/terminals.ts:1087`) ignoriert die Zahl, die
  `bridge.terminalBroadcast` zurückgibt. Ist der Broadcast an, aber keine SSH-Sitzung läuft, passiert nach dem
  Klick auf ein Snippet sichtbar nichts.

## Ziel & Nicht-Ziele

Ziel:
- Neue Terminal-Option „Vor mehrzeiligem Einfügen fragen“ (`confirmMultilinePaste`), ab Werk aus: das bisherige
  Verhalten bleibt, bis man sie einschaltet. Ist sie an und enthält der bereinigte Text einen Zeilenumbruch, zeigt das
  Terminal eine Rückfrage im Tab (Zeilenzahl, „Einfügen“, „Abbrechen“); erst „Einfügen“ gibt den Text an das
  Terminal. Gilt für alle drei Einfüge-Wege und auch im abgelösten Terminal-Fenster.
- `runSnippet` gibt die Zahl der erreichten Sitzungen zurück; das Snippet-Panel meldet bei 0 in der Statusleiste,
  dass keine SSH-Sitzung läuft.

Nicht-Ziele: keine Prüfung, ob die Gegenseite Bracketed Paste aktiv hat; keine Rückfrage bei Snippets (die sind
mehrzeilig gewollt und eigens angelegt); keine Änderung am Broadcast selbst.

## Betroffene Komponenten & Dateien

- desktop-rs: `apps/desktop/src-tauri/src/models.rs` (`TerminalPrefs`, Default), Tests in
  `apps/desktop/src-tauri/src/storage.rs` (alte `prefs.json` ohne das Feld lädt mit `false`).
- desktop-ui: `apps/desktop/ui/src/lib/bridge/types.ts` (`TerminalPrefs`), `apps/desktop/ui/src/lib/models/settings.ts`
  (Default), `apps/desktop/ui/src/components/terminal/TerminalOptions.svelte` (Checkbox),
  `apps/desktop/ui/src/components/terminal/SshTerminal.svelte` (Rückfrage im Einfüge-Weg `paste()`),
  `apps/desktop/ui/src/lib/i18n/dictionaries.ts` (DE+EN), Tests `SshTerminal.test.ts`.
- desktop-ui: `apps/desktop/ui/src/lib/stores/terminals.ts` (`runSnippet` gibt `number | null` zurück),
  `apps/desktop/ui/src/components/terminal/SnippetsPanel.svelte` (Hinweis), Tests `terminals.test.ts`,
  `SnippetsPanel.test.ts`.

## Datenmodell / API / Migrationen

`prefs.json` bekommt `terminal.confirmMultilinePaste` (bool). `#[serde(default)]` auf `TerminalPrefs` lässt ältere
Dateien mit `false` laden; keine Migration. Kein Server-, Web- oder Agent-Vertrag.

## Externe Integrationen

Keine neuen. xterm.js `Terminal.paste()` bleibt der einzige Weg zur Sitzung (er setzt Bracketed Paste selbst, wenn
die Gegenseite es verlangt).

## Trade-offs & Alternativen

- **Rückfrage im Tab statt `ConfirmDialog`:** Den Dialog-Host hat nur `App.svelte`; das abgelöste Terminal-Fenster
  (`DetachedTerminal`) hat keinen. Eine kleine Leiste im Terminal funktioniert in beiden Fenstern. Empfehlung: im Tab.
- **Default aus:** Admins fügen oft Skripte ein, und bash ab 5.1 schaltet Bracketed Paste ein; eine Rückfrage ab
  Werk würde das Gewohnte stören. Empfehlung: aus (Kevin am Gate genannt).
- **Hinweis bei 0 im Panel statt im Store:** Die Stores sind frei von i18n; das Panel hat `$t`. Empfehlung: Panel.

## Risiken & Rollback

Gering. Die Rückfrage hält den Text nur im Speicher der Komponente; ein Tab-Wechsel oder Schließen verwirft ihn.
Rollback: Revert der Commits; das Feld in `prefs.json` wird von einer älteren Version ignoriert (serde ohne
`deny_unknown_fields`).

## Doku-Impact

`docs/admin/index.html` und `docs/en/admin/index.html` (Liste der Terminal-Optionen beim SSH-Terminal, Snippets mit
Broadcast), `changelog.d/kern-terminal-4.md`.

## Offene Fragen

- Default der Option: aus (Empfehlung) oder an.
