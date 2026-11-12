<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-ui-3 — Dienste-Details: Inventar, Gründe, Fehlerzeilen, „Mehr Log“ (R-1226)

Stand `origin/main@0645ec064`. Roadmap R-1226 (FEAT, Kevin 2026-11-09 diktiert, Monitoring-Konzept P0b und §3.9).

## Problem / Motivation

Der Agent schickt heute das volle Dienste-Inventar (`systemd.all_services`, gedrosselt), der Monitoring-Dienst wertet
es im Check `service_process` aus und verwirft es (Docstring von `ServiceProcessChecker._evaluate_auto`,
`apps/monitoring/app/checkers/agent.py:711`). Der Desktop zeigt nur Zahlen und die auffälligen Dienste
(`SecServices.svelte`). Ein Admin sieht nicht, welche Dienste laufen, seit wann, wie oft sie neu gestartet sind und
wie viel RAM sie belegen. Fällt ein Dienst aus, steht in der Alarm-Mail nur sein Name, nicht der Grund.

## Ziel & Nicht-Ziele

**Ziel** (R-1226):
1. **Inventar speichern** statt verwerfen; im Desktop als Liste mit Filter und Suche: Zustand, seit wann, Neustarts,
   RAM, Grund.
2. **Logs Stufe 1 (immer):** strukturierte Fakten.
   - Linux: `Result`, Exit-Code oder Signal, seit wann, `NRestarts` aus systemd.
   - Windows: Exit-Codes aus `sc query` und die SCM-Ereignisse 7031/7034.
   - Der Grund steht im Check-Text und damit in Mail und Webhook.
3. **Logs Stufe 2 (bei einem Ausfall):** höchstens 10 Zeilen der Unit, je 300 Zeichen, einmal je Ausfall.
   - Vor dem Senden geschwärzt: URLs mit `user:pass@`, `password=`/`token=`/`secret=`/`key=`, `Authorization:`,
     lange Base64- und Hex-Ketten.
   - Gespeichert nur am Vorfall, nicht im Verlauf.
   - Sichtbar nur im Desktop, nie in Mail oder Webhook.
   - Standardmäßig an, je Server abschaltbar.
4. **Logs Stufe 3 (auf Knopfdruck):** „Mehr Log“ öffnet über die vorhandene SSH-Verbindung des Desktops
   `journalctl -u <unit> -n 200`. Nichts wird gespeichert, es gelten die Rechte des Admins.

**Nicht-Ziele:**
- Stufe 2 und 3 für Windows und FreeBSD. Folgezeile `neu` am Gate: Windows-Ereignisprotokoll über SSH, FreeBSD
  ohne journald.
- FreeBSD Stufe 1: rc(8) führt weder Ergebnis noch Neustarts. Die Liste zeigt dort nur den Zustand.
- Kein neuer „failed“-Begriff unter Windows. Ein gestoppter Dienst mit Exit-Code bleibt `inactive` wie heute. Der
  Grund steht nur in der Liste und im Text des Listen-Modus. Kein neuer Alarm.
- Keine Liste im Web-Frontend.
- Kein Verlauf der Dienstzustände.

## Betroffene Komponenten & Dateien

**Agent** (`apps/agent`):
- `internal/monitor/services_linux.go`: `collectServiceHealth` :18, `resolveAliases` :86, `runSystemctl` :168,
  `parseShowBlocks` :209.
- `internal/monitor/services.go`: `ServiceEntry`.
- `internal/monitor/inventory.go`: `inventoryHash` :35, `throttleInventory` :87.
- `internal/monitor/scquery.go` und `services_windows.go`.
- `internal/monitor/report.go`: Block `services` :80–92.
- `internal/monitor/plan.go`: `parsePlan` :103.
- `internal/probe/probe.go`: `Plan` :28.
- `internal/allowlist/allowlist.go`: `commands`, `systemctl` :165, `sc` :182.
- Neu: `servicelogs.go` (Schwärzung, ohne Build-Tag) und `servicelogs_linux.go` (journalctl).

