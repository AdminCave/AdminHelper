<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-monitoring-1 — Monitoring: Vergleichstest gegen httpx für die Proxy-Wahl

Roadmap R-0844. Nur ein Test, kein Produktivcode. `overlap.sh` ohne Treffer.

## Problem / Motivation
`apps/monitoring/app/core/ssrf.py` liest die Proxies der Umgebung mit der privaten
`httpx._utils.get_environment_proxies`. Der Vergleichstest gegen einen einfachen `httpx.Client`
(`apps/server/tests/test_ssrf_pin.py`, `test_with_a_proxy_httpx_picks_the_path_and_the_direct_one_is_pinned`) läuft nur in der
Server-Suite. Monitoring pinnt httpx getrennt (heute beide 0.28.1): ändert ein Bump dort die Proxy-Regeln, fiele es in der
Monitoring-Suite nicht auf, und ein Request könnte am Pin vorbeigehen.

## Ziel & Nicht-Ziele
Derselbe Vergleichstest in der Monitoring-Suite. Nicht-Ziel: den Code ändern oder die Pins koppeln.

## Betroffene Komponenten & Dateien
`apps/monitoring/tests/test_ssrf_proxy_route.py` (neu).

## Trade-offs
Kopie des Tests statt gemeinsamer Hilfe: Server und Monitoring teilen keinen Testcode (Modulgrenzen), die Kopie ist klein.

## Risiken & Rollback
Test-only; Revert genügt. Wird er bei einem Bump rot, ist das der Zweck.

## Doku-Impact
Keine (interner Test).

## Offene Fragen
Keine.
