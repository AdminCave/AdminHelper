# Dienste einzeln ignorieren — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-37 · Review: am Ende
Spec: Roadmap R-1520
Heavy: none — nur Desktop-UI-Komponente und Store, kein Stack-, Gateway-, Journey- oder Install-Pfad; die PUT-Route gibt es schon
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Semantik: docs/admin/monitoring.html:73 „<code>ignore</code> blendet Units aus, mit oder ohne <code>.service</code> und als Glob-Muster“ — der Check kennt das Ausblenden je Name; der Desktop bietet es je Dienst nicht an, nur das Abschalten des ganzen Checks (MonCheckLine.svelte:163). Gewolltes Verhalten entschieden von Kevin 2026-11-16 (Roadmap-Notiz R-1520).

### T1 — Knopf Ignorieren je betroffenem Dienst in der Dienste-Karte  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/SecServices.svelte, apps/desktop/ui/src/components/monitoring/section/SecServices.test.ts, apps/desktop/ui/src/lib/stores/monitoring.ts, apps/desktop/ui/src/lib/api/monitoring.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @df151f69d 2026-11-16T14:55:36+01:00
Review: am Ende (Branch-Review)
Änderung: Jede Problemzeile der aufgeklappten Dienste-Zeile (auto: fehlgeschlagen, inaktiv; list: läuft nicht) bekommt einen Knopf „Ignorieren“; nach Rückfrage schreibt der Store per PUT nur `config`: auto hängt den Namen an `config.ignore` (eine CSV-Altform wird zur Liste), list nimmt ihn aus `config.services`; die Antwort ersetzt den Check im Store. Erst der rote Test (Knopf fehlt), dann der Fix.
Beweis: main@2f40e989e Code-Lesung SecServices.svelte:185 (Dienstzeilen ohne Aktion), MonCheckLine.svelte:163 (toggleCheck des ganzen Checks)
Dedup-Key: bug:desktop:SecServices.svelte:ignore-single-service
HEAD: a94445872
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/section/SecServices.test.ts
Doku: → T2

### T2 — Doku DE+EN und Changelog  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-37.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @c64708f3b 2026-11-16T15:06:20+01:00
Review: am Ende (Branch-Review)
Änderung: Absatz zur Dienste-Zeile im Desktop (Knopf Ignorieren, Rückfrage, Rückweg über Ignorieren bzw. Dienste im Check-Editor) DE+EN; Changelog-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/monitoring.html docs/en/admin/monitoring.html changelog.d/kern-monitoring-37.md
Task-Review: am Ende
Abhängt von: T1

## Entscheidungen
- Der Knopf steht an jeder Problemzeile (fehlgeschlagen, inaktiv, läuft nicht), nicht an „nicht gefunden“: `ignore` filtert im Checker failed und enabled_inactive gleich (agent.py:841-842), eine graue Zeile ist kein Problem.
- Der Store schreibt nur `config` (CheckUpdate ist partiell, checks.py:62); der Status zeigt den Dienst bis zum nächsten Bericht des Agents weiter, kein vorgetäuschtes Ausblenden.
