<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Oberfläche neu (Architektur, Zug 1)

Roadmap R-1225 (FEAT, Architektur) · Zug `arch-monitoring-ui` · Kevin 2026-11-09, Monitoring-Konzept (§3.10,
§3.11, §3.13, §3.14, §5, Entscheidungen „Mockup“, 3, 9a, 9c). Stand des Codes: `origin/main@2980eaab5`. `datei:zeile`
gilt für diesen Stand; Dateien, die #438 (`arch-monitoring-module`, R-1223) noch ändert, nennt die Spec nur mit
Funktions- oder Routennamen. Gebaut wird erst, wenn #438 gemergt ist (der Datenvertrag: Katalog, Erkennung, Funde,
`probe`-Checks, Collector-Metriken).

R-1226 (Dienste-Details mit Logs, Stufe 1–3) und R-1227 (Details der bestehenden Checks) waren demselben Zug
zugeordnet. Ihre Agent-Dateien (`apps/agent/internal/monitor/services*.go`, `system_linux.go`, `updates_linux.go`)
und `apps/monitoring/app/checkers/agent.py` ändert der offene Branch `feature/arch-freebsd-agent` (R-1247); sie fahren
im Folgezug `arch-monitoring-ui-2` auf dem Gerüst dieses Zugs. Aus R-1227 nimmt dieser Zug nur das HTTPS-Zertifikat im
HTTP-Check mit (T2): es ist die erste Quelle des Querschnitts „Zertifikate & Domains“ und berührt keine Agent-Datei.

## Problem / Motivation

Die Server-Ansicht des Monitorings (`MonServerDashboard.svelte`, eingebunden in
`apps/desktop/ui/src/components/monitoring/MonitoringOverview.svelte:27`) reiht je Check-Typ eine Sektion aneinander
(Live, Netz, Heartbeat, Dienste, System, Docker, Backups, ZFS, SMART, Prognose) und zeigt Rohwerte. Mit den Modulen
aus R-1223 kommen je Server beliebig viele Dienst-Instanzen (nginx, Nextcloud, MariaDB …) mit eigenen Checks dazu,
dazu ein Funde-Eingang. Die heutige Ansicht hat dafür keinen Platz: keine Karten je Modul-Instanz, kein „Neu
gefunden“, keine Sicht über alle Server („läuft etwas ab, sind die Backups da?“), kein Hinweis, wenn eine
Benachrichtigung unterdrückt wird, und keine Warnung, wenn das Monitoring selbst nichts mehr liefert. Die
Monitoring-Kosten, die der Agent seit R-1223 je Collector misst, sieht niemand.

## Ziel & Nicht-Ziele

**Ziel (R-1225):**
- **Server-Seite neu:** Kopf mit Problemzahl und [Jetzt scannen]; Karte „System“ (bündelt die heutigen Sektionen
  Live, Netz, Heartbeat, System, ZFS, SMART, Prognose); eigene Karten Dienste, Docker, Backups (die heutigen
  Sektionen); **eine generische Karte je Modul-Instanz** aus der Katalog-Definition (Kennzahlen `card` plus Checks);
  Karte „Neu gefunden (n)“ mit übernehmen / alle übernehmen / ignorieren. Karten mit Status ok sind zugeklappt, Karten
  mit Problem aufgeklappt; was grün ist, ist eine Zeile (Konzept §3.14).
- **Klartext statt Rohwerten:** Fühler-Status (`no_credential`, `denied`, `not_allowed`, `unsupported`,
  `ambiguous_target`, `invalid`), Ablaufdaten und Alter als Sätze („Zertifikat läuft in 9 Tagen ab“, „Zugangsdaten
  fehlen“), Zahlen mit Einheit.
