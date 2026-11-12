<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-ui-2 — Task-Ledger
Status: aktiv · Branch: feature/arch-monitoring-ui-2 · Review: pro Task
Spec: docs/features/arch-monitoring-ui-2.md (Roadmap R-1227)
Heavy: linux-full — `apps/agent` (neue Allowlist-Aufrufe, Bericht) und Desktop-Ansichten; dazu vor dem Merge die Live-Spec aus T11 auf der warmen Desktop-VM (Screenshots für Kevin, Spec „Screenshots“)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@2782b2d83`. R-1226 fährt in `arch-monitoring-ui-3` (überlappt `feature/arch-monitoring-module-2`),
das HTTPS-Zertifikat aus R-1227 ist mit `arch-monitoring-ui` T2 gemergt. Dieser Zug ändert weder
`apps/desktop/ui/src/lib/api/types.ts` noch `apps/monitoring/app/schemas.py` oder den OpenAPI-Snapshot (ändert
`feature/arch-monitoring-module-2`) noch `apps/agent/internal/monitor/allowlist_test.go` (ändert
`feature/kern-monitoring-22`): neue Detail-Felder als lokale Typen in `checkDetails.ts`, neue Allowlist-Fälle in
`apps/agent/internal/allowlist/allowlist_test.go`. Status, Meldung und Metriken jedes Checks bleiben bitgleich, jede
Agent-Task prüft das mit einem Test. Jedes externe Format liest die Task vor dem Code in der Primärquelle nach
(Spec „Externe Integrationen“) und nennt sie im Commit-Body. Neue Quelldateien bekommen den SPDX-Header (`reuse
annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later <datei>`). UI nur aus Tokens und Komponenten unter
`apps/desktop/ui/src/components/ui/`, Texte DE+EN in `dictionaries.ts`.

### T1 — Agent: Namen der Sicherheitsupdates und Reboot-Pakete (R-1227)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/updates_linux.go, apps/agent/internal/monitor/updates_linux_test.go, apps/agent/internal/monitor/pkgaudit.go, apps/agent/internal/monitor/pkgaudit_test.go, apps/agent/internal/monitor/system_linux.go, apps/agent/internal/monitor/system_linux_test.go, apps/agent/internal/monitor/reportstate.go, apps/agent/internal/monitor/reportstate_test.go, apps/agent/internal/monitor/updates.go, apps/agent/internal/monitor/system_freebsd_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @59c1bc98b 2026-11-12T11:40:23+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-2/T1.verdict.json)
Änderung: `countAptSecurity`, `countDNFSecurity` und `pkgSecurityUpdates` liefern neben der Zahl die sortierten Paketnamen (höchstens 100, Name gekappt); `updatesCheck` speichert sie, damit die stündliche Zählung sie bis zum nächsten Lauf weitergibt (alter Zustand ohne Namen bleibt lesbar). Reboot-Pakete: Debian aus `/var/run/reboot-required.pkgs` (Pfad als Variable neben `rebootRequiredPath`), RPM aus den `  * <paket>`-Zeilen von `needs-restarting -r` (Format in `dnf-plugins-core` nachlesen). Der Systemzustands-Block trägt `security_packages` und `reboot_packages`; Zahl und `reboot_required` unverändert. Tests: Fixtures je Werkzeug, Kappung, alter Zustand, fehlende/leere `.pkgs`-Datei, unbekanntes Format ohne Namen.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestSystemStateUpdates|TestSystemStateReboot|TestCountPkgAudit|TestPkgSecurityUpdates|TestFreebsdSystemState|TestReportState|TestSystemStateBlock
Doku: → T12

### T2 — Agent: Prozess hinter dem OOM-Kill (R-1227)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/system_linux.go, apps/agent/internal/monitor/system_linux_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @432ac0a2f 2026-11-12T11:55:29+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-2/T2.verdict.json)
Änderung: Nur wenn `oom_kills` in diesem Bericht > 0 und nicht im Container: ein neuer Allowlist-Aufruf `journalctl` mit `--dmesg`, Priorität `err` und festem Fenster seit dem letzten Bericht (`--since=-<seconds>s`, gedeckelt; Ausgabeform nach journalctl(1) wählen, getrennt von den Aufrufen des Log-Sensors), daraus nur `Killed process <pid> (<comm>)` (Kernel `mm/oom_kill.c` nachlesen) → `oom_processes: [{pid, name}]`, höchstens 10, `comm` gekappt. Fehlt journalctl oder scheitert der Aufruf: keine Namen, Zähler unverändert. Tests: Fixture mit globalem und cgroup-OOM, fremde Zeilen verworfen, kein Aufruf ohne Kill und im Container, Allowlist positiv und Fallen (andere Ausgabe, ohne `--dmesg`, Option im Sekundenfeld).
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestSystemStateOOM|TestAllowlist
Doku: → T12
Abhängt von: T1

### T3 — Agent: Docker nach Compose-Projekt, Ports, Laufzeit (R-1227)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/plugins.go, apps/agent/internal/monitor/plugins_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @ebc8a1357 2026-11-12T12:01:37+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-2/T3.verdict.json)
Änderung: Aus dem `docker inspect`, das `collectDocker` schon fährt (kein neuer Aufruf): je Container `compose_project` und `compose_service` aus `Config.Labels`, `ports` aus `NetworkSettings.Ports` (nur veröffentlichte, `host_ip:host_port->port/proto`, gekappt) und `started_at` aus `State.StartedAt`. Fehlende Felder bleiben weg. Tests: Inspect-Fixture mit und ohne Compose-Labels, ohne Ports, IPv4+IPv6, Teilantwort.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestCollectDocker|TestParseDockerPS
Doku: → T12

### T4 — Agent: Proxmox-Backup mit Storage, Größe, Job, Fehler, PBS-Verify (R-1227)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/plugins.go, apps/agent/internal/monitor/plugins_test.go, apps/agent/internal/monitor/reportstate.go, apps/agent/internal/monitor/reportstate_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @596d6eabc 2026-11-12T12:25:58+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-2/T4.verdict.json)
Änderung: PVE-API-Viewer vorher lesen. `buildBackupIndex` nimmt aus den Content-Einträgen, die es schon liest, je Gast Storage, `size` und `verification.state` des neuesten Backups; neue Allowlist-Aufrufe `pvesh get /cluster/backup` (Job je Gast: ID, Zeitplan, Ziel-Storage) und `pvesh get /nodes/<node>/tasks` mit `--typefilter vzdump --errors 1 --limit <n>`, für den jüngsten fehlgeschlagenen Lauf sein Log (`/nodes/<node>/tasks/<upid>/log`, neue Klasse `upid`) und daraus nur `ERROR: Backup of VM <id> failed - <text>` je Gast (Text gekappt). Alles im 30-min-Cache von `backupIndexCheck` (alter Zustand bleibt lesbar). Ein gescheiterter Zusatzaufruf lässt nur sein Feld weg. Tests: Fixtures aus der dokumentierten Form, Cache, fehlende Rechte, Allowlist positiv und Fallen (UPID mit fremdem Typ, Pfad außerhalb `tasks`).
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestCollectProxmox|TestReportStateProxmoxBackups|TestBuildReportCarriesProxmoxBackups|TestAllowlist
Doku: → T12

### T5 — Agent: ZFS mit Scrub, vdev-Fehlern und Fragmentierung (R-1227)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/plugins.go, apps/agent/internal/monitor/plugins_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go, apps/agent/internal/monitor/testdata/zpool-status-scrub.json
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @c85b93f8e 2026-11-12T12:44:19+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-2/T5.verdict.json)
Änderung: zpool-status(8) und zpoolprops(7) vorher lesen. `zpool list` um `fragmentation` (Allowlist-Eintrag und `parseZpoolList` zusammen; `-` heißt unbekannt); neuer Aufruf `zpool status -j` → je Pool `scrub` (Ende, Fehler, Zustand) und je vdev Lese-/Schreib-/Prüfsummenfehler (nur vdevs mit Fehlern, gekappt). Kennt `zpool` kein `-j` (OpenZFS ≤ 2.2): keine Zusatzdetails, kein Fehler, Gesundheit wie heute. Tests: JSON-Fixture mit Scrub und vdev-Fehlern, alter zpool, kaputtes JSON, Allowlist.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestParseZpoolList|TestCollectZFS|TestAllowlist
Doku: → T12

### T6 — Agent: Top-5-Prozesse bei hoher Last (R-1227)  [?] (Auslöser der Top-5-Prozesse: A Standard-Warnschwelle 80 % im Agenten (Empfehlung) oder B Schwellen über den Agent-Plan)
Komponente: agent · Dateien: apps/agent/internal/monitor/processes.go, apps/agent/internal/monitor/processes_test.go, apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/collector_test.go
Änderung: Neue Datei `processes.go` (SPDX, Test ebenso): liegt CPU bzw. RAM über dem Auslöser (Spec „Offene Fragen“ 1), sammelt der Agent mit gopsutil `process` die fünf Prozesse nach CPU (zwei Stichproben ~1 s, ctx-begrenzt) bzw. RSS: `top_processes: {cpu: [{pid, name, cpu_pct}], memory: [{pid, name, rss}]}` im Ressourcen-Block, nur `comm`, nie die Kommandozeile. Unter dem Auslöser: kein Aufruf. Tests mit gestubbter Prozessliste: unter/über dem Auslöser, Sortierung, Kappung, verschwundener Prozess.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestTopProcesses|TestResources
Doku: → T12

### T7 — Monitoring: Systemzustand und Ressourcen reichen die Details durch (R-1227)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/system.py, apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_system_state_checker.py, apps/monitoring/tests/test_agent_resources_checker.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @a7368ab95 2026-11-12T12:51:27+01:00
Review: approve (.ah-out/review/arch-monitoring-ui-2/T7.verdict.json)
Änderung: `SystemStateChecker` übernimmt `security_packages`, `reboot_packages`, `oom_processes`, `_resources_details` übernimmt `top_processes` gekappt (`capped_objects`, `cap_agent_text`) in `details`; Status, Meldung und Metriken bitgleich (Test vergleicht mit und ohne die neuen Felder). Kaputte Formen fallen weg.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_system_state_checker.py tests/test_agent_resources_checker.py
Doku: → T12

### T8 — Monitoring: Docker, Proxmox-Backup, ZFS reichen die Details durch (R-1227)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/plugins.py, apps/monitoring/tests/test_plugin_checkers.py
Änderung: `DockerHealthChecker` übernimmt `compose_project`, `compose_service`, `ports`, `started_at` je Container; `ProxmoxBackupChecker` Storage, Größe, Job, letzten Fehler, Verify-Status je Gast; `ZfsHealthChecker` Scrub, vdev-Fehler, Fragmentierung; alles gekappt. Status, Meldung, Metriken bitgleich (Vergleichstest je Checker).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_plugin_checkers.py
Doku: → T12

### T9 — Desktop: Systemzustand, Updates, Top-5 in der Server-Seite und der Quer-Ansicht (R-1227)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/models/checkDetails.ts, apps/desktop/ui/src/lib/models/checkDetails.test.ts, apps/desktop/ui/src/components/monitoring/section/SecSystem.svelte, apps/desktop/ui/src/components/monitoring/section/SecSystem.test.ts, apps/desktop/ui/src/components/monitoring/section/SecLive.svelte, apps/desktop/ui/src/components/monitoring/section/SecLive.test.ts, apps/desktop/ui/src/components/monitoring/cross/UpdatesView.svelte, apps/desktop/ui/src/components/monitoring/cross/UpdatesView.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: Leser für die neuen Felder in `checkDetails.ts` (lokale Typen, `types.ts` unberührt). SecSystem: aufklappbare Paketlisten (Sicherheitsupdates, Reboot-Pakete), OOM-Prozesse; UpdatesView: Paketnamen je Server; SecLive: Top-5-Tabelle, wenn vorhanden und der Check warnt. Ohne die Felder sieht alles aus wie heute. Neun Dateien: Leser, drei Ansichten mit ihren Tests und die Texte gehören zu einer Anzeige.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/models/checkDetails.test.ts src/components/monitoring/section/SecSystem.test.ts src/components/monitoring/section/SecLive.test.ts src/components/monitoring/cross/UpdatesView.test.ts src/lib/i18n/i18n.test.ts
Doku: → T12
Abhängt von: T7

### T10 — Desktop: Docker nach Projekt, Backups, ZFS (R-1227)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/models/checkDetails.ts, apps/desktop/ui/src/lib/models/checkDetails.test.ts, apps/desktop/ui/src/components/monitoring/section/SecDocker.svelte, apps/desktop/ui/src/components/monitoring/section/SecDocker.test.ts, apps/desktop/ui/src/components/monitoring/section/SecBackups.svelte, apps/desktop/ui/src/components/monitoring/section/SecBackups.test.ts, apps/desktop/ui/src/components/monitoring/section/SecZfs.svelte, apps/desktop/ui/src/components/monitoring/section/SecZfs.test.ts, apps/desktop/ui/src/components/monitoring/cross/BackupsView.svelte, apps/desktop/ui/src/components/monitoring/cross/BackupsView.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts
Änderung: SecDocker gruppiert nach `compose_project` („mailcow 18/18“, aufklappbar zu Containern mit Health, Ports, Laufzeit; ohne Label „ohne Projekt“); SecBackups und BackupsView zeigen Storage, Größe, Job, letzten Fehler, PBS-Verify; SecZfs Scrub, vdev-Fehler, Fragmentierung. Ohne die Felder wie heute. Elf Dateien: drei Sektionen und eine Quer-Ansicht je mit Test, dazu Leser und Texte, eine Anzeige-Schicht.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/models/checkDetails.test.ts src/components/monitoring/section/SecDocker.test.ts src/components/monitoring/section/SecBackups.test.ts src/components/monitoring/section/SecZfs.test.ts src/components/monitoring/cross/BackupsView.test.ts src/lib/i18n/i18n.test.ts
Doku: → T12
Abhängt von: T8, T9

### T11 — Desktop-E2E: Detail-Ansichten mit Fixture-Bericht und Screenshots (R-1227)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/test/specs/monitoring-server-page.live.js, scripts/tests/desktop_e2e_monitoring.sh
Änderung: Ein zweiter Server mit einem festen Fixture-Bericht (Compose-Projekte, Proxmox-Backups mit Fehler und Verify, ZFS mit Scrub und vdev-Fehler, Sicherheitsupdates, Reboot-Pakete, OOM, Top-5); der Weg dorthin ist Testcode, kein Produktpfad. Die Spec öffnet je neue Detail-Ansicht, prüft die Werte und speichert ein Bild hell und dunkel unter `.ah-out/screenshots/`. Läuft auf der warmen Desktop-VM (`Heavy:`).
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: → T12
Abhängt von: T9, T10

### T12 — Doku: Details der Checks DE+EN, Allowlist, CHANGELOG (R-1227)  [ ]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/arch-monitoring-ui-2.md
Änderung: Admin: welche Details je Check erscheinen, wann (Top-5 nur bei hoher Last, OOM nur nach einem Kill, ZFS-Details ab OpenZFS 2.3), Satz zur Feld-Freigabe (nur Namen, nie Ausgaben oder Kommandozeilen; nur im Desktop). Entwickler: die neuen `details`-Felder je Check-Typ, die neuen Allowlist-Aufrufe. CHANGELOG-Fragment nach `changelog.d/README.md`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende

## Entscheidungen

- 2026-11-12 T1: Paketnamen höchstens 100 je Feld, je Name höchstens 128 Byte (UTF-8-sicher gekappt), sortiert und dedupliziert über `packageNames` — begrenzt Report und Zustandsdatei bei vielen Updates, Reihenfolge stabil für Vergleiche im Desktop
- 2026-11-12 T1: `putSecurityUpdates` setzt Zahl und Namen für Linux und FreeBSD an einer Stelle — beide Systemzustands-Blöcke trugen die Zahl doppelt
- 2026-11-12 T1: Namen aus apt `Inst`-Zeilen (Feld 2, `:arch` nur bei Fremdarchitektur, apt `pkgcache.cc`), dnf `updateinfo list` (Spalte 3 ohne Version), `pkg audit -q` (bis zum letzten `-`), `/var/run/reboot-required.pkgs` (update-notifier, Namen können doppelt stehen), `needs-restarting -r` (`  * <name>`, dnf-plugins-core) — die Zahl bleibt wie bisher, die Namen sind die der gezählten Zeilen
- 2026-11-12 T1: unlesbare `reboot-required.pkgs` (nicht „fehlt“) loggt eine Warnung und lässt nur `reboot_packages` weg — `reboot_required` steht über die Flag-Datei fest
- 2026-11-12 T2: Zeitfenster der OOM-Namen = jetzt − Zeitpunkt des letzten erfolgreichen Reports (`prev.CPU.Unix`) + 1 s, gedeckelt auf 1 h (auch ohne Vorgänger und bei zurückgestellter Uhr) — best effort: ein Kill, der im letzten Report gezählt, aber erst danach geloggt wurde, kann noch einmal genannt werden; ein Name, den journald verspätet annimmt, kann fehlen; der Zähler bleibt die Wahrheit
- 2026-11-12 T2: kein `--lines` neben `--since` — journalctl(1) beschreibt nicht, wie beide zusammenwirken; die Menge begrenzen Fenster, `--priority=3` und `--dmesg` (nur der aktuelle Boot)
- 2026-11-12 T2: gelesen wird nur `Killed process <pid> (<comm>) total-vm:` am Zeilenanfang (optional hinter einem Präfix ohne Doppelpunkt) — eine zitierte Kill-Zeile in einer anderen Meldung ist kein Kill; `(.*)` gierig bis zum letzten `) total-vm:`, weil comm Klammern tragen kann; ältere Kernel ohne Ursachen-Präfix nicht verifiziert
- 2026-11-12 T2: die neuesten 10 in Log-Reihenfolge, comm über `capPackageName` (128 Byte, UTF-8-sicher) — begrenzt den Report bei Kill-Serien, die jüngsten Kills sind die relevanten
- 2026-11-12 T2: `systemCLI.now` als Uhr-Naht neben `run`/`lookPath` — macht das Fenster ohne echte Wartezeit testbar
- 2026-11-12 T3: `compose_project`/`compose_service` nach der Regel der Discovery (`contractText`: höchstens 255 Zeichen, kein Steuerzeichen, sonst weggelassen statt gekürzt) — ein gekürzter Name gruppierte den Container unter ein anderes Projekt; Labelnamen aus docker/compose `pkg/api/labels.go`
- 2026-11-12 T3: `ports` als `host_ip:host_port->port/proto` wie die Ports-Spalte von `docker ps` (IPv6 in Klammern über `net.JoinHostPort`, Bindung ohne Adresse ohne Host-Teil), sortiert, dedupliziert, höchstens 64 (wie `maxContainerPorts` der Discovery); Adresse über `netip.ParseAddr`, Ports als Zahl 1–65535 normalisiert, Protokoll nur tcp/udp/sctp — der Daemon-Ausgabe wird nicht ungeprüft vertraut
- 2026-11-12 T3: `started_at` als Unix-Sekunden wie `last_backup_ts`, auch für gestoppte Container (letzter Start); die Nullzeit eines nie gestarteten Containers lässt das Feld weg — der Desktop rechnet die Laufzeit nur für laufende
- 2026-11-12 T3: Fixture aus echtem Docker 29.9 (API 1.56, drei Wegwerf-Container auf der Dev-Box, Ports nur auf Loopback, danach entfernt)
- 2026-11-12 T4: Jobs, letzter Fehler und Größe/Verifikation werden nur zusammen mit dem Backup-Index gelesen (alle 30 min, `proxmoxBackupsEvery`), nie einzeln; ein Teil, der sich nicht lesen lässt, fehlt nur selbst — der Index und Status/Meldung/Metriken des Checks bleiben unverändert; ein frischer Index eines älteren Agenten trägt bis zum nächsten Lesen keine Details
- 2026-11-12 T4: Größe nur bei 1 < size < 2^53 — PBSPlugin.pm setzt `size => $item->{size} // 1` für unbekannte Größe; Verifikationszustand nur, wenn er `^[a-z][a-z0-9_-]{0,31}$` trifft
- 2026-11-12 T4: Jobs aus `/cluster/backup`, deaktivierte (`enabled` nach `parse_boolean`) verworfen, höchstens 64; ID, Zeitplan und Speicher über `labelText` (Steuerzeichen oder über 255 Zeichen ⇒ weggelassen); Mail-Adressen, Kommentare und Notiz-Vorlagen der Jobs werden nie gelesen (Feld-Freigabe)
- 2026-11-12 T4: Abdeckung wie `VZDump.pm get_included_guests`: `pool` (nur direkte Mitglieder, `get_resource_pool_guest_members`) vor `vmid`-Liste vor `all` minus `exclude`, gefiltert auf den Knoten des Jobs — ein Pool-Job deckt keinen Gast über seine vmid-Liste
- 2026-11-12 T4: letzter Fehler aus der jüngsten vzdump-Task mit `--statusfilter error` (nicht `--errors 1`, das auch Warnungen zählt), deren Log mit `--limit 10000` (ein Gast schreibt etwa 20–50 Zeilen); nur Zeilen `ERROR: Backup of VM <id> failed - <text>`, Text mit Steuerzeichen als Leerzeichen und auf 200 Zeichen gekappt
- 2026-11-12 T4: der Log-Aufruf wird vorher gegen die Allowlist geprüft (`commandAllowed`), die UPID-Klasse nimmt nur `vzdump`-UPIDs ohne `/` und `:` im Benutzer — die UPID kommt aus der Ausgabe von pvesh, nicht aus eigenem Code
- 2026-11-12 T4: dieselbe UPID wie im gespeicherten Zustand ⇒ Log nicht erneut lesen; ein Fehler gilt nur, solange seine Task nicht vor dem neuesten Backup des Gasts startete (ein späteres erfolgreiches Backup löscht ihn)
- 2026-11-12 T4: nicht auf echter PVE verifiziert — Formate aus pve-manager/pve-common/pve-storage-Quellen und dem API-Viewer; Befund 1/2 bleibt nach §10 Entscheidung 7 Kevins Wort
- 2026-11-12 T5: `zpool status -j --json-int --json-flat-vdevs` (alle drei ab OpenZFS 2.3.0) — Zähler als Zahlen statt `nicenum`-Text, jedes vdev einmal in einer Map (Wurzel, Log, Cache, Spare, Special eingeschlossen); ohne `-v`, also nie Namen beschädigter Dateien; eine Zahl als String ⇒ keine Details
- 2026-11-12 T5: der Aufruf läuft je Zyklus nur, wenn `zpool list` Pools nennt; ein Fehlschlag (alter zpool ohne `-j`, Timeout, Exit ≠ 0 auch mit Ausgabe) oder unlesbare Ausgabe lässt die Details still weg wie bei `status -x` — Gesundheit und Kapazität wie bisher
- 2026-11-12 T5: `scrub` nur, wenn der letzte Scan ein Scrub war (`function` SCRUB) — der Pool hält nur den letzten Scan, nach einem Resilver gibt es kein Scrub-Datum; Zustände SCANNING/FINISHED/CANCELED, ein pausierter Scrub (SCANNING mit `scrub_pause`) als PAUSED; `end` nur, wenn er nicht mehr läuft und > 0
- 2026-11-12 T5: `vdev_errors` nur vdevs mit einem Zähler > 0, nach Name sortiert, höchstens 32 je Pool; Namen über `labelText` (Steuerzeichen oder über 255 Zeichen ⇒ leer)
- 2026-11-12 T5: `fragmentation_percent` nur aus `NN%` mit 0–100 (`zpool_get_prop`); `-` (unbekannt, `ZFS_FRAG_INVALID`) oder anderes lässt das Feld weg; Allowlist-Eintrag von `zpool list` und Parser zusammen geändert
- 2026-11-12 T5: Fixture aus echtem OpenZFS 2.4.2 (FreeBSD 15.1, Wegwerf-VM im Pool `adminhelper-ci`, dateibasierter Mirror mit Log-vdev, eine Seite überschrieben, dann Scrub; danach zerstört); pausierter und abgebrochener Scrub aus derselben Probe
- 2026-11-12 T7: neue Felder nur in `details`, nie in der Meldung (Mail, Webhook); jedes Feld nur, wenn der Agent ein brauchbares schickte — die Details eines älteren Agenten bleiben bitgleich, ein Block ohne brauchbaren Zähler bleibt „nicht bewertet“ ohne Namen
- 2026-11-12 T7: dieselben Grenzen wie auf dem Agenten (100 Paketnamen, 10 OOM-Prozesse, 5 Top-Prozesse je Liste), Namen über `cap_agent_text`; von Prozessen nur `pid` (ganze Zahl ab 1), `name` und `cpu_pct`/`rss` (Zahl ab 0) — jedes weitere Feld eines Eintrags fällt weg (Feld-Freigabe), ein kaputter Eintrag ebenso, ohne die Liste aufzufüllen
