<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-17

## Problem / Motivation
Vier Nits aus Abschlusspruefungen (alle REF, nur Kommentar, Doku, Changelog-Fragment, Testhygiene):
- R-1643: `smartWWN` (`apps/agent/internal/monitor/smart.go`), `docs/developer/agent.html` (DE+EN) und
  `changelog.d/kern-agent-11.md` sagen, die WWN habe "die Form von `lsblk`". Bei NVMe mit NGUID kann `lsblk` eine
  andere Kennung (`eui.` plus 32 Hex-Ziffern) zeigen; der Agent meldet die EUI-64 wie `smartctl`. Welche Kennung
  der Kernel waehlt, ist nicht verifiziert; der Text wird deshalb eingegrenzt, nicht neu behauptet.
- R-1649: `docs/features/ci-19.md` (Trade-off) beschreibt die Suche "vor `.` oder `[`"; der Test sucht den
  Kontext-Namen als ganzes Wort (`test_ci_workflow.py`, Regex mit Lookarounds).
- R-1662: `docs/developer/monitoring.html` (DE+EN, Statuswechsel-Log): `history.server_events` faltet
  `alert_log`-Zeilen je Check und gleichem Wechsel (`(check_id, old_status, new_status)`, nur Check-Zeilen), nicht
  "desselben Objekts"; `changelog.d/kern-monitoring-53.md` hat Umlaute; im Test
  `test_lock_state_waits_for_the_first_writer_of_a_check` schliesst `first` nicht in `try/finally`.
- R-1664: `changelog.d/ops-13.md` hat einen Umlaut.

## Ziel & Nicht-Ziele
Ziel: die Aussagen stimmen mit dem Code ueberein, Fragmente sind umlautfrei, der Test raeumt auch im Fehlerfall auf.
Nicht-Ziele: Verhalten aendern, die WWN-Form aendern.

## Betroffene Komponenten & Dateien
agent (nur Kommentar), monitoring (Test), docs, changelog.d.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine neuen. Die lsblk-Kennung bei NVMe bleibt "nicht verifiziert" und wird so formuliert.

## Trade-offs & Alternativen
Text eingrenzen statt die lsblk-Form des Kernels nachzubauen: kein Verhalten, kein Wire-Format betroffen.

## Risiken & Rollback
Gering; Revert.

## Doku-Impact
Die genannten Seiten DE+EN; sonst keine.

## Offene Fragen
Keine.
