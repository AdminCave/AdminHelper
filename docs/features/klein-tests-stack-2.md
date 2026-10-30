<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-stack-2 — Stack-Test: Enroll-Start und stabile FAIL-Zeilen (R-0935, R-0955, R-0899)

## Problem
- R-0935 / R-0955 (dieselbe Ursache): `integration_stack_test.sh` enrollt auf :8444 direkt nach `e2e_up gateway`. `e2e_up`
  wartet nur auf :443; der Gateway haengt am ca-issuer nur mit `service_started`. Nach frischer PKI-Erzeugung antwortet
  :8444 kurz mit 502 oder Connection reset, der Schritt „enrollment on the certless plane failed“ ist flaky (rot, dann
  gruen; db-roles T3 und update-rollback T3 haben es gesehen).
- R-0899 (Teile, die sich belegen lassen):
  - `integration_stack_test.sh` (Abschnitt `app_not_dumpable`) nennt in zwei FAIL-Zeilen PIDs; `heavy.sh first_marker`
    vergleicht die erste FAIL-Zeile dreier Laeufe, wechselnde PIDs verhindern „3x rot mit demselben Marker“.
  - `multibox_test.sh`: der Negativ-Check `! grep -q 'frps-egress' "$FAKE_LOG"` besteht auch, wenn das Log fehlt (grep rc 2).
  - `init-secrets_test.sh` gibt im roten Fall die ganze Test-`.env` aus.
  - `_secret_sources()` in `apps/server/tests/test_env_parity.py` hat keinen eigenen Test.

## Ziel & Nicht-Ziele
Nur Tests und Test-Hilfen unter `scripts/tests/` und `apps/server/tests/`. Kein Eingriff in `docker-compose.yml`
(`depends_on` des Gateways bleibt; die Zeile dort gehoert zu `klein-ref-compose-1`). Nicht in diesem Zug: „Neuerzeugen
nach Leeren nur von Hand belegt“ (R-0899) braucht einen Stack-Lauf und wird eine eigene Roadmap-Zeile.

## Betroffene Dateien
`scripts/tests/lib_e2e_stack.sh`, `scripts/tests/lib_e2e_stack_test.sh`, `scripts/tests/integration_stack_test.sh`,
`scripts/tests/multibox_test.sh`, `scripts/tests/init-secrets_test.sh`, `apps/server/tests/test_env_parity.py`.

## Datenmodell / API / Externes
Keine Aenderung. Der Warte-Helfer fragt :8444 per `curl`; jede Antwort ausser 000/502/503/504 heisst „Gateway erreicht
den ca-issuer“.

## Trade-offs
Warten im Test (neuer Helfer `e2e_wait_enroll_plane`, mit curl-Stub in `lib_e2e_stack_test.sh` pruefbar) statt
`service_healthy` im Compose: der Helfer aendert kein Produktverhalten und kollidiert nicht mit `klein-ref-compose-1`.

## Risiken & Rollback
Reine Tests; Revert des Task-Commits. Die FAIL-Zeilen in `integration_stack_test.sh` laufen nur im Stack-Lauf
(`Heavy: linux-full`, Sammellauf).

## Doku-Impact
Keine.

## Offene Fragen
Keine.
