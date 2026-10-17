<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring meldet Ausfälle von Docker, ZFS und SMART und bewertet Container nach ihrem Ende — Spec

Roadmap: R-0419 (BUG). Entscheidungen: Kevin, 2026-10-16 (Monitoring-Untersuchung, Fragen per Rückfrage beantwortet).
Stand: `origin/main@af4498a7`. Ledger: `tasks/monitoring-silent-outages.md`.
**Hängt ab von R-0417** (`feature/monitoring-docker-parse`): der Parser für `docker ps` ab Docker 28.2/29. Dieses
Vorhaben baut auf dem reparierten `parseDockerPS` auf und startet erst nach dessen Merge.

## Problem / Motivation

Das Monitoring schweigt genau dann, wenn ein Subsystem ausfällt, und es bewertet Container nach der Restart-Policy
statt nach ihrem tatsächlichen Ende. Belegt im Monitoring-Lab (Ubuntu 24.04, Docker 29.9.1, echter Stack, 2026-10-16)
und im Code:

1. **Stumme Ausfälle.** Der Agent liefert den Block `docker` nur, wenn CLI, `docker info`, `docker ps` und das Parsen
   klappen; sonst fehlt er (`apps/agent/internal/monitor/plugins.go:37-69`). Für ZFS dasselbe: `zpool list` mit
   Fehler oder Timeout → kein Block (`plugins.go:242-271`), obwohl der Kommentar `:21-26` genau den hängenden Pool
   als Grund für das Timeout nennt. Der Checker macht daraus `unknown` mit „Keine Docker-/ZFS-Daten im Report“
   (`apps/monitoring/app/checkers/plugins.py:118-121`, `:182-185`), und `unknown` benachrichtigt nie
   (`apps/monitoring/app/alerter.py:58-78`). Ein gestoppter Docker-Daemon oder ein hängender Pool bleibt damit
   unsichtbar.
2. **Veraltete Anzeige.** Fehlt der Block, behält die Push-Auswertung die alten Details
   (`apps/monitoring/app/routers/agent.py` → `apply_result(..., keep_previous_details_when_absent=True)`,
   `apps/monitoring/app/check_engine.py:166-197`). Die Desktop-Sektion zeigt weiter „Alle N Container laufen“,
   nur mit grauem Punkt.
3. **Ein neuer Check ohne Daten steht grün.** `effective_status` macht aus einem gedämpften Nicht-ok bei altem Status
   `pending` ein `ok` (`check_engine.py:88-101`). Ein neu zugewiesenes Docker-Template ohne Agent-Daten erscheint
   so zuerst als gesund.
4. **Bewertung nach Restart-Policy statt nach dem Ende** (`checkers/plugins.py:205-220`): Im Lab galt ein
   abgestürzter Container `Exited (3)` ohne Policy als ok, `paused`/`created` als ok, ein von Hand gestoppter
   Container mit `always`/`unless-stopped` als critical. Restart-Zähler, Exit-Code und OOM werden nicht erhoben;
   eine Crash-Schleife sieht man im 5-Minuten-Raster meist als `running`.
5. **SMART ohne smartctl gilt als ok** mit demselben Text wie eine VM ohne SMART-Geräte
   (`apps/monitoring/app/checkers/smart.py:69-73`; Agent `apps/agent/internal/monitor/smart.go:50-75` gibt in allen
   Fällen `nil`). Ein Bare-Metal-Host ohne `smartmontools` wirkt geprüft, ist es aber nicht.

## Ziel & Nicht-Ziele

**Ziele**
- Der Agent meldet die Blöcke `docker` und `zfs` **immer, sobald die CLI da ist**: `{available, error, …}`. Fehlt
  die CLI, fehlt der Block wie heute (nicht installiert ist kein Fehler).
- Ein nicht erreichbarer Daemon, ein Fehler oder Timeout eines CLI-Aufrufs, eine nicht lesbare Ausgabe ist ein
  **eigener Fehlerzustand**: Standard **warning mit Benachrichtigung**, je Check abschaltbar
  (`alert_on_unavailable`, Default `true`; abgeschaltet → `unknown` mit derselben Meldung, ohne Benachrichtigung).
- 0 Container bzw. 0 Pools bei erreichbarem Daemon: ok.
- Container werden nach ihrem Ende bewertet (Tabelle unten): Exit ≠ 0 → critical, OOM → critical, steigender
  Restart-Zähler → warning, gewollt gestoppt → ok, unhealthy → warning.
