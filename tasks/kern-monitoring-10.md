<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Module Netz, Sicherheit, DNS, DHCP, Zeit und Reverse-Proxies — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-10 · Review: pro Task
Spec: docs/features/kern-monitoring-10.md (Roadmap R-1236, R-1237, R-1238)
Heavy: linux-full — neue Agent-Ansichten und Freigabeliste (`apps/agent`), kein Stack-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1236: Ansichten wg_peers, fail2ban, crowdsec_bouncers, tailscale_status  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_net.go, apps/agent/internal/probe/app_net_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @08bd2bd2b 2026-11-13T12:54:23+01:00
Review: approve (.ah-out/review/kern-monitoring-10/T1.verdict.json)
Änderung: vier Ansichten, die feste Lesekommandos über `runTool` (Freigabeliste) starten und nur die Felder der Spec
melden; neue Freigabe-Zeilen mit festen Argumenten (Fail2ban-Jail als Argumentklasse), Fallen als Negativtest. Formate
vorher an `wg(8)`, fail2ban, `cscli`, Tailscale belegt (Quelle im Kommentar). Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T9

### T2 — R-1236: Ansichten openvpn_status, keepalived_vips  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_vpn.go, apps/agent/internal/probe/app_vpn_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @475a55ed3 2026-11-13T13:04:20+01:00
Review: approve (.ah-out/review/kern-monitoring-10/T2.verdict.json)
Änderung: OpenVPN: Statusdatei der Unit-Instanz (Pfad aus dem Instanznamen, keine freien Pfade), `clients` und
`updated_age_s`; Keepalived: nur `virtual_ipaddress` aus keepalived.conf gegen die lokalen Interface-Adressen, nie
`auth_pass` oder andere Inhalte. Datei-Zugriffe über Seams, Obergrenzen je Datei. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T9

### T3 — R-1236: Module wireguard, openvpn, fail2ban, crowdsec, keepalived, tailscale, headscale  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/wireguard.py, apps/monitoring/app/catalog/modules/openvpn.py, apps/monitoring/app/catalog/modules/fail2ban.py, apps/monitoring/app/catalog/modules/crowdsec.py, apps/monitoring/app/catalog/modules/keepalived.py, apps/monitoring/app/catalog/modules/tailscale.py, apps/monitoring/app/catalog/modules/headscale.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_catalog_netsec.py, apps/monitoring/app/discovery.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @b40ab2602 2026-11-13T13:17:45+01:00
Review: approve (.ah-out/review/kern-monitoring-10/T3.verdict.json)
Änderung: Ansichten aus T1/T2 in `APP_VIEW_FIELDS`/`APP_VIEW_TARGETS`/`AppParams`; sieben Module mit Erkennung,
Instanz, Checks, Regeln und Karte nach Spec; Test je Modul mit Inventar-Fixture und je Regel an der Schwelle. Mehr als
acht Dateien: Module sind kleine Datendateien desselben Musters, ein Verify.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_netsec.py tests/test_catalog_sensors.py
Doku: → T9
Abhängt von: T1, T2

### T4 — R-1237: Ansichten bind_status, unbound_stats, chrony_tracking, ntpsec_status  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_dns.go, apps/agent/internal/probe/app_dns_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @b2d80bfdd 2026-11-13T13:28:00+01:00
Review: approve (.ah-out/review/kern-monitoring-10/T4.verdict.json)
Änderung: vier Ansichten über feste Lesekommandos (`rndc status`, `unbound-control stats_noreset`, `chronyc -c
tracking`, `ntpq -c rv`); Fallen (`unbound-control stats`, `rndc stats`, `chronyc makestep|burst`) als Negativtest.
Formate vorher an BIND ARM, `unbound-control(8)`, `chronyc(1)`, NTPsec belegt. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T9

