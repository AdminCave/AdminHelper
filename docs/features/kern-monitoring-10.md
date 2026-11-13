<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-10 — Katalog-Module für Netz, Sicherheit, DNS, DHCP, Zeit und Reverse-Proxies

Roadmap: R-1236, R-1237, R-1238 (FEAT, Kevin 2026-11-09, Monitoring-Konzept, vor 0.47.0). Ledger:
`tasks/kern-monitoring-10.md`. Baut auf dem Modul-Katalog (R-1223, `docs/features/arch-monitoring-module.md`), den
App-Modulen (`docs/features/arch-monitoring-apps-1.md`) und dem Fühler `app` (R-1404,
`docs/features/arch-monitoring-app-collector.md`) auf.

## Problem / Motivation
Läuft auf einem Host ein VPN, ein Schutzdienst, ein DNS-/DHCP-/Zeitserver oder ein Reverse-Proxy, sieht AdminHelper
heute nur seine Ports (`port`-Instanzen) und seine Unit (linux-base). Ob WireGuard-Peers noch Handshakes machen,
fail2ban noch antwortet, der CrowdSec-Bouncer noch Entscheidungen abholt, chrony synchron ist, ein Kea-Pool vollläuft
oder ein von Caddy/Traefik verwaltetes Zertifikat abläuft, erfährt niemand. Die drei Zeilen verlangen Module für:

- **R-1236 Netz und Sicherheit:** WireGuard (Handshake nur bei Peers mit Keepalive, nie `dump`), OpenVPN
  (Statusdatei, nie Management-Schnittstelle), fail2ban, CrowdSec, Keepalived (VIP-Besitz über Hosts),
  Tailscale/Headscale.
- **R-1237 DNS, DHCP, Zeit:** BIND (`rndc status`), Unbound (`stats_noreset`), Pi-hole, AdGuard Home, Kea
  (Pool-Auslastung), dnsmasq, isc-dhcp-server (EOL-Befund), chrony/NTPsec.
- **R-1238 Reverse-Proxies:** Caddy, Traefik, Nginx Proxy Manager (Zertifikate nur notAfter), Squid (tatsächliche
  Ports, cache manager über localhost).

Leitplanken (Konzept §3.8, §3.13, Kevin 2026-11-09): der Dienst verliert nie spürbar Leistung; der Agent fragt nur
seinen eigenen Host; der Server schickt nur Parameter; ein Programm startet der Agent nur aus der Freigabeliste mit
festen Argumenten; zum Server gehen nur Felder der Katalog-Allowlist (Zahlen, Wahrheitswerte, Zustände), nie Namen,
Schlüssel, Adressen fremder Hosts oder Konfigurationsinhalte.

## Ziel & Nicht-Ziele
**Ziel:** je Dienst ein Modul unter `apps/monitoring/app/catalog/modules/` (Erkennung, Instanz, Checks, Karte), das
vorhandene Fühler nutzt (Unit, Prozess, Container, Socket, HTTP, DNS, Dateialter) und, wo der Dienst sein Innenleben
nur über ein Lesekommando, eine Statusdatei oder einen lokalen Socket zeigt, neue Ansichten des Fühlers `app`.

Neue Ansichten (Entwurf; Formate, Pfade und Felder belegt jede Agent-Task an der offiziellen Doku bzw. am Quelltext
und nennt die Quelle im Kommentar; Unbelegtes fährt nicht mit oder steht als „nicht verifiziert“ in der Task):

