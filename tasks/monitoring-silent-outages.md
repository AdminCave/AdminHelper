<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring meldet Ausfälle von Docker, ZFS und SMART — Task-Ledger
Status: aktiv · Branch: feature/monitoring-silent-outages · Review: pro Task
Spec: docs/features/monitoring-silent-outages.md (Roadmap R-0419)
Heavy: linux-full + scenario --agents 1 --docker — Agent-Plugins und Push-Auswertung im echten Stack (`run.sh integration`, Agent-Monitoring-Pipeline); vor dem Merge der Multibox-Lauf mit der neuen Etappe `--docker` (T14), weil nur eine Box mit echtem Docker 29 und nativem Agent zeigt, dass ok → critical (`exit 1`) → warning (Daemon gestoppt) über den echten Push-Pfad ankommt; ask-first, Kevin hat Multibox am 2026-10-16 für die Monitoring-Pakete erlaubt
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-16: Daemon nicht erreichbar / zpool hängt / CLI-Fehler → eigener Fehlerzustand statt `unknown`, Standard warning mit Benachrichtigung, je Check abschaltbar (`alert_on_unavailable`, Default an); additive Report-Felder freigegeben; Exit ≠ 0 ohne Restart-Policy → critical; steigender Restart-Zähler → warning, immer an (kein Schalter); `smartmontools` als `Recommends` im deb und rpm (T12); Proxmox-Fehlerblock ist eine eigene Folgezeile. **Hängt ab von R-0417** (`feature/monitoring-docker-parse`, Parser für `docker ps` ab Docker 28.2/29): erst nach dessen Merge starten und `origin/main` hineinmergen. T14 ändert `scripts/` → den PR merged Kevin; T14 nicht gleichzeitig mit anderen Tasks an `multibox.sh` (frps-supervisor T16, agent-frpc-sync T7).

### T1 — Agent: Docker-Block mit `available`/`error` und Ende-Daten aus `docker inspect`  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/plugins.go, apps/agent/internal/monitor/plugins_test.go
Änderung: `collectDocker` (`plugins.go:37-69`) liefert den Block immer, sobald `docker` auf dem PATH ist: `available`, `error` (Code `daemon_unreachable` | `timeout` | `cli_failed` | `parse_failed`, kurzer Text ohne Pfade), `containers` (auch leer). `inspectRestartPolicies`/`parseRestartPolicies` (`:73-84`, `:111-121`) werden durch ein `docker inspect <ids>` mit Standard-JSON und eine Struct-Dekodierung ersetzt (`Id`, `RestartCount`, `State.Status/ExitCode/OOMKilled/Health.Status`, `HostConfig.RestartPolicy.Name`; Feldnamen vorher gegen die Engine-API-Doku prüfen) und je Container `restart_policy`, `exit_code`, `oom_killed`, `restart_count`, `health` gesetzt. Die docker-Aufrufe laufen über eine Paketvariable (Seam wie `pluginCollectors`, `report.go`), damit Tests ohne Docker laufen. Tests zuerst rot (Namen mit `Docker`): CLI fehlt → `nil`; `docker info` scheitert → `available=false`, `error=daemon_unreachable`, kein Container; Timeout → `error=timeout`; 0 Container → Block mit leerer Liste; `inspect`-JSON eines Containers ohne Healthcheck, eines mit `unhealthy`, eines `OOMKilled` und eines mit `RestartCount` 3 wird korrekt übernommen; unbekannte JSON-Felder stören nicht.
Verify: bash scripts/dev/verify.sh agent --strict -- -run Docker
Doku: keine (intern; Doku in T13)
Test-Löschung: apps/agent/internal/monitor/plugins_test.go::TestParseRestartPolicies — parseRestartPolicies entfällt, die Restart-Policy kommt aus dem inspect-JSON; ersetzt durch die neuen Docker-Tests dieser Task

### T2 — Agent: ZFS-Block mit `available`/`error`  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/plugins.go, apps/agent/internal/monitor/plugins_test.go
Änderung: `collectZFS` (`plugins.go:242-271`) liefert bei vorhandenem `zpool` immer einen Block: Fehler oder Timeout von `zpool list` → `available=false`, `error` (`timeout` | `cli_failed`), `pools: []`; sonst `available=true`, `error=null`, `pools` und ggf. `errors` wie heute. `zpool`-Aufrufe über einen Seam. Tests zuerst rot (Namen mit `ZFS`): zpool fehlt → `nil`; `zpool list` mit Fehler → Block mit `cli_failed`; Timeout → `timeout`; 0 Pools → `available=true`, leere Liste.
Verify: bash scripts/dev/verify.sh agent --strict -- -run ZFS
Doku: keine (intern; Doku in T13)
Abhängt von: T1

