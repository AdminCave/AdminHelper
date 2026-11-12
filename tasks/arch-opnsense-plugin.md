<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-opnsense-plugin — Task-Ledger
Status: aktiv · Branch: feature/arch-opnsense-plugin · Review: pro Task
Spec: docs/features/arch-opnsense-plugin.md (Roadmap R-1248)
Heavy: linux-full — Agent (neuer Fühler, Paketierung) und Monitoring (Katalogmodul); dazu vor dem Merge der OPNsense-Box-Lauf `bash scripts/tests/opnsense_box.sh` (T8) auf der Pool-VM
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Baut auf R-1223 (`arch-monitoring-module`, PR #438: Fühler-Framework, Katalog, Plan) und R-1247
(`arch-freebsd-agent`: FreeBSD-Plattform, `build-pkg.sh`, Vorlage `base-freebsd`). T1 hängt an keinem von beiden; T3
bis T8 warten auf deren Merge, T7 zusätzlich auf R-1247 T8. Bake der Vorlage OPNsense 26.7 im Pool `adminhelper-ci`
auf Kevins Wort aus der Roadmap-Zeile (2026-11-09).

### T1 — Agent: OPNsense-Ansichten über configctl lesen und zu Feldern verdichten (R-1248)  [x]
Komponente: agent · Dateien: apps/agent/internal/opnsense/opnsense.go, apps/agent/internal/opnsense/parse.go, apps/agent/internal/opnsense/opnsense_test.go, apps/agent/internal/opnsense/testdata/carp_global.json, apps/agent/internal/opnsense/testdata/carp_ifconfig.json, apps/agent/internal/opnsense/testdata/carp_ifconfig_novip.json, apps/agent/internal/opnsense/testdata/firmware.json, apps/agent/internal/opnsense/testdata/firmware_unchecked.json, apps/agent/internal/opnsense/testdata/gateways.json, apps/agent/internal/opnsense/testdata/services.json, apps/agent/internal/opnsense/testdata/states.txt
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @f879c7520 2026-11-10T08:52:57+01:00
Review: approve (.ah-out/review/arch-opnsense-plugin/T1.verdict.json)
Änderung: Neues Paket `internal/opnsense` ohne Build-Tag, alle Dateien mit SPDX. Es enthält die feste Allowlist der Ansichten `services|gateways|firmware|states|carp`. Jede Ansicht hat ein argv mit absolutem `/usr/local/sbin/configctl` und einen Zeitdeckel; `carp` hat zwei Aufrufe (`interface show carp`, `interface list ifconfig`). `Read(ctx, view, run)` bekommt den Aufrufer injiziert und gibt skalare Felder nach Spec §Datenmodell zurück. Die Parser verwerfen eine unbekannte Form ganz und nennen im Fehler weder Ausgabe noch Pfad. `check_age_s` kommt aus der mtime von `/tmp/pkg_upgrade.json`; auch das ist über eine injizierte Funktion ersetzbar. Fixtures unter `testdata/` sind aus den OPNsense-Quellen nachgebaut (Spec §Externe Integrationen) und gelten bis T8 als nicht verifiziert. Tests: jede Ansicht mit Normal-, Leer- und Fehlerfall, unbekannte Ansicht → Fehler, Abbruch über den Kontext, Textfelder ≤ 256 Zeichen.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T9

### T2 — Plugin-Quellbaum `os-adminhelper` (MVC, configd, plugins.inc.d, rc.conf.d) (R-1248)  [x]
Komponente: agent · Dateien: apps/agent/opnsense/plugin_test.go, apps/agent/opnsense/src/etc/inc/plugins.inc.d/adminhelper.inc, apps/agent/opnsense/src/opnsense/mvc/app/controllers/OPNsense/AdminHelper/Api/GeneralController.php, apps/agent/opnsense/src/opnsense/mvc/app/controllers/OPNsense/AdminHelper/Api/ServiceController.php, apps/agent/opnsense/src/opnsense/mvc/app/controllers/OPNsense/AdminHelper/forms/general.xml, apps/agent/opnsense/src/opnsense/mvc/app/controllers/OPNsense/AdminHelper/GeneralController.php, apps/agent/opnsense/src/opnsense/mvc/app/models/OPNsense/AdminHelper/ACL/ACL.xml, apps/agent/opnsense/src/opnsense/mvc/app/models/OPNsense/AdminHelper/General.php, apps/agent/opnsense/src/opnsense/mvc/app/models/OPNsense/AdminHelper/General.xml, apps/agent/opnsense/src/opnsense/mvc/app/models/OPNsense/AdminHelper/Menu/Menu.xml, apps/agent/opnsense/src/opnsense/mvc/app/views/OPNsense/AdminHelper/general.volt, apps/agent/opnsense/src/opnsense/scripts/OPNsense/AdminHelper/info.php, apps/agent/opnsense/src/opnsense/scripts/OPNsense/AdminHelper/reconfigure.sh, apps/agent/opnsense/src/opnsense/service/conf/actions.d/actions_adminhelper.conf, apps/agent/opnsense/src/opnsense/service/templates/OPNsense/AdminHelper/adminhelper_frpc, apps/agent/opnsense/src/opnsense/service/templates/OPNsense/AdminHelper/+TARGETS
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @eeb8aa4a2 2026-11-10T11:13:11+01:00
Review: approve (.ah-out/review/arch-opnsense-plugin/T2.verdict.json)
Änderung: Quellbaum unter `apps/agent/opnsense/src/` im Layout des offiziellen Plugin-Repos:
- `etc/inc/plugins.inc.d/adminhelper.inc` mit `adminhelper_services()` (Dienst `adminhelper_frpc`, configd start/stop/restart/status, pidfile aus R-1247) und `adminhelper_enabled()`;
- MVC `OPNsense/AdminHelper`: Model `General` (Feld `enabled`), Form, `Api/GeneralController`, `Api/ServiceController` (Muster `ApiMutableServiceControllerBase`), Seiten-Controller, Volt-View, `ACL/ACL.xml`, `Menu/Menu.xml` (Dienste → AdminHelper);
- `service/conf/actions.d/actions_adminhelper.conf` (start, stop, restart, status, reconfigure);
- `service/templates/OPNsense/AdminHelper/+TARGETS` mit `adminhelper_frpc:/etc/rc.conf.d/adminhelper_frpc`.
Der Schalter steuert den Agenten-Takt (cron.d) und frpc. Aus heißt: kein Lauf, frpc gestoppt. So überschreibt kein Agentenlauf die Vorlage.
Die Seite zeigt den Status (registriert, Server, Agent-Version, letzter Lauf) über eine lesende configd-Aktion. Registriert wird per Shell (`adminhelper-agent provision --token-stdin`); die Seite trägt kein Token, keine configd-Aktion bekommt eines (Kevin 2026-11-10, Frage 2).
SPDX in jeder Datei: PHP/Volt/XML als Kommentar, Jinja als `{# #}`.
`plugin_test.go` prüft statisch:
- jede XML-Datei wohlgeformt;
- jeder Controller-Pfad von einer ACL-Pattern gedeckt;
- jede Action mit `command`, `type` und `message`;
- `+TARGETS` nennt nur vorhandene Vorlagen;
- Dienst- und Pfadnamen gleich den Konstanten aus R-1247 (`internal/frpc/rcd.go`).
`php -l`, configd und das Template prüft T8 nativ. Begründung für mehr als acht Dateien: ein Plugin, das nur zusammen lädt und getestet wird.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T9
Abhängt von: R-1247 gemergt (Dienstname, Pfade)

### T3 — Agent: Fühler-Framework auf FreeBSD (R-1248)  [x]
Komponente: agent · Dateien: apps/agent/internal/credentials/store_linux.go, apps/agent/internal/credentials/store_unix.go, apps/agent/internal/discovery/discovery.go, apps/agent/internal/discovery/discovery_test.go, apps/agent/internal/probe/guard.go, apps/agent/internal/probe/listeners_gopsutil.go, apps/agent/internal/probe/target.go, apps/agent/internal/probe/target_test.go, apps/agent/internal/probe/unit_rcd.go, apps/agent/internal/probe/unit_rcd_test.go, apps/agent/internal/probe/target_freebsd.go, apps/agent/internal/probe/sensor_local_freebsd.go, apps/agent/internal/probe/sensor_local_freebsd_test.go, apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/sensor_local_windows.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @cfc9aada1 2026-11-10T10:46:43+01:00
Review: approve (.ah-out/review/arch-opnsense-plugin/T3.verdict.json)
Änderung: Was R-1223 für Linux und Windows trägt, bekommt FreeBSD. Wo Linux und FreeBSD gleich sind, geschieht das als `_unix`-Datei nach der Konvention aus R-1247.
- Credential-Store: Datei unter `/usr/local/etc/adminhelper`, root-only, wie unter Linux.
- Ziel-Auflösung: Port und Prozess über `sockstat -46ln`, Parser ohne Build-Tag.
- Lokale Fühler: `unit` als rc.d-Status über `service <name> status`; `container` meldet `unsupported`.
- `unixsocket`: der Prozess hinter dem Socket über `LOCAL_PEERCRED` (`xucred.cr_pid`, FreeBSD ≥ 13).
- Marker-Prüfung, Plan holen und Bericht laufen unverändert; das belegt ein Test.
Die genaue Dateiliste stellt der Bau nach dem Merge von R-1223 und R-1247 fest (`set-files`). Der Cross-Build-Wächter nimmt die neuen Pakete auf. Native Tests kompiliert der Cross-Vet; sie laufen in T8.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T9
Abhängt von: R-1223 und R-1247 gemergt

### T4 — Fühler `opnsense` im Agenten und im Sensorvertrag des Monitorings (R-1248)  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_opnsense.go, apps/agent/internal/probe/sensor_opnsense_test.go, apps/monitoring/app/catalog/sensors.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/app/catalog/model.py
Evidenz: run.sh[quick] agent monitoring: 6 passed, 0 failed, 12 skipped @7e1f290a0 2026-11-10T10:12:04+01:00
Review: approve (.ah-out/review/arch-opnsense-plugin/T4.verdict.json)
Änderung:
- `sensor_opnsense.go` (SPDX) registriert `sensors["opnsense"]`: kein Ziel, kein Credential, Parameter `view` aus der Allowlist (sonst `invalid`). Er ruft `opnsense.Read` mit `execx.Run`. Ohne `/usr/local/sbin/configctl` meldet er `unsupported`, auch auf Linux und Windows.
- `sensors.py` nimmt `opnsense` auf, mit `view: Literal[…]`, der Feldmenge je Fühler und ohne Zielarten.
- Tests: Agent mit einem Fake-Aufrufer (Felder, unbekannte Ansicht, fehlendes configctl); Monitoring mit dem Schema (gültiger und ungültiger `view`, unbekanntes Feld abgewiesen).
Verify: bash scripts/dev/verify.sh agent monitoring --strict
Doku: → T9
Abhängt von: T1, T3

### T5 — Monitoring: Katalogmodul `opnsense` (Erkennung, Checks, Regeln, Karte) (R-1248)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/modules/opnsense.py, apps/monitoring/tests/test_catalog_opnsense.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @1eec01481 2026-11-10T10:15:11+01:00
Review: approve (.ah-out/review/arch-opnsense-plugin/T5.verdict.json)
Änderung: `MODULE`:
- Erkennung: `id: "opnsense"`, Marker `opnsense.core` (`/usr/local/opnsense/version/core`).
- Ein Check je Ansicht mit den Feldern aus T4 und den Intervallen aus der Spec (5 min, `firmware` 1 h).
- Regeln wie in der Spec §Datenmodell (Kevin 2026-11-10, Fragen 4 und 5); die Karte zeigt Version, gestoppte Dienste, Gateways down, States in % und CARP-Rolle.
Tests:
- das Modul lädt durch den Loader;
- ein Bericht mit Marker-Treffer ergibt die Instanz `opnsense` mit allen Checks;
- je Regel ein Bericht, der sie auslöst, und einer knapp darunter;
- ein Bericht ohne Marker ergibt nichts.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_opnsense.py
Doku: → T9
Abhängt von: T4

### T6 — Paket `os-adminhelper` je ABI und Repo-Datei (R-1248)  [x]
Komponente: agent · Dateien: apps/agent/build-pkg.sh, apps/agent/opnsense/post-install, apps/agent/opnsense/post-deinstall, apps/agent/cmd/adminhelper-agent/packaging_pkg_test.go, apps/agent/opnsense/src/opnsense/scripts/firmware/repos/AdminHelper.sh, apps/agent/opnsense/plugin_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @1ef625ac6 2026-11-10T11:44:16+01:00
Review: approve (.ah-out/review/arch-opnsense-plugin/T6.verdict.json)
Änderung: `build-pkg.sh` baut nach `adminhelper-agent` zusätzlich `os-adminhelper` je ABI aus `apps/agent/opnsense/src`.
- Manifest: Abhängigkeit `adminhelper-agent`, origin `opnsense/os-adminhelper`, Versionsdatei `/usr/local/opnsense/version/adminhelper` im Format von `plugins.mk`.
- `+POST_INSTALL`/`+POST_DEINSTALL` wie `plugins.mk`: configd neu starten, `run_migrations.php`, `rc.configure_plugins`, Template-Reload. Unter `PKG_ROOTDIR`/`PKG_CHROOTED` ruft es keinen Dienst, wie in R-1247.
- Dazu (Kevin 2026-11-10, Frage 1: signiertes Repo des Servers) `etc/pkg/repos/AdminHelper.conf` als `@sample` und `opnsense/scripts/firmware/repos/AdminHelper.php`. Das Repo-Skript schreibt die Repo-Datei aus der Server-URL der Agent-Konfiguration: `${ABI}`, `signature_type: pubkey`, `SSL_CA_CERT_FILE` je Repo, Priorität unter OPNsense.
Test mit Stubs wie die Agent-Skripte (Fake-Wurzel, Abbruch bei fremdem absolutem Pfad) und Prüfung des Manifests.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T9
Abhängt von: T2, R-1247 gemergt

### T7 — Test-Infrastruktur: Vorlage OPNsense 26.7 im Pool (R-1248)  [x]
Komponente: scripts · Dateien: scripts/vm/profiles.json, scripts/vm/vm.py, scripts/vm/tests/test_vm.py, scripts/vm/opnsense/config.xml.in, scripts/vm/opnsense/bootstrap.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d01521d66 2026-11-12T07:50:12+01:00
Review: approve (.ah-out/review/arch-opnsense-plugin/T7.verdict.json)
Änderung: Profil `base-opnsense` (Tag `ah-tpl-base-opnsense`, Rolle `opnsense`), gebacken aus einem Klon von `base-freebsd`.
- `bootstrap.sh` (POSIX sh, SPDX) holt `opnsense-bootstrap.sh.in` gepinnt (Commit und SHA-256) und fährt es mit `-r 26.7 -y`.
- Danach setzt es eine `config.xml` aus `config.xml.in`: root-Hash eines Wegwerf-Passworts, SSH nur mit Key aus der Lane, Interfaces `vtnet0`/`vtnet1`, keine API-Keys.
- Was `vm.py` für einen OPNsense-Gast anpasst (Shell, IP-Ermittlung), mit Tests gegen aufgezeichnete Proxmox-Antworten.
Bake auf Kevins Wort aus der Roadmap-Zeile. Harness-Pfad als eigene Task.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: → T9
Abhängt von: R-1247 T8 (Vorlage `base-freebsd`)

### T8 — Test: OPNsense-Box-Lauf (Plugin, Fühler, Paket) (R-1248)  [x]
Komponente: scripts · Dateien: scripts/tests/opnsense_box.sh, scripts/tests/box_opnsensebox.sh, scripts/tests/box_scripts_guard_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @161a01915 2026-11-12T08:48:29+01:00
Review: approve (.ah-out/review/arch-opnsense-plugin/T8.verdict.json)
Änderung: `opnsense_box.sh` (SPDX, Dev-Box) läuft wie `freebsd_box.sh`:
- baut die Agent-Testbinaries (`GOOS=freebsd`), das Agent-Binary und beide Pakete mit Wegwerf-Schlüssel;
- least eine VM `--profile base-opnsense`, kopiert alles hinüber und fährt `box_opnsensebox.sh`;
- reapt am Ende; bei Fehler bleibt die VM stehen.
`box_opnsensebox.sh` (POSIX sh, als root) prüft:
- alle Testbinaries;
- `php -l` über jede PHP-Datei des Plugins;
- `pkg install os-adminhelper` aus dem lokalen Repo zieht den Agenten mit;
- `configctl service list` nennt `adminhelper_frpc`;
- `run_migrations` und Template-Reload schreiben `/etc/rc.conf.d/adminhelper_frpc` nach dem Schalter;
- jede Ansicht aus T1 liefert gegen das echte configctl Felder; die Rohausgaben landen als Fixture-Vergleich im Log;
- `firmware product` öffnet keine Netzverbindung (`sockstat -c` vor und nach);
- `adminhelper-agent run --once` mit einem Plan aus Datei meldet den Fühler `opnsense` mit `ok`;
- `pkg delete os-adminhelper` entfernt Menü und Vorlage.
Ergebnis `N passed, M failed`, Exit ≠ 0 bei Fail; fehlt die Vorlage, Exit 75 (SKIP = rot).
Verify: bash scripts/dev/verify.sh scripts --strict -- box_scripts_guard_test
Doku: → T9
Abhängt von: T2–T7

### T9 — Doku DE+EN und CHANGELOG (R-1248)  [x]
Komponente: scripts · Dateien: docs/developer/agent.html, docs/en/developer/agent.html, DEVELOPMENT.md, changelog.d/arch-opnsense-plugin.md, docs/admin/agent-deployment.html, docs/en/admin/agent-deployment.html, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @25e02f1c7 2026-11-12T09:11:09+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung:
- Agent-Verteilung, Abschnitt OPNsense: Installation, Hinweis „Fremd-Repo nicht unterstützt“, Registrierung, Einstellungsseite, Deinstallation.
- Monitoring: Modul `opnsense` mit Ansichten, Feldern, Regeln, Intervallen und Kosten; kein API-Key.
- Entwickler-Doku Agent: Fühler `opnsense` und Allowlist, Plugin-Baum, Paketbau, Box-Lauf.
- `DEVELOPMENT.md`: Vorlage `base-opnsense`, `opnsense_box.sh`.
- CHANGELOG-Fragment.
Die genauen Seiten stellt `grep -rl` beim Bau fest (`set-files`).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/ DE+EN, DEVELOPMENT.md, changelog.d/arch-opnsense-plugin.md
Task-Review: am Ende

### T10 — Monitoring: Plan-Test einer neuen Box ohne die Marker des ausgelieferten Katalogs (R-1248)  [x]
Komponente: monitoring · Dateien: apps/monitoring/tests/test_agent_plan.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @8c8802e78 2026-11-12T06:34:18+01:00
Review: approve (.ah-out/review/arch-opnsense-plugin/T10.verdict.json)
Änderung: Seit T5 trägt der ausgelieferte Katalog den ersten Marker (`opnsense.core`). `test_plan_of_a_new_server_is_empty_and_scans_at_once` erwartete aus dem echten Katalog `"markers": []` und ist seitdem rot; das `Verify:` von T5 fuhr nur `tests/test_catalog_opnsense.py`. Der Test nimmt einen leeren Katalog über `monkeypatch` wie `test_markers_come_from_the_whole_catalog_sorted`; die Gleichheit des ganzen Plans bleibt, die Marker aus dem Katalog prüft weiter der Nachbartest.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_plan.py
Doku: keine (nur ein Test)
Abhängt von: T5

### T11 — Agent: Pfadsperre des Fühlers `unixsocket` auch unter FreeBSD (R-1248)  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/guard.go, apps/agent/internal/probe/guard_test.go, apps/agent/internal/probe/sensor_local.go, apps/agent/internal/probe/sensor_local_linux.go, apps/agent/internal/probe/sensor_local_freebsd.go, apps/agent/internal/probe/sensor_local_freebsd_test.go, docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/arch-opnsense-plugin.md
Änderung: Gleichstand mit Linux. Dort weist `dialUnix` einen Socket ab, dessen Pfad, wie angegeben oder mit aufgelösten Links, in `controlSockets` liegt; unter FreeBSD (T3) gleicht er bisher nur den Prozess dahinter ab. Die Pfadprüfung wandert in einen gemeinsamen Helfer, den beide `dialUnix` vor dem Verbinden rufen; verbunden wird mit dem aufgelösten Pfad. `controlSockets` nimmt den Socket von configd auf (OPNsense, `/var/run/configd.socket`), einem Steuerdienst des Hosts, dessen Prozess (Python) kein Prozessname erfasst. Tests: `guard_test` nennt den Pfad gesperrt (vorher rot), ein FreeBSD-Test weist Socket, Link und configd-Pfad mit `ErrNotAllowed` ab. Native Tests kompiliert der Cross-Vet; sie laufen im OPNsense-Box-Lauf (T8), der danach neu läuft.
Verify: bash scripts/dev/verify.sh agent scripts --strict
Doku: in der Task — admin/monitoring.html und developer/agent.html (DE+EN) nennen configd unter den Steuerdiensten, das Changelog-Fragment die Pfadsperre unter FreeBSD
Abhängt von: T3

## Entscheidungen
- 2026-11-10 Kevin, Frage 1: `os-adminhelper` kommt aus demselben signierten pkg-Repo des Servers wie der Agent; das Plugin legt die Repo-Datei nach dem Vendor-Muster an; die Doku nennt „Fremd-Repo, nicht unterstützt“ (T6, T9).
- 2026-11-10 Kevin, Frage 2: Einstellungsseite mit Schalter und Status; Registrierung nur per Shell, kein Token in `config.xml` (T2).
- 2026-11-10 Kevin, Frage 3: HAProxy-Modul in R-1231 für Linux und OPNsense; R-1248 baut keines, `service list` liefert den Dienststatus.
- 2026-11-10 Kevin, Frage 4: Regeln und Schwellen wie in der Spec vorgeschlagen (T5).
- 2026-11-10 T1: Statt `Read(ctx, view, run)` ein `Reader{Run, ModTime, Now}` mit `Read(ctx, view)`; so sind Aufrufer, mtime und Uhr für `check_age_s` an einer Stelle injizierbar, `nil` heißt `os.Stat`/`time.Now`.
- 2026-11-10 T1: `gateways` zählt `force_down` getrennt als `forced_down` (vom Admin gewollt, kein Ausfall) und ein Gateway ohne Monitoring (`none` ohne Messwert, Quelle `StaticRoute::getMonitorStatus`) gar nicht; `max_loss_pct`/`max_delay_ms` fehlen ohne Messwert.
- 2026-11-10 T1: `firmware` liefert `update_reboot` statt `needs_reboot`: `needs_reboot` aus `check.sh` heißt „das anstehende Update braucht einen Neustart“ (oder die Einstellung „immer neu starten“), nicht „Neustart steht aus“; das Feld ist nur mit Update wahr. Dazu `checked`, `connection`, `updates`, `major_upgrade`; `product_mirror` und `product_license` verlassen den Parser nie.
- 2026-11-10 Kevin, Frage 5: `update_reboot` ist info, zusammen mit „Update verfügbar“ (Meldung nennt den Neustart); einen ausstehenden Neustart meldet der Systemcheck (`reboot_required`, warn), das Modul nicht (T5).
- 2026-11-10 Kevin, Frage 6: Keine Regel für „Update verfügbar“, `update_reboot` und den CARP-Wartungsmodus (der Katalogvertrag aus R-1223 kennt nur warning/critical); die Werte stehen auf der Karte (`update_available` als sechste Kachel) und in den Check-Details, der Status bleibt ok. Eine echte Stufe info ist R-1280 (T5).
- 2026-11-10 T4 vor T2/T3: der Fühler hängt nur zur Laufzeit auf FreeBSD an R-1247, die Tests nehmen einen Fake-Aufrufer; Basis ist der Branch von #438 (R-1223), in diesen Branch gemergt.
- 2026-11-10 T4: Der Katalog prüft die Felder je Ansicht (`field_allowed` bekommt die Params, dazu `model.py`), denn ein Feld einer anderen Ansicht käme nie zurück. Der Zeitdeckel eines Checks ist `timeout_s` (≤ 30 s) und liegt unter den 60 s des Readers für `firmware`; `firmware product` startet PHP, `opnsense-update -M/-G` und `opnsense-verify -l`, nach den Quellen ohne Netz (für `-G` nicht verifiziert); ob 30 s reichen und ob es lokal bleibt, prüft der Box-Lauf (T8).
- 2026-11-10 T5: `instance: "unit"` ohne Units: FreeBSD hat keine systemd-Units, der Marker allein ergibt die Ersatz-Instanz `opnsense` (`discovery._instances`). `timeout_s` je Check wie der Deckel des Readers, höchstens 30 s (services 30, gateways/states/carp 15, firmware 30). Regeln nur auf Feldern, die die Ansicht immer liefert (fehlt ein Wert, wäre der Status unknown).
- 2026-11-10 Kevin, Frage 7: T2, T3 und T6 bauen auf dem lokalen Stand von R-1247 (T1–T6, `c354511f4`), in diesen Branch gemergt; ändert dessen Abschlussprüfung noch etwas daran, wird erneut gemergt. T7–T9 warten auf den Merge von R-1247 (Vorlage `base-freebsd`, gemeinsame Dateien `vm.py`, `profiles.json`, Doku).
- 2026-11-10 T3 vor T2: der Cross-Build-Wächter aus R-1247 (`GOOS=freebsd go vet ./...`) bleibt rot, bis `internal/probe` auf FreeBSD kompiliert; T3 macht ihn grün, `crossbuild_test.go` selbst bleibt unverändert.
- 2026-11-10 T3: Listener über `/usr/bin/sockstat -46lnq -P tcp` (`parseSockstat` ohne Build-Tag) statt gopsutil: gopsutil liest sie auf FreeBSD über `lsof`, das weder Basis noch OPNsense mitbringen. Eine Zeile anderer Form lässt das ganze Lesen scheitern (fail closed); Owner `?` wird pid 0 wie bei gopsutil; ein Socket ohne Port (`*:*`) fällt weg.
- 2026-11-10 T3: `unit` liest `service <name> onestatus` statt `status`: `onestatus` antwortet unabhängig von `<name>_enable` in rc.conf, `status` verweigert einen nicht aktivierten Dienst. Owner eines Ports sind genau die pids der Statuszeile (rc.subr `check_pidfile`/`check_process`); ein geforkter Worker hält denselben Socket, sockstat listet ihn zusätzlich unter der Eltern-pid. `active_since` ist die Startzeit der ersten pid, Neustarts zählt rc(8) nicht.
- 2026-11-10 T3: `unixsocket` verweigert auf FreeBSD neben den Prozessen des Wächters auch `inetd` (hält Sockets für andere Dienste, wie systemd unter Linux); die pid kommt aus `LOCAL_PEERCRED` (`xucred.cr_pid`, Version 0 geprüft, pid ≤ 0 ist ein Fehler). `checkPeer` unter Linux bleibt unverändert.
- 2026-11-10 T3: Marker auf FreeBSD nur über Pfade (`markerHost`): `dpkg-query`/`rpm` fehlen dort, ein Paket-Marker gilt damit als nicht gefunden. Plan holen und Bericht haben kein OS-Gate (`monitor/plan.go`, `report.go`); Beleg sind der Marker-Test und der Cross-Vet.
- 2026-11-10 T3: Der Credential-Store wird `store_unix.go` (`linux || freebsd`), sein Test bleibt `store_linux_test.go`: ein Umbenennen gälte `task-close.sh` als Löschung einer Testdatei (`Test-Löschung:` nur mit Plan-Commit, `tasks/README.md`). Auf FreeBSD laufen damit die plattformneutralen Tests aus `store_test.go`, die Rechte- und Link-Tests nur unter Linux.
- 2026-11-10 T2: Der Schalter steht ab Werk auf An (Modell-Default 1): ein nachinstalliertes Plugin ändert an einem laufenden Agenten nichts. Die Vorlage schreibt `adminhelper_frpc_enable="YES"` nur mit Schalter an und vorhandener `frpc.toml`; beim Booten schreibt OPNsense alle Vorlagen vor rc(8), so gewinnt Aus. `reconfigure` überschreibt das der Basisklasse: `template reload`, dann `reconfigure.sh on|off`; An startet frpc nur, wenn es nicht läuft (Speichern startet einen laufenden Tunnel nicht neu), Aus nimmt erst den cron-Eintrag und stoppt dann frpc.
- 2026-11-10 T2: Grenzen des Schalters: ein Agentenlauf, der beim Ausschalten schon läuft, kann frpc und die rcvar wieder setzen, bis zum nächsten Speichern oder Booten; `provision` bei Schalter Aus legt den cron-Eintrag an (das nächste Speichern nimmt ihn). „Stop“ auf der Dienste-Seite hält nur bis zum nächsten Agentenlauf, der den Tunnel sicherstellt. `flock` auf `frpc.lock` hätte das Rennen nur verschoben (der Lauf nimmt den Lock nicht über die ganze Zeit).
- 2026-11-10 T2: Statusseite über die lesende configd-Aktion `info` (`info.php`): von den Agentendateien liest sie nur `ADMINHELPER_URL`/`MONITOR_URL` und zeigt Schema, Host und Port; „letzter Monitoring-Lauf“ ist die mtime von `.report-state.json` (nach jedem Push, auch einem gescheiterten), andere Laufzeiten führt der Agent nicht. Die Seite setzt jeden Wert als Text. Kein `xmlrpc_sync`: jeder Knoten eines CARP-Paars registriert sich selbst.
- 2026-11-10 T2: Volt im klassischen Muster (`mapDataToFormUI`, `saveFormToEndpoint`, `ajaxCall`) statt neuerer Helfer, damit die Seite über OPNsense-Versionen lädt. `plugin_test.go` trägt `//go:build linux` (fährt `reconfigure.sh` mit `/bin/sh` gegen Stubs); `./...` lässt es auf Windows aus. PHP, configd, Jinja und ACL prüft der Box-Lauf (T8) nativ, die Dev-Box hat weder PHP noch jinja2.
- 2026-11-10 T2: Vorlage und Agent teilen eine Datei: rc.subrs `enable`/`delete` (`write_rcvar`/`delete_rcvar`) ändern die erste Datei, die die rcvar schon setzt, `rc.conf.d/<name>` vor `/etc/rc.conf`; die Vorlage legt `/etc/rc.conf.d/adminhelper_frpc` an, also setzt der Agent beim ersten Tunnel YES dort, und `load_rc_config` liest `rc.conf.d` nach `rc.conf` (ein altes YES in `rc.conf` verliert gegen die Vorlage). Den Ablauf Plugin installiert → erster Tunnel → Neustart fährt der Box-Lauf (T8).
- 2026-11-10 T6: Repo-Skript `firmware/repos/AdminHelper.sh` statt `.php` (gegen Stubs testbar) schreibt `AdminHelper.conf` selbst (`.new`, dann `mv`); kein `@sample`/`.shadow` (bräuchte Keyword-Dateien beim Bau). `+POST_DEINSTALL` löscht die Datei; ohne Plugin bekommt der Agent keine Updates mehr aus dem Repo, er selbst bleibt. Ohne Schlüssel oder ohne brauchbare Server-URL bleibt eine vorhandene Datei stehen (eine von Hand angelegte zum Erstinstallieren gilt bis zur Registrierung).
- 2026-11-10 T6: Host aus `ADMINHELPER_URL` (frp), sonst `MONITOR_URL`, gelesen wie `LoadKeyValue`; nur https, ein Hostname oder eine IPv6-Adresse in Klammern, danach höchstens `:Port` (pkg expandiert den UCL-String). Port fest 8445 wie `agent-install.sh`; dessen `--repo-port` hat kein Gegenstück, die Agentendateien kennen den Repo-Port nicht.
- 2026-11-10 T6: TLS vor dem Enrollment `SSL_NO_VERIFY_PEER` und `SSL_NO_VERIFY_HOSTNAME` (wie apt `Verify-Peer false`/dnf `sslverify=0`; die Echtheit trägt die pkg-Signatur), danach `SSL_CA_CERT_FILE` auf `identity/ca.crt` (Pfad aus `AgentPkiDir`/`CAFileName`). pkg setzt das `env` eines Repos nur für dessen Fetches und stellt es danach zurück (`libpkg/fetch.c`, geprüft in 1.19.0 bis 2.1.0). Priorität 5 unter OPNsenses 11. IPv6 in der Repo-URL und der Ablauf auf OPNsense: nicht verifiziert bis zum Box-Lauf (T8).
- 2026-11-10 T6: Der öffentliche Schlüssel entsteht beim Bau aus `PKG_REPO_KEY` (`openssl rsa -pubout`, die Form aus pkg-repo(8)) als `/usr/local/etc/pkg/keys/AdminHelper.pub`; ohne Schlüssel packt der Bau keinen, und das Repo-Skript schreibt nichts. Dass der Release-Schlüssel zu `apps/agent/freebsd/adminhelper-pkg.pub` passt, prüft R-1247 T10; ein Box-Lauf mit Wegwerf-Schlüssel passt von selbst. Ein Nicht-RSA-Schlüssel scheitert vor dem Löschen der Ausgabe.
- 2026-11-10 T6: Versionsdatei wie `plugins.mk`: `product_abi` je ABI die OPNsense-Serie (FreeBSD 14 → 26.1, 15 → 26.7), `product_tier` "4" (zeigt OPNsense für jedes fremde Repo ohnehin), `product_hash` leer; dieselbe JSON als Annotations (OPNsense liest die Stufe eines entfernten Plugins daraus). Abhängigkeit `adminhelper-agent` mit Origin und Version des Agentenpakets. Die Tests der Plugin-Skripte stehen in `apps/agent/opnsense/plugin_test.go` neben den Skripten; 29 Mutanten in einer Probe-Kopie, alle gefangen.
- 2026-11-11 Kevin (Roadmap-Notiz R-1247): Frage 1 dort: Token-Recht `Datastore.AllocateTemplate` auf einem Datei-Storage mit Inhalt `import`, das Kevin setzt; `vm.py` importiert Vorlagen selbst. T7 baut weiter wie geplant auf einem Klon von `base-freebsd` und wartet auf R-1247 T8. Frage 3 dort: R-1247 T10 (CI/Release, signiertes Repo) wird eine eigene Zeile mit Kevin-Merge; da `build-pkg.sh` beide Pakete in ein Repo legt, liefert diese Zeile `os-adminhelper` ohne eigenen Schritt mit aus, die Doku (T9) nennt das Repo erst ab dem Release, das sie enthält.
- 2026-11-12 Merge von origin/main (R-1247 gemergt, `b9b599693`): die FreeBSD-Listener aus main (`listen_freebsd.go`, `sockstat.go`; lehnt eine lokale Adresse `*:*` ab) ersetzen `parseSockstat` aus T3, `listeners_gopsutil.go` entfällt. Seit main jeden Werkzeugaufruf über `allowlist.Run` führt, trägt die Allowlist `service <rcscript> onestatus` (T3) und die sechs configctl-Aufrufe der Ansichten (T1); `TestEveryCallOfTheViewsIsOnTheCommandAllowlist` hält Ansichten und Allowlist zusammen.
- 2026-11-12 T7: Die Sperre ist weg: R-1247 T8/T9 sind gemergt, `base-freebsd` steht im Pool (`vm.py doctor`: Vorlage vom 2026-11-11). T10 vor T7, damit der Branch vor dem Harness-Teil grün ist.
- 2026-11-12 T7: Die Vorlage hat ein Interface, `wan` auf `vtnet0` per DHCP, statt `vtnet0`/`vtnet1` aus dem Plan. Die Pool-VMs haben eine NIC; ein konfiguriertes Interface ohne Gerät hält den Boot an der Interface-Zuweisung der Konsole an, und ein LAN mit DHCP-Server wäre ein fremder DHCP-Dienst im Pool-Netz. Die Anti-Lockout-Regel öffnet 22/80/443 auf dem einen Interface (`filter.lib.inc`, mit `system.ssh.enabled` auch 22).
- 2026-11-12 T7: Gebacken wird aus einem Klon von `base-freebsd` mit dessen Gast-User (kein `ciuser` beim Anlegen, kein Upgrade). Der Bootstrap läuft als dieser User; danach stellt `vm.py` `ciuser` auf `adminhelper` um, bevor die VM in OPNsense bootet: OPNsense legt seine User aus `/conf/config.xml` an, cloud-init hat dort nichts zu sagen, und jedes `guest_user` einer Lease liest `ciuser`. Der alte User samt Home fällt im Clean-Schritt (`pw userdel -r`), denn OPNsense räumt beim Abgleich nur uids ab 2000.
- 2026-11-12 T7: In der Vorlage steckt der Pool-Schlüssel (`AH_VM_SSH_KEY`, als `authorizedkeys` des Users `adminhelper` in `config.xml`). Ändert er sich, wird neu gebacken. Root- und User-Passwort sind zufällige bcrypt-Hashes, die niemand kennt: Sie gelten nur für die Web-GUI, das Unix-Passwort jedes Kontos ist `*`. SSH nimmt nur Schlüssel, `sudo_allow_wheel=2` erlaubt wheel sudo ohne Passwort.
- 2026-11-12 T7: `opnsense-bootstrap.sh` ist per Commit und SHA-256 gepinnt (opnsense/update `ef64082e…`), nie per Branch. 26.7 liegt auf pkg.opnsense.org nur unter `FreeBSD:15:amd64` (24.7 bis 26.1 unter `FreeBSD:14`), und das passt zu `base-freebsd` (15.1). Das `reboot` am Ende des Upstream-Skripts fängt ein Shim ab; neu startet `vm.py`, erst nach `config.xml` und der Umstellung von `ciuser`.
- 2026-11-12 T7: Die Shell für `vm.py run` kommt aus dem Profil, das der `tpl-`-Tag der Box nennt (`"shell": "sh"` bei `base-opnsense`, sonst `bash`). OPNsense hat kein bash, und eine Profil-Eigenschaft hält die Ausnahme dort, wo die Vorlage beschrieben ist.
- 2026-11-12 T7: `vm.py doctor` ist bis zum ersten Bake von `base-opnsense` rot (`no template tagged for … base-opnsense`). Gebacken wird vor dem Merge (dieser Branch).
- 2026-11-12 T7: Der erste echte Bake ist grün (Vorlage vom 2026-11-12, OPNsense 26.7.9, Check-Schritt bestanden, auf einer Lease 610 MiB frei auf `/`). Die Lease zeigte, dass nuageinits NOPASSWD-Regel für den gelöschten base-freebsd-User (`/usr/local/etc/sudoers.d/90-nuageinit-users`) den Clean-Schritt überlebte: OPNsense hat kein nuageinit, das sie je Lease neu schriebe. Der Clean-Schritt löscht sie jetzt (auf der Lease geprobt). Die Vorlage vom 2026-11-12 trägt die Regel noch, für einen User, den es dort nicht gibt; neu gebacken wird erst, wenn T8 die Vorlage ändern muss, denn jede zweite Vorlage müsste Kevin löschen (CLAUDE.md §11).
- 2026-11-12 T8: `opnsense_box.sh` nimmt von `freebsd_box.sh` den frp-Pin (`FRP_VERSION`, `FRP_SHA256_FREEBSD_AMD64`, per `sed` gelesen und geprüft) und den Sink (sein Heredoc, unverändert gebaut), statt sie zu kopieren: beide Boxen tragen dasselbe frpc, und ein Pin steht an einer Stelle. Die Agent-Tests als Box-User und als root fährt `box_freebsdbox.sh` (OPNsense ist darunter FreeBSD), `box_opnsensebox.sh` nur die Phase `pkg`. Beide Pakete baut `build-pkg.sh` auf der Box (wie auf der FreeBSD-Box: `pkg create` braucht FreeBSDs pkg); bash dafür kommt aus dem OPNsense-Repo und geht nach dem Bau wieder, der Rest der Phase läuft ohne.
- 2026-11-12 T8: Dass `firmware product` keine Netzverbindung öffnet, beweist ein `ktrace -d -i` auf configd statt `sockstat -c` vorher und nachher: sockstat sieht eine Verbindung nicht, die zwischen zwei Blicken kam und ging. Der Trace muss die Aktion sehen (execve > 0, `product.php` unter den Namen) und darf keine `AF_INET`-Adresse tragen; die Gegenprobe ist `nc -z 127.0.0.1 9` unter ktrace, dessen Adresse der Trace zeigen muss (kein Paket verlässt die Box). configd startet beim post-install neu, deshalb liest das Skript die pid erst danach.
- 2026-11-12 T8: Der Plan für `run --once` kommt aus der gespeicherten `.plan.json`: der Sink antwortet `{}`, das der Agent als Plan ablehnt (`plan_version 0`), und er fährt dann seinen gespeicherten. Den baut `opnsense_box.sh` aus dem `MODULE` des Katalogmoduls (`runpy`, die Form von `module_plan.py`, `scan: true` für den Marker). `monitor init` plant den Agenten per Cron; die Phase nimmt den Plan gleich wieder heraus (`service uninstall`), damit kein Cron-Lauf den einen Lauf kreuzt und `reconfigure on` ihn nachweislich schreibt.
- 2026-11-12 T8: Den Schalter fährt die Phase in den Teilen von `ServiceController::reconfigureAction` (Modell über `load_phalcon.php`, `setNodes`, `serializeToConfig`, `Config::save`; dann `template reload`, dann `adminhelper reconfigure on|off`), nicht über die Web-API: die bräuchte einen API-Key, den das Plugin bewusst nicht hat.
- 2026-11-12 T8: Der erste echte Lauf (OPNsense 26.7.9, FreeBSD 15.1) bestätigt die Fixtures aus T1 in der Form: `gateways`, `firmware product` (jeder Fixture-Schlüssel steht in der echten Ausgabe) und `show carp` decken sich; `service list` trägt auf der Box kein `id` (nur Dienste mit Instanzen) und dazu `configd`, `list ifconfig` `carp` nur mit VIPs. Beide Schlüssel lesen die Parser, wo sie stehen; diese Box hat weder Dienst-Instanzen noch VIPs, den Fall decken die Fixtures (`services.json`, `carp_ifconfig.json`). Ein DHCP-Gateway ohne Monitor meldet `status: none` mit `~` als Messwert und zählt nach Spec nicht (`total: 0`); `firmware` ohne Prüfung liefert nur `version`, `latest`, `checked: false`. Dass `opnsense-update -G` lokal bleibt (Spec §Externe Integrationen, dort „nicht verifiziert“), zeigt der Trace: keine `AF_INET`-Adresse unter 31 execve.
- 2026-11-12 T8: Platz auf der Box: während der Phase `pkg` sind auf `/` 352 MiB frei (Testbinaries 169 MiB, dazu Checkout, Agent, frpc, Sink). Die Phase räumt ihr Arbeitsverzeichnis unter `/var/tmp` nur bei Grün.
