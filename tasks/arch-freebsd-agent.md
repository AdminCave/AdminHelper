<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-freebsd-agent — Task-Ledger
Status: geplant · Branch: feature/arch-freebsd-agent · Review: pro Task
Spec: docs/features/arch-freebsd-agent.md (Roadmap R-1247)
Heavy: linux-full — Agent (Plattform-Umbenennungen, Paketierung), Gateway-Repo-Ebene und Monitoring-Annahme; dazu vor dem Merge der FreeBSD-Box-Lauf `bash scripts/tests/freebsd_box.sh` (T9) auf der Pool-VM
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@726c51d13`. Risikopfade: T2 (`apps/agent/internal/frpc/*`), T7 (`apps/gateway/*`), T8
(`scripts/vm/*`), T10 (`.github/workflows/*`): `security` je Task. T7 erst nach dem Merge von PR #429
(`feature/arch-ca-trust-generation` ändert `nginx.conf` und `test_gateway_container.py` in anderen Abschnitten) und
einem Merge von `origin/main` in diesen Branch. T8 ändert Harness-Pfade unter `scripts/vm/` auf Kevins Wort aus der
Roadmap-Zeile (Vorlage FreeBSD 15.1 im Pool, Bake erlaubt 2026-11-09); `run.sh` und `heavy.sh` bleiben unberührt.
T10 ändert Workflows: der PR ist ein Kevin-Merge (CLAUDE.md §2).

Der Cross-Build-Wächter `crossbuild_test.go` wächst mit: T1 nennt die Pakete, die nach T1 für FreeBSD bauen, T2 nimmt
`internal/frpc` dazu, T3 stellt auf `./...` um.

### T1 — Agent: Plattform-Basis FreeBSD (Pfade, Lock, Logging, Takt über cron.d) (R-1247)  [ ]
Komponente: agent · Dateien: apps/agent/internal/config/paths_freebsd.go, apps/agent/internal/config/securedir_linux.go, apps/agent/internal/config/securedir_unix.go, apps/agent/internal/config/securedir_linux_test.go, apps/agent/internal/config/securedir_unix_test.go, apps/agent/internal/enroll/lock_linux.go, apps/agent/internal/enroll/lock_unix.go, apps/agent/internal/logging/eventlog_linux.go, apps/agent/internal/logging/eventlog_unix.go, apps/agent/internal/logging/logging_linux_test.go, apps/agent/internal/logging/logging_unix_test.go, apps/agent/internal/service/service_freebsd.go, apps/agent/internal/service/cronentry.go, apps/agent/internal/service/cronentry_test.go, apps/agent/cmd/adminhelper-agent/crossbuild_test.go, apps/agent/Makefile
Änderung: `paths_freebsd.go` mit den Pfaden der Spec und denselben `ADMINHELPER_*_DIR`-Overrides wie Linux. securedir, lock und eventlog samt ihren Linux-Tests werden per `git mv` zu `_unix`-Dateien mit `//go:build linux || freebsd`, der Inhalt bleibt. `service_freebsd.go`: `EnableTimer` schreibt `/usr/local/etc/cron.d/adminhelper` (Zeile aus `cronentry.go`, ohne Build-Tag: alle 5 Minuten, `nice -n 19`, `timeout 270` wie `TimeoutStartSec=270`, `run --once`, Ausgabe verworfen, das Log schreibt der Agent selbst), `Install` kopiert das Binary nach `/usr/local/bin/adminhelper-agent` (wie Linux) und ruft `EnableTimer`, `Uninstall` löscht die Datei. `cronentry_test.go` prüft die Zeile (fünf Zeitfelder, Benutzer `root`, absoluter Pfad, Deckel < 300 s). `crossbuild_test.go` (neu, SPDX) fährt `go vet` mit `GOOS=freebsd GOARCH=amd64 CGO_ENABLED=0` über die Pakete `config`, `enroll`, `logging`, `service`. Makefile-Ziel `build-freebsd`. 16 Pfade: vier Umbenennungen sind acht davon.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T11

### T2 — Agent: frpc als rc.d-Dienst unter FreeBSD (R-1247)  [ ]
Komponente: agent · Dateien: apps/agent/internal/frpc/platform_freebsd.go, apps/agent/internal/frpc/sockstat.go, apps/agent/internal/frpc/sockstat_test.go, apps/agent/freebsd/adminhelper_frpc, apps/agent/cmd/adminhelper-agent/rcscript_test.go, apps/agent/cmd/adminhelper-agent/crossbuild_test.go
Änderung: `platform_freebsd.go` setzt die Plattform-Funktionen aus `platform_linux.go` um: `service adminhelper_frpc start|stop|restart|status`, aktivieren über `sysrc adminhelper_frpc_enable=YES`, Reload über `/usr/local/libexec/adminhelper/frpc reload -c <FrpDir>/frpc.toml`. `frpcOwnsAdminPort` liest `sockstat -4 -l -q -n -P tcp -p <port>`; der Parser `sockstat.go` (ohne Build-Tag, SPDX) verlangt Benutzer `root`, Kommando `frpc` und `127.0.0.1:<port>`, Tests mit echten Ausgaben und Gegenfällen (anderer Benutzer, anderes Kommando, `*:<port>`, leere Ausgabe). `apps/agent/freebsd/adminhelper_frpc` (rc.subr, SPDX): `daemon -r -R 5 -P <pidfile> -S -T adminhelper-frpc` um frpc mit `-c <FrpDir>/frpc.toml`, `pidfile` auf den Supervisor, `adminhelper_frpc_enable` Standard `NO`; `rcscript_test.go` prüft diese Bausteine im Text. `crossbuild_test.go` nimmt `internal/frpc` auf.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T11
Abhängt von: T1

### T3 — Agent: Monitoring-Sammler unter FreeBSD (Virtualisierung, Dienste, Dateisysteme) (R-1247)  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/hostfacts.go, apps/agent/internal/monitor/hostfacts_test.go, apps/agent/internal/monitor/virt_freebsd.go, apps/agent/internal/monitor/virt_other.go, apps/agent/internal/monitor/services_freebsd.go, apps/agent/internal/monitor/rcservice.go, apps/agent/internal/monitor/rcservice_test.go, apps/agent/internal/monitor/collector.go, apps/agent/internal/monitor/collector_test.go, apps/agent/cmd/adminhelper-agent/crossbuild_test.go
Änderung: Die Virtualisierung hängt an einer Plattform-Funktion: unter FreeBSD `virt_freebsd.go` mit `unix.SysctlUint32("security.jail.jailed")` und `unix.Sysctl("kern.vm_guest")`, ohne Prozess (jailed → `jail`/`guest`, vm_guest ≠ `none` → Wert/`guest`, sonst leer); die Abbildung als reine Funktion in `hostfacts.go`, getestet unter Linux; `virt_other.go` behält `host.Virtualization` für alle anderen Systeme. `services_freebsd.go`: `collectServiceHealth` und `collectWatchedServices` über `service -e` und je Dienst `service <name> status` mit dem bestehenden Zeitdeckel; der Parser `rcservice.go` (ohne Build-Tag, SPDX) bildet „is running as pid“ → `active`, „is not running“ → `inactive` ab und lässt alles andere aus. `skipFSTypes` um `devfs`, `fdescfs`, `procfs`, `linprocfs`, `linsysfs`, `nullfs`. `crossbuild_test.go` stellt auf das ganze Modul (`./...`) um. Zehn Dateien: Hook, zwei Plattformseiten und Parser gehören zu einem Sammler-Satz.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T11
Abhängt von: T2

### T4 — Agent: system_state unter FreeBSD (Neustart nötig, Sicherheitslücken) (R-1247)  [ ]
Komponente: agent · Dateien: apps/agent/internal/monitor/system_freebsd.go, apps/agent/internal/monitor/system_other.go, apps/agent/internal/monitor/pkgaudit.go, apps/agent/internal/monitor/pkgaudit_test.go, apps/agent/internal/monitor/system_freebsd_test.go
Änderung: `system_other.go` wird `//go:build !linux && !freebsd`. `system_freebsd.go`: `reboot_required` = `freebsd-version -k` ≠ `freebsd-version -r`; `security_updates` stündlich wie unter Linux (Zustand in `reportState`, `updatesCheckEvery`, Zeitdeckel): `pkg audit -q` (Zahl der Pakete) plus `pkg audit -q FreeBSD-<-u>` und `FreeBSD-kernel-<-k>` gegen die lokale `vuln.xml`, nie mit `-F`. Fehlt die Datenbank, fällt das Feld weg. `pkgaudit.go` (ohne Build-Tag, SPDX) parst die Ausgaben und formt die Versionen wie `405.pkg-base-audit` um (`15.1-RELEASE-p2` → `15.1_2`); Tests unter Linux mit Fixtures, `system_freebsd_test.go` stubbt die Aufrufe und läuft im Box-Lauf (T9).
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T11
Abhängt von: T3

### T5 — Monitoring: Betriebssystem `freebsd` annehmen (R-1247)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/template_suggestions.py, apps/monitoring/tests/test_template_suggestions.py
Änderung: `_OSES` (`template_suggestions.py:34`) nimmt `freebsd` auf, ohne Vorlagen-Vorschlag wie `darwin`. Test: ein Bericht mit `os: freebsd` wird gespeichert und schlägt keine Vorlage vor (Fall neben `("darwin", (), [])`, Z. 160).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_template_suggestions.py
Doku: → T11

### T6 — Agent: FreeBSD-Paket und signiertes pkg-Repo bauen (R-1247)  [ ]
Komponente: agent · Dateien: apps/agent/build-pkg.sh, apps/agent/freebsd/post-install, apps/agent/freebsd/pre-deinstall, apps/agent/cmd/adminhelper-agent/packaging_pkg_test.go, apps/agent/Makefile
Änderung: `build-pkg.sh` (SPDX) baut aus `bin/adminhelper-agent-freebsd` und dem frpc-Archiv je ABI (`FreeBSD:14:amd64`, `FreeBSD:15:amd64`) einen Stage-Baum (`/usr/local/bin/adminhelper-agent`, `/usr/local/libexec/adminhelper/frpc`, `/usr/local/etc/rc.d/adminhelper_frpc`), schreibt `+MANIFEST` (UCL: Name, Version aus `VERSION`, `abi`, `prefix`, Lizenz, Scripts) und ruft `pkg create`; mit `PKG_REPO_KEY` danach `pkg repo <dir> rsa:<key>` je ABI unter `<out>/freebsd/<ABI>/`. `post-install` und `pre-deinstall` (POSIX sh): Deinstallation stoppt `adminhelper_frpc`, löscht `/usr/local/etc/cron.d/adminhelper` und lässt Konfiguration und Identität stehen. `packaging_pkg_test.go` fährt die Scripts mit Stubs (`service`, `sysrc`) wie die RPM-Tests und prüft das erzeugte Manifest; echtes `pkg create`/`pkg repo`/`pkg install` prüfen T9 (FreeBSD) und T10 (Ubuntu-CI). Makefile-Ziel `pkg`.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T11
Abhängt von: T2

### T7 — Gateway: pkg-Repo unter `/freebsd/` auf der Repo-Ebene :8445 (R-1247)  [ ]
Komponente: server · Dateien: apps/gateway/nginx.conf, apps/server/tests/test_gateway_container.py
Änderung: die Location der Repo-Ebene (`nginx.conf:220`, heute `^/(apt|rpm)/`) lässt `freebsd` zu; Dateitypen und Methoden wie bei apt/rpm, alles andere bleibt 404. Test im echten nginx-Container: `/freebsd/FreeBSD:15:amd64/meta.conf` liefert 200, `/freebsd/../etc` und eine fremde Wurzel liefern 404.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_gateway_container.py
Doku: → T11

### T8 — Test-Infrastruktur: VM-Vorlage FreeBSD 15.1 im Pool (R-1247)  [?] (Frage 1: Basis-Vorlage über ein Token-Recht `Datastore.AllocateTemplate` auf einem Datei-Storage mit Inhalt `import`, oder Import von Hand durch Kevin)
Komponente: scripts · Dateien: scripts/vm/profiles.json, scripts/vm/vm.py, scripts/vm/tests/test_vm.py
Änderung: Profil `base-freebsd` (`template_tag` `ah-tpl-base-freebsd`) und Rolle `freebsd`; was `vm.py` für einen FreeBSD-Gast anpassen muss (IP über den qemu-guest-agent, `sudo` aus `/usr/local/bin`, kein `bash` im Basissystem), mit Tests gegen aufgezeichnete Proxmox-Antworten. Je nach Antwort auf Frage 1 zusätzlich ein Import-Verb in `vm.py` (Image laden, als Vorlage taggen) oder die Handgriffe für Kevin in `DEVELOPMENT.md` (T11). Harness-Pfad auf Kevins Wort aus der Roadmap-Zeile.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: → T11

### T9 — Test: FreeBSD-Box-Lauf (Agent-Tests nativ, Paket, Dienst) (R-1247)  [ ]
Komponente: scripts · Dateien: scripts/tests/freebsd_box.sh, scripts/tests/box_freebsdbox.sh
Änderung: `freebsd_box.sh` (SPDX, Dev-Box): baut die Testbinaries mit `GOOS=freebsd go test -c -o <dir>/ ./...`, das Agent-Binary und das Paket (`build-pkg.sh`, Wegwerf-RSA-Schlüssel im eigenen Temp-Verzeichnis), least eine VM mit `vm.py clone --profile base-freebsd --role freebsd`, kopiert alles hinüber, fährt `box_freebsdbox.sh` und reapt am Ende (bei Fehler bleibt die VM stehen, wie die anderen Box-Läufe). `box_freebsdbox.sh` (POSIX sh, SPDX, auf der VM als root): alle Testbinaries; lokales Repo mit Signatur anlegen und `pkg install adminhelper-agent` daraus; `adminhelper-agent service install` schreibt die cron.d-Datei; `service adminhelper_frpc start` mit einer Wegwerf-`frpc.toml` und `status` meldet „is running“; `adminhelper-agent run --once` mit einem Monitor-Ziel ohne Gegenstelle läuft durch die Sammler (Report-JSON per `monitor show` o. ä., `host.os` = `freebsd`, `system_state` vorhanden); `pkg delete` räumt cron.d und Dienst. Ergebnis als `N passed, M failed` und Exit ≠ 0 bei Fail; fehlt die VM-Vorlage, endet der Lauf mit 75 (SKIP = rot).
Verify: bash scripts/dev/verify.sh scripts --strict -- box_scripts_guard_test
Doku: → T11
Abhängt von: T4, T6, T8

### T10 — CI und Release: pkg aus den Quellen, FreeBSD-Pakete und signiertes Repo (R-1247)  [?] (Frage 2: Signierschlüssel RSA-4096, Secret `PKG_REPO_SIGNING_KEY`, Public Key im Repo gepinnt; Frage 3: ein PR mit Kevin-Merge)
Komponente: scripts · Dateien: .github/workflows/ci.yml, .github/workflows/release.yml, apps/agent/freebsd/adminhelper-pkg.pub, apps/agent/build-repo.sh
Änderung: `ci.yml`: der Job `agent` baut zusätzlich `GOOS=freebsd`; ein neuer Job baut `pkg` aus `freebsd/pkg` (Tag und Commit gepinnt, Cache), fährt `build-pkg.sh` mit einem Wegwerf-Schlüssel für beide ABIs und prüft Katalog und Signatur. `release.yml`: dasselbe mit dem Secret, fail-closed, wenn der Public Key des Secrets nicht `adminhelper-pkg.pub` ist; der Teilbaum `freebsd/` geht in `adminhelper-agent-repo-<tag>.tar.gz` (`build-repo.sh` nimmt ihn auf, wenn er da ist). `install.sh` und `update.sh` bleiben unverändert (sie entpacken den ganzen Tarball). frp-Archiv `freebsd_amd64` aus derselben `FRP_VERSION`.
Verify: bash scripts/dev/verify.sh scripts --strict -- toolchain_lockstep_test harness_consistency_test
Doku: → T11
Abhängt von: T6

### T11 — Doku DE+EN und CHANGELOG (R-1247)  [ ]
Komponente: scripts · Dateien: docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/cicd.html, docs/en/developer/cicd.html, DEVELOPMENT.md, changelog.d/arch-freebsd-agent.md
Änderung: Agent-Verteilung: Abschnitt FreeBSD (Repo-Datei mit `${ABI}`, Schlüssel und Gateway-CA per `ENV`, `pkg install`, `provision`, Pfade, Dienst `adminhelper_frpc`, Takt über cron.d, Deinstallation). Monitoring: was FreeBSD meldet (`security_updates` aus pkg audit, `reboot_required`, Dienste aus `service -e`, Jail/VM). Entwickler-Doku Agent: Plattformdateien, `_unix`-Konvention, Cross-Build-Wächter. CI/CD: pkg-Bau aus den Quellen und Signatur. DEVELOPMENT.md: `make build-freebsd`, `make pkg`, die Vorlage, `freebsd_box.sh`. CHANGELOG-Fragment.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
