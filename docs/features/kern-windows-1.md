<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-windows-1 — Windows-Agent: frpc-Tunnel, Installation als Update, Dienst-Monitoring

Zug: R-1576, R-0577, R-1545, R-0708, R-1577, R-1583.

## Problem / Motivation

- **R-1545 / R-0708:** Auf Windows schreibt der Agent die `frpc.toml`, startet aber kein frpc: die Plattform-Hooks in
  `apps/agent/internal/frpc/platform_windows.go` warnen und melden Erfolg (`enableFrpcService`, `restartFrpc`), die
  übrigen sind leer. `Sync` schreibt danach `.started-hash` und loggt „frpc enabled and started“. Folge: Tunnel zu
  Windows-Hosts sind tot (RDP über STCP scheitert, Kevin 2026-11-17), obwohl Agent und Server Erfolg melden. Der
  Handweg ist belegt: frpc 0.72.0 als SYSTEM mit der vom Agent geschriebenen `frpc.toml` trägt RDP extern und
  eingebettet.
- **R-1576:** `service install` (`internal/service/service_windows.go`) legt `%ProgramFiles%\AdminHelper` mit
  `MkdirAll` an und übernimmt die Rechte des Elternordners ungeprüft. Der Ordner soll feste Rechte bekommen, bevor dort
  ein zweites Programm liegt, das als SYSTEM läuft.
- **R-0577:** `Sync` (`internal/frpc/sync.go`) liest seine Konfiguration, bevor es das Datenverzeichnis einrichtet; die
  Reihenfolge soll umgekehrt werden, bevor frpc unter Windows läuft.
- **R-1577:** Ein zweites `service install` scheitert an `sc create` (Dienst existiert); ein Update heißt heute
  `uninstall` + `install` von Hand. Es gibt kein Aufräumen von Programm- und Datenordner.
- **R-1583:** Der Windows-Collector kennt den Starttyp der Dienste nicht (`scquery.go`: `enabled_state` immer
  `unknown`, `enabled_inactive` immer leer), und `system_state` fehlt auf Windows ganz (`system_other.go`), also auch
  die Zeitsynchronisation. Damit ist der Auto-Modus der Dienst-Überwachung auf Windows wertlos.

## Ziel & Nicht-Ziele

Ziel:
1. Der Agent-Dienst startet und überwacht frpc als Kindprozess: Start, wenn eine `frpc.toml` mit Tunneln vorliegt;
   Neustart bei geänderter Konfiguration oder wenn frpc endet; Stopp ohne Tunnel. Kein zweiter Windows-Dienst.
2. `frpc.exe` kommt als Release-Asset neben dem Agent, in `SHA256SUMS` (minisign-signiert); der Agent prüft vor jedem
   Start den im Agent gepinnten SHA-256. `service install` legt `frpc.exe` aus dem Ordner des Agent-Binarys mit ab.
3. Der Programmordner bekommt beim Install feste Rechte (`config.EnsureSecureDir`, wie der Datenordner); `Sync` richtet
   das Datenverzeichnis ein, bevor es liest.
4. `service install` ist idempotent: vorhandener Dienst → stoppen, Dateien tauschen, Konfiguration nachziehen,
   starten. `service uninstall --purge` entfernt zusätzlich Programm- und Datenordner.
5. Windows-Dienste melden ihren Starttyp (Registry `Start`, `DelayedAutostart`, Trigger-Start), gestoppte
   Auto-Start-Dienste erscheinen in `enabled_inactive` wie unter Linux; `system_state` meldet auf Windows
   `time_synchronized` aus `w32tm`.

Nicht-Ziele (YAGNI): kein Download von frpc aus dem Agent heraus; kein MSI; keine Änderung am Server, an FRP-Config
oder Wire-Format; keine Parität weiterer `system_state`-Felder (nur die Zeitsynchronisation); Defender-Ausnahmen nur
als Doku-Hinweis.

## Betroffene Komponenten & Dateien

- **Agent** (`apps/agent`): `internal/frpc/platform_windows.go` (Hooks auf den Supervisor), neu
  `internal/frpc/supervisor_windows.go` + Test (Kindprozess, Job-Objekt mit `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`,
  Hash-Prüfung, Neustart mit Backoff), `internal/frpc/sync.go` (Reihenfolge), `cmd/adminhelper-agent/run_windows.go`
  (Supervisor im Dienst), `cmd/adminhelper-agent/main.go` (`uninstall --purge`), `internal/service/service_windows.go`
  + Test, `internal/monitor/scquery.go`, `services_windows.go`, `system_other.go` → neu `system_windows.go` + Tests.