- Fehlt ein Block (CLI weg, alter Agent), zeigt die Anzeige keine veraltete Liste mehr: die Details werden geleert.
- Ein neuer Check, dessen erstes Ergebnis `unknown` ist, steht nicht grün, sondern `unknown`.
- SMART: „smartctl nicht installiert“, „Scan gescheitert“ und „keine SMART-fähigen Geräte“ sind unterscheidbar
  (Meldung und Detail-Code), Status bleibt ok.
- Desktop zeigt den Fehlerzustand von Docker und ZFS deutlich, zählt gestoppte Container getrennt und nennt den
  Grund je Container (Exit-Code, OOM, Neustarts, unhealthy, gestoppt).

**Nicht-Ziele (YAGNI)**
- Der Parser-Fix für `docker ps` ab Docker 28.2/29 (R-0417).
- Rootless Docker, `DOCKER_HOST`, Podman, Snap-Docker (Docker-Analyse Befund 7; eigene Zeile, wenn gewünscht).
- Proxmox-Plugin (`pvesh`): gleiches Muster; eigene Folgezeile (Kevin 2026-10-16).
- Erkennung „VM vs. Bare Metal“ für SMART (OS/Virtualisierung kommt mit R-0420).
- Änderung der `unknown`-Politik selbst: `unknown` benachrichtigt weiter nie; der neue Fehlerzustand ist ein echtes
  `warning`.

## Betroffene Komponenten & Dateien

| Bereich | Datei | Stelle |
|---|---|---|
| Agent Docker | `apps/agent/internal/monitor/plugins.go` | `collectDocker` `:37-69`, `inspectRestartPolicies` `:73-84`, `parseRestartPolicies` `:111-121` |
| Agent ZFS | `apps/agent/internal/monitor/plugins.go` | `collectZFS` `:242-271` |
| Agent SMART | `apps/agent/internal/monitor/smart.go`, `report.go` | `collectSmart` `:50-124` (`return nil` an `:53/61/72/97/124`), `BuildReport` `:61-73` |
| Agent-Tests | `apps/agent/internal/monitor/plugins_test.go`, `smart_test.go`, `report_test.go` | `TestParseRestartPolicies` (wird ersetzt) |
| Check-Config | `apps/monitoring/app/check_configs.py` | `ZfsHealthConfig` `:103-105`, `DockerHealthConfig` `:108-113` |
| Checker | `apps/monitoring/app/checkers/plugins.py` | `ZfsHealthChecker.evaluate` `:118-167`, `DockerHealthChecker.evaluate` `:182-246` |
| Checker SMART | `apps/monitoring/app/checkers/smart.py` | `evaluate` `:69-73` |
| Push-Pfad | `apps/monitoring/app/routers/agent.py` | Vorwert-Details nur für `agent_resources` `:226-236` |
| Engine | `apps/monitoring/app/check_engine.py` | `effective_status` `:88-101` |
| Desktop | `apps/desktop/ui/src/components/monitoring/section/SecDocker.svelte` (`info` `:31-49`, Anzeige `:66-120`), `SecZfs.svelte` (`:21-22`, `:58`), `CheckConfigFields.svelte` (zfs `:330`, docker `:351-361`), `apps/desktop/ui/src/lib/api/types.ts` (`MonitorContainerDetails` `:289-296`, `MonitorZfsDetails` `:308-314`), `apps/desktop/ui/src/lib/i18n/dictionaries.ts` (`monitoring.docker.*` DE `:581-582`, EN `:1203-1204`) |
| Paket | `apps/agent/deb/DEBIAN/control` (`Depends: systemd` `:5`), `apps/agent/rpm/adminhelper-agent.spec` (`Requires: systemd` `:17`) | `Recommends: smartmontools` |
| Doku | `docs/admin/monitoring.html` + EN (`:48-49`, `:64`, `:86-87`, `:95-96`, `:106ff`, `:165`), `docs/developer/agent.html` + EN (`:91-92`, `:102`), `docs/developer/monitoring.html` + EN (`:115`, `:121`), `CHANGELOG.md` |
| Heavy | `scripts/tests/multibox.sh`, `scripts/tests/box_agentbox.sh`, `scripts/tests/multibox_test.sh` | neue Etappe `--docker` (Harness, PR merged Kevin) |

## Datenmodell / API / Migrationen

**Agent-Report (additiv, Kevin 2026-10-16 freigegeben).** Alte Server ignorieren unbekannte Felder; der Report ist
auf der Serverseite ein freies `dict` (`routers/agent.py`, `report: dict`).

