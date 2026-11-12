<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# arch-monitoring-module-2 — Task-Ledger
Status: bereit · Branch: feature/arch-monitoring-module-2 · Review: pro Task
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

### T2 — Monitoring: Engine reicht Vorzustand und Partner an erklärende Checker (R-1224)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/check_engine.py, apps/monitoring/app/checkers/__init__.py, apps/monitoring/tests/test_check_engine_context.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @4b74aebb1 2026-11-12T06:32:56+01:00
Review: approve (.ah-out/review/arch-monitoring-module-2/T2.verdict.json)
Änderung: `execute_check` liest vor dem `db.rollback()` den bisherigen `details`-Text und, bei `pair_check_id`, Status und `details` des Partner-Checks und übergibt beides an Checker mit `wants_context = True` (neue Methode `run_with_context`); alle anderen Checker unverändert. Test: Kontext kommt an, Partner fehlt oder gehört zu anderem Server → ohne Partner, andere Checker bekommen nichts, bestehende Engine-Tests grün.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_engine_context.py tests/test_check_engine.py tests/test_check_engine_concurrency.py
Doku: → T14
Abhängt von: T1

### T3 — Check-Typ `central` mit Fühler `tls` (Kette, Hostname, relative Restlaufzeit) (R-1224)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/check_types.py, apps/monitoring/app/check_configs.py, apps/monitoring/app/routers/checks.py, apps/monitoring/app/checkers/__init__.py, apps/monitoring/app/checkers/central.py, apps/monitoring/app/central/tls.py, apps/monitoring/tests/test_central_tls.py, apps/monitoring/tests/test_central_config.py, apps/desktop/ui/src/lib/api/types.ts, apps/monitoring/app/checkers/context.py, apps/monitoring/app/central/limits.py, apps/monitoring/app/check_engine.py, apps/monitoring/app/scheduler.py, apps/monitoring/app/schemas.py, apps/monitoring/requirements.in, apps/monitoring/requirements.txt, apps/monitoring/tests/test_check_engine_context.py, apps/monitoring/tests/test_scheduler.py, apps/monitoring/tests/test_central_checker.py, apps/monitoring/tests/test_check_configs.py
Evidenz: run.sh[quick] monitoring desktop-ui: 5 passed, 0 failed, 13 skipped @3d90c7019 2026-11-12T07:38:13+01:00
Review: approve (.ah-out/review/arch-monitoring-module-2/T3.verdict.json)
Änderung: `central` in `CHECK_TYPES` (nicht push-only), `CentralConfig` mit `sensor`, `host`, `port`, `pair_check_id`, `params` (Port 22/3306 verboten), Takt-Untergrenzen je Fühler im Checks-Router, Metriken in `CHECK_TYPE_METRICS`, Dispatcher `checkers/central.py` mit Regel öffentlich/intern und Schonung aus T1. Fühler `tls`: Handshake mit SNI und `CERT_NONE`, `get_unverified_chain()`, Prüfung mit `cryptography.x509.verification` gegen den certifi-Store (DNSName bzw. IPAddress), Schwellen 25/10 % der Gesamtlaufzeit, kritisch spätestens 12 h vor Ablauf. Desktop: `central` in `MonitorCheckType` (Paritätstest verlangt es im selben Commit, daher beide Komponenten-Suiten im Verify). Tests mit lokal erzeugter CA und TLS-Server auf Loopback (Regel öffentlich im Test ersetzt): gültig, Name falsch, Wildcard nur linke Marke, Kette unvollständig, abgelaufen, Schwellen.
Verify: bash scripts/dev/verify.sh monitoring desktop-ui --strict
Doku: → T14
Abhängt von: T2

### T4 — Fühler `tls`: ARI und CAA (R-1224)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/central/ari.py, apps/monitoring/app/central/caa.py, apps/monitoring/app/central/tls.py, apps/monitoring/tests/test_central_ari.py, apps/monitoring/tests/test_central_caa.py, apps/monitoring/app/central/fetch.py, apps/monitoring/app/checkers/central.py, apps/monitoring/tests/test_central_fetch.py, apps/monitoring/tests/test_central_tls.py, apps/monitoring/tests/test_central_checker.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @095b0a12b 2026-11-12T08:33:10+01:00
Review: approve (.ah-out/review/arch-monitoring-module-2/T4.verdict.json)
Änderung: Täglich (Zeitpunkt in `details`): ARI nach RFC 9773 nur für CAs einer eingebauten Tabelle Aussteller → ACME-Directory (Directory-URL vorher in der Doku der CA verifizieren), CertID aus AKI und Seriennummer, `suggestedWindow` begonnen → Warnung, `Retry-After` auf 1 min–1 Tag begrenzt, keine Abfrage nach Ablauf; CAA nach RFC 8659 über die öffentlichen Resolver (Baum aufsteigen, `issuewild` vor `issue`, kritisches unbekanntes Tag), aktueller Aussteller laut Tabelle nicht erlaubt → Warnung, unbekannter Aussteller → keine Aussage. HTTPS-Abruf gepinnt auf globale Adressen.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_ari.py tests/test_central_caa.py tests/test_central_fetch.py tests/test_central_tls.py tests/test_central_checker.py
Doku: → T14
Abhängt von: T3

### T5 — Fühler `dns`: Basislinie, Delegation, DNSSEC, Route `rebaseline` (R-1224)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/central/dns.py, apps/monitoring/app/check_configs.py, apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_central_dns.py, apps/monitoring/tests/test_central_rebaseline.py, apps/monitoring/tests/openapi.snapshot.json, apps/monitoring/app/checkers/central.py, apps/monitoring/tests/test_central_checker.py, apps/monitoring/tests/test_central_config.py, apps/monitoring/tests/test_response_shapes.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @24727af52 2026-11-12T09:02:50+01:00
Review: approve (.ah-out/review/arch-monitoring-module-2/T5.verdict.json)
Änderung: A/AAAA über beide Resolver; erste vollständige Antwort wird Basislinie in `details` (oder `params.expected`); Abweichung → Warnung „geändert“, Resolver uneins → Warnung. Stündlich: NS der Zone antworten autoritativ (lame → Warnung); DNSSEC nur mit DS: SERVFAIL ohne CD, Antwort mit CD → kritisch, RRSIG läuft in < 3 Tagen ab → Warnung. `POST /checks/{id}/rebaseline` (nur `central`/`dns`, sonst 400) verwirft die Basislinie.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_dns.py tests/test_central_rebaseline.py tests/test_central_checker.py tests/test_central_config.py tests/test_openapi_snapshot.py tests/test_response_shapes.py
Doku: → T14
Abhängt von: T3