- **Release/CI:** `.github/workflows/release.yml` (frpc.exe 0.72.0 aus dem gepinnten Archiv als Asset
  `frpc-windows-x86_64.exe`), `.github/workflows/ci.yml` (Pin-Gleichstand Go-Konstante ↔ Workflows). Der PR ändert
  Workflows: **Kevin merged**.
- **Doku:** `docs/admin/agent-deployment.html` + EN, `changelog.d/kern-windows-1.md`.

## Datenmodell / API / Migrationen

Keine Server-API, keine Migration. Agent-Payload: `systemd.all_services[].enabled_state` auf Windows `enabled` |
`disabled` | `manual` statt `unknown`; `enabled_inactive` gefüllt; neu `system_state.time_synchronized` auf Windows
(gleiche Felder wie Linux, der Monitoring-Dienst kennt sie). Der Agent pinnt den SHA-256 der entpackten `frpc.exe`
als Go-Konstante; `FRP_SHA256_WINDOWS_AMD64` in den Workflows pinnt das ZIP. Der Release-Job prüft beide.

## Externe Integrationen

- Windows Job Objects (`CreateJobObject`, `SetInformationJobObject` mit `JOBOBJECT_EXTENDED_LIMIT_INFORMATION`,
  `AssignProcessToJobObject`): https://learn.microsoft.com/windows/win32/procthread/job-objects
- Dienst-Registry `HKLM\SYSTEM\CurrentControlSet\Services\<name>` (`Start`, `DelayedAutostart`, Unterschlüssel
  `TriggerInfo`): https://learn.microsoft.com/windows-hardware/drivers/install/hklm-system-currentcontrolset-services-registry-tree
- `w32tm /query /status`: https://learn.microsoft.com/windows-server/networking/windows-time-service/windows-time-service-tools-and-settings
  (Ausgabe lokalisiert: nicht verifiziert für deutsche Windows-Versionen; unlesbar → Feld fehlt mit Warnung, wie
  `timedatectl` unter Linux).
- frpc 0.72.0 `frpc -c <toml>`, `frpc reload -c <toml>` (Admin-API, wie Linux).

## Trade-offs & Alternativen

- Kindprozess statt zweitem Dienst (Empfehlung der Roadmap-Notiz, Kevin angenommen): ein Install, ein Dienst, frpc
  stirbt mit dem Agent (Job-Objekt). Preis: ein Agent-Neustart reißt den Tunnel kurz ab.
- frpc.exe als Release-Asset statt Download: kein Netzzugriff zu GitHub vom Host, Prüfsumme signiert; Preis: Workflow-
  Änderung (Kevin merged) und ein zweites Asset.
- Starttyp aus der Registry statt `sc qc` je Dienst: ein Durchlauf statt ~300 Prozessstarts (Monitoring kostet keine
  Dienst-Leistung). Trigger-Start-Dienste zählen nicht als `enabled`, sonst meldet jeder ruhende Trigger-Dienst einen
  Fehler.

## Risiken & Rollback

- Neues Rauschen durch `enabled_inactive` auf Windows (Auto-Start-Dienste, die regulär enden): Trigger-Start
  ausgenommen; Rest in der Dienst-Regel des Monitorings ausnehmbar.
- Supervisor-Fehler darf den Agent nicht stoppen: Fehler gehen in Log und Sync-Ergebnis, Backoff verhindert
  Neustart-Schleifen.
- Rollback: Revert; ein alter Agent ignoriert `frpc.exe` im Programmordner.
- Risikopfade: `service_windows.go` (Install, Rechte), `sync.go` und frpc-Start, `release.yml` → `security` je Task.
- Heavy `windows`: die Windows-Tests laufen im CI-Job `agent-windows` (`go test ./...` auf `windows-latest`); der Pool hat
  keine Windows-Vorlage. Echter RDP-Tunnel bleibt die Probe vor dem Release (R-0541).

## Doku-Impact

`docs/admin/agent-deployment.html` + EN: Windows-Abschnitt (frpc.exe neben dem Agent, Update mit demselben Befehl,
`uninstall --purge`, Defender-Hinweis); `changelog.d/kern-windows-1.md`.

## Offene Fragen

- **Dienstnamen klein normalisieren (Teil von R-1583):** Ein Kleinschreiben der `unit`-Namen im Agent ändert das
  gespeicherte Dienst-Inventar und trifft Regeln, die heute `W32Time` schreiben. Empfehlung: Namen im Agent
  unverändert lassen; der Monitoring-Dienst vergleicht auf Windows-Hosts ohne Groß-/Kleinschreibung (R-0436 mit Beweis
  neu aufnehmen, Kern-1-Bereich). Task T7 steht bis zur Antwort auf `[?]`.