| Ansicht | Ziel | Quelle (lesend) | Felder (Entwurf) |
|---|---|---|---|
| `wg_peers` | unit | `wg show all latest-handshakes`, `wg show all persistent-keepalive` (nie `dump`, nie `showconf`) | `interfaces`, `peers`, `keepalive_peers`, `stale_warn` (> 300 s), `stale_crit` (> 900 s), `max_handshake_age_s` |
| `fail2ban` | unit | `fail2ban-client ping`, `fail2ban-client status`, `fail2ban-client status <jail>` | `responding`, `jails`, `banned_total`, `max_banned`, `jails_without_files` |
| `crowdsec_bouncers` | unit | `cscli bouncers list -o json` | `bouncers`, `stale_bouncers` (letzter Abruf > 10 min), `max_pull_age_s` |
| `tailscale_status` | unit | `tailscale status --json` (nie `netcheck` im Takt) | `backend_running`, `health_warnings`, `key_expiry_days` |
| `openvpn_status` | unit | Statusdatei der Instanz (`openvpn-server@<i>`: `/run/openvpn-server/status-<i>.log`) | `clients`, `updated_age_s` |
| `keepalived_vips` | unit | `/etc/keepalived/keepalived.conf` (nur `virtual_ipaddress`), Adressen der lokalen Interfaces | `vips`, `held` |
| `bind_status` | unit | `rndc status` | `running`, `zones`, `recursive_clients`, `recursive_limit` |
| `unbound_stats` | unit | `unbound-control stats_noreset` (nie `stats`: setzt die Zähler zurück) | `queries`, `requestlist_exceeded`, `servfail_pct` |
| `chrony_tracking` | unit | `chronyc -c tracking` | `synced`, `stratum`, `offset_abs_ms` |
| `ntpsec_status` | unit | `ntpq -c rv` (nur `leap`, `stratum`, `offset`) | `synced`, `stratum`, `offset_abs_ms` |
| `kea_pools` | unit | Kea-Steuersocket: `status-get`, `statistic-get-all` (nie `config-get`: Klartext-Passwörter) | `subnets`, `max_pool_used_pct`, `alloc_fail` |
| `dnsmasq_leases` | unit | Lease-Datei, `dhcp-range` aus der dnsmasq-Konfiguration | `leases`, `range_size`, `used_pct` |
| `caddy_upstreams` | unit/container | Admin-API `GET /reverse_proxy/upstreams` auf Loopback (nie `/config/`: enthält Geheimnisse) | `upstreams`, `failing` |
| `proxy_certs` | unit/container | Zertifikate aus dem Datenverzeichnis von Caddy, `acme.json` von Traefik, `letsencrypt/live` von NPM; gelesen wird nur `notAfter`, nie ein Schlüssel | `certs`, `min_days_left`, `expired` |

Module (Erkennung über Unit, Prozess, Container-Image; Instanz Unit bzw. Container):

| Zeile | Modul-IDs | Checks (Entwurf) |
|---|---|---|
| R-1236 | `wireguard` | Unit `wg-quick@<if>`, `wg_peers` (Regeln: `stale_crit gt 0` → critical, `stale_warn gt 0` → warning) |
| R-1236 | `openvpn` | Unit `openvpn-server@<i>`, `openvpn_status` (`updated_age_s` > 3 × Statusintervall → warning) |
| R-1236 | `fail2ban` | Unit, `fail2ban` (`responding` false → critical; `jails_without_files gt 0` → warning; `max_banned gt 10000` → warning) |
| R-1236 | `crowdsec` | Unit/Container, `crowdsec_bouncers` (`stale_bouncers gt 0` → critical) |
| R-1236 | `keepalived` | Unit, `keepalived_vips` (Zahl gehaltener VIPs je Host); der Vergleich über Hosts → T10 `[?]` |
| R-1236 | `tailscale`, `headscale` | Unit `tailscaled`, `tailscale_status` (`backend_running` false → critical, `key_expiry_days lt 14` → warning); Headscale: Unit/Container, HTTP `/health` |
| R-1237 | `bind`, `unbound` | Unit `named`/`bind9`, `bind_status`; Unit `unbound`, `unbound_stats` (`servfail_pct gt 5` → warning) |
| R-1237 | `pihole`, `adguard` | Unit/Container, DNS-Probe gegen den eigenen Resolver (5 min); Pi-hole: Alter der Gravity-Datenbank (Dateialter, täglich) |
| R-1237 | `kea`, `dnsmasq`, `isc-dhcp-server` | Kea: Unit, `kea_pools` (80 % warning, 95 % critical); dnsmasq: Unit, `dnsmasq_leases` (dieselben Schwellen); isc-dhcp-server: Unit, im Modultext und in der Doku als seit Ende 2022 nicht mehr gepflegt markiert |
| R-1237 | `chrony`, `ntpsec` | Unit, `chrony_tracking` bzw. `ntpsec_status` (`synced` false → critical; `offset_abs_ms gt 100` → warning, `gt 1000` → critical) |
| R-1238 | `caddy`, `traefik`, `npm` | Unit/Container; Caddy `caddy_upstreams` (`failing gt 0` → warning); Traefik `/ping` ohne Regel (die API ist oft aus, kein Befund); alle drei `proxy_certs` täglich (`min_days_left lt 14` → warning, `expired gt 0` → critical) |
| R-1238 | `squid` | Unit/Prozess, Sockets der tatsächlichen Ports, HTTP `squid-internal-mgr/info` über Loopback (15 min) |

