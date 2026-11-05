<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-9 — Desktop-Visitor verlangt den frps-Namen

## Problem / Motivation
Seit kern-ca-8 trägt das frps-Zertifikat den festen Namen `frps.adminhelper.invalid`, und der frpc des Agents verlangt
ihn (`transport.tls.serverName`, `apps/agent/internal/frpc/rewrite.go:39`). Der frpc des Desktop-Visitors prüft das
frps-Zertifikat weiter nur gegen `ca.crt` und den Namen aus `serverAddr`. R-1121: der Desktop verlangt denselben Namen.

## Ziel & Nicht-Ziele
- `GET /api/frp/generate/visitor-bundle` liefert zusätzlich `frps_tls_name` (`VisitorBundleOut`, immer gesetzt auf
  `frps.adminhelper.invalid`). Kevin 2026-11-04: Weg c, ein optionales Feld; der Desktop setzt den Namen nur, wenn das
  Feld da ist. So fällt kein Tunnel durch ein Update aus: ein neuer Desktop gegen einen älteren Server bleibt beim
  bisherigen Verhalten, ein älterer Desktop ignoriert das Feld (`VisitorBundle` in `frpc.rs` lehnt unbekannte Felder
  nicht ab).
- Der Desktop schreibt den Wert als `transport.tls.serverName` in die geprüfte `visitor.toml`, nachdem
  `validate_visitor_table` sie angenommen hat. Der Text des Servers selbst setzt `serverName` weiter nicht (die
  Allow-List `TLS_KEYS` bleibt).
- Nicht-Ziele: R-1054 (eigener Zug), Änderungen an frps, am Gateway, am Agent oder an `serverAddr`.

## Betroffene Komponenten & Dateien
- Server: `apps/server/app/modules/frp/schemas.py` (`VisitorBundleOut`), `apps/server/app/modules/frp/generate_router.py`
  (`gen_visitor_bundle`, Konstante mit Verweis auf die Gegenstücke), Tests `apps/server/tests/test_frp_tunnels.py`,
  `apps/server/tests/openapi.snapshot.json` (Vertrag).
- Desktop: `apps/desktop/src-tauri/src/frpc.rs` (`VisitorBundle`, Aufbau der Visitor-Konfiguration), Tests dort.

## Datenmodell / API / Migrationen
Ein neues optionales Antwortfeld `frps_tls_name: string | null` in `VisitorBundleOut`; keine Migration. Vertrags-Drift
nur Server ↔ Desktop; Web und Agent lesen das Bundle nicht.

## Externe Integrationen
frp v0.69.1, `transport.tls.serverName` (wie kern-ca-8, `docs/features/kern-ca-8.md`): frpc prüft den Namen des
frps-Zertifikats gegen diesen Wert statt gegen `serverAddr` und verbindet sich weiter mit `serverAddr`.

## Trade-offs & Alternativen
- Welche Werte der Desktop annimmt: **nur genau `frps.adminhelper.invalid`** (Empfehlung) statt jedes Hostnamens. Der
  Name ist fest (Gegenstück `FRPS_TLS_NAME` in `apps/ca-issuer/app/config.py`); ein anderer Wert ist ein Fehler des
  Servers, und der Desktop lehnt das Bundle dann ab, wie jeden anderen unerlaubten Inhalt der `visitor.toml`.
- Weg a (Desktop setzt den Namen ohne Feld) und b (Server schreibt ihn in die `visitor.toml`): von Kevin verworfen
  (2026-11-04), weil ein Update dabei Tunnel trennt.

## Risiken & Rollback
- Ein neuer Desktop gegen einen Server, dessen frps-Zertifikat den Namen noch nicht trägt: der Server liefert das Feld
  erst in der Version, deren ca-issuer den Namen schon ausstellt (kern-ca-8); beide kommen aus demselben Compose-Stand,
  und der ca-issuer stellt das frps-Zertifikat mit dem Namen beim ersten Start neu aus.
- Rollback: Revert der Tasks; ein Desktop ohne das Feld verhält sich wie vorher.

## Doku-Impact
`docs/admin/frp-tunnel.html` + EN (Tunnel-PKI: auch der Desktop verlangt den Namen), `docs/developer/api-reference.html`
+ EN (`visitor-bundle` liefert `frps_tls_name`), Changelog-Fragment.

## Offene Fragen
Keine. R-1054 (Trust-Generation) wandert in einen eigenen Zug; die Frage, ob es eine Architektur-Session wird, geht an
Kevin.
