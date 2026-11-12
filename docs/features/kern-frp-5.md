# kern-frp-5 — frps-Plugin prüft mehr Felder, FRP-Konfiguration löschen, Domains über Server

Roadmap: R-1304, R-1305, R-1306, R-1311, R-1318, R-1310 · Stand 2026-11-12, frp v0.72.0

## Problem / Motivation

Nachlese zu arch-frps-identity (R-1215): das frps-Plugin `frps-policy` prüft jede Proxy-Anmeldung gegen die
Policy-Datei des Servers. Dieser Zug erweitert die Prüfungen:

- **R-1305:** Das Plugin prüft bei STCP-Proxys künftig auch `allow_users` und `sk` gegen das, was der Server
  für den Tunnel erzeugt.
- **R-1306:** frps soll den Host-Schlüssel nicht in seinen Proxy-Daten speichern.
- **R-1304:** Login-Prüfung im Plugin vorbereiten. Kevin 2026-11-12: zwei Releases —
  dieser Zug bereitet sie vor (Agent nimmt den Schlüssel an, Plugin kann Login prüfen), ein Folgezug nach dem
  Release schaltet sie scharf.
- **R-1311:** Domain-Prüfung über Server: eine `customDomain` auf mehreren Servern ohne gemeinsame Gruppe.
  Kevin 2026-11-12: die Tunnel-API lehnt den Konflikt ab (409), Altbestand lässt die Policy weg und warnt.
- **R-1318:** Ein Neustart des Plugins durch den Supervisor steht nur als Info-Zeile im Log. Kevin 2026-11-12:
  Warnung mit Zähler, Betriebsdoku.
- **R-1310 (BUG):** `DELETE /api/frp/server-config/{id}` mit Tunneln endet in 500: die Beziehung
  `FrpServerConfig.tunnels` (`apps/server/app/modules/frp/models.py:35`) hat kein `passive_deletes`, das ORM setzt
  `frp_config_id` auf NULL (NotNullViolation), statt die Kaskade der DB greifen zu lassen.

## Ziel & Nicht-Ziele

Ziel: das Plugin lässt nur zu, was der Generator für den Tunnel schreibt, auch `allowUsers` und `secretKey`; frps
speichert den Host-Schlüssel nicht; die Login-Prüfung liegt bereit; Domain-Konflikte über Server werden abgelehnt;
Plugin-Neustarts sind im Log sichtbar; FRP-Konfiguration samt Tunneln lässt sich löschen.

Nicht-Ziele: Login scharfschalten (Folgezug nach dem Release), Rotation je Host (R-1316), Policy-Fenster (R-1317),
eine API- oder UI-Anzeige für Plugin-Neustarts.

## Betroffene Komponenten & Dateien

- Agent (Go): `apps/agent/internal/frpspolicy/{policy.go,handler.go}` + Tests und `testdata/`,
  `apps/agent/internal/frpc/servertoml.go` (`serverRootKeys`, Zeile 18) + Test.
- Server (Python): `apps/server/app/modules/frp/{models.py,policy.py,tunnel_router.py}`, Hooks in
  `apps/server/app/modules/users/` (Zugriffsänderungen ändern `allowUsers`), Tests `test_frp_config.py`,
  `test_frp_policy.py`, `test_frps_policy_live.py`, `test_frp_tunnels.py`.
- frps-Container: `apps/frps/frps-supervisor.sh` (Neustart des Plugins, Zeile 578) + `test_frps_supervisor_policy.py`.

## Datenmodell / API / Migrationen

- Keine Alembic-Migration (die Kaskade steht schon in der DB; nur das ORM-Mapping ändert sich).
- Policy-Format Version 2 (Plugin und Server im selben Release): je Proxy zusätzlich `allowUsers` (Liste) und
  `skHash` (SHA-256 hex oder leer). Das Plugin liest nur Version 2; bis der Server nach dem Update schreibt
  (Start, ≤ 60 s), sind neue Proxy-Anmeldungen abgelehnt (fail-closed, wie heute ohne Datei).
- Tunnel-API: `POST`/`PUT /api/frp/tunnels` antworten 409, wenn eine Domain des Tunnels schon bei einem Tunnel
  eines anderen Servers steht und nicht beide dieselbe nicht leere Gruppe tragen. Neue Fehlerfälle, kein neues
  Feld.
- frpc.toml des Agents: der Agent nimmt den Wurzel-Schlüssel `metadatas.ahProxyKey` an; der Server schreibt ihn in
  diesem Release noch nicht.

## Externe Integrationen

frp v0.72.0 Server-Plugin (`pkg/plugin/server`): Ops `Login` und `NewProxy`, Antwort `unchange=false` ersetzt den
Inhalt vollständig (`handleMutableContent` dekodiert in einen frischen Wert), daher gibt das Plugin den ganzen
Inhalt zurück und entfernt nur den Schlüssel. `msg.NewProxy` trägt `sk` und `allow_users`; der Login-Hook läuft vor
`RegisterControl` und darf den Inhalt ändern.
Quelle: https://github.com/fatedier/frp/tree/v0.72.0 (`pkg/plugin/server/{types,manager,http}.go`, `pkg/msg/msg.go`,
`server/service.go`, `server/control.go`).

## Trade-offs & Alternativen

- Schlüssel aus dem Inhalt entfernen statt Dashboard abschalten: der Server liest den Proxy-Status übers Dashboard.
  Das Plugin dekodiert den Inhalt generisch (Zahlen exakt) und löscht nur den einen Eintrag.
- Login-Bindung: der Host meldet seinen Schlüssel in den Login-Metadaten, das Plugin prüft ihn wie bei Proxys.
  Ohne Schlüssel im Login wäre die Bindung nicht prüfbar, deshalb Agent-Update zuerst.
- Domain-Konflikt: API ablehnen und Altbestand aus der Policy lassen (Kevin), statt nur eines von beiden.

## Risiken & Rollback

- Policy v2 gegen altes Plugin oder umgekehrt: fail-closed, bis beide Seiten aktualisiert sind (ein Release).
- Ein Fehler beim Zurückgeben des Inhalts könnte Proxy-Felder verlieren: Test über den echten frps
  (`test_frps_policy_live.py`) und `scenario --tunnel`.
- Rollback: Revert des Merge-Commits; keine Migration.

## Doku-Impact

`docs/admin/frp-tunnel.html` + EN (Domain-Konflikt, Policy prüft Benutzerliste und Schlüssel), `docs/admin/betrieb.html`
/ `docs/en/admin/operations.html` (Plugin-Neustart im Log), `docs/developer/server.html` + EN (Policy-Format v2),
`changelog.d/kern-frp-5.md`.

## Offene Fragen

Keine: Kevin hat am 2026-11-12 R-1304 (zwei Releases), R-1311 (API + Policy), R-1318 (Log + Doku) und Heavy
(`scenario --tunnel` vor dem Merge) entschieden.
