# kern-frp-9 — Audit-Eintrag, wenn ein Tunnel-Update die verknüpfte Verbindung umschreibt

## Problem / Motivation
R-1617: `update_tunnel` (`apps/server/app/modules/frp/tunnel_router.py`) ruft bei geändertem `protocol` oder
`tunnel_type` `follow_tunnel` (`_helpers.py`) auf. Das schreibt `kind`, `host`, `port` und `url` der verknüpften
Verbindung um. Auditiert wird nur `frp.tunnel.updated` (Objekt Tunnel). Die Verbindung selbst bekommt keinen
Eintrag, obwohl `docs/admin/betrieb.html` sagt, dass das Ändern von Verbindungen erfasst wird.

## Ziel & Nicht-Ziele
- Ziel: Zieht ein Tunnel-Update die verknüpfte Verbindung nach, schreibt der Server zusätzlich einen
  `connection.updated`-Eintrag (Objekt `connection`, ID und Name der Verbindung, Actor der Anfrage). `detail` nennt
  den auslösenden Tunnel. Der Eintrag entsteht erst nach dem Commit, wie die übrigen Einträge der Route.
- Nicht-Ziel: kein neues Hook-Event `connection.updated` für diesen Weg (eigenes sichtbares Verhalten für
  Hook-Abonnenten, nicht Teil der Zeile). Kein Eintrag für eine neu angelegte Auto-Verbindung (Anlegen läuft heute
  ebenfalls nur über `frp.tunnel.*`; bei Bedarf eine eigene Zeile).

## Betroffene Komponenten & Dateien
`apps/server/app/modules/frp/tunnel_router.py` (`update_tunnel`), `apps/server/tests/test_frp_auto_connection.py`,
`docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `changelog.d/kern-frp-9.md`.

## Datenmodell / API / Migrationen
Keine. Neuer Audit-Eintrag mit bestehender Action `connection.updated`; keine Änderung an Schemas oder OpenAPI.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
- Eintrag in `follow_tunnel` selbst: der Helfer kennt Request und Actor nicht und läuft vor dem Commit. Empfehlung:
  in der Route nach dem Commit, mit dem Actor der Anfrage.
- Nur `detail` am Tunnel-Eintrag erweitern: die Verbindung wäre in `GET /api/audit?object_type=connection` weiter
  unsichtbar. Empfehlung: eigener Eintrag.

## Risiken & Rollback
Gering; ein zusätzlicher Audit-Eintrag. Rollback: Revert des Task-Commits.

## Doku-Impact
`docs/admin/betrieb.html` und `docs/en/admin/operations.html`: ein Halbsatz, dass auch das Nachziehen einer verknüpften Verbindung durch ein
Tunnel-Update als Änderung der Verbindung erfasst wird. `changelog.d/kern-frp-9.md`.

## Offene Fragen
Keine.
