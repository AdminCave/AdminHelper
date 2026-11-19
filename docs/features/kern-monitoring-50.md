# kern-monitoring-50 — Dienst-Details Windows/FreeBSD: Fehlerzeilen und „Mehr Log“

Roadmap: R-1391 (FEAT). Kevin 2026-11-19: Windows Stufe 2 an gestopptem Auto-Start-Dienst mit Exit-Code (Stufe-1-Grund),
Zeilen aus System-/Application-Log des Dienstes; Stufe 3 über SSH aus dem Ereignisprotokoll; FreeBSD nur Stufe 3
(grep im syslog).

## Problem / Motivation
arch-monitoring-ui-3 (R-1226) und kern-monitoring-48 (R-1413) bauen die Stufen 2 und 3 der Dienst-Details nur für
Linux:
- **Stufe 2:** höchstens 10 geschwärzte Zeilen je Ausfall, vom Agent gesendet.
- **Stufe 3:** „Mehr Log“ öffnet `journalctl -u <unit> -n 200` über die SSH-Verbindung des Admins.

Windows und FreeBSD zeigen nur Stufe 1, also Zustand und Grund. Ein gestoppter Auto-Start-Dienst mit Exit-Code
unter Windows bleibt ohne Zeilen. „Mehr Log“ blendet die Liste unter Windows und FreeBSD aus
(`ServiceList.svelte`, `hasJournal` verlangt `.service`).

## Ziel & Nicht-Ziele
- **Windows Stufe 2:**
  - **Welche Dienste:** jeder gestoppte `enabled`-Dienst mit `exit` (Stufe-1-Grund aus `scquery.go`).
  - **Wann:** einmal je Ausfall; Schlüssel ist Dienst + `since` aus den SCM-Crash-Ereignissen wie unter Linux.
  - **Zeilen:** die letzten 10 Ereignisse des Dienstes aus den letzten 24 h, älteste zuerst, geschwärzt und gekürzt
    mit `cleanLogLine`:
    - System-Log: Ereignisse des Service Control Manager, deren `param1` Dienst- oder Anzeigename ist.
    - Application-Log: Ereignisse, deren Provider der Dienstname ist.
  - **Ohne Fremdwerte im Aufruf:** zwei feste `wevtutil`-Aufrufe je Lauf (`/f:RenderedXml`, Allowlist). Den Dienst
    wählt der Agent beim Lesen aus; kein Dienstname gelangt in den Aufruf.
  - **Rahmen wie unter Linux:** gleiches Plan-Feld `service_logs`, gleiches Last-Tor (Sammler `service_logs`),
    höchstens 20 Dienste je Bericht.
- **Welche Dienste Zeilen behalten:** Das Monitoring speichert und behält Zeilen für die Dienste der neuen Liste
  `log_units` im Dienste-Block. Fehlt die Liste (Linux, alter Agent), gilt wie heute `failed`.
- **Stufe 3 Windows:** „Mehr Log“ öffnet über SSH die letzten 200 Ereignisse des Dienstes aus System- und
  Application-Log (24 h). Das Skript ist fest und läuft als `powershell -NoProfile -NonInteractive -EncodedCommand
  <Base64>`:
  - Der Aufruf liest sich in cmd und in PowerShell als Login-Shell gleich: Base64 enthält kein Zeichen, das eine der
    beiden deutet.
  - Der Dienstname steht nur in der Windows-Dienstklasse (`[A-Za-z0-9._$-]`) und in einfachen Anführungszeichen im
    Skript.
  - `wevtutil` mit einer XPath-Abfrage ließe sich nicht für beide Shells gleich quoten. `$` würde in PowerShell
    expandieren, `'` würde PowerShell entfernen.
- **Stufe 3 FreeBSD:** „Mehr Log“ öffnet `grep -h -e '<dienst>' /var/log/messages | tail -n 200`. Der Name steht nur
  in der rc-Klasse (`[A-Za-z0-9_]`).
- **Nicht-Ziele:**
  - Kein neuer `failed`-Begriff unter Windows oder FreeBSD (Kevin 2026-11-13); `log_units` steuert nur die Zeilen.
  - Keine Stufe 2 für FreeBSD.
  - Kein neuer Alarm.
  - OPNsense nur, soweit es den FreeBSD-Agent nutzt; keine eigene Logquelle (clog).

## Betroffene Komponenten & Dateien
- **agent:**
  - `internal/monitor/servicelogs_windows.go` (neu): die zwei `wevtutil`-Aufrufe je Lauf.
  - `internal/monitor/winevents.go` (neu, ohne Build-Tag) und `winevents_test.go`: Parser für RenderedXml, Auswahl
    je Dienst.
  - `servicelogs_other.go`: Build-Tag `!linux && !windows`.
  - `report.go`: Kandidaten je Plattform, `log_units`.
  - `scquery.go`: `since` je Dienst schon da.
  - `internal/allowlist/allowlist.go` und `allowlist_test.go`: zwei neue feste `wevtutil`-Aufrufe.
