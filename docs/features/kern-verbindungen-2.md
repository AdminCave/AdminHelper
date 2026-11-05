<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-verbindungen-2 — Verbindungs-Editor v2 und Sitzungsverlauf

Roadmap: R-1066, R-1068 (FEAT, Kevin 2026-11-02). Vorlage `AdminCave/DesignSystem@244e890`
(`ui_kits/adminhelper/editor.jsx`, `connections.jsx` Inspector). Stand `origin/main@c550f4a9`. Baut auf R-1061 (#373)
und R-1065 (#376, Liste v2 mit Inspector).

## Problem / Motivation
- **R-1066:** `apps/desktop/ui/src/components/ConnectionEditor.svelte` ist ein einziges Formular ohne Tabs. Eine
  Verbindung kennt nur Host, Port, Benutzer, Domäne, Schlüssel, URL, Notizen, Tags und `trustCert`; alles weitere
  (Jump-Host, Weiterleitungen, Keepalive, RDP-Anzeige und -Umleitungen) gilt global oder gar nicht
  (`connection/ssh.rs` `build_ssh_args`, `connection/rdp.rs` `build_rdp_args` mit `RdpOptions` aus den Settings).
  „Server zuordnen“ fehlt im Editor, obwohl `serverId` im Modell steht.
- **R-1068:** Der Inspector zeigt nur „Zuletzt“ (`lastUsed`). Es gibt keinen Verlauf mit Beginn, Dauer und Gerät.

## Ziel & Nicht-Ziele
**Ziel:**
- Editor mit Typ-Umschalter und Tabs: SSH *Allgemein / Anmeldung / Optionen*, RDP *Allgemein / Anmeldung / Anzeige*,
  Web nur *Allgemein*. *Allgemein* trägt Name, „Server zuordnen“ (Liste der Server, Server-Modus), Host/Port/Benutzer
  bzw. URL, Tags, Notizen.
- Optionen je Verbindung, jede leer = globaler Standard:
  - SSH: Jump-Host (`-J`), Port-Weiterleitungen L/R/D, Agent-Forwarding (`-A`), Kompression (`-C`), Keepalive
    (`ServerAliveInterval`), Auth-Art Schlüssel/Agent/Passwort.
  - RDP: Skalierung, Fenstermodus, Größe, Leistungsprofil (Überschreibung der globalen Werte), Laufwerke, Audio,
    Drucker, RD-Gateway, NLA.
- Sitzungsverlauf: jedes Verbinden schreibt einen Eintrag (Beginn, Gerät, Ende sofern bekannt); der Inspector zeigt
  „Letzte Sitzungen“ (die letzten 5). Server-Modus: Server-Tabelle und API; lokaler Modus: auf dem Gerät.

**Nicht-Ziele:**
- „Öffnen-Modus je Verbindung“ (eingebettet/eigenes Fenster): ohne eingebettete Sitzungen gibt es nichts zu wählen;
  kommt mit R-1069/R-1097 (Arch-Sessions). Das Feld wird nicht vorab angelegt (YAGNI).
- „Bei Verbindungsabbruch neu verbinden“ und TOFU-Schalter aus dem Mockup: brauchen eine eigene Sitzung (R-1069).
- Dauer externer SSH-Sitzungen: das OS-Terminal meldet kein Ende (`terminal.rs` startet den Emulator und kehrt
  zurück); der Verlauf zeigt dort „—“. RDP kennt das Ende (`monitor_rdp_exit`).
- Web-Frontend: zeigt und bearbeitet keine Verbindungen.

## Betroffene Komponenten & Dateien
- Server: `apps/server/app/modules/connections/{models,schemas,router}.py`, neue Alembic-Revision unter
  `apps/server/alembic/versions/`, Tests unter `apps/server/tests/`. OpenAPI-Snapshot ändert sich.
- Desktop-Backend: `apps/desktop/src-tauri/src/models.rs` (`Connection.options`), `validation.rs`,
  `connection/ssh.rs`, `connection/rdp.rs` (Linux-Argumente und `.rdp`-Datei unter Windows), `commands.rs`,
  `storage.rs` (lokaler Verlauf), `sync.rs` (Server-Client).
- Desktop-UI: `components/ConnectionEditor.svelte`, `components/connections/ConnectionInspector.svelte`,
  `lib/api/types.ts`, `lib/bridge/{index,types}.ts`, `lib/stores/connections.ts`, `lib/i18n/dictionaries.ts`.

## Datenmodell / API / Migrationen
Vorschlag (Kevins Entscheidung, siehe Offene Fragen):
- **`options`** an der Verbindung, ein Objekt `{ssh?: {...}, rdp?: {...}}`, alle Felder optional, unbekannte
  Schlüssel abgelehnt. Server: eigene Spalte `options` (JSON-Text) per Alembic-Revision, Pydantic
  `ConnectionOptions` in Create/Update/Out, Import/Export nehmen es mit. Desktop: `ConnectionOptions` mit
  `#[serde(default)]`, alte Dateien laden ohne Migration.
- **Sitzungen:** Tabelle `connection_sessions` (`id`, `connection_id` FK `ON DELETE CASCADE`, `user_id`, `device`,
  `started_at`, `ended_at` nullable). `POST /connections/{id}/touch` legt zusätzlich einen Eintrag an und liefert
  `sessionId`; neu `POST /connections/{id}/sessions/{sid}/end` und `GET /connections/{id}/sessions?limit=5`
  (Scope wie die Liste). Alte Einträge löscht der Server nach der Speicherdauer. Lokal:
  `sessions.json` je Workspace, dieselbe Form.

## Externe Integrationen
Kein neues Wire-Format. Die SSH-Optionen (`ssh(1)`: `-J`, `-L`, `-R`, `-D`, `-A`, `-C`, `-o ServerAliveInterval`,
`-o PreferredAuthentications`) und die FreeRDP-/`.rdp`-Schalter (`/drive`, `/sound`, `/printer`, `/gateway`,
`/sec:nla`; `drivestoredirect`, `audiomode`, `redirectprinters`, `gatewayhostname`, `enablecredsspsupport`) liest die
jeweilige Task vor dem Bau in der offiziellen Doku nach (OpenSSH-Manpage, FreeRDP-Wiki, Microsoft „Supported RDP
properties“): **nicht verifiziert**.

## Trade-offs & Alternativen
- **Eigene Spalte `options` mit Migration — empfohlen** statt `extra_data` (das der Server heute schon unverändert
  durchreicht): `extra_data` bräuchte keine Migration, prüft aber nichts, erscheint nicht in der OpenAPI und der
  Desktop-Client (`models.rs` ohne Flatten) verlöre das Feld bei jeder Bearbeitung. Die Werte landen in
  Kommandozeilen; Validierung an der Grenze (Server und `validation.rs`) ist Pflicht.
- **Sitzungen in eigener Tabelle — empfohlen** (so in der Zeile) statt aus dem Audit-Log (`connection.accessed`
  steht dort schon): das Audit-Log kennt kein Ende und keine Speicherdauer je Zweck.
- Optionen als feste Spalten je Schalter: viele Spalten für Werte, die nur der Desktop liest; verworfen.

## Risiken & Rollback
- Kommandozeilen-Injektion über Jump-Host, Weiterleitungen, Gateway: strenge Formate (Host, Port, kein führendes
  `-`), Tests mit bösen Werten. `security` prüft die Desktop-Tasks (Risikopfad: Startargumente).
- Migration: additive Spalte und neue Tabelle, Downgrade entfernt beides. Alte Desktop-Clients ignorieren `options`
  (serde ignoriert unbekannte Felder), aber eine Bearbeitung mit altem Client löscht sie (dokumentieren).

## Doku-Impact
`docs/admin/index.html` (Verbindungen: Editor, Optionen, Verlauf) DE+EN, `docs/developer/api-reference.html` und
`server.html` (Felder, Endpunkte, Speicherdauer) DE+EN, `docs/developer/desktop.html` DE+EN, Changelog-Fragment.

## Offene Fragen
1. **Datenmodell `options` (R-1066):** eigene Spalte + Migration + Schema (Empfehlung) oder `extra_data` ohne
   Migration? Hängt: T1–T3, T5.
2. **Sitzungsverlauf, API und Speicherdauer (R-1068):** Tabelle und Endpunkte wie oben (Empfehlung), Speicherdauer
   90 Tage serverseitig, lokal ebenfalls 90 Tage und höchstens 50 je Verbindung (Empfehlung)? Hängt: T6–T8.
3. Gerät im Verlauf: Name des Geräts aus der Geräteregistrierung, sonst der Hostname (Empfehlung)?
