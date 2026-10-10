<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Messlauf 2: Test-Engine in UTC, SSRF-Testlücken, FRP-Port in der Doku (R-0225, R-0228, R-0236) — Task-Ledger
Status: bereit · Branch: feature/messlauf-2 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-09 (kleines Fund-Paket aus R-0225, R-0228 und R-0236, von Kevin in der Triage als Loop-Futter angenommen; Delegation Kevin 2026-10-05; Abnahmelauf von Schritt 4b)
Spec: Roadmap R-0225, R-0228, R-0236 (Kurz-Ledger ohne Spec)
Heavy: none — Server-Tests ohne Produktivcode und zwei Doku-Seiten je Sprache; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, ruff sauber, Doku DE und EN im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-09 von der Aufsicht (adminhelper-ac) aus drei Zeilen, die Kevin als Futter für den Loop angenommen hat
(R-0225, R-0228 am 2026-10-08, R-0236 am 2026-10-09). Dieses Ledger ist der Abnahmelauf von Schritt 4b: `ledger-loop.sh
start --profile kevin` baut es, und außer dem Start braucht es keinen Handgriff. Zeilenangaben main@c94c59d5.

### T1 — Die Test-Engine fährt ihre Sessions in UTC wie die App (R-0225)  [x]
Komponente: server · Dateien: apps/server/tests/conftest.py, apps/server/tests/test_session_timezone.py
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped @9098a252 2026-10-09T21:22:48+02:00
Review: approve (sonnet/high) · round 1
Änderung: Die App stellt jede Verbindung auf `SET TIME ZONE 'UTC'` (`app/core/database.py:29-35`, R-0209). Die Engine der
Unit-Suite in `tests/conftest.py` (`pg_engine`, `:92`; `create_engine` in `:106` und `:120`) hat diesen Listener nicht und
läuft deshalb in der Default-Zeitzone der Datenbank: lokal Europe/Berlin, in der CI UTC. Die Suite sieht damit lokal
eine andere Session als die App. Die Engine bekommt denselben Listener, am besten die Funktion aus `app/core/database.py`
wiederverwendet statt kopiert. Ein neuer Test (SPDX-Kopf) prüft über `SHOW TIME ZONE` bzw. `current_setting('TimeZone')`
auf einer Verbindung der Test-Engine, dass sie `UTC` meldet; er ist vor der Änderung lokal rot. Ein Test, den die Änderung
rot macht, ist ein Fund, kein Grund zum Abschwächen: dann `[?]` mit dem Namen des Tests.
Beweis: Roadmap R-0225 — Review R-0209, Worker A, 2026-10-07, feature/db-session-utc@abf7c334: `apps/server/tests/conftest.py`
erzeugt seine Engines ohne den Listener.
Semantik: keine Stelle in docs/ — gesucht nach Zeitzone/time zone der DB-Session; Maßstab ist der Vertrag der App in
`app/core/database.py:29-35` (R-0209), den die Suite nachbilden soll.
Dedup-Key: ref:server:tests/conftest.py:pg_engine-utc
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (intern)

### T2 — SSRF-Tests decken die zwei fehlenden Zweige ab (R-0228)  [x]
Komponente: server · Dateien: apps/server/tests/test_ssrf.py
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped @9110f01e 2026-10-09T21:46:39+02:00
Review: approve (sonnet/high) · round 1
Änderung: Seit R-0045 unterscheidet `classify_url` (`app/core/ssrf.py`, Server und Monitoring zeilengleich) ALLOWED,
PRIVATE und UNRESOLVED. Zwei Zweige haben keinen Test: eine Adresse, die `ipaddress` nicht lesen kann, ergibt PRIVATE
(der `ValueError`-Zweig), und eine leere `getaddrinfo`-Liste ergibt UNRESOLVED. Beide bekommen je einen Test in
`apps/server/tests/test_ssrf.py`, mit gepatchtem `getaddrinfo`, ohne Netz. Die Monitoring-Kopie bekommt keine eigenen
Tests: `tests/test_ssrf_parity.py` hält ihren Code zeilengleich, und task-close fährt nur die Suite dieser Komponente. Die Tests müssen das Urteil selbst prüfen (`UrlVerdict.PRIVATE`
bzw. `UrlVerdict.UNRESOLVED`), nicht nur eine Meldung: Eine Mutante, die alles zu UNRESOLVED macht, muss rot werden.
Beweis: Roadmap R-0228 — Review R-0045, Worker A, 2026-10-08, feature/ssrf-guard-reason@aca11f2a.
Semantik: keine Stelle in docs/ — gesucht nach SSRF/unresolved; Maßstab ist der Docstring von `classify_url` und
`is_private_url` („Fail-closed: … a parse error … counts as private“).
Dedup-Key: ref:server:ssrf.py:classify-url-test-gaps
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ssrf.py tests/test_ssrf_parity.py
Doku: keine (intern)

### T3 — Die Doku nennt 7443 nicht mehr als FRP-mTLS-Port (R-0236)  [x]
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @1f427dba 2026-10-10T04:53:05+02:00
Review: approve (sonnet/high) · round 1
Antwort der Aufsicht (2026-10-10, Kevin hat den Neustart freigegeben): Der erste Lauf scheiterte an `review.sh docs-pairs` — nur `docs/en/admin/troubleshooting.html` war geändert. Der englische Satz „Common causes: clock skew > 5 min, expired client cert, DNS failure, firewall blocking …“ hat auf der deutschen Seite kein Gegenstück; die Seiten waren schon auseinander. Die deutsche Seite bekommt denselben Satz in korrekter Form an der entsprechenden Stelle im Agent-Abschnitt (bei „Zertifikat abgelaufen?“), damit beide Sprachen dasselbe sagen und beide Dateien im Commit stehen.
Komponente: scripts · Dateien: docs/en/admin/installation.html, docs/admin/installation.html, docs/en/admin/troubleshooting.html, docs/admin/troubleshooting.html
Änderung: `docs/en/admin/installation.html:41` nennt `7443` den „FRP mTLS tunnel“-Port, und
`docs/en/admin/troubleshooting.html:67` verbindet ein abgelaufenes Client-Zertifikat mit einer Firewall-Regel für
`7443/tcp`. Beides widerspricht der am Code belegten FRP-Seite (`docs/en/admin/frp-tunnel.html`, R-0214) und
DEVELOPMENT.md: frps lauscht laut `docker-compose.yml` auf 7000 und 7443→443, das mTLS sitzt auf dem bindPort
(`config_generator.py`). Die beiden Stellen und ihre deutschen Gegenstücke werden auf die FRP-Seite gebracht; was der
Code nicht hergibt, wird nicht erfunden, ein Widerspruch, der sich am Code nicht klären lässt, ist ein `[?]`.
Beweis: Roadmap R-0236 — Opus-Branch-Review messlauf-1, Aufsicht 2026-10-09.
Semantik: `.claude/rules/docs.md:13`: „Code-Änderung ohne passendes Doku-Update ist unvollständig. Falsche Doku ist ein Bug —
korrigieren, …“
Dedup-Key: bug:docs:installation.html:frp-7443
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die vier Seiten (das ist die Task)
