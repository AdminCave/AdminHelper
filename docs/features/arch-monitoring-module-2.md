<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Monitoring-Module 2: zentrale Fühler und Rücksicht bei Last (Architektur)

Roadmap R-1224 (FEAT, zentrale Fühler) und R-1268 (FEAT, Rücksicht bei Last) · Zug `arch-monitoring-module-2` ·
Kevin 2026-11-09 (Monitoring-Konzept) und 2026-11-10. Stand des Codes: `origin/main@efe47ff6f`. Alle
`datei:zeile` beziehen sich auf diesen Stand.

Baut auf R-1223 (`arch-monitoring-module`, gemergt: Fühler-Framework, Katalog, Plan, Check-Typ `probe`,
Selbstbremse) und R-1225 (`arch-monitoring-ui`, gemergt: Karten, Querschnitt-Ansichten).

## Problem / Motivation

**R-1224.** Der Agent prüft, was auf seinem Host läuft, von innen. Ob ein Dienst von außen funktioniert, sieht er
nicht: ein Zertifikat, das lokal neu liegt, aber nicht ausgeliefert wird; ein DNS-Eintrag, der beim Provider
verschwunden ist; eine Domain kurz vor dem Ablauf; ein Mailserver auf einer Sperrliste; ein MX ohne passenden
Rückwärts-Eintrag. Heute bietet der Monitoring-Dienst dafür nur `http`, `tcp` und `ping`. Das Konzept legt fest:
Öffentliches prüft allein der AdminHelper-Server, Internes der Agent; beide Sichten zusammen sagen, ob ein Fehler
am Dienst oder auf dem Weg liegt.

**R-1268.** Die Selbstbremse aus R-1223 drosselt einen Collector, der selbst teuer wird
(`apps/agent/internal/monitor/selfmeasure.go:19`, `maxThrottleFactor = 8`). Sie schaut nicht auf den Host: Ist
der Host ohnehin überlastet, misst der Agent trotzdem alles Optionale. Das Konzept verlangt: „Ist die Last pro CPU
hoch, die I/O-Wartezeit hoch oder freier RAM knapp, misst der Agent nur das Nötigste und überspringt alles
Optionale. Die Erkennung wird verschoben.“ Offen ist, wo die Grenzen liegen und wie der Server davon erfährt, damit
eine Pause als Befund sichtbar wird und nicht als Lücke.

## Ziel & Nicht-Ziele

**Ziel R-1224:** ein neuer, vom Scheduler gefahrener Check-Typ `central` mit sieben Fühlern im Monitoring-Dienst:

| Fühler | Prüft | Takt (Mindestens / Vorgabe) |
|---|---|---|
| `tls` | Handshake mit SNI, Kette gegen den Trust-Store, Hostname nach RFC 9525, Restlaufzeit relativ zur Gesamtlaufzeit (Warnung < 25 %, kritisch < 10 %, kritisch spätestens 12 h vor Ablauf); täglich ARI (nur bekannte ACME-CAs) und CAA | 15m / 1h |
| `dns` | A/AAAA über zwei öffentliche Resolver, Abgleich mit einer gelernten Basislinie, Uneinigkeit der Resolver; stündlich Delegation (NS antworten autoritativ) und DNSSEC (nur mit DS) | 5m / 15m |
| `rdap` | Domain-Status und Ablauf über RDAP; `.de` nur Status | 24h / 24h |
| `smtp` | Banner, EHLO, STARTTLS (bzw. TLS auf 465), EHLO, QUIT; Zertifikat passt zum MX-Namen | 15m / 15m |
| `imap` | dasselbe für IMAP (143 mit STARTTLS, 993) und POP3S (995) | 15m / 15m |
| `mail_dns` | SPF (≤ 10 DNS-Lookups, ≤ 2 leere), DMARC (Baumsuche nach RFC 9989), MTA-STS (TXT + Policy), TLS-RPT, FCrDNS der MX | 1h / 1h |
| `dnsbl` | MX-Adressen gegen freie Listen (PSBL, SpamCop, UCEPROTECT Stufe 1), Spamhaus ZEN nur mit DQS-Key | 24h / 24h |

Dazu die **Regel öffentlich/intern** (Konzept §3.7) vor jeder Prüfung und die **Weg-Diagnose** aus der
Doppelprüfung (zentraler Check plus Agent-Check desselben Dienstes).

