<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# FRP: extra_config eines Tunnels nur in der Form, die der Agent annimmt

## Problem / Motivation

Die `extra_config` eines Tunnels landet Schlüssel für Schlüssel im `[[proxies]]`-Block der `frpc.toml`
(`apps/server/app/modules/frp/config_generator.py:387-398`). Der Agent nimmt den Text nur in der Form an, die der
Generator schreibt (`checkServerConfig`, `apps/agent/internal/frpc/servertoml.go`): Schlüssel aus Segmenten
`[A-Za-z0-9_-]+`, je Tabelle kein Schlüssel zweimal und keiner als Präfix eines anderen, verglichen ohne Rücksicht
auf Groß-/Kleinschreibung (frp ordnet Felder so zu). Der Server nimmt heute drei Dinge an, die der Agent ablehnt;
dann bekommt der ganze Host keine Konfiguration, alle seine Tunnel fallen aus:

1. Schlüssel mit leeren Segmenten wie `.a`, `a.`, `a..b` (`_TOML_BARE_KEY`, `apps/server/app/modules/frp/schemas.py:59`).
2. Ganzzahlen außerhalb von 64 Bit (TOML-Integer); Python-ints haben keine Grenze (`_check_extra_config`, `:62`).
3. Schlüssel, die mit einem Schlüssel des Generators (`name`, `type`, `localIP`, `localPort`, `secretKey`,
   `allowUsers`, `customDomains`) oder untereinander kollidieren, auch nur in der Schreibweise (`localport`, `Type`)
   oder als Präfix (`localIP.x`).

## Ziel & Nicht-Ziele

Ziel:
- Die API weist alle drei Fälle mit `422` an `extra_config` ab (`POST` und `PUT /api/frp/tunnels`).
- Eine schon gespeicherte Zeile mit einem solchen Wert lässt der Generator mit Warnung weg
  (`without_refused_extra_config`, `config_generator.py:139`), die übrigen Tunnel des Hosts bleiben.

Nicht-Ziele:
- Keine Änderung an der `extra_config` der frps-Konfiguration (eigene Allowlist, R-0411) außer der gemeinsamen
  Schlüssel-Form (1) und der int-Grenze (2), die dort ohnehin nur gültige Werte trifft.
- Keine Änderung am Agent; keine Migration (Altzeilen behandelt der Generator).
- Floats bleiben, wie sie sind (`inf`/`nan` nimmt der Agent an).

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | server | `apps/server/app/modules/frp/schemas.py`, `apps/server/tests/test_frp_input_hardening.py`, `docs/developer/api-reference.html`, `docs/en/developer/api-reference.html`, `CHANGELOG.md` |
| T2 | server | `apps/server/app/modules/frp/config_generator.py`, `apps/server/tests/test_frp_input_hardening.py`, `docs/developer/server.html`, `docs/en/developer/server.html`, `CHANGELOG.md` |

## Datenmodell / API / Migrationen

Keine Migration, kein Schema-Feld neu. Die Validierung von `extra_config` wird strenger (`422` im deklarierten
`HTTPValidationError`-Format); das OpenAPI-Dokument ändert sich nicht (Validator, kein Schema-Bound).

## Externe Integrationen

frp v0.69.1: Felder ohne Rücksicht auf Groß-/Kleinschreibung, TOML-Integer 64 Bit (TOML 1.0, „Integer“). Die Regeln
spiegelt der Agent schon (`servertoml.go`, `keyTable`, `serverKey`); der Server übernimmt sie.

## Trade-offs & Alternativen

1. **Server spiegelt die Agent-Regel** statt dass der Agent großzügiger wird: der Agent ist die letzte Grenze vor
   frpc, die Regel steht dort schon; der Server soll nichts erzeugen, was sie verletzt.
2. **Ganze Zeile weglassen** (wie bei Plugin-Schlüsseln) statt nur den einen Schlüssel: ein Tunnel ohne die Option,
   die der Admin wollte, liefe anders als konfiguriert; weglassen mit Warnung ist ehrlicher.

## Risiken & Rollback

- Eine bestehende Zeile mit einem solchen Schlüssel fällt aus der `frpc.toml` des Hosts; heute fällt der ganze Host.
- Rollback: Revert der zwei Task-Commits.

## Doku-Impact

`docs/developer/api-reference.html` (`POST /api/frp/tunnels`, Satz zu `extra_config`-Schlüsseln, DE+EN);
`docs/developer/server.html:119` (welche gespeicherte `extra_config` der Generator weglässt, DE+EN). CHANGELOG (Fixed).

## Offene Fragen

Keine.
