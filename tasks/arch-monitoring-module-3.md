<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-module-3 — Task-Ledger
Status: bereit · Branch: feature/arch-monitoring-module-3 · Review: am Ende
Spec: docs/features/arch-monitoring-module-3.md (Roadmap R-1268)
Heavy: linux-full — `apps/agent` (Last-Tor im Lauf des Agenten); der Sammellauf fährt agent-monitoring
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Risikopfad: T2 (`apps/monitoring/app/routers/agent.py`) → `security` in der Abschlussprüfung.

### T1 — Agent: Last-Tor (R-1268)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/loadgate.go, apps/agent/internal/monitor/loadgate_test.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/reportstate.go, apps/agent/internal/monitor/selfmeasure.go, apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/monitor.go, apps/agent/internal/monitor/report_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @3f0d497db 2026-11-12T16:42:04+01:00
Review: am Ende (Branch-Review)
Änderung: Neues `loadgate.go` (SPDX) entscheidet nach dem Kern aus Last je CPU (≥ 2,0, nicht im Container, nicht unter Windows), I/O-Wartezeit seit dem letzten CPU-Stand (≥ 25 %, nur Linux, neues `cpuSample.Iowait`) und verfügbarem RAM (< 10 %) mit Hysterese im `reportState` (zwei Läufe hinein, drei unauffällige hinaus). Bei Schonung laufen die optionalen Collector, die Proben und die Erkennung nicht; sie melden `throttled: true, reason: "load"`, ihre Drossel und die gespeicherten Probenergebnisse bleiben; neuer Block `self.load_shed`; nach verlorenem Push bleibt der Schonungs-Zustand. Tests: Eintritt, Hysterese, Austritt, Kern läuft immer, Container/Windows/fehlende Werte, Block-Form, verlorener Push.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T3

### T2 — Monitoring: Last-Schonung auswerten (R-1268)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/app/check_engine.py, apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_agent_load_shed.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @12d6135de 2026-11-12T17:02:22+01:00
Review: am Ende (Branch-Review)
Änderung: `_COLLECTOR_OF_CHECK` um `probe` → `probes`; ein Collector mit `throttled: true, reason: "load"` schont seine Checks ohne die 45-min-Grenze, sofern sie einen Zustand haben, und hängt über `note_skip` (bisher `_note_skip`, wird öffentlich) „(skipped: load shedding)“ an die Meldung; Metrik `monitor_agent_load_shed` aus `self.load_shed` (beschränkt gelesen); `agent_resources` warnt nach 30 min durchgehender Schonung. Ein Report ohne Block bleibt wie heute. Neue Testdatei mit SPDX.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_load_shed.py tests/test_agent_report.py tests/test_agent_report_v4.py tests/test_check_engine_context.py tests/test_agent_resources_checker.py
Doku: → T3
Abhängt von: T1

### T3 — Doku DE+EN und CHANGELOG (R-1268)  [x]
Komponente: monitoring · Dateien: docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/arch-monitoring-module-3.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @292d6f132 2026-11-12T17:12:10+01:00
Review: am Ende (Branch-Review)
Änderung: Last-Tor, Zustand und `self.load_shed` im Agenten-Kapitel; Push-Payload, `reason`, Schonung ohne 45-min-Grenze und Metrik in der Entwickler-Doku des Monitorings; in der Admin-Doku, was bei Last aussetzt und wie es sich zeigt; CHANGELOG-Fragment ohne Umlaute.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_openapi_snapshot.py
Doku: docs/developer/agent.html DE+EN · docs/developer/monitoring.html DE+EN · docs/admin/monitoring.html DE+EN · changelog.d/arch-monitoring-module-3.md
Task-Review: am Ende
Abhängt von: T1, T2