**Ziel R-1268:** ein Last-Tor im Agenten, das bei hoher Host-Last alles Optionale aussetzt, und eine Auswertung im
Monitoring-Dienst, die das als Befund zeigt. Inhalt hängt an Kevins Antwort (Offene Fragen).

**Nicht-Ziele:**
- Keine Außensonde, keine LAN-Sonde, kein Label „nur intern geprüft“ (Konzept 9b, 4).
- Kein SMTP-`MAIL`, `RCPT`, `VRFY`, `AUTH`, keine Testmail; SSH und MySQL nie zyklisch von außen (Konzept §3.7).
- Kein OCSP (die Let's-Encrypt-Responder sind seit 2025-08-06 abgeschaltet, Konzept §5).
- Keine automatische Ableitung zentraler Checks aus Web-Verbindungen, FRP-HTTPS oder vHosts in diesem Zug: zentrale
  Checks legt der Admin an. Die Ableitung wird eine eigene Roadmap-Zeile (die Erkennung des Agenten liefert heute
  keine Domainnamen).
- Keine Katalog-Module für zentrale Fühler: `central` ist ein eigener Check-Typ mit eigener Config, kein `probe`.

## Betroffene Komponenten & Dateien

- **Monitoring** (`apps/monitoring/`):
  - neu `app/central/` — `net.py` (globale Adresse), `resolve.py` (öffentliche Resolver, Regel öffentlich/intern),
    `limits.py` (Parallelität, Mindestabstand), je Fühler ein Modul (`tls.py`, `ari.py`, `caa.py`, `dns.py`,
    `rdap.py`, `mail.py`, `maildns.py`, `dnsbl.py`), `diagnose.py` (Weg-Diagnose); `app/checkers/central.py`
    (Dispatcher).
  - `app/check_types.py:21` (`CHECK_TYPES` um `central`), `app/check_configs.py:258` (`CONFIG_MODELS`),
    `app/routers/checks.py:156` (`CHECK_TYPE_METRICS`) und `:247`/`:310` (Takt-Untergrenzen je Fühler),
    `app/check_engine.py:316` (`execute_check`: Vorzustand und Partner an den Checker; Risikopfad),
    `app/core/config.py` (Resolver, DQS-Key), `requirements.in`/`requirements.txt` (dnspython, cryptography).
  - für R-1268: `app/routers/agent.py:146` (`_spared_by_throttle`; Risikopfad).
- **Agent** (`apps/agent/internal/monitor/`, nur R-1268): `report.go:55`, `selfmeasure.go`, `collector.go`.
- **Desktop-UI** (`apps/desktop/ui/`): `src/lib/api/types.ts:227` (`MonitorCheckType`; Risikopfad),
  `src/components/monitoring/CheckConfigFields.svelte`, `MonitorCheckModal.svelte`,
  `src/components/monitoring/cross/CertsView.svelte`.
- **Compose:** `docker-compose.yml` (Umgebung des Dienstes `monitoring`; Risikopfad), `.env.example`.
- **Server:** keine Änderung. Neue Admin-Routen des Monitorings gehen durch den generischen Durchgriff
  `apps/server/app/modules/monitoring_proxy/router.py` (`/{path:path}`).

## Datenmodell / API / Migrationen

**Keine Migration.** `MonitorCheck.config` (JSON) trägt die Config, `MonitorState.details`
(`app/models.py:184`, String) den Fühler-Zustand: Basislinie, Zeitpunkte der langsamen Teilprüfungen (ARI, CAA,
Delegation, DNSSEC), zuletzt gesehenes Zertifikat, Einstufung öffentlich.

**Config `central`** (`_StrictConfig`, `extra=forbid`):

```json
{
  "sensor": "tls",
  "host": "www.example.org",
  "port": 443,
  "pair_check_id": "<id eines probe-Checks desselben Servers>",
  "params": {}
}
```

- `host`: DNS-Name (A-Label) oder IP-Literal; `port` je Fühler vorgegeben bzw. eingeschränkt (`smtp` 25/465/587,
  `imap` 143/993/995; Port 22 und 3306 für alle Fühler verboten).
- `params` je Fühler (Modelle in `check_configs.py`): `dns.expected` (optional feste Adressliste statt Basislinie),
  `rdap.warn_days`/`crit_days` (Vorgabe 30/7), `dnsbl.lists` (Teilmenge der eingebauten Listen).
- `pair_check_id` optional, nur ein `probe`-Check mit Fühler `tls`, `certfile` oder `http` auf demselben
  `server_id`.
- Takt-Untergrenzen je Fühler (Tabelle oben) prüft der Checks-Router beim Anlegen und Ändern (400 mit Grund).

**Ergebnis:** wie jeder Checker `(status, message, metrics)`; `metrics["_details"]` wird zum neuen
`MonitorState.details`. Metriken je Fühler in `CHECK_TYPE_METRICS` (etwa `days_left`, `lifetime_pct`,
`resolvers_agree`, `listed_count`).

**Engine-Erweiterung (Risikopfad):** `execute_check` (`app/check_engine.py:316`) liest vor dem `db.rollback()`
(`:353`) den bisherigen `details`-Text des Checks und, wenn `pair_check_id` gesetzt ist, Status und `details` des
Partners, und reicht beides an Checker, die es erklären (`wants_context = True`). Alle anderen Checker bleiben
unberührt.

**Neue Route:** `POST /checks/{id}/rebaseline` — nur für `central`/`dns`: verwirft die gelernte Basislinie, der
nächste Lauf lernt neu. Antwort wie `GET /checks/{id}`. Admin-Auth wie die übrigen Check-Routen.

**Umgebung (neu, beide optional):** `MONITOR_PUBLIC_RESOLVERS` (kommagetrennte IPs; Vorgabe Quad9 `9.9.9.9` und
Cloudflare `1.1.1.1`, beide validierend), `MONITOR_SPAMHAUS_DQS_KEY` (leer = Spamhaus aus).

**Regel öffentlich/intern** (Konzept §3.7), je Lauf:
1. Jeder antwortende öffentliche Resolver kennt den Namen mit Adresse (direkt vom Monitoring-Dienst gefragt,
   nicht über den System-Resolver); ein stummer Resolver (Timeout, SERVFAIL, REFUSED) hat kein Veto.
2. Mindestens eine Adresse ist global (gegen die IANA-Tabellen gepinnte Zeilen vor `ipaddress.is_global`, IPv6
   nur aus 2000::/3; eingebettetes IPv4 in IPv4-mapped, NAT64 und 6to4 entscheidet).
3. Der Dienst erreicht eine globale Adresse; verbunden wird nur mit globalen Adressen, gepinnt (kein zweites
   Auflösen).

Ergebnis: „nicht öffentlich – prüft der Agent“ (Status `unknown`) bei 1 oder 2; „öffentliche Resolver nicht
erreichbar“ (`unknown`, eigener Text) wenn keiner antwortet. Wer einmal öffentlich war (`details.public_since`), dem
bringt ein späterer Verbindungsfehler `critical`, keine Umstufung: sonst würde ein ausgefallener öffentlicher Dienst
still.

**Schonung der Ziele** (Konzept §3.13 Punkt 5): höchstens vier zentrale Läufe gleichzeitig (Semaphore im
Prozess), Mindestabstand 2 s je Zieladresse, für `smtp`/`imap` 15 min je Adresse und Port über alle Checks.
Ein Lauf, der den Abstand nicht einhält, wird übersprungen (Zustand bleibt, Meldung „übersprungen: Mindestabstand“).

**Weg-Diagnose** (Konzept §3.7): zentral rot und Partner ok → „Problem auf dem Weg (DNS, Firewall, Proxy,
Provider)“; beide rot → „Dienst gestört“; Partner `certfile` mit `not_after` mehr als 1 h nach dem ausgelieferten
→ „Zertifikat erneuert, Reload fehlt“ (Warnung). Die Diagnose ändert nur die Meldung und `details.diagnosis`, nie
den Status.

**R-1268 (Vorschlag, wartet auf Kevin):** Report-Block `self.load_shed = {active, since, reason, values}`
(additiv, `report_version` bleibt 4). Ausgesetzte Collector melden `throttled: true` mit `reason: "load"`; die
Prüfung im Monitoring-Dienst (`_spared_by_throttle`) schont ihre Checks dann für die Dauer der Schonung statt
höchstens 45 min (`app/routers/agent.py:57`) und hängt „(nicht gemessen: Last-Schonung)“ an die Meldung; nach 30 min
durchgehender Schonung geht der Check `agent_resources` auf Warnung „Last-Schonung seit …“.

## Externe Integrationen

- RFC 9525 (Dienst-Identität in TLS): https://www.rfc-editor.org/rfc/rfc9525 — kein CN, Wildcard nur als ganze
  linke Marke, IP gegen `iPAddress`-SAN.
- `cryptography` `x509.verification` (`PolicyBuilder`, `Store`, `build_server_verifier`):
  https://cryptography.io/en/latest/x509/verification/ — Kette und Hostname in einem Schritt.
- Python `ssl.SSLSocket.get_unverified_chain()` (3.13+): https://docs.python.org/3/library/ssl.html
- RFC 9773 (ACME Renewal Information): https://www.rfc-editor.org/rfc/rfc9773 — CertID aus AKI und Seriennummer,
  `renewalInfo` aus dem ACME-Directory, `Retry-After` auf 1 min bis 1 Tag begrenzt. Die Directory-URL je CA prüft
  die Task gegen die Doku der CA.
- RFC 8659 (CAA): https://www.rfc-editor.org/rfc/rfc8659 — Baum aufsteigen, `issue`/`issuewild`, kritisches
  unbekanntes Tag.
- IANA Special-Purpose Address Registries: https://www.iana.org/assignments/iana-ipv4-special-registry/ und
  https://www.iana.org/assignments/iana-ipv6-special-registry/
- RDAP: RFC 9224 (Bootstrap) https://www.rfc-editor.org/rfc/rfc9224, `https://data.iana.org/rdap/dns.json`;
  DENIC-RDAP `https://rdap.denic.de/domain/<name>` (nur Status, Nutzungshinweis beachten).
- Postfix postscreen: https://www.postfix.org/POSTSCREEN_README.html — nicht vor dem Banner senden, sauber mit QUIT
  gehen.
- SPF RFC 7208, DMARC RFC 9989, MTA-STS RFC 8461, TLS-RPT RFC 8460 (rfc-editor.org).
- Spamhaus DQS (Zone `<key>.zen.dq.spamhaus.net`; Rückgabecodes 127.255.255.252/.254/.255 = Fehler, nicht
  gelistet): https://docs.spamhaus.com/ — die genaue Seite und die Nutzungsbedingungen von PSBL, SpamCop und
  UCEPROTECT prüft T9 vor dem Bau (bis dahin nicht verifiziert).
- dnspython 2.9 (ISC): https://dnspython.readthedocs.io/

## Trade-offs & Alternativen

- **Eigener Check-Typ `central` statt Katalog-Fühler:** Katalog-Fühler laufen im Agenten nach Plan; zentrale
  Prüfungen laufen im Dienst nach Scheduler, mit anderen Grenzen (global, gepinnt, Schonung). Ein Typ mit
  Fühler-Feld hält die Typliste klein (ein Eintrag statt sieben) und die Oberfläche bei einer Sektion. Empfehlung:
  so.
- **dnspython statt System-Resolver:** Die Regel öffentlich/intern verlangt Antworten zweier benannter öffentlicher
  Resolver; `getaddrinfo` kann das nicht, und DNSSEC, CAA, TXT, NS brauchen ohnehin einen DNS-Client. Neue
  Abhängigkeit (ISC-Lizenz, reines Python).
- **cryptography für die Kette:** Pythons `ssl` prüft die Kette nur als Ganzes und meldet bei Fehlern wenig; ein
  Handshake mit `CERT_NONE` plus `x509.verification` trennt „Kette kaputt“, „Name passt nicht“ und „abgelaufen“ in
  einem Lauf. `cryptography` liegt mit derselben Version schon im Server.
- **Basislinie gelernt statt Pflichtliste:** Eine Pflichtliste verlangt Pflege und bricht bei jedem Umzug. Gelernt
  wird beim ersten vollständigen Lauf; eine Abweichung meldet „geändert“, und `rebaseline` übernimmt sie. Wer es fest
  will, setzt `dns.expected`.
- **Öffentlich bleibt öffentlich:** Würde die Regel bei jedem Lauf neu entscheiden, verschwände ein ausgefallener
  öffentlicher Dienst als „nicht öffentlich“ aus der Alarmierung.
- **Last-Tor im Agenten statt Drosselung durch den Server:** Nur der Agent sieht die Last im Moment des Laufs; der
  Server erfährt es über den Report (R-1268, Frage an Kevin).

## Risiken & Rollback

- **Ausgehende Verbindungen des Dienstes:** zentrale Checks verbinden zu beliebigen Namen. Schutz: nur globale
  Adressen, gepinnt, Port 22/3306 verboten, Admin-Routen nur mit Admin-Auth. `security` prüft T1, T2, T3, T7, T8
  und T9.
- **DNS nach außen gesperrt:** Erlaubt die Umgebung kein UDP/TCP 53 zu öffentlichen Resolvern, melden alle
  zentralen Checks `unknown` „öffentliche Resolver nicht erreichbar“, nie `critical`. `MONITOR_PUBLIC_RESOLVERS`
  erlaubt eigene Resolver.
- **Sperrlisten-Betreiber:** Spamhaus verweigert öffentliche Resolver; ohne DQS-Key läuft Spamhaus nicht.
  Antworten außerhalb `127.0.0.0/8` und Fehlercodes `127.255.255.x` zählen als `unknown`, nie als „gelistet“.
- **postscreen und Ratenbegrenzung:** zu häufige Verbindungen bestrafen den Absender. Mindestabstand 15 min je
  Adresse und Port, Banner abwarten, QUIT.
- **Rollback:** Typ `central` entfernen heißt, angelegte Checks dieses Typs zu löschen (keine Migration). Das
  Last-Tor im Agenten ist rein additiv; ein älterer Monitoring-Dienst ignoriert `self.load_shed`.

## Doku-Impact

DE+EN: `docs/admin/monitoring.html` (zentrale Checks, Fühler, Regel öffentlich/intern, Weg-Diagnose, Sperrlisten
und DQS-Key, Last-Schonung), `docs/developer/monitoring.html` (Check-Typ `central`, Engine-Kontext, Schonung der
Ziele), `docs/developer/agent.html` (Last-Tor, `self.load_shed`), `docs/developer/api-reference.html`
(`POST /checks/{id}/rebaseline`); `DEVELOPMENT.md` (neue Abhängigkeiten), `THIRD_PARTY_LICENSES.md`,
`changelog.d/arch-monitoring-module-2.md`.

## Entscheidungen

- **Kevin 2026-11-09 (Monitoring-Konzept, übernommen):** Öffentliches prüft allein der AdminHelper-Server, Internes
  der Agent; keine Außensonde, keine LAN-Sonde, kein Label „nur intern geprüft“ · Spamhaus nur mit eigenem DQS-Key,
  freie Listen nach Prüfung ihrer Bedingungen · TLS-Schwellen relativ (25/10 %, mindestens 12 h) · SMTP nie `MAIL`,
  `RCPT`, `VRFY`, `AUTH` · SSH und MySQL nie zyklisch von außen · überwachte Dienste dürfen nie spürbar Leistung
  verlieren · Rücksicht bei Last: nur das Nötigste, alles Optionale aus, Erkennung verschoben · alles vor 0.47.0.
- **Session 2026-11-12:** ein Check-Typ `central` mit Fühler-Feld; neue Abhängigkeiten dnspython und cryptography;
  Resolver-Vorgabe Quad9 + Cloudflare; freie Listen PSBL, SpamCop, UCEPROTECT Stufe 1; RDAP-Schwellen 30/7 Tage;
  Takt-Untergrenzen laut Tabelle; zentrale Checks legt in v1 der Admin an (Ableitung als eigene Roadmap-Zeile);
  „öffentlich bleibt öffentlich“; Weg-Diagnose ändert nur die Meldung.

## Offene Fragen

**R-1268 (Kevin):** Grenzen und Sichtbarkeit der Last-Schonung. Empfehlung:
- Eintritt, wenn in zwei Läufen nacheinander eines gilt: Last (1 min) je CPU ≥ 2,0 · I/O-Wartezeit ≥ 25 % · verfügbarer
  RAM < 10 %; Austritt nach drei sauberen Läufen.
- Ausgesetzt: optionale Collector (Docker, Proxmox, ZFS, SMART), alle Proben, die Erkennung; der Kern (Ressourcen,
  Uptime, Host, Dienste) läuft immer.
- Sichtbar: betroffene Checks behalten ihren Zustand mit „(nicht gemessen: Last-Schonung)“, ohne die 45-min-Grenze;
  nach 30 min durchgehender Schonung Warnung am Check `agent_resources`.

Die Tasks T12 und T13 stehen auf `[?]`, bis Kevin antwortet; die übrigen Tasks hängen nicht daran.