### T3 — Agent: Grund, wenn SMART fehlt  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/smart.go, apps/agent/internal/monitor/smart_test.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/report_test.go
Änderung: `collectSmart` (`smart.go:50-124`) gibt neben den Platten einen Grund zurück, wenn es keine gibt: `not_installed` (smartctl fehlt, `:53`), `scan_failed` (Scan scheitert oder liefert kein JSON, `:61`, `:72`), `no_devices` (Scan leer). `BuildReport` (`report.go:61-73`) setzt dann `smart_absent: {"reason": …}`; `smart` bleibt die Liste wie heute. `pluginCollectors.smart` (`report.go:84-89`) passt sich an. Tests zuerst rot (Namen mit `Smart`): je Grund der richtige Code im Report; mit Platten kein `smart_absent`.
Verify: bash scripts/dev/verify.sh agent --strict -- -run Smart
Doku: keine (intern; Doku in T13)

### T4 — Monitoring: Schalter `alert_on_unavailable` für Docker und ZFS  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/check_configs.py, apps/monitoring/tests/test_check_configs.py
Änderung: `ZfsHealthConfig` (`check_configs.py:103-105`) und `DockerHealthConfig` (`:108-113`) bekommen `alert_on_unavailable: bool = True`. `check_restarts` bleibt toleriert. Tests zuerst rot: Default `True`, `False` wird angenommen, ein Nicht-Bool wird 422, eine bestehende Config ohne den Schlüssel validiert weiter.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_configs.py
Doku: keine (intern; Doku in T13)

### T5 — Monitoring: Docker-Checker bewertet Ausfall und Container-Ende  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/plugins.py, apps/monitoring/tests/test_plugin_checkers.py
Änderung: `DockerHealthChecker.evaluate` (`plugins.py:182-246`) bekommt `prev_details=None`. Block fehlt → `unknown`, Details `{"containers": []}` (statt `None`, damit die alte Liste verschwindet). `available=false` oder `error` → `warning` mit Meldung, bei `alert_on_unavailable=false` `unknown`; Details `{"available": false, "error": <code>, "containers": []}`. Sonst Bewertung nach der Tabelle der Spec (Abschnitt „Bewertung je Container“): `category` ∈ ok/warning/critical/stopped, `reason`-Code, `exit_code`, `restart_count`; ein `restart_count` größer als der Vorwert derselben ID aus `prev_details` → warning `restarted`. Meldung zählt laufende, gestoppte und problematische Container ehrlich. Neue Meldungstexte englisch (Konvention), die Anzeige übersetzt aus den Codes. Tests zuerst rot: je Zeile der Tabelle ein Fall (u. a. `Exited (3)` ohne Policy → critical, `always` von Hand gestoppt → stopped, `on-failure` Exit 0 → stopped, OOM → critical, `paused` → warning, `created` → stopped, Restart-Zähler steigt → warning), Daemon weg → warning bzw. unknown mit Schalter aus, Block fehlt → unknown mit leerer Liste, 0 Container → ok.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_plugin_checkers.py
Doku: keine (intern; Doku in T13)
Abhängt von: T4

### T6 — Monitoring: Push-Pfad reicht Vorwerte auch an `docker_health`  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/tests/test_agent_report.py
Änderung: Die Vorwert-Details (`routers/agent.py:226-236`, heute nur `agent_resources`) gehen auch an `docker_health` (gleiche Absicherung gegen ungültiges JSON). Test zuerst rot: zwei Pushes nacheinander, im zweiten ist `restart_count` eines Containers gestiegen → der gespeicherte Zustand ist `warning` mit `reason=restarted`; ein Push ohne `docker`-Block leert die gespeicherten Container.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_report.py
Doku: keine (intern)
Abhängt von: T5

### T7 — Monitoring: ZFS-Checker meldet einen hängenden oder fehlerhaften `zpool`  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/plugins.py, apps/monitoring/tests/test_plugin_checkers.py
Änderung: `ZfsHealthChecker.evaluate` (`plugins.py:118-167`): Block fehlt → `unknown`, Details `{"pools": []}`; `available=false`/`error` → `warning` (bei `alert_on_unavailable=false` `unknown`), Details mit `available`, `error`; sonst wie heute, Details zusätzlich `available: true`. Tests zuerst rot: Timeout → warning, Schalter aus → unknown, Block fehlt → leere Pools, gesunde Pools unverändert ok.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_plugin_checkers.py
Doku: keine (intern; Doku in T13)
Abhängt von: T4