**Monitoring** (`apps/monitoring`):
- `app/models.py` und eine neue Alembic-Revision nach `b8d0f2a4c6e8`.
- `app/server_cleanup.py`: `cleanup_server` :37.
- `app/routers/agent.py`: `agent_report` :82, neben `_store_host_facts` :194 und `_store_discovery` :203.
- `app/checkers/agent.py`: `ServiceProcessChecker` :593, `_evaluate_auto` :711, `_evaluate_list` :813.
- `app/routers/checks.py`: Muster `/status/server/{server_id}/costs` :884.
- `app/schemas.py`.
- `app/module_plan.py`: `build_plan`, `PLAN_VERSION` :24.
- `tests/openapi.snapshot.json`.

**Server:** unverändert. Die neuen Routen liegen unter dem Präfix `status`, den
`apps/server/app/modules/monitoring_proxy/router.py:78` (`_ALLOWED_PATH_PREFIXES`) schon durchlässt, nur für Admins.

**Desktop-UI** (`apps/desktop/ui/src`):
- `components/monitoring/section/SecServices.svelte`.
- `lib/api/monitoring.ts` und `lib/api/types.ts`.
- `lib/bridge/index.ts`.
- `lib/stores/connectFlow.ts` und `lib/stores/terminals.ts`, nach dem Muster `connectCredential` aus R-1225.
- `lib/i18n/dictionaries.ts`.

**Desktop-Rust** (`apps/desktop/src-tauri`):
- `src/connection/ssh.rs`: Muster `build_credential_args` :82.
- `src/commands.rs`: Muster `ssh_credential_spawn` :724 und `terminal_open_ssh_credential` :827.
- `src/main.rs`, `build.rs`, `capabilities/default.json`.

**E2E:** `apps/desktop/e2e/test/specs/` (neue Live-Spec).

## Datenmodell / API / Migrationen

### Wire Agent → Monitoring (Bericht, `report_version` bleibt 4, nur hinzugefügte Schlüssel)

`systemd.all_services[]` bekommt optionale Felder; alle Werte bleiben Strings (`ServiceEntry = map[string]string`):

| Feld | Linux | Windows | FreeBSD |
|---|---|---|---|
| `sub_state` | `SubState` | – | – |
| `since` | `StateChangeTimestampMonotonic` + Boot-Zeit, ISO-UTC | Zeit des letzten 7031/7034 | – |
| `restarts` | `NRestarts` (ab systemd 235) | – | – |
| `result` | `Result` (`exit-code`, `signal`, `core-dump`, `oom-kill`, `timeout`, `start-limit-hit` …) | `crashed` bei 7031/7034 | – |
| `exit` | `status=<n>` oder `signal=SIG…` aus `ExecMainCode`/`ExecMainStatus` | `win32=<n>`/`service=<n>` aus `sc query` | – |
| `memory_bytes` | `MemoryCurrent`, ohne `[not set]` und 2^64−1 | – | – |

- `memory_bytes` bleibt aus `inventoryHash`. Sonst ginge das volle Inventar mit jedem Bericht mit statt stündlich
  oder bei Änderung. RAM ist damit bis zu einer Stunde alt; die Liste zeigt den Stand.
- Die übrigen Felder gehen in den Hash ein.
- Neu `systemd.failed_details[]` (jeder Bericht, klein): `{unit, result, exit, since, restarts}` je fehlgeschlagener
  Unit. Grundlage des Grundes im Check-Text, auch wenn `all_services` gedrosselt fehlt.
- Neu `systemd.failed_logs` (nur Linux, nur bei Schalter an, einmal je Ausfall): `{<unit>: {since, lines: [...]}}`.
  Der Checker liest diesen Schlüssel nie.
- Alte Server ignorieren die neuen Schlüssel. Neue Server lesen alte Berichte ohne sie: keine Gründe, keine Zeilen.

### Wire Monitoring → Agent (Plan)

- `build_plan` bekommt `"service_logs": true|false`. `PLAN_VERSION` bleibt 1: `parsePlan` decodiert mit
  `json.Unmarshal`, unbekannte Felder stören alte Agenten nicht.
- Fehlt das Feld (alter Server), sendet der Agent keine Zeilen.

### Tabellen (eine additive Alembic-Revision, Downgrade löscht beide)

- `monitor_service_inventory`: `server_id` PK, `reported_at` (naive UTC), `services` (JSON-Text, höchstens
  `_MAX_REPORT_ENTRIES` = 500 Einträge, Felder gekürzt), `log_lines` (Boolean, `server_default` true) als Schalter
  je Server.
