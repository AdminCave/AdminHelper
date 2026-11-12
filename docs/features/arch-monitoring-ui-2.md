<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Details der bestehenden Checks (Architektur, Zug 2)

Roadmap R-1227 (FEAT, Architektur) · Zug `arch-monitoring-ui-2` · Kevin 2026-11-09, Monitoring-Konzept (§3.13
Feld-Freigabe und feste Allowlist, Entscheidung „Mockup“: ohne Mockup bauen, Screenshots vor dem Merge). Stand des
Codes: `origin/main@2782b2d83`; `datei:zeile` gilt für diesen Stand.

R-1226 (Dienste-Details mit Logs) war demselben Zug zugeordnet und fährt im Folgezug `arch-monitoring-ui-3`: sein
Schalter je Server braucht `apps/monitoring/app/schemas.py`, `check_configs.py` und den OpenAPI-Snapshot, die der
offene Branch `feature/arch-monitoring-module-2` (R-1224) ändert. Das HTTPS-Zertifikat aus R-1227 ist mit
`arch-monitoring-ui` T2 gemergt (`details.cert` im HTTP-Check, #450) und hier keine Task mehr.

## Problem / Motivation

Die bestehenden Agent-Checks melden Zahlen, wo der Admin den Namen braucht: „3 Sicherheitsupdates“ ohne Paketnamen,
„Neustart nötig“ ohne die Pakete dahinter, „1 OOM-Kill“ ohne den getöteten Prozess, CPU 95 % ohne den Verursacher,
eine flache Container-Liste statt „mailcow 18/18“, „Backup von VM 104 fehlt“ ohne Storage, Größe, Job, letzten Fehler
und PBS-Verify, ZFS nur `ONLINE`/`DEGRADED` ohne Scrub-Datum und vdev-Fehler. Der nächste Schritt ist dann immer
derselbe: per SSH auf die Box und nachsehen. Die Daten liegen meist schon in Ausgaben, die der Agent heute liest und
auf eine Zahl verdichtet.

## Ziel & Nicht-Ziele

**Ziel:** jeder dieser Checks trägt die Details, die die nächste Frage beantworten, in seinen `details`; die
Desktop-Sektionen und Quer-Ansichten zeigen sie. Im Einzelnen:

1. **Systemzustand:** Namen der ausstehenden Sicherheitsupdates (apt, dnf, FreeBSD `pkg audit`), Pakete hinter
   „Neustart nötig“ (Debian, RPM), Name und PID des Prozesses, den der OOM-Killer seit dem letzten Bericht getötet hat
   (Linux).
2. **Ressourcen:** die fünf Prozesse mit der höchsten CPU- bzw. RAM-Last, nur wenn die Last hoch ist (Kevins Zeile:
   „nur bei Warnung“; Auslöser siehe Offene Fragen).
3. **Docker:** Container nach Compose-Projekt gruppiert („mailcow 18/18“), je Container Health, veröffentlichte Ports
   und Laufzeit.
4. **Proxmox-Backup:** je Gast Storage und Größe des neuesten Backups, der Backup-Job, der ihn abdeckt, der letzte
   Fehler eines vzdump-Laufs, bei PBS der Verify-Status.
5. **ZFS:** letzter Scrub (Datum, Fehler), Lese-/Schreib-/Prüfsummenfehler je vdev, Fragmentierung je Pool.

**Nicht-Ziele (YAGNI):**
- Kein neuer Status, keine neue Meldung, keine neue Metrik, keine neue Alert-Bedingung: Status und Meldung jedes Checks
  bleiben bitgleich, die Details kommen nur dazu (wie `details.cert` in `arch-monitoring-ui` T2). Ein „PBS-Verify
  fehlgeschlagen → Warnung“ wäre eine eigene Roadmap-Zeile.
- Keine Details in Mail oder Webhook; sie erscheinen nur im Desktop.
- Keine Kommandozeilen von Prozessen (nur `comm`), keine ganzen Ausgaben, keine Logzeilen (das ist R-1226).
- Kein neuer Check-Typ, keine Konfig-Option, keine Änderung an `apps/monitoring/app/schemas.py`, am OpenAPI-Snapshot
  oder an `apps/desktop/ui/src/lib/api/types.ts`.
- Keine Proxmox-Aufrufe, die schreiben oder Storages aktivieren (Konzept §3.6), keine LAN-Sonde.
- Windows: Systemzustand gibt es dort nicht; die Top-5-Prozesse kommen auf allen drei Plattformen (gopsutil).

## Betroffene Komponenten & Dateien

**Agent (`apps/agent/internal/`):**
- `monitor/updates_linux.go` — `countAptSecurity` (`:75`) zählt die `Inst`-Zeilen aus einer Security-Quelle,
  `countDNFSecurity` (`:99`) zählt eindeutige Namen: beide liefern künftig die Namen mit (sortiert, gekappt).
- `monitor/pkgaudit.go` — `pkgSecurityUpdates` (`:105`): die Paketnamen aus `pkg audit -q` ebenso.
- `monitor/reportstate.go` — `updatesCheck` (`:66`, `CheckedUnix`, `Security`) bekommt die Namen, damit die
  stündliche Zählung sie bis zum nächsten Lauf weitergibt; `backupIndexCheck` (`:74`) bekommt die Backup-Details je
  Gast und den letzten vzdump-Fehler (Cache wie heute `proxmoxBackupsEvery`, 30 min, `plugins.go:324`).
- `monitor/system_linux.go` — Reboot-Pakete neben `rebootRequiredPath` (`:28`, Debian
  `/var/run/reboot-required.pkgs`) und aus der Ausgabe von `needs-restarting -r` (`:135`); OOM-Prozess, wenn der
  Zähler (`readOOMKill`, `:71`) seit dem letzten Bericht gestiegen ist.
- `monitor/plugins.go` — `collectDocker` (`:58`) nimmt Compose-Labels, Ports und Startzeit aus dem `docker inspect`,
  das es schon fährt; `collectProxmox` (`:246`) und `buildBackupIndex` (`:336`) die Details aus den
  Content-Einträgen, dazu Job und letzter Fehler; `collectZFS` (`:412`) und `parseZpoolList` (`:459`) Fragmentierung
  und `zpool status -j`.
- `monitor/collector.go` und eine neue Datei `monitor/processes.go` (SPDX) für die Top-5-Prozesse.
- `allowlist/allowlist.go` — neue Einträge: `journalctl` für die OOM-Zeile, `zpool status -j`, `pvesh` für
  `/cluster/backup`, die Task-Liste und das Log eines vzdump-Tasks (neue Klasse `upid`); `zpool list` um
  `fragmentation`. Tests in `allowlist/allowlist_test.go` (Positiv- und Fallen-Fälle); die Collector-Stubs prüfen jeden
  ihrer Aufrufe ohnehin gegen die Liste. `monitor/allowlist_test.go` ändert dieser Zug nicht (ändert
  `feature/kern-monitoring-22`).

**Monitoring (`apps/monitoring/app/checkers/`):** reicht die Felder gekappt in `details` durch, ohne Schema- oder
Snapshot-Änderung: `system.py` (`SystemStateChecker`, `:40`), `agent.py` (`_resources_details`, `:474`),
`plugins.py` (`ProxmoxBackupChecker` `:47`, `ZfsHealthChecker` `:172`, `DockerHealthChecker` `:339`). Kappung mit
den vorhandenen Helfern `cap_agent_text` (`agent.py:74`), `join_capped` (`:94`), `capped_objects` (`:133`),
`_MAX_REPORT_ENTRIES` (`:130`). Tests: `test_system_state_checker.py`, `test_agent_resources_checker.py`,
`test_plugin_checkers.py`.

**Desktop-UI (`apps/desktop/ui/src/`):** `lib/models/checkDetails.ts` (Leser `resourceDetails` `:78`,
`containerDetails` `:135`, `zfsDetails` `:159`; die neuen Felder als lokale Erweiterungstypen, `lib/api/types.ts`
bleibt unberührt), Sektionen `components/monitoring/section/SecSystem.svelte`, `SecLive.svelte`, `SecDocker.svelte`,
`SecBackups.svelte`, `SecZfs.svelte`, Quer-Ansichten `components/monitoring/cross/UpdatesView.svelte`,
`BackupsView.svelte`, je mit ihrem `*.test.ts`; Texte DE+EN in `lib/i18n/dictionaries.ts`. UI nur aus Tokens und
Komponenten unter `components/ui/`.

**E2E:** `apps/desktop/e2e/test/specs/monitoring-server-page.live.js` und `scripts/tests/desktop_e2e_monitoring.sh`.

## Datenmodell / API / Migrationen

Keine Migration, keine Änderung an einem API-Schema. Der Agent-Bericht bekommt nur zusätzliche Felder in Blöcken, die
der Monitoring-Dienst frei liest (alte Agenten lassen sie weg, alte Monitoring-Dienste ignorieren sie). Die `details`
eines Check-Ergebnisses sind freies JSON; der Desktop liest die neuen Felder optional und zeigt ohne sie den heutigen
Stand. Der Agent-Plan (`/agent/{id}/plan`) bleibt unverändert, solange die Frage zu den Top-5-Prozessen mit
Empfehlung A beantwortet wird.

Feld-Freigabe (Konzept §3.13): der Agent schickt nur die genannten Felder, nie eine Ausgabe im Ganzen. Namen,
Fehlertexte und Labels werden auf dem Agenten und im Monitoring gekappt (Zeichen und Anzahl); Prozesse nur mit `comm`
und PID, ein vzdump-Fehler nur als die Zeile `ERROR: Backup of VM <id> failed - <text>` (Text gekappt).

## Externe Integrationen

Alle Formate unten sind **nicht verifiziert**, bis die jeweilige Task sie in der Primärquelle nachgelesen hat; die
Task nennt die Quelle im Commit-Body.

- **apt / dnf / pkg:** `apt-get -s dist-upgrade` (`Inst <paket> …`-Zeilen), `dnf updateinfo list --security`
  (drei Spalten, Name-Version-Release in der dritten), `pkg audit -q` (ein `<name>-<version>` je Zeile) — die Parser
  bestehen schon, sie geben künftig die Namen zurück.
- **Reboot-Pakete:** Debian `/var/run/reboot-required.pkgs` (ein Paket je Zeile, von `update-notifier-common`
  geschrieben); RPM `needs-restarting -r` — Zeilen `  * <paket>` vor dem Hinweis „Reboot is required“, Format im
  Quelltext von `dnf-plugins-core` (`needs_restarting.py`) prüfen.
- **OOM:** Kernel-Meldung aus `mm/oom_kill.c` (`__oom_kill_process`, `pr_err`): „Out of memory: Killed process <pid>
  (<comm>) …“ bzw. „Memory cgroup out of memory: Killed process …“. Das ist keine dokumentierte Schnittstelle: nur
  `Killed process <pid> (<comm>)` wird gelesen, alles andere verworfen. Lesen über `journalctl --dmesg` mit festem
  Fenster seit dem letzten Bericht (journalctl(1): `--dmesg`, `--since`, `--output`).
- **Docker:** Engine-API ContainerInspect (`Config.Labels` mit `com.docker.compose.project` und
  `com.docker.compose.service`, `NetworkSettings.Ports`, `State.StartedAt`).
  https://docs.docker.com/reference/api/engine/
- **Proxmox VE API** (https://pve.proxmox.com/pve-docs/api-viewer/): `GET /nodes/{node}/storage/{storage}/content`
  (Felder `size`, `ctime`, `vmid`, `verification.state`), `GET /cluster/backup` (Jobs), `GET /nodes/{node}/tasks`
  (`typefilter=vzdump`, `errors`, `limit`), `GET /nodes/{node}/tasks/{upid}/log`. Eine echte PVE-Box gibt es im Pool
  nicht (Kevins Entscheidung 7: ein Nachstellen auf einer Test-VM startet nur auf sein Wort): Unit-Fixtures aus der
  dokumentierten Form, im PR als „nicht auf echter PVE verifiziert“ genannt.
- **OpenZFS:** `zpool status -j` (ab OpenZFS 2.3; zpool-status(8), JSON-Form mit `pools`, `vdevs`, `scan_stats`) und
  die Eigenschaft `fragmentation` (zpoolprops(7)). Kennt `zpool` kein `-j` (OpenZFS ≤ 2.2), bleibt es bei den
  heutigen Details.
- **Prozesse:** gopsutil/v4 `process` (schon Abhängigkeit, `apps/agent/go.mod:8`).

## Trade-offs & Alternativen

- **Namen statt neuer Befehle:** Sicherheitsupdates, Docker und Backup-Größe kommen aus Ausgaben, die der Agent heute
  schon liest; neue Aufrufe nur für OOM (nur nach einem Kill), ZFS-JSON, Backup-Jobs und vzdump-Fehler (im
  30-min-Cache). Alternative „eigene Detail-Collectors je Check“ kostet jede Runde und widerspricht „nie
  Dienst-Leistung kosten“.
- **OOM über `journalctl --dmesg` statt `/dev/kmsg`:** `/dev/kmsg` müsste der Agent selbst lesen und filtern (ganzer
  Ringpuffer), journalctl filtert nach Priorität und Zeit. Ohne systemd-journal (Container, FreeBSD) bleibt es beim
  Zähler.
- **Top-5 über zwei Stichproben im Abstand von ~1 s** statt Prozesszeiten im Report-Zustand: kein wachsender Zustand
  je PID, Kosten nur bei hoher Last. Empfehlung A in den Offenen Fragen hält den Agent-Plan unverändert.
- **Docker-Gruppierung im Desktop**, nicht im Monitoring: der Check bleibt eine Container-Liste; der Desktop gruppiert
  nach `compose_project`, Container ohne Label stehen unter „ohne Projekt“.

## Risiken & Rollback

- **Datenschutz:** Paket-, Prozess- und Containernamen sind Betriebsdaten, keine Geheimnisse; Fehlertexte von vzdump
  können Pfade enthalten. Kappung auf beiden Seiten, keine Ausgabe im Ganzen. Kein Feld landet in Mail oder Webhook.
- **Kosten auf dem Host:** jeder neue Aufruf mit festem Timeout über `runTimed`, OOM nur nach einem Kill, ZFS-JSON
  nur wo `zpool` schon läuft, Proxmox im bestehenden 30-min-Cache, Top-5 nur bei hoher Last.
- **Unbekannte Formate:** ein Parser, der nichts versteht, liefert keine Details statt eines Fehlers; Status und
  Meldung hängen nie an den neuen Feldern.
- **Rollback:** je Task ein Commit, alle Felder additiv; ein Revert lässt alte Berichte gültig.

## Doku-Impact

`docs/admin/monitoring.html` + `docs/en/admin/monitoring.html` (welche Details je Check erscheinen, Datenschutz-Satz
zur Feld-Freigabe), `docs/developer/monitoring.html` + EN (die neuen `details`-Felder je Check-Typ),
`docs/developer/agent.html` + EN (neue Allowlist-Aufrufe), `changelog.d/arch-monitoring-ui-2.md`.

## Screenshots

Kevin will vor dem Merge Screenshots (Entscheidung „Mockup“). Die Live-Spec bekommt einen zweiten Server mit einem
festen Fixture-Bericht (Docker mit Compose-Projekten, Proxmox-Backups, ZFS, Sicherheitsupdates, OOM, Top-5) und
speichert je neuer Detail-Ansicht ein Bild hell und dunkel unter `.ah-out/screenshots/`. Der Weg des Fixtures ist
Testcode; ein neuer Produktpfad dafür entsteht nicht.

## Offene Fragen

1. **Auslöser der Top-5-Prozesse (Kevin, sichtbares Verhalten) — T6 `[?]`.** Der Agent kennt die Schwellen der
   Ressourcen-Checks nicht; sie leben im Monitoring.
   - **A (Empfehlung):** der Agent sammelt die Liste, sobald CPU bzw. RAM die Standard-Warnschwelle von 80 % erreicht
     (`AgentResourcesChecker`, `apps/monitoring/app/checkers/agent.py:530`). Kein Vertragswechsel, baubar in diesem
     Zug. Folge: wer eigene Schwellen unter 80 % setzt, sieht bei einer Warnung zwischen seiner Schwelle und 80 %
     keine Liste; bei Schwellen über 80 % zeigt der Desktop die Liste nur, wenn der Check warnt.
   - **B:** die Schwellen gehen über den Agent-Plan (`build_plan`, `apps/monitoring/app/module_plan.py:27`,
     `AgentPlanOut` in `schemas.py`) an den Agenten. Genau, aber ein Vertragswechsel in Dateien, die
     `feature/arch-monitoring-module-2` ändert: Folgezug.
   Durchreichen im Monitoring (T7) und Anzeige im Desktop (T9) hängen nicht an der Antwort und werden gebaut. Ohne
   Antwort bis zum Abschluss: T6 `[~] verschoben in arch-monitoring-ui-3`, eine Roadmap-Zeile für den Auslöser.
