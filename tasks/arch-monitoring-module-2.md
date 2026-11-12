<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-module-2 — Task-Ledger
Status: aktiv · Branch: feature/arch-monitoring-module-2 · Review: pro Task
Spec: docs/features/arch-monitoring-module-2.md (Roadmap R-1224, R-1268)
Heavy: linux-full — `apps/agent` (Last-Tor, R-1268), `docker-compose.yml` (Umgebung des Monitoring-Dienstes) und ein neuer Check-Typ im Monitoring-Dienst; der Sammellauf fährt agent-monitoring und den Stack
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@efe47ff6f`. Risikopfade (`scripts/dev/review-risk.txt`): T1 (`docker-compose.yml`), T2
(`check_engine.py`), T3 (`types.ts`), T13 (`routers/agent.py`): `security` je Task. Die Fühler-Tasks T7 (SMTP/IMAP),
T8 (MTA-STS-Abruf) und T9 (Sperrlisten, DQS-Key) stehen nicht auf der Liste, öffnen aber Verbindungen nach außen:
`security` auch dort. Neue Quelldateien bekommen den SPDX-Header (`reuse annotate --copyright "Kevin Stenzel"
--license GPL-3.0-or-later <datei>`). Mehr als acht Dateien in T1 und T3: Lock-Datei, Lizenzliste und Compose
gehören zur Abhängigkeit bzw. zum Typ und sind nur gemeinsam grün.

### T1 — Monitoring: Grundlage `app/central/` (globale Adresse, öffentliche Resolver, Schonung) und Abhängigkeiten (R-1224)  [x]
Komponente: monitoring · Dateien: apps/monitoring/requirements.in, apps/monitoring/requirements.txt, THIRD_PARTY_LICENSES.md, apps/monitoring/app/central/__init__.py, apps/monitoring/app/central/net.py, apps/monitoring/app/central/resolve.py, apps/monitoring/app/central/limits.py, apps/monitoring/app/core/config.py, docker-compose.yml, .env.example, apps/monitoring/tests/test_central_net.py, apps/monitoring/tests/test_central_resolve.py, docs/features/arch-monitoring-module-2.md
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @b0ac0754d 2026-11-12T06:25:14+01:00
Review: approve (.ah-out/review/arch-monitoring-module-2/T1.verdict.json)
Änderung: dnspython und cryptography (Version wie im Server) in `requirements.in`, Lock mit `pip-compile --generate-hashes` neu, Lizenzen in `THIRD_PARTY_LICENSES.md`. `net.py`: `is_global` plus gegen die IANA-Tabellen gepinnte Ergänzung, eingebettetes IPv4 (mapped, NAT64). `resolve.py`: Abfrage zweier öffentlicher Resolver (`MONITOR_PUBLIC_RESOLVERS`, Vorgabe 9.9.9.9 und 1.1.1.1) und die Regel öffentlich/intern mit den drei Ergebnissen der Spec. `limits.py`: Semaphore (4) und Mindestabstand je Adresse bzw. Adresse+Port. `MONITOR_SPAMHAUS_DQS_KEY` in `config.py`, beide Variablen in Compose und `.env.example`. Tests mit gefälschtem Resolver (kein Netz): global/nicht global je IANA-Zeile, ein Resolver stumm, beide stumm, keine globale Adresse, Abstand.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_net.py tests/test_central_resolve.py
Doku: → T14

### T2 — Monitoring: Engine reicht Vorzustand und Partner an erklärende Checker (R-1224)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/check_engine.py, apps/monitoring/app/checkers/__init__.py, apps/monitoring/tests/test_check_engine_context.py
Änderung: `execute_check` liest vor dem `db.rollback()` den bisherigen `details`-Text und, bei `pair_check_id`, Status und `details` des Partner-Checks und übergibt beides an Checker mit `wants_context = True` (neue Methode `run_with_context`); alle anderen Checker unverändert. Test: Kontext kommt an, Partner fehlt oder gehört zu anderem Server → ohne Partner, andere Checker bekommen nichts, bestehende Engine-Tests grün.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_engine_context.py tests/test_check_engine.py tests/test_check_engine_concurrency.py
Doku: → T14
Abhängt von: T1

### T3 — Check-Typ `central` mit Fühler `tls` (Kette, Hostname, relative Restlaufzeit) (R-1224)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/check_types.py, apps/monitoring/app/check_configs.py, apps/monitoring/app/routers/checks.py, apps/monitoring/app/checkers/__init__.py, apps/monitoring/app/checkers/central.py, apps/monitoring/app/central/tls.py, apps/monitoring/tests/test_central_tls.py, apps/monitoring/tests/test_central_config.py, apps/desktop/ui/src/lib/api/types.ts
Änderung: `central` in `CHECK_TYPES` (nicht push-only), `CentralConfig` mit `sensor`, `host`, `port`, `pair_check_id`, `params` (Port 22/3306 verboten), Takt-Untergrenzen je Fühler im Checks-Router, Metriken in `CHECK_TYPE_METRICS`, Dispatcher `checkers/central.py` mit Regel öffentlich/intern und Schonung aus T1. Fühler `tls`: Handshake mit SNI und `CERT_NONE`, `get_unverified_chain()`, Prüfung mit `cryptography.x509.verification` gegen den certifi-Store (DNSName bzw. IPAddress), Schwellen 25/10 % der Gesamtlaufzeit, kritisch spätestens 12 h vor Ablauf. Desktop: `central` in `MonitorCheckType` (Paritätstest verlangt es im selben Commit, daher beide Komponenten-Suiten im Verify). Tests mit lokal erzeugter CA und TLS-Server auf Loopback (Regel öffentlich im Test ersetzt): gültig, Name falsch, Wildcard nur linke Marke, Kette unvollständig, abgelaufen, Schwellen.
Verify: bash scripts/dev/verify.sh monitoring desktop-ui --strict
Doku: → T14
Abhängt von: T2

### T4 — Fühler `tls`: ARI und CAA (R-1224)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/central/ari.py, apps/monitoring/app/central/caa.py, apps/monitoring/app/central/tls.py, apps/monitoring/tests/test_central_ari.py, apps/monitoring/tests/test_central_caa.py
Änderung: Täglich (Zeitpunkt in `details`): ARI nach RFC 9773 nur für CAs einer eingebauten Tabelle Aussteller → ACME-Directory (Directory-URL vorher in der Doku der CA verifizieren), CertID aus AKI und Seriennummer, `suggestedWindow` begonnen → Warnung, `Retry-After` auf 1 min–1 Tag begrenzt, keine Abfrage nach Ablauf; CAA nach RFC 8659 über die öffentlichen Resolver (Baum aufsteigen, `issuewild` vor `issue`, kritisches unbekanntes Tag), aktueller Aussteller laut Tabelle nicht erlaubt → Warnung, unbekannter Aussteller → keine Aussage. HTTPS-Abruf gepinnt auf globale Adressen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_ari.py tests/test_central_caa.py tests/test_central_tls.py
Doku: → T14
Abhängt von: T3

### T5 — Fühler `dns`: Basislinie, Delegation, DNSSEC, Route `rebaseline` (R-1224)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/central/dns.py, apps/monitoring/app/check_configs.py, apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_central_dns.py, apps/monitoring/tests/test_central_rebaseline.py, apps/monitoring/tests/openapi.snapshot.json
Änderung: A/AAAA über beide Resolver; erste vollständige Antwort wird Basislinie in `details` (oder `params.expected`); Abweichung → Warnung „geändert“, Resolver uneins → Warnung. Stündlich: NS der Zone antworten autoritativ (lame → Warnung); DNSSEC nur mit DS: SERVFAIL ohne CD, Antwort mit CD → kritisch, RRSIG läuft in < 3 Tagen ab → Warnung. `POST /checks/{id}/rebaseline` (nur `central`/`dns`, sonst 400) verwirft die Basislinie.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_dns.py tests/test_central_rebaseline.py tests/test_openapi_snapshot.py tests/test_response_shapes.py
Doku: → T14
Abhängt von: T3

### T6 — Fühler `rdap` (R-1224)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/central/rdap.py, apps/monitoring/app/check_configs.py, apps/monitoring/tests/test_central_rdap.py
Änderung: IANA-Bootstrap `dns.json` (gecacht, täglich), registrierbare Domain aus `host`; `.de` über `rdap.denic.de` nur Status; sonst Ablauf aus `events` (Warnung < `warn_days` 30, kritisch < `crit_days` 7) und Status (`clientHold`/`serverHold` → kritisch, `redemptionPeriod`/`pendingDelete` → kritisch). Abruf gepinnt auf globale Adressen; 429 → `unknown`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_rdap.py
Doku: → T14
Abhängt von: T3

### T7 — Fühler `smtp` und `imap` (postscreen-konform) (R-1224)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/central/mail.py, apps/monitoring/app/check_configs.py, apps/monitoring/tests/test_central_mail.py
Änderung: SMTP: Banner bis zur letzten `220 `-Zeile abwarten, nichts vorher senden, `EHLO`, `STARTTLS` (465: TLS sofort), `EHLO`, `QUIT`; nie `MAIL`, `RCPT`, `VRFY`, `AUTH`. IMAP (143 STARTTLS, 993) und POP3S (995) analog mit Greeting, `CAPABILITY`, `LOGOUT`/`QUIT`. Zertifikat über `tls.py` gegen den Namen des Ziels; Mindestabstand 15 min je Adresse und Port. Test mit Fake-Servern auf Loopback, die jedes verbotene Kommando als Fehler werten, ein vorzeitig gesendetes Byte erkennen und ein mehrzeiliges Banner senden.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_mail.py
Doku: → T14
Abhängt von: T3

### T8 — Fühler `mail_dns` (SPF, DMARC, MTA-STS, TLS-RPT, FCrDNS) (R-1224)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/central/maildns.py, apps/monitoring/app/check_configs.py, apps/monitoring/tests/test_central_maildns.py
Änderung: SPF nach RFC 7208 (genau ein Record, ≤ 10 Lookups, ≤ 2 leere, Rekursion in `include`/`redirect`), DMARC nach RFC 9989 (Baumsuche, `p=none` → Hinweis), MTA-STS nach RFC 8461 (TXT, Policy über `https://mta-sts.<domain>/.well-known/mta-sts.txt`, gepinnt, MX in der Policy), TLS-RPT nach RFC 8460 (Syntax), FCrDNS jeder MX-Adresse. Je Teil eine Stufe; der schlechteste gewinnt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_maildns.py
Doku: → T14
Abhängt von: T3

