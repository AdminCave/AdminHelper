<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-8 — Task-Ledger
Status: aktiv · Branch: feature/klein-nachlese-8 · Review: am Ende
Spec: docs/features/klein-nachlese-8.md (Roadmap R-1462, R-1463, R-1464, R-1469, R-1470)
Heavy: linux-full — apps/agent (R-1470): Sammellauf über main
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1462, R-1463: zwei Monitoring-Tests (module_sync-Update, Alt-Summary bleibt adopted)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_module_sync.py, apps/monitoring/tests/test_discovery_match.py
Beweis: reviewer kern-monitoring-20 T3/T4 2026-11-14 · Dedup-Key: REF:monitoring:module_sync.py:_update-invalid-test, REF:monitoring:discovery.py:_seen_again-legacy-summary-test
Änderung: R-1462: Test, dass `_update` bei einer Admin-Zeit (`interval_s`/`timeout_s`), mit der die neue Definition `ProbeConfig` nicht besteht, den Grund zurückgibt und die Zeile unverändert lässt. R-1463: Test, dass ein übernommener compose-Fund mit Alt-Summary ohne `containers` beim Scan (`_seen_again`) `adopted` bleibt. Reine Tests; ein Test, der schon grün ist, wird mit einer Gegenprobe am Code belegt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_module_sync.py tests/test_discovery_match.py
Doku: keine (Tests)

### T2 — R-1464: Negativtest der Container-Zeile zählt die Zeilen  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/card/FindingsInbox.test.ts
Beweis: reviewer kern-monitoring-20 T5 2026-11-14
Änderung: `queryByText(/Container: .*not a map/)` durch `queryAllByText(/^Container: /)` mit `toHaveLength(1)` ersetzen (nur die Zeile des ersten Fundes); Gegenprobe: ohne die Map-Prüfung im Svelte-Code wäre der Test rot.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/card/FindingsInbox.test.ts
Doku: keine (Tests)

### T3 — R-1469, R-1470: redis_acl-Form vor dem Dial prüfen, redis_acl/redis_auth über unixsocket testen  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_proto.go, apps/agent/internal/probe/sensor_proto_test.go, apps/agent/internal/probe/sensor_unixsocket_test.go
Beweis: reviewer kern-monitoring-20 T6 2026-11-14
Änderung: R-1470: die Prüfung `user:password` beim Aufbau der Protokoll-Optionen vor dem Dial, derselbe `ErrInvalid`, ohne Verbindung; Test: Credential ohne `:` bzw. mit leerem User erzeugt keine Verbindung (Server zählt 0 Verbindungen). R-1469: Fall `redis_acl` und `redis_auth` in `TestUnixSocketSensorSpeaksTheProtocolOfItsService`. Kein Credential im Fehlertext.
Verify: bash scripts/dev/verify.sh agent --strict -- -run 'Redis|UnixSocket'
Doku: keine (kein sichtbares Verhalten)
