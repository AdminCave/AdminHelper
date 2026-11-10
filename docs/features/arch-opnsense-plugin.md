<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# OPNsense-Plugin `os-adminhelper` (`arch-opnsense-plugin`, Roadmap R-1248)

## Problem / Motivation

Eine OPNsense steht meist am Rand eines Kunden-LANs und ist heute für AdminHelper unsichtbar: kein Monitoring der
Dienste, Gateways, States oder des CARP-Zustands und kein FRP-Tunnel zur Firewall-GUI. Der Weg über die OPNsense-API
braucht einen Key, und einen rein lesenden Key gibt es nicht: die Rechte gelten pro Seite, „Status: Services“ umfasst
auch start/stop/restart, „System: Firmware“ auch update/reboot. Kevin hat entschieden (Monitoring-Konzept, 2026-11-09):
OPNsense nur über das Plugin `os-adminhelper` auf dem FreeBSD-Agenten (R-1247), ohne API-Key und ohne LAN-Sonde.

## Ziel & Nicht-Ziele

**Ziel:**
- Der FreeBSD-Agent liest auf einer OPNsense lokal und nur lesend über `configctl` (configd):
  - `service list`: Dienste mit Status,
  - `interface gateways status`: Gateways (dpinger: Status, Verlust, Latenz),
  - `firmware product`: Version, letzte Update-Prüfung (liest nur deren Ergebnis, kein Netz),
  - `filter diag state_size`: pf-States und ihr Limit,
  - `interface show carp` und `interface list ifconfig`: CARP-Demotion, Wartungsmodus, Rolle je VIP.
  Er fasst das in skalare Felder eines neuen Fühlers `opnsense` im Fühler-Framework aus R-1223. Ein Katalogmodul
  `opnsense` erkennt die Firewall an `/usr/local/opnsense/version/core` und bewertet die Felder mit Regeln.
- Ein Plugin `os-adminhelper` bindet den Agenten in OPNsense ein:
  - `plugins.inc.d`: der Dienst `adminhelper_frpc` erscheint unter „Dienste“ und im Dashboard,
  - configd-Actions: start, stop, restart, status,
  - `rc.conf.d` aus einer Vorlage, eine Einstellungsseite (MVC) mit Menü und ACL.
- Paket `os-adminhelper` je ABI im signierten pkg-Repo aus R-1247; es hängt von `adminhelper-agent` ab.
- Das Fühler-Framework aus R-1223 läuft auf FreeBSD, soweit das Modul es braucht: Plan holen, Marker, Fühler ohne
  Ziel, Bericht.
- Testvorlage OPNsense 26.7 im Pool `adminhelper-ci` (FreeBSD 15.1 → `opnsense-bootstrap.sh -r 26.7`) und ein
  Box-Lauf, der Plugin und Fühler gegen eine echte OPNsense prüft. Der Bake ist erlaubt (Kevin, 2026-11-09).

**Nicht-Ziele (YAGNI):**
- OPNsense-API (Weg A), LAN-Sonde, API-Keys: ausdrücklich nicht (Konzept-Entscheidung 5 und 4).
- Keine schreibende configd-Aktion: `firmware check`/`probe`, `filter kill.states`/`flush.states` und Dienst-Neustarts
  ruft der Fühler nie. Die Allowlist ist im Agenten fest, der Server wählt nur eine Ansicht.
- VPN, Zertifikate, ACME und IDS: eigene Module, wenn Bedarf entsteht.
- arm64: frp baut kein `freebsd_arm64`, wie in R-1247.
- Die Einreichung bei OPNsense (Tier 3) ist eine eigene spätere Zeile.

## Betroffene Komponenten & Dateien