### T9 — Fühler `dnsbl` (freie Listen, Spamhaus nur mit DQS-Key) (R-1224)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/central/dnsbl.py, apps/monitoring/app/check_configs.py, apps/monitoring/tests/test_central_dnsbl.py
Änderung: Vor dem Bau die Nutzungsbedingungen von PSBL, SpamCop, UCEPROTECT und die DQS-Doku von Spamhaus lesen (Ergebnis unter `## Entscheidungen`). MX-Adressen (IPv4) über den System-Resolver gegen die Listen; Spamhaus ZEN nur über `<key>.zen.dq.spamhaus.net` mit `MONITOR_SPAMHAUS_DQS_KEY`; Antworten außerhalb `127.0.0.0/8` und `127.255.255.x` → `unknown`, nie „gelistet“. Der Key erscheint nie in Meldung, Metrik oder Log.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_dnsbl.py
Doku: → T14
Abhängt von: T3

### T10 — Weg-Diagnose aus der Doppelprüfung (R-1224)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/central/diagnose.py, apps/monitoring/app/checkers/central.py, apps/monitoring/app/check_configs.py, apps/monitoring/tests/test_central_diagnose.py
Änderung: Mit Partner aus T2: zentral rot und Partner ok → „Problem auf dem Weg“; beide rot → „Dienst gestört“; Partner `certfile` mit `not_after` > 1 h nach dem ausgelieferten → Warnung „Zertifikat erneuert, Reload fehlt“. Nur Meldung und `details.diagnosis`, nie der Status (außer der Reload-Warnung). `pair_check_id` nur auf einen `probe`-Check (`tls`, `certfile`, `http`) desselben `server_id` (400 sonst).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_diagnose.py tests/test_central_config.py
Doku: → T14
Abhängt von: T3

