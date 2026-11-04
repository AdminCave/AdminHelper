<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-frp-4 — Agent prüft den TLS-Teil des frpc-Texts enger

Zug `tasks/kern-frp-4.md` mit R-1120 (Kevin 2026-11-04: angenommen, vor 0.47.0). Kein offener Branch ändert
`apps/agent/internal/frpc/` oder `docs/developer/agent.html` (`overlap.sh`, 2026-11-04).

## Problem / Motivation

Der Agent übernimmt den frpc-Text des Servers nur in der Form, die `generate_frpc_toml` schreibt
(`checkServerConfig`, `apps/agent/internal/frpc/servertoml.go:73`). Für die Wurzel prüft er die Schlüssel
(`serverRootKeys`, `servertoml.go:18`) und bei `auth.method` auch den Wert (`servertoml.go:133`). Die Werte der
TLS-Schlüssel unter `transport.tls` prüft er nicht, und ein Text ohne sie besteht ebenfalls. Der Generator schreibt
den TLS-Teil immer gleich (`_tls_agent_block`, `apps/server/app/modules/frp/config_generator.py:348`):
`enable = true` und die drei Identitätspfade unter `/etc/adminhelper/identity/`.

## Ziel & Nicht-Ziele

Ziel: Der Agent nimmt einen Server-Text nur an, wenn sein TLS-Teil genau der des Generators ist:
- `transport.tls.enable = true`,
- `trustedCaFile = "/etc/adminhelper/identity/ca.crt"`, `certFile = "/etc/adminhelper/identity/agent.crt"`,
  `keyFile = "/etc/adminhelper/identity/agent.key"`,
- alle vier vorhanden, gleich ob als Tabelle `[transport.tls]` oder als gepunktete Schlüssel in der Wurzel (beide
  Formen nimmt die Prüfung heute an).

Einen anderen Text verwirft er wie heute mit Zeile und Schlüssel, nie dem Wert.

Nicht-Ziele:
- `serverAddr` bleibt frei (Trade-offs).
- Kein neuer Schlüssel, keine Änderung am Generator, am Server oder am Wire-Format.

## Betroffene Komponenten & Dateien

- `apps/agent/internal/frpc/servertoml.go` (Prüfung)
- `apps/agent/internal/frpc/servertoml_test.go`, dazu Testtexte ohne TLS-Teil in `sync_flow_test.go` und
  `apply_test.go`
- `docs/developer/agent.html`, `docs/en/developer/agent.html`, `changelog.d/kern-frp-4.md`

## Datenmodell / API / Migrationen

Keine. Der Generator schreibt schon genau diese Form; die Fixture `apps/agent/internal/frpc/testdata/server_frpc.toml`
hält `test_config_generator.py` mit ihm gleich, und `TestServerConfigAcceptsTheGeneratorForm` nimmt sie weiter an.

## Externe Integrationen

frpc-Konfiguration `transport.tls.*` (gofrp.org, Client-Konfiguration, TLS): ohne `trustedCaFile` prüft frpc das
Zertifikat des Servers nicht. Deshalb verlangt die Prüfung den Schlüssel, statt nur einen falschen Wert abzulehnen.

## Trade-offs & Alternativen

- **`serverAddr` pinnen oder frei lassen.** Gewählt: frei. Der Admin ändert die Adresse in der FRP-Konfiguration
  (`config.server_addr`), und der Agent kennt keinen eigenen Sollwert dafür; ein Pin bräche diese Änderung. Mit dem
  festen TLS-Teil und dem Namen, den der Agent selbst setzt (`withFrpsTLSName`), baut frpc die Verbindung nur zu einem
  frps mit gültigem Zertifikat dieser Installation auf, gleich unter welcher Adresse.
- **Nur `enable = false` ablehnen.** Verworfen: ein fehlendes oder anderes `trustedCaFile` wäre weiter möglich.

## Risiken & Rollback

- Ein Server, der den TLS-Teil anders schreibt, hätte danach keinen Tunnel mehr. Der Agent ist nie neuer als der
  Server, und der Generator schreibt den Teil ohne Bedingung; die Fixture hält beides gleich.
- Rollback: Revert des Task-Commits.

## Doku-Impact

`docs/developer/agent.html` DE+EN, Absatz „Lokale Admin-API“: die Form des TLS-Teils, und der Satz zum Text ohne
TLS-Schlüssel entfällt. `changelog.d/kern-frp-4.md` (`### Changed`).

## Offene Fragen

Keine.
