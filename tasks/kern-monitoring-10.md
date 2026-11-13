<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Module Netz, Sicherheit, DNS, DHCP, Zeit und Reverse-Proxies — Task-Ledger
Status: aktiv · Branch: feature/kern-monitoring-10 · Review: pro Task
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

### T2 — R-1236: Ansichten openvpn_status, keepalived_vips  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_vpn.go, apps/agent/internal/probe/app_vpn_test.go
Änderung: OpenVPN: Statusdatei der Unit-Instanz (Pfad aus dem Instanznamen, keine freien Pfade), `clients` und
`updated_age_s`; Keepalived: nur `virtual_ipaddress` aus keepalived.conf gegen die lokalen Interface-Adressen, nie
`auth_pass` oder andere Inhalte. Datei-Zugriffe über Seams, Obergrenzen je Datei. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T9

### T3 — R-1236: Module wireguard, openvpn, fail2ban, crowdsec, keepalived, tailscale, headscale  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/wireguard.py, apps/monitoring/app/catalog/modules/openvpn.py, apps/monitoring/app/catalog/modules/fail2ban.py, apps/monitoring/app/catalog/modules/crowdsec.py, apps/monitoring/app/catalog/modules/keepalived.py, apps/monitoring/app/catalog/modules/tailscale.py, apps/monitoring/app/catalog/modules/headscale.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_catalog_netsec.py
Änderung: Ansichten aus T1/T2 in `APP_VIEW_FIELDS`/`APP_VIEW_TARGETS`/`AppParams`; sieben Module mit Erkennung,
Instanz, Checks, Regeln und Karte nach Spec; Test je Modul mit Inventar-Fixture und je Regel an der Schwelle. Mehr als
acht Dateien: Module sind kleine Datendateien desselben Musters, ein Verify.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_netsec.py tests/test_catalog_sensors.py
Doku: → T9
Abhängt von: T1, T2

### T4 — R-1237: Ansichten bind_status, unbound_stats, chrony_tracking, ntpsec_status  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_dns.go, apps/agent/internal/probe/app_dns_test.go, apps/agent/internal/allowlist/allowlist.go, apps/agent/internal/allowlist/allowlist_test.go
Änderung: vier Ansichten über feste Lesekommandos (`rndc status`, `unbound-control stats_noreset`, `chronyc -c
tracking`, `ntpq -c rv`); Fallen (`unbound-control stats`, `rndc stats`, `chronyc makestep|burst`) als Negativtest.
Formate vorher an BIND ARM, `unbound-control(8)`, `chronyc(1)`, NTPsec belegt. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T9

### T5 — R-1237: Ansichten kea_pools, dnsmasq_leases  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_dhcp.go, apps/agent/internal/probe/app_dhcp_test.go
Änderung: Kea über den Steuersocket (`dialUnix`, nur `status-get` und `statistic-get-all`, nie `config-get`),
Pool-Auslastung je Subnetz als Maximum; dnsmasq: Lease-Datei zählen, IPv4-`dhcp-range` aus der Konfiguration
summieren. Formate vorher an Kea ARM und `dnsmasq(8)` belegt. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T9

### T6 — R-1237: Module bind, unbound, pihole, adguard, kea, dnsmasq, isc-dhcp-server, chrony, ntpsec  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/bind.py, apps/monitoring/app/catalog/modules/unbound.py, apps/monitoring/app/catalog/modules/pihole.py, apps/monitoring/app/catalog/modules/adguard.py, apps/monitoring/app/catalog/modules/kea.py, apps/monitoring/app/catalog/modules/dnsmasq.py, apps/monitoring/app/catalog/modules/isc_dhcp_server.py, apps/monitoring/app/catalog/modules/chrony.py, apps/monitoring/app/catalog/modules/ntpsec.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_catalog_dns.py
Änderung: Ansichten aus T4/T5 im Katalog; neun Module nach Spec (Pi-hole/AdGuard nur DNS-Probe, Unit/Container,
Gravity-Alter; isc-dhcp-server mit EOL-Hinweis im Modultext); Tests wie T3. Mehr als acht Dateien: wie T3.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_dns.py tests/test_catalog_sensors.py
Doku: → T9
Abhängt von: T4, T5

