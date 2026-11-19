<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-14 — Task-Ledger
Status: bereit · Branch: feature/klein-nachlese-14 · Review: pro Task
Spec: docs/features/klein-nachlese-14.md (Roadmap R-1546, R-1549, R-1550, R-1551, R-1574, R-1590, R-1591, R-1593, R-1603)
Heavy: none — Monitoring-, Agent-, Server- und Desktop-UI-Unit-Tests, Doku
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1546/R-1549/R-1550: Monitoring-Katalog und Central-Fetch  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/module_sync.py, apps/monitoring/app/catalog/model.py, apps/monitoring/app/central/fetch.py, apps/monitoring/app/central/rdap.py, apps/monitoring/tests/test_central_rdap.py, apps/monitoring/tests/test_central_fetch.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @2a61ee7c8 2026-11-19T23:30:50+01:00
Review: approve (.ah-out/review/klein-nachlese-14/T1.verdict.json)
Beweis: reviewer branch (Nits), 2026-11-18
Semantik: keine Stelle in docs/ — die Texte und Zähler selbst sind der Fund
Änderung: Docstring von `module_sync.py` auf höchstens 100 Zeichen je Zeile; `Check._central_consistent` nimmt `interval_timedelta(sensor.min_interval)` statt eigenem Parser; `_deadline` nennt den Rahmen (`seconds` des Aufrufers), nicht die Restzeit; der Kommentar an `QUERY_DEADLINE_S` sagt, dass die DNS-Klassifizierung vor dem Watchdog läuft und die Frist um deren Zeit überschreiten kann. Der Test für die `_deadline`-Meldung zuerst rot.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_fetch.py tests/test_central_rdap.py tests/test_module_sync.py tests/test_catalog.py
Doku: → T6

### T2 — R-1574: SMART-Zähler je Platte, check_restarts-Kommentar  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/smart.py, apps/monitoring/app/check_configs.py, apps/monitoring/tests/test_smart_checker.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @49d863a76 2026-11-19T23:33:46+01:00
Review: approve (.ah-out/review/klein-nachlese-14/T2.verdict.json)
Beweis: reviewer branch (Nits), 2026-11-18
Semantik: keine Stelle in docs/ — die Texte und Zähler selbst sind der Fund
Änderung: `smart_disks_warning/critical` zählen Platten, nicht Meldungen (eine Platte mit zwei Meldungen zählt einmal); der Kommentar an `check_restarts` sagt, dass das Formular den Schlüssel nicht mehr schreibt und das Schema ihn für gespeicherte Konfigurationen duldet. Erst ein roter Test mit einer Platte, die zwei Meldungen trägt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_smart_checker.py tests/test_check_configs.py
Doku: → T6

### T3 — R-1551/R-1574/R-1591: Agent — Doc-Kommentar, SMART-Reihenfolge, Freigaben-Kommentar  [x]
Komponente: agent · Dateien: apps/agent/internal/discovery/discovery.go, apps/agent/internal/monitor/smart.go, apps/agent/internal/monitor/smart_test.go, apps/agent/internal/probe/net_share.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @19361e8f5 2026-11-19T23:42:36+01:00
Review: approve (.ah-out/review/klein-nachlese-14/T3.verdict.json)
Beweis: reviewer branch (Nits), 2026-11-18
Semantik: keine Stelle in docs/ — die Texte und Zähler selbst sind der Fund
Änderung: Doc-Kommentar von `Run` auf höchstens 100 Zeichen je Zeile umbrechen; die SMART-Platten nach `Device` sortieren, bevor `Collect` sie liefert (Test erst rot: mehrere Platten in umgekehrter Scan-Reihenfolge); der Kommentar an `netShareUsage` behauptet nicht mehr, dass der Timeout ein hängendes `statfs` beendet, sondern nennt, was belegt ist (der Agent wartet nicht länger als `shareTimeout`, `hung=true`).
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/discovery/... ./internal/monitor/... ./internal/probe/...
Doku: → T6

### T4 — R-1593: Webhook-Body mit zu tiefer Verschachtelung ablehnen  [x]
Komponente: server · Dateien: apps/server/app/modules/hooks/router.py, apps/server/tests/test_hooks_webhook_payload.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @fc868aa37 2026-11-19T23:45:36+01:00
Review: approve (.ah-out/review/klein-nachlese-14/T4.verdict.json)
Beweis: security-Nit kern-monitoring-45 T1, 2026-11-18
Semantik: keine Stelle in docs/ — die Texte und Zähler selbst sind der Fund
Änderung: In `_do_trigger` fängt `except Exception` einen `RecursionError` von `request.json()` ab und setzt `{}`. Ein Body, an dem das Parsen mit `RecursionError` scheitert, wird wie ein Body ab 33 Ebenen mit 422 abgelehnt; ein Body, der kein JSON ist, bleibt `{}`. Erst ein roter Test mit einem tief verschachtelten Body (Skript läuft nicht, 422).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hooks_webhook_payload.py tests/test_openapi_snapshot.py
Doku: → T6

