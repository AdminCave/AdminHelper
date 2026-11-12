<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-3 — Task-Ledger
Status: aktiv · Branch: feature/klein-nachlese-3 · Review: pro Task
Spec: docs/features/klein-nachlese-3.md (Roadmap R-1380, R-1390, R-1377)
Heavy: none — Doku, UI-Texte, Sortierung und ein Filter im Monitoring-Dienst, kein Stack-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1380: MonitorCheckModal ignoriert eine verspätete fetchStatus-Antwort  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/MonitorCheckModal.svelte, apps/desktop/ui/src/components/monitoring/MonitorCheckModal.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @c11ca1328 2026-11-12T16:22:37+01:00
Review: approve (.ah-out/review/klein-nachlese-3/T1.verdict.json)
Beweis: reviewer arch-monitoring-module-2 2026-11-12 · feature/arch-monitoring-module-2@af3a20207 MonitorCheckModal.svelte:79 (T11)
Änderung: Die Antwort von `fetchStatus` setzt `serverChecks` nur, wenn das Modal seit dem Aufruf nicht geschlossen oder neu geöffnet wurde (Öffnungszähler oder Abbruchmarke). Test: Modal öffnen, schließen und für anderen Server neu öffnen, die erste Antwort danach auflösen, die Partnerliste bleibt die der zweiten.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/MonitorCheckModal.test.ts
Doku: keine (interner Zustand)

### T2 — R-1390: Docker-Laufzeit und ZFS-Fehlertext stimmen grammatisch, Gruppenreihenfolge hat einen Test  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/monitoring/section/SecDocker.svelte, apps/desktop/ui/src/components/monitoring/section/SecDocker.test.ts, apps/desktop/ui/src/components/monitoring/section/SecZfs.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @432ed930d 2026-11-12T16:33:36+01:00
Review: approve (.ah-out/review/klein-nachlese-3/T2.verdict.json)
Beweis: reviewer arch-monitoring-ui-2 2026-11-12 (T10) · feature/arch-monitoring-ui-2@72e71d8ca dictionaries.ts:1195, :2711, SecDocker.svelte:119 · Dedup-Key: ref:monitoring-ui:arch-monitoring-ui-2:nachlese
Änderung: `monitoring.docker.upFor` DE wird zu einer Form, die mit „5 Tage“ stimmt (etwa „Laufzeit {span}“); `monitoring.zfs.scrubErrors` EN stimmt für 1 (Pluralmechanismus des Wörterbuchs, sonst Formulierung ohne Plural). `SecDocker` behält die Sortierung nach Schwere; ein Test legt fest, dass eine kritische Gruppe ohne Projekt vor gesunden Projekten steht, und die Tests der beiden Texte prüfen „1“ und „5 Tage“.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/section/SecDocker.test.ts
Doku: keine (Beschriftung, Test)

### T3 — R-1390, R-1380: Agent-Arrays zählen Nicht-Objekte mit, Kommentar und Testliteral  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/plugins.py, apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_check_engine.py, apps/monitoring/tests/test_plugin_checkers.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @c4f662c85 2026-11-12T16:36:09+01:00
Review: approve (.ah-out/review/klein-nachlese-3/T3.verdict.json)
Beweis: reviewer arch-monitoring-ui-2 2026-11-12 (T8) plugins.py:80/248; agent.py:474 (Branch-Prüfung); arch-monitoring-module-2 test_check_engine.py:853-855 (T16)
Änderung: `capped_objects(value, limit)` schneidet vor dem Filter auf Objekte; die Teilgrenzen für Backup-Jobs und vdev-Fehler (`plugins.py:80/248`) rufen es mit `limit` auf, statt nach dem Filter zu schneiden, damit Nicht-Objekte dort Platz belegen wie die Ports (Test in `test_plugin_checkers.py`, rot vor dem Fix). Kommentar `agent.py:474` greift R-1389 nicht mehr vor. In `test_check_engine.py` stehen U+FFFD als `\ufffd`-Escape statt als Literalzeichen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_engine.py tests/test_plugin_checkers.py
Doku: keine (interne Grenze, Kommentar, Test)

### T4 — R-1390: E2E-Screenshots ohne Alarm-Toasts  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/monitoring-server-page.live.js
Beweis: reviewer arch-monitoring-ui-2 Bau T11 · feature/arch-monitoring-ui-2@72e71d8ca monitoring-server-page.live.js:87
Änderung: `shot()` schließt oder blendet vor der Aufnahme sichtbare Toasts aus (derselbe Weg wie andere Specs, vorher greppen). Lauf der Live-Spec ist Plattform-I/O ohne Display hier; verifiziert wird Lint, das Ergebnis wird so genannt.
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: keine (Testhilfe)

### T5 — R-1380, R-1377, R-1390: Doku nachziehen (README, Monitoring-Seiten, Changelog-Fragment)  [ ]
Komponente: scripts · Dateien: README.md, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/arch-monitoring-ui-2.md
Beweis: README.md:335 und :494, monitoring.html Admin :384/:404 und :343, Entwickler :367/:368 (frisch greppen); Semantik: docs/admin/monitoring.html:384 „prüft er nicht“ widerspricht dem Agent-Verhalten (security kern-monitoring-22)
Änderung: README nennt `central` in der Typenliste, `MONITOR_PUBLIC_RESOLVERS` und `MONITOR_SPAMHAUS_DQS_KEY` in der Env-Tabelle (Werte aus `apps/monitoring/app/core/config.py`) und `central` in der `checkers/`-Zeile des Baums. Die vier Monitoring-Seiten: `days_left`/`lifetime_pct` auch bei smtp und imap (nach `checkers/central*` belegen), und ein relativ oder abstrakt gebundener Unix-Socket wird abgewiesen statt „nicht geprüft“, DE+EN. Im Fragment `arch-monitoring-ui-2.md` fällt das gerade Anführungszeichen weg.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Änderung selbst
Task-Review: am Ende
