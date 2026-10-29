<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-server-1 — Server: Logs und OpenAPI-Nachzügler

Roadmap R-0838, R-0895, R-0906, R-0940, R-0941. Alle fünf Zeilen ändern Log-Ausgabe, Log-Sprache oder die
Beschreibung der API, kein Verhalten für Aufrufer. R-0869 (`users/schemas.py`) überlappt `feature/kern-server-1`
und fährt in `klein-ref-server-2`. `overlap.sh` ohne Treffer für die übrigen Dateien.

## Problem / Motivation
- **R-0906:** Warn-Logs in `core/middleware.py` und `core/identity.py` schreiben `request.url.path` mit `%s`. Der
  Pfad ist percent-decodiert; ein `%0A` im Request landet als echter Zeilenumbruch im Log (Log-Zeilen fälschen).
- **R-0940:** `stream_hub.py` loggt Redis-Fehler mit `exc_info=True`; psycopg/redis-py zitieren dabei die
  Verbindungsdaten (Memory „DB-URL in Fehlermeldungen"). `_reader` loggt deutsch. Soll: nur der Fehlertyp, englisch,
  wie die Rate-Limit-Warnungen (R-0776).
- **R-0941:** `get_backend()` in `core/rate_limit.py` meldet deutsch, die übrigen Rate-Limit-Warnungen englisch.
- **R-0895:** `without_refused_extra_config` loggt die Warnung eines abgelehnten Tunnels bei jedem Sync- und
  Hash-Poll. Dazu fehlt dem Wortlaut „plugin keys" ein Test, und `api-reference.html` verschweigt, dass der
  Servername vor der Prüfung mit `strip()` gekürzt wird.
- **R-0838:** `POST /api/hooks/trigger` und `/trigger/{token}` deklarieren in OpenAPI nur 200 (und 422), obwohl sie
  401, 403, 404 und 429 liefern.

## Ziel & Nicht-Ziele
- Pfad in Logs als `%r` (Steuerzeichen escaped), Redis-Fehler nur als Typ, englische Texte, die Warnung eines
  abgelehnten Tunnels einmal je unveränderter Zeile, `responses=` an den beiden Trigger-Routen, zwei Doku-Sätze.
- Nicht-Ziel: Logs auf anderen Pfaden umbauen, die Logsprache insgesamt vereinheitlichen, 413 deklarieren (das
  setzt das Gateway, nicht die App), die Antworten der Routen ändern.

## Betroffene Komponenten & Dateien
`apps/server/app/core/middleware.py`, `core/identity.py`, `core/rate_limit.py`,
`modules/notifications/stream_hub.py`, `modules/frp/config_generator.py`, `modules/hooks/router.py`,
`apps/server/tests/` (neue und bestehende Tests, `openapi.snapshot.json`), `docs/developer/api-reference.html`
(DE+EN).

## Datenmodell / API / Migrationen
Keine Migration. Der OpenAPI-Snapshot ändert sich (nur `responses` der zwei Trigger-Routen, additiv); der
oasdiff-Gate-Lauf zeigt keinen Bruch.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- R-0906: `%r` statt eines Hilfsfunktions-Wrappers — eine Zeichenänderung je Aufruf, Python escaped `\n`, `\x1b`
  usw. Der Pfad erscheint nun in Anführungszeichen. Empfehlung: `%r`.
- R-0895: „einmal je Zeile" über ein kleines Modul-Dict `(tunnel.id, Schlüssel) → ` (begrenzt wie `_ignored_logged`
  in `identity.py`) statt Absenken auf `debug`; die Warnung bleibt so für den Admin sichtbar. Empfehlung: Dict.

## Risiken & Rollback
`rate_limit.py` und `identity.py` sind Risikopfade (`security` je Task); die Änderung dort ist reine Log-Formatierung.
Rollback per Revert je Task.

## Doku-Impact
`docs/developer/api-reference.html` DE+EN: Satz zum `strip()` des Servernamens. Sonst keine; CHANGELOG-Fragment
`changelog.d/klein-ref-server-1.md`.

## Offene Fragen
Keine.
