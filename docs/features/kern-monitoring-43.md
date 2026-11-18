# Zentrale Domain-Checks für vHost-Domains (kern-monitoring-43)

Roadmap: R-1501 (FEAT). Konzept: `tasks/private/monitoring-module-konzept.md` §6.1, Zeile Domains.

## Problem / Motivation
Das Modul `web_domain` (R-1435) prüft je vHost mit TLS nur, was der Agent auf dem Host sieht: das ausgelieferte
Zertifikat über Loopback und ob der Webserver nach einer Erneuerung neu geladen wurde. Was die Domain von außen
ausmacht, sieht es nicht: ob der Name noch auf die bekannten Adressen auflöst, ob die Delegation und DNSSEC stimmen,
ob ein CAA-Eintrag die ausstellende CA noch erlaubt. Die zentralen Sensoren `dns` und `tls` (R-1224) können das schon,
doch ein Admin müsste jeden zentralen Check je Domain von Hand anlegen. Die Admin-Doku nennt es als „Nicht abgedeckt:
… Domain-Checks von außen (Auflösung, Delegation, CAA)“ (`docs/admin/monitoring.html`, Abschnitt vHosts).

## Ziel & Nicht-Ziele
Ziel: Übernimmt der Admin eine `web_domain`-Instanz, legt das Modul neben den beiden Agent-Checks zwei zentrale Checks
an, beide mit dem Domainnamen als Host:
- `dns`: Auflösung gegen die Baseline (alle 15 min), Delegation/SOA und DNSSEC (stündlich, im Sensor).
- `tls`: Handshake von außen auf dem Port des vHosts, CAA und ARI (täglich, im Sensor), stündlich. Den Ablauf des
  Zertifikats bewertet dieser Check nicht (Kevin 2026-11-18): das tut der Agent-Check `certificate` mit seinen
  Schwellen (14/3 Tage); so gibt es je Domain einen Ablauf-Alarm, nicht zwei mit verschiedenen Schwellen.

Namen, die nie öffentlich sind, bekommen keine zentralen Checks (Kevin 2026-11-18): Endungen nach RFC 6761
(`.localhost`, `.test`, `.example`, `.invalid`), RFC 6762 (`.local`), RFC 8375 (`.home.arpa`), `.internal` sowie die
verbreiteten `.lan` und `.home`. Beim Übernehmen stehen sie mit dem Grund `not a public name` unter den
übersprungenen Checks; die Agent-Checks entstehen wie bisher.

Nicht-Ziele:
- RDAP (Ablauf der Domain-Registrierung): folgt mit R-1406 nach 0.47.0 (Kevin 2026-11-18).
- Zentrale Checks für andere Instanzarten als `vhost`; Vorlagen für zentrale Checks (`schemas.py` lehnt das weiter ab).
- Eine Zusammenfassung je Zone: Zwei Domains derselben Zone prüfen Delegation und DNSSEC je für sich (stündlich,
  innerhalb von `central/limits.py`).
- Eine Netzprobe beim Übernehmen, ob der Name öffentlich ist: die Liste ist statisch; ein interner Name mit
  öffentlicher Endung steht wie heute beim zentralen Check auf `unknown` („not public – checked by the agent“),
  alarmiert nicht und lässt sich löschen (Grabstein, wird nicht neu angelegt).

## Betroffene Komponenten & Dateien
Nur der Monitoring-Dienst (`apps/monitoring/`):
- `app/check_configs.py` (`TlsParams`, Zeile 268): neuer Parameter `expiry: bool = True`.
- `app/central/tls.py` (Bewertung um Zeile 160–190): bei `expiry: false` weder `warning`/`critical` aus der
  Restlaufzeit noch aus dem Ablauf; Name und Kette werden weiter geprüft, ein abgelaufenes Zertifikat zum letzten
  Zeitpunkt seiner Gültigkeit. Die Messwerte `days_left`/`lifetime_pct` bleiben.
- `app/catalog/model.py` (`Check`, Zeile 201): ein Katalog-Check kann zentral sein (`central: true`, Sensor aus
  `CENTRAL_SENSORS`, Ziel `vhost`, Params nach `CentralConfig`, Intervall nicht unter dem des Sensors, keine Felder,
  Regeln und Zugangsdaten).
