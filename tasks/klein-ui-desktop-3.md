<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ui-desktop-3 — Task-Ledger
Status: erledigt · Branch: feature/klein-ui-desktop-3 · Review: am Ende
Spec: docs/features/klein-ui-desktop-3.md (Roadmap R-1333, R-1358)
Heavy: none — reine UI-Logik mit Vitest
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1333: Monitoring-Navigation und -Seite nur für Admins  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/AppShell.svelte, apps/desktop/ui/src/components/AppShell.workspace.test.ts, apps/desktop/ui/src/pages/Monitoring.svelte, apps/desktop/ui/src/pages/Monitoring.test.ts, changelog.d/klein-ui-desktop-3.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @6132e2363 2026-11-12T12:31:04+01:00
Review: am Ende (Branch-Review)
Beweis: Kevin 2026-11-11 (Folge von R-1289) · apps/server/app/modules/monitoring_proxy/router.py get_current_admin · Dedup-Key: REF:desktop-ui:AppShell.svelte:monitoring-nav-admin
Semantik: apps/server/app/modules/monitoring_proxy/router.py „Proxy for all monitoring requests (admins only).“
Änderung: `NavItem` bekommt `adminOnly`; der Monitoring-Eintrag setzt es, `visibleNav` filtert nach `$session?.isAdmin === true`, die Route fällt für Nicht-Admins auf das Dashboard. `Monitoring.svelte` prüft die Rolle für den Funde-Tab nicht mehr. Tests: Nicht-Admin sieht keinen Eintrag, `/monitoring` zeigt das Dashboard; Admin sieht die Seite; Funde-Tab ohne eigene Prüfung.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/AppShell.workspace.test.ts src/pages/Monitoring.test.ts
Doku: keine (Changelog-Fragment changelog.d/klein-ui-desktop-3.md)

### T2 — R-1358: Namensfeld sperren, bis die Serverliste geladen ist  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/ConnectionEditor.svelte, apps/desktop/ui/src/components/ConnectionEditor.tabs.test.ts, changelog.d/klein-ui-desktop-3.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @043321e57 2026-11-12T12:39:21+01:00
Review: am Ende (Branch-Review)
Beweis: Nit arch-namen, aus R-1250 gelöst, Frage an Kevin 2026-11-12 · apps/desktop/ui/src/components/ConnectionEditor.svelte:250
Semantik: keine Stelle in docs/ — Kevin 2026-11-12: „Namensfeld sperren, bis die Serverliste geladen ist“
Änderung: Hat die Verbindung eine `serverId`, ist `assignServer` wahr und steht der Server nicht in `$infraServers`, ist das freie Namensfeld `disabled`; mit geladener Liste erscheint das Feld des Servers, mit „kein Server“ wird es frei. Test mit verzögerter Liste: gesperrt, dann Feld des Servers.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ConnectionEditor.tabs.test.ts
Doku: keine (Changelog-Fragment changelog.d/klein-ui-desktop-3.md)

### T3 — Abschlussprüfung: Frist im Test, umlautfreies Changelog-Fragment  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/ConnectionEditor.tabs.test.ts, changelog.d/klein-ui-desktop-3.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @398c23a35 2026-11-12T12:51:45+01:00
Review: am Ende (Branch-Review)
Änderung: `vi.waitFor` im R-1358-Test bekommt `{ timeout: 30_000 }` (testing.md, Fristen); das Fragment wird umlautfrei (docs.md).
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/ConnectionEditor.tabs.test.ts
Doku: keine (Changelog-Fragment)
