# kern-monitoring-31 — tägliche Konfigurationstests (DNS, DHCP, VRRP, Proxy, fail2ban)

Roadmap: R-1432 (Kevin, Monitoring-Programm vor 0.47.0).

## Problem / Motivation
Die Module `bind`, `unbound`, `dnsmasq`, `keepalived`, `squid` und `fail2ban` prüfen Unit, Port und Statuswerte, nicht
aber, ob die Konfiguration auf der Platte noch lädt. Ein Tippfehler fällt erst beim nächsten Reload oder Neustart auf
(Paket-Update, Zertifikatserneuerung, Reboot), dann aber mit einem Ausfall. Für nginx, Apache und HAProxy leistet das
schon die Ansicht `web_config` (kern-monitoring-8): täglich der Konfigurationstest, gemeldet wird nur `config_ok`.

## Ziel & Nicht-Ziele
**Ziel:** dasselbe für die sechs Dienste. Eine neue Ansicht `service_config` des Fühlers `app` (an die Unit gebunden)
startet je Dienst genau einen Test der Freigabeliste und meldet nur `config_ok` (true/false). Die Katalogmodule bekommen
je einen Check `config` (täglich, `interval: 86400`, `config_ok eq False` → warning), wie `nginx.py`.

| Dienst (Unit) | Test | Quelle (in T1 an der offiziellen Doku zu prüfen) |
|---|---|---|
| `named.service` | `named-checkconf` (ohne `-z`: lädt keine Zonen) | BIND 9 ARM, named-checkconf(1) |
| `unbound.service` | `unbound-checkconf` | unbound-checkconf(8) |
| `keepalived.service` | `keepalived --config-test` | keepalived(8) |
| `squid.service` | `squid -k parse` | squid(8): `-k parse` liest die Konfiguration und endet; `-k check` signalisiert dagegen den laufenden Prozess |
| `fail2ban.service` | `fail2ban-client --test` | fail2ban-client(1) |
| `dnsmasq.service` | `dnsmasq --test` | dnsmasq(8) |

Die Zeile nennt `squid -k check`. Gebaut wird `-k parse`, weil nur das die Konfiguration prüft, ohne den laufenden
Dienst anzusprechen. Das bestätigt T1 an der Doku; erweist sich `-k parse` als nicht schreibfrei, fährt Squid nicht mit
(Entscheidung im Ledger, eigene Zeile).

**Nicht-Ziele:**
- die Ausgabe der Tests: Sie nennt Dateien, Zeilen und Direktiven und geht nie zum Server, wie bei `web_config`
- Zonen laden (`named-checkconf -z`, `named-checkzone`)
- Dienste in Containern (Pi-hole u. a.)
- FreeBSD/OPNsense (die Erkennung kennt dort keine Units)

## Betroffene Komponenten & Dateien
- **Agent:**
  - `apps/agent/internal/probe/app_conftest.go` (neu): `serviceConfig` nach dem Vorbild `webConfig` in `app_web.go`.
    - Exit≠0 ist ein Wert.
    - Fehlendes Binary ergibt `ErrUnsupported`.
    - Eine Unit, die die Ansicht nicht kennt, ergibt `ErrUnsupported`.
  - `apps/agent/internal/probe/sensor_app.go`: Registrierung in `appViews`.
  - `apps/agent/internal/allowlist/allowlist.go`: sechs Einträge mit genau diesen Argumenten.
  - Tests:
    - `app_conftest_test.go` (neu)
    - `allowlist_test.go`: Positivliste und Fallen, z. B. `named-checkconf -z`, `squid -k reconfigure|shutdown|check`,
      `keepalived` ohne Test-Flag, `fail2ban-client reload|stop`, `dnsmasq` ohne `--test`, `unbound-checkconf -o`.
- **Monitoring:**
  - `apps/monitoring/app/catalog/sensors.py`: Felder, Ziel, Literal.
  - Module `bind.py`, `unbound.py`, `dnsmasq.py`, `keepalived.py`, `squid.py`, `fail2ban.py`: Check `config`, Version 2.
  - Tests: `test_catalog_dns.py`, `test_catalog_netsec.py`, `test_catalog_proxies.py`.

## Datenmodell / API / Migrationen
- keine Migration
- Ein neuer Ansichtsname im Plan, den ein älterer Agent nicht kennt: Der Check bleibt `unknown` (`invalid`), wie bei jeder neuen
  Ansicht (Doku `docs/admin/monitoring.html`, Sensor `app`). Schon übernommene Instanzen bekommen den Check still
  (Katalogversion, `module_sync.py`).

## Externe Integrationen
Die sechs Programme, siehe Tabelle. Die Schreibfreiheit jedes Aufrufs belegt T1 an der offiziellen Manpage bzw. Doku. Bis
dahin gilt sie als nicht verifiziert.

## Trade-offs & Alternativen
- **Eine Ansicht für sechs Dienste statt sechs Ansichten:** Gewählt ist eine Ansicht, `service_config`. Sie ist wie
  `web_config` an den Unit-Namen gebunden, das spart sechs Registrierungen und sechs Feldmengen. Eine Erweiterung von
  `web_config` scheidet aus, weil sie Server- und Dienst-Tests im Namen vermischte.
- **Intervall:** täglich, wie `web_config`. Die Tests lesen die Konfiguration, kosten Millisekunden bis Sekunden und
  laufen nie öfter (Kevin 2026-11-09: keine Dienst-Leistung kosten).

## Risiken & Rollback
- **Alte Versionen:** Ein altes keepalived ohne `--config-test` endet mit Exit≠0 und meldete einen falschen Fehler.
  - T1 prüft die Version, ab der es das Flag gibt.
  - Fehlt das Flag, meldet die Ansicht `unsupported` (Ausgabe „unrecognized option“ o. ä. über den Exit-Code allein nicht
    unterscheidbar).
  - Notfalls bleibt keepalived draußen (Entscheidung im Ledger).
- **Ausgabe:** Ein Test könnte mehr tun als lesen. Gegenmittel: nur Aufrufe, deren Schreibfreiheit die Doku belegt, und
  die Freigabeliste mit festen Argumenten.
- **Rollback:** Revert des Merge-Commits. Der Check verschwindet mit der Katalogversion still wieder.

## Doku-Impact
- `docs/admin/monitoring.html` DE+EN: die sechs Modulzeilen bekommen den täglichen Test. Bei Squid entfällt „Nicht
  abgedeckt: der Konfigurationstest“.
- `docs/developer/agent.html` DE+EN: die Ansicht in der Liste des Fühlers `app`.
- `changelog.d/kern-monitoring-31.md`

## Offene Fragen
keine. Verschoben aus dem Zug:
- R-1378 und R-1422 nach `kern-monitoring-28`, weil sie die vHost-Liste aus R-1435 brauchen
- R-1423, R-1424 und R-1434 nach `kern-monitoring-35`, weil Fragen an Kevin offen sind