```json
"docker": {
  "available": true,
  "error": null,
  "containers": [
    {"id": "abc123def456", "name": "web", "image": "nginx:1.27", "state": "exited",
     "status": "Exited (3) 2 minutes ago", "restart_policy": "no",
     "exit_code": 3, "oom_killed": false, "restart_count": 0, "health": ""}
  ]
},
"zfs": {"available": true, "error": null, "pools": [...], "errors": "..."},
"smart_absent": {"reason": "not_installed" | "scan_failed" | "no_devices"}
```

- `available=false` + `error` (Maschinen-Code `daemon_unreachable` | `timeout` | `cli_failed` | `parse_failed`,
  dazu ein kurzer Text ohne Pfade/Secrets) bei Fehlern von `docker info`/`docker ps`/`docker inspect` bzw.
  `zpool list`. Die Container-Felder kommen aus **einem** `docker inspect <ids>` mit der Standard-JSON-Ausgabe statt
  eines Go-Templates (ein Template auf `.State.Health.Status` scheitert an Containern ohne Healthcheck): `Id`,
  `RestartCount`, `State.Status`, `State.ExitCode`, `State.OOMKilled`, `State.Health.Status`,
  `HostConfig.RestartPolicy.Name` — Feldnamen der Docker Engine API, gegen
  <https://docs.docker.com/reference/api/engine/> zu prüfen (**nicht verifiziert**). Unbekannte Felder werden
  ignoriert (Struct, kein `map[string]string`).
- `smart_absent` erscheint nur, wenn `smart` fehlt. `smart` selbst bleibt die Liste wie heute.

**Check-Config (kein Alembic):** `check.config` ist JSON. `DockerHealthConfig` und `ZfsHealthConfig` bekommen
`alert_on_unavailable: bool = True`; bestehende Checks ohne den Schlüssel bekommen damit Kevins Standard (warning).
`check_restarts` in `DockerHealthConfig` bleibt toleriert und ungenutzt (offene Frage 1).

**Details (Desktop-Vertrag, additiv):** `docker_health` → `{"available": bool, "error": code|null,
"containers": [{name, image, state, category, reason, exit_code, restart_count}]}` mit `category` ∈ `ok | warning |
critical | stopped`; `zfs_health` → zusätzlich `available`, `error`. Fehlt der Block, liefert der Checker
`{"containers": []}` bzw. `{"pools": []}` statt `None`, damit die alte Liste verschwindet.

**Vorwert-Details für `docker_health`:** Der Push-Pfad reicht die gespeicherten Details heute nur an
`agent_resources` (`routers/agent.py:226-236`). Für den Restart-Zähler bekommt auch `docker_health` die Vorwerte
(Zähler je Container-ID); `evaluate(config, report, prev_details=None)`.

**Bewertung je Container** (Docker-Doku Restart-Policies:
<https://docs.docker.com/engine/containers/start-containers-automatically/> — `on-failure` startet nur bei
Exit ≠ 0 neu; „If you manually stop a container, the restart policy is ignored until the Docker daemon restarts or
the container is manually restarted“; `always`/`unless-stopped` starten nach einem Absturz neu):

| Zustand | Bedingung | Kategorie | Grund-Code |
|---|---|---|---|
| `running` | Health `unhealthy` | warning | `unhealthy` |
| `running` | `restart_count` größer als der Vorwert derselben ID | warning | `restarted` |
| `running` | sonst (auch Health `starting`/`healthy`) | ok | — |
| `restarting` | — | critical | `restarting` |
| `dead` | — | critical | `dead` |
| `paused` | — | warning | `paused` |
| `created` | Exit 0 (nie gestartet) | stopped | `created` |
| `created` | Exit ≠ 0 (Start gescheitert) | critical | `start_failed` (Kevin 2026-10-17; Docker-Verhalten im Bau belegt) |
| `exited` | `oom_killed` | critical | `oom` |
| `exited` | Policy `always`/`unless-stopped` | stopped | `stopped` (ein Absturz würde neu starten; exited heißt von Hand gestoppt) |
| `exited` | Policy `on-failure`, Exit ≠ 0 | critical | `exit:<code>` (Versuche erschöpft) |
| `exited` | Exit 143 oder 137 ohne `oom_killed` (Signal, typisch `docker stop`) | stopped | `stopped` bzw. eigener Code (Kevin 2026-10-17) |
| `exited` | Policy `no`/leer, Exit ≠ 0 | critical | `exit:<code>` (Kevin 2026-10-16) |
| `exited` | Exit 0 | stopped | `stopped` |

Gesamtstatus: schlechteste Kategorie; `stopped` zählt als ok. `ignore_containers` gilt wie heute.

## Externe Integrationen

- Docker Restart-Policies: <https://docs.docker.com/engine/containers/start-containers-automatically/> (per WebFetch
  am 2026-10-16 gelesen, Zitate oben).
