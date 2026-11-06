<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-verbindungen-3 — Optionen je Verbindung und Sitzungsverlauf

Roadmap: R-1066, R-1068 (FEAT, Kevin 2026-11-02). Rest aus `kern-verbindungen-2`, dessen Spec
`docs/features/kern-verbindungen-2.md` Problem, Ziel und Nicht-Ziele trägt. Gebaut sind dort Editor-Reiter und
„Server zuordnen“. Hier fehlen noch die Optionen je Verbindung und der Sitzungsverlauf. Stand `origin/main@a3645c00`.

## Entschieden (Kevin 2026-11-05)
- **R-1066:** `options` als eigene Spalte mit Alembic-Migration, nicht `extra_data`.
- **R-1068:** Tabelle und Endpunkte wie in der Spec von kern-verbindungen-2. Speicherdauer 90 Tage, lokal höchstens
  50 Einträge je Verbindung. Als Gerät gilt der Name aus der Geräteregistrierung, sonst der Hostname.

## Problem / Motivation
- **R-1066:** Eine Verbindung kennt weder Jump-Host noch Weiterleitungen, Keepalive, RDP-Anzeige oder Umleitungen.
  Alles gilt global (`connection/ssh.rs` `build_ssh_args`, `connection/rdp.rs` `build_rdp_args` mit `RdpOptions` aus
  den Settings). Die Reiter Optionen und Anzeige des Editors bleiben leer verborgen.
- **R-1068:** Der Inspector zeigt nur „Zuletzt“ (`lastUsed`), keinen Verlauf mit Beginn, Dauer und Gerät.

## Ziel & Nicht-Ziele
**Ziel:**
- Optionen je Verbindung. Bleibt ein Feld leer, gilt der globale Standard:
  - **SSH:** Jump-Host (`-J`), Weiterleitungen L/R/D, Agent-Forwarding (`-A`), Kompression (`-C`), Keepalive,
    Auth-Art Schlüssel/Agent/Passwort.
  - **RDP:** Skalierung, Fenstermodus, Größe und Leistungsprofil überschreiben die globalen Werte; dazu Laufwerke,
    Audio, Drucker, RD-Gateway und NLA.
- **Sitzungsverlauf:** Jedes Verbinden schreibt einen Eintrag mit Beginn, Gerät und Ende (sofern bekannt). Der
  Inspector zeigt die letzten 5.

**Nicht-Ziele:** wie in kern-verbindungen-2:
- kein Öffnen-Modus je Verbindung
- kein Reconnect, kein TOFU-Schalter
- keine Dauer externer SSH-Sitzungen („—“)
- kein Web-Frontend

## Betroffene Komponenten & Dateien
- **Server:**
  - `apps/server/app/modules/connections/{models,schemas,router}.py`
  - zwei Alembic-Revisionen unter `apps/server/alembic/versions/`
  - neue Tests
  - OpenAPI-Snapshot
- **Desktop-Backend:** `apps/desktop/src-tauri/src/`
  - `models.rs`, `validation.rs`
  - `connection/{ssh,rdp,mod}.rs`
  - `storage.rs`, `sync.rs`, `commands.rs`, `main.rs`
- **Desktop-UI:**
  - `components/ConnectionEditor.svelte`
  - `components/connections/ConnectionInspector.svelte`
  - `lib/api/types.ts`, `lib/bridge/{index,types}.ts`
  - `lib/stores/connections.ts`, `lib/i18n/dictionaries.ts`

## Datenmodell / API / Migrationen
- **`options`:** Objekt `{ssh?: {...}, rdp?: {...}}`.
  - Alle Felder sind optional, unbekannte Schlüssel werden abgelehnt (`extra="forbid"`).
  - Server: Spalte `options` (Text, JSON) per Alembic-Revision; Create, Update, Out, Import und Export nehmen sie mit.
  - Desktop: `ConnectionOptions` mit `#[serde(default)]`, alte Dateien laden ohne Migration.
