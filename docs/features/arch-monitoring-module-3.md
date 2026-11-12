<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Module 3: Rücksicht bei Last (Architektur)

Roadmap R-1268 (FEAT) · Zug `arch-monitoring-module-3` · Kevin 2026-11-10 (angenommen) und 2026-11-12 (Grenzen und
Sichtbarkeit). Stand des Codes: `origin/main@f1d4ca7f2`; alle `datei:zeile` beziehen sich auf diesen Stand.

Aus `arch-monitoring-module-2` verschoben (dort T12/T13, gewartet auf Kevins Antwort). Baut auf der Selbstdrosselung
der optionalen Collector (`apps/agent/internal/monitor/selfmeasure.go`) und deren Auswertung im Monitoring-Dienst
(`apps/monitoring/app/routers/agent.py:146`, `_spared_by_throttle`) auf.

## Problem / Motivation

Der Agent misst heute bei jedem Lauf alles, was ansteht: Docker, Proxmox, ZFS, SMART, die Proben und eine
angeforderte Erkennung. Die Selbstdrosselung bremst nur Collector, die an ihre eigene Zeitgrenze stoßen. Steht der
Host unter Last (CPU-Warteschlange, I/O-Wartezeit, knapper RAM), kostet das Monitoring dem überwachten Dienst
zusätzlich Leistung, genau dann, wenn er sie am meisten braucht. Das Monitoring-Konzept (Kevin 2026-11-09) verlangt:
überwachte Dienste verlieren nie spürbar Leistung; bei Last misst der Agent nur das Nötigste, alles Optionale
setzt aus, die Erkennung wird verschoben.

## Ziel & Nicht-Ziele

**Ziel:** ein Last-Tor im Agenten mit Hysterese und eine Auswertung im Monitoring-Dienst (Kevin 2026-11-12):

- **Eintritt:** in zwei Läufen hintereinander gilt mindestens eines: Last (1 min) je CPU ≥ 2,0 · I/O-Wartezeit
  ≥ 25 % · verfügbarer RAM < 10 %. Der zweite Lauf schont schon.
- **Austritt:** nach drei unauffälligen Läufen hintereinander; der dritte misst wieder alles.
- **Ausgesetzt:** die optionalen Collector (`docker`, `proxmox`, `zfs`, `smart`), die Proben-Phase und eine
  angeforderte Erkennung. Der Kern (`resources`, `system_state`, `services`) läuft immer.
- **Sichtbar:** betroffene Checks behalten ihren letzten Status, die Meldung bekommt „(skipped: load shedding)“
  (Kevins Wortlaut „nicht gemessen: Last-Schonung“; Code-Texte sind englisch); die 45-min-Grenze der
  Selbstdrosselung gilt dafür nicht. Nach 30 min durchgehender Schonung geht der Check `agent_resources` auf
  Warnung „Load shedding since <Zeit> UTC (<n> min)“.

**Nicht-Ziele:**
- Keine eigene UI: die Meldung trägt den Hinweis, die Kosten-Karte zeigt ausgesetzte Collector schon heute als
  gedrosselt (`MonCosts.svelte`). Ein eigener Hinweis in Desktop oder Web wäre eine eigene Roadmap-Zeile.
- Keine einstellbaren Grenzen (YAGNI; feste Werte nach Kevins Wort).
- Kein Einfluss auf das Lauf-Intervall des Agenten und keine Drosselung durch den Server.
- Kein neuer Wert im `resources`-Block: die I/O-Wartezeit steht nur im neuen Block `self.load_shed`.

## Betroffene Komponenten & Dateien

**Agent** (`apps/agent/internal/monitor/`):
- Neu `loadgate.go` (SPDX): das reine Tor. Eingaben: Last je CPU (`load_1m / cpu_count`, nicht in einem Container
  wie bei `agent_resources`, unter Windows ohne Last), I/O-Wartezeit seit dem letzten gespeicherten CPU-Stand,
  verfügbarer RAM (`100 − memory_percent`; gopsutil rechnet unter Linux `Used = Total − Available`). Ein Wert, der
  fehlt, zählt nicht. Zustand `loadShed{Active, Since, Hits, Clean}` im `reportState`.
