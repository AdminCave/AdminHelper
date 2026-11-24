<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-22 — Nachlese kern-agent-23

Zug `tasks/klein-nachlese-22.md` mit R-1771. `overlap.sh` (2026-11-24): kein offener Branch ändert die betroffenen
Dateien; kern-agent-23 ist gemergt. Stand `origin/main@c7d1f4bed`.

## Problem / Motivation
- **T1 Doku.** `docs/developer/agent.html` und `docs/en/developer/agent.html` (Zeile 224, Zelle `collectDisks()`) sagen
  „Gemeinsamer Code via gopsutil/disk“. Unter FreeBSD stimmt das nur für die Typen und die Rechnung: die Liste der
  Mounts holt `disks_freebsd.go` selbst per `getfsstat`, weil `disk.Partitions` mit `MNT_WAIT` an einem hängenden
  NFS-Mount hält (R-1701). `disk.Partitions` und `disk.Usage` rufen nur Linux und Windows (`disks_other.go`,
  `//go:build !freebsd`).
- **T2 Tests.** `monitor_init_test.go:56,66,131` nennen in ihren Fehlertexten `monitor.Init`; die Funktion heißt
  `push.Init` (`apps/agent/internal/monitor/push/init.go`). Die `TestPush*` in `plan_test.go`, `loadgate_test.go` und
  `reportstate_test.go` fahren seit kern-agent-23 `runCycle` (Collect, dann Done) statt `Push`; ein Kommentar sagt es,
  die Namen bleiben.

## Ziel & Nicht-Ziele
Doku und Meldungen stimmen mit dem Code überein. **Nicht-Ziele:** keine Umbenennung der Tests, keine
Verhaltensänderung; die Testlogik bleibt, nur Fehlertexte und Kommentare ändern sich.

## Betroffene Komponenten & Dateien
`docs/developer/agent.html`, `docs/en/developer/agent.html`, `apps/agent/cmd/adminhelper-agent/monitor_init_test.go`,
`apps/agent/internal/monitor/{plan,loadgate,reportstate,servicelogs_linux}_test.go`.

## Datenmodell / API / Migrationen
Keine.

## Trade-offs & Alternativen
Die `TestPush*`-Namen bleiben (Roadmap-Zeile): eine Umbenennung ändert die Testkennung in Berichten und Läufen ohne
Gewinn.

## Risiken & Rollback
Nur Fehlertexte, Kommentare und eine Doku-Zelle; Revert genügt.

## Doku-Impact
Die Änderung ist die Doku (DE+EN gleichzeitig). Kein `changelog.d`-Fragment (kein Nutzerverhalten).

## Offene Fragen
Keine.
