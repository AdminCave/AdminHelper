# Einheitliche Namen: ein Name je Server, Kennungen über IDs

Roadmap: R-1210 (FEAT), R-1211 (BUG). Entscheidungen Kevin 2026-11-09 (alle Empfehlungen angenommen, 1a–5a).
Vor dem Release 0.47.0 (R-1110). Stand der Zeilenangaben: `main@f8b5364f`.

## Problem / Motivation

Für einen Host fragt AdminHelper heute an jeder Stelle einen eigenen Namen ab und kopiert ihn:

| Objekt | Felder heute | folgt einer Umbenennung des Servers? |
|---|---|---|
| Server | `name` + `hostname`, beide Pflicht, getrennt eingegeben (`ServerModal.svelte:121-141`); `name` ist zugleich frpc-`user` und Visitor-`serverUser` (`config_generator.py:474,556-563`), nicht eindeutig (`servers/models.py:19-20`) | – |
| Verbindung | `name` (Pflicht, `connections/schemas.py:139`) + `host`; im Server-Tab nicht aus dem Server vorbelegt (`serverConnection.ts:33-47`); Tabs, Titel, Fenster zeigen nur `connection.name` | nein |
| FRP-Tunnel | `name` Pflicht, global eindeutig (`frp/models.py:91`, 409 in `tunnel_router.py:154-156`) = FRP-Proxy-Name; nur Platzhalter `k01-lnx1-ssh` (`TunnelModal.svelte:165`) | nein |
| Auto-Verbindung eines Tunnels | Kopie `"{tunnel.name} (via FRP)"` (`frp/_helpers.py:39,52`) | nein |
| Monitoring | Platzhalter `{{server_name}}`/`{{hostname}}`, Kopie in der Zuordnung, `tag_sync._refresh_names` gleicht ab | ja |

Dazu legt die Gruppierung „Server“ der Verbindungsliste nach `connection.host` ab (`connectionList.ts:156`): alle
Tunnel-Verbindungen landen unter „127.0.0.1“.

**R-1211:** Die FRP-Statusseite ordnet frps-Proxies per `name.split(".")[-1]` den Tunneln zu
(`status_router.py:107-111`). frps führt einen Proxy als `{user}.{proxyName}` (frp-Doku, unten); ein Tunnelname mit
Punkt, etwa aus einem FQDN, wird nie gefunden (`"web01.kunde.de.web01.kunde.de-ssh"` → `"de-ssh"`).

Kern des Problems: Die IDs gibt es schon (`uuid4` für Server, Verbindung, Tunnel; Zertifikat-CN = Server-ID), aber
FRP benutzt Namen als Schlüssel, und die Oberfläche kopiert Namen, statt sie abzuleiten.

## Ziel & Nicht-Ziele

**Ziel**
1. **Kennungen über IDs (1a):** frpc-`user` = Server-ID, Proxy-Name = Tunnel-ID, Visitor `serverUser`/`serverName`
   ebenso. Eine Umbenennung ändert kein frpc.toml und keine Visitor-Konfiguration mehr. Die Statusseite ordnet exakt
   über `{server_id}.{tunnel_id}` zu (R-1211).
2. **Ein Name je Server (2a):** Pflicht ist nur der Name (FQDN empfohlen). Die Adresse (`hostname`) folgt dem Namen,
   solange keine abweichende Adresse (IP, interner Name) eingetragen ist.
3. **Abgeleitete Anzeigenamen (3a):** Verbindungen eines Servers und Tunnel speichern keinen Namen mehr, nur einen
   optionalen **Zusatz**. Anzeige: `{server} · {Zusatz}`, ohne Zusatz `{server} · SSH|RDP|Web`, über einen Tunnel mit
   ` (FRP)`. Der Server berechnet den Anzeigenamen; alle Oberflächen zeigen ihn.
4. **Bestehende Kopien leeren (4a):** Auto-Namen `… (via FRP)` und Namen, die nur Server-/Tunnelnamen oder Adresse
   wiederholen, werden leer (abgeleitet); alles andere bleibt als Zusatz.
5. **Servername eindeutig ab jetzt (5a):** Anlegen und Umbenennen lehnen einen vergebenen Namen ab (ohne
   Groß-/Kleinschreibung); bestehende Doppelte bleiben, Bearbeiten ohne Namensänderung geht.
6. Verbindungsliste gruppiert „Server“ nach dem verknüpften Server.

**Nicht-Ziele (YAGNI)**
- Monitoring: folgt schon (`tag_sync._refresh_names`), keine Änderung.
- Host einer Verbindung folgt nicht live der Serveradresse; der Dialog belegt ihn nur vor.
- Name des Agent-API-Keys (`agent-{server}`, `provisioning/router.py:180`) bleibt eine Kopie.
- frp-`annotations` (Name im frps-Dashboard): der Name stünde wieder im frpc.toml, jede Umbenennung startete frpc neu.
- Bulk-ZIP bleibt `clients/<servername>/frpc.toml` (lesbar), mit den bisherigen Pfadprüfungen.
- Keine DB-Eindeutigkeit für Servernamen (bestehende Doppelte); keine Markierung Doppelter in der Liste.
- Verbindungen ohne Server (auch im lokalen Workspace des Desktops) bleiben wie heute: Name Pflicht.

