<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-desktop-8

## Problem / Motivation
R-1522: `scripts/tests/desktop_e2e_connect_tunnel.sh` (Z. 40) und `desktop_e2e_workspaces.sh` (Z. 61) definieren
`wait_log` als `docker logs … | grep -qE …` unter `set -uo pipefail`. `grep -q` beendet sich am ersten Treffer,
`docker logs` bekommt SIGPIPE, und die Pipeline meldet unter pipefail Fehlschlag, obwohl der Treffer da ist: ein
Wartepunkt läuft dann in sein Timeout. Dasselbe Muster, das R-1493 in `desktop_e2e_connect.sh` behoben hat
(`docker logs` zuerst in eine Variable, dann `grep -qE … <<<"$log"`).

## Ziel & Nicht-Ziele
Ziel: in beiden Skripten jede Pipeline `<Log-Quelle> | grep -q` (auch `wait_rdp_log`, die frps-Schleifen, die sshd-
und nginx-Prüfung in `connect_tunnel`) liest die Quelle erst in eine Variable. Nicht-Ziele: pipefail abschalten,
Timeouts ändern, andere Skripte.

## Betroffene Komponenten & Dateien
`scripts/tests/desktop_e2e_connect_tunnel.sh`, `scripts/tests/desktop_e2e_workspaces.sh` (Komponente `scripts`;
Harness-Pfad, von Kevin am 2026-11-19 freigegeben, Notiz der Zeile).

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
`grep … <<<"$log"` (Empfehlung, wie R-1493) oder `|| true`/`set +o pipefail` (verdeckt echte Fehler).

## Risiken & Rollback
Live-Skripte brauchen Docker und die Desktop-Box; ihr Verhalten bleibt bis zum nächsten Heavy-Lauf nicht
verifiziert. Lokal belegt: Gegenprobe der SIGPIPE-Semantik (alte Form rot, neue grün) und `verify.sh scripts`
(shellcheck/Syntax). Rollback: Revert.

## Doku-Impact
Keiner (Testskripte).

## Offene Fragen
Keine.