### T11 — Desktop: Formular `central`, Zertifikate-Ansicht, Basislinie neu lernen (R-1224)  [ ]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/CheckConfigFields.svelte, apps/desktop/ui/src/components/monitoring/CheckConfigFields.test.ts, apps/desktop/ui/src/components/monitoring/MonitorCheckModal.svelte, apps/desktop/ui/src/components/monitoring/cross/CertsView.svelte, apps/desktop/ui/src/components/monitoring/cross/CertsView.test.ts, apps/desktop/ui/src/lib/api/monitoring.ts, apps/desktop/ui/src/lib/api/monitoring.test.ts
Änderung: Fühler-Auswahl mit Feldern je Fühler, Takt-Auswahl nur ab der Untergrenze, Partner-Auswahl aus den `probe`-Checks des Servers; `CertsView` zeigt zentrale `tls`- und `rdap`-Checks neben den Agent-Zertifikaten (Spalte „Quelle“); Knopf „Basislinie neu lernen“ für `dns` ruft `POST /checks/{id}/rebaseline`. Texte englisch im Code.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/CheckConfigFields.test.ts src/components/monitoring/cross/CertsView.test.ts src/lib/api/monitoring.test.ts
Doku: → T14
Abhängt von: T5, T10

### T12 — Agent: Last-Tor (R-1268)  [?] (Grenzen und Umfang der Last-Schonung: Empfehlung Last/CPU ≥ 2,0 oder I/O-Wartezeit ≥ 25 % oder verfügbarer RAM < 10 % in zwei Läufen, Austritt nach drei sauberen; ausgesetzt optionale Collector, Proben, Erkennung)
Komponente: agent · Dateien: apps/agent/internal/monitor/loadgate.go, apps/agent/internal/monitor/loadgate_test.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/selfmeasure.go, apps/agent/internal/monitor/report_test.go
Änderung: Aus den Kernwerten des Laufs (Last, I/O-Wartezeit, verfügbarer RAM) entscheidet ein Tor mit Hysterese im `reportState`, ob die nächsten Läufe schonen. Während der Schonung: `m.optional` und Proben laufen nicht, Erkennung verschoben; die ausgesetzten Collector melden `throttled: true, reason: "load"`; neuer Block `self.load_shed = {active, since, reason, values}`. Tests: Eintritt, Hysterese, Austritt, Kern läuft immer, Block-Form.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T14