### T6 — Fühler `rdap` (R-1224)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/central/rdap.py, apps/monitoring/app/check_configs.py, apps/monitoring/tests/test_central_rdap.py, apps/monitoring/app/central/fetch.py, apps/monitoring/tests/test_central_fetch.py, apps/monitoring/app/checkers/central.py, apps/monitoring/tests/test_central_checker.py, apps/monitoring/tests/test_central_config.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @5406480b9 2026-11-12T09:22:27+01:00
Review: approve (.ah-out/review/arch-monitoring-module-2/T6.verdict.json)
Änderung: IANA-Bootstrap `dns.json` (gecacht, täglich), registrierbare Domain aus `host`; `.de` über `rdap.denic.de` nur Status; sonst Ablauf aus `events` (Warnung < `warn_days` 30, kritisch < `crit_days` 7) und Status (`clientHold`/`serverHold` → kritisch, `redemptionPeriod`/`pendingDelete` → kritisch). Abruf gepinnt auf globale Adressen; 429 → `unknown`.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_rdap.py tests/test_central_fetch.py tests/test_central_checker.py tests/test_central_config.py tests/test_openapi_snapshot.py
Doku: → T14
Abhängt von: T3

### T7 — Fühler `smtp` und `imap` (postscreen-konform) (R-1224)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/central/mail.py, apps/monitoring/app/check_configs.py, apps/monitoring/tests/test_central_mail.py, apps/monitoring/app/central/tls.py, apps/monitoring/app/checkers/central.py, apps/monitoring/tests/test_central_config.py, apps/monitoring/tests/test_central_checker.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @4ef8e0bca 2026-11-12T09:49:06+01:00
Review: approve (.ah-out/review/arch-monitoring-module-2/T7.verdict.json)
Änderung: SMTP: Banner bis zur letzten `220 `-Zeile abwarten, nichts vorher senden, `EHLO`, `STARTTLS` (465: TLS sofort), `EHLO`, `QUIT`; nie `MAIL`, `RCPT`, `VRFY`, `AUTH`. IMAP (143 STARTTLS, 993) und POP3S (995) analog mit Greeting, `CAPABILITY`, `LOGOUT`/`QUIT`. Zertifikat über `tls.py` gegen den Namen des Ziels; Mindestabstand 15 min je Adresse und Port. Test mit Fake-Servern auf Loopback, die jedes verbotene Kommando als Fehler werten, ein vorzeitig gesendetes Byte erkennen und ein mehrzeiliges Banner senden.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_mail.py tests/test_central_tls.py tests/test_central_checker.py tests/test_central_config.py tests/test_openapi_snapshot.py
Doku: → T14
Abhängt von: T3

### T8 — Fühler `mail_dns` (SPF, DMARC, MTA-STS, TLS-RPT, FCrDNS) (R-1224)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/central/maildns.py, apps/monitoring/app/check_configs.py, apps/monitoring/tests/test_central_maildns.py, apps/monitoring/app/central/fetch.py, apps/monitoring/app/checkers/central.py, apps/monitoring/tests/test_central_fetch.py, apps/monitoring/tests/test_central_checker.py, apps/monitoring/tests/test_central_config.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @fc0124e65 2026-11-12T11:03:19+01:00
Review: approve (.ah-out/review/arch-monitoring-module-2/T8.verdict.json)
Änderung: SPF nach RFC 7208 (genau ein Record, ≤ 10 Lookups, ≤ 2 leere, Rekursion in `include`/`redirect`), DMARC nach RFC 9989 (Baumsuche, `p=none` → Hinweis), MTA-STS nach RFC 8461 (TXT, Policy über `https://mta-sts.<domain>/.well-known/mta-sts.txt`, gepinnt, MX in der Policy), TLS-RPT nach RFC 8460 (Syntax), FCrDNS jeder MX-Adresse. Je Teil eine Stufe; der schlechteste gewinnt.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_maildns.py tests/test_central_fetch.py tests/test_central_checker.py tests/test_central_config.py
Doku: → T14
Abhängt von: T3

### T9 — Fühler `dnsbl` (freie Listen, Spamhaus nur mit DQS-Key) (R-1224)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/central/dnsbl.py, apps/monitoring/app/check_configs.py, apps/monitoring/tests/test_central_dnsbl.py, apps/monitoring/app/checkers/central.py, apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_central_config.py, apps/monitoring/tests/test_central_checker.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @760eda07c 2026-11-12T11:18:35+01:00
Review: approve (.ah-out/review/arch-monitoring-module-2/T9.verdict.json)
Änderung: Vor dem Bau die Nutzungsbedingungen von PSBL, SpamCop, UCEPROTECT und die DQS-Doku von Spamhaus lesen (Ergebnis unter `## Entscheidungen`). MX-Adressen (IPv4) über den System-Resolver gegen die Listen; Spamhaus ZEN nur über `<key>.zen.dq.spamhaus.net` mit `MONITOR_SPAMHAUS_DQS_KEY`; Antworten außerhalb `127.0.0.0/8` und `127.255.255.x` → `unknown`, nie „gelistet“. Der Key erscheint nie in Meldung, Metrik oder Log.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_dnsbl.py tests/test_central_checker.py tests/test_central_config.py
Doku: → T14
Abhängt von: T3

### T10 — Weg-Diagnose aus der Doppelprüfung (R-1224)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/central/diagnose.py, apps/monitoring/app/checkers/central.py, apps/monitoring/app/check_configs.py, apps/monitoring/tests/test_central_diagnose.py, apps/monitoring/app/routers/checks.py, apps/monitoring/tests/test_central_config.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @5ce886191 2026-11-12T11:59:59+01:00
Review: approve (.ah-out/review/arch-monitoring-module-2/T10.verdict.json)
Änderung: Mit Partner aus T2: zentral rot und Partner ok → „Problem auf dem Weg“; beide rot → „Dienst gestört“; Partner `certfile` mit `not_after` > 1 h nach dem ausgelieferten → Warnung „Zertifikat erneuert, Reload fehlt“. Nur Meldung und `details.diagnosis`, nie der Status (außer der Reload-Warnung). `pair_check_id` nur auf einen `probe`-Check (`tls`, `certfile`, `http`) desselben `server_id` (400 sonst).
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_diagnose.py tests/test_central_config.py
Doku: → T14
Abhängt von: T3

