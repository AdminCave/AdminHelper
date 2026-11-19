<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-48 — Fehlerzeilen vom Linux-Agent, SMART ohne Aufwecken

Zug aus R-1413 (FEAT) und R-1569 (BUG). R-1391 (Windows/FreeBSD Stufe 2) fährt nicht mit: es baut auf R-1413 auf und
überlappt `feature/kern-windows-1` (`services_windows.go`), es wandert nach `kern-monitoring-50`.

## Problem / Motivation

- **R-1413:** Stufe 2 der Dienste-Logs (R-1226, `docs/features/arch-monitoring-ui-3.md`) ist auf der Server-Seite
  fertig: der Plan trägt `service_logs`, `service_inventory.py` nimmt `systemd.failed_logs`, schwärzt, speichert und
  der Desktop zeigt die Zeilen. Der Agent sendet sie nur nicht; die Liste bleibt leer.
- **R-1569:** `querySmartDevice` (`apps/agent/internal/monitor/smart.go:143`) ruft `smartctl --all` ohne
  `-n standby`. Eine schlafende HDD läuft damit bei jedem Bericht an, gegen „Monitoring kostet den Host nichts“
  (Kevin 2026-11-09). Kevin 2026-11-19: ohne Testbox-Beleg bauen, er prüft danach an einer echten HDD.

## Ziel & Nicht-Ziele

**Ziel R-1413** (Kevins Antworten 2026-11-13 und 2026-11-19):
- Linux: je Unit aus `systemd.failed` die letzten 10 Journal-Einträge der Unit, jede Priorität, geschwärzt und auf
  300 Zeichen gekürzt, in `systemd.failed_logs` (`{<unit>: {since, lines}}`, älteste zuerst).
- Einmal je Ausfall: Schlüssel Unit + `since` aus `failed_details`, im Report-State gemerkt.
- Nur wenn der Plan `service_logs: true` trägt; fehlt das Feld (alter Server), keine Zeilen.
- Höchstens 20 Units je Bericht (`MAX_LOG_UNITS`); der Rest folgt im nächsten.
- Unter dem Last-Tor (R-1268): ein eigener optionaler Sammler `service_logs`, der unter Last ruht und sich
  selbst drosselt wie `smart` oder `zfs`.

**Ziel R-1569:**
- `smartctl --all` mit `-n standby,3`: eine Platte in STANDBY oder SLEEP wird nicht abgefragt, smartctl endet mit
  Status 3.
- Der Agent meldet sie als `{device, standby: true}`. Das Monitoring behält für sie den letzten gelesenen Stand
  aus den Details des Checks, mit Zeitpunkt.
- Der Desktop zeigt „schläft, letzter Stand von <Zeit>“.

**Nicht-Ziele:**
- Stufe 2 für Windows und FreeBSD (R-1391).
- Eine Sperre auf Zeilen, die keine Regel trifft: die Regeln geben frei, sie sperren nicht (wie arch-monitoring-ui-3).
- `-n standby` für den Scan: `smartctl --scan` öffnet keine Platte.

## Betroffene Komponenten & Dateien

**Agent** (`apps/agent`):
- `internal/monitor/servicelogs.go` (neu, ohne Build-Tag): Schwärzung, gleiche Regeln wie
  `apps/monitoring/app/service_inventory.py` (`_RULES`, `_BASE64_RUN`), Testvektoren
  `apps/monitoring/tests/service_log_redaction.json`.
- `internal/monitor/servicelogs_linux.go` / `servicelogs_other.go` (neu): journalctl-Aufruf bzw. nichts.
- `internal/monitor/report.go`: optionaler Sammler nach dem Last-Tor; `reportstate.go`: gesendete Ausfälle.
- `internal/monitor/monitor.go`: `probeWork` trägt den Schalter; `internal/probe/probe.go`: `Plan.ServiceLogs`.
- `internal/allowlist/allowlist.go`: ein fester journalctl-Aufruf, smartctl mit `-n standby,3`.
- `internal/monitor/smart.go`: Status 3 → Platte schläft.

**Monitoring** (`apps/monitoring`): `app/checkers/smart.py` — `standby`-Platten aus `prev_details`, `read_at` je
gelesener Platte.

**Desktop-UI** (`apps/desktop/ui`): `components/monitoring/section/SecSmart.svelte`, `lib/api/types.ts`
(`MonitorSmartDetails`), i18n.

## Datenmodell / API / Migrationen