- **Abhängigkeits-Unterdrückung sichtbar:** die Unterdrückung selbst gibt es (`muted_reason`,
  `apps/monitoring/app/alerter.py:353`: Wartungsfenster, Host down; mit #438 auch „stiller Check“); die Status-API
  liefert den Grund je Check mit, die Karten zeigen ihn („Host down — Meldungen unterdrückt“).
- **Querschnitt über alle Server** als Reiter der Monitoring-Seite (`apps/desktop/ui/src/pages/Monitoring.svelte:40`):
  Zertifikate & Domains (nach Ablauf sortiert), Backups, Updates & Neustarts, Funde (Eingang aller Server).
- **Monitoring-Kosten je Server** (Dauer und CPU-Zeit je Collector, gebremste Collector, Zeitlimit-Treffer) auf der
  Server-Seite.
- **Desktop-Warnung „Monitoring seit X min ohne Ergebnis“** (Entscheidung 9c, kein externer Ping).
- **Zugangsdaten hinterlegen** aus der Karte (Entscheidung 3): der Desktop öffnet sein eingebettetes Terminal per SSH
  auf den Host mit dem festen Befehl `sudo adminhelper-agent monitor credential set <ref>`; das Geheimnis tippt der
  Admin dort ein (der Agent fragt ohne Echo), es läuft nie durch den Desktop-Code, den Server oder die Monitoring-DB.
- **Ohne Mockup, aber gut:** nur Tokens und Komponenten aus `apps/desktop/ui/src/components/ui/` (Design-Programm
  R-1061 ff.), keine eigenen Farben oder Abstände; Karte, Querschnitts-Tabelle und Funde-Eingang als wiederverwendbare
  Komponenten; Screenshots aus der echten App (Desktop-E2E auf der VM) gehen vor dem Merge an Kevin.

**Nicht-Ziele:**
- Dienste-Details mit Logs (R-1226), volle Dienste-Liste, Top-Prozesse, Paketnamen, Docker-Gruppen, ZFS-/PBS-Details
  (R-1227) — Folgezug `arch-monitoring-ui-2`, gebaut in die Karten dieses Zugs.
- Alarm auf Zertifikatsablauf: der HTTP-Check bekommt das Zertifikat nur als Detail, sein Status ändert sich nicht.
  Alarmieren wird der zentrale Fühler `tls` (R-1224, `arch-monitoring-module-2`) mit den Schwellen aus Konzept §5.
- Domain-Ablauf (RDAP) als Datenquelle — kommt mit R-1224; die Tabelle nimmt ihn ohne Umbau auf (siehe API).
- Querschnitt „Geräte“ (UniFi): ohne Datenquelle, bis die UniFi-Welle kommt (offene Frage 1).
- Die Verwaltungsansicht eines Servers (`components/infra/tabs/MonitoringTab.svelte`: Checks, Templates, Wartung)
  bleibt, wie sie ist.
- Web-Frontend: das Monitoring lebt nur im Desktop.

## Betroffene Komponenten & Dateien

| Komponente | Dateien |
|---|---|
| Monitoring | `app/routers/checks.py` (Status-Routen ab `get_server_status`, `:452`; `get_status_summary`, `:466`), `app/schemas.py`, `app/alerter.py` (`muted_reason` `:353`, `_host_is_down` `:378`), `app/checkers/http.py` (Hop-Schleife `:77`, `tls_note` `:121`), Tests, `tests/openapi.snapshot.json` |
| Desktop-UI | `lib/api/monitoring.ts`, `lib/api/types.ts`, `lib/models/monitoring.ts`, `lib/stores/monitoring.ts` (Refresh `:492`), neu `lib/models/monitoringText.ts`, neu `lib/stores/monitoringPulse.ts`, `components/monitoring/MonServerDashboard.svelte` (Umbau statt Neubau), neu `components/monitoring/card/*`, neu `components/monitoring/cross/*`, `pages/Monitoring.svelte`, `components/StatusBar.svelte`, `lib/bridge/index.ts` (`terminalOpenSsh` `:307`), `lib/i18n/dictionaries.ts` |
| Desktop-Rust | `src/commands.rs` (`ssh_spawn` `:694`, `terminal_open_ssh` `:760`), `src/connection/ssh.rs` (`build_ssh_args` `:24`), `build.rs` (`COMMANDS` `:9`), `src/main.rs` (`terminal_open_ssh` im `generate_handler!`, `:293`), `capabilities/default.json` (`:56`), `src/capabilities.rs` |
| Desktop-E2E | neu `apps/desktop/e2e/test/specs/monitoring-server-page.live.js`, `scripts/tests/desktop_e2e_monitoring.sh` |
| Server | keine Änderung: der Proxy (`apps/server/app/modules/monitoring_proxy/router.py`, `_ALLOWED_PATH_PREFIXES`) reicht `status/…`, `catalog`, `discovery`, `findings` schon durch (letztere mit #438) |
| Agent | keine Änderung |

## Datenmodell / API / Migrationen

Keine Migration. Alle API-Änderungen sind additiv (neue Felder, eine neue Route); bestehende Clients lesen weiter.

**Monitoring-API (über den Server-Proxy):**
- Check-Antworten von `GET /status` und `GET /status/server/{server_id}` tragen zusätzlich `muted_reason`
  (`"maintenance window"` · `"host down"` · `"silent check"` · `null`). Berechnet je Antwort gebündelt: Wartungsfenster
  einmal laden, Host-down einmal je Server bestimmen; dieselbe Semantik wie `alerter.muted_reason`, ein Test vergleicht
  beide über dieselben Fälle (keine zweite Wahrheit, die driftet).
- `GET /status/summary` trägt zusätzlich `last_result_at` (jüngstes `MonitorState.last_check` aktiver Checks, `null`
  ohne Checks) und `min_interval_s` (kleinstes Intervall aktiver Checks). Ein `max()` und ein `min()` in SQL, kein
  Zeilen-Materialisieren (die Route ist auf Last getrimmt, Kommentar dort).
- Neu `GET /status/server/{server_id}/costs`: je Collector Mittel über die letzte Stunde von Dauer und CPU-Zeit,
  Summe der Zeitlimit-Treffer, aktueller Faktor und gebremst ja/nein, aus den Reihen
  `monitor_agent_collector_{duration_ms,cpu_ms,timeouts,factor,throttled}` (R-1223, Tags `server_id`, `collector`);
  VictoriaMetrics nicht erreichbar → 502 wie die anderen Metrik-Routen.
- HTTP-Check: bei `https` und eingeschalteter Zertifikatsprüfung `details.cert` = `not_before`, `not_after`, `issuer`
  (CN bzw. O), `subject_cn` des ersten https-Hops (der eingetragenen Adresse bzw. ihres ersten https-Ziels). Mit
  ausgeschalteter Prüfung (`verify_ssl: false`) kein `cert`: ohne Prüfung liefert `ssl` nur das binäre Zertifikat, und
  ein Parser wäre eine neue Abhängigkeit. Der Weg an das Zertifikat (httpx-Erweiterung `network_stream`,
  `get_extra_info("ssl_object")`, durch den eigenen Transport `_PinnedTransport` hindurch) ist **nicht verifiziert**,
  bis T2 ihn in der httpx- und Python-`ssl`-Doku nachgelesen und mit einem Test belegt hat.

**Vertrag für die Folgezüge (Querschnitt „Zertifikate & Domains“):** die Tabelle sammelt jede Zeile mit Ablaufdatum
aus (a) `details.cert` von HTTP-Checks und (b) `probe`-Checks, deren Felder `not_after` tragen (heute die Fühler `tls`
und `certfile`). Ein RDAP-Fühler aus R-1224, der dieselben Feldnamen (`not_after`, `days_left`) nutzt, erscheint ohne
Umbau; eine Zeile nennt dann „Domain“ statt „Zertifikat“ nach dem Fühler.

**Schwellen für die Anzeige (Konzept §5):** Laufzeit L = `not_after − not_before`; „läuft bald ab“ unter 25 % von L,
„kritisch“ unter 10 % von L, mindestens 12 h. Ohne `not_before` (Fühler-Zeilen) zählt der Status des Checks selbst.
Die Einstufung ist Anzeige, kein Alarm (Nicht-Ziele).

**Desktop-Warnung (Totmann, Entscheidung 9c):** ein schlanker Puls-Store fragt alle 60 s `GET /status/summary`, solange
eine Sitzung besteht (nicht nur auf der Monitoring-Seite). Grenze = max(10 min, 2 × `min_interval_s`). Liegt
`last_result_at` weiter zurück, oder antwortet das Monitoring länger als die Grenze nicht, zeigt die Statusleiste
„Monitoring seit X min ohne Ergebnis“ (Warnton, Klick öffnet die Monitoring-Seite), die Monitoring-Seite dazu einen
Hinweis. Ohne aktive Checks keine Warnung.

**Zugangsdaten hinterlegen (Entscheidung 3):** ein neues Tauri-Kommando öffnet das eingebettete Terminal wie
`terminal_open_ssh`, aber mit einer festen Fern-Aktion, die Rust baut: `sudo adminhelper-agent monitor credential set
<ref>` (mit `-t`). Der `ref` wird in Rust gegen dasselbe Muster geprüft wie im Agent (`credentials.ValidRef`, #438:
`^[A-Za-z0-9][A-Za-z0-9_.:@-]*(/[A-Za-z0-9][A-Za-z0-9_.:@-]*)*$`, keine Shell-Zeichen); die UI reicht nur Verbindung und
`ref`, nie einen Befehlstext. Ziel: Linux-Hosts (Agent-Fakten `os`); für andere Ziele und Server ohne SSH-Verbindung
zeigt der Dialog den Befehl zum Kopieren. Der Server erfährt danach nur „hinterlegt“ (Report-Block `credentials`).

## Externe Integrationen

- **Tauri v2 Commands und Capabilities:** jedes neue Kommando braucht seinen Eintrag in `build.rs` (`COMMANDS`) und
  `allow-<command>` in der Capability des aufrufenden Fensters (`capabilities/default.json`); Primärquelle
  <https://v2.tauri.app/security/capabilities/> und <https://v2.tauri.app/develop/calling-rust/> vor T9 nachlesen.
- **httpx** (`network_stream`-Erweiterung, <https://www.python-httpx.org/advanced/extensions/>) und Python `ssl`
  (`SSLSocket.getpeercert`, <https://docs.python.org/3/library/ssl.html>) vor T2.
- **OpenSSH** `-t` (Pseudo-Terminal für die Passwortabfrage von `sudo` und die Eingabe ohne Echo), `ssh(1)`.
- VictoriaMetrics: nur bestehende Abfragen (`avg_over_time`, `max_over_time`, `sum_over_time`) über den vorhandenen
  Client; keine neue Schnittstelle.

## Trade-offs & Alternativen

- **MonServerDashboard umbauen (gewählt) statt eine neue Seite daneben:** Einbindung und Tests bleiben; die heutigen
  `Sec*`-Komponenten wandern unverändert in die Karten System, Dienste, Docker, Backups. Eine zweite Seite hieße zwei
  Ansichten pflegen, bis die alte fällt.
- **Unterdrückungsgrund in der Status-Antwort (gewählt) statt im Desktop nachrechnen:** der Desktop kennt die
  Rangfolge der Host-Signale (Host Ping vor Heartbeat) nicht und soll sie nicht doppeln.
- **Zertifikat im HTTP-Check nur als Detail (gewählt) statt gleich mit Schwelle:** eine Schwelle würde bestehende
  HTTP-Checks ohne Zutun der Admins warnen lassen (sichtbares Verhalten); der zentrale `tls`-Fühler (R-1224) bringt die
  Regel samt Katalog-Schwellen.
- **Totmann im Desktop über `/status/summary` (gewählt) statt einer eigenen Health-Route:** die Summary ist schon eine
  billige Aggregat-Abfrage und vom Desktop erreichbar; `/health` des Monitorings sagt nur „Prozess lebt“, nicht „der
  Scheduler liefert“.
- **Terminal mit fester Fern-Aktion (gewählt) statt Geheimnis im Desktop-Dialog und `ssh … | agent`:** so geht das
  Geheimnis nie durch Webview, IPC oder Logs, und `sudo` fragt im Terminal wie gewohnt. Ein freies „Befehl im Terminal
  ausführen“ wäre ein allgemeines Fern-Ausführungs-Kommando der Webview; die feste Aktion mit geprüftem `ref` ist es
  nicht.

## Risiken & Rollback

- **Datenvertrag aus #438 ändert sich noch:** Bau erst nach dem Merge, dann `origin/main` in den Worktree; Typen in T3
  gegen die gemergten Schemas (`CatalogOut`, `DiscoveryOut`, `FindingOut`).
- **Status-Route wird teurer:** `muted_reason` je Check gebündelt (zwei Abfragen je Antwort, nicht je Check); T1 testet
  die Abfragezahl.
- **Neues Tauri-Kommando mit Fern-Aktion:** Risiko Befehlseinschleusung über `ref` oder Verbindungsfelder; `ref` gegen
  das Agent-Muster, die Verbindung über `validate_connection_input` wie `ssh_spawn`; `security` prüft T9 und T10
  (Risikopfad `lib/bridge/types.ts`, `lib/api/types.ts`; `commands.rs` und die Capability tragen Fern-Ausführung).
- **Statusleisten-Warnung zu laut:** Grenze mindestens 10 min und doppeltes Intervall; ohne Checks nie.
- **Rollback:** Revert des Merge-Commits; keine Migration, die API-Felder sind additiv.

## Doku-Impact

`docs/admin/monitoring.html` + `docs/en/admin/monitoring.html` (Server-Seite mit Karten, Neu gefunden, Querschnitt,
Kosten, Totmann-Warnung, Zugangsdaten hinterlegen, Unterdrückungsgrund), `docs/developer/monitoring.html` +
`docs/en/developer/monitoring.html` (Status-Felder `muted_reason`, `last_result_at`, `min_interval_s`, Route `costs`,
`details.cert`, neues Tauri-Kommando), `changelog.d/arch-monitoring-ui.md`; gebündelt in T12.

## Screenshots

T11 legt die Journey der Server-Seite als Live-Spec an, die an jedem Schritt einen Screenshot nach
`.ah-out/screenshots/` schreibt (heller und dunkler Modus). Vor dem Merge läuft sie auf der warmen Desktop-VM; die
Bilder gehen an Kevin, bevor gemergt wird.

## Offene Fragen

1. **Querschnitt „Geräte“:** ohne Datenquelle bis zur UniFi-Welle (Entscheidung 9a: Geräte als Liste in der
   Modulkarte). Entschieden (Kevin 2026-11-10): der Reiter kommt mit der UniFi-Welle (R-1244), nicht leer in diesem
   Zug.
