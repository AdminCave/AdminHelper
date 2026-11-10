# Desktop-Terminal: Rückfrage vor mehrzeiligem Einfügen, Rückmeldung beim Broadcast — Task-Ledger
Status: bereit · Branch: feature/kern-terminal-4 · Review: pro Task
Spec: docs/features/kern-terminal-4.md (Roadmap R-1144, R-1175)
Heavy: none — nur Desktop-Einstellung und UI im Terminal-Tab; kein Stack-, Gateway-, PKI- oder Install-Pfad, keine Desktop-Journey
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1144: Terminal-Option confirmMultilinePaste in den Desktop-Einstellungen  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/models.rs, apps/desktop/src-tauri/src/storage.rs, apps/desktop/src-tauri/src/migration.rs
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @327e514dd 2026-11-10T09:45:21+01:00
Review: approve (.ah-out/review/kern-terminal-4/T1.verdict.json)
Änderung: `TerminalPrefs` bekommt `confirm_multiline_paste: bool`, Default `false`; Test, dass eine `prefs.json` ohne das Feld mit `false` lädt und der Wert die Runde übersteht.
Verify: bash scripts/dev/verify.sh desktop-rs --strict
Doku: → T4

### T2 — R-1144: Rückfrage im Terminal vor mehrzeiligem Einfügen  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/bridge/types.ts, apps/desktop/ui/src/lib/models/settings.ts, apps/desktop/ui/src/components/terminal/TerminalOptions.svelte, apps/desktop/ui/src/components/terminal/SshTerminal.svelte, apps/desktop/ui/src/components/terminal/SshTerminal.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/Login.workspace.test.ts, apps/desktop/ui/src/components/SettingsModal.nav.test.ts, apps/desktop/ui/src/components/SettingsModal.save.test.ts, apps/desktop/ui/src/components/SettingsModal.seed.test.ts, apps/desktop/ui/src/components/SettingsModal.workspace.test.ts, apps/desktop/ui/src/components/StatusFooter.test.ts, apps/desktop/ui/src/lib/models/settings.test.ts, apps/desktop/ui/src/lib/stores/session.test.ts, docs/features/kern-terminal-4.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @af011c363 2026-11-10T09:59:14+01:00
Review: approve (.ah-out/review/kern-terminal-4/T2.verdict.json)
Änderung: Typ und Default `confirmMultilinePaste: false`, Checkbox in den Terminal-Optionen; `paste()` hält bei eingeschalteter Option einen bereinigten Text mit Zeilenumbruch zurück und zeigt eine Leiste im Tab (Zeilenzahl, Einfügen, Abbrechen; Fokus auf Abbrechen, Escape bricht ab); Tests für aus, an + einzeilig, an + mehrzeilig (Einfügen und Abbrechen).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/terminal/SshTerminal.test.ts
Doku: → T4
Abhängt von: T1

### T3 — R-1175: Broadcast an 0 Sitzungen meldet sich  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/stores/terminals.ts, apps/desktop/ui/src/lib/stores/terminals.test.ts, apps/desktop/ui/src/components/terminal/SnippetsPanel.svelte, apps/desktop/ui/src/components/terminal/SnippetsPanel.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @5e432d4d9 2026-11-10T10:15:27+01:00
Review: approve (.ah-out/review/kern-terminal-4/T3.verdict.json)
Änderung: `runSnippet` gibt die Zahl der erreichten Sitzungen zurück (`null` ohne Broadcast oder bei Fehler); das Snippet-Panel zeigt bei 0 per `showStatus` „Keine SSH-Sitzung läuft“; Tests im Store und im Panel.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/stores/terminals.test.ts src/components/terminal/SnippetsPanel.test.ts
Doku: → T4

### T4 — Doku DE+EN und Changelog  [x]
Komponente: desktop-ui · Dateien: docs/admin/index.html, docs/en/admin/index.html, changelog.d/kern-terminal-4.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @57a91cbf7 2026-11-10T10:17:40+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Die Liste der Terminal-Optionen nennt die Rückfrage (ab Werk aus), der Snippet-Absatz den Hinweis bei Broadcast ohne Sitzung; Changelog-Fragment.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/terminal/SshTerminal.test.ts
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- Die Zeilen überlappen `feature/arch-namen` in `types.ts` und `dictionaries.ts`, dort aber an anderen Stellen (TunnelMapping, Tunnel-Texte); der Zug fährt trotzdem, sonst wartet er auf PR #432 (Kevins Merge). Wer später merged, löst einen rein textuellen Konflikt.
- T3: Der Wortlaut der Einfüge-Rückfrage aus T2 lautet jetzt „Text mit Zeilenumbruch einfügen (Zeilen: {n})?“: Auch ein einzelner Befehl mit Umbruch am Ende fragt, und „1 Zeilen“ wäre falsch (Nit des reviewers zu T2); dictionaries.ts gehört zu T3.
- T3 baut erst nach dem Merge von `feature/kern-rdp-9` (#445), das `terminals.ts` ebenfalls ändert.
- T2: Die Rückfrage nimmt den Fokus auf „Abbrechen“, nicht auf „Einfügen“: ein Enter, das noch für die Shell gemeint war, verwirft den Text, statt ihn laufen zu lassen; Escape bricht ab.
