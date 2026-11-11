<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-freebsd-agent — Task-Ledger
Status: aktiv · Branch: feature/arch-freebsd-agent · Review: pro Task
Spec: docs/features/arch-freebsd-agent.md (Roadmap R-1247, R-1281)
Heavy: linux-full — Agent (Plattform-Umbenennungen, Paketierung), Gateway-Repo-Ebene und Monitoring-Annahme; dazu vor dem Merge der FreeBSD-Box-Lauf `bash scripts/tests/freebsd_box.sh` (T9) auf der Pool-VM
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@726c51d13`, am 2026-11-11 `origin/main@b9ed1782d` hineingemergt (`6cadad3d3`, samt FreeBSD-Anpassungen an `credentials` und `probe`; T12 prüft sie mit). Risikopfade: T2 (`apps/agent/internal/frpc/*`), T7 (`apps/gateway/*`), T8
(`scripts/vm/*`), T10 (`.github/workflows/*`): `security` je Task. T7 erst nach dem Merge von PR #429
(`feature/arch-ca-trust-generation` ändert `nginx.conf` und `test_gateway_container.py` in anderen Abschnitten) und
einem Merge von `origin/main` in diesen Branch. T8 ändert Harness-Pfade unter `scripts/vm/` auf Kevins Wort aus der
Roadmap-Zeile (Vorlage FreeBSD 15.1 im Pool, Bake erlaubt 2026-11-09); `run.sh` und `heavy.sh` bleiben unberührt.
T10 ändert Workflows: der PR ist ein Kevin-Merge (CLAUDE.md §2).

Der Cross-Build-Wächter `crossbuild_test.go` wächst mit: T1 nennt die Pakete, die nach T1 für FreeBSD bauen, T2 nimmt
`internal/frpc` dazu, T3 stellt auf `./...` um.

### T1 — Agent: Plattform-Basis FreeBSD (Pfade, Lock, Logging, Takt über cron.d) (R-1247)  [x]
Komponente: agent · Dateien: apps/agent/internal/config/paths_freebsd.go, apps/agent/internal/config/securedir_linux.go, apps/agent/internal/config/securedir_unix.go, apps/agent/internal/config/securedir_linux_test.go, apps/agent/internal/config/securedir_unix_test.go, apps/agent/internal/enroll/lock_linux.go, apps/agent/internal/enroll/lock_unix.go, apps/agent/internal/logging/eventlog_linux.go, apps/agent/internal/logging/eventlog_unix.go, apps/agent/internal/logging/logging_linux_test.go, apps/agent/internal/logging/logging_unix_test.go, apps/agent/internal/service/service_freebsd.go, apps/agent/internal/service/cronentry.go, apps/agent/internal/service/cronentry_test.go, apps/agent/cmd/adminhelper-agent/crossbuild_test.go, apps/agent/Makefile
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @8ce226768 2026-11-09T16:52:12+01:00
Review: approve (.ah-out/review/arch-freebsd-agent/T1.verdict.json)
Änderung: `paths_freebsd.go` mit den Pfaden der Spec und denselben `ADMINHELPER_*_DIR`-Overrides wie Linux. securedir, lock und eventlog samt ihren Linux-Tests werden per `git mv` zu `_unix`-Dateien mit `//go:build linux || freebsd`, der Inhalt bleibt. `service_freebsd.go`: `EnableTimer` schreibt `/usr/local/etc/cron.d/adminhelper` (Zeile aus `cronentry.go`, ohne Build-Tag: alle 5 Minuten, `nice -n 19`, `timeout 270` wie `TimeoutStartSec=270`, `run --once`, Ausgabe verworfen, das Log schreibt der Agent selbst), `Install` kopiert das Binary nach `/usr/local/bin/adminhelper-agent` (wie Linux) und ruft `EnableTimer`, `Uninstall` löscht die Datei. `cronentry_test.go` prüft die Zeile (fünf Zeitfelder, Benutzer `root`, absoluter Pfad, Deckel < 300 s). `crossbuild_test.go` (neu, SPDX) fährt `go vet` mit `GOOS=freebsd GOARCH=amd64 CGO_ENABLED=0` über die Pakete `config`, `enroll`, `logging`, `service`. Makefile-Ziel `build-freebsd`. 16 Pfade: vier Umbenennungen sind acht davon.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T11
Test-Löschung: apps/agent/internal/config/securedir_linux_test.go::* — per git mv umbenannt nach securedir_unix_test.go (Build-Tag linux || freebsd), Tests unverändert; apps/agent/internal/logging/logging_linux_test.go::* — per git mv umbenannt nach logging_unix_test.go (Build-Tag linux || freebsd), Tests unverändert

### T2 — Agent: frpc als rc.d-Dienst unter FreeBSD (R-1247)  [x]
Komponente: agent · Dateien: apps/agent/internal/frpc/platform_freebsd.go, apps/agent/internal/frpc/sockstat.go, apps/agent/internal/frpc/sockstat_test.go, apps/agent/freebsd/adminhelper_frpc, apps/agent/cmd/adminhelper-agent/crossbuild_test.go, apps/agent/internal/frpc/platform_freebsd_test.go, apps/agent/internal/service/service_freebsd_test.go, apps/agent/internal/frpc/rcd.go, apps/agent/internal/frpc/rcscript_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @46679688d 2026-11-09T17:26:15+01:00
Review: approve (.ah-out/review/arch-freebsd-agent/T2.verdict.json)
Änderung: `platform_freebsd.go` setzt die Plattform-Funktionen aus `platform_linux.go` um: `service adminhelper_frpc start|stop|restart|status`, aktivieren über `sysrc adminhelper_frpc_enable=YES`, Reload über `/usr/local/libexec/adminhelper/frpc reload -c <FrpDir>/frpc.toml`. `frpcOwnsAdminPort` liest `sockstat -4 -l -q -n -P tcp -p <port>`; der Parser `sockstat.go` (ohne Build-Tag, SPDX) verlangt Benutzer `root`, Kommando `frpc` und `127.0.0.1:<port>`, Tests mit echten Ausgaben und Gegenfällen (anderer Benutzer, anderes Kommando, `*:<port>`, leere Ausgabe). `apps/agent/freebsd/adminhelper_frpc` (rc.subr, SPDX): `daemon -r -R 5 -P <pidfile> -S -T adminhelper-frpc` um frpc mit `-c <FrpDir>/frpc.toml`, `pidfile` auf den Supervisor, `adminhelper_frpc_enable` Standard `NO`; `rcscript_test.go` prüft diese Bausteine im Text. `crossbuild_test.go` nimmt `internal/frpc` auf.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T11
Abhängt von: T1

### T3 — Agent: Monitoring-Sammler unter FreeBSD (Virtualisierung, Dienste, Dateisysteme) (R-1247)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/hostfacts.go, apps/agent/internal/monitor/hostfacts_test.go, apps/agent/internal/monitor/virt_freebsd.go, apps/agent/internal/monitor/virt_other.go, apps/agent/internal/monitor/services_freebsd.go, apps/agent/internal/monitor/rcservice.go, apps/agent/internal/monitor/rcservice_test.go, apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/collector_test.go, apps/agent/cmd/adminhelper-agent/crossbuild_test.go, apps/agent/internal/monitor/services.go, apps/agent/internal/monitor/services_linux.go, apps/agent/internal/monitor/virt_freebsd_test.go, apps/agent/internal/monitor/services_freebsd_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @cb3e739d6 2026-11-09T17:51:44+01:00
Review: approve (.ah-out/review/arch-freebsd-agent/T3.verdict.json)
Änderung: Die Virtualisierung hängt an einer Plattform-Funktion: unter FreeBSD `virt_freebsd.go` mit `unix.SysctlUint32("security.jail.jailed")` und `unix.Sysctl("kern.vm_guest")`, ohne Prozess (jailed → `jail`/`guest`, vm_guest ≠ `none` → Wert/`guest`, sonst leer); die Abbildung als reine Funktion in `hostfacts.go`, getestet unter Linux; `virt_other.go` behält `host.Virtualization` für alle anderen Systeme. `services_freebsd.go`: `collectServiceHealth` und `collectWatchedServices` über `service -e` und je Dienst `service <name> status` mit dem bestehenden Zeitdeckel; der Parser `rcservice.go` (ohne Build-Tag, SPDX) bildet „is running as pid“ → `active`, „is not running“ → `inactive` ab und lässt alles andere aus. `skipFSTypes` um `devfs`, `fdescfs`, `procfs`, `linprocfs`, `linsysfs`, `nullfs`. `crossbuild_test.go` stellt auf das ganze Modul (`./...`) um. Vierzehn Dateien (Entscheidung T3): Hook, Plattformseiten, Parser und ihre Tests gehören zu einem Sammler-Satz.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T11
Abhängt von: T2

### T4 — Agent: system_state unter FreeBSD (Neustart nötig, Sicherheitslücken) (R-1247)  [x]
Komponente: agent · Dateien: apps/agent/internal/monitor/system_freebsd.go, apps/agent/internal/monitor/system_other.go, apps/agent/internal/monitor/pkgaudit.go, apps/agent/internal/monitor/pkgaudit_test.go, apps/agent/internal/monitor/system_freebsd_test.go, apps/agent/internal/monitor/updates.go, apps/agent/internal/monitor/updates_linux.go, apps/agent/internal/monitor/reportstate.go, apps/agent/internal/monitor/hostfacts.go, apps/agent/internal/monitor/hostfacts_test.go, apps/agent/internal/monitor/system_linux.go, apps/agent/internal/monitor/system_linux_test.go, apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_agent_resources_checker.py
Evidenz: run.sh[quick] agent monitoring: 6 passed, 0 failed, 12 skipped @a3ff5d021 2026-11-09T18:24:28+01:00
Review: approve (.ah-out/review/arch-freebsd-agent/T4.verdict.json)
Änderung: `system_other.go` wird `//go:build !linux && !freebsd`. `system_freebsd.go`: `reboot_required` = `freebsd-version -k` ≠ `freebsd-version -r`; `security_updates` stündlich wie unter Linux (Zustand in `reportState`, `updatesCheckEvery`, Zeitdeckel): `pkg audit -q` (Zahl der Pakete) plus `pkg audit -q FreeBSD-<-u>` und `FreeBSD-kernel-<-k>` gegen die lokale `vuln.xml`, nie mit `-F`. Fehlt die Datenbank, fällt das Feld weg. `pkgaudit.go` (ohne Build-Tag, SPDX) parst die Ausgaben und formt die Versionen wie `405.pkg-base-audit` um (`15.1-RELEASE-p2` → `15.1_2`); Tests unter Linux mit Fixtures, `system_freebsd_test.go` stubbt die Aufrufe und läuft im Box-Lauf (T9). Vierzehn Dateien (Entscheidung T4): die gemeinsamen Teile der stündlichen Zählung wandern nach `updates.go`, `inContainer` und `containerSystems` (mit `jail`) nach `hostfacts.go`, und das Monitoring zählt das Jail als Container (`agent.py`, Paritätstest).
Verify: bash scripts/dev/verify.sh agent monitoring --strict
Doku: → T11
Abhängt von: T3

### T5 — Monitoring: Betriebssystem `freebsd` annehmen (R-1247)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/template_suggestions.py, apps/monitoring/tests/test_template_suggestions.py, apps/monitoring/tests/test_agent_report.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @263766a7e 2026-11-09T18:27:49+01:00
Review: approve (.ah-out/review/arch-freebsd-agent/T5.verdict.json)
Änderung: `_OSES` (`template_suggestions.py:34`) nimmt `freebsd` auf, ohne Vorlagen-Vorschlag wie `darwin`. Test: ein Bericht mit `os: freebsd` wird gespeichert und schlägt keine Vorlage vor (Fall neben `("darwin", (), [])`, Z. 160). `test_agent_report.py::test_report_drops_unknown_os_and_subsystems` nahm `freebsd` als unbekanntes OS und nimmt jetzt `openbsd`; ein Bericht eines FreeBSD-Jails wird mit `os`, Plattform und `jail`/`guest` gespeichert.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_template_suggestions.py tests/test_agent_report.py
Doku: → T11

### T6 — Agent: FreeBSD-Paket und signiertes pkg-Repo bauen (R-1247)  [x]
Komponente: agent · Dateien: apps/agent/build-pkg.sh, apps/agent/freebsd/post-install, apps/agent/freebsd/pre-deinstall, apps/agent/cmd/adminhelper-agent/packaging_pkg_test.go, apps/agent/Makefile, .gitignore
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @8a0435d15 2026-11-09T18:57:31+01:00
Review: approve (.ah-out/review/arch-freebsd-agent/T6.verdict.json)
Änderung: `build-pkg.sh` (SPDX) baut aus `bin/adminhelper-agent-freebsd` und dem frpc-Archiv je ABI (`FreeBSD:14:amd64`, `FreeBSD:15:amd64`) einen Stage-Baum (`/usr/local/bin/adminhelper-agent`, `/usr/local/libexec/adminhelper/frpc`, `/usr/local/etc/rc.d/adminhelper_frpc`), schreibt `+MANIFEST` (UCL: Name, Version aus `VERSION`, `abi`, `prefix`, Lizenz, Scripts) und ruft `pkg create`; mit `PKG_REPO_KEY` danach `pkg repo <dir> rsa:<key>` je ABI unter `<out>/freebsd/<ABI>/`. `post-install` und `pre-deinstall` (POSIX sh): Deinstallation stoppt `adminhelper_frpc`, löscht `/usr/local/etc/cron.d/adminhelper` und lässt Konfiguration und Identität stehen. `packaging_pkg_test.go` fährt die Scripts mit Stubs (`service`, `sysrc`) wie die RPM-Tests und prüft das erzeugte Manifest; echtes `pkg create`/`pkg repo`/`pkg install` prüfen T9 (FreeBSD) und T10 (Ubuntu-CI). Makefile-Ziel `pkg`.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T11
Abhängt von: T2

### T12 — Agent: FreeBSD-Aufrufe auf die Befehls-Freigabeliste (R-1281)  [x]
Komponente: agent · Dateien: apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go, apps/agent/internal/monitor/allowlist_test.go, apps/agent/internal/monitor/rcservice.go, apps/agent/internal/monitor/rcservice_test.go, apps/agent/internal/monitor/pkgaudit_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @6f4d02655 2026-11-11T08:47:10+01:00
Review: approve (.ah-out/review/arch-freebsd-agent/T12.verdict.json)
Beweis: feature/arch-freebsd-agent@6cadad3d3, die Stubs `fakeService` (`rcservice_test.go`) und `stubFreeBSDCalls` (`pkgaudit_test.go`) rufen `checkAllowed`; in `apps/agent`: `go test -count=1 -run 'TestRCServiceHealth$|TestFreebsdSystemState$' ./internal/monitor/` → dreimal identisch rot, 20× „call off the command allowlist“, u. a. `/usr/sbin/service ["-e"]`, `/usr/sbin/service ["cron" "status"]`, `/bin/freebsd-version ["-kru"]`, `/usr/local/sbin/pkg ["audit" "-q" "FreeBSD-15.0_3" "FreeBSD-kernel-15.0_3"]`
Orakel: contract — die Freigabeliste ist der Vertrag, jeder Aufruf eines Stubs muss sie bestehen
Dedup-Key: bug:agent:allowlist.go:commandAllowlist-freebsd
HEAD: 6cadad3d3
Änderung: `commands` nimmt `service` (`-e`, `<rcscript> status`), `freebsd-version` (`-kru`, `-u`) und `pkg` (`audit -q`, `audit -q <basepkg>...`) auf; neue Klassen `rcscript` (der Name, den service(8) nimmt, wie `reRCScriptName`) und `basepkg` (`FreeBSD-` oder `FreeBSD-kernel-` mit `<major>.<minor>` und optional `_<patch>`, wie `freebsdPkgName` sie bildet). `reRCScriptName` liest seine Klasse aus `argClasses` (wie `reUnitName`). Die Stubs prüfen jeden Aufruf (`checkAllowed`); `TestAllowlistTakesEveryCollectorCall` nimmt Formen, die die Stubs nicht zeigen (Release ohne Patch-Level, Jail mit einem Namen, Skriptname mit `_` und `.`), `TestAllowlistRefusesTheTraps` die Fallen (`pkg audit -F`, `pkg audit -q -F`, `pkg install`, `pkg audit -q nginx`, `service cron restart`, `service ../x status`, `service -e -v`, `freebsd-version -k`).
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T11

### T7 — Gateway: pkg-Repo unter `/freebsd/` auf der Repo-Ebene :8445 (R-1247)  [x]
Komponente: server · Dateien: apps/gateway/nginx.conf, apps/server/tests/test_gateway_container.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @e468d7352 2026-11-11T08:52:43+01:00
Review: approve (.ah-out/review/arch-freebsd-agent/T7.verdict.json)
Änderung: die Location der Repo-Ebene (`nginx.conf:220`, heute `^/(apt|rpm)/`) lässt `freebsd` zu; Dateitypen und Methoden wie bei apt/rpm, alles andere bleibt 404. Test im echten nginx-Container: `/freebsd/FreeBSD:15:amd64/meta.conf` liefert 200, `/freebsd/../etc` und eine fremde Wurzel liefern 404.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_gateway_container.py
Doku: → T11

### T8 — Test-Infrastruktur: VM-Vorlage FreeBSD 15.1 im Pool (R-1247)  [x]
Komponente: scripts · Dateien: scripts/vm/profiles.json, scripts/vm/vm.py, scripts/vm/tests/test_vm.py, scripts/vm/tests/conftest.py, scripts/vm/tests/README.md, scripts/vm/tests/fixtures/upload_post.json, scripts/vm/tests/fixtures/create_post.json, scripts/vm/tests/fixtures/task_imgcopy.json, scripts/vm/tests/fixtures/task_qmcreate.json
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @1a38dc2f3 2026-11-11T11:11:53+01:00
Review: approve (.ah-out/review/arch-freebsd-agent/T8.verdict.json)
Änderung: Profil `base-freebsd` (`template_tag` `ah-tpl-base-freebsd`) und Rolle `freebsd`; was `vm.py` für einen FreeBSD-Gast anpassen muss (IP über den qemu-guest-agent, `sudo` aus `/usr/local/bin`, kein `bash` im Basissystem), mit Tests gegen aufgezeichnete Proxmox-Antworten. Frage 1 (Kevin 2026-11-11): `vm.py` importiert selbst. Ein Import-Verb lädt das offizielle FreeBSD-15.1-Cloud-Image samt Prüfsumme auf einen Datei-Storage mit Inhalt `import` und legt daraus die Vorlage mit Tag an; das Token-Recht `Datastore.AllocateTemplate` auf diesem Storage setzt Kevin, `doctor` meldet, ob es fehlt. Die Handgriffe stehen in `DEVELOPMENT.md` (T11). Harness-Pfad auf Kevins Wort aus der Roadmap-Zeile.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: → T11

### T9 — Test: FreeBSD-Box-Lauf (Agent-Tests nativ, Paket, Dienst) (R-1247)  [ ]
Komponente: scripts · Dateien: scripts/tests/freebsd_box.sh, scripts/tests/box_freebsdbox.sh
Änderung: `freebsd_box.sh` (SPDX, Dev-Box): baut die Testbinaries mit `GOOS=freebsd go test -c -o <dir>/ ./...`, das Agent-Binary und das Paket (`build-pkg.sh`, Wegwerf-RSA-Schlüssel im eigenen Temp-Verzeichnis), least eine VM mit `vm.py clone --profile base-freebsd --role freebsd`, kopiert alles hinüber, fährt `box_freebsdbox.sh` und reapt am Ende (bei Fehler bleibt die VM stehen, wie die anderen Box-Läufe). `box_freebsdbox.sh` (POSIX sh, SPDX, auf der VM als root): alle Testbinaries; lokales Repo mit Signatur anlegen und `pkg install adminhelper-agent` daraus; `adminhelper-agent service install` schreibt die cron.d-Datei; `service adminhelper_frpc start` mit einer Wegwerf-`frpc.toml` und `status` meldet „is running“; `adminhelper-agent run --once` mit einem Monitor-Ziel ohne Gegenstelle läuft durch die Sammler (Report-JSON per `monitor show` o. ä., `host.os` = `freebsd`, `system_state` vorhanden); `pkg delete` räumt cron.d und Dienst. Ergebnis als `N passed, M failed` und Exit ≠ 0 bei Fail; fehlt die VM-Vorlage, endet der Lauf mit 75 (SKIP = rot).
Verify: bash scripts/dev/verify.sh scripts --strict -- box_scripts_guard_test
Doku: → T11
Abhängt von: T4, T6, T8

### T10 — CI und Release: pkg aus den Quellen, FreeBSD-Pakete und signiertes Repo (R-1247)  [~] (verschoben in ci-10 (R-1303): Kevin 2026-11-11 Frage 3, Workflows als eigene Zeile mit Kevin-Merge)
Komponente: scripts · Dateien: .github/workflows/ci.yml, .github/workflows/release.yml, apps/agent/freebsd/adminhelper-pkg.pub, apps/agent/build-repo.sh
Änderung: `ci.yml`: der Job `agent` baut zusätzlich `GOOS=freebsd`; ein neuer Job baut `pkg` aus `freebsd/pkg` (Tag und Commit gepinnt, Cache), fährt `build-pkg.sh` mit einem Wegwerf-Schlüssel für beide ABIs und prüft Katalog und Signatur. `release.yml`: dasselbe mit dem Secret, fail-closed, wenn der Public Key des Secrets nicht `adminhelper-pkg.pub` ist; der Teilbaum `freebsd/` geht in `adminhelper-agent-repo-<tag>.tar.gz` (`build-repo.sh` nimmt ihn auf, wenn er da ist). `install.sh` und `update.sh` bleiben unverändert (sie entpacken den ganzen Tarball). frp-Archiv `freebsd_amd64` aus derselben `FRP_VERSION`.
Verify: bash scripts/dev/verify.sh scripts --strict -- toolchain_lockstep_test harness_consistency_test
Doku: → T11
Abhängt von: T6

### T11 — Doku DE+EN und CHANGELOG (R-1247)  [ ]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, DEVELOPMENT.md, changelog.d/arch-freebsd-agent.md, docs/developer/monitoring.html, docs/en/developer/monitoring.html
Änderung: Agent-Verteilung: Abschnitt FreeBSD (Repo-Datei mit `${ABI}`, Schlüssel und Gateway-CA per `ENV`, `pkg install`, `provision`, Pfade, Dienst `adminhelper_frpc`, Takt über cron.d, Deinstallation). Monitoring: was FreeBSD meldet (`security_updates` aus pkg audit, nur ein RELEASE zählt die Basis, Aktualität der `vuln.xml` über periodic; `reboot_required`, Dienste aus `service -e` samt Einmal-Skripten, Jail/VM, ein Jail zählt als Container). Entwickler-Doku Agent und Monitoring: die Container-Liste nennt `jail` und verweist auf `hostfacts.go` statt `system_linux.go`; die `os`-Liste von `store_host_facts()` nennt `freebsd` ohne Standard-Template (`docs/developer/monitoring.html` Z. 238 f., DE+EN). Entwickler-Doku Agent: Plattformdateien, `_unix`-Konvention, Cross-Build-Wächter; die Befehls-Freigabeliste nennt rc.d-Skript und Basis-Paket unter den variablen Teilen (T12). Sensoren unter FreeBSD: Unit, Unix-Socket und Container-Ziel melden „nicht unterstützt“ (Merge `6cadad3d3`). Der CI/CD-Teil (pkg-Bau, Signatur) zieht mit R-1303 um. DEVELOPMENT.md: `make build-freebsd`, `make pkg`, die Vorlage, `freebsd_box.sh`. CHANGELOG-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- 2026-11-09 T2: Aktivieren über `service adminhelper_frpc enable` (rc.subr ruft `sysrc -s`) statt `sysrc` direkt, Start und Neustart mit `onestart`/`onerestart`, Stopp mit `faststop` vor `disable` — rc.subr lässt `start`/`restart` bei abgeschaltetem rcvar still mit Exit 0 aus, `stop` ohne laufenden Dienst endet mit 1 (rc.subr 14.3 gelesen).
- 2026-11-09 T2: `daemon -f -p <child-pidfile>` zusätzlich zu `-r -R 5 -P -S -T` — ohne `-f` hält der Supervisor stdout/stderr des Aufrufers offen; `frpcDown` gilt auch bei laufendem Supervisor, solange daemon die Kind-pidfile beim Warten auf den Neustart geleert hat (wie systemd im Restart-Wartezustand).
- 2026-11-09 T2: Besitz des Admin-Ports über UID `0` und die PID aus der Kind-pidfile statt über den Prozessnamen (den wählt, wer die Datei startet); sockstat mit `-n`, weil die numerische UID nicht an der passwd-Reihenfolge hängt (`toor`). Eine Zeile, die nicht der Spaltenform folgt, und Sockets ohne Prozess (`?`/`??`) verwerfen die ganze Ausgabe (Security-Review T2).
- 2026-11-09 T2: `service` und `sockstat` mit absolutem Pfad — unabhängig vom PATH eines Aufrufs aus der Shell (cron setzt `_PATH_DEFPATH`, das beide enthält).
- 2026-11-09 T2: Namen, die Go und rc-Skript teilen, in `internal/frpc/rcd.go` ohne Build-Tag und `rcscript_test.go` nach `internal/frpc/` statt `cmd/adminhelper-agent/` — so prüft die Linux-CI das Skript gegen die Go-Konstanten; die FreeBSD-Tests (`platform_freebsd_test.go`, `service_freebsd_test.go`) kompiliert der Cross-Vet hier, ausgeführt werden sie nativ in T9.
- 2026-11-09 T3: Einmal-Skripte nimmt `stop_cmd=":"` (auch `':'` und `:`, mit Kommentar dahinter) im Skript aus `enabled_inactive`; im Inventar bleiben sie `inactive`. rc.subr nennt sie „not running“, ihr Start läuft einmal und lässt keinen Prozess zurück (newsyslog, ntpdate, ddb; in releng/14.3 und 15.0 gelesen). Ein unlesbares Skript bleibt ein Kandidat.
- 2026-11-09 T3: Die Logik liegt ohne Build-Tag in `rcservice.go` und bekommt den Runner injiziert (Muster `scquery.go`), `services_freebsd.go` verdrahtet nur. So prüft die Linux-CI Parser und Abbruch. Native Tests (`services_freebsd_test.go`, `virt_freebsd_test.go`) für T9 kompiliert der Cross-Vet, sie laufen als root auf der Box. Dazu kommt `answered` von `services_linux.go` nach `services.go`: 14 statt 10 Dateien.
- 2026-11-09 T3: Antwortet ein `status`-Aufruf nicht (Zeitdeckel, Signal, nicht gestartet), bricht die Runde ab. Es bleiben eine Teilinventur plus `error` und keine `counts`; der Checker macht daraus `unknown`, fehlende Namen sind `nodata`, kein Fehlalarm. Ohne Abbruch würde jeder weitere Aufruf erneut `pluginTimeout` warten. Beobachtete Dienste: danach kein Aufruf mehr, alle weiteren gelten als nicht laufend.
- 2026-11-09 T3: Kosten je Lauf sind ein `service -e` plus ein `status` je aktiviertem Skript, beides nur lesend. `/usr/sbin/service` steht mit absolutem Pfad wie in T2. Ein Name, den service(8) nicht nimmt (`/`, `.`, `..`, führendes `-`), wird nicht gefragt.
- 2026-11-09 T3: Ein Jail geht vor die VM: Im Jail meldet die Virtualisierung `jail`/`guest`, auch wenn `kern.vm_guest` einen Hypervisor nennt, denn der Agent überwacht das Jail. `nullfs` fällt aus den Dateisystemen, weil seine Mounts (Jails) ein Verzeichnis eines anderen Dateisystems doppelt zeigen würden.
- 2026-11-09 T4: Kosten je Bericht ein `freebsd-version` (sh, sysctl, `what` über den Kernel), stündlich höchstens zwei `pkg audit -q`, die nur die lokale `vuln.xml` lesen; nie `-F`, die Datenbank holt periodic (`410.pkg-audit`). `pkg` mit absolutem Pfad `/usr/local/sbin/pkg` statt dem Bootstrap `/usr/sbin/pkg`, das zur Installation anbietet.
- 2026-11-09 T4: Ein Aufruf `freebsd-version -kru` mit strikt drei Zeilen (im Jail `-u`, eine Zeile); eine Zeile zu wenig ist unlesbar statt verschoben. Kernel aus `-k` (installiert) wie `405.pkg-base-audit`; dass er noch nicht läuft, meldet `reboot_required`.
- 2026-11-09 T4: Die Basis (`FreeBSD-`, `FreeBSD-kernel-`) zählt nur bei einem RELEASE mit oder ohne Patch-Level; STABLE, CURRENT, BETA und RC zählen nur Pakete, weil VuXML für sie keine Einträge hat.
- 2026-11-09 T4: `pkg audit` endet mit 1 bei Funden und bei Fehlern; mit `-q` druckt nur ein Fund eine Zeile, jeder Fehler endet vorher (pkg `src/audit.c`). Daher zählt nur Exit 1 mit Zeilen, Exit 1 ohne Zeilen ist ein Fehlschlag. Eine Zeile anderer Form macht die ganze Ausgabe unlesbar. Der Log nennt weder stderr noch Pfade.
- 2026-11-09 T4: Ein Jail zählt als Container in Agent (`containerSystems`) und Monitoring (`_CONTAINER_SYSTEMS`): es teilt Kernel, Last und Boot des Hosts, also kein `reboot_required` und keine Last-Bewertung. Die gemeinsamen Teile der stündlichen Zählung (`updatesDue`, `runTimedEnv`, Zeitdeckel) liegen ohne Build-Tag in `updates.go`, `inContainer` in `hostfacts.go`; daher vierzehn Dateien und `Verify: agent monitoring`.
- 2026-11-09 T6: Entfernen stoppt mit `faststop` (still, wenn frpc nicht läuft) und löscht den rcvar mit `service … delete` statt `disable`: wie `systemctl disable` bleibt keine Spur eines Skripts, das danach fehlt; `delete` scheitert ohne gesetzten rcvar, daher Ausgabe verworfen und Exit 0. Konfiguration und Identität unter `/usr/local/etc/adminhelper` bleiben wie unter Linux.
- 2026-11-09 T6: Ein Upgrade lässt Tunnel und Cron stehen; das neue `+POST_INSTALL` startet frpc nur neu, wenn `service adminhelper_frpc enabled` gilt (rc.subr meldet `restart` sonst mit „Cannot 'restart'“). Eine Neuinstallation startet nichts und schreibt keinen Cron-Eintrag, das tun der erste Tunnel und das Setup. Unter `pkg -r` (`PKG_ROOTDIR` ≠ `/`) oder `pkg -c` (`PKG_CHROOTED`) rufen beide Skripte kein `service`, denn Prozesse und service(8) sind die des Hosts; der Cron-Eintrag wird unter `${PKG_ROOTDIR%/}` gelöscht (pkg-script(5), libpkg `scripts.c`).
- 2026-11-09 T6: frpc kommt als Binary (`FRPC_BINARY`, Standard `./frpc-freebsd`) statt als Archiv, wie `./frpc` bei deb/rpm; `AGENT_BINARY` und `OUT_DIR` sind überschreibbar für T10. Die Ausgabe ist zustandslos: jeder Lauf löscht nur `$OUT_DIR/freebsd`, das T10 mit apt/rpm teilen kann, und erst nach allen Eingabeprüfungen, so bleibt bei einem Fehler das letzte Repo stehen.
- 2026-11-09 T6: `VERSION` nur `^[0-9][0-9A-Za-z.]*$` unter `LC_ALL=C`: pkg trennt Name und Version am letzten `-` und liest `_`/`,` als Port-Revision und Epoch. `make pkg` braucht daher wie `make deb` ein explizites `VERSION=`. Das Manifest ist JSON (gültiges UCL), so prüft der Test es mit `encoding/json`; die Pflichtfelder aus `pkg_is_valid`, `@owner root`/`@group wheel` in der plist, weil das Archiv sonst den Build-Benutzer trägt. `pkg repo` in der Positionsform `rsa:<key>`, die alte und neue pkg-Versionen nehmen. Keine pkg-Message (YAGNI).
- 2026-11-09 T6: Der Test leitet `/usr/local/etc/` in eine Fake-Wurzel und `/usr/sbin/service` auf einen Stub um und bricht ab, sobald eine Code-Zeile einen anderen absoluten Pfad nennt; ein Mutant, der `/usr/local/etc/adminhelper` löschte, lief sonst gegen den Host (Gegenprobe, harmlos, der Pfad fehlt auf der Dev-Box). `sysrc` braucht keinen Stub, die Skripte rufen es nicht. Echtes `pkg create`/`repo`/`install` prüfen T9 und T10 (nicht verifiziert bis dahin).
- 2026-11-11 T8: `vm.py import` legt die VM mit allen Laufwerken in einem `create`-Aufruf an (Platte und Seed per `import-from` vom Import-Storage, das cloud-init-Laufwerk `ide2` gleich dazu), weil das Token kein `VM.Config.CDROM` trägt, um ein Laufwerk später anzuhängen. Gastbenutzer ist `ciuser freebsd`, wie im Image vorgesehen.
- 2026-11-11 T8: Der Import-Boot liest einen eigenen config-2-Seed (OpenStack-Config-Drive, `genisoimage`/`mkisofs`/`xorrisofs`) statt PVEs Laufwerk: das trägt weder Pakete noch Befehle, und Snippets bräuchten Rechte auf einem Snippet-Storage. nuageinit sucht config-2 vor cidata, PVEs Laufwerk steht beim Import auf `nocloud` und bleibt ungelesen; vor `template` fliegt der Seed (`delete virtio1`), die Vorlage bekommt `citype configdrive2`, die Klone holen Schlüssel und Hostname daraus.
- 2026-11-11 T8: Die Benutzerliste des Seeds hat keinen Eintrag `default` (der legt `freebsd` mit bekanntem Passwort an); Passwörter von `freebsd` und `root` sind vor dem Template gesperrt (`pw usermod -h -`). `rc.conf.d/firstboot_pkg_upgrade` schaltet das Paket-Upgrade beim ersten Boot jedes Klons ab, Leases laufen auf den Paketen der Vorlage (`ciupgrade 0`). nuageinit warnt bei einem gescheiterten Paket nur, daher prüft `IMPORT_CHECK` Pakete, sudo, bash, sshd und Agent erneut.
- 2026-11-11 T8: `virtio_console` wird beim Boot geladen und der qemu-guest-agent eingeschaltet: ohne beide erfährt `wait` die Adresse nie. Kein eigener PATH für die Import-Skripte: sshd nimmt ihn aus login.conf, `/usr/local/bin` ist dabei (am Klon gesehen). Keine Plattenvergrößerung: das Image bringt 5 GiB mit, Vergrößern bräuchte `VM.Config.Disk` plus `growfs` (YAGNI bis T9 mehr braucht).
- 2026-11-11 T8: Feste Upload-Namen `ah-<profil>.qcow2` und `ah-<profil>-seed.raw`: ein zweiter Import überschreibt den ersten, löschen kann das Token nicht (`DELETE` auf Storage-Inhalt verlangt `Datastore.Allocate`, `Content.pm`). Der Upload streamt mit `Content-Length` (pveproxy nimmt keinen chunked Body) und sha256, die PVE vor dem Ablegen prüft; ein abgelehnter Upload wird nicht wiederholt (der Generator ist verbraucht).
- 2026-11-11 T8: Das Image liegt mit gepinnter sha256 in `profiles.json` und im Cache unter `~/.cache/adminhelper/vm-images`; jede Nutzung prüft die Kopie, ein Download, der nicht passt, beendet den Import, bevor etwas den Hypervisor erreicht. Die Import-VM hat die Form und Tags von `bake` (`role-bake`, Lane, TTL) und wird bei jedem Fehler bis zum Tag wieder entfernt.
- 2026-11-11 T8: `doctor` liest den Wert in `/access/permissions` als Propagate-Flag, nicht als „gewährt“: eine Gewährung nur auf dem Import-Storage (`propagate 0`) meldet 0 und zählt. Die Import-Rechte prüft `doctor` nur, wenn `AH_PVE_IMPORT_STORAGE` gesetzt ist; die Vorlage `base-freebsd` muss vor dem Merge stehen (T9).
