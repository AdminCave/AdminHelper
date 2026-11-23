# klein-tests-agent-2 — probe-Test ohne echten Docker

Roadmap: R-1729 (BUG, Test).

## Problem
`TestHTTPSensorTellsASilentServerOfPlainTextWithinAShortTimeout` (`apps/agent/internal/probe/sensor_net_test.go:462`)
gibt dem HTTP-Sensor eine Sekunde und lässt den Guard die veröffentlichten Ports der Container über den echten Docker
lesen (`checkPublished`, `guard.go:504`; `publishedPorts` ist im Test nicht gestubbt). Mit vielen Containern auf dem
Host dauert schon der Dial rund 850 ms, und der Sensor läuft in sein Timeout: auf der Dev-Box 19 von 20 Läufen rot,
auf der CI (ohne Container) grün.

## Ziel & Nicht-Ziele
- Der Test stubbt `publishedPorts` wie `app_web_test.go:216-218` und hängt nicht mehr an Docker.
- Keine Änderung am Guard, am Sensor oder am Timeout des Tests.

## Doku-Impact
Keine (nur ein Test).

## Risiken & Rollback
Keine; ein Commit, per `git revert` zurücknehmbar.
