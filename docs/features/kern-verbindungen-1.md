<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-verbindungen-1 — Verbindungsliste v2 und Erreichbarkeit

Roadmap: R-1065 (Verbindungsliste v2 nach Mockup), R-1067 (Erreichbarkeit je Verbindung).
Vorlage: Mockup `AdminCave/DesignSystem@244e890 ui_kits/adminhelper/connections.jsx`.

## Problem / Motivation
- **R-1065:** `apps/desktop/ui/src/pages/Connections.svelte` zeigt Karten, sortiert nur nach Name, filtert über
  Chips (einzeln/gruppiert, SSH/RDP/Web) und kennt eine Baumansicht nach Tags. Es gibt keine Favoriten, keinen
  Schnellzugriff, keine Tabelle mit sortierbaren Spalten, keine Mehrfachauswahl, keinen Inspector und keine
  Tastaturbedienung.
- **R-1067:** Die Liste sagt nicht, ob ein Ziel erreichbar ist. Das Mockup zeigt eine Ping-Spalte (`PingCell`),
  einen Wert im Inspector und im Schnellzugriff.

## Ziel & Nicht-Ziele
**Ziel** (nach dem Mockup, mit den Bausteinen aus `components/ui/`, R-1061):
- Linke Leiste ab 1180 px: **Bibliothek** (Alle, Favoriten, Letzte 24 Std., Über Tunnel), **Typ** (SSH/RDP/Web),
  **Ordner** (= Tags, keine eigene Hierarchie), je mit Anzahl.
- **Schnellzugriff:** erst Favoriten, dann zuletzt genutzt, höchstens 4 Kacheln.
- **Tabelle** (Spalten Name, Ziel, Tags, Ping, Zuletzt; sortierbar: Name, Ping, Zuletzt) oder **Karten**; Gruppierung
  nach Server (Host), Ordner (Tag), Typ oder keine; Gruppen einklappbar.
- Suche, aktive Filter als Chips mit „Zurücksetzen“.
- **Mehrfachauswahl** mit Sammelaktionen Tags (hinzufügen/entfernen), Exportieren (CSV), Löschen (mit Bestätigung).
- **Tastatur:** ↑/↓ wählt, ↵ verbindet, Doppelklick verbindet.
- **Inspector** ab 900 px: Typ, Host, Port, Benutzer, Schlüssel, Tunnel, Server, Erreichbar, Zuletzt, Tags,
  Kommando-Vorschau (`ssh …`, `xfreerdp …`, URL), Notizen; Aktionen Verbinden, Bearbeiten, Favorit.
- **Favorit** als Stern in Zeile, Karte und Inspector.
- **Erreichbarkeit (R-1067):** TCP-Probe vom Gerät auf Host und Port jeder sichtbaren Verbindung, Latenz in ms oder
  „nicht erreichbar“; beim Öffnen der Seite und alle 60 s, solange sie sichtbar ist.

**Nicht-Ziele** (YAGNI oder abhängig von anderen Zeilen):
- Bibliothek „Verbunden“, Sammelaktion „In Tabs öffnen“ und Split-Button „Eingebettet/Eigenes Fenster“: Es gibt
  heute keine eingebetteten Sitzungen und keinen Verbindungszustand; das kommt mit R-1069/R-1070 (Arch-Session).
  Verbinden bleibt ein einfacher Knopf mit dem heutigen Verhalten (extern).
- „Letzte Sitzungen“ im Inspector: Es gibt keine Sitzungshistorie, nur `lastUsed`; der Inspector zeigt „Zuletzt“.
- Favoriten-Sync zwischen Geräten (siehe Trade-offs).
- Eine eigene Ordner-Hierarchie neben den Tags.

## Betroffene Komponenten & Dateien
- Desktop-UI: `apps/desktop/ui/src/pages/Connections.svelte` (Umbau), neue Bausteine unter
  `apps/desktop/ui/src/components/connections/` (Leiste, Tabelle, Inspector, Schnellzugriff), neue reine Logik
  `apps/desktop/ui/src/lib/models/connectionList.ts` (Filter, Sortierung, Gruppierung, Schnellzugriff,
  Kommando-Vorschau), `apps/desktop/ui/src/lib/stores/connections.ts` (Favoriten, Ping-Werte),
  `apps/desktop/ui/src/lib/bridge/{index,types}.ts`, `apps/desktop/ui/src/lib/i18n/dictionaries.ts`.
