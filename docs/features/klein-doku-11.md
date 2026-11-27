# klein-doku-11 — FreeBSD-Platten-Zelle: was von gopsutil kommt

Roadmap R-1775 (REF).

## Problem
`docs/developer/agent.html` (DE + EN, Zeile 224) sagt, FreeBSD nehme von gopsutil "nur die Typen und die Rechnung". Die
Rechnung steht aber in der eigenen reinen Funktion `disksFromFsstat` (Agent, `disks_freebsd.go`) und folgt nur
gopsutils Formel. Falsche Doku ist ein Bug.

## Ziel & Nicht-Ziele
Die Zelle sagt: nur die Typen kommen von gopsutil, gerechnet wird nach gopsutils Formel. Nicht-Ziel: andere Doku-Reste.

## Betroffene Dateien
`docs/developer/agent.html`, `docs/en/developer/agent.html`.

## Datenmodell / API
Keine.

## Risiken & Rollback
Keine; reine Doku.

## Doku-Impact
Das ist die Doku-Aenderung selbst, DE + EN.

## Offene Fragen
Keine.
