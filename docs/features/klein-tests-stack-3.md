<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-stack-3 — Stack-Test: Neuerzeugen nach Leeren (R-1006)

## Problem
- R-1006 (Rest von R-0899): Dass der Stack nach `docker compose down -v` mit frischer PKI und frischer Datenbank wieder
  hochkommt (der Weg von `install.sh --reset` und von jedem Neuaufsetzen), ist nur von Hand belegt. Kein Test fährt
  `integration_stack_test.sh` über ein Leeren hinweg: die bestehenden Abschnitte laufen alle gegen einen einmal
  erzeugten Stack.

## Ziel & Nicht-Ziele
Ein neuer letzter Abschnitt `recreate_after_wipe` in `scripts/tests/integration_stack_test.sh`:
- vorher das Wurzel-Zertifikat der PKI festhalten (Fingerabdruck des Roots aus `/app/...` des ca-issuer),
- `e2e_dc down -v --remove-orphans`, dann `e2e_up gateway` und `e2e_wait_enroll_plane`,
- belegen: (a) der Root hat einen anderen Fingerabdruck (frische PKI), (b) ein Gerät aus der Zeit vor dem Leeren wird vom
  Gateway abgewiesen (HTTP 400), (c) eine frische Anmeldung auf :8444 liefert ein Zertifikat, das das Gateway annimmt
  (401 der App), (d) der Admin meldet sich mit `ADMIN_PASSWORD` und dem Zertifikat aus (c) an (der Startup-Lifespan legt ihn an).
Nicht: Änderungen an `docker-compose.yml`, `install.sh` oder produktivem Code; kein Test für `install.sh --reset` selbst.

## Betroffene Dateien
`scripts/tests/integration_stack_test.sh`.

## Datenmodell / API / Externes
Keine Änderung. Genutzt werden die vorhandenen Helfer (`e2e_dc`, `e2e_up`, `e2e_wait_enroll_plane`, `enroll`, `reach`,
`e2e_login`, mit dem Zertifikat des frisch angemeldeten Geräts, weil der Rand mTLS erzwingt).

## Trade-offs
Der Abschnitt steht ganz am Ende, weil er den Stack zerstört und neu baut (Abschnitt 18 verändert schon die Hierarchie);
derselbe Stack, kein zweiter, damit der Lauf nicht länger wird als ein Neustart des Gateways samt ca-issuer.

## Risiken & Rollback
Reiner Test; Revert des Task-Commits. Er läuft nur im Stack-Lauf (`Heavy: linux-full`, Sammellauf). Lokal lässt sich die
Syntax (`bash -n`, shellcheck über den `scripts`-Schritt) prüfen; das Verhalten gegen den echten Stack ist bis zum
Sammellauf „nicht verifiziert“ und wird im PR-Text so genannt.

## Doku-Impact
Keine (Test).

## Offene Fragen
Keine.
