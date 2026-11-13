<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# FRP: Tunnel-Schlüssel je Host erneuern (kern-frp-6)

Roadmap: R-1316 · Ledger: `tasks/kern-frp-6.md`

## Problem / Motivation

Jeder Proxy in der `frpc.toml` eines Hosts trägt einen Schlüssel (`metadatas.ahProxyKey`), den der Server aus
`SECRET_KEY` und der Server-ID ableitet (`apps/server/app/modules/frp/proxy_key.py`); das Plugin `frps-policy` lässt
eine Proxy-Anmeldung nur mit dem Schlüssel des Hosts zu. Heute lässt sich dieser Schlüssel nur für alle Hosts auf
einmal wechseln (neuer `SECRET_KEY` oder neue Version im Ableitungs-Label). Ein Admin, der die `frpc.toml` eines
einzelnen Hosts ersetzen will (etwa nach einer Neuinstallation des Hosts), hat dafür keinen Weg.

## Ziel & Nicht-Ziele

Ziel:
- Jeder Server hat eine **Schlüssel-Generation** (`servers.frp_key_generation`, Ganzzahl, Default 0). Generation 0
  ergibt genau den heutigen Schlüssel; jede höhere Generation ergibt einen neuen.
- Die Generation steigt **automatisch bei jeder Provisionierung** des Servers (`POST
  /api/servers/{id}/provision/activate`) und **auf Admin-Aktion**: `POST /api/servers/{id}/frp-key/rotate` (nur Admin,
  Audit-Eintrag `server.frp_key.rotated`, Antwort `{"generation": n}`).
- Nach dem Wechsel schreibt der Server die Policy neu (`sync_policy`), der Config-Hash des Hosts ändert sich, und der
  Agent holt seine neue `frpc.toml` beim nächsten Lauf selbst.
- Desktop: Knopf „Tunnel-Schlüssel erneuern“ im Tunnel-Reiter der Server-Ansicht, nur für Admins, mit
  Bestätigungsdialog.

Nicht-Ziele:
- Kein Wechsel für bestehende Hosts beim Update (Generation 0 = heute).
- Die Login-Bindung (R-1363) bleibt ein eigener Zug nach dem Release.
- Kein Wechsel am Plugin `frps-policy` (es vergleicht weiter den Hash aus der Policy).

## Betroffene Komponenten & Dateien

- Server: `apps/server/app/modules/servers/models.py` (Spalte), neue Alembic-Revision unter
  `apps/server/alembic/versions/` (nach `d3e5f7a9b1c3`), `apps/server/app/modules/frp/proxy_key.py` (Generation in
  der Ableitung), `config_generator.py` (`generate_frpc_toml` bekommt die Generation), die Aufrufer
  `frp/policy.py`, `frp/provisioner.py`, `frp/provision_router.py`, `frp/generate_router.py`,
  `provisioning/helpers.py`; Auslöser in `provisioning/router.py` (`activate_provision`) und `servers/router.py`
  (neue Route). Tests: `tests/test_frp_proxy_key.py`, `tests/test_frp_policy.py`, `tests/test_config_generator.py`,
  Provisionierungs- und Servers-Tests, OpenAPI-Snapshot.
- Desktop-UI: `apps/desktop/ui/src/lib/api/frp.ts`, `components/infra/tabs/TunnelsTab.svelte`, i18n DE+EN, Tests.
- Web: keine Server-Verwaltung mehr (`apps/web/src/lib/api/servers.ts`: „The web no longer manages servers“), daher
  Frage am Gate.

## Datenmodell / API / Migrationen

- Alembic: `servers.frp_key_generation INTEGER NOT NULL DEFAULT 0` (Server-Default, damit bestehende Zeilen 0
  tragen); Downgrade entfernt die Spalte (alle Hosts fallen auf den Schlüssel der Generation 0 zurück).
- Ableitung: Generation 0 hält die heutige Nachricht `frp-proxy-v1:<server_id>`, Generation n > 0 hängt
  `:<n>` an. Der Schlüssel bleibt zustandslos aus `SECRET_KEY` abgeleitet; die Datenbank speichert keinen Schlüssel.
- Neue Route `POST /api/servers/{server_id}/frp-key/rotate` (Admin, 404 bei unbekanntem Server), erhöht die Generation
  unter Zeilensperre, committet, `sync_policy`, Audit. OpenAPI-Snapshot ändert sich (neue Route, additiv; oasdiff
  ohne Breaking Change).
- Vertrags-Drift: Desktop ruft die Route über `apiRequest`; der Agent ist unberührt (er holt die `frpc.toml` wie bisher
  über den Config-Hash).

## Externe Integrationen

Keine neue: frps sieht nur einen anderen Wert in `metadatas.ahProxyKey`, das Plugin einen anderen Hash in der
Policy. Ein laufender Proxy bleibt bis zum Reconnect des frpc registriert (frps prüft nur `NewProxy`); der Agent
startet frpc nach einer neuen `frpc.toml` neu.

## Trade-offs & Alternativen

- **Generation je Host (gewählt)** gegen einen gespeicherten Zufallsschlüssel je Host: die Generation hält die
  Ableitung zustandslos, kein Geheimnis in der Datenbank, und Generation 0 bewahrt den heutigen Schlüssel ohne
  Rollout.
- **Auslöser Provisionierung + Admin-Aktion** (Kevin 2026-11-13): eine Neuinstallation ersetzt schon API-Key und
  Zertifikat; der Tunnel-Schlüssel folgt ihr.

## Risiken & Rollback

- Ein vergessener Aufrufer, der die Generation nicht weitergibt, würde eine `frpc.toml` mit altem Schlüssel
  ausliefern: frps nähme die Tunnel des Hosts nicht an. Abhilfe: Generation als Pflichtargument von
  `generate_frpc_toml`, Tests über Generator, Policy und Config-Hash mit Generation > 0.
- Rotation während einer Provisionierung: die Route sperrt die Server-Zeile wie die Aktivierung.
- Rollback: Revert der Commits und Downgrade der Migration; Hosts mit Generation > 0 holen danach den Schlüssel der
  Generation 0 beim nächsten Lauf.

## Doku-Impact

`docs/admin/frp-tunnel.html` (+ EN): Schlüssel je Host, Erneuern im Desktop und per API, Provisionierung erneuert
ihn; `docs/developer/api-reference.html` (+ EN) die neue Route; `docs/developer/server.html` (+ EN), wo die Ableitung
beschrieben ist; `changelog.d/kern-frp-6.md`.

## Offene Fragen

- Web-Knopf: Kevin wählte „Web und Desktop“; das Web verwaltet aber bewusst keine Server mehr. Empfehlung: nur Desktop,
  Web-Task bleibt `[?]`.
- Heavy: `scenario --tunnel` vor dem Merge (wie kern-frp-5)?