- **Sitzungen:** Tabelle `connection_sessions` per Alembic-Revision.
  - Spalten: `id`, `connection_id` (FK `ON DELETE CASCADE`), `user_id`, `device`, `started_at`, `ended_at`
    (nullable).
  - `POST /connections/{id}/touch` legt zusätzlich einen Eintrag an und liefert `sessionId`.
  - Neu: `POST /connections/{id}/sessions/{sid}/end` und `GET /connections/{id}/sessions?limit=5`, im Scope wie die
    Liste.
  - Einträge, die älter als 90 Tage sind, löscht der Server beim Schreiben.
  - Lokal: `sessions.json` je Workspace, höchstens 50 je Verbindung, ebenfalls 90 Tage.
- Gerät: Server-Modus mit Geräteidentität → Name aus der Registrierung, sonst Hostname.
- **Vertrags-Drift:** Server, Desktop-Bridge und Desktop-UI ändern sich im selben Branch; der Agent ist nicht
  betroffen.

## Externe Integrationen
Kein neues Wire-Format. Die SSH-Schalter (`ssh(1)`: `-J`, `-L`, `-R`, `-D`, `-A`, `-C`, `-o ServerAliveInterval`,
`-o PreferredAuthentications`) und die FreeRDP- bzw. `.rdp`-Schalter (`/drive`, `/sound`, `/printer`, `/gateway`,
`/sec:nla`; `drivestoredirect`, `audiomode`, `redirectprinters`, `gatewayhostname`, `enablecredsspsupport`) liest
jede Task vor dem Bau in der offiziellen Doku nach (OpenSSH-Manpage, FreeRDP-Wiki, Microsoft „Supported RDP
properties“). Bis dahin **nicht verifiziert**.

## Trade-offs & Alternativen
- Eigene Spalte statt `extra_data`: entschieden (Kevin), Begründung in der Spec von kern-verbindungen-2.
- Sitzungen in eigener Tabelle statt aus dem Audit-Log: Das Audit-Log kennt kein Ende und keine eigene Speicherdauer.
- Löschen nach 90 Tagen beim Schreiben statt per Scheduler-Job: Es entsteht kein neuer Job, die Tabelle wächst nur mit
  Sitzungen.

## Risiken & Rollback
- **Kommandozeilen-Injektion** über Jump-Host, Weiterleitungen und Gateway:
  - strenge Formate an beiden Grenzen (Server-Schema und `validation.rs`): Host, Port 1–65535, kein führendes `-`,
    keine Steuerzeichen
  - Tests mit bösen Werten
  - `security` je Task, weil Startargumente und Alembic Risikopfade sind
- **Migrationen:** additiv, der Downgrade entfernt Spalte bzw. Tabelle. Alte Desktop-Clients ignorieren `options`,
  ein Bearbeiten mit altem Client verwirft sie aber (wird dokumentiert).
- **Parallelität:** Die Arch-Vorhaben `arch-ssh-terminal` und `arch-rdp-backend` werden `connection/*.rs`,
  `commands.rs` und `main.rs` berühren. Bei Planung haben sie keinen Commit. Vor jedem Desktop-Task prüft
  `overlap.sh` erneut; bei Überschneidung wird origin/main nach deren Merge hineingemergt.
- **Rollback:** Revert des Merges plus `alembic downgrade` um zwei Revisionen.

## Doku-Impact
- `docs/admin/index.html` (Optionen je Verbindung, Verlauf), DE+EN
- `docs/developer/api-reference.html` (`options`, Sitzungs-Endpunkte, Speicherdauer), DE+EN
- `docs/developer/desktop.html` (Überschreibung der globalen RDP-Werte, lokaler Verlauf), DE+EN
- Changelog-Fragment

## Offene Fragen
Keine. Die Entscheidungen stehen oben.