### T5 — R-1237: Ansichten kea_pools, dnsmasq_leases  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_dhcp.go, apps/agent/internal/probe/app_dhcp_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @3a143e6bc 2026-11-13T13:46:15+01:00
Review: approve (.ah-out/review/kern-monitoring-10/T5.verdict.json)
Änderung: Kea über den Steuersocket (`dialUnix`, nur `status-get` und `statistic-get-all`, nie `config-get`),
Pool-Auslastung je Subnetz als Maximum; dnsmasq: Lease-Datei zählen, IPv4-`dhcp-range` aus der Konfiguration
summieren. Formate vorher an Kea ARM und `dnsmasq(8)` belegt. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T9

### T6 — R-1237: Module bind, unbound, pihole, adguard, kea, dnsmasq, isc-dhcp-server, chrony, ntpsec  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/bind.py, apps/monitoring/app/catalog/modules/unbound.py, apps/monitoring/app/catalog/modules/pihole.py, apps/monitoring/app/catalog/modules/adguard.py, apps/monitoring/app/catalog/modules/kea.py, apps/monitoring/app/catalog/modules/dnsmasq.py, apps/monitoring/app/catalog/modules/isc_dhcp_server.py, apps/monitoring/app/catalog/modules/chrony.py, apps/monitoring/app/catalog/modules/ntpsec.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_catalog_dns.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @2fa103e59 2026-11-13T13:58:17+01:00
Review: approve (.ah-out/review/kern-monitoring-10/T6.verdict.json)
Änderung: Ansichten aus T4/T5 im Katalog; neun Module nach Spec (Pi-hole/AdGuard nur DNS-Probe, Unit/Container,
Gravity-Alter; isc-dhcp-server mit EOL-Hinweis im Modultext); Tests wie T3. Mehr als acht Dateien: wie T3.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_dns.py tests/test_catalog_sensors.py
Doku: → T9
Abhängt von: T4, T5

### T7 — R-1238: Ansichten caddy_upstreams, proxy_certs  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_proxy.go, apps/agent/internal/probe/app_proxy_test.go, apps/agent/internal/probe/sensor_app_test.go, apps/agent/internal/probe/app_proxy_linux_test.go, apps/agent/internal/probe/app_dhcp_test.go, apps/agent/internal/probe/app_dns_test.go, apps/agent/internal/probe/app_vpn_test.go, apps/agent/internal/probe/app_net_test.go
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @6adff700b 2026-11-13T14:23:03+01:00
Review: approve (.ah-out/review/kern-monitoring-10/T7.verdict.json)
Änderung: Caddy-Admin-API nur `GET /reverse_proxy/upstreams` auf Loopback (Ziel-Wächter, Obergrenze); `proxy_certs`
mit festem Parameter `source` (`caddy`, `traefik`, `npm`): liest nur Zertifikate (bei Traefik das Feld `certificate`
aus `acme.json`, nie `key`), meldet `certs`, `min_days_left`, `expired`; Container-Quellen über `/proc/<pid>/root` wie
`wordpress_version`. Test: Schlüsselmaterial erscheint nie in Feldern oder Fehlern. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T9

### T8 — R-1238: Module caddy, traefik, npm, squid  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/caddy.py, apps/monitoring/app/catalog/modules/traefik.py, apps/monitoring/app/catalog/modules/npm.py, apps/monitoring/app/catalog/modules/squid.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_catalog_proxies.py, apps/monitoring/app/catalog/model.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @f1b592b5e 2026-11-13T14:31:27+01:00
Review: approve (.ah-out/review/kern-monitoring-10/T8.verdict.json)
Änderung: Ansichten aus T7 (mit `source`) im Katalog; vier Module nach Spec (Traefik `/ping` ohne Regel, Squid über
die tatsächlichen Ports und `squid-internal-mgr/info` auf Loopback); Tests wie T3.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_proxies.py tests/test_catalog_sensors.py
Doku: → T9
Abhängt von: T7