## Betroffene Komponenten & Dateien

- **Server:** `frp/config_generator.py`, `frp/status_router.py`, `frp/generate_router.py`, `frp/provision_router.py`,
  `provisioning/helpers.py` (Kennungen); `servers/{models,schemas,router}.py` (Name/Adresse, Eindeutigkeit);
  `connections/{models,schemas,router}.py`, `frp/_helpers.py` (Verbindungen); `frp/{models,schemas,tunnel_router}.py`
  (Tunnel); zwei Alembic-Revisionen; `tests/openapi.snapshot.json`.
- **Desktop-UI:** `components/infra/ServerModal.svelte`, `ServerConnectionModal.svelte`, `TunnelModal.svelte`,
  `components/ConnectionEditor.svelte`, `lib/models/{infra,serverConnection,connection,frpTunnel,connectionList}.ts`,
  `lib/stores/infra.ts`, `lib/api/types.ts`, i18n.
- **Desktop-RS:** `src-tauri/src/tunnel.rs:119` (Tunnelname eines Visitors ohne verknüpften Tunnel = Visitor-Name,
  künftig eine UUID).
- **Web:** `modals/FrpStatusModal.svelte:91` zeigt den rohen Proxy-Namen.
- **Desktop-E2E:** `server-crud`, `tunnel-create`, `tunnel-crud`, `connection-crud` (füllen Namensfelder).
- **Test-Skripte:** `scripts/tests/multibox.sh` (`frps_registered`), `box_tunnelbox.sh` (`proxy_started`),
  `box_serverbox.sh` suchen Tunnelnamen in frpc/frps-Logs.
- **Agent:** keine Änderung. Er übernimmt das frpc.toml des Servers; seine Wertprüfung (`servertoml.go:45`) nimmt
  jede Zeichenkette ohne Anführungszeichen/Backslash; `serverName` der Aktivierung zeigt er nur an.

## Datenmodell / API / Migrationen

**Server** (`servers`): `hostname` wird nullable; `NULL` = Adresse folgt dem Namen. API-Ausgabe `hostname` = wirksame
Adresse (Leser wie Monitoring `{{hostname}}`, Ansible, R-1202, `ServerSummary`, `InternalServerOut` bleiben
unverändert), neu `customHostname: bool`. Eingabe: `hostname` optional; leer, fehlend oder gleich dem Namen (ohne
Groß-/Kleinschreibung) speichert `NULL` (ein alter Client, der die wirksame Adresse zurückschickt, setzt also keine
Abweichung). Name: 409, wenn ein anderer Server ihn schon trägt (`lower`), nur beim Anlegen und bei einer Änderung.
Migration: `hostname = NULL`, wo `lower(trim(hostname)) = lower(trim(name))`; Downgrade füllt `NULL` mit dem Namen.

**Verbindung** (`connections`): Spalte `name` hält bei Verbindungen mit Server den Zusatz (`''` = keiner), ohne Server
den Namen wie heute. API-Ausgabe `name` = Anzeigename (alte Clients zeigen damit das Richtige), neu `label` = der
gespeicherte Wert. Eingabe `label`; ein `name` alter Clients wird bei Verbindungen mit Server als Zusatz genommen,
außer er gleicht Anzeigename, Servername oder Adresse (dann `''`). Ohne Server bleibt `name` Pflicht. Über einen
Tunnel = ein Tunnel trägt `connection_id` dieser Verbindung. Löschen eines Servers schreibt den Anzeigenamen seiner
Verbindungen fest, bevor `server_id` per `SET NULL` fällt (sonst stünden sie ohne Namen da). Auto-Verbindung eines
Tunnels: Zusatz `''`. Migration: leert bei Verbindungen mit Server `name`, wenn er (ohne Groß-/Kleinschreibung,
getrimmt) Servername, Adresse, `"{tunnel.name} (via FRP)"` oder `tunnel.name` des verknüpften Tunnels gleicht.

**Tunnel** (`frp_tunnels`): `name` = Zusatz, `''` = keiner; Unique-Constraint und 409 entfallen. API-Ausgabe `name` =
Anzeigename, neu `label`. Eingabe `label` (optional), `name` alter Clients wie bei Verbindungen. Migration: leert
`name`, wenn er Servername oder `{server}-{protocol}` / `{server}-{tunnel_type}` gleicht; Downgrade füllt leere und
doppelte Namen mit einem ID-Suffix und setzt den Constraint wieder.

