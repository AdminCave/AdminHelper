<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Agent: RPM-Upgrade, Provisionierung und Sync mit gesichertem Datenverzeichnis, Meldung im Ereignisprotokoll — Task-Ledger
Status: bereit · Branch: feature/agent-followups · Review: pro Task
Spec: keine eigene Datei (drei Folgezeilen des Agents, Roadmap R-0527, R-0556, R-0557)
Heavy: linux-full + windows — `apps/agent` (Provisionierung, frpc-Sync, Logger, Windows-Dienst) liegt auf dem Provisionierungs- und Sync-Pfad und läuft im Sammellauf über `main` (der Schritt `agent_monitoring` provisioniert echt, `/feature-build` §5); `windows` über den CI-Job „Go Agent (test, Windows)“ (der Pool hat keine Windows-Vorlage, Belege über Probe-Branches, unten); kein `scenario --rpm`: T1 ändert nur Scriptlets, und die Multibox-RPM-Strecke installiert im Container ohne systemd, sie sähe die Reihenfolge nicht; den Beleg liefert die rpm-Probe in T1
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Nach `dnf upgrade` laufen `adminhelper-agent.timer` und `frpc.service` weiter, wie nach `apt upgrade`.
(2) `provision` sichert das Datenverzeichnis, bevor es den Einmal-Token einlöst; scheitert das, bleibt der Token
gültig. (3) Der FRP-Sync ändert Dateien nur in einem Verzeichnis, das er im selben Lauf gesichert hat. (4) Kann der
Windows-Dienst sein Log-Verzeichnis nicht sichern, steht der Grund im Windows-Ereignisprotokoll statt nirgends.
Linux bleibt bis auf (1) und das `0700` aus (2)/(3) unverändert. Zeilenangaben: main@82e4a7b8.

