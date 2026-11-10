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

### T2 — Plugin-Quellbaum `os-adminhelper` (MVC, configd, plugins.inc.d, rc.conf.d) (R-1248)  [?] (Frage 7: auf den lokalen Stand von R-1247 (T1-T6) stapeln oder dessen Merge abwarten)
Komponente: agent · Dateien: apps/agent/opnsense, apps/agent/opnsense/plugin_test.go
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

### T3 — Agent: Fühler-Framework auf FreeBSD (R-1248)  [?] (Frage 7: auf den lokalen Stand von R-1247 (T1-T6) stapeln oder dessen Merge abwarten)
Komponente: agent · Dateien: apps/agent/internal/credentials/store_freebsd.go, apps/agent/internal/probe/target_freebsd.go, apps/agent/internal/probe/sensor_local_freebsd.go, apps/agent/internal/probe/sensor_unixsocket.go, apps/agent/internal/probe/target_test.go, apps/agent/cmd/adminhelper-agent/crossbuild_test.go
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

### T6 — Paket `os-adminhelper` je ABI und Repo-Datei (R-1248)  [?] (Frage 7: auf den lokalen Stand von R-1247 (T1-T6) stapeln oder dessen Merge abwarten)
Komponente: agent · Dateien: apps/agent/build-pkg.sh, apps/agent/opnsense/post-install, apps/agent/opnsense/post-deinstall, apps/agent/cmd/adminhelper-agent/packaging_pkg_test.go
Änderung: `build-pkg.sh` baut nach `adminhelper-agent` zusätzlich `os-adminhelper` je ABI aus `apps/agent/opnsense/src`.
- Manifest: Abhängigkeit `adminhelper-agent`, origin `opnsense/os-adminhelper`, Versionsdatei `/usr/local/opnsense/version/adminhelper` im Format von `plugins.mk`.
- `+POST_INSTALL`/`+POST_DEINSTALL` wie `plugins.mk`: configd neu starten, `run_migrations.php`, `rc.configure_plugins`, Template-Reload. Unter `PKG_ROOTDIR`/`PKG_CHROOTED` ruft es keinen Dienst, wie in R-1247.
- Dazu (Kevin 2026-11-10, Frage 1: signiertes Repo des Servers) `etc/pkg/repos/AdminHelper.conf` als `@sample` und `opnsense/scripts/firmware/repos/AdminHelper.php`. Das Repo-Skript schreibt die Repo-Datei aus der Server-URL der Agent-Konfiguration: `${ABI}`, `signature_type: pubkey`, `SSL_CA_CERT_FILE` je Repo, Priorität unter OPNsense.
Test mit Stubs wie die Agent-Skripte (Fake-Wurzel, Abbruch bei fremdem absolutem Pfad) und Prüfung des Manifests.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T9
Abhängt von: T2, R-1247 gemergt

### T7 — Test-Infrastruktur: Vorlage OPNsense 26.7 im Pool (R-1248)  [ ]
Komponente: scripts · Dateien: scripts/vm/profiles.json, scripts/vm/vm.py, scripts/vm/tests/test_vm.py, scripts/vm/opnsense/config.xml.in, scripts/vm/opnsense/bootstrap.sh
Änderung: Profil `base-opnsense` (Tag `ah-tpl-base-opnsense`, Rolle `opnsense`), gebacken aus einem Klon von `base-freebsd`.
- `bootstrap.sh` (POSIX sh, SPDX) holt `opnsense-bootstrap.sh.in` gepinnt (Commit und SHA-256) und fährt es mit `-r 26.7 -y`.
- Danach setzt es eine `config.xml` aus `config.xml.in`: root-Hash eines Wegwerf-Passworts, SSH nur mit Key aus der Lane, Interfaces `vtnet0`/`vtnet1`, keine API-Keys.
- Was `vm.py` für einen OPNsense-Gast anpasst (Shell, IP-Ermittlung), mit Tests gegen aufgezeichnete Proxmox-Antworten.
Bake auf Kevins Wort aus der Roadmap-Zeile. Harness-Pfad als eigene Task.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: → T9
Abhängt von: R-1247 T8 (Vorlage `base-freebsd`)

### T8 — Test: OPNsense-Box-Lauf (Plugin, Fühler, Paket) (R-1248)  [ ]
Komponente: scripts · Dateien: scripts/tests/opnsense_box.sh, scripts/tests/box_opnsensebox.sh, scripts/tests/box_scripts_guard_test.sh
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

### T9 — Doku DE+EN und CHANGELOG (R-1248)  [ ]
Komponente: scripts · Dateien: docs/agent-distribution.html, docs/en/agent-distribution.html, docs/monitoring.html, docs/en/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, DEVELOPMENT.md, changelog.d/arch-opnsense-plugin.md
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
