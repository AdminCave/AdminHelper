<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-23 — Nachlese kern-pycommon-2

Zug `tasks/klein-nachlese-23.md` mit R-1776. `overlap.sh` (2026-11-24): kein offener Branch ändert die Dateien;
kern-pycommon-2 ist gemergt (#665). Der Zug hieß zuerst `klein-nachlese-22`; dieser Slug ist seit #664 vergeben.
Stand `origin/main@fd8687a0c`.

## Problem / Motivation
- **Fixture-Kommentar.** `apps/server/tests/fixtures/mail_template_parity.json` (`_comment`) nennt „the monitoring
  (app/mail_template.py)“; diese Kopie gibt es nicht mehr, der Renderer liegt in
  `apps/pycommon/ah_common/mail_template.py`, den Fall fährt `apps/server/tests/test_notify_mail_template.py`.
- **Kopien-Wächter.** `apps/server/tests/test_no_python_copies.py` (`_TREES`) sucht nur zwischen `server/app` und
  `monitoring/app`. Kopiert jemand eine Funktion aus `ah_common` in einen Dienst, bleibt das unbemerkt (Gegenprobe des
  Prüfers grün). `_TREES` bekommt `apps/pycommon/ah_common`; die Paarbildung nach oberstem Ordner trennt `pycommon`
  von `server` und `monitoring` schon.

## Ziel & Nicht-Ziele
Der Kommentar stimmt, der Wächter sieht eine Kopie aus `ah_common`. **Nicht-Ziele:** keine Funktion verschieben; findet
der erweiterte Wächter bestehende Kopien, kommen sie nur mit Begründung in `_KNOWN` oder werden eine eigene Zeile.

## Betroffene Komponenten & Dateien
`apps/server/tests/fixtures/mail_template_parity.json`, `apps/server/tests/test_no_python_copies.py`.

## Datenmodell / API / Migrationen
Keine.

## Trade-offs & Alternativen
Ein Test mit synthetischer Kopie (Positivkontrolle) gibt es schon für `_shape`; die Gegenprobe der Task ist eine echte
Kopie aus `ah_common` in einem Probe-Worktree, nicht ein neuer Test.

## Risiken & Rollback
Nur Tests. Der Wächter kann rot werden, wenn `ah_common` schon eine Kopie in einem Dienst hat; das wäre ein echter
Fund. Revert genügt.

## Doku-Impact
Keine (Test und Fixture-Kommentar).

## Offene Fragen
Keine.