### T9 — Doku: Module, Ansichten, nie gerufene Kommandos (DE + EN)  [x]
Komponente: scripts · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-monitoring-10.md, docs/developer/monitoring.html, docs/en/developer/monitoring.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @aac5088a2 2026-11-13T14:36:06+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Unterabschnitte je Gruppe unter „Module und Erkennung“ mit Voraussetzungen und Mindestversion, Liste „Nie
aufgerufen“ ergänzt, Ansichten des Fühlers `app` in der Entwickler-Doku, Changelog-Fragment (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende
Abhängt von: T3, T6, T8

### T10 — R-1236: Keepalived-VIP-Besitz über Hosts  [~] (verschoben in eigene Zeile R-1434 (neu, wartet auf Kevin): VIP-Besitz ueber Hosts; dieser Zug liefert vips/held je Host)
Komponente: monitoring · Dateien: —
Änderung: je nach Antwort: eigene Zeile anlegen und `[~]`, oder Server-Regel über mehrere Checks planen.
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: → T9

## Entscheidungen
- Lesekommandos (root) über die Freigabeliste in Ansichten des Fühlers `app`: das Konzept nennt sie mit Zugang root (§6.9), die Freigabeliste ist der Mechanismus aus §3.13; kein exec als Anwendungs-Benutzer, kein `docker exec` (die andere Risikoklasse aus R-1404).
- T1: `wg_peers` zählt als veraltet nur Peers mit persistent keepalive (nur sie handshaken verlässlich alle zwei Minuten; ein ruhender Road-Warrior ist kein Fehler), ein Keepalive-Peer ohne Handshake zählt zu `stale_crit`; die Unit `wg-quick@<if>` engt auf ihr Interface ein (keine neue Argumentklasse, `wg show all …` gefiltert). `fail2ban`: ein nicht antwortender Server ist ein Wert (`responding` false), kein Fehler; mehr als 32 Jails ist ein Fehler statt unvollständiger Zahlen. `tailscale status --json --peers=false` (Flag aus `cli/status.go`), Peers bleiben ungelesen.
- T2: `openvpn_status` nur für `openvpn-server@<i>` (Statusdatei des Upstream-Units, Instanzname ohne `/`, sonst ErrInvalid; andere Units ErrUnsupported), Version 1 nimmt die mtime (ihr Zeitstempel ist lokale Zeit ohne Zone), eine Datei ohne `END`/`TIME` ist ein Fehler. `keepalived_vips` liest `virtual_ipaddress` und `virtual_ipaddress_excluded` (beide sind VIPs der Instanz), eindeutige Adressen; `include` nur absolut (Glob), höchstens 64 Dateien und Tiefe 8; relative Includes, Bereiche (`a-b`), Zonen und unbekannte Formen sind Fehler, die nichts aus der Datei zitieren; fehlt die Konfiguration am Standardpfad: ErrUnsupported.
- T3: Erkennung nimmt eine Template-Unit (`wg-quick@.service`) für jede ihrer Instanzen (`discovery.py` `_unit_wanted`; das Template selbst nie), jede Instanz ist eine Instanz des Moduls. CrowdSec `stale_bouncers gt 0` → warning statt critical: LAPI erneuert `last_pull` nur bei Abfragen (Stream je Poll, Live höchstens minütlich je gefilterter Anfrage, `controllers/v1/decisions.go`, `database/bouncers.go`), ein Live-Bouncer auf ruhigem Host veraltet ohne Fehler. Tailscale: Schlüsselablauf als eigene Prüfung (stündlich); ohne Ablauf bleibt sie unknown (Modultext). Headscale: GET `/health` (pingt die DB, `hscontrol/handlers.go`), Port-Hinweis 8080 aus der Doku, Images ohne eigenen HEALTHCHECK. keepalived ohne Regel (Rolle bestimmt `held`).
- T4: `bind_status`: ein `rndc status` mit Exit ≠ 0 ist ein Wert (`running` false), wie fail2ban; `recursive_limit` ist das dritte Feld (max, `named_server_status`). `unbound_stats`: Zähler seit dem Start (`stats_noreset`), `servfail_pct` nur mit `statistics-extended` (die rcode-Zeilen druckt `print_ext` nur dann), sonst fehlt das Feld. `chrony_tracking`: Offset = Feld 5 (System time, Sekunden), synchron außer bei Leap `Not synchronised`/`Invalid` (`client.c` `print_report`). `ntpsec_status`: `ntpq -c "rv 0 leap,stratum,offset"` liest nur die drei Systemvariablen (Syntax `ntpq.html`), Offset in ms, Leap `11` oder Stratum 16 = nicht synchron; Leap als Ziffer wird mitgenommen (Anzeige nicht belegt).
- T5: `kea_pools` schickt nur `statistic-get-all` (ein Kommando reicht; `status-get` brächte kein Feld), liest je Statistik die neueste Probe, Auslastung je Subnetz aus `subnet[id].total-/assigned-addresses` (Pool-Zähler nicht), Subnetze ohne Adressen ohne Anteil, `alloc_fail` nur, wenn Kea `v4-allocation-fail` führt; Antwort als Objekt oder Liste eines Objekts (Control Agent), Ergebnis ≠ 0 ist ein Fehler ohne Kea-Text. Socket `/run/kea/kea4-ctrl-socket`, dann `/var/run/kea/…`: `socket-name` der Debian-Konfiguration plus `RuntimeDirectory=kea` der Unit (isc-kea 2.6.3); wie Kea den relativen Namen auflöst, ist nicht verifiziert, ein anderer Pfad heißt ErrUnsupported. `dnsmasq_leases`: Lease-Format aus `lease.c` (2.91, Debian), gezählt werden IPv4-Zeilen ohne Ablaufprüfung (dnsmasq schreibt nach dem Prune; mit `HAVE_BROKEN_RTC` stünde dort die Dauer); `used_pct` = Leases in dynamischen Bereichen / Bereichsgröße (überlappende Bereiche einmal), statische Leases zählen nur in `leases`. Konfiguration: Datei, `conf-file`, `conf-dir` (`*.ext` nur diese, `.ext` ohne diese, Sonderdateien `~`/`.`/`#…#` aus), unter Linux zusätzlich `/etc/dnsmasq.d` (Debian setzt es per `/etc/default/dnsmasq`, nicht in der Datei), `dhcp-leasefile` nur absolut; `DHCP_LEASE` in `/etc/default/dnsmasq` wird nicht gelesen. Kommentare und Anführungszeichen wie `option.c` `read_file` (`#` am Anfang oder nach Leerraum außerhalb von Anführungszeichen; Verhalten mit `dnsmasq --test` 2.91 gegengeprüft); ein dnsmasq ohne `dhcp-range` (nur DNS, keine Lease-Datei) ist ErrUnsupported statt kritisch.
- T6: Pi-hole/AdGuard prüfen „DNS“ als `socket`-Check auf Port 53 (lauscht, critical sonst), keine echte Anfrage: der `dns`-Sensor des Agents fragt nur den Resolver des Hosts (`net.DefaultResolver`), nicht den Dienst; eine Anfrage an den Dienst selbst braucht eine Agent-Änderung (Roadmap-Zeile, `neu`). Gravity-Alter: `file_age` auf `/etc/pihole/gravity.db` täglich, > 14 Tage warning (Pi-hole erneuert wöchentlich); im Container liegt die Datei in einem Volume, der Check bleibt dort unknown (Modultext). Unbound: eine Regel auf `servfail_pct`, ohne erweiterte Statistik oder ohne Anfrage unknown (Modultext). Units an den Quellen geprüft (Debian trixie: `named.service` mit Alias bind9, `chrony.service` mit Alias chronyd, RHEL `chronyd.service`, `ntpsec.service` (Debian benennt `ntpd.service` um), `kea-dhcp4-server.service`, `isc-dhcp-server.service` aus dem Init-Skript; Pi-hole-Installer `pihole-FTL.service`, AdGuard `AdGuardHome.service`); RHEL-Namen für Kea und NTPsec nicht aufgenommen (nicht verifiziert). Schwellen Kea/dnsmasq mit `ge` (80/95 %), Zeit mit `gt` (100/1000 ms).
- T7: statt `proxy_certs` mit Parameter `source` drei Ansichten `caddy_certs`, `traefik_certs`, `npm_certs` (gleicher Code, kein neuer Parameterweg; der Server nennt eine Ansicht, nie einen Pfad); Ansichten tragen jetzt eine Liste von Zielarten (`appView.kinds`), Zertifikate von Caddy und Traefik lesen Unit (Wurzel des Hosts) oder Container (`/proc/<pid>/root`), NPM nur Container. Felder `certs`, `expired`, `min_days_left` (abgerundete Tage, negativ wenn abgelaufen; fehlt ohne Zertifikat). Caddy: Datenverzeichnis `data/caddy` (Image), `var/lib/caddy/.local/share/caddy` (Pakete), `root/.local/share/caddy`, Ablage `certificates/<issuer>/<site>/<site>.crt` (certmagic), Aussteller `local` (eigene CA, 12-h-Zertifikate) ausgenommen, `.key`/`.json` ungelesen; Fehler nennen den Aussteller-Ordner, nie die Site (eine Domain). Traefik: `acme.json` an den Orten aus Doku und üblichen Setups, nur `Certificates[].certificate` (base64-PEM) dekodiert, nie `key` oder Account. NPM: `etc/letsencrypt/live/npm-<id>/fullchain.pem` (certbot-Link, nur relativ und unterhalb `etc/letsencrypt`, ein Glied) und `data/custom_ssl/npm-<id>/fullchain.pem`; `live/npm-<id>` aus NPMs `getLiveCertPath` nicht verifiziert. Dateien nur über `openRegular` (kein Link, keine FIFO), Obergrenzen 1 MiB je Zertifikat, 16 MiB `acme.json`, 10 000 Einträge. Kurzlebige ACME-Zertifikate (6 Tage) lägen immer unter 14 Tagen (Doku T9). `caddy_upstreams` nur als Unit: im Container lauscht die Admin-API auf localhost im Netz des Containers; Port = Hinweis oder 2019, aufgelöster Port muss gleich sein und auf Loopback liegen, GET `/reverse_proxy/upstreams`, `upstreams` = Anzahl, `failing` = `fails > 0`, nie Adressen. Gegen `caddy:2` (v2.11.9) geprüft: Antwortform, Standard-Admin 127.0.0.1:2019 nimmt Host `127.0.0.1:2019`, `fails` zählt nur mit passivem Health-Check (`fail_duration`), sonst immer 0 (Doku T9). Prüfer T7: eine leere `acme.json` (Traefik v3.7 legt sie beim Start mit 0 Byte an, gegen `traefik:v3` geprüft) gilt als Store ohne Zertifikate, nicht als Fehler. Traefik `/ping` antwortet nur mit `--ping=true` (dann 200 auf :8080), sonst lauscht :8080 nicht.
- T8: `APP_VIEW_TARGETS` trägt je Ansicht eine Menge von Zielarten (Spiegel von `appView.kinds`); Fehlermeldung nennt die sortierte Liste. Caddy und Traefik je Container- und Unit-Checks mit eigenen Schlüsseln (Muster Pi-hole), `upstreams` nur Unit mit `port_hint` 2019; Traefik `/ping` (Port 8080) ohne Regel auf beiden Arten. Ohne Zertifikat fehlt `min_days_left`, die Prüfung ist dann unknown (wie Unbound ohne Abfragen; Doku T9). Squid: Unit, Socket mit Hinweis 3128 (nur `listening` als Regel, ein anderer einzelner Port ist kein Befund), HTTP GET `/squid-internal-mgr/info` alle 900 s, nicht 200 → warning; gegen `ubuntu/squid` (Squid 6.13) geprüft: GET und HEAD über Loopback 200. Verweigert der Manager (403, `cachemgr_passwd` 401), meldet der Agent `error` (sensor_http.go, für alle HTTP-Checks) und der Check ist critical; dokumentiert statt eines Squid-Sonderfalls im Agent (Prüferfund T8 Runde 1).
