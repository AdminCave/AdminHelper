<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-18 — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-18 · Review: pro Task
Spec: docs/features/kern-monitoring-18.md (Roadmap R-1406, R-1302, R-1267)
Heavy: linux-full — Inventar-Format, Discovery, Plattenliste und eine neue Ansicht im Agent (`apps/agent`), kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Prüfung: `security` zusätzlich zu `reviewer` bei T1, bei den übrigen Tasks, wenn `review.sh risk` es verlangt.
Reihenfolge: T1 steht für sich. T2 → T3. T4 braucht T2 (Abschnitt `shares` mit eigenem Flag), T5 braucht T4, T6
braucht T3 und T4. T7 zuletzt.

## Tasks

### T1 — R-1406: Gesamtfrist für eine RDAP-Abfrage  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/central/fetch.py, apps/monitoring/app/central/rdap.py, apps/monitoring/tests/test_central_fetch.py, apps/monitoring/tests/test_central_rdap.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @1d722dbdc 2026-11-18T11:26:16+01:00
Review: approve (.ah-out/review/kern-monitoring-18/T1.verdict.json)
Änderung: `fetch.get` nimmt optional eine Frist (Zeitpunkt), die der Watchdog statt `DEADLINE_S` benutzt, wenn sie
früher endet. `rdap.probe` setzt eine Frist für die ganze Abfrage samt Weiterleitungen und Kandidaten und reicht sie
an `_get` und jeden Sprung durch. Tests: eine Kette von Weiterleitungen und mehrere Kandidaten enden zusammen innerhalb
der Gesamtfrist (Uhr gefälscht).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_fetch.py tests/test_central_rdap.py
Doku: → T7

### T2 — R-1302: Agent meldet die Vollständigkeit je Abschnitt  [x]
Komponente: agent · Dateien: apps/agent/internal/discovery/discovery.go, apps/agent/internal/discovery/discovery_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @84574fd0e 2026-11-18T11:28:50+01:00
Review: approve (.ah-out/review/kern-monitoring-18/T2.verdict.json)
Änderung: `Inventory` bekommt `Complete map[string]bool json:"complete"`. Jeder `part(...)` setzt das Flag seines
Abschnitts (units, containers, sockets, markers, vhosts); `ports` aus `recognizePorts`. Ein abgelaufener Gesamtrahmen
macht die Abschnitte unvollständig, die danach noch liefen. `Partial` bleibt wie heute. Test: ein Abschnitt, der
scheitert, macht nur sein eigenes Flag falsch.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestRun|TestAPart|TestTheEnd|TestTheLists|TestTheInventory
Doku: → T7

### T3 — R-1302: gone je Abschnitt  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/tests/test_discovery_match.py, apps/monitoring/tests/test_agent_report_v4.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @c0646c16e 2026-11-18T11:32:26+01:00
Review: approve (.ah-out/review/kern-monitoring-18/T3.verdict.json)
Beweis: `apps/monitoring/app/discovery.py` `apply_discovery` setzt `full_scan = not inventory["partial"]`, `_update_findings` meldet gone nur bei `full_scan`; Dedup-Key BUG:monitoring:discovery.py:gone-bei-stets-partial
Änderung: `clean_inventory` übernimmt `complete`, und eine Kappung macht nur den gekappten Abschnitt unvollständig.
Fehlt `complete`, gelten alle Abschnitte als `not partial`. `apply_discovery` führt `section_full_scan_at` je
Abschnitt im gespeicherten JSON. `_update_findings` erklärt einen Fund für verschwunden, wenn der Abschnitt seiner
Herkunft vollständig war und der Fund älter ist als der vorige vollständige Scan dieses Abschnitts. Herkunft:
Container und Compose aus containers, Unit aus units, Prozess aus sockets, Port aus ports, Marker aus markers, vHost
aus vhosts. Tests, zuerst rot:
- Ports stets gekappt, ein verschwundener Container wird gone.
- Ein alter Agent ohne `complete` verhält sich wie heute.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_discovery_match.py tests/test_agent_report_v4.py
Doku: → T7
Abhängt von: T2

### T4 — R-1267: Netz-Freigaben in der Discovery, raus aus der Plattenliste  [x]
Komponente: agent · Dateien: apps/agent/internal/discovery/discovery.go, apps/agent/internal/discovery/discovery_linux.go, apps/agent/internal/discovery/discovery_other.go, apps/agent/internal/discovery/discovery_windows.go, apps/agent/internal/discovery/discovery_test.go, apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/collector_test.go, apps/agent/internal/probe/mountinfo.go, apps/agent/internal/probe/mountinfo_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @98ad03ad1 2026-11-18T11:36:22+01:00
Review: approve (.ah-out/review/kern-monitoring-18/T4.verdict.json)
Änderung:
- Neuer Abschnitt `Shares []Share json:"shares"` mit `{mountpoint, fstype}` und eigenem `complete`-Flag.
- Er liest `/proc/self/mountinfo` (nfs, nfs4, cifs, smb3), nur unter Linux, und ruft dabei kein `statfs` auf.
- Die Quelle (Gerät, Export) geht nicht ins Inventar. Kappung über `maxShares`.
- `skipFSTypes` bekommt nfs, nfs4, cifs und smb3.
- Tests: Parser mit Fixture (Quelle fehlt im Ergebnis); der Collector überspringt Netz-Typen.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestShare|TestNoShares|TestRun|TestAPart|TestTheInventory|TestSkip
Doku: → T7
Abhängt von: T2