- `monitor_service_logs`: PK (`server_id`, `unit`), `since`, `collected_at`, `lines` (JSON-Text, ≤ 10 × 300 Zeichen).
  - Eine Zeile lebt, solange die Unit in `systemd.failed` steht.
  - Sie wird gelöscht bei Erholung, wenn der Schalter aus ist und mit dem Server (`cleanup_server`).
  - Ein Bericht mit `systemd.error` löscht nichts.
- Die Zeilen gehen nie in `monitor_states.details`, die History oder `MonitorAlertLog`.

### Admin-API (über den Server-Proxy, Präfix `status`)

- `GET /status/server/{server_id}/services`: `{reported_at, log_lines, services: [...], logs: {<unit>: {since,
  collected_at, lines}}}`; 404, wenn der Server unbekannt ist.
- `PUT /status/server/{server_id}/services/options`: `{log_lines: bool}` (strict). Aus löscht die gespeicherten
  Zeilen sofort; der Plan trägt die Änderung beim nächsten Abruf.

### Desktop

- Tauri-Befehl `terminal_open_ssh_journal(connection, unit, cols, rows, output)`, nur im Hauptfenster.
  - Feste Aktion `journalctl --no-pager --unit='<unit>' --lines=200` über `base_args`, nach dem Muster von
    `build_credential_args`.
  - Die UI übergibt nur den Unit-Namen, nie einen Befehl.
  - Der Name wird gegen die Unit-Klasse geprüft (`[A-Za-z0-9:_.@\-]`, `\` für systemd-Escapes, nicht mit `-`
    beginnend) und für die entfernte Shell in einfache Anführungszeichen gesetzt.
- Kein neuer Desktop-Typ in den Web-Typen. `sync-from-web.sh --check` bleibt grün.

## Externe Integrationen

- **systemd** (`org.freedesktop.systemd1(5)`, `systemctl(1)`):
  - Lokal auf systemd 257 belegt: `Result`, `ExecMainCode`, `ExecMainStatus`, `NRestarts`,
    `StateChangeTimestampMonotonic`, `MemoryCurrent` (`[not set]` ohne Accounting).
  - Ältere Versionen lassen unbekannte Eigenschaften weg. Das wird in der Build-Task gegen die offizielle
    Doku nachgelesen.
- **journald** (`journalctl(1)`, `systemd.exec(5)` `SyslogLevel=`):
  - Lokal belegt (systemd 257, transiente Unit): Eine stderr-Zeile des Dienstes trägt `PRIORITY=6`.
  - systemds eigene Zeilen tragen 5 („Main process exited“) und 4 („Failed with result“).
  - `journalctl -p err` lieferte **keine Zeile** (offene Frage 1).
- **Windows SCM**:
  - `sc query` liefert `WIN32_EXIT_CODE` und `SERVICE_EXIT_CODE` schon heute.
  - Ereignisse 7031/7034 über `wevtutil qe System /q:<XPath> /c:<n> /rd:true /f:xml`.
  - Syntax und Ereignis-Layout (Anzeigename statt Dienstname) **nicht verifiziert**; die Build-Task liest sie bei
    Microsoft Learn nach.
- **Tauri:** neuer App-Befehl in `build.rs` und `capabilities/default.json` wie `terminal_open_ssh_credential`.

## Trade-offs & Alternativen

1. **Fakten je Report vs. nur mit dem vollen Inventar.** Ein gebündeltes `systemctl show` über die geladenen Units
   läuft jeden Bericht, eine D-Bus-Abfrage an PID 1 für einige hundert Units. Nur so erkennt der Hash einen Neustart
   zeitnah und `failed_details` trägt den Grund. Ein gescheiterter Batch lässt die Fakten weg, ohne Einzel-Fallback,
   damit nichts mehr kostet (Konzept §3.13). **Empfehlung: je Report.**
2. **RAM im Hash vs. außen.** Im Hash ginge das volle Inventar bei jedem Bericht mit, etwa 500 × 200 Byte alle
   5 Minuten je Server. **Empfehlung: außen**, mit Stand-Anzeige.
3. **Schalter je Server: Spalte in `monitor_service_inventory` vs. eigene Einstellungs-Tabelle vs. Feld im
   `ServiceProcessConfig`.** Die Check-Config gilt je Check (Auto und Liste können beide bestehen) und wäre mehrdeutig.
   Eine allgemeine Einstellungs-Tabelle wäre heute auf Vorrat gebaut. **Empfehlung: Spalte in der Inventar-Tabelle**.
   Sie hat genau einen Wert je Server, und Upsert legt die Zeile auch vor dem ersten Bericht an.
4. **Zeilen bei Erholung löschen vs. bis zum nächsten Ausfall halten.** „Nur am Vorfall, nicht im Verlauf“ (Konzept
   §3.9). **Empfehlung: löschen.** Nach der Erholung hilft Stufe 3.
5. **Doppelte Schwärzung.** Agent und Monitoring schwärzen mit denselben Regeln. Ein alter oder fremder Agent
   bringt sonst ungeschwärzte Zeilen in die DB. Beide Seiten bekommen dieselben Testvektoren.

## Risiken & Rollback

- **Datenschutz Stufe 2:**
  - Geschwärzt wird auf beiden Seiten; die Regeln sind Freigabe-, keine Sperrlogik für Zeilen.
  - Was keine Regel trifft, geht mit. Deshalb sind die Zeilen nur im Desktop sichtbar und je Server abschaltbar.
  - Die Testvektoren decken jedes Muster aus §3.9 ab, dazu Groß-/Kleinschreibung, Anführungszeichen und JSON-Form.
  - Prüfung je Task durch `security` (Agent T3, Monitoring T5).
- **Remote-Befehl im Desktop (T9):**
  - Nur der Unit-Name kommt aus der UI, die entfernte Shell sieht ihn quotiert.
  - Prüfung durch `security`. Kein Pfad auf der Risikoliste, aber ein Remote-Befehl wie R-1225.
- **Last:** ein zusätzlicher `systemctl show`-Batch je Bericht. journalctl nur einmal je Ausfall und nur über das
  indexierte Unit-Feld.
- **Rollback:**
  - Die Migration ist additiv mit Downgrade.
  - Agent und Monitoring bleiben gegenseitig abwärtskompatibel (nur hinzugefügte Schlüssel).
  - Revert des Branches genügt.
- **Überlappung:** `feature/arch-monitoring-ui-2` (R-1227, aktiv) ändert `allowlist.go`, `checkDetails.ts` und
  `checkers/agent.py` in anderen Abschnitten. Nach dessen Merge wird `main` hereingezogen, und die ganzen Suiten
  von Agent, Monitoring und Desktop-UI laufen.

## Doku-Impact

- `docs/admin/monitoring.html` (DE+EN): Dienste-Liste, Stufen 1–3, was in Mail und Webhook steht, Schalter,
  Schwärzung, Speicherdauer, Plattformgrenzen.
- `docs/developer/monitoring.html` (DE+EN): neue Bericht-Schlüssel, Plan-Feld, Tabellen.
- `docs/developer/api-reference.html` (DE+EN): beide Routen.
- `docs/developer/agent.html` (DE+EN): neue Allowlist-Aufrufe.
- `changelog.d/arch-monitoring-ui-3.md`.

## Offene Fragen

1. **Welche Zeilen sendet Stufe 2? (Kevin, blockiert T3)**
   - Das Konzept sagt „journald-Priorität `err` und schlechter“.
   - Belegt: Was ein Dienst auf stderr schreibt (das nginx-Beispiel), hat Priorität 6. `-p err` fand im Test gar
     nichts.
   - **Empfehlung A:** die letzten 10 Zeilen des gescheiterten Laufs jeder Priorität, wie `systemctl status`,
     geschwärzt.
   - B: `-p warning`, das liefert nur systemds eigene Zeilen, die Stufe 1 schon kennt.
   - C: wörtlich `err`, meist leer.
2. **„Sichtbar nur im Desktop“ (Lesart, nicht blockierend).** Die Zeilen liefert eine Admin-API. Das Web zeigt sie
   nicht, Mail und Webhook nie. Eine Durchsetzung „nur der Desktop-Client darf lesen“ ist nicht geplant, sie ginge
   über Server-Proxy oder Gateway. **Empfehlung:** so lassen, Admin-Rechte sind dieselbe Vertrauensstufe wie der
   Desktop.
3. **Stufe 2/3 nur Linux, Windows Stufe 1 ohne neuen Alarm (Scope, nicht blockierend).** **Empfehlung:** so bauen,
   Windows/FreeBSD als Folgezeile `neu`.