**Nicht-Ziele (YAGNI):**
- Keine täglichen Konfigurationstests (`named-checkconf`, `unbound-checkconf`, `keepalived -t`, `squid -k check`,
  `fail2ban-client -t`, `dnsmasq --test`): eigene Zeile, am Gate angelegt. Sie starten schwerere Programme, und
  einige schreiben Dateien (`dhcpd -T`).
- Keine Zertifikats-/CRL-Abläufe von OpenVPN (Pfade stehen nur in der Konfiguration), kein WireGuard-`transfer`,
  keine CrowdSec-Quellen ohne geparste Zeilen, kein BIND-Statistikkanal, keine CHAOS-Statistik von dnsmasq: alles
  eigene Zeilen, falls gewünscht.
- Pi-hole/AdGuard ohne API: Pi-hole v6 hat 16 Sitzungsplätze, jede Anmeldung belegt einen; AdGuard sperrt nach
  Fehlversuchen. Blocking-Status über die API ist eine eigene Zeile.
- Keine Änderung an Web- oder Desktop-UI (ein neues Modul braucht dort nichts, R-1404).

## Betroffene Komponenten & Dateien
| Komponente | Dateien |
|---|---|
| Agent | `apps/agent/internal/probe/sensor_app.go` (`appViews`, `:26`), neu `app_net.go` (WireGuard, fail2ban, CrowdSec, Tailscale), `app_vpn.go` (OpenVPN, Keepalived), `app_dns.go` (BIND, Unbound, chrony, NTPsec), `app_dhcp.go` (Kea, dnsmasq), `app_proxy.go` (Caddy, Zertifikate), je mit `_test.go`; `apps/agent/internal/allowlist/allowlist.go` (`commands`, `:152`) und `allowlist_test.go` (neue Kommandos, Fallen-Negativtests) |
| Monitoring-Katalog | `apps/monitoring/app/catalog/sensors.py` (`APP_VIEW_FIELDS` `:81`, `APP_VIEW_TARGETS` `:100`, `AppParams` `:244`), neu je Modul `apps/monitoring/app/catalog/modules/<id>.py` (21 Dateien, SPDX-Header; `isc_dhcp_server.py`) |
| Monitoring-Tests | `apps/monitoring/tests/test_catalog_sensors.py`, neu je Gruppe `tests/test_catalog_netsec.py`, `tests/test_catalog_dns.py`, `tests/test_catalog_proxies.py` |
| Doku | `docs/admin/monitoring.html` (Abschnitt „Module und Erkennung“, `:329`: neue Unterabschnitte je Gruppe, Liste „Nie aufgerufen“), `docs/developer/agent.html` (Ansichten des Fühlers `app`), beide EN, `changelog.d/kern-monitoring-10.md` |

## Datenmodell / API / Migrationen
Keine Migration, keine neue Route, kein Schema der Check-API. Neu sind Werte des Parameters `view` (Katalog
`AppParams` und Agent `appViews` prüfen beide). Ein Agent vor diesem Release kennt die Ansichten nicht und meldet den
Check als `unknown` (invalid parameters), bis er aktualisiert ist; die Doku nennt die Mindestversion. Die
Katalog-Version ändert sich mit jedem Modul; übernommene Instanzen betrifft das nicht.