**FRP-Wire:** `user = "<server_id>"`, Proxy `name = "<tunnel_id>"`, Visitor `name = "<tunnel_id>-visitor"`,
`serverName = "<tunnel_id>"`, `serverUser = "<server_id>"`, Tunnel nach ID sortiert (stabiler Konfig-Hash). Prüfungen,
die nur bestanden, weil Namen im TOML standen (`without_refused_server_name`, `name` in `_CHECKED_TUNNEL_FIELDS`,
`name_refused(frpc_user)`, `generate_router.py:116`), entfallen; der ZIP-Pfad behält seine Prüfung
(`generate_router.py:241`).

**Vertrags-Drift:** neue Ausgabefelder `customHostname`, `label`; Eingaben werden optionaler (für oasdiff nicht
brechend); `name` der Ausgabe ändert die Bedeutung (Anzeige statt Rohwert), bewusst kompatibel für alte Clients.
OpenAPI-Snapshot und Desktop-Vertragstest (`lib/api/types.contract.test.ts`) ziehen mit.

## Externe Integrationen

frp v0.72.0 (`docker-compose.yml` frps, `FRP_VERSION`). Doku gelesen 2026-11-09:
<https://gofrp.org/en/docs/reference/client-configures/> – `user`: „proxy names will be modified to
{user}.{proxyName}“; <https://gofrp.org/en/docs/reference/visitor/> – `serverUser`: „Username that the proxy to be
accessed belongs to“. Keine Einschränkung für Zeichen oder Länge von `user`, Proxy- oder Visitor-Namen genannt;
`{uuid}.{uuid}` (73 Zeichen) gegen frps v0.72.0 **nicht verifiziert** → Heavy `scenario --tunnel` und die
Desktop-Tunnel-Suiten im Sammellauf.

## Trade-offs & Alternativen

- **Kennung: UUID vs. lesbarer Name.** Ein aus dem Servernamen gebildeter Proxy-Name änderte sich mit jeder
  Umbenennung (frpc auf dem Agenten und alle Visitors gleichzeitig) und hätte Punkte (R-1211). UUID: stabil, eindeutig,
  schon vorhanden; Nachteil: das frps-Dashboard zeigt UUIDs, AdminHelpers Statusseite übersetzt. **Gewählt: UUID.**
- **`name` der Ausgabe: Anzeige vs. Rohwert + neues `displayName`.** Rohwert + `displayName` wäre sauberer benannt,
  aber alte Desktops (Server zuerst aktualisiert) zeigten bei geleerten Kopien leere Namen. **Gewählt: `name` =
  Anzeige, `label` = Rohwert.**
- **Anzeigename im Server vs. in jeder UI.** Eine Stelle (Server) hält Desktop, Web, Audit und Fenstertitel gleich;
  die Anzeige ist sprachneutral (`SSH`, `RDP`, `Web`, `(FRP)`). **Gewählt: Server.**
- **Adresse: nullable Spalte vs. nur Vorbelegung im Formular.** Nur Vorbelegung zöge eine Umbenennung nicht nach.
  **Gewählt: nullable mit wirksamer Adresse in der Ausgabe.**

## Risiken & Rollback

- **Einmaliger Wechsel aller Tunnel:** Nach dem Server-Update holt jeder Agent sein neues frpc.toml über den Hash
  (`provision_router.py:95-96`) und startet frpc neu; Desktops brauchen die neue Visitor-Konfiguration. Bis beide Seiten
  umgestellt sind, scheitert eine Tunnel-Verbindung → CHANGELOG/Doku: „Tunnel nach dem Update einmal neu starten“.
- **Portkarte des Desktops** ist nach Visitor-Namen geschlüsselt (`port_registry.rs:69-146`); neue Namen erhalten
  einmalig neue Einträge, `free_port` bevorzugt den Server-Port – in T8 per Test belegen.
- **Mischbetrieb:** alter Desktop + neuer Server zeigt Anzeigenamen richtig (`name`), bei einem Visitor ohne
  verknüpften Tunnel den Visitor-Namen (UUID) – kosmetisch. Neuer Desktop + alter Server: `label`/`customHostname`
  fehlen → Formulare fallen auf `name`/`hostname` zurück.
- **Migrationen** mit Downgrade und Migrationstest je Revision; Rollback = Downgrade + vorheriges Image (FRP stellt
  sich mit dem alten Generator von selbst zurück).
- **Merge-Reihenfolge:** zwei neue Alembic-Revisionen; vor dem Merge auf den aktuellen Kopf von `main` setzen.

## Doku-Impact

`docs/admin/frp-tunnel.html` (DE+EN): Kennungen, einmaliger Neustart nach dem Update, Statusseite;
`docs/developer/server.html` (DE+EN): `generate_frpc_toml(frpc_user=server_id)`, Visitor, Statuszuordnung, Anzeigename
und `label`; Seiten zur Bedienung von Servern/Verbindungen, soweit sie Namensfelder beschreiben (per grep in T12);
`changelog.d/arch-namen.md`.

## Offene Fragen

1. **Heavy `scenario --tunnel` vor dem Merge (ask-first):** Empfehlung ja – das Vorhaben ändert die FRP-Kennungen
   des echten 3-Host-Datenpfads.
