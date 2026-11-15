<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-5

## Problem / Motivation
Drei Nits aus dem Review von `arch-monitoring-app-collector` (R-1429):
- `app_ldap_test.go:540`: der Fall „a notice of disconnection“ schließt nur die Verbindung (die Antwort ist leer);
  der Name verspricht eine Benachrichtigung. Die echte Benachrichtigung (Message-ID 0) prüft der Fall in Zeile 590.
- `openProcRoot` (`app_wordpress.go`) prüft `runtime.GOOS` und liefert außerhalb Linux `ErrUnsupported`; kein Test
  ruft sie selbst auf (`TestTheWordPressViewOutsideLinux` ersetzt `containerRoot`).
- `apps/monitoring/app/catalog/sensors.py:13`: eine Docstring-Zeile mit 169 Zeichen, der Rest bricht bei etwa 90.

## Ziel & Nicht-Ziele
Ziel: Name korrigieren, `openProcRoot` direkt testen, Zeile umbrechen. Nicht-Ziele: Verhalten ändern.

## Betroffene Komponenten & Dateien
`apps/agent/internal/probe/app_ldap_test.go`, `app_wordpress_test.go`; `apps/monitoring/app/catalog/sensors.py`.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
Der GOOS-Zweig ist auf der Linux-Dev-Box nicht ausführbar, und ein Skip wäre unter `--strict` rot. Der Test prüft
deshalb je Plattform das, was `openProcRoot` dort tun muss: unter Linux öffnet `openProcRoot(os.Getpid())`, sonst
`ErrUnsupported`. Der nicht-Linux-Zweig wird hier nur kompiliert (`GOOS=windows go vet`), nicht ausgeführt; das
Ergebnis nennt der PR-Text.

## Risiken & Rollback
Nur Tests und ein Docstring; Revert je Task.

## Doku-Impact
Keine.

## Offene Fragen
Keine.