- `collector.go:64` `collectCPUSince` / `:80` `cpuBusyTimes`: der CPU-Stand trägt zusätzlich die I/O-Wartezeit
  (`cpu.TimesStat.Iowait`); ihr Anteil gilt im selben Fenster wie `cpuPercentSince` (`:91`). Nur Linux misst sie,
  sonst bleibt sie leer.
- `reportstate.go:20` `reportState` (neues Feld `LoadShed`), `:120` `cpuSample` (neues Feld `Iowait`, fehlt in
  alten Zustandsdateien → Kriterium zählt einen Lauf lang nicht).
- `report.go:55` `buildReportWithState`: nach dem Kern das Tor; bei Schonung laufen `m.optional` (`:96`–`:114`),
  die Proben (`:125`–`:144`) und die Erkennung (`:153`) nicht. Proben: `next.Probes`, Bremse, Bindungen und Cursor
  bleiben wie in `prev`, der Report trägt die gespeicherten Ergebnisse; der Block `credentials` geht wie heute mit.
- `selfmeasure.go:26` `collectorStat` bekommt `Reason string \`json:"reason,omitempty"\``; ein durch die Schonung
  ausgesetzter Collector meldet `{factor, throttled: true, reason: "load"}`, seine Drossel bleibt unverändert.
- `monitor.go:228`: nach einem verlorenen Push bleibt auch `LoadShed` aus dem neuen Zustand (wie `Throttle`).

**Monitoring** (`apps/monitoring/`):
- `app/routers/agent.py` (Risikopfad, `security`): `_COLLECTOR_OF_CHECK` (`:48`) um `probe` → `probes`;
  `_spared_by_throttle` (`:146`) schont bei `reason: "load"` ohne die Grenze `_THROTTLE_SPARES_AT_MOST` (`:57`) und
  hängt den Hinweis an die Meldung; Metrik `monitor_agent_load_shed` (0/1) aus `self.load_shed`.
- `app/check_engine.py:392` `_note_skip` wird öffentlich (`note_skip`): es hängt eine Notiz „(skipped: …)“ an die
  gespeicherte Meldung und ändert sonst nichts (Status, `since`, `last_check`, Details bleiben; eine neue Notiz
  ersetzt die alte, `_SKIP_NOTE` `:47`). Genau das braucht die Schonung.
- `app/checkers/agent.py:555` `AgentResourcesChecker.evaluate`: Warnung nach 30 min Schonung über den `_Grader`
  (`:291`), mit eigener Problem-Kennung, damit die Hysterese der übrigen Werte unberührt bleibt.
- Tests: neu `tests/test_agent_load_shed.py` (SPDX); `tests/test_agent_report.py`, `tests/test_agent_report_v4.py`
  laufen mit.

## Datenmodell / API / Migrationen

- **Agent-Zustand** `.report-state.json`: neue Felder `load_shed` (`active`, `since`, `hits`, `clean`) und
  `cpu.iowait`; beide `omitempty`, eine alte Datei liest sich als „keine Schonung“.
- **Report** (additiv, `report_version` bleibt 4): `self.load_shed = {active: bool, since: RFC 3339 UTC (nur
  aktiv), over: [Kriterien über der Grenze in diesem Lauf: "load", "iowait", "memory"], values: {load_per_cpu,
  iowait_percent, mem_available_percent}}` (gemessene Werte, fehlende fehlen). `self.collectors.<name>.reason`
  = `"load"` bei Schonung.
- **Monitoring:** keine Migration, kein neues Schema an der API (`/agent/{id}/report` nimmt `dict`). Der Dienst
  liest den Block beschränkt wie `self.collectors`: nur ein Objekt, `active` nur als `bool`, `since` nur als
  gültige UTC-Zeit, Werte über `agent_number`.
