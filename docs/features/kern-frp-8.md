# kern-frp-8: STCP-Tunnel mit Protokoll web, Schema und Pfad

Roadmap: R-1540 (FEAT). Entscheidungen Kevin 2026-11-17 (A, B, C in der Zeile), Triage 2026-11-18.

## Problem / Motivation

Ein STCP-Tunnel mit Protokoll `web` legt auf Wunsch eine Verbindung an. Der Tunnel-Dialog fragt dafür nur einen
Benutzernamen, der für eine Web-Verbindung nichts bedeutet. Der Server speichert die Verbindung als
`127.0.0.1:<Visitor-Port>` ohne URL (`apps/server/app/modules/frp/_helpers.py`, `create_auto_connection`). Der Desktop
baut beim Auflösen die URL immer als `http://127.0.0.1:<lokaler Port>` (`apps/desktop/src-tauri/src/tunnel.rs`,
`to_visitor`). Ein HTTPS-Ziel wie die PVE-Oberfläche auf 8006 und ein Pfad gehen deshalb nicht. Wechselt der Tunnel
das Protokoll, bleibt die verknüpfte Verbindung beim alten Typ.

## Ziel und Nicht-Ziele

Ziel:
- **A, Desktop:** Beim Auflösen über einen STCP-Visitor ersetzt der Desktop nur Host und Port einer gespeicherten URL
  durch `127.0.0.1:<lokaler Port>`. Schema, Pfad und Query bleiben. Eine Web-Verbindung ohne URL bekommt wie heute
  `http://127.0.0.1:<lokaler Port>`. Die Verbindungs-Ansicht zeigt bei einer Tunnel-Verbindung die aufgelöste Adresse.
- **B, Dialog und API:** Bei Protokoll `web` fragt der Tunnel-Dialog Schema und optional einen Pfad statt des
  Benutzernamens. Vorgabe ist `https` bei Zielport 443, 8006, 8443 oder 9443, sonst `http`. Die API nimmt dafür die
  optionalen Felder `auto_connection_scheme` (`http|https`) und `auto_connection_path` (beginnt mit `/`). Die
  Auto-Verbindung speichert die URL `<schema>://127.0.0.1:<Visitor-Port><pfad>`.
- **C, Server:** Ändert ein Tunnel Protokoll oder Typ, zieht die verknüpfte Verbindung mit, auch eine von Hand
  verknüpfte. Das betrifft den Typ (`ssh|rdp|web`), bei STCP Host `127.0.0.1` und Port gleich Visitor-Port, bei `web`
  die URL. Ein Schema, das der Dialog nicht schickt, übernimmt der Server aus der bisherigen URL der Verbindung, sonst
  gilt `http`.

Nicht-Ziele:
- **„Zertifikat vertrauen anbieten“ aus dem Titel der Zeile:** Eine Web-Verbindung öffnet der Desktop im
  Standard-Browser (`connection/web.rs`), der die Zertifikatswarnung selbst zeigt. `trust_cert` wirkt heute nur bei
  RDP. Ein Schalter im Dialog hätte keine Wirkung, daher entfällt er; am Gate genannt.
- Kein Platzhalter für den Port in der URL (Kevin A).
- HTTPS-Tunnel (`tunnel_type=https`) lösen weiter auf `https://<Domain>` auf. Pfad und Query der gespeicherten URL
  bleiben dort unverändert, wie heute.
- Kein Nachziehen bei einer reinen Änderung des Visitor-Ports: Die Auflösung über das Mapping ersetzt Host und Port
  ohnehin.

## Betroffene Komponenten und Dateien

- **Server** (`apps/server/app/modules/frp/`):
  - `schemas.py`: `FrpTunnelCreate` und `FrpTunnelUpdate` bekommen `auto_connection_scheme: Literal["http","https"] |
    None` und `auto_connection_path: str | None`. Der Pfad beginnt mit `/`, hat höchstens 255 Zeichen und enthält
    keinen Leerraum, kein Steuerzeichen und kein `#`.
  - `_helpers.py`, `create_auto_connection`: STCP mit `web` legt die URL an, der Benutzername entfällt bei `web`.
  - `tunnel_router.py`, `update_tunnel`: neue Hilfsfunktion, die die verknüpfte Verbindung bei geändertem `protocol`
    oder `tunnel_type` nachzieht.
  - Tests: neu `tests/test_frp_auto_connection.py`, dazu `tests/openapi.snapshot.json`.
- **Desktop-Backend:** `apps/desktop/src-tauri/src/tunnel.rs` (`to_visitor` mit `url::Url`, Tests im Modul).
- **Desktop-UI:**
  - `components/infra/TunnelModal.svelte` und `TunnelModal.test.ts`
  - `lib/models/frpTunnel.ts` (Form, Payload, Vorgabe des Schemas) mit Test
  - `lib/api/types.ts`
  - `lib/i18n/dictionaries.ts`
  - `components/connections/ConnectionInspector.svelte` und `ConnectionInspector.test.ts` (aufgelöste Adresse über
    `bridge.resolveConnection`)
- Das Web-Frontend hat keinen Tunnel-Dialog mit Auto-Verbindung: kein Gleichlauf nötig.

## Datenmodell / API / Migrationen

Keine Migration: Die Verbindung hat schon `url`. Die API bekommt zwei optionale Request-Felder; ein älterer Client
schickt sie nicht und erhält das bisherige Verhalten (Schema `http`, kein Pfad). Die OpenAPI-Snapshot-Datei ändert
sich.

## Externe Integrationen

Kein Wire-Format: FRP-Konfiguration und Visitor-Bundle bleiben unverändert. `url::Url::set_host` und `set_port` aus
dem bereits genutzten Crate `url` (<https://docs.rs/url/latest/url/struct.Url.html#method.set_port>).

## Trade-offs und Alternativen

- Die URL speichert den Visitor-Port, und der Desktop ersetzt Host und Port (Kevin A). Ein Port-Platzhalter wäre
  eindeutiger, bräche aber jeden anderen Leser der URL. Empfehlung und Entscheidung: A.
- Das Schema einer Verbindung, deren Protokoll wechselt, kommt aus dem Request, sonst aus der alten URL, sonst `http`.
  Die Alternative, ein Schema aus dem Zielport zu raten, steckt im Dialog als Vorgabe (B), nicht im Server.

## Risiken und Rollback

- Eine bestehende STCP-Web-Verbindung mit von Hand eingetragener URL, die auf einen ganz anderen Host zeigt, wird beim
  Auflösen jetzt auf `127.0.0.1:<lokaler Port>` umgebogen und behält ihr Schema. Heute wird sie ganz durch
  `http://127.0.0.1:<Port>` ersetzt. Der Pfad bleibt also neu erhalten; das ist gewollt (A).
- Nachziehen (C) überschreibt Host und Port einer von Hand verknüpften Verbindung. Das ist so entschieden (C).
- Rollback: Revert der Task-Commits; keine Datenmigration.

## Doku-Impact

`docs/admin/frp-tunnel.html` DE+EN (Auto-Verbindung bei `web`, Auflösung mit Schema und Pfad, Nachziehen beim
Protokollwechsel), `docs/developer/api-reference.html` DE+EN (`POST`/`PUT /api/frp/tunnels`: neue Felder),
`changelog.d/kern-frp-8.md`.

## Offene Fragen

Keine. A, B und C hat Kevin am 2026-11-17 entschieden. Der Vertrauens-Schalter entfällt mit Begründung (Nicht-Ziele).
