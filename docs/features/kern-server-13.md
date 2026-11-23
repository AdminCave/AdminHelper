# kern-server-13 — Authentifizierung ohne Server-Kette

Roadmap: R-0692 (REF, Code-Audit 2026-10-21, SRV-15).

## Problem / Motivation

`User.servers` ist `lazy="selectin"` (`apps/server/app/modules/users/models.py:57`), `Server.connections` und
`Server.frp_tunnels` ebenso (`apps/server/app/modules/servers/models.py:29-44`). `_get_user_from_token`
(`apps/server/app/core/auth.py:106`) lädt den Benutzer per `db.get(User, uid)`; für einen Benutzer mit zugewiesenen
Servern zieht das bei jedem authentifizierten Request drei Zusatzabfragen nach sich (Server, ihre Verbindungen,
ihre Tunnel), auch für Routen wie `/api/auth/me`, die nichts davon lesen.

## Ziel & Nicht-Ziele

Ziel:
- `User.servers` lädt erst beim Zugriff (`lazy="select"`). Die Authentifizierung fragt damit nur noch den Benutzer
  (und die Blacklist) ab.
- Wo viele Benutzer samt Servern gelesen werden, lädt die Abfrage sie gezielt mit `selectinload(User.servers)`:
  `list_users` (`modules/users/router.py:48`) und die Visitor-Erzeugung (`modules/frp/generate_router.py:239`).

Nicht-Ziele:
- `Server.connections` und `Server.frp_tunnels` bleiben `selectin`: Server-Listen (`Server.to_dict`) brauchen beide,
  und ohne eager `User.servers` hängen sie nicht mehr an der Authentifizierung.
- Keine Abfrage der Zuordnungstabelle statt `user.servers` (eigene Änderung, nicht gemessen nötig).

## Betroffene Komponenten & Dateien

Server: `app/modules/users/models.py`, `app/modules/users/router.py`, `app/modules/frp/generate_router.py`, neuer
Test `tests/test_auth_query_count.py`.

## Datenmodell / API / Migrationen

Keine. Nur Ladeverhalten des ORM; keine Antwort ändert sich.

## Externe Integrationen

Keine.

## Trade-offs & Alternativen

- Alle drei Beziehungen auf `select` (Vorschlag der Zeile): Server-Listen bekämen N+1 oder bräuchten an jeder
  Stelle `selectinload`; mehr Fläche für denselben Gewinn bei der Authentifizierung. Verworfen.
- Empfehlung: nur `User.servers` umstellen, die zwei Listen-Abfragen gezielt laden.

## Risiken & Rollback

- Zugriff auf `user.servers` nach geschlossener Session (DetachedInstanceError): geprüft, kein Thread oder Hintergrund-
  Task bekommt ein `User`-Objekt; der SSE-Stream gibt nur `user.id` weiter. Die PR-CI fährt die ganze Server-Suite.
- Einzelne Zugriffe auf `user.servers` (Scope-Prüfung, Notify) kosten wie bisher eine Abfrage-Kette, nur erst dort.
- Rollback: Revert des Commits.

## Doku-Impact

Keine (internes Ladeverhalten, keine dokumentierte Schnittstelle).

## Offene Fragen

Keine.