Der Plan setzt auf zwei offene Stände: R-1223 (`arch-monitoring-module`, PR #438, Fühler-Framework, Katalog, Plan)
und R-1247 (`arch-freebsd-agent`, Branch `feature/arch-freebsd-agent`, FreeBSD-Plattform, `build-pkg.sh`, Vorlage
FreeBSD 15.1). Pfade unten, die es auf `main` noch nicht gibt, stammen von dort.

**Agent (`apps/agent/`):**
- `internal/opnsense/` (neu, ohne Build-Tag, SPDX): die Allowlist der Ansichten
  (`services|gateways|firmware|states|carp` → festes argv mit `/usr/local/sbin/configctl`, Zeitdeckel), die Parser
  der JSON- und Textausgaben und die Verdichtung zu skalaren Feldern. Der Aufrufer wird injiziert (Muster
  `rcservice.go` aus R-1247), so testet die Linux-CI alles mit Fixtures.
- `internal/probe/sensor_opnsense.go` (neu): Fühler `opnsense` mit Parameter `view`, ohne Ziel und ohne Credential.
  Fehlt `configctl`, meldet er `unsupported`.
- Fühler-Framework auf FreeBSD: R-1223 trägt Plattformdateien nur für Linux und Windows (`credentials/store_*`,
  `probe/target_*`, `probe/sensor_local_*`). R-1247 kennt das Framework nicht. Die FreeBSD-Gegenstücke liefert
  R-1248, soweit nötig:
  - Credential-Store wie unter Linux (Datei unter `/usr/local/etc/adminhelper`, root-only),
  - Ziel-Auflösung über `sockstat`,
  - lokale Fühler, die auf FreeBSD nichts zu fragen haben, melden `unsupported`,
  - ein `unixsocket`-Peer-Check über `LOCAL_PEERCRED`.

**Plugin (`apps/agent/opnsense/`, neu):** Quellbaum im Layout des offiziellen Plugin-Repos (`src/…`, Vorbild
`sysutils/node_exporter`):
- `src/etc/inc/plugins.inc.d/adminhelper.inc`,
- MVC `OPNsense/AdminHelper` mit Model `General`, Form, API- und Seiten-Controller, Volt-View, ACL und Menü,
- `src/opnsense/service/conf/actions.d/actions_adminhelper.conf`,
- `src/opnsense/service/templates/OPNsense/AdminHelper/{+TARGETS,adminhelper_frpc}`,
- die Repo-Datei nach Vendor-Muster (Frage 1).
Ein Go-Test prüft den Baum statisch: XML wohlgeformt, ACL deckt die Controller-Pfade, Actions und `+TARGETS`
vollständig, Namen gleich denen aus R-1247. Nativ prüft ihn der Box-Lauf (`php -l`, configd, Template).

**Paket:** `apps/agent/build-pkg.sh` (R-1247) baut zusätzlich `os-adminhelper` je ABI. Manifest, Versionsdatei
`/usr/local/opnsense/version/adminhelper` und die Install-Skripte folgen `Mk/plugins.mk` des Plugin-Repos:
- configd neu starten,
- `run_migrations.php OPNsense/AdminHelper`,
- `rc.configure_plugins POST_INSTALL`,
- `configctl template reload OPNsense/AdminHelper`.
Dazu ein Test mit Stubs wie `packaging_pkg_test.go`.

**Monitoring (`apps/monitoring/`):**
- `app/catalog/sensors.py`: Fühler `opnsense` mit seinen Feldern und dem Parameter `view`.
- `app/catalog/modules/opnsense.py` (neu): Modul `opnsense` mit Marker, Checks je Ansicht, Regeln und Karte.
  Eine Firewall ergibt eine Instanz namens `opnsense`. `discovery._instances` legt bei einem Marker-Treffer ohne
  eigene Instanzart eine Instanz mit dem Modulnamen an.

**Test-Infrastruktur (`scripts/vm/`, `scripts/tests/`):**
- Profil `base-opnsense` (Tag `ah-tpl-base-opnsense`), gebacken aus `base-freebsd` (R-1247 T8) mit
  `opnsense-bootstrap.sh -r 26.7` und einer vorbereiteten `config.xml` (root-Hash, SSH mit Key, Interfaces `vtnet*`).
- `opnsense_box.sh` und `box_opnsensebox.sh` nach dem Muster von `freebsd_box.sh`.

**Web/Desktop:** keine Änderung. Modul, Checks und Karte zeigt die generische Modul-Oberfläche aus R-1223.

## Datenmodell / API / Migrationen

- **Keine Alembic-Migration**, keine neue API-Route. Neu sind ein Fühlername im Plan (`sensor: "opnsense"`,
  `params: {"view": …}`) und ein Katalogmodul. Beides ist eine Erweiterung des Plan- und Katalogvertrags aus R-1223;
  ein älterer Agent meldet `invalid` für einen unbekannten Fühler.
- **Felder je Ansicht** (Vorschlag; welche Felder genau, legt der Bau nach den Fixtures fest; skalar, höchstens 32,
  Text ≤ 256 Zeichen):
  - `services`: `total`, `running`, `stopped`, `stopped_names` (Komma-Liste). Ein Dienst mit `nocheck` zählt nicht.
  - `gateways`: `total`, `down`, `degraded` (delay/loss), `down_names`, `degraded_names`, `max_loss_pct`,
    `max_delay_ms`. Ein Gateway ohne Monitor (`none` bei abgeschaltetem dpinger) zählt nicht.
  - `firmware`: `version`, `latest`, `update_available`, `needs_reboot`, `check_age_s` (Alter von
    `/tmp/pkg_upgrade.json`, fehlt ohne Prüfung), `repository` (Status der letzten Prüfung).
  - `states`: `current`, `limit`, `used_pct`.
  - `carp`: `vips`, `master`, `backup`, `init`, `demotion`, `maintenance`.
- **Regeln des Moduls** (Frage 4):
  - Dienst gestoppt → crit,
  - Gateway down → crit, Verlust oder Latenz → warn,
  - States ≥ 80 % → warn, ≥ 95 % → crit,
  - VIP in INIT → crit, Demotion > 0 → warn, Wartungsmodus → info,
  - Firmware: Update verfügbar → info, Neustart nötig → warn.
- **Intervalle:** `services`, `gateways`, `states`, `carp` 5 min, `firmware` 1 h. Grund: `firmware product` startet
  mehrere PHP-Prozesse und `opnsense-update`/`opnsense-verify`.

## Externe Integrationen

Gelesen in den Quellen (opnsense/core, opnsense/plugins, opnsense/docs, opnsense/update; Stand 2026-11-09):
- `configctl service list` → `actions_service.conf` `[list]` = `/usr/local/sbin/pluginctl -S`: JSON-Liste mit
  `name`, `description`, `status` („… is running“), `locked`, `nocheck`. `ServiceController::searchAction` liest
  `running` genauso per `strpos(status, 'is running')`.
- `configctl interface gateways status` → `scripts/routes/gateway_status.php`: JSON je Gateway mit `name`,
  `address`, `status` (`none` = online, `force_down`, `down`, `delay`, `loss`, `delay+loss`), `loss`, `delay`,
  `stddev`, `monitor`.
- `configctl firmware product` → `scripts/firmware/product.php`: liest `/usr/local/opnsense/version/core`,
  `latest.php` (lokaler Changelog), `opnsense-update -M`/`-G`, `opnsense-verify -l` und das letzte
  Prüfergebnis `/tmp/pkg_upgrade.json` (`product_check`). `firmware check`/`probe` gehen ins Netz und bleiben aus.
  Ob `opnsense-update -G` wirklich lokal bleibt, ist **nicht verifiziert**; der Box-Lauf prüft es.
- `configctl filter diag state_size` → `pfctl -si` (current entries) und `pfctl -s memory` (states hard limit),
  zwei Textzeilen.
- CARP: `configctl interface show carp` → `carp_global_status.php` (JSON `demotion`, `allow`, `maintenancemode`,
  `status_msg`); Rolle je VIP aus `configctl interface list ifconfig` (`pluginctl -D`, Einträge `carp` mit `vhid`,
  `status` MASTER/BACKUP/INIT), wie `Diagnostics/Api/InterfaceController::getVipStatusAction`.
- Plugin-Aufbau: `plugins/Mk/plugins.mk` (Manifest, `@shadow`/`@sample`, Install-Skripte), Beispiel
  `plugins/sysutils/node_exporter`; Repo-Skripte `/usr/local/opnsense/scripts/firmware/repos/*`, die
  `system_firmware_configure()` (`core/src/etc/inc/system.inc`) ausführt, mit dem Vendor-Muster
  `plugins/vendor/sunnyvalley`.
- docs.opnsense.org `manual/software_included.rst`: „Adding (FreeBSD, ..) repositories in /usr/local/etc/pkg/repos/
  manually is not supported and usually lead to unexpected issues.“
- Bootstrap: opnsense/update `README.md`, aus FreeBSD 15.1-RELEASE `opnsense-bootstrap.sh.in -r 26.7`. Ein
  unbeaufsichtigter Durchlauf ist nicht dokumentiert und **nicht verifiziert**.

Die Antwortformen sind aus dem Quelltext gelesen, nicht an einer laufenden OPNsense gesehen: Fixtures und Parser
gelten bis zum Box-Lauf als **nicht verifiziert**.

## Trade-offs & Alternativen

- **configctl statt direkter Skript- oder Systemaufrufe:**
  - Für configctl spricht: Kevins Vorgabe, dieselben Ausgaben wie die GUI, und configd serialisiert die Aufrufe.
  - Der Preis: configd muss laufen. Läuft es nicht, meldet der Fühler `error`, und das ist dann selbst ein Befund.
- **Ein Fühler mit `view` statt fünf Fühlern:** ein Ort für die Allowlist und den Zeitdeckel, ein Eintrag im
  Sensorvertrag. Empfehlung: einer.
- **Verteilung (Frage 1):**
  - (a) Empfehlung: dasselbe signierte Repo wie der Agent (Server :8445/freebsd), Repo-Datei nach dem Vendor-Muster.
    Die Firmware-Konfiguration verwaltet sie dann, und Updates kommen über System → Firmware. Das Repo trägt nur
    unsere zwei Pakete, also ersetzt es kein OPNsense-Paket; die Agent-Binaries sind statisch, also gibt es keinen
    OpenSSL-Bruch beim Major-Upgrade.
  - (b) Nur `pkg add` je Version, ohne Repo.
  - (c) Gleich zur Einreichung bei OPNsense.
- **HAProxy (Frage 3):**
  - Die Konzept-Tabelle führt HAProxy im Web-Modul (R-1231) „auch OPNsense-Plugin“, die Zeile R-1248 nennt den
    Socket „nur show“.
  - Empfehlung: das HAProxy-Modul einmal in R-1231, für Linux und OPNsense (`/var/run/haproxy.socket`), weil die
    Auswertung je Backend und Server (DOWN gegen MAINT) dort ohnehin entsteht.
  - R-1248 liefert den Dienststatus über `service list`. Der `unixsocket`-Fühler sendet ohnehin nur `show stat`.
- **Einstellungsseite (Frage 2):**
  - Empfehlung: Schalter, Status und Registrierung per Shell (`provision --token-stdin`). Kein Token in
    `config.xml`, keiner in einer configd-Aktion (die loggt ihre Parameter).

## Risiken & Rollback

- **Fremd-Repo auf OPNsense:** offiziell nicht unterstützt (Zitat oben). Die Folgen bleiben klein:
  - Das Repo trägt nur `adminhelper-agent` und `os-adminhelper`.
  - Es hat eine niedrigere Priorität als OPNsense.
  - Es ist je ABI gebaut, so findet ein Major-Upgrade (26.1 → 26.7, FreeBSD 14 → 15) das passende Paket.
  Die Doku nennt den Hinweis.
- **configd-Last:** ein Aufruf je Ansicht und Intervall; `firmware` stündlich. Kein Aufruf schreibt oder geht ins
  Netz, das prüft der Box-Lauf mit `sockstat`/Log für `firmware product`.
- **Ungeprüfte Formate:** die Parser verwerfen eine unbekannte Form ganz (Fehler statt falscher Zahlen); der
  Box-Lauf liest die echten Ausgaben.
- **Merge-Reihenfolge:** R-1248 braucht R-1223 und R-1247 auf `main`. Wer von beiden zuletzt merged, muss den
  FreeBSD-Cross-Build (`crossbuild_test.go`) mit den neuen Framework-Paketen grün halten; T3 hier füllt danach die
  Funktion.
- **Rollback:** `pkg delete os-adminhelper` entfernt Plugin, Menü und Vorlage. Die Install-Skripte von `plugins.mk`
  laufen auch beim Entfernen (`POST_DEINSTALL`). Die Agent-Konfiguration bleibt wie in R-1247. Server-seitig fällt
  ein Revert des Moduls auf „Fühler unbekannt“ zurück.

## Doku-Impact

- Agent-Verteilung: Abschnitt OPNsense mit Installation, Repo-Hinweis, Registrierung, Einstellungsseite und
  Deinstallation.
- Monitoring: Modul `opnsense` mit Ansichten, Feldern, Regeln und Kosten.
- Entwickler-Doku Agent: Fühler `opnsense`, Plugin-Baum, Box-Lauf.
- `DEVELOPMENT.md`: Vorlage `base-opnsense` und `opnsense_box.sh`.
- CHANGELOG-Fragment.

Alles DE+EN (T9).

## Offene Fragen

Keine. Kevin hat am 2026-11-10 alle vier Empfehlungen angenommen:
1. **Verteilung:** signiertes Repo des Servers mit Vendor-Repo-Datei → T6.
2. **Einstellungsseite:** Schalter und Status, Registrierung per Shell → T2.
3. **HAProxy:** Modul in R-1231 für Linux und OPNsense, nicht hier.
4. **Regeln und Schwellen:** wie oben → T5.