- Keine Migration, keine neue Route.
- Agent → Monitoring: `systemd.failed_logs` (Form steht seit arch-monitoring-ui-3); neu `smart[]`-Eintrag
  `{"device": "/dev/sdb", "standby": true}`.
- `smart_health`-Details je Platte: neu `read_at` (ISO-UTC, wann die Werte gelesen wurden) und `standby` (bool).
  Additiv; der Typ ist Desktop-only (`MonitorSmartDetails`, nicht in den Web-Typen).
- Plan: `service_logs` steht schon im Plan (`module_plan.py`), `PLAN_VERSION` bleibt 1.

## Externe Integrationen

- **smartctl(8)** (smartmontools, `-n POWERMODE[,STATUS]`): „exit before performing any checks when the device is
  in a low-power mode … `-n standby,3` to return a unique exit status“; ohne `-d` kann die Typerkennung die Platte
  anlaufen lassen („it may also be necessary to specify the device type with the '-d' option“). Gelesen in der
  Manpage der Dev-Box. Der Agent gibt `-d` mit, wenn der Scan einen Typ nennt, außer `scsi`
  (`smart.go:139`). Ob eine SATA-Platte hinter `-d scsi`-Scan beim Öffnen anläuft: **nicht verifiziert**, Kevins
  HDD-Probe.
- **journalctl(1)**: `--unit=` (Unit-Feld, indexiert), `--lines=10` (die letzten N Einträge), `--output=cat`,
  `--no-pager`, `--quiet`. Wie die Aufrufe des Log-Sensors (`allowlist.go`, `journalHead`).

## Trade-offs & Alternativen

1. **Welche Zeilen:** die letzten 10 Einträge der Unit (`--lines=10`), wie `systemctl status`. Eine Einschränkung
   auf die Invocation-ID des gescheiterten Laufs wäre genauer, braucht aber einen weiteren `systemctl show`-Aufruf
   und eine zweite Allowlist-Form. **Empfehlung: `--lines=10`**: der Ausfall ist das jüngste Ereignis der Unit.
2. **Gesendet merken:** im Report-State (Unit → `since`). Ein Ausfall, der unter Last oder im Drosseltakt nicht
   gelesen wurde, bleibt offen. Schalter aus → die Merkliste wird leer, damit ein wieder eingeschalteter Schalter
   die Zeilen eines laufenden Ausfalls neu schickt (der Server löscht sie beim Ausschalten).
3. **SMART-Stand halten: Agent oder Monitoring.** Das Monitoring hat die Details des Checks schon
   (`evaluate(..., prev_details)`); der Agent bräuchte einen Plattencache im State. **Empfehlung: Monitoring.**
4. **Exit-Status für „schläft“:** 3 (Manpage-Beispiel). Bits 0 und 1 zusammen kommen sonst nicht vor
   (Parse-Fehler endet vor dem Öffnen); `querySmartDevice` verwarf 3 bisher ohnehin. Eine schlafende Platte ohne
   bekannten Stand ist „nicht erhoben“: Kategorie ok, kein `unknown` (Kevins Regel: nicht erhoben = info).

## Risiken & Rollback

- **Datenschutz Stufe 2:** zweite Schwärzung im Agent, dieselben Testvektoren auf beiden Seiten; Zeilen nur über
  die Admin-API, je Server abschaltbar. `security` je Agent-Task.
- **Last:** journalctl nur einmal je Ausfall, über das indexierte Unit-Feld, höchstens 20 Units, unter Last-Tor
  und Selbstdrossel.
- **SMART:** ändert sich das Verhalten einer schlafenden Platte nicht wie erwartet (Typerkennung weckt doch), bleibt
  sie wie heute abgefragt; schlimmer wird nichts. Kevins HDD-Probe danach.
- **Rollback:** Revert des Branches; alle neuen Felder sind additiv.

## Doku-Impact

- `docs/admin/monitoring.html` (DE+EN): Fehlerzeilen kommen vom Linux-Agent (welche, wann); SMART: schlafende
  Platten, „letzter Stand“.
- `docs/developer/agent.html` (DE+EN): Sammler `service_logs`, die neuen Allowlist-Aufrufe, `-n standby,3`.
- `docs/developer/monitoring.html` (DE+EN): `standby`/`read_at` im SMART-Check.
- `changelog.d/kern-monitoring-48.md`.

## Offene Fragen

Keine: Zeilenauswahl (A) und Bauen ohne Testbox-Beleg hat Kevin am 2026-11-19 entschieden.
