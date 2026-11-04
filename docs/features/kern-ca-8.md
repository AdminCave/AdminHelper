<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-8 — Eigener TLS-Name für frps

Roadmap R-1112 (Zug `tasks/kern-ca-8.md`). Stand `origin/main@03c4068a`. Details nur in
`tasks/private/sec-kern-ca-6-notes.md` (Abschnitt R-1112). R-1054 aus demselben Zug fährt im nächsten
(`tasks/kern-ca-9.md`): seine Dateien ändern `feature/kern-ca-6` (`apps/desktop/src-tauri/src/enrollment.rs`) und
`feature/kern-ca-7` (`apps/ca-issuer/app/storage.py`), `overlap.sh` am 2026-11-03.

## Problem / Motivation
frpc prüft das Zertifikat von frps gegen die Kettendatei `ca.crt` aus seinem Enrollment und gegen den Namen aus
`serverAddr` (`docs/admin/frp-tunnel.html`, Abschnitt Tunnel-PKI). Härtung: das frps-Zertifikat bekommt einen eigenen
festen Namen, und frpc verlangt genau diesen (`transport.tls.serverName`). Kevin 2026-11-03: Variante a.

## Ziel & Nicht-Ziele
Ziel:
- Das frps-Leaf trägt zusätzlich den festen DNS-Namen `frps.adminhelper.invalid` (`.invalid` ist nach RFC 6761
  reserviert und löst nie auf); andere Leafs des ca-issuer tragen ihn nicht.
- frpc des Agents setzt `transport.tls.serverName = "frps.adminhelper.invalid"`.
- Jeder Fall mit einem Test, der ohne die Änderung rot ist.

Nicht-Ziele:
- `trustedCaFile` auf das Tunnel-Intermediate einengen (Variante b).
- Trust-Generation im Config-Hash (R-1054, nächster Zug).
- Änderungen an frps selbst, am Gateway oder an `serverAddr`.
- Der Desktop-Visitor: R-1121 (`tasks/kern-ca-9.md`).

## Betroffene Komponenten & Dateien
- ca-issuer: `apps/ca-issuer/app/config.py`, `apps/ca-issuer/app/main.py` (Aufruf `ensure_frps_cert`), Tests
  `apps/ca-issuer/tests/test_frps_cert.py`, `test_gateway_cert.py`, `test_config.py`. `storage.py` bleibt
  unverändert (überlappt `feature/kern-ca-7`). Ein geänderter Name lässt `ensure_frps_cert` das Leaf beim nächsten
  Start neu ausstellen (R-0880, `_names_are`).
- agent: `apps/agent/internal/frpc/sync.go`, `rewrite.go`, `servertoml.go`, Tests im Paket. `checkServerConfig` lehnt
  einen vom Server gesendeten `serverName` weiter ab: der Agent setzt den Namen selbst.
- Doku: `docs/admin/frp-tunnel.html` + EN (Abschnitt Tunnel-PKI), `docs/developer/agent.html` + EN,
  `changelog.d/kern-ca-8.md`.

## Datenmodell / API / Migrationen
Keine Migration, kein Vertragswechsel: der Server schickt dieselbe `frpc.toml`.

## Externe Integrationen
frp v0.69.1, `transport.tls.serverName`: „custom server name of tls certificate. By default, server name if same to
ServerAddr“ (frp v0.69.1, Kommentar zum Feld in der Client-Konfiguration). frpc prüft damit Name statt `serverAddr`; die Kette
prüft es weiter gegen `trustedCaFile`. Ob frps den SNI-Wert auswertet: nicht verifiziert, der Heavy-Lauf zeigt es.

## Trade-offs & Alternativen
- **Fester Name statt eines aus `DOMAIN` abgeleiteten** (`frps.<DOMAIN>`): ein abgeleiteter Name könnte mit einem
  echten Host zusammenfallen; `.invalid` kann das nicht, und der Agent braucht keine Konfiguration.
- **Agent setzt den Namen selbst** statt ihn vom Server zu bekommen: ein alter Agent lehnt einen unbekannten
  TLS-Schlüssel ab und stoppt frpc (`refuseServerConfig`); der Agent kommt aus dem apt-Repo des Servers, ist also
  nie neuer als der Server, dessen ca-issuer den Namen schon ausstellt.
- **Konfiguration, die den Namen nennt:** `EXTRA_SANS` lässt ihn mit einer Warnung weg, statt den Start zu
  verweigern: ein Tippfehler soll den Stack nicht stoppen.

## Risiken & Rollback
- Ein neuer Agent gegen ein frps-Leaf ohne den Namen baut keinen Tunnel auf; ausgeschlossen (siehe oben).
- Der ca-issuer stellt das frps-Leaf beim ersten Start neu aus; frps übernimmt neue Zertifikate selbst (Supervisor,
  `docs/admin/frp-tunnel.html`), Tunnel sind einige Sekunden getrennt.
- Rollback: Revert je Task; ein schon ausgestelltes Leaf mit dem Zusatznamen stört alte Clients nicht.

## Doku-Impact
`docs/admin/frp-tunnel.html` + EN: frpc verlangt den Namen, den nur das frps-Zertifikat trägt;
`docs/developer/agent.html` + EN: der Agent setzt ihn in `frpc.toml`. Changelog `### Security` ohne Details.

## Offene Fragen
1. **Heavy `scenario --tunnel`** vor dem Merge: Kevins Ja.