### T13 — Monitoring: Last-Schonung auswerten (R-1268)  [?] (Sichtbarkeit der Last-Schonung: Empfehlung betroffene Checks behalten ihren Zustand mit „(nicht gemessen: Last-Schonung)“ ohne 45-min-Grenze, nach 30 min Warnung am Check agent_resources)
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_agent_load_shed.py
Änderung: `self.load_shed` lesen (beschränkt wie `self.collectors`); `_spared_by_throttle` schont bei `reason: "load"` für die Dauer der Schonung und ergänzt die Meldung; Proben-Frische entsprechend; nach 30 min durchgehender Schonung Warnung am Check `agent_resources`; Metrik `agent_load_shed`. Ein Report ohne Block bleibt wie heute.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_load_shed.py tests/test_agent_report.py tests/test_agent_report_v4.py
Doku: → T14
Abhängt von: T12

### T14 — Doku DE+EN und CHANGELOG (R-1224, R-1268)  [ ]
Komponente: monitoring · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/agent.html, docs/en/developer/agent.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, DEVELOPMENT.md, changelog.d/arch-monitoring-module-2.md
Änderung: Zentrale Checks (Fühler, Takte, Regel öffentlich/intern, Weg-Diagnose, Sperrlisten und DQS-Key, Umgebungsvariablen), Engine-Kontext und Schonung der Ziele, Last-Tor und `self.load_shed`, Route `rebaseline`, neue Abhängigkeiten; Fragment `changelog.d/arch-monitoring-module-2.md` (umlautfrei). Zehn Dateien: vier Seiten je DE+EN, DEVELOPMENT.md und das Fragment.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_openapi_snapshot.py
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- 2026-11-12 T1: Meldungen im Code englisch („not public – checked by the agent“, „public resolvers unreachable“, „skipped: minimum spacing“), die Spec zitiert sie deutsch — Code-Strings sind englisch (Konvention), die UI übersetzt nicht Freitext.
- 2026-11-12 T1: Mindestabstand je Adresse 2 s mit Reservierung: ein Lauf wartet höchstens 10 s, sonst übersprungen; Slot-Wartezeit ebenfalls 10 s — ein wartender Lauf hält einen Thread des gemeinsamen Scheduler-Pools (30).
- 2026-11-12 T1: smtp/imap-Abstand 15 min je Adresse+Port mit 30 s Spielraum; ein übersprungener Lauf zählt nicht als Verbindung, ein zweiter Check auf dieselbe Adresse+Port wird übersprungen — sonst wird ein Intervall von genau 15 min jeden zweiten Lauf übersprungen bzw. zwei Checks öffnen zwei Verbindungen.
- 2026-11-12 T1: Ein stummer Resolver (Timeout, SERVFAIL, REFUSED, Netzfehler) hat kein Veto, entschieden wird auf den antwortenden; antwortet einer mit NXDOMAIN oder ohne Adresse, ist das Ziel nicht öffentlich — ein ausgefallener Resolver ist nicht Schuld des Ziels, Split-Horizon muss aber intern bleiben.
- 2026-11-12 T1: IANA-Tabellen gepinnt (Stand 2026-11-12), gepinnte Zeilen entscheiden vor `ipaddress.is_global`; Python 3.13.5 und 3.14 weichen ab bei 192.88.99.0/24, 192.88.99.2/32, 100:0:0:1::/64, 5f00::/16 (dort „global“) und 2001:1::3 (dort „nicht global“); der Test verbietet `is_global` für jede gelistete Zeile — gleiche Antwort auf jedem Python.
- 2026-11-12 T1: IPv4-mapped, NAT64 (64:ff9b::/96) und 6to4 entscheidet das eingebettete IPv4; Teredo, fec0::/10 und Multicast nie global — die Verbindung erreicht den IPv4-Host; Teredo/6to4 sind laut IANA „N/A“.
- 2026-11-12 T1: Spamhaus-DQS-Key muss ein DNS-Label aus [A-Za-z0-9] sein, sonst aus mit Warnung ohne den Key — er wird Teil des Abfragenamens.
- 2026-11-12 T1: Limits-Tests in `test_central_net.py` statt eigener Datei — das `Verify:` der Task bleibt wie geplant.
- 2026-11-12 T1→T3: zentrale Jobs brauchen `jitter` am `IntervalTrigger` (`app/scheduler.py` per `set-files` in T3) — ohne feuern alle nach dem Start gleichzeitig und verhungern an den 4 Slots.
- 2026-11-12 T1: IPv6 außerhalb 2000::/3 ist nach den gepinnten Zeilen nie global — IANA vergibt Global Unicast nur daraus, `ipaddress` hält IPv4-compatible ::/96 und 4000::/3 für global (Prüfer T1).
- 2026-11-12 T1→T9: der Abfragename trägt den DQS-Key, dnspython-Ausnahmen zitieren ihn: weder Abfragename noch `str(exc)` gehen in `details`, `message`, Log oder API, nur Zone und Ergebnis.
- 2026-11-12 T1→T14: Spec-Regel 1 und 2 folgen den Entscheidungen oben (stummer Resolver ohne Veto, 2000::/3, 6to4) — in T1 nachgezogen.