### T5 — R-1267: Zielart `share` und Ansicht `net_share_usage`  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/target.go, apps/agent/internal/probe/target_test.go, apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/net_share.go, apps/agent/internal/probe/net_share_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go, apps/agent/internal/probe/mountinfo.go, apps/agent/internal/probe/mountinfo_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @fabba3ed4 2026-11-18T11:41:13+01:00
Review: approve (.ah-out/review/kern-monitoring-18/T5.verdict.json)
Änderung:
- Die Zielart `share` nimmt nur einen Mountpunkt, der laut mountinfo gerade ein Netz-Mount dieses Hosts ist; einen
  anderen weist sie ab.
- Die Ansicht `net_share_usage` (neue Datei, SPDX) misst `stat -f` im Unterprozess über `execx` mit 10 s Timeout und
  einem Allowlist-Eintrag für den Mountpunkt.
- Felder: `mounted`, `hung`, `used_percent`, `free_gb`.
- Tests: Timeout ergibt `hung=true`, ein fehlender Mount ergibt `mounted=false`, ein lokaler Pfad wird abgewiesen.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestShare|TestNetShare|TestTarget|TestAllowlist
Doku: → T7
Abhängt von: T4

### T6 — R-1267: Instanz `share` und Modul `net_share`  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/discovery.py, apps/monitoring/app/catalog/model.py, apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/module_sync.py, apps/monitoring/app/catalog/modules/net_share.py, apps/monitoring/tests/test_discovery_match.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_catalog_shares.py, apps/monitoring/app/check_configs.py, apps/monitoring/tests/test_agent_report_v4.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @cb6495314 2026-11-18T11:54:53+01:00
Review: approve (.ah-out/review/kern-monitoring-18/T6.verdict.json)
Änderung:
- `clean_inventory` übernimmt `shares` (Mountpunkt geprüft, `fstype` aus der Liste).
- Neu: Instanzart `share` mit `Detect.net_shares`, Zielart `share`, `APP_VIEW_TARGETS["net_share_usage"]`.
- Das Modul `net_share` (neue Datei, SPDX) hat einen Check im 5-min-Intervall. critical bei `mounted` false oder
  `hung` true; warning ab `used_percent` 85, critical ab 95.
- Herkunft für gone: shares.
- Tests: Fund, Übernahme, Regeln.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_discovery_match.py tests/test_catalog_sensors.py tests/test_catalog_shares.py tests/test_catalog.py tests/test_agent_report_v4.py
Doku: → T7
Abhängt von: T3, T4

### T7 — Doku DE+EN und CHANGELOG  [ ]
Komponente: monitoring · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-18.md
Änderung:
- Admin: Modul `net_share`; Netz-Mounts nicht mehr in der Plattenliste; gone je Abschnitt.
- Developer: Inventar-Felder `complete` und `shares`, Zielart `share`, Ansicht `net_share_usage`, Frist der
  RDAP-Abfrage.
- CHANGELOG für R-1406 neutral.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_shares.py
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, changelog.d/kern-monitoring-18.md
Task-Review: am Ende

## Entscheidungen
- 2026-11-18 Kevin: R-1267 als Katalog-Modul; Netz-Mounts raus aus der Plattenliste; Schwellen wie bei Platten
  (hängt/fehlt critical, 85/95 %); Mountpunkt und Typ dürfen an den Server, die Quelle nicht.
- 2026-11-18 T4: Der mountinfo-Parser liegt in `internal/probe/mountinfo.go` (`NetMounts`, `NetFSTypes`), damit die
  Zielart `share` in T5 dieselbe Tabelle liest. Netz-Mounts verlassen die Plattenliste nur unter Linux
  (`skippedDisk`), nicht über `skipFSTypes`: FreeBSD und Windows haben keine Share-Prüfung (Nicht-Ziel), dort bleibt
  eine Freigabe eine Platte, wie `TestSkipFSTypesFreeBSD` es für nfs festhält.
- 2026-11-18 T6: Instanzschlüssel einer Freigabe ist ihr Mountpunkt ohne führendes `/`, jedes weitere `/` als `:`
  (`share_key`); `:` kommt in keinem zulässigen Mountpunkt vor, der Schlüssel ist also eindeutig. Ein Mountpunkt mit
  Leerzeichen, `,` oder `+`, einem ersten Segment, das nicht mit Buchstabe oder Ziffer beginnt, oder über 120 Zeichen bleibt im Inventar, ergibt aber keinen Fund (`_INSTANCE_KEY`).
  `clean_inventory` prüft den Mountpunkt nach derselben Regel wie die Zielart `share` im Agent. Das Modul setzt
  `timeout_s` 20 über die 10 s von `stat -f`, damit eine hängende Freigabe als `hung` ankommt. `module_sync.py`
  bleibt unverändert: der Zielname kommt aus `summary["share"]`.