## Externe Integrationen
Je Ansicht die offizielle Doku bzw. der Quelltext (in der Task per WebFetch gelesen, Link im Kommentar):
`wg(8)`, fail2ban `fail2ban-client`, CrowdSec `cscli bouncers list`, Tailscale `status --json`, OpenVPN
`--status`-Format (Version 1/2/3) und Debians `openvpn-server@.service`, keepalived.conf(5), BIND ARM `rndc status`,
`unbound-control(8)`, `chronyc(1)` (`-c tracking`), NTPsec `ntpq`, Kea ARM (Steuersocket, `statistic-get-all`),
`dnsmasq(8)` (Lease-Datei, `dhcp-range`), Caddy Admin-API (`/reverse_proxy/upstreams`), Traefik `acme.json` und
`/ping`, NPM-Datenverzeichnis, Squid cache manager. **Bis zur Task ist alles davon nicht verifiziert.**

## Trade-offs & Alternativen
- **Lesekommandos über die Freigabeliste statt eigener Protokoll-Implementierung** (Empfehlung): `wg`, `rndc`,
  `unbound-control`, `chronyc`, `fail2ban-client`, `cscli`, `tailscale` sprechen geschützte oder interne Protokolle
  (Netlink, rndc-HMAC, TLS-Steuerkanal, Unix-Sockets mit eigenem Format). Ein Nachbau wäre groß und fragil; die
  Freigabeliste (Konzept §3.13 Punkt 1) ist genau für feste Lesekommandos da. Die Ansichten des Fühlers `app` lasen
  bisher nur Dateien und Sockets; dieser Zug erlaubt ihnen Aufrufe über `runTool` (`sensor_local.go:59`), nie
  daran vorbei. Kosten: ein Prozessstart je Lauf, Takt 5 min oder länger.
- **Eine Ansicht `proxy_certs` für drei Proxies statt je eine:** dieselbe Arbeit (Verzeichnis lesen, PEM parsen,
  `notAfter`), verschiedene Quellen über einen festen Parameter `source` (`caddy`, `traefik`, `npm`), keine freien
  Pfade.
- **Keepalived über Hosts:** braucht Server-Logik, die die Werte mehrerer Agents vergleicht (heute rechnet jede Regel
  auf einem Check). Empfehlung: dieser Zug liefert je Host `vips`/`held`; die Hosts-übergreifende Regel („0 oder
  mehr als 1 Besitzer“) wird eine eigene Zeile → T10 `[?]`.

## Risiken & Rollback
- **Ein Kommando mit Nebenwirkung rutscht in die Liste:** jede neue Zeile hat feste Argumente; der Negativtest der
  Freigabeliste nennt die Fallen (`wg show … dump`, `wg showconf`, `unbound-control stats`, `rndc stats`,
  `chronyc makestep|burst`, `fail2ban-client unban|reload|set`, `cscli decisions add`, `tailscale netcheck`).
- **Geheimnisse:** `acme.json` und Caddys Datenverzeichnis enthalten private Schlüssel, keepalived.conf
  `auth_pass`, Kea `config-get` Passwörter. Die Ansichten lesen nur Zertifikate bzw. `virtual_ipaddress`; Tests
  prüfen, dass Schlüsselmaterial nie in Feldern oder Fehlern erscheint.
- **Falsche Regel = Daueralarm nach dem Übernehmen:** jede Regel mit Test an ihrer Schwelle; neue Checks starten
  still (Konzept §3.13 Punkt 6).
- Rollback: Module und Ansichten sind additiv; Revert der Task-Commits.

## Doku-Impact
`docs/admin/monitoring.html` + EN: neue Unterabschnitte „Netz und Sicherheit“, „DNS, DHCP und Zeit“,
„Reverse-Proxies“ mit Voraussetzungen (Agent als root, Mindestversion) und den nie gerufenen Kommandos;
`docs/developer/agent.html` + EN: neue Ansichten und Kommandos des Fühlers `app`; `changelog.d/kern-monitoring-10.md`.

## Offene Fragen
1. **Keepalived über Hosts (T10, Kevins Bereich: sichtbares Verhalten):** Empfehlung: Zeile R-1236 liefert hier
   den VIP-Besitz je Host; die Hosts-übergreifende Regel wird eine eigene FEAT-Zeile.