### T4 — Warnung nach Spec, Zustandsschema in der Doku (R-1268, Abschlussprüfung)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_agent_load_shed.py, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @62bea97c1 2026-11-12T17:22:46+01:00
Review: am Ende (Branch-Review)
Änderung: Die 30-min-Warnung von `agent_resources` lautet wie in der Spec „Load shedding since <Zeit> UTC (<n> min)“ (Fund `wichtig` der Abschlussprüfung); Test und Doku DE+EN ziehen nach. Dazu die zwei Nits der Prüfung in `agent.html`: `cpu` im Report-Zustand trägt `iowait`, `load_shed` fehlt nur, solange das Tor ruht.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_load_shed.py tests/test_agent_resources_checker.py
Doku: docs/developer/monitoring.html DE+EN · docs/admin/monitoring.html DE+EN · docs/developer/agent.html DE+EN
Abhängt von: T2, T3

## Entscheidungen
- 2026-11-12 T1: `cpuSample.Iowait` ist ein Wert, kein Zeiger; 0 heißt „nicht gelesen“ (kein Linux, alter Zustand) — die bestehenden Vergleiche ganzer `cpuSample` in den Tests bleiben gültig, ein Host ohne jede I/O-Wartezeit verliert nur ein Kriterium, das er nicht erfüllen kann
- 2026-11-12 T1: `reportState.LoadShed` mit `omitzero` (Go 1.24+, Modul auf 1.27) — eine Zustandsdatei ohne Schonung bleibt wie heute
- 2026-11-12 T1: die Schonung lässt die Drossel eines Collectors unverändert und meldet ihren Faktor — was er kostet, misst erst sein nächster echter Lauf
- 2026-11-12 T1: Integrationstests des Tors (fünf Läufe, verlorener Push) stehen in `loadgate_test.go`, nicht in `report_test.go` — eine Datei je Funktion, `report_test.go` bekommt nur den Stub
- 2026-11-12 T2: statt `_note_skip` öffentlich zu machen, steckt die Textregel in der reinen Funktion `with_skip_note` (`check_engine.py`) — `_note_skip` committet selbst, der Push-Pfad braucht genau einen Commit am Ende des Reports
- 2026-11-12 T2: die unbegrenzte Schonung verlangt den aktiven Block `self.load_shed` mit lesbarem `since` (derselbe Block wie die 30-min-Warnung); ohne ihn gilt für `reason: "load"` die 45-min-Grenze der Drossel
- 2026-11-12 T2: die Dauer rechnet ab dem `since` des Agenten (Minuten-Genauigkeit), eine vorgehende Agenten-Uhr zählt als 0 min
- 2026-11-12 T2: neuer Problem-Schlüssel `load_shed` in `problems` (nur `warning`); die UIs lesen `problems` nur je Metrik-Schlüssel, die Liste im Kommentar von `apps/desktop/ui/src/lib/api/types.ts` wird eine `klein-`-Zeile
- 2026-11-12 T2: die Schonung mit Hinweis läuft wie eine Auswertung in einem SAVEPOINT mit eigenem Fehlerfang (R-0635); der Commit am Ende gilt auch, wenn nur Hinweise geschrieben wurden
- 2026-11-12 T2: `test_agent_load_shed.py` schaltet die geteilte sqlite-Verbindung in den PEP-249-Modus (`autocommit = False`) — im Legacy-Modus committet das `RELEASE` des SAVEPOINTs selbst, ein fehlender Commit bliebe unsichtbar (Gegenprobe: ohne das Fixture blieb diese Mutation grün)
- 2026-11-12 T2: `Verify:` um `test_check_engine_context.py` (Hinweis-Regel) und `test_agent_resources_checker.py` (Bewertung) erweitert
- 2026-11-12 T4: die Warnung trägt den Wortlaut der Spec als Label; `_grade` hängt wie an jede Problem-Meldung die Grenze an („… UTC (42 min) (>=30 min)“) — eine Ausnahme nur für diese Meldung wäre eine zweite Regel im Grader; die Zeit ist das `since` des Agenten, minutengenau