- `app/module_sync.py` (`probe_config` 261, `_create` 334, `_update` 366): ein zentraler Katalog-Check wird zu einer
  Zeile mit `check_type="central"` und `CentralConfig` (`host` = Instanzname, `port` = Port des vHosts für `tls`);
  Special-Use-Namen werden übersprungen. Adopt, Catalog-Sync, Grabsteine und „gone“ laufen über dieselben Wege wie
  bei Agent-Checks.
- `app/routers/checks.py` (`_probe_change_refused`, Zeile 202): eine zentrale Zeile eines Moduls behält Server,
  Sensor und Host ihres Moduls.
- `app/catalog/modules/web_domain.py`: Version 2, zwei zentrale Checks `dns` und `outside`.
- Tests: `tests/test_central_tls.py`, `tests/test_central_config.py`, `tests/test_catalog.py`,
  `tests/test_module_sync.py`, `tests/test_checks_crud.py`, `tests/test_catalog_web.py`.

`module_plan.py` schickt dem Agent weiter nur `probe`-Zeilen: die zentralen erreichen den Agent nie.

## Datenmodell / API / Migrationen
Keine Migration: `monitor_checks` trägt `module_id`, `module_instance`, `module_check_key` und
`module_check_hash` unabhängig vom `check_type`. Neu ist nur der Wert `central` an Modul-Zeilen. Die API ändert
keine Form; `GET /catalog` nennt an zentralen Checks den Sensor wie bisher (dazu `central: true`). Kein Vertrag zu
Web, Desktop oder Agent ändert sich; die Web-Oberfläche zeigt die Zeilen als zentrale Checks der Instanz.

Katalog-Update: `web_domain` steigt auf Version 2. `sync_catalog` legt bei übernommenen Instanzen die zwei neuen
Checks stumm an und öffnet den Fund als „geändert“ (bestehender Weg, R-1264); erst Übernehmen macht sie laut.

## Externe Integrationen
Keine neuen: DNS (öffentliche Resolver) und TLS laufen über die bestehenden Sensoren `central/dns.py`,
`central/tls.py`, `central/caa.py` (RFC 8659), `central/ari.py` (RFC 9773).

## Trade-offs & Alternativen
- **Ablauf doppelt melden** (zentraler tls-Check unverändert): weniger Code, aber zwei Alarme mit verschiedenen
  Schwellen. Verworfen (Kevin 2026-11-18).
- **Nur `dns` je Domain:** CAA bliebe außen vor. Verworfen.
- **Netzprobe statt statischer Liste:** zustandsabhängig und beim Übernehmen langsam; die statische Liste ist
  deterministisch (Kevin 2026-11-18).
- **Eigenes Modul `web_domain_outside`:** gleiche Instanzen zweimal im Funde-Eingang. Empfehlung und Wahl: an
  `web_domain` hängen.

## Risiken & Rollback
- Last: je vHost-Domain ein `dns`-Check alle 15 min und ein `tls`-Check stündlich; `central/limits.py` deckelt die
  Parallelität (4) und die Abstände je Ziel. Ein Host mit vielen vHosts erzeugt viele zentrale Checks; der Admin
  sieht sie beim Übernehmen und kann einzelne löschen.
- Die Ziele sind fremde Dienste nur, soweit der Domainname auf sie zeigt; der Handshake ist derselbe wie beim
  Agent-Check, einmal je Stunde (Monitoring-Regel 2026-11-09).
- Rollback: Revert des Merges; angelegte zentrale Zeilen bleiben als Checks ohne Katalog-Definition stehen
  (`dropped`, „bleibt, wie der Admin es ließ“).

## Doku-Impact
`docs/admin/monitoring.html` und `docs/en/admin/monitoring.html`: Abschnitt vHosts („Nicht abgedeckt“ ohne
Auflösung, Delegation, CAA), Zeile `web_domain` der Modultabelle, Parameter `expiry` beim zentralen Sensor `tls`;
`docs/developer/monitoring.html` (DE+EN) zum zentralen Katalog-Check; `changelog.d/kern-monitoring-43.md`.

## Offene Fragen
Keine; beide Verhaltensfragen hat Kevin am 2026-11-18 entschieden (Ablauf nur vom Agent, interne Namen statisch
auslassen).