### T8 — Monitoring: SMART-Meldung nennt den Grund  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/smart.py, apps/monitoring/tests/test_smart_checker.py
Änderung: `SmartHealthChecker.evaluate` (`smart.py:69-73`): fehlt `smart`, liest der Checker `smart_absent.reason` und meldet ok mit unterscheidbarem Text und Details `{"absent": <reason>}` (`not_installed`, `scan_failed`, `no_devices`; ohne Feld wie heute „keine Daten“). Tests zuerst rot: je Grund Meldung und Detail-Code, Status bleibt ok.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_smart_checker.py
Doku: keine (intern; Doku in T13)

### T9 — Monitoring: ein neuer Check ohne Daten steht nicht grün  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/check_engine.py, apps/monitoring/tests/test_check_engine.py
Änderung: `effective_status` (`check_engine.py:88-101`): Ist das Ergebnis `unknown` und der alte Status `pending`, gilt `unknown` statt `ok`. Warning/critical beim ersten Ergebnis bleiben gedämpft wie heute; `unknown` benachrichtigt weiter nie (`alerter.py:58-78` unverändert). Tests zuerst rot: neuer Check, erstes Ergebnis `unknown` bei `consecutive_fails=2` → Status `unknown`, keine Benachrichtigung; erstes Ergebnis `critical` → weiter `ok` (gedämpft); bestehender `ok`-Check mit einem `unknown` → bleibt `ok` (gedämpft).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_engine.py
Doku: keine (intern; Doku in T13)

### T10 — Desktop: Docker-Sektion zeigt Ausfall, Gründe und gestoppte Container  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/SecDocker.svelte, apps/desktop/ui/src/components/monitoring/section/SecDocker.test.ts, apps/desktop/ui/src/lib/api/types.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: `MonitorContainerDetails` (`types.ts:289-296`) bekommt `available`, `error`, `category` inkl. `stopped`, `reason`, `exit_code`, `restart_count`. `SecDocker.svelte` (`info` `:31-49`, Anzeige `:66-120`): `available=false` → deutlicher Hinweis mit übersetztem Fehler statt „—“; gestoppte Container getrennt gezählt („3 laufen · 1 gestoppt“ statt „Alle 4 Container laufen“), je Container der übersetzte Grund (Exit-Code, OOM, n Neustarts, unhealthy, pausiert, gestoppt); auf dem Stand von R-0417 aufbauen, falls dort die Zählung schon angepasst wurde. Texte DE+EN in `dictionaries.ts` (neben `monitoring.docker.*`, DE `:581-582`, EN `:1203-1204`), nur aus Codes. Neue Testdatei mit SPDX-Header (`// SPDX-FileCopyrightText: 2026 Kevin Stenzel` / `//` / `// SPDX-License-Identifier: GPL-3.0-or-later`), zuerst rot: Ausfall-Hinweis, getrennte Zählung, Gründe je Kategorie, leere Liste ohne veraltete Einträge.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/section/SecDocker.test.ts
Doku: keine (intern; Doku in T13)
Abhängt von: T5

### T11 — Desktop: ZFS-Ausfall anzeigen, Schalter im Check-Formular  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/section/SecZfs.svelte, apps/desktop/ui/src/components/monitoring/CheckConfigFields.svelte, apps/desktop/ui/src/components/monitoring/CheckConfigFields.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: `SecZfs.svelte` (`:21-22`, `:58`) zeigt `available=false` mit übersetztem Fehler statt „keine Pools“ (`MonitorZfsDetails` `types.ts:308-314` bekommt `available`, `error` — falls `types.ts` dafür nötig, per `ledger.sh set-files` ergänzen). `CheckConfigFields.svelte` bekommt für `zfs_health` (`:330`) und `docker_health` (`:351-361`) die Checkbox „Ausfall melden“ (`alert_on_unavailable`, Default an). Texte DE+EN. Tests in `CheckConfigFields.test.ts`, zuerst rot: Checkbox bei beiden Typen, Default an, Abwahl schreibt `false`; der Test „no longer renders the dead check_restarts checkbox“ (`:58`) bleibt grün.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/CheckConfigFields.test.ts
Doku: keine (intern; Doku in T13)
Abhängt von: T4

