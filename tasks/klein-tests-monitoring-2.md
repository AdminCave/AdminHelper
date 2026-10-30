<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-monitoring-2 — Task-Ledger
Status: bereit · Branch: feature/klein-tests-monitoring-2 · Review: am Ende
Spec: docs/features/klein-tests-monitoring-2.md (Roadmap R-0966, R-0977)
Heavy: none — nur Unit-Tests, kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Katalog: zwei HTTP-Meldungen ergänzen (R-0966)  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_checker_messages.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @93831f0e 2026-10-30T10:36:01+01:00
Review: am Ende (Branch-Review)
Beweis: R-0966 apps/monitoring/app/checkers/http.py (`Redirect without Location header`, `Too many content encodings`)
Dedup-Key: ref:monitoring:test_checker_messages.py:http-message-catalog
Änderung: zwei `PULL_CASES` im Muster der Nachbarfälle: eine 302-Antwort ohne `location` → critical „Redirect without Location header“; eine Antwort mit mehr als fünf `Content-Encoding`-Schichten → die Meldung, die der Checker daraus macht (zuerst die echte Ausgabe lesen, dann den Fall festschreiben).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_checker_messages.py
Doku: keine (Tests)

### T2 — Monitoring-Antwortform: Metrics-Serie, dünne Zeile, /run über die Route (R-0977)  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_response_shapes.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @b46226ac 2026-10-30T10:37:07+01:00
Review: am Ende (Branch-Review)
Beweis: R-0977 apps/monitoring/tests/test_response_shapes.py (`test_metrics_pass_the_series_through` prüft `data` nur auf nicht leer)
Dedup-Key: ref:cross:tests/test_response_shapes.py:gaps
Änderung: `data` des Metrics-Tests gegen die durchgereichte Serie (`data == series`, soweit die Route sie unverändert liefert, sonst gegen die belegte Form); ein Check mit State-Zeile aus NULL-Feldern gegen `_produced`; `POST /checks/{id}/run` (Ausführung gestubbt) gegen `_produced`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_response_shapes.py
Doku: keine (Tests)

### T3 — Server-Antwortform: interne Serverliste ohne Tags (R-0977)  [x]
Komponente: server · Dateien: apps/server/tests/test_response_shapes.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @0257af7f 2026-10-30T10:41:42+01:00
Review: am Ende (Branch-Review)
Beweis: R-0977 apps/server/tests/test_response_shapes.py:292 (`test_internal_listing` kennt nur einen Server mit Tags)
Dedup-Key: ref:cross:tests/test_response_shapes.py:gaps
Änderung: `test_internal_listing` legt zusätzlich den dünnen Server (`_sparse`, `tags` NULL) an und erwartet die Liste mit beiden Einträgen; die Form von `tags` (hier `[]`) wird an der Route belegt, nicht geraten.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_response_shapes.py
Doku: keine (Tests)