Belege (offizielle Doku, 2026-10-21): Upgrade-Reihenfolge laut rpm-scriptlets(7)
(<https://rpm-software-management.github.io/rpm/man/rpm-scriptlets.7>): „%post of new“ … „%preun of old“ … „%postun
of old“ … „%posttrans of new“; `$1` ist „the number of installed instances of the package when the operation on the
package containing the executing script completes“, „1 on initial install, and 0 on final removal“. Die
Fedora-Packaging-Guidelines (docs.fedoraproject.org) ließen sich nicht abrufen (Bot-Schutz) — nicht gelesen; die
systemd-Makros (<https://github.com/systemd/systemd/blob/main/src/rpm/macros.systemd.in>) handeln in `%systemd_preun`
nur bei `$1 -eq 0` („Package removal, not upgrade“). Ereignisprotokoll: RegisterEventSource
(<https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-registereventsourcew>): „If the source name
cannot be found, the event logging service uses the Application log. Although events will be reported, the events
will not include descriptions …“; `golang.org/x/sys/windows/svc/eventlog` ist Teil von `golang.org/x/sys` v0.45.0
aus `apps/agent/go.mod` (keine neue Abhängigkeit): `Open`, `Warning`, `InstallAsEventCreate` („When EventCreate.exe
is used, eid must be between 1 and 1000“), `Remove`.

Windows-Belege: Die windows-getaggten Tests und der plattformneutrale Test aus T2 laufen unter Windows nur in der CI
(Job „Go Agent (test, Windows)“). Für T2–T5 schiebt die Session vor dem Review den Stand des Worktrees auf einen
Probe-Branch `ci-probe/agent-followups-t<n>` und startet `gh workflow run ci.yml --ref ci-probe/agent-followups-t<n>`;
„zuerst rot“ belegt ein zweiter Probe-Branch mit den Tests, aber ohne die Produktänderung. Lauf-IDs und Ergebnis
stehen im Commit-Body; die Probe-Branches löscht die Session danach (wie bei `agent-windows-datadir`).

### T1 — RPM: Timer und frpc laufen nach einem Upgrade weiter  [x]
Komponente: agent · Dateien: apps/agent/rpm/adminhelper-agent.spec, apps/agent/cmd/adminhelper-agent/packaging_rpm_test.go, CHANGELOG.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @e91ab8c6 2026-10-21T09:51:04+02:00
Review: approve (.ah-out/review/agent-followups/T1.verdict.json)
Änderung: Beim Upgrade läuft das `%preun` des alten Pakets nach dem `%post` des neuen. `%preun` (`adminhelper-agent.spec:79-86`) stoppt heute auch bei `$1 == 1` den Timer und `frpc.service` (`:81-82`), nachdem `%post` sie gestartet hat (`:70`, `:73`, `enable --now`); beide bleiben enabled, laufen aber bis zum nächsten Reboot nicht. Neu: `%preun` stoppt und deaktiviert nur bei `[ "$1" -eq 0 ]` (Deinstallation, wie `%systemd_preun`); das Aktivieren wandert aus `%post` in ein neues `%posttrans`, das nach `%preun` und `%postun` des alten Pakets läuft: `systemctl enable --now adminhelper-agent.timer`, und wenn `/etc/frp/frpc.toml` vorhanden ist, `systemctl enable frpc.service` und `systemctl restart frpc.service` (frpc läuft danach auf dem neuen Binary, wie beim deb über prerm und postinst). Das greift auch beim Upgrade von einem heute ausgelieferten Paket, dessen `%preun` weiter stoppt. Die Hinweiszeilen (`echo`) wandern mit; `%post` behält `daemon-reload` und das Aufräumen der alten Units. Keine `%systemd_*`-Makros: das RPM entsteht mit `rpmbuild` auf Ubuntu (`release.yml`), ob die Makros dort vorliegen, ist nicht verifiziert. Test `packaging_rpm_test.go` (neu, SPDX, `//go:build linux`): führt die Scriptlet-Abschnitte der Spec mit `/bin/sh` in der Reihenfolge aus rpm-scriptlets(7) aus (Upgrade: neues `%post` mit 2, altes `%preun` mit 1, altes `%postun` mit 1, neues `%posttrans` mit 0; ein fehlender Abschnitt ist leer), mit einem `systemctl`-Stub vorn im `PATH`, der je Unit enabled/active und die Aufrufe festhält, und mit `/etc/` im Scriptlet-Text auf ein Temp-Verzeichnis umgelenkt. Fälle: Upgrade vom bisherigen Paket (die Scriptlets von main@82e4a7b8 als Text im Test) und Upgrade auf dieselbe Fassung, jeweils mit `frpc.toml` und beiden Units vorher enabled und aktiv → danach beide enabled und aktiv, frpc nach dem alten `%preun` (neu) gestartet; Neuinstallation ohne `frpc.toml` → Timer enabled und aktiv, frpc unberührt; Deinstallation → beide gestoppt und deaktiviert. Zuerst rot: die beiden Upgrade-Fälle. Nach dem Fix fährt der builder die rpm-Probe aus `Beweis:` mit den Scriptlet-Abschnitten der geänderten Spec (bisheriges Paket → neues, neues → neues, Deinstallation) und nennt die `systemctl`-Aufrufe im Commit-Body.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestRPM
Doku: CHANGELOG.md (Fixed); das Soll steht schon in `docs/admin/agent-deployment.html:207` und `docs/en/admin/agent-deployment.html:206`
Beweis: rpm-Probe 2026-10-21 an main@82e4a7b8 (rockylinux:9, rpm 4.16.1.3, dnf 4.14.0; Paket nur aus den Scriptlet-Abschnitten `adminhelper-agent.spec:57-89`, `/usr/bin/systemctl` als Stub, der jeden Aufruf protokolliert, `/etc/frp/frpc.toml` vorhanden): `rpm -U` und `dnf upgrade` von 1.0 auf 2.0 rufen dreimal identisch `enable --now adminhelper-agent.timer`, `enable --now frpc.service` (neues `%post`) und danach `stop adminhelper-agent.timer`, `stop frpc.service` (altes `%preun`). Gegenprobe mit `%preun` nur bei `$1 -eq 0` und einem `%posttrans`: beim Upgrade vom alten Paket folgen `enable --now` und `restart` auf die `stop`-Aufrufe
Semantik: docs/admin/agent-deployment.html:207 „Bei jeder Installation und jedem Upgrade aktiviert das Paket adminhelper-agent.timer neu, frpc.service nur, wenn /etc/frp/frpc.toml vorhanden ist.“
Dedup-Key: bug:agent:adminhelper-agent.spec:preun-stops-after-upgrade
HEAD: 82e4a7b8

### T2 — provision: Datenverzeichnis vor dem Einlösen des Tokens sichern  [x]
Komponente: agent · Dateien: apps/agent/internal/provision/provision.go, apps/agent/internal/provision/provision_test.go, CHANGELOG.md, docs/developer/agent.html, docs/en/developer/agent.html
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @732a441f 2026-10-21T10:00:48+02:00
Review: approve (.ah-out/review/agent-followups/T2.verdict.json)
Änderung: `Run` löst den Einmal-Token in `callActivate` ein (`provision.go:102`), bevor eine Schreibstelle das Datenverzeichnis zum ersten Mal sichert (`enroll.LockIdentity` in `runEnrollment`, `provision.go:299`; `monitor.Init`, `monitor.go:59`; `frpc.WriteSyncConfig`, `apply.go:58`); scheitert die Sicherung dort, ist der Token verbraucht und `provision` bricht trotzdem ab. Neu sichert `Run` nach der Prüfung der Argumente und vor `callActivate` die Datenwurzel mit `config.EnsureDataDir(config.MonitorDir())` (Linux: `0700`, auch bei einer Provisionierung ohne Monitor; Windows: die Wurzel samt Baum); scheitert das, gibt `Run` einen Fehler zurück, der das Verzeichnis nennt und sagt, dass der Token nicht eingelöst wurde (englisch). Test in `provision_test.go` (plattformneutral, läuft auch im Windows-Job): `ADMINHELPER_MONITOR_DIR` zeigt unter eine reguläre Datei, ein httptest-Server zählt die Aufrufe von `/api/servers/<id>/provision/activate`; erwartet: Fehler mit dem Verzeichnis, null Aufrufe. Zuerst rot (heute ein Aufruf). Beleg Windows über den Probe-Branch (oben).
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestRunRedeemsNothing
Doku: CHANGELOG.md (Fixed) · docs/developer/agent.html:79 + docs/en/developer/agent.html:79 (`provision` sichert die Datenwurzel vor dem Einlösen des Tokens)
Beweis: Code-Lesung main@82e4a7b8 im Review des Branches `agent-windows-datadir` (2026-10-21): `provision.go:102` `callActivate` vor der ersten Sicherung; auf Windows nicht nachgestellt, der Test der Task zeigt die Reihenfolge
Dedup-Key: bug:agent:provision.go:token-before-secure
HEAD: 82e4a7b8

### T3 — frpc-Sync: Dateien nur in einem gesicherten Verzeichnis ändern  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/sync.go, apps/agent/internal/frpc/sync_flow_test.go, apps/agent/internal/frpc/sync_windows_test.go, CHANGELOG.md, docs/developer/agent.html, docs/en/developer/agent.html
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @dbaeb1b5 2026-10-21T10:21:34+02:00
Review: approve (.ah-out/review/agent-followups/T3.verdict.json)
Änderung: Ein Sync ändert Dateien unter `FrpDir()` per Pfad, ohne das Verzeichnis im selben Lauf zu sichern: `renewAdminAPI` (`sync.go:118`, `admin.conf`), `applyConfig` (`sync.go:150-202`: `frpc.toml.tmp`, `frpc.toml`, `.config-hash`, `.started-hash`) und `syncWithoutFrpConfig`/`stopFrpc` (`sync.go:299-325`, löschen `frpc.toml` und den Hash). Im Windows-Dienst sichert nur `logging.Init` beim Start die Datenwurzel; scheitert das, läuft der Dienst trotzdem weiter. Neu sichert `Sync` vor seiner ersten Änderung auf der Platte, Schreiben wie Löschen, das FRP-Verzeichnis mit `config.EnsureDataDir(config.FrpDir())` (unter Windows zuerst die Datenwurzel), über eine Naht `ensureDataDir` im Paket; scheitert das, gibt `Sync` einen Fehler zurück, der das Verzeichnis nennt, und schreibt, löscht, startet und stoppt nichts. Ein Lauf ohne Änderung (gleicher Hash, frpc läuft, Tunnel vorhanden; ohne FRP-Config weder `frpc.toml` noch Hash vorhanden) sichert nichts. Unter Linux heißt das `0700` für `/etc/frp`, wie bei der Provisionierung. Tests in `sync_flow_test.go` (plattformneutral, die Naht liefert einen Fehler): neue Config mit Tunneln; Null-Hash bei vorhandener `frpc.toml`; frpc hängt bei geändertem Hash (neuer Admin-Port) → jeweils Fehler mit dem Verzeichnis, Dateien unverändert, keine Dienstaktion; gleicher Hash → die Naht wird nicht aufgerufen. Zuerst rot: mit der Naht, ohne die Prüfung. `sync_windows_test.go` (neu, SPDX, windows-getaggt, Helfer `holdForeignChild` aus `apply_windows_test.go`): offene Datenwurzel mit einem offen gehaltenen fremden Kind → `Sync` mit neuer Config scheitert, `frpc.toml`, `frpc.toml.tmp` und `admin.conf` fehlen danach (zuerst rot auf dem Probe-Branch ohne die Prüfung); eine Log-Datei unter `logs`, die offen ist wie bei lumberjack (`os.OpenFile` mit `O_CREATE|O_WRONLY|O_APPEND`), hindert einen Sync mit neuer Config nicht.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestSync
Doku: CHANGELOG.md (Fixed) · docs/developer/agent.html:79 + docs/en/developer/agent.html:79 (der Sync ändert nur ein gesichertes Verzeichnis)
Beweis: Code-Lesung main@82e4a7b8 im Review des Branches `agent-windows-datadir` (2026-10-21): `applyConfig` und `renewAdminAPI` schreiben per Pfad ohne `EnsureDataDir` im selben Lauf, `logging.go:40` fällt bei einem Fehler still auf stdout zurück; auf Windows nicht nachgestellt, der Windows-Test der Task zeigt es
Dedup-Key: bug:agent:windows:service-unsecured-root-silent
HEAD: 82e4a7b8

### T4 — Windows-Dienst: ein nicht gesichertes Log-Verzeichnis im Ereignisprotokoll melden  [x]
Komponente: agent · Dateien: apps/agent/internal/logging/logging.go, apps/agent/internal/logging/eventlog_windows.go, apps/agent/internal/logging/eventlog_linux.go, apps/agent/internal/logging/logging_test.go, apps/agent/internal/logging/logging_windows_test.go, CHANGELOG.md, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/developer/agent.html, docs/en/developer/agent.html
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @d465bbb0 2026-10-21T10:40:03+02:00
Review: approve (.ah-out/review/agent-followups/T4.verdict.json)
Änderung: Scheitert `config.EnsureLogDir`, loggt `logging.Init` (`logging.go:38-50`) heute nur auf stdout, ohne Hinweis (Kevin 2026-10-20, für Aufrufe ohne Administratorrechte); unter dem Dienststeuerungs-Manager geht stdout ins Leere, Grund und Folgen (T3: der Sync ändert nichts) bleiben unsichtbar. Neu (Kanal: Kevins Wahl, gebaut ist die Empfehlung): läuft der Agent als Windows-Dienst (`svc.IsWindowsService`), schreibt `Init` in diesem Fall genau einen Eintrag „Warnung“ ins Windows-Ereignisprotokoll (Protokoll Anwendung, Quelle `AdminHelper-Agent`, `golang.org/x/sys/windows/svc/eventlog`, Event-ID fest zwischen 1 und 1000) mit dem Log-Verzeichnis, dem Grund und der Folge (bis zum Neustart des Dienstes nur stdout; der FRP-Sync ändert nichts, solange sich das Datenverzeichnis nicht sichern lässt). Sonst bleibt alles wie heute: kein weiterer Eintrag, interaktive Aufrufe ohne Hinweis, Linux unverändert; scheitert das Ereignisprotokoll selbst, bleibt es beim stdout-Rückfall. Nähte `ensureLogDir` und eine Meldestelle für den Dienst (Windows: Ereignisprotokoll, nur als Dienst; Linux: keine, `eventlog_linux.go`); neue Dateien mit SPDX. Tests: `logging_test.go` (plattformneutral, Nähte): `EnsureLogDir` scheitert und eine Meldestelle ist da → genau eine Meldung mit Verzeichnis und Grund; gelingt es, oder fehlt die Meldestelle (interaktiv) → keine. `logging_windows_test.go`: als Dienst (Naht) mit offen gehaltenem fremdem Kind in der Datenwurzel und einer Testquelle mit eindeutigem Namen schreibt `Init` einen Eintrag, den `wevtutil qe Application /q:"*[System[Provider[@Name='<quelle>']]]" /rd:true /c:5 /f:xml` mit dem Grund in den EventData zurückgibt (die Darstellung ohne registrierte Quelle ist nicht verifiziert, daher XML). `TestInitLogsToStdoutOnlyWhenTheLogDirCannotBeSecured` bleibt grün (interaktiv still), nur sein Kommentar wird nachgezogen. Zuerst rot: der plattformneutrale Test mit den Nähten, ohne die Meldung; der Windows-Test auf dem Probe-Branch ohne die Meldung.
Verify: bash scripts/dev/verify.sh agent --strict -- -run TestInit
Doku: CHANGELOG.md (Changed) · docs/admin/agent-deployment.html (Abschnitt Logs, :197) + docs/en/admin/agent-deployment.html (:196): Windows-Dienst ohne gesichertes Log-Verzeichnis → Ereignisanzeige, Windows-Protokolle → Anwendung, Quelle `AdminHelper-Agent` · docs/developer/agent.html:80 + docs/en/developer/agent.html:80 („ohne Hinweis“ gilt nur noch für interaktive Aufrufe)
Beweis: Hinweis aus dem Review des Branches `agent-windows-datadir` (2026-10-20/21) und Code-Lesung main@82e4a7b8: `logging.go:40` wählt bei einem Fehler von `EnsureLogDir` still `os.Stdout`; unter dem Dienst ist stdout nicht sichtbar
Dedup-Key: bug:agent:windows:service-unsecured-root-silent
HEAD: 82e4a7b8

### T5 — `service install` registriert die Ereignisquelle, `service uninstall` entfernt sie  [x]
Komponente: agent · Dateien: apps/agent/internal/service/service_windows.go, apps/agent/internal/service/service_windows_test.go, CHANGELOG.md, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @88ed0fa5 2026-10-21T10:51:37+02:00
Review: approve (.ah-out/review/agent-followups/T5.verdict.json)
Änderung: Ohne registrierte Quelle schreibt Windows den Eintrag aus T4 ins Anwendungsprotokoll, aber ohne Beschreibung (RegisterEventSource, oben). `Install` (`service_windows.go:21`) registriert nach `sc create` die Quelle `AdminHelper-Agent` mit `eventlog.InstallAsEventCreate` (Fehler, Warnung, Information); eine schon vorhandene Quelle ist kein Fehler, jeder andere Fehler eine WARNUNG wie bei `sc failure`. `Uninstall` (`:77`) entfernt sie nach `sc delete` mit `eventlog.Remove`; eine fehlende Quelle ist kein Fehler. Den Quellnamen teilen sich T4 und der Dienst als eine Konstante. Test windows-getaggt (`service_windows_test.go`, neu, SPDX) über die beiden Helfer mit einem eindeutigen Testnamen: zweimal registrieren ohne Fehler, der Schlüssel `HKLM\SYSTEM\CurrentControlSet\Services\EventLog\Application\<name>` ist da; zweimal entfernen ohne Fehler, der Schlüssel ist weg. `Install` und `Uninstall` selbst (sc.exe) bleiben wie bisher ohne Test (Plattform-I/O). Entfällt (`[~]`), wenn Kevin die Variante ohne Registrierung wählt.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: docs/admin/agent-deployment.html:140 + docs/en/admin/agent-deployment.html:140 (`service install` registriert die Ereignisquelle, `service uninstall` entfernt sie) · CHANGELOG.md (Eintrag aus T4 ergänzt)
Abhängt von: T4