### T12 — Agent-Paket empfiehlt `smartmontools`  [ ]
Komponente: agent · Dateien: apps/agent/deb/DEBIAN/control, apps/agent/rpm/adminhelper-agent.spec, apps/agent/cmd/adminhelper-agent/packaging_test.go
Änderung: `apps/agent/deb/DEBIAN/control` bekommt nach `Depends: systemd` (`:5`) die Zeile `Recommends: smartmontools`; `apps/agent/rpm/adminhelper-agent.spec` nach `Requires: systemd` (`:17`) die Zeile `Recommends:     smartmontools` (Weak Dependency, kein `Depends`/`Requires`: der Agent läuft auch ohne, der SMART-Check nennt dann den Grund aus T3). Neue Testdatei mit SPDX-Header (`// SPDX-FileCopyrightText: 2026 Kevin Stenzel` / `//` / `// SPDX-License-Identifier: GPL-3.0-or-later`) im Paket `main` von `cmd/adminhelper-agent`, zuerst rot: liest `../../deb/DEBIAN/control` und `../../rpm/adminhelper-agent.spec` und prüft, dass genau eine `Recommends:`-Zeile `smartmontools` nennt und `smartmontools` in keiner `Depends:`/`Requires:`-Zeile steht. Ob die Ziel-Distributionen rpm ≥ 4.12 haben (Weak Dependencies), ist nicht verifiziert — `box_agentbox_rpm.sh` im Sammellauf installiert das echte Paket.
Verify: bash scripts/dev/verify.sh agent --strict -- -run Packag
Doku: keine (intern; der CHANGELOG-Eintrag in T13 nennt es)

### T13 — Doku und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, CHANGELOG.md
Änderung: `docs/admin/monitoring.html` DE+EN: Check-Tabelle (`:48-49`), Plugin-Hinweis (`:64`: „ohne Daten kein Fehler“ nur noch bei fehlender CLI; ein nicht erreichbares Subsystem ist warning), Defaults (`:86-87`: `alert_on_unavailable`), Abschnitt „unknown benachrichtigt nie“ (`:95-96`: die Ausnahme), SMART (`:106ff`: Gründe), Template-Zeile Docker (`:165`: Bewertung nach Exit-Code/OOM/Neustarts). `docs/developer/agent.html` DE+EN (`:91-92`: CLI statt Socket, Fehlerblock; `:102`). `docs/developer/monitoring.html` DE+EN (Report-Format `:115`, `:121`: `available`/`error`, `smart_absent`). CHANGELOG: Fixed (stumme Ausfälle, Bewertung) und Changed (neue Warnungen nach dem Update, Ausweg `alert_on_unavailable`/`ignore_containers`; das Agent-Paket empfiehlt `smartmontools`).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/monitoring.html + docs/en/admin/monitoring.html · docs/developer/agent.html + EN · docs/developer/monitoring.html + EN · CHANGELOG.md
Abhängt von: T1, T2, T3, T5, T7, T8, T9, T10, T11, T12

### T14 — Multibox: Etappe `--docker` mit echtem Docker auf der Agent-Box  [ ]
Komponente: scripts · Dateien: scripts/tests/multibox.sh, scripts/tests/box_agentbox.sh, scripts/tests/multibox_test.sh
Änderung: Neuer Flag `--docker` in `multibox.sh`: die Agent-Box installiert Docker (Paket der Distribution oder docker-ce, aktuelle Version), der Orchestrator weist dem Server das Template „Docker Host“ zu, dann drei Stufen mit je einem `adminhelper-agent run --once` und Abfrage des Check-Zustands über den Monitoring-Dienst der Server-Box: (1) ein laufender Container → `ok` (`DOCKER_OK`), (2) zusätzlich ein Container mit `exit 1` ohne Policy → `critical` mit `reason=exit:1` (`DOCKER_EXIT_CRIT`), (3) Docker-Daemon gestoppt → `warning` mit `error=daemon_unreachable` (`DOCKER_UNAVAIL_WARN`). `multibox_test.sh` (hermetisch) prüft Flag-Parsing und Marker-Auswertung. **Harness-Pfad: PR merged Kevin.** Nicht gleichzeitig mit frps-supervisor T16 / agent-frpc-sync T7 (beide ändern `multibox.sh`); vorher `origin/main` hineinmergen.
Verify: bash scripts/dev/verify.sh scripts --strict -- multibox_test
Doku: keine (Test-Harness)
Abhängt von: T1, T5, T6