### T11 — Desktop: Formular `central`, Zertifikate-Ansicht, Basislinie neu lernen (R-1224)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/components/monitoring/CheckConfigFields.svelte, apps/desktop/ui/src/components/monitoring/CheckConfigFields.test.ts, apps/desktop/ui/src/components/monitoring/MonitorCheckModal.svelte, apps/desktop/ui/src/components/monitoring/cross/CertsView.svelte, apps/desktop/ui/src/components/monitoring/cross/CertsView.test.ts, apps/desktop/ui/src/lib/api/monitoring.ts, apps/desktop/ui/src/lib/api/monitoring.test.ts, apps/desktop/ui/src/lib/models/monitorCheck.ts, apps/desktop/ui/src/lib/models/monitorCheck.test.ts, apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/monitoring/MonitorCheckModal.test.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @0bd2dcf7a 2026-11-12T12:40:05+01:00
Review: approve (.ah-out/review/arch-monitoring-module-2/T11.verdict.json)
Änderung: Fühler-Auswahl mit Feldern je Fühler, Takt-Auswahl nur ab der Untergrenze, Partner-Auswahl aus den `probe`-Checks des Servers; `CertsView` zeigt zentrale `tls`- und `rdap`-Checks neben den Agent-Zertifikaten (Spalte „Quelle“); Knopf „Basislinie neu lernen“ für `dns` ruft `POST /checks/{id}/rebaseline`. Texte englisch im Code.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/components/monitoring/CheckConfigFields.test.ts src/components/monitoring/cross/CertsView.test.ts src/lib/api/monitoring.test.ts src/lib/models/monitorCheck.test.ts src/components/monitoring/MonitorCheckModal.test.ts src/lib/i18n/i18n.test.ts
Doku: → T14
Abhängt von: T5, T10

### T12 — Agent: Last-Tor (R-1268)  [~] (verschoben in tasks/arch-monitoring-module-3.md: Kevins Antwort zu Grenzen und Sichtbarkeit der Last-Schonung steht aus)
Komponente: agent · Dateien: apps/agent/internal/monitor/loadgate.go, apps/agent/internal/monitor/loadgate_test.go, apps/agent/internal/monitor/report.go, apps/agent/internal/monitor/selfmeasure.go, apps/agent/internal/monitor/report_test.go
Änderung: Aus den Kernwerten des Laufs (Last, I/O-Wartezeit, verfügbarer RAM) entscheidet ein Tor mit Hysterese im `reportState`, ob die nächsten Läufe schonen. Während der Schonung: `m.optional` und Proben laufen nicht, Erkennung verschoben; die ausgesetzten Collector melden `throttled: true, reason: "load"`; neuer Block `self.load_shed = {active, since, reason, values}`. Tests: Eintritt, Hysterese, Austritt, Kern läuft immer, Block-Form.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: → T14

### T13 — Monitoring: Last-Schonung auswerten (R-1268)  [~] (verschoben in tasks/arch-monitoring-module-3.md: Kevins Antwort zu Grenzen und Sichtbarkeit der Last-Schonung steht aus)
Komponente: monitoring · Dateien: apps/monitoring/app/routers/agent.py, apps/monitoring/app/checkers/agent.py, apps/monitoring/tests/test_agent_load_shed.py
Änderung: `self.load_shed` lesen (beschränkt wie `self.collectors`); `_spared_by_throttle` schont bei `reason: "load"` für die Dauer der Schonung und ergänzt die Meldung; Proben-Frische entsprechend; nach 30 min durchgehender Schonung Warnung am Check `agent_resources`; Metrik `agent_load_shed`. Ein Report ohne Block bleibt wie heute.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_agent_load_shed.py tests/test_agent_report.py tests/test_agent_report_v4.py
Doku: → T14
Abhängt von: T12

### T15 — Fühler `tls`: Klartext-Mail-Ports ablehnen (R-1367)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/check_configs.py, apps/monitoring/tests/test_central_config.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @3440e72c5 2026-11-12T11:22:02+01:00
Review: approve (.ah-out/review/arch-monitoring-module-2/T15.verdict.json)
Änderung: `CentralConfig` mit Fühler `tls` lehnt die Ports 25, 587, 143 und 110 ab und verweist auf `smtp`/`imap`: dort spricht der Server zuerst und erwartet STARTTLS, ein ClientHello vor dem Greeting ist für postscreen ein Pregreet. Erst der rote Test (heute wird Port 25 angenommen), dann die Regel in `_fits_sensor`.
Beweis: feature/arch-monitoring-module-2@HEAD · `CentralConfig.model_validate({"sensor": "tls", "host": "mx.example.test", "port": 25})` → wird angenommen
Dedup-Key: bug:monitoring:check_configs.py:CENTRAL_SENSORS.tls
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_central_config.py
Doku: → T14

### T16 — Check-Ergebnisse vor dem Speichern auf speicherbare Zeichen bringen (R-1366)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/check_engine.py, apps/monitoring/tests/test_check_engine.py, apps/monitoring/tests/test_agent_report.py
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @40e0d96c8 2026-11-12T11:36:17+01:00
Review: approve (.ah-out/review/arch-monitoring-module-2/T16.verdict.json)
Änderung: `apply_result` bringt `message` und die Texte in `details` auf Zeichen, die Postgres speichert, bevor `_write_state` schreibt; das gilt damit für beide Ergebniswege (Scheduler `execute_check` und Agent-Push `routers/agent.py`) und jeden Checker. Je Weg ein Test gegen die Test-DB.
Verify: bash scripts/dev/verify.sh monitoring --strict -- tests/test_check_engine.py tests/test_agent_report.py
Doku: → T14

