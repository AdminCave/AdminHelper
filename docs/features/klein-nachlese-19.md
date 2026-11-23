<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-19

## Problem / Motivation
Ein Nit aus der Abschlusspruefung von ops-15 (REF, Doku):
- R-1726: `README.md:194-195` zaehlt auf, was `scripts/uninstall.sh` entfernt (`./data`/`./certs` und die
  `.env`-Geheimnisse); `./repo` (das Agent-Paket-Repo) fehlt, obwohl `uninstall.sh:116` und `:159` es loeschen.

## Ziel & Nicht-Ziele
Ziel: die Aufzaehlung im README nennt `./repo`. Nicht-Ziele: `uninstall.sh` aendern, weitere Doku umschreiben.

## Betroffene Komponenten & Dateien
`README.md` (Englisch, ein Satzteil). Eine deutsche Fassung dieser Stelle gibt es nicht.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
Nur der Satzteil, kein Umbau des Absatzes.

## Risiken & Rollback
Keine; Revert.

## Doku-Impact
Die Aenderung ist die Doku (`README.md`); `changelog.d` entfaellt, es aendert sich kein Verhalten.

## Offene Fragen
Keine.