- **monitoring:** `app/service_inventory.py` (`log_units`), `tests/test_service_inventory.py`.
- **desktop-rs:**
  - `src-tauri/src/connection/ssh.rs`: argv je Plattform, journalctl / Ereignisprotokoll / syslog.
  - `src-tauri/src/commands.rs` (`terminal_open_ssh_journal` und `ssh_journal_spawn` mit Plattform) samt Tests.
- **desktop-ui:**
  - `components/monitoring/section/ServiceList.svelte` und `.test.ts`: Plattform der Servers, „Mehr Log“ je
    Plattform.
  - `SecServices.svelte`.
  - `lib/bridge/index.ts`, `lib/stores/connectFlow.ts`.
  - i18n, falls ein Text sich ändert.
- **Doku:** `docs/admin/monitoring.html` DE+EN, `changelog.d/kern-monitoring-50.md`.

## Datenmodell / API / Migrationen
- **Keine Migration, keine neue Route.**
- **Agent → Monitoring:**
  - Der Dienste-Block (`systemd`) bekommt optional `log_units: [<dienst>, …]`.
  - `failed_logs` behält seine Form `{dienst: {since, lines}}`.
  - Additiv: Ein altes Monitoring ignoriert das neue Feld und speichert für Windows wie bisher nichts.
- **Tauri-IPC:** `terminal_open_ssh_journal` nimmt neu `platform` (`linux` | `windows` | `freebsd`). Desktop-UI und
  -Backend wechseln im selben PR.

## Externe Integrationen
- **wevtutil** (https://learn.microsoft.com/windows-server/administration/windows-commands/wevtutil):
  `qe <log> /q:<XPath> /c:<n> /rd:true /f:RenderedXml`. RenderedXml trägt `RenderingInfo/Message`.
- **Get-WinEvent** (https://learn.microsoft.com/powershell/module/microsoft.powershell.diagnostics/get-winevent):
  `-FilterHashtable @{LogName=…; StartTime=…}`.
- **powershell.exe -EncodedCommand:** Base64 eines UTF-16LE-Strings
  (https://learn.microsoft.com/powershell/module/microsoft.powershell.core/about/about_powershell_exe).
- **FreeBSD syslogd:** `/var/log/messages` (syslog.conf(5)).

Die Task liest jede Stelle vor der Umsetzung nach. Ob `param1` der SCM-Ereignisse Dienst- oder Anzeigename trägt,
ist nicht dokumentiert. Der Parser prüft beide, wie `scmevents.go`.

## Trade-offs & Alternativen
- **Agent-seitig feste Abfragen plus Filter in Go statt einer XPath-Abfrage je Dienst:** Kein Dienstname gelangt in
  einen Aufruf, und die Allowlist bleibt fest. Dafür liest der Agent bis zu 2×200 Ereignisse je Lauf, aber nur wenn
  ein Kandidat offen ist und das Last-Tor den Lauf zulässt. **Empfehlung.**
- **`log_units` statt `failed ∪ enabled_inactive` auf dem Server:** Linux hat auch `enabled_inactive` mit `exit`.
  Der Vereinigungsweg würde dort Zeilen nach `reset-failed` behalten, eine Verhaltensänderung. **Empfehlung:
  `log_units`.**

## Risiken & Rollback
- **Kein Windows im Pool:**
  - Parser und Auswahl laufen ohne Build-Tag auf jeder Plattform im Test.
  - Den Windows-Teil prüfen die Windows-CI-Jobs (`go test` als Admin; `Heavy: windows`).
  - Das SSH-Skript ist nur als argv getestet. Die echte Prüfung auf Windows gehört in Kevins R-0541-Durchgang; der PR
    nennt das.
- **Last:** Die beiden `wevtutil`-Aufrufe laufen nur, wenn ein Kandidat ohne gesendete Zeilen offen ist, und unter dem
  Last-Tor. `/c:200` begrenzt.
- **Rollback:** Den PR revertieren. Ohne `log_units` gilt wieder `failed`.

## Doku-Impact
`docs/admin/monitoring.html` (DE+EN), Abschnitt Dienst-Details: Fehlerzeilen und „Mehr Log“ je Plattform; dazu
`changelog.d/kern-monitoring-50.md`.

## Offene Fragen
Keine. Kevin hat 2026-11-19 entschieden. Die Shell-Form von Stufe 3 unter Windows (EncodedCommand statt
`wevtutil`-Text) ist eine Implementierungswahl mit derselben Datenquelle.
