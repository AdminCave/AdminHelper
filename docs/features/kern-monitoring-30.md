<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-monitoring-30 — Fühler http, tls und dns für die Katalog-Module

Roadmap: R-1392 (http liest eine kurze Klartext-Antwort), R-1394 (tls liefert den Anteil der Lebensdauer), R-1395
(http erkennt Klartext oder TLS am Port), R-1433 (dns fragt den Resolver des Dienstes). Alle vier sind Funde aus
den Modul-Zügen (arch-monitoring-apps-1, kern-monitoring-10) und gehören zum Monitoring-Programm vor 0.47.0.

## Problem / Motivation

- **R-1392:** Der Fühler `http` liest einen Body nur als JSON-Objekt (`fetch`, `jsonObject` in
  `apps/agent/internal/probe/sensor_http.go`). ONLYOFFICE antwortet auf `/healthcheck` immer mit 200 und dem Text
  `true` oder `false`. Das Modul `onlyoffice` sieht deshalb nur, dass der Docservice antwortet, nicht ob die
  Prüfung bestanden ist (Docstring `onlyoffice.py`).
- **R-1394:** `certValues` (`sensor_tls.go`) liefert `days_left`, aber nicht die Laufzeit des Zertifikats.
  Konzept §5 verlangt Schwellen relativ zur Laufzeit L: warning unter 25 % von L, critical unter 10 % von L,
  mindestens 12 h vor Ablauf. Mit 45-Tage- und 6-Tage-Zertifikaten passen feste Tage nicht mehr. `openldap` nimmt
  heute feste 22/9 Tage.
- **R-1395:** `http` kennt nur das feste Schema `http` oder `https` aus dem Katalog. Bei Keycloak erbt der
  Management-Port 9000 das TLS des Hauptservers, bei Vaultwarden schaltet `ROCKET_TLS` TLS ein, bei Mattermost
  `ConnectionSecurity`. Ein Modul kann vorher nicht wissen, was am Port spricht, und der Check fällt dann durch.
- **R-1433:** `dns` fragt nur den Resolver des Hosts (`lookupDNS` über `net.DefaultResolver`) und nimmt kein Ziel.
  Pi-hole und AdGuard prüfen deshalb nur, ob Port 53 lauscht; Unbound und BIND haben gar keinen Antwort-Check.

## Ziel & Nicht-Ziele

**Ziel:** vier Erweiterungen der Fühler, dazu die Module, die sie brauchen. Es gelten die Leitplanken des
Monitoring-Konzepts (Kevin 2026-11-09):

- kein Dienst verliert spürbar Leistung;
- der Agent fragt nur seinen eigenen Host;
- zum Server gehen nur Zahlen, Booleans und Zustände.

**Nicht-Ziele:**

- Kein Body-Text geht an den Server: `http` vergleicht im Agent und meldet nur das Ergebnis.
- Keine Weiterleitung folgen, keine Zertifikatsprüfung im `http`-Fühler; das bleibt Sache von `tls`.
- Keine rekursive Auflösung über Upstream-Server: der dns-Check fragt einen Namen, den der Resolver selbst
  beantwortet (siehe Trade-offs).
- Collabora bleibt beim Fühler `proto` mit `auto`, der Klartext und TLS schon erkennt und 500er bewertet; die
  Antwort `OK` brächte dort nichts Neues (YAGNI).
- GitLabs Puma mit eigenem TLS-Listener lauscht auf einem anderen Port; das deckt die Schema-Erkennung nicht ab.
- Die Einstufung der Agent-Zertifikate im Reiter „Zertifikate & Domains“ bleibt, wie sie ist (nur das
  Ablaufdatum).

## Betroffene Komponenten & Dateien

- **Agent** (`apps/agent/internal/probe/`): `sensor_http.go` (Parameter `expect`, Feld `body_match`, Schema
  `auto` mit Feld `tls`), `sensor_tls.go` (`certValues`: `lifetime_pct`, `hours_left`), `sensor_dns.go` (optionales
  Ziel, Anfrage über TCP durch den Wächter, Feld `rcode`), dazu Tests in `sensor_net_test.go` bzw. neuen
  Testdateien.
- **Monitoring** (`apps/monitoring/app/catalog/`):
  - `sensors.py`: `HttpParams.expect`, neue Felder in `SENSOR_FIELDS`, `dns` mit optionalem Ziel;
  - `model.py`: Schema `auto` in `Target` und `Alternative`, optionales Ziel im Check;
  - Module `onlyoffice`, `keycloak`, `vaultwarden`, `mattermost`, `openldap`, `pihole`, `adguard`, `unbound`,
    `bind` (Version +1).
- **Doku:** `docs/admin/monitoring.html` (App-Module, Probe-Checks), `docs/developer/monitoring.html` (Katalog,
  `HttpParams`), `docs/developer/agent.html` (Sensoren), je DE+EN; `changelog.d/kern-monitoring-30.md`.

## Datenmodell / API / Migrationen

- Keine Migration und keine REST-Änderung. Der Vertrag Server ↔ Agent wächst nur um Parameter, Felder und den
  Schema-Wert `auto`.
- Ein älterer Agent lehnt einen Check mit unbekanntem Parameter, Schema oder Ziel als `invalid` ab; der Check
  steht dann auf `unknown`, bis der Agent aktualisiert ist. So war es auch in den bisherigen Modul-Zügen.
- `validate_params` lässt ungesetzte Parameter weg; die Katalog-Version ändert sich nur für die Module, die die
  neuen Werte nutzen.

## Fühler im Einzelnen