- Docker Engine API / `docker inspect`-JSON-Feldnamen: <https://docs.docker.com/reference/api/engine/> — **nicht
  verifiziert**, vom Builder vor T1 zu prüfen.
- `zpool list`: Format unverändert (`-H -o name,size,alloc,free,cap,health`); nur Fehlerpfad neu.

## Trade-offs & Alternativen

1. **Block immer senden vs. eigener Statuskanal.** Immer senden mit `{available, error}` hält Daten und Zustand in
   einem Objekt und ist für alte Server harmlos (ein alter Checker sieht `containers: []` → „Keine Container
   gefunden“, ok). Empfehlung: so.
2. **`docker inspect` als JSON vs. Go-Template.** JSON ist robust gegen fehlende `Health` und neue Felder; kostet
   mehr Bytes (eine Ausgabe je Zyklus). Empfehlung: JSON in ein Struct.
3. **„Von Hand gestoppt“ erkennen.** Docker legt das nicht in `inspect` offen. Bei `always`/`unless-stopped` ist
   `exited` nur nach manuellem Stopp möglich (ein Absturz startet neu) → stopped. Bei `no` ist Absturz und manueller
   Stopp nicht unterscheidbar → Exit-Code entscheidet (offene Frage 2).
4. **Details bei fehlendem Block leeren vs. als veraltet markieren.** Leeren ist einfacher und ehrlich; der Vorwert
   des Restart-Zählers geht dabei verloren (danach keine Warnung beim ersten Push, harmlos). Empfehlung: leeren.
5. **Pending-Dämpfung.** Nur `unknown` durchreichen, wenn der alte Status `pending` ist (kein Benachrichtigungsrisiko,
   `unknown` meldet nie). Warning/critical beim allerersten Ergebnis bleiben gedämpft wie heute.

## Risiken & Rollback

- **Neue Warnungen nach dem Update:** Hosts mit gestopptem Daemon oder alten `Exited (≠0)`-Containern melden
  erstmals. Das ist gewollt; Ausweg je Check `alert_on_unavailable=false` bzw. `ignore_containers`. CHANGELOG nennt
  es.
- **Restart-Zähler-Warnung** kann bei Containern mit geplanten Neustarts (z. B. Watchtower) rauschen → `ignore_containers`.
- **Gemischte Versionen:** neuer Agent + alter Server: ok (siehe Trade-off 1). Alter Agent + neuer Server: Block
  fehlt → `unknown`, Details geleert (statt veraltet). Kein Fehler.
- **Rollback:** Revert des Merge-Commits; keine Migration, keine API-Route.

## Doku-Impact

Sichtbar, DE + EN: `docs/admin/monitoring.html` (Check-Tabelle `:48-49`, Plugin-Hinweis `:64` — „ohne Daten kein
Fehler“ gilt nur noch für fehlende CLI, Defaults `:86-87` mit `alert_on_unavailable`, `unknown`-Abschnitt `:95-96`
mit der Ausnahme „Subsystem nicht erreichbar = warning“, SMART `:106ff`, Template-Zeile `:165`),
`docs/developer/agent.html` (`:91-92`: CLI statt Socket, Fehlerblock; `:102`), `docs/developer/monitoring.html`
(Report-Format `:115`, `:121`), `CHANGELOG.md` (auch: das Agent-Paket empfiehlt `smartmontools`).

## Offene Fragen

Keine. Entschieden von Kevin am 2026-10-16:

1. **Restart-Zähler-Warnung:** immer an, kein Schalter; Ausweg `ignore_containers`. `check_restarts` (tot in
   `DockerHealthConfig`, `check_configs.py:113`) bleibt toleriert und ungenutzt.
2. **`exited` mit Exit ≠ 0 ohne Restart-Policy:** critical; Ausweg `ignore_containers`.
3. **`smartmontools`:** als `Recommends` (nicht `Depends`) im deb (`apps/agent/deb/DEBIAN/control`) und im rpm
   (`apps/agent/rpm/adminhelper-agent.spec`), eigene Task (T12). RPM-Weak-Dependencies brauchen rpm ≥ 4.12;
   Rocky Linux 8, 9 und 10 bringen es mit (T12). Ein Paket-Upgrade installiert neue `Recommends` auf bestehenden
   Hosts nicht nach (apt `upgrade`, `dpkg -i`): Hinweis in Doku und CHANGELOG (T13).
4. **Proxmox-Plugin** (`pvesh` hängt bei Quorum-Verlust) mit demselben Fehlerblock: eigene Folgezeile, nicht hier.