### T14 — Doku DE+EN und CHANGELOG (R-1224, R-1268)  [x]
Komponente: monitoring · Dateien: docs/admin/monitoring.html, docs/en/admin/monitoring.html, docs/developer/monitoring.html, docs/en/developer/monitoring.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html, DEVELOPMENT.md, changelog.d/arch-monitoring-module-2.md, docs/admin/installation.html, docs/en/admin/installation.html
Evidenz: run.sh[quick] monitoring: 3 passed, 0 failed, 15 skipped @4659ffbc7 2026-11-12T13:06:07+01:00
Review: am Ende (nur Doku, Branch-Review)
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
- 2026-11-12 T2: Partner zählt nur als aktivierter `probe`-Check mit demselben, gesetzten `server_id`; ohne State-Zeile Status `pending`; zwei Checks ohne Server sind kein Paar — ein deaktivierter Partner trägt einen veralteten Zustand, ein fremder Server erklärt nichts.
- 2026-11-12 T2: `PartnerState` trägt `sensor` (aus der Partner-Config) und `last_check` — T10 braucht den Fühler für die certfile-Regel und das Alter für die Frische; ein zweites Lesen in T10 entfällt.
- 2026-11-12 T2: Kontext nur bei `wants_context is True` (kein truthy-Wert), gelesen in der Lese-Transaktion vor dem `db.rollback()` — der R-0615-Test für `run_with_context` zeigt 0 belegte Verbindungen während des Laufs.
- 2026-11-12 T2: Gespeichertes JSON, das kein Objekt ist, wird None (wie `_prev_details` im Agent-Router, als lokaler Helfer `_json_object`) — die Engine importiert keine Router.
- 2026-11-12 T2: Das `Verify:` meldet 5 test-skips (`test_check_engine_concurrency` ohne Postgres in `DATABASE_URL`, Vorbedingung lokal nicht erfüllt); zusätzlich lokal mit `DATABASE_URL` auf die Test-DB des Worktrees samt `test_execute_check.py`: 43 passed — die PR-CI fährt den Lock-Test mit Postgres.
- 2026-11-12 T3: zufällige Phase für den ersten Lauf zentraler Checks (`start_date` = jetzt + Zufall × Intervall) statt `jitter` (ersetzt T1→T3) — `jitter` verschiebt jeden Lauf, zwei Mail-Läufe kämen sich dann näher als 15 min; die Phase verteilt den Start und hält den Abstand.
- 2026-11-12 T3: `RunSkipped` hängt nur „(skipped: …)“ an die gespeicherte Meldung (ersetzt eine frühere Notiz, gekappt auf `MAX_MESSAGE`); Status, Zähler, `since`, `last_check`, `details`, VictoriaMetrics und Alarm bleiben; ohne State-Zeile entsteht keine — ein übersprungener Lauf ist kein Befund über das Ziel.
- 2026-11-12 T3: gespeicherte Config, die kein Objekt ist, ergibt „Invalid check configuration“ statt einer Ausnahme im Checker.
- 2026-11-12 T3: `public_since` nur aus den vorigen Details mit demselben Host, die Details tragen immer Host und Port — ein geänderter Host beginnt ohne Geschichte.
- 2026-11-12 T3: Takt-Untergrenze je Fühler im Router (tls 15 min), ohne Intervall der Vorgabewert des Fühlers (1 h); bei Update erneut geprüft, sobald `check_type`, `config`, `interval` oder `server_id` gesendet werden — ein reiner Namenswechsel lässt einen alten Check editierbar.
- 2026-11-12 T3: Partner nur `probe` desselben, gesetzten Servers mit Fühler tls, certfile oder http; ein Fühler als Liste/Objekt oder kaputtes JSON ergibt 400, nicht 500.
- 2026-11-12 T3: Vorlagen verweigern `central` — eine Vorlage würde ein öffentliches Ziel auf jeden Server verteilen.
- 2026-11-12 T3: `host` prüft das Schema nur syntaktisch (ASCII/`xn--`, kein Punkt am Ende, kein Zonenindex, letzte Marke nicht numerisch); `localhost` besteht das Schema, die Regel öffentlich/intern entscheidet zur Laufzeit — eine Namensliste im Schema wäre unvollständig.
- 2026-11-12 T3: Tabelle `CENTRAL_SENSORS` (Port, Untergrenze, Vorgabe-Intervall, Parameter) in `check_configs.py`; `tls` nimmt keine Parameter.
- 2026-11-12 T3: `certifi` als direkte Abhängigkeit (>=2026.10.23), Store einmal je Prozess, `CryptographyDeprecationWarning` beim Laden unterdrückt — certifi trägt eine Wurzel mit nicht-positiver Seriennummer, die cryptography annimmt und nur anwarnt.
- 2026-11-12 T3: abgelaufen/noch nicht gültig vor `verify` geprüft (klare Meldung), Metriken auch bei nicht vertrauenswürdiger Kette — die Restlaufzeit bleibt sichtbar.
- 2026-11-12 T3: kein SNI für IP-Literale (RFC 6066); der Host geht unverändert in `DNSName` — cryptography vergleicht Namen ohne Groß-/Kleinschreibung (Probe 2026-11-12, Test mit Großbuchstaben-Host).
- 2026-11-12 T3: höchstens 3 Adressen nacheinander; verweigert der Mindestabstand eine Adresse, wird der ganze Lauf übersprungen (kein Ausweichen auf die nächste) — sonst trifft der Lauf eine andere Adresse als geplant.
- 2026-11-12 T3: unvollständige Kette ist kritisch, kein AIA-Nachladen — der Monitoring-Dienst kontaktiert nur das Ziel.
- 2026-11-12 T3: Die Plan-Annahme eines Desktop-Paritätstests war falsch (keiner prüft `MonitorCheckType` gegen die Check-Typen); `central` steht trotzdem in `MonitorCheckType`, die Formularliste `CHECK_TYPES` folgt in T11.
- 2026-11-12 T3: `test_central_checker.py` per `set-files`; `CheckContext` in eigenem Modul `checkers/context.py` — `app.checkers` importiert jeden Checker, bevor es selbst etwas definiert.
- 2026-11-12 T3→T4: Prüfer-Nit T3 — die Schwellen 25/10 % vergleichen das gerundete `lifetime_pct` (9,96 % bleibt Warnung); T4 ändert `tls.py` ohnehin und vergleicht dort das ungerundete Verhältnis, mit Test an der Grenze.
- 2026-11-12 T4: zehn Dateien statt höchstens acht — der gepinnte HTTPS-Abruf (`fetch.py`, eigene Tests) entsteht hier für ARI und wird in T6 (RDAP) wiederverwendet; `checkers/central.py` reicht die vorigen Details an `tls.probe` durch, `test_central_checker.py` prüft das.
- 2026-11-12 T4: ARI-Tabelle Let's Encrypt, Google Trust Services, ZeroSSL (Directory live gelesen, `renewalInfo` vorhanden); SSL.com bleibt draußen — sein öffentliches Directory ist RSA-only, das ECC-Directory nicht verifiziert.
- 2026-11-12 T4: ARI warnt erst, wenn das Fenster vorbei ist (Plan: „begonnen → Warnung“) — RFC 9773 §6: ein ganz vergangenes Fenster ist der Ruf zum sofortigen Erneuern; ein laufendes Fenster ist der Normalfall, in dem der Client zu einem Zufallszeitpunkt erneuert, eine Warnung dort wäre bei jedem ACME-Zertifikat Rauschen. Kevin erfährt es im Bericht.
- 2026-11-12 T4: Retry-After geklemmt auf 1 min–1 Tag befolgt; ohne Retry-After nach Erfolg und bei Langzeitfehlern 6 h, temporäre Fehler 15/30/60 min, dann 6 h (RFC 9773 §4.3.3); ungültige Antwort behält das letzte gültige Fenster.
- 2026-11-12 T4: ein ARI-GET je CertID und Abrufzeitpunkt (Retry-After der CA, begrenzt auf 1 min–1 Tag, ohne Angabe 6 h) über alle Checks: Prozess-Zustand je CertID (höchstens 1024, älteste raus) neben den Details des Checks; zwei gleichzeitige Läufe desselben Zertifikats können beide einmal fragen (selten, hingenommen).
- 2026-11-12 T4: CA-Abrufe außerhalb des Mindestabstands je Adresse, aber im Slot des laufenden Checks — sie treffen die CA, nicht das Ziel.
- 2026-11-12 T4: CAA-Zustand gilt nur für denselben Namen, Wildcard und CA; Aufstieg höchstens 16 Labels; ohne Antwort der Resolver bleibt das letzte Urteil, neuer Versuch nach 1 h; unbekannte CA oder IP-Literal → keine ARI-/CAA-Aussage.
- 2026-11-12 T4: `fetch.get` verweigert Ports außerhalb 1–65535 selbst — httpx nimmt jede Zahl, die Socket-Schicht wirft dann `OverflowError` statt eines `FetchError`.
- 2026-11-12 T4: ARI/CAA nur bei gültigem, vertrauenswürdigem, nicht abgelaufenem Zertifikat; ihre Befunde machen aus ok eine Warnung, ein kritischer Status bleibt kritisch, die Befunde hängen an der Meldung.
- 2026-11-12 T4 (Prüfrunde): `fetch.get` hat eine Gesamtfrist von 20 s — die Zeitlimits von httpx gelten je Operation; ein Watchdog-Timer schließt den Socket per `shutdown` (Basisklasse, der blockierte TLS-Read kehrt zurück), Connect und Handshake bekommen ein auf die Restzeit gekürztes Timeout, nach Ablauf wird keine weitere Adresse versucht. Der Watchdog stoppt, bevor httpx den Socket schließt; schließt httpcore ihn auf einem Fehlerpfad selbst, bleibt ein Wettlauf mit der Wiederverwendung des Deskriptors im Bereich weniger Mikrosekunden (hingenommen).
- 2026-11-12 T4 (Prüfrunde): `Accept-Encoding: identity`; eine Antwort mit Content-Coding wird abgelehnt — die Body-Grenze zählt empfangene Bytes (`iter_raw`), nicht entpackte.
- 2026-11-12 T5: RRSIG-Schwelle relativ — Warnung, wenn weniger als 5 % der Gültigkeit übrig sind, statt „< 3 Tage“ (Plan): Fenster reichen von 2 Tagen (Online-Signer, live gelesen) bis zu einem Monat, eine feste Grenze von 3 Tagen warnte bei 2-Tage-Fenstern dauerhaft; Signer erneuern weit vorher (BIND bei 25 % Restlaufzeit, Knot bei etwa 10 %). Abgelaufen → kritisch. Kevin erfährt es im Bericht.
- 2026-11-12 T5: RRSIG wird an den autoritativen Servern gelesen (RD=0, DO), nicht beim Resolver — der liefert zwischengespeicherte Signaturen; je Nameserver höchstens 2 SOA-Fragen (zweite Adresse oder dieselbe noch einmal), höchstens 8 Nameserver (Rest als `unchecked`), Abstand je Adresse über `address_turn`; verweigert er eine Adresse oder sind die Resolver stumm, bleibt der alte Zustand und der Blick kommt nach 15 min wieder.
- 2026-11-12 T5: antwortet kein einziger Nameserver, wird das nur festgehalten, ohne Warnung — wahrscheinlicher ist der eigene ausgehende Port 53 gesperrt; ein stummer neben antwortenden warnt.
- 2026-11-12 T5: `resolvers_agree` nur mit mindestens zwei antwortenden Resolvern; Basislinie = Vereinigung der ersten vollständigen Antwort (jeder Resolver hat geantwortet); ohne Vollständigkeit meldet der Vergleich nur neue Adressen — ein stummer Resolver kann die fehlenden halten. Resolver-Uneinigkeit warnt auch bei geo-verteilten CDNs (Plan); T14 dokumentiert es.
- 2026-11-12 T5: Ein Lauf ohne Ergebnis (nicht öffentlich, Resolver stumm, tls nicht erreicht) übernimmt Basislinie und Zonen-Zustand (dns) bzw. ARI und CAA (tls) aus den vorigen Details desselben Hosts — sonst lernte der nächste Lauf eine neue Basislinie und ein Ausfall verdeckte einen Adresswechsel.
- 2026-11-12 T5: Antworten alle Resolver mit SERVFAIL, fragt der Checker bei `dns` ohne und mit CD nach: Antwort nur mit CD → kritisch „DNSSEC validation fails“, SERVFAIL bei jedem → kritisch; sonst bleibt es „unknown“ — dann ist eher der eigene Weg nach draußen gestört.
- 2026-11-12 T5: `dns` verweigert Port und IP-Literal als Host (422) — der Fühler fragt nach einem Namen und verbindet sich mit keinem Dienst-Port.
- 2026-11-12 T5: `rebaseline` mitten in einem laufenden Lauf: der Lauf kann die alte Basislinie zurückschreiben, ein zweiter Aufruf entfernt sie (hingenommen, Kommentar in der Route) — eine Sperre gegen den Scheduler wäre für einen seltenen Klick zu viel.
- 2026-11-12 T5: zehn Dateien statt höchstens acht, `Verify:` um `test_central_checker.py` und `test_central_config.py` erweitert — der Checker reicht Regel und Parameter an den Fühler durch, die Fühler-Tabelle bekommt `dns`.
- 2026-11-12 T6: Registry-Fühler (`rdap`) überspringen die Regel öffentlich/intern — der Host braucht keine Adresse (Mail-only-Domain), und der Agent könnte die Registry nicht an seiner Stelle fragen; Slot ja, Mindestabstand über das Intervall-Minimum 24h.
- 2026-11-12 T6: registrierte Domain ohne Public Suffix List und ohne DNS (eine Domain auf Hold ist aus dem DNS): von Host und Eltern die drei nächsten zur TLD, längster zuerst, bis die Registry 200 sagt; einmal, danach nur die gespeicherte Domain. 404 auf die gespeicherte → kritisch „no longer registered“; beim ersten Lauf nichts gefunden → unknown.
- 2026-11-12 T6: Antwortet die Registry mit `ldhName` einer Eltern-Domain des gefragten Namens, gilt diese (eine Registry darf für die umfassende Domain antworten); ein fremder Name oder eine TLD → unknown.
- 2026-11-12 T6: IANA-Bootstrap im Prozess gecacht, 24 h; nach einem Fehlschlag 15 min kein neuer Abruf, bis dahin dient die alte Kopie weiter. Eine in IANA gelistete TLD schlägt die eigene Tabelle (`.de` → `rdap.denic.de`, DENIC-Doku 2026-11-12). Bootstrap-Grenze 512 KiB (`fetch.get(max_body=…)`), Datei hatte 71 kB.
- 2026-11-12 T6: ohne Ablaufdatum (`.de`, oder die Registry nennt keins) meldet der Fühler nur den Status, `ok`, ohne Metrik — kein eigener `.de`-Zweig. Hold/Redemption/pendingDelete sind kritisch unabhängig vom Datum.
- 2026-11-12 T6: Ablauf ist das Datum der Registry; Registrare mit Auto-Renew verlängern oft erst kurz davor — der Hinweis und DENICs Pilotbetrieb samt Nutzungsvermerk („technical or administrative necessities of Internet operation“) gehen in die Doku (T14).
- 2026-11-12 T7: EHLO nennt immer das Adress-Literal des eigenen Endes (RFC 5321 §4.1.4), nie einen Hostnamen — der Dienst hat keinen öffentlichen Namen, den er belegen könnte; hinter Docker/NAT ist das die interne Adresse (T14 nennt es).
- 2026-11-12 T7: fehlendes oder abgelehntes STARTTLS ist auf 25 und 587 kritisch (RFC 8314 empfiehlt TLS für Submission, ein MX ohne STARTTLS liefert Mail im Klartext aus); der Fühler fällt nie auf Klartext zurück.
- 2026-11-12 T7: Klartext, der nach dem STARTTLS-Go-ahead im Puffer liegt, wird verworfen (RFC 3207 §4.2), nicht nach TLS übernommen.
- 2026-11-12 T7: POP3S (995) gehört zum Fühler `imap` — beide prüfen den Postfachzugang; POP3 im Klartext (110) prüft er nicht.
- 2026-11-12 T7: kein ARI/CAA für Mail-Ports — die bleiben beim Fühler `tls` des Web-Namens; der Mail-Fühler prüft Kette, Name und Laufzeit über `tls.judge`.
- 2026-11-12 T7: höchstens eine Verbindung je Adresse und Port in 15 min über alle Checks (`mail_turn`); zwei Checks auf dieselbe Adresse und denselben Port: der zweite wird wiederholt übersprungen (T14 dokumentiert es). Dass 15 min unter den üblichen fail2ban-Zählfenstern bleiben, ist nicht verifiziert.
- 2026-11-12 T7: eine Zeitüberschreitung, die die Gesamtfrist (60 s) abschneidet, meldet die Frist, nicht „keine Antwort in N s“.
- 2026-11-12 T7: lehnt ein Server unter implizitem TLS (465, 993, 995) ab, trägt die Meldung zusätzlich das Zertifikatsurteil — das Zertifikat ist dann schon gesehen.
- 2026-11-12 T7 (Prüfrunde security): das IMAP-Statuswort läuft wie aller Servertext durch `_show`. Prüfer-Nit `tls` auf Mail-Ports: Roadmap-Zeile R-1367.
- 2026-11-12 T8: `mail_dns` läuft wie `rdap` ohne Regel öffentlich/intern und ohne Zustand zwischen Läufen — er fragt öffentliche Resolver und `mta-sts.<domain>`, nicht den Host; Intervall-Minimum und Vorgabe 1 h (Mail-Records ändern sich selten, 1 h begrenzt die Policy-Abrufe beim Webserver der Domain).
- 2026-11-12 T8: SPF wird statisch im schlimmsten Fall gezählt: jedes `include`/`a`/`mx`/`ptr`/`exists`/`redirect` zählt, Ziele mit Makros und `ptr` werden gezählt, nicht verfolgt (sie hängen am Absender); leere Antworten je Adressfamilie (ein IPv6-Absender trifft andere als ein IPv4-Absender), `exists` fragt nur A (§5.7), `mx:` mit mehr als 10 MX ist permerror, `redirect` neben `all` wird ignoriert (§6.1).
- 2026-11-12 T8: je Lauf höchstens 150 DNS-Fragen und 45 s für DNS, jedes (Name, Typ) einmal; danach werden die übrigen Teile nicht beurteilt („<Teil>: more than 150 lookups or 45 s“) — wer die DNS-Zone der Domain hält, kann den Lauf nicht verlängern. Mit der zuletzt begonnenen Frage (2 s), der Auflösung von `mta-sts.<domain>` vor dem Abruf (A und AAAA nacheinander, je 2 s) und dem Policy-Abruf (`fetch.DEADLINE_S` 20 s) dauert ein Lauf höchstens etwa 71 s; diese Zahl nennt T14. Bleibt der Teil MX unbeurteilt, ist es FCrDNS mit demselben Grund.
- 2026-11-12 T8: ein Teil, dessen Namen kein Resolver beantwortet, wird nicht beurteilt; Befunde der anderen Teile gehen vor, ohne Befund ist der Lauf `unknown` — eine fehlende Antwort ist kein fehlender Record.
- 2026-11-12 T8: DMARC ohne `p` gilt als `p=none` (RFC 9989 §4.7), zwei Records an einem Namen gelten als keiner; Baumsuche nach §4.10 mit `psd=y/n`, höchstens 8 Namen.
- 2026-11-12 T8: MTA-STS: TXT-Filter auf `v=STSv1;` (§3.1); Policy über `fetch.get` (gepinnt, Gesamtfrist, Body-Grenze, keine Redirects) mit `Accept: text/plain`, Medientyp muss `text/plain` sein (§3.2) — dafür `HttpAnswer.content_type`; MX außerhalb der Policy bei `enforce` kritisch, bei `testing` Warnung; Wildcard nur für das linke Label (§4.1).
- 2026-11-12 T8: Parser ohne verschachtelte Quantoren (lineare Laufzeit, Test mit 200 000 Zeichen); Text aus DNS und HTTP nur über `_show` in Meldung und Details; Records in den Details höchstens 512 Zeichen, Adressen je MX-Host und FCrDNS höchstens 10, PTR-Namen 3, MX-Hosts 10, `mx`-Muster der MTA-STS-Policy 10 (dazu `mx_count`, wenn es mehr sind) — eine DNS-Antwort über TCP kann tausende Records tragen, eine Policy bis 64 KiB tausende Zeilen.
- 2026-11-12 T8: acht Dateien: `fetch.py` (Content-Type), `checkers/central.py` (Registry-Fühler) und ihre Tests per `set-files`, `Verify:` um diese Tests erweitert.
- 2026-11-12 T9: Bedingungen gelesen (2026-11-12): UCEPROTECT „free of charge, either private or commercial use“, ab 100 000 Fragen/Tag RSYNC; PSBL „Anybody is free to use PSBL“; SpamCop frei mit Spendenbitte, „AS IS“; Spamhaus nur über DQS mit eigenem Key (Antworten außerhalb 127.0.0.0/8 verwerfen, 127.255.255.0/24 sind Fehler, abgeschaltet → SERVFAIL); die Bedingungen des freien DQS-Keys ließen sich nicht abrufen (nicht verifiziert) — der Key bleibt optional und Sache des Betreibers. Ein Lauf je Tag und Domain stellt höchstens 4 + 10 Fragen je Liste.
- 2026-11-12 T9: MX-Hosts und ihre Adressen über die öffentlichen Resolver wie `mail_dns`; die Listen über den System-Resolver, wie ein Mailserver sie fragt (Spamhaus lehnt öffentliche Resolver ab). Nur globale IPv4-Adressen (die Listen führen IPv4), höchstens 10 MX-Hosts und 10 Adressen, beides als Hinweis genannt. Ohne MX gilt die Domain selbst (RFC 5321 §5.1), Null-MX und NXDOMAIN fragen keine Liste.
- 2026-11-12 T9: jede Liste wird je Lauf zuerst an ihren Testeinträgen gemessen (RFC 5782 §5: 127.0.0.2 gelistet, 127.0.0.1 nicht); dazu eine Antwort außerhalb 127.0.0.0/8 oder aus 127.255.255.0/24, keine Antwort oder eine Ausnahme → die Liste wird in diesem Lauf nicht beurteilt, auch ihre übrigen Antworten nicht. Probe am 2026-11-12 über den System-Resolver der Dev-Box: die Testeinträge der drei freien Listen antworten 127.0.0.2 mit TXT, nicht gelistete Namen NODATA statt NXDOMAIN — beides gilt als „nicht gelistet“. Die Testeinträge der DQS-Zone sind nicht verifiziert (kein Key).
- 2026-11-12 T9: Status: eine Listung ist `warning` (Zustellung leidet, der Dienst läuft), Metrik `listed_count` = Zahl der Paare (Adresse, Liste); eine nicht beurteilte Liste oder ein MX-Host ohne Antwort macht einen Lauf ohne Listung `unknown`, eine Listung geht immer vor. TXT-Grund nur der freien Listen, über `_show` begrenzt.
- 2026-11-12 T9: der DQS-Key ist ein Label des Fragenamens: `list_query` fängt jede Ausnahme selbst, `_Run.listed` jede weitere; Meldung, Details und Metrik tragen nur Listen-Titel — Test über alle Pfade (auch eine Ausnahme mit dem Namen) mit `caplog`. Laufzeit höchstens 45 s, danach sind die übrigen Listen nicht beurteilt. NXDOMAIN der Domain ist `reached=True` wie in `mail_dns`.
- 2026-11-12 T9: sieben Dateien: `checkers/central.py` (Registry-Fühler), `routers/checks.py` (Metrik `monitor_listed_count_value`) und die Tests von Config und Dispatcher per `set-files`, `Verify:` um diese Tests erweitert.
- 2026-11-12 T15: die Ablehnung nennt den passenden Fühler (25/587 → `smtp`, 143 → `imap`); für 110 (POP3, STLS) gibt es keinen, die Meldung sagt das — der Fühler `imap` spricht kein POP3. Andere STARTTLS-Ports (21, 119, 4190) nennt R-1367 nicht, sie bleiben offen (kein postscreen davor). Die Ports 465, 993 und 995 mit direktem TLS bleiben für `tls` erlaubt (Test).
- 2026-11-12 T16: zentral in `apply_result`, damit für beide Ergebniswege und jeden Checker: NUL und einzelne Surrogate (U+D800–U+DFFF) in `message` und in jedem String von `details`, Schlüssel eingeschlossen, werden U+FFFD; alle anderen Zeichen bleiben. Der Agent-Bericht lehnt beides schon an seiner Grenze ab (`core/bounds.py`, 422), der Push-Test lässt den Text daher den Checker selbst erzeugen. `core/bounds.py` bleibt die Kopie der Server-Datei, die Regex steht in `check_engine.py`.
- 2026-11-12 T16: `details` auch, weil `json.dumps` ein Surrogat als Escape schreibt, das die Datenbank nimmt, eine spätere JSON-Antwort aber nicht in UTF-8 kodieren kann; NUL in den Details stört escaped nicht und wird der Einheitlichkeit halber mit ersetzt. Rekursiv statt mit explizitem Stack wie `find_unstorable`: die Tiefe der Details bestimmt der Checker im eigenen Code, kein Absender. Annahme: die Datenbank kodiert UTF8 (Standard des Postgres-Images).
- 2026-11-12 T16: kein Postgres-gebundener Test (liefe lokal als SKIP); stattdessen eine einmalige Gegenprobe gegen einen Wegwerf-Container `postgres:18-alpine` (Ergebnis im Commit-Body). Die sqlite-Tests fallen ohne die Änderung rot, ebenso jeder Mutant (Regex ohne NUL oder ohne untere Surrogate, `message`, `details`, Schlüssel oder Listen nicht ersetzt).
- 2026-11-12 T10: Weg und Dienst nur mit einem Partner `tls` oder `http` (der Agent erreicht den Dienst selbst); ein `certfile`-Partner liest eine Datei und dient nur dem Reload-Vergleich, und der nur für den zentralen Fühler `tls`.
- 2026-11-12 T10: Diagnose nur für Fühler, die den Host selbst ansprechen (`tls`, `dns`, `smtp`, `imap`); `rdap`, `mail_dns` und `dnsbl` fragen Dritte, deren Befund erklärt der Agent nicht.
- 2026-11-12 T10: ein Partner zählt nur, wenn sein letzter Report höchstens drei Agent-Läufe (900 s) alt ist; ein Agent, der schweigt, sagt nichts über den Dienst jetzt. Eine eigene Spalte für das Partner-Intervall braucht das nicht: der Probe-Zustand wird mit jedem Report neu bewertet.
- 2026-11-12 T10: die Reload-Warnung hebt nur `ok` auf `warning`, ein schlechterer Status bleibt (Ledger „außer der Reload-Warnung“; „nie den Status“ der Spec gilt für Weg und Dienst); sie zählt bei jedem bewerteten Partner-Status, nicht bei `unknown`/`pending`.
- 2026-11-12 T10: die Diagnose hängt mit „; “ an die Meldung des Fühlers an, deren Anfang bleibt; `details.diagnosis` trägt Art, Partner-ID, -Status und -Zeit, beim Reload beide Ablaufdaten.
- 2026-11-12 T10: die 400 für einen ungeeigneten `pair_check_id` brachte schon T3 (`routers/checks.py` `_central_refused`, Tests in `tests/test_central_config.py`, die das Verify mitfährt); `check_configs.py` bleibt unverändert, `routers/checks.py` kommt für den certfile-Partner dazu (unten).
- 2026-11-12 T10 (Prüfer, Runde 1): „Problem auf dem Weg“ nur, wenn der zentrale Lauf den Host nicht erreicht hat (`_run` gibt `reached` mit); ein Lauf, der ihn erreicht hat, sah den Dienst und fand etwas an ihm (Zertifikat, fehlendes STARTTLS), das der Agent nicht prüfen muss. „Dienst gestört“ bleibt in beiden Fällen. Der Fühler `dns` erreicht immer, wenn die Resolver antworten: eine falsche Antwort nennt seine eigene Meldung, den Weg nur, wenn der Name nicht mehr auflöst.
- 2026-11-12 T10 (Prüfer, Runde 1): ein `certfile`-Partner ergibt 400, wenn der zentrale Fühler nicht `tls` ist oder die Probe `not_after` nicht in `fields` speichert (der Probe-Checker hält nur die genannten Felder); sonst sagte der Partner still nie etwas. Der Annahme-Test für `certfile` trägt dafür `fields` mit `not_after` (gewollte Verhaltensänderung, Ablehnungen eigene Tests). Ändert ein späteres Katalog-Update die Felder, prüft der Router das nicht nach: die Diagnose schweigt dann, wie ohne Partner.
- 2026-11-12 T11: elf statt höchstens acht Dateien — die Fühler-Tabelle, Takt-Untergrenze und Partner-Auswahl gehören ins Formular-Modell (`lib/models/monitorCheck.ts` samt Test), die neuen Texte DE+EN nach `dictionaries.ts` (die Paritäts- und Tot-Schlüssel-Tests in `i18n.test.ts` fährt das Verify mit), der Basislinien-Knopf und das Nachladen der Partner in `MonitorCheckModal` samt Test; Formular, Zertifikate-Ansicht und Client gemeinsam getestet ergeben einen Commit.
- 2026-11-12 T11: der Knopf „Basislinie neu lernen“ erscheint nur bei einem zentralen `dns`-Check ohne `params.expected` (nur dann lernt `dns.py` eine Basislinie) und fragt vorher nach: neu gelernt, während eine Antwort falsch ist, wird die falsche Antwort zur Basislinie.
- 2026-11-12 T11: die Zertifikate-Ansicht bekommt „Quelle“ als letzte Spalte (HTTP-Check, Zentral, Agent); der bestehende Zeilen-Test erwartet deshalb eine sechste Zelle. Zentrale `tls`-Zeilen werden wie die übrigen nach der Restlaufzeit relativ zur Laufzeit eingestuft, ohne Datum nach dem Status; `rdap` nach dem Status, abgelaufen nach dem Datum.
- 2026-11-12 T11 (Prüfer): Hinweistexte korrigiert — eine interne Adresse lehnt der Dienst nicht ab, der Lauf meldet unknown; `tls` nimmt keinen STARTTLS-Port (25, 587, 110, 143). Offen als Nit: eine `fetchStatus`-Antwort aus einem früheren Öffnen kann die Partner-Liste setzen (kosmetisch, der Router weist einen fremden Partner mit 400 ab); eine zentrale `tls`-Zeile mit gültiger Laufzeit, aber rotem Check (Kette, Hostname) zeigt in der Zertifikate-Ansicht die Laufzeit-Stufe → Doku T14.
- 2026-11-12 T14: Dateien ohne `docs/developer/agent.html` DE+EN (Last-Tor und `self.load_shed` sind R-1268, T12/T13 warten auf Kevin und ziehen in den nächsten Zug samt ihrer Doku), dafür `docs/admin/installation.html` DE+EN (Tabelle der Umgebungsvariablen: `MONITOR_PUBLIC_RESOLVERS`, `MONITOR_SPAMHAUS_DQS_KEY`).
