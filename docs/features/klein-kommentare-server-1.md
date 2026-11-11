<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-kommentare-server-1 — Spec

## Problem
- **R-1181:** Der Kommentar an `NotificationOutbox.title` (`apps/server/app/modules/notifications/models.py`, Z. 192–196)
  sagt, der Kanal eines Bündels nenne nur die Server der Abonnements, die ihn verlangt haben. Seit R-1080 wählt die
  Matrix der Person die Kanäle; `resolve_recipients` (`service.py`, Z. 151–153, 213) liefert für "bell" und "out" dieselben
  Server, und `incidents._queue` (Z. 548) setzt den Text aus `channels["out"]`. Der Kommentar beschreibt eine
  Zuordnung je Abonnement, die es nicht mehr gibt.

## Ziel / Nicht-Ziele
Der Kommentar nennt, was gilt: der Text ist der des Pings, der den Eintrag einreiht, und nennt dieselben Server wie die
Glocken-Zeile bei diesem Ping; ein späterer Ping überschreibt die Zeile, nicht den Eintrag. Kein Verhalten ändert sich.

## Dateien
`apps/server/app/modules/notifications/models.py`.

## Datenmodell / API / Integrationen
Keine. Kein OpenAPI-Eintrag betroffen (Spaltenkommentar, kein Routen-Docstring).

## Trade-offs
Keine. Kein Changelog-Fragment (nur ein Kommentar).

## Risiken & Rollback
Keine; ein Commit.

## Doku-Impact
Keine.

## Offene Fragen
Keine.