- **Vertrags-Drift:** keine Änderung an Server, Web oder Desktop. Ein älterer Monitoring-Dienst ignoriert Block
  und `reason` (ausgesetzte Collector: heutige 45-min-Regel; Proben: nach `2 × Intervall + 5 min` `unknown`).

## Externe Integrationen

Keine. gopsutil v4.26.10 liefert `Iowait` unter Linux aus `/proc/stat`; unter Windows und FreeBSD gibt es den Wert
nicht (`cpu.TimesStat`), dort zählt das Kriterium nicht.

## Trade-offs & Alternativen

- **Last über 1 min statt 5 min:** reagiert schneller; die Hysterese (zwei Läufe = 10 min) glättet Ausreißer.
  Mit `load_5m` käme die Schonung bei kurzen Spitzen zu spät und bliebe zu lange. Empfehlung und Kevins Wort: 1 min.
- **Hinweis über `note_skip` statt eigenem Feld:** derselbe Mechanismus wie bei ausgesetzten zentralen Checks,
  sichtbar in jeder Ansicht und im Verlauf; die nächste echte Bewertung ersetzt die Meldung. Ein Feld in `details`
  bräuchte UI-Arbeit in Desktop und Web.
- **Gespeicherte Probenergebnisse mitsenden statt weglassen:** ein älterer Monitoring-Dienst bewertet sie wie
  heute (Frische-Grenze), ein neuer schont den Check; weglassen hieße für beide „kein Ergebnis“.
- **Tor im Agenten statt im Server:** nur der Agent sieht die Last im Moment des Laufs.

## Risiken & Rollback

- **Eingefrorene Checks:** ein Agent unter Dauerlast hält seine optionalen Checks auf dem letzten Stand. Gegenmittel:
  die Meldung sagt es, `agent_resources` warnt nach 30 min, der Verlauf zeigt `monitor_agent_load_shed`.
- **Agent bestimmt die Schonung:** ein Agent kann seine Checks dadurch anhalten; das konnte er schon immer (er
  liefert die Daten selbst). Der Hinweis und die Warnung machen es sichtbar. Prüfung durch `security` (T2).
- **Falsche Grenzen:** zu empfindlich schont zu oft, zu träge schützt zu spät. Die Werte sind Kevins Wort; der
  Block `values` liefert die Grundlage, sie später anzupassen.
- **Rollback:** rein additiv. Agent und Dienst einzeln zurücknehmbar; alte Zustandsdateien und Reports bleiben
  gültig.

## Doku-Impact

DE+EN: `docs/developer/agent.html` (Abschnitt „Probes, Plan und Selbstdrosselung“: Last-Tor, Zustand, `self.load_shed`),
`docs/developer/monitoring.html` (Push-Payload `self.load_shed`, `reason`, Schonung ohne 45-min-Grenze, Metrik),
`docs/admin/monitoring.html` (Monitoring-Kosten bzw. Sicherheitsmodell: was bei Last aussetzt und wie es sich
zeigt); `changelog.d/arch-monitoring-module-3.md`.

## Entscheidungen

- **Kevin 2026-11-09 (Monitoring-Konzept):** überwachte Dienste verlieren nie spürbar Leistung; bei Last nur das
  Nötigste, alles Optionale aus, Erkennung verschoben.
- **Kevin 2026-11-12:** Grenzen 2,0 / 25 % / 10 % in zwei Läufen, Ende nach drei unauffälligen; letzter Status mit
  Hinweis, ohne 45-min-Grenze; Warnung an `agent_resources` nach 30 min.
- **Session 2026-11-12:** Hinweis über `note_skip` („skipped: load shedding“); Proben-Checks schont dieselbe Regel
  (`probe` → `probes`); keine UI-Änderung; I/O-Wartezeit nur unter Linux.

## Offene Fragen

Keine.
