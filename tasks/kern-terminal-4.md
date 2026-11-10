# Desktop-Terminal: Rückfrage vor mehrzeiligem Einfügen, Rückmeldung beim Broadcast — Task-Ledger
Status: geplant · Branch: feature/kern-terminal-4 · Review: pro Task
Spec: docs/features/kern-terminal-4.md (Roadmap R-1144, R-1175)
Heavy: none — nur Desktop-Einstellung und UI im Terminal-Tab; kein Stack-, Gateway-, PKI- oder Install-Pfad, keine Desktop-Journey
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1144: Terminal-Option confirmMultilinePaste in den Desktop-Einstellungen  [ ]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/storage.rs
Änderung: `TerminalPrefs` bekommt `confirm_multiline_paste: bool`, Default `false`; Test, dass eine `prefs.json` ohne das Feld mit `false` lädt und der Wert die Runde übersteht.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- storage::
Doku: → T4

### T2 — R-1144: Rückfrage im Terminal vor mehrzeiligem Einfügen  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/models/settings.ts, apps/desktop/ui/src/components/terminal/TerminalOptions.svelte, apps/desktop/ui/src/components/terminal/SshTerminal.svelte, apps/desktop/ui/src/components/terminal/SshTerminal.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Typ und Default `confirmMultilinePaste: false`, Checkbox in den Terminal-Optionen; `paste()` hält bei eingeschalteter Option einen bereinigten Text mit Zeilenumbruch zurück und zeigt eine Leiste im Tab (Zeilenzahl, Einfügen, Abbrechen); Tests für aus, an + einzeilig, an + mehrzeilig (Einfügen und Abbrechen).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/terminal/SshTerminal.test.ts
Doku: → T4
Abhängt von: T1

### T3 — R-1175: Broadcast an 0 Sitzungen meldet sich  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/components/terminal/SnippetsPanel.svelte, apps/desktop/ui/src/components/terminal/SnippetsPanel.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: `runSnippet` gibt die Zahl der erreichten Sitzungen zurück (`null` ohne Broadcast oder bei Fehler); das Snippet-Panel zeigt bei 0 per `showStatus` „Keine SSH-Sitzung läuft“; Tests im Store und im Panel.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/terminals.test.ts src/components/terminal/SnippetsPanel.test.ts
Doku: → T4

### T4 — Doku DE+EN und Changelog  [ ]
Komponente: desktop-ui · Dateien: docs/admin/index.html, docs/en/admin/index.html, changelog.d/kern-terminal-4.md
Änderung: Die Liste der Terminal-Optionen nennt die Rückfrage (ab Werk aus), der Snippet-Absatz den Hinweis bei Broadcast ohne Sitzung; Changelog-Fragment.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/terminal/SshTerminal.test.ts
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- Die Zeilen überlappen `feature/arch-namen` in `types.ts` und `dictionaries.ts`, dort aber an anderen Stellen (TunnelMapping, Tunnel-Texte); der Zug fährt trotzdem, sonst wartet er auf PR #432 (Kevins Merge). Wer später merged, löst einen rein textuellen Konflikt.
- T3 baut erst nach dem Merge von `feature/kern-rdp-9` (#445), das `terminals.ts` ebenfalls ändert.
