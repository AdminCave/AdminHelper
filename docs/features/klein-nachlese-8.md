<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-8

## Problem / Motivation
Nachlese-Zeilen aus den Reviews von kern-monitoring-20 (Nits, Dauerauftrag Nit-Regel 2026-11-14). Dieser Zug nimmt
die Zeilen, die lokal verifizierbar sind und keine Datei eines offenen Branches ändern:
- R-1462: kein Test für `module_sync._update`, wenn die neue Katalog-Definition mit dem `interval_s`/`timeout_s` des
  Admins `ProbeConfig.model_validate` nicht besteht (Grund-Rückgabe statt Ausnahme).
- R-1463: kein Test, dass ein übernommener compose-Fund mit Alt-Summary ohne `containers` beim Scan (`_seen_again`)
  `adopted` bleibt.
- R-1464: der Negativtest der Container-Zeile in `FindingsInbox.test.ts` prüft nur ein Regex-`queryByText(...)` auf
  `null`; er soll die Zeilen zählen (`queryAllByText(/^Container: /)` hat Länge 1).
- R-1469: `redis_acl` (und `redis_auth`) über `unixsocket` sind ungetestet
  (`TestUnixSocketSensorSpeaksTheProtocolOfItsService`).
- R-1470: `redis_acl` prüft die Form `user:password` erst in `speakRedis`, nach Verbindungsaufbau; die Prüfung gehört
  vor den Dial.

## Ziel & Nicht-Ziele
Ziel: je Zeile der oben genannte Test bzw. die Verschiebung der Prüfung. Nicht-Ziele: alle übrigen Zeilen des Zugs
(Windows-Agent-Code ohne Windows-Box, Harness-Pfade `release.yml`/`run.sh`/`.claude/rules`, Zeilen, deren Dateien
`feature/kern-monitoring-11` ändert: `catalog/sensors.py`, Mail-/Samba-/LINBO-Agent-Code); sie wandern in
`tasks/klein-nachlese-9.md`.

## Betroffene Komponenten & Dateien
`apps/monitoring/tests/` (module_sync, discovery), `apps/desktop/ui/src/components/monitoring/card/FindingsInbox.test.ts`,
`apps/agent/internal/probe/sensor_proto.go` und `sensor_proto_test.go` / der Unixsocket-Test.

## Datenmodell / API / Migrationen
Keine; R-1470 ändert keinen Vertrag, nur den Zeitpunkt desselben `ErrInvalid`.

## Externe Integrationen
Redis `AUTH <user> <password>` (ACL) — Verhalten bleibt, nur der Prüfzeitpunkt wechselt.

## Trade-offs & Alternativen
R-1470: Prüfung beim Aufbau der Optionen statt in `speakRedis` (Empfehlung) oder nur Reihenfolge in `speakRedis`
(gibt es nicht: der Dial liegt davor).

## Risiken & Rollback
Revert je Task. R-1470 ist Agent-Code: `Heavy: linux-full` im Sammellauf.

## Doku-Impact
Keine (Tests, ein Prüfzeitpunkt ohne sichtbare Wirkung).

## Offene Fragen
Keine.