### T5 — R-1574/R-1603: Desktop-UI — Backups-Sortierung, ZFS-Anzeige, Scrub-Felder  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/SecBackups.svelte, apps/desktop/ui/src/components/monitoring/section/SecZfs.svelte, apps/desktop/ui/src/components/monitoring/CheckConfigFields.svelte, apps/desktop/ui/src/components/monitoring/CheckConfigFields.test.ts, apps/desktop/ui/src/components/monitoring/section/SecBackups.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @182d9227f 2026-11-19T23:59:20+01:00
Review: approve (.ah-out/review/klein-nachlese-14/T5.verdict.json)
Beweis: reviewer kern-monitoring-45 branch, 2026-11-18
Semantik: keine Stelle in docs/ — die Texte und Zähler selbst sind der Fund
Änderung: `SecBackups`: die Sortierfunktion nimmt zwei Argumente und vergleicht beide Ränge. `SecZfs`: der Kommentar an `scrubChip` und der tote `warn`-Zweig von `healthClass` (der Rückgabetyp nennt `warn`, kein Pfad liefert es) stimmen mit der Bewertung überein. `CheckConfigFields`: das `zfs_health`-Formular bietet `scrub_warn_days` und `scrub_crit_days` an (Zahlenfelder, 1–3650, Standard 35/60 wie im Schema), Beschriftungen in `dictionaries.ts` DE+EN. Je Punkt erst ein roter Test.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring
Doku: → T6

### T6 — R-1590/R-1591: Entwickler-Doku (_origin, Freigaben-Timeout) und Changelog  [x]
Komponente: scripts · Dateien: docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/klein-nachlese-14.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @180445dfe 2026-11-20T00:04:01+01:00
Review: am Ende (nur Doku, Branch-Review)
Beweis: reviewer branch kern-monitoring-18, 2026-11-18
Semantik: keine Stelle in docs/ — die Texte und Zähler selbst sind der Fund
Änderung: `_origin`: Port aus `ports` und `sockets`; ein Fund ohne eigene Instanzart (Stand-in `matched_by`) aus `containers`, `units`, `sockets`, `markers` — gegen `discovery._origin` lesen. `net_share_usage`: der Satz, ein Timeout beende das hängende `stat -f`, wird auf das Belegte beschränkt (der Aufruf wartet höchstens 10 s, danach `hung`; ein Prozess im Kernel-Wartezustand wird nicht als beendet zugesichert). Changelog-Fragment (ASCII) für T2, T4, T5.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Änderung selbst
Task-Review: am Ende

### T7 — R-1603: scrubChip-Kommentar nennt die Bewertung der Prüfung genau  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/SecZfs.svelte
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @60531a302 2026-11-20T00:19:21+01:00
Review: approve (.ah-out/review/klein-nachlese-14/T7.verdict.json)
Beweis: Abschlussprüfung klein-nachlese-14, 2026-11-20 (plugins.py:394-402: Scrub-Fehler und vdev-Fehler bewerten warning)
Semantik: keine Stelle in docs/ — der Kommentar selbst ist der Fund
Änderung: Der Kommentar an `scrubChip` sagt, die Prüfung bewerte Gesundheit, Scrub-Alter (`scrub_warn_days`, `scrub_crit_days`), Scrub-Fehler und vdev-Fehler; der Chip zeigt nur an. Nur Kommentar, kein Verhalten.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring
Doku: keine (Kommentar)

### T8 — R-1574: Webhook-Test unabhängig von der Stack-Größe  [x]
Komponente: server · Dateien: apps/server/tests/test_hooks_webhook_payload.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @c7f7e22f8 2026-11-20T00:43:10+01:00
Review: approve (.ah-out/review/klein-nachlese-14/T8.verdict.json)
Beweis: CI-Lauf 44636743934 (py3.14 shard 2/2): `assert (200, 'application/json') == (422, …)`; ein Body mit 100000 Ebenen lief dort nicht in den RecursionError, sondern in einen JSONDecodeError
Semantik: keine Stelle in docs/ — der Test selbst ist der Fund
Änderung: `test_a_body_too_deep_to_parse_is_a_422_not_an_empty_payload` lässt `json.loads` für genau diesen Body einen RecursionError werfen, statt auf die Stack-Größe der Maschine zu bauen. Nur Test, kein Produktcode.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hooks_webhook_payload.py
Doku: keine (Test)

## Entscheidungen
- R-1591 wird nicht an einer echten hängenden Freigabe geprüft (keine Infrastruktur); Kommentar und Doku werden eingeschränkt.
- `check_restarts` bleibt im Schema, weil gespeicherte Konfigurationen sonst 422 liefern.