- Desktop-Backend (Rust): `apps/desktop/src-tauri/src/models.rs` (`Settings.favorite_connections`), neuer Befehl
  `probe_targets` (neues Modul `apps/desktop/src-tauri/src/probe.rs`, Registrierung in `commands.rs`/`main.rs`).
- Server: keine Änderung. Kein API-Vertrag, keine Migration.

## Datenmodell / API / Migrationen
- `Settings.favoriteConnections: string[]` (Rust `favorite_connections: Vec<String>`, `#[serde(default)]`): alte
  Settings-Dateien laden ohne Migration. Lokal je Workspace, auch im Server-Modus (IDs der Server-Verbindungen).
- Tauri-Befehl `probe_targets(targets: [{host, port}]) -> [latencyMs | null]`: höchstens 256 Ziele je Aufruf,
  Zeitlimit 1,5 s je Ziel einschließlich DNS, höchstens 16 gleichzeitig. Nur TCP-Connect, kein Byte wird gesendet.
- Export: CSV mit Name, Typ, Host, Port, Benutzer, URL, Tags (keine Passwörter, keine Notizen) über den
  Speichern-Dialog und `write_export_csv` (kommt mit kern-monitoring-3).

## Externe Integrationen
Keine neuen Wire-Formate. Tauri-Befehl nach dem Muster der bestehenden (`#[tauri::command]`, Fehler als
`AppError`); `dialog:allow-save` ist schon freigegeben.

## Trade-offs & Alternativen
- **Favoriten lokal (Settings) statt auf dem Server — empfohlen.** Server-Feld hieße Alembic-Migration,
  API-Änderung und Vertrags-Drift Web↔Desktop; der Nutzen (Favoriten auf allen Geräten) ist nicht verlangt.
  Will Kevin Sync, wird das eine eigene Zeile.
- **Erreichbarkeit per lokaler TCP-Probe — empfohlen** statt Monitoring-Status des Servers: zeigt, ob *dieses
  Gerät* das Ziel erreicht (das, was beim Verbinden zählt), geht auch im lokalen Modus und für Ziele ohne
  Monitoring. Kosten: Netzverkehr vom Gerät (ein SYN je Ziel und Minute). Verbindungen mit Tunnel werden nicht
  geprobt (Ziel liegt hinter FRP), sie zeigen „über Tunnel“.
- Host und Port kommen aus der UI (im Server-Modus kennt Rust die Verbindungen nicht). Grenze gegen Missbrauch aus
  einem kompromittierten Webview: nur TCP-Connect, Obergrenzen wie oben; ein Webview kann ohnehin `fetch` absetzen.

## Risiken & Rollback
- Großer UI-Umbau der meistgenutzten Seite: E2E-Specs, die Selektoren der alten Karten nutzen
  (`apps/desktop/e2e/test/specs/*`), müssen mitziehen; die Desktop-Journeys laufen im Sammellauf (Heavy).
- Probe erzeugt Verbindungsversuche, die Firewalls/IDS loggen können: Intervall 60 s, nur bei sichtbarer Seite.
- Rollback: Revert der Task-Commits. Das Settings-Feld ist abwärtskompatibel (`serde(default)`; `Settings` hat kein
  `deny_unknown_fields`, ein älterer Stand ignoriert das Feld).

## Doku-Impact
Bisher beschreibt keine Seite die Verbindungsliste im Detail. Neu: Abschnitt „Verbindungen“ im Desktop-Teil der
Doku (DE+EN) mit Leiste, Favoriten, Schnellzugriff, Tastatur, Sammelaktionen, Erreichbarkeit; `docs/developer/
desktop.html` (DE+EN) die Befehle `probe_targets`; `changelog.d/kern-verbindungen-1.md`.

## Offene Fragen
- Favoriten-Speicherort und Ping-Quelle: Die Zeilen überlassen sie dem Plan; gewählt ist lokal/TCP-Probe (oben).
  Kevin kann umsteuern, dann neue Zeile.