### T7 — R-1238: Ansichten caddy_upstreams, proxy_certs  [ ]
Komponente: agent · Dateien: apps/agent/internal/probe/sensor_app.go, apps/agent/internal/probe/app_proxy.go, apps/agent/internal/probe/app_proxy_test.go
Änderung: Caddy-Admin-API nur `GET /reverse_proxy/upstreams` auf Loopback (Ziel-Wächter, Obergrenze); `proxy_certs`
mit festem Parameter `source` (`caddy`, `traefik`, `npm`): liest nur Zertifikate (bei Traefik das Feld `certificate`
aus `acme.json`, nie `key`), meldet `certs`, `min_days_left`, `expired`; Container-Quellen über `/proc/<pid>/root` wie
`wordpress_version`. Test: Schlüsselmaterial erscheint nie in Feldern oder Fehlern. Neue Dateien mit SPDX-Header.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T9

### T8 — R-1238: Module caddy, traefik, npm, squid  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/catalog/sensors.py, apps/monitoring/app/catalog/modules/caddy.py, apps/monitoring/app/catalog/modules/traefik.py, apps/monitoring/app/catalog/modules/npm.py, apps/monitoring/app/catalog/modules/squid.py, apps/monitoring/tests/test_catalog_sensors.py, apps/monitoring/tests/test_catalog_proxies.py
Änderung: Ansichten aus T7 (mit `source`) im Katalog; vier Module nach Spec (Traefik `/ping` ohne Regel, Squid über
die tatsächlichen Ports und `squid-internal-mgr/info` auf Loopback); Tests wie T3.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_catalog_proxies.py tests/test_catalog_sensors.py
Doku: → T9
Abhängt von: T7

### T9 — Doku: Module, Ansichten, nie gerufene Kommandos (DE + EN)  [ ]
Komponente: docs · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, changelog.d/kern-monitoring-10.md
Änderung: Unterabschnitte je Gruppe unter „Module und Erkennung“ mit Voraussetzungen und Mindestversion, Liste „Nie
aufgerufen“ ergänzt, Ansichten des Fühlers `app` in der Entwickler-Doku, Changelog-Fragment (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende
Abhängt von: T3, T6, T8

### T10 — R-1236: Keepalived-VIP-Besitz über Hosts  [?] (Hosts-übergreifende Regel jetzt bauen oder eigene Zeile? Empfehlung: eigene FEAT-Zeile, dieser Zug liefert vips/held je Host)
Komponente: monitoring · Dateien: —
Änderung: je nach Antwort: eigene Zeile anlegen und `[~]`, oder Server-Regel über mehrere Checks planen.
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: → T9

## Entscheidungen
- Lesekommandos (root) über die Freigabeliste in Ansichten des Fühlers `app`: das Konzept nennt sie mit Zugang root (§6.9), die Freigabeliste ist der Mechanismus aus §3.13; kein exec als Anwendungs-Benutzer, kein `docker exec` (die andere Risikoklasse aus R-1404).
- T1: `wg_peers` zählt als veraltet nur Peers mit persistent keepalive (nur sie handshaken verlässlich alle zwei Minuten; ein ruhender Road-Warrior ist kein Fehler), ein Keepalive-Peer ohne Handshake zählt zu `stale_crit`; die Unit `wg-quick@<if>` engt auf ihr Interface ein (keine neue Argumentklasse, `wg show all …` gefiltert). `fail2ban`: ein nicht antwortender Server ist ein Wert (`responding` false), kein Fehler; mehr als 32 Jails ist ein Fehler statt unvollständiger Zahlen. `tailscale status --json --peers=false` (Flag aus `cli/status.go`), Peers bleiben ungelesen.
