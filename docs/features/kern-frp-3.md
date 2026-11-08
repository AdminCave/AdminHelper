# kern-frp-3: frp 0.69.1 -> 0.72.0

Zug `tasks/kern-frp-3.md`, Roadmap R-1034 (Kevin 2026-11-02: alles auf aktuelle LTS/Stable; Kevin 2026-11-06:
Aenderung an `scripts/vm/bootstrap_linux.sh` freigegeben).

## Problem / Motivation

- **R-1034:** frps-Image, gebuendeltes frpc (Agent-Pakete, Desktop-Sidecar) und die Test-Boxen laufen mit frp
  0.69.1. Die Zeile nannte 0.71.1; aktuell ist 0.72.0 (github.com/fatedier/frp/releases, 2026-11-08). Kevins
  Auftrag ist „aktuelle Stable“, daher Ziel 0.72.0.
- snowdreamtech fuehrt neue Versionen nur noch als `<v>-alpine`/`<v>-debian`: `snowdreamtech/frps:0.72.0` gibt es
  nicht, `0.72.0-alpine` schon. Das alte `0.69.1` war ebenfalls Alpine.

## Ziel & Nicht-Ziele

**Ziel:** Alle Pins auf 0.72.0, Verhalten unveraendert; die Quellen-Zitate im Code, die eine Stelle aus frp v0.69.1
belegen, sind gegen v0.72.0 nachgeprueft und nennen die neue Version.

**Nicht-Ziele:**
- Neue frp-Funktionen (Wire-Protokoll v2, `metricsServer`, `useSystemCa`, die v2-Dashboard-API) zu nutzen.
- Historische Zitate in alten Specs/Ledgern (`docs/features/kern-ca-8.md` usw.) und im CHANGELOG: sie belegen,
  was damals galt.

## Betroffene Komponenten & Dateien

- Pins: `.github/workflows/ci.yml:24-27`, `.github/workflows/release.yml:22-25` (`FRP_VERSION`,
  `FRP_SHA256_LINUX_AMD64`, `FRP_SHA256_WINDOWS_AMD64`), `scripts/vm/bootstrap_linux.sh:17-18`,
  `apps/frps/Dockerfile:5` (Basis-Image samt Digest), `scripts/tests/desktop_e2e_workspaces.sh:40` und
  `scripts/tests/desktop_e2e_connect_tunnel.sh:25` (`FRPC_IMAGE`).
- Test: `apps/server/tests/test_release_images.py:53` (`_FRPS_BASE` verlangt `:<x.y.z>@`, das `-alpine` faellt
  durch) und `:416` (der Gegentest ersetzt `:<v>@`).
- Zitate: `apps/server/app/modules/frp/config_generator.py`, `schemas.py`, `proxy_status.py`,
  `apps/frps/frps-supervisor.sh:118`, `apps/server/tests/test_frp_input_hardening.py`,
  `apps/server/tests/test_frp_status.py`, `scripts/tests/box_tunnelbox.sh`, `scripts/tests/multibox.sh`,
  `SECURITY.md:44`.

## Datenmodell / API / Migrationen

Keine. Kein Vertrag zwischen Server, Web, Desktop und Agent aendert sich.

## Externe Integrationen

frp-Release-Notes v0.70.0, v0.71.0, v0.71.1, v0.72.0 und die Quellen beider Tags (geprueft 2026-11-08):

- **Wire-Protokoll:** der Standard bleibt v1; 0.69.1- und 0.72.0-Gegenstellen sprechen miteinander (gemischte
  Versionen waehrend eines Updates, etwa ein Agent vor dem Server).
- **TLS:** `transport.tls.useSystemCa` ist neu und standardmaessig aus; der Weg mit `trustedCaFile` allein ist
  unveraendert (`pkg/transport/tls.go`, nur in eine Hilfsfunktion herausgezogen). Weder v0.69.1 noch v0.72.0 werten
  das Client-Zertifikat aus (kein `PeerCertificates`/`VerifiedChains` ausserhalb von Tests): die Aussage in
  `SECURITY.md:44` gilt weiter.
- **Doppelte Namen (0.70.0):** frpc lehnt doppelte Proxy- und Visitor-Namen ab (`pkg/config/load.go`). Unsere
  Proxy-Namen sind `frp_tunnels.name` (`unique=True`, `apps/server/app/modules/frp/models.py:91`), der Visitor ist
  `<name>-visitor`; Proxies und Visitors werden getrennt geprueft.
- **frps-Konfig:** alle Schluessel aus `TOP_KEYS` (`frps-supervisor.sh:117-122`) gibt es in v0.72.0 unveraendert;
  neu ist `metricsServer`, ein eigener Listener, der nur mit `port > 0` startet (Standard 0) und nicht in `TOP_KEYS`
  steht, also nicht durchkommt.
- **Dashboard:** `GET /api/proxy/{type}` besteht weiter (`server/api_router.go:43`), `GetProxyInfoResp` und
  `ProxyStatsInfo` sind gleich (`server/http/model/types.go`).
- **Zitierte Stellen gleich:** `bindPort`-Standard 7000 (`ServerConfig.Complete`), `ValidatePort` 0..65535, die
  Log-Zeilen `[<proxy>] start proxy success` (frpc) und `new proxy [<n>] type [<t>] success` (frps).
- **Artefakte:** `frp_0.72.0_linux_amd64.tar.gz` sha256 `daf719b3…9804`, `frp_0.72.0_windows_amd64.zip` sha256
  `5197c1b6…f9ae` (Release-Checksummen). `snowdreamtech/frps:0.72.0-alpine@sha256:bd1b1475…e9a2` und
  `snowdreamtech/frpc:0.72.0-alpine@sha256:ade64d3a…13b9` (`docker buildx imagetools inspect`); das Image traegt
  frps 0.72.0, `curl`, `addgroup`, `adduser`, `find`, die das Dockerfile braucht. Wie schon bei 0.69.1 baut
  snowdreamtech das Binary selbst (Hash ungleich dem Release-Tarball): das Vertrauen in die Image-Quelle aendert
  sich nicht.

## Trade-offs & Alternativen

- **0.71.1 (Zeile) vs. 0.72.0:** 0.72.0 ist die aktuelle Stable; zwischen beiden liegt nichts, was uns bricht
  (siehe oben). Empfehlung 0.72.0.
- **`-alpine` vs. `-debian`:** Alpine wie bisher; das Dockerfile nutzt `addgroup -S`/`adduser -S` (BusyBox).

## Risiken & Rollback

- Ein frpc/frps, das sich anders verhaelt als die Quellen zeigen: `Heavy: scenario --tunnel` faehrt den echten
  3-Host-Datenpfad vor dem Merge (ask-first). Die Desktop-Tunnel-Suiten mit dem frpc-Image laufen im Sammellauf.
- Release-Workflow: die Windows-SHA steht nur in `ci.yml`/`release.yml`; `frp-consistency` vergleicht beide.
- Rollback: Revert des Merge-Commits.

## Doku-Impact

`SECURITY.md` (Version der Pruefung), `changelog.d/kern-frp-3.md` (`### Changed`). Die Seiten unter `docs/` nennen
die frp-Version nur in historischen Release-Abschnitten.

## Offene Fragen

- Heavy `scenario --tunnel` vor dem Merge: Kevins Ja (gefragt 2026-11-08, Empfehlung ja).