- **http `expect` (R-1392):** Text von 1 bis 64 Zeichen ohne Leer- und Steuerzeichen, nur mit `GET`. Ist das Feld
  `body_match` verlangt, liest der Agent höchstens 4 KiB des Bodys, schneidet Leerraum am Rand ab und vergleicht
  genau. Bei einem längeren Body ist `body_match` false. Ohne `expect` ist `body_match` ein ungültiges Feld.
- **http Schema `auto` (R-1395):** Der Agent baut zuerst über den Wächter eine eigene Verbindung auf und versucht
  einen TLS-Handshake. Antwortet der Dienst mit einem Nicht-TLS-Datensatz, fragt er im Klartext; sonst über HTTPS,
  wie bisher ohne Zertifikatsprüfung. Das Feld `tls` meldet, welcher Weg galt. Kosten: eine zusätzliche
  Verbindung je Lauf.
- **tls (R-1394):**
  - `lifetime_pct` = verbleibende Zeit geteilt durch die Laufzeit (`NotAfter − NotBefore`), in Prozent mit einer
    Nachkommastelle, nie unter 0.
  - `hours_left` = ganze Stunden bis zum Ablauf, abgerundet.
  - Die Regeln eines Moduls: `lifetime_pct lt 25` warning, `lifetime_pct lt 10` critical, `hours_left lt 12`
    critical.
- **dns mit Ziel (R-1433):**
  - Ohne Ziel bleibt alles wie heute.
  - Mit Ziel (`loopback`, `port`, `process`, `container`, `unit`) schickt der Agent eine Anfrage nach RFC 1035 über
    TCP, mit Längenpräfix (RFC 7766), durch den Wächter an den Port des Dienstes. Die Anfrage geht ohne EDNS, mit
    gesetztem RD-Bit.
  - Er liest Kopf und Antwortzähler: `resolved`, `answers`, `duration_ms` und `rcode` (`noerror`, `nxdomain`,
    `servfail`, `refused`, `other`).
  - Er braucht keine neue Abhängigkeit; Kopf und Frage sind wenige Bytes.

## Externe Integrationen

- DNS: RFC 1035 §4.1 (Nachrichtenformat), RFC 7766 §8 (TCP mit zwei Byte Länge), RFC 6761 §6.3 (`localhost`).
- Wie Unbound, dnsmasq/Pi-hole, AdGuard Home und BIND `localhost` beantworten, ist vor T7 an ihrer Doku zu prüfen.
  Was sich nicht belegen lässt, steht im Modul-Docstring als „nicht verifiziert“.
- Keycloak `http-management-scheme`, Vaultwarden `ROCKET_TLS`, Mattermost `ConnectionSecurity`: Was dazu in den
  Docstrings steht, gilt weiter; mit `auto` entfällt nur die Einschränkung „nicht abgedeckt: TLS“.

## Trade-offs & Alternativen

- **Body an den Server schicken** (das Modul vergleicht dort): abgelehnt wegen der Leitplanke „nur Zahlen,
  Booleans, Zustände“. Der Agent vergleicht selbst; `expect` gehört zum Katalog und nicht zur Antwort.
- **Schema `auto` über das Fehlerbild von `net/http`:** Bei einem Klartext-Server auf einer HTTPS-URL gibt `net/http`
  den Fehler nur als Text weiter („server gave HTTP response to HTTPS client“). Den als Signal zu nehmen, wäre
  brüchig. Darum der eigene Handshake vorab. Alternative: zwei Checks je Port, Klartext und TLS. Das verdoppelt
  Läufe und Karte.
- **dns über `net.Resolver{PreferGo, Dial}`:** liest `/etc/hosts` vor dem Resolver und verbirgt den rcode; ein
  Name aus `hosts` erreichte den Dienst nie. Die eigene Anfrage ist klein und genau.
- **Welcher Name im dns-Check (Empfehlung):** `localhost` mit Typ A. Den beantworten die Resolver ohne Anfrage
  nach außen; das entspricht der Leitplanke „keine Leistung kosten, nur den eigenen Host fragen“. Der Check
  belegt dann, dass der Dienst DNS spricht und antwortet, nicht aber, dass die Auflösung nach außen geht.
  Alternativ eine echte Domain: belegt die Kette nach außen, erzeugt aber Anfragen an Upstream-Server und
  scheitert ohne Netz. Für die Bewertung gilt: critical bei `servfail` oder einem Fehler der Anfrage, sonst ok;
  `refused` und `nxdomain` sind ebenfalls eine Antwort des Dienstes.

## Risiken & Rollback

- Ein älterer Agent meldet die neuen Checks als `unknown` (siehe Datenmodell). Der CHANGELOG nennt das.
- `auto` öffnet eine zweite Verbindung je Lauf; bei 300 s Takt ist das vernachlässigbar.
- Rollback: Revert des Merges. Es gibt keine Daten, die migriert werden müssten.

## Doku-Impact

Die Modul-Tabelle in `docs/admin/monitoring.html` (onlyoffice, keycloak, vaultwarden, mattermost, openldap,
pihole, adguard, unbound, bind) und der Abschnitt Probe-Checks. Dazu der Katalog-Abschnitt in
`docs/developer/monitoring.html` und die Sensorliste in `docs/developer/agent.html`, je DE+EN, sowie
`changelog.d/kern-monitoring-30.md`.

## Offene Fragen

1. Name des dns-Checks: `localhost` A (Empfehlung, nur lokal) oder eine echte Domain (prüft auch Upstream)?
   Gebaut wird mit der Empfehlung; Kevin kann umstellen.
