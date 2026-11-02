<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-server-5 — Spec

Roadmap: R-1000, R-1010, R-1001 (Zug `tasks/kern-server-5.md`).

## Problem / Motivation
Nachzügler aus den Prüfungen von kern-server-3 und kern-frp-2:
- **R-1000:** Ein Refresh, der unter `MTLS_ENFORCE` ohne Zertifikat abgewiesen wird, zählt nicht gegen das
  Rate-Limit je IP, ein so abgewiesener Login schon (Details privat).
- **R-1010:** Die Namensprüfung für Altzeilen ist im FRP-Bulk-ZIP und beim Anlegen eines Admins per CLI
  unvollständig: Beide prüfen nicht alles, was die API für neue Namen verlangt (Details privat).
- **R-1001:** `_NameResolver._run` (`app/core/middleware.py`) leert die Adressen nach einem unerwarteten Fehler
  außerhalb der Runden-Sperre `_round`. Eine gleichzeitige Runde außer der Reihe (`has_address`) kann so ihr frisches
  Ergebnis verlieren (nur Verfügbarkeit, fail-closed). Der Klassen-Docstring nennt nur `_NAME_TTL`, nicht die TTL je
  Instanz.

## Ziel & Nicht-Ziele
Ziel: Jede Zeile ist behoben und durch einen Test belegt.

Nicht-Ziele:
- kein eigener Zähler für Refreshs: der abgewiesene Refresh zählt im selben Zähler wie der fehlgeschlagene Login;
- keine Migration von Altzeilen: Namen, die die API heute abweist, fehlen in der Ausgabe, wie schon bei
  `name_refused`;
- keine neue Regel für Namen: die CLI übernimmt die Regel des Schemas (`UserCreate`).

## Betroffene Komponenten & Dateien
Nur der Server, dazu die Benutzer-Seite und die API-Referenz (DE und EN):
- `apps/server/app/modules/users/auth_router.py`
- `apps/server/app/modules/frp/generate_router.py`
- `apps/server/app/cli.py`
- `apps/server/app/core/middleware.py`
- Tests: `test_cert_user_binding.py`, `test_frp_input_hardening.py`, `test_cli.py`, `test_ip_filter.py`
- `docs/admin/benutzer.html`, `docs/en/admin/users.html`, `docs/developer/api-reference.html`,
  `docs/en/developer/api-reference.html`

## Datenmodell / API / Migrationen
Keine Migration. `POST /api/auth/refresh` kann nach fünf abgewiesenen Versuchen derselben IP binnen 60 s mit `429`
antworten, wie Login und Bootstrap. Kein neues Feld, kein neuer Endpoint.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- R-1000: ein eigener Zähler für Refreshs hielte Login und Refresh getrennt. Beide werden aber durch dieselbe
  fehlende Bedingung abgewiesen, und ein Client ohne Zertifikat kann sich ohnehin nicht anmelden. Empfehlung: der
  gemeinsame Zähler (`_check_rate_limit`).
- R-1010: eine Prüfung im ZIP und in der CLI statt einer Migration, die Altnamen umschreibt. Eine Migration würde
  Namen ändern, die Admins kennen. Empfehlung: prüfen und auslassen.

## Risiken & Rollback
Gering. Jede Task ist einzeln zurücknehmbar (`git revert`). Ein Admin mit einem abgewiesenen Altnamen fehlt im
Bulk-ZIP. Das Log nennt ihn, wie schon bei `name_refused`.

## Doku-Impact
Das Login-Rate-Limit auf der Benutzer-Seite und der Refresh in der API-Referenz nennen den abgewiesenen Refresh (DE
und EN). R-1010 und R-1001 ändern kein dokumentiertes Verhalten. Changelog-Einträge sind neutral.

## Offene Fragen
Keine.
