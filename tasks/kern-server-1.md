<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-server-1 — Task-Ledger
Status: aktiv · Branch: feature/kern-server-1 · Review: pro Task
Spec: docs/features/kern-server-1.md (Roadmap R-0827, R-0832, R-0836, R-0837, R-0839, R-0845, R-0846, R-0897, R-0901, R-0942)
Heavy: linux-full — T8 ändert die Namensauflösung für Gateway und TRUSTED_PROXIES (Gateway-Pfad), T7 den Bootstrap auf Postgres mit mehreren Workern
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Für alle Tasks: Zeilenangaben `origin/main@9baee4b1`, vor dem Schreiben neu greppen. Neue Code-Strings englisch,
CHANGELOG umlautfrei in `changelog.d/kern-server-1.md`. `security` zusätzlich bei T1, T2, T3, T7, T8 (und wo
`review.sh risk` es verlangt).

### T1 — Mail-Betreff einzeilig wie im Monitoring (R-0827)  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/sender.py, changelog.d/kern-server-1.md, apps/server/tests/test_email_sender.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @f9d453f4 2026-10-29T17:38:02+01:00
Review: approve (.ah-out/review/kern-server-1/T1.verdict.json)
Änderung: `send_email` (`app/modules/notifications/sender.py:20-29`) ersetzt im Betreff dieselben Zeichen wie `apps/monitoring/app/alerter.py:78-80` (C0, DEL, C1, U+2028, U+2029) je durch ein Leerzeichen; der Text bleibt. Test: Betreff mit Zeilenumbruch und U+2028 wird einzeilig gesendet (SMTP-Stub wie im Bestand), der Body unverändert.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_email_sender.py
Doku: changelog.d/kern-server-1.md

### T2 — Warnung bei zu weiten Rechten der Schlüsseldatei (R-0832)  [x]
Komponente: server · Dateien: apps/server/app/core/config.py, apps/server/tests/test_secret_key_file.py, docs/admin/installation.html, docs/en/admin/installation.html, changelog.d/kern-server-1.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @d2d1a44c 2026-10-29T17:40:02+01:00
Review: approve (.ah-out/review/kern-server-1/T2.verdict.json)
Änderung: `_resolve_secret_key` (`app/core/config.py:86-109`) loggt beim Lesen einer vorhandenen `DATA_DIR/.secret_key` eine Warnung (englisch, Pfad und Modus, nie der Inhalt), wenn `mode & 0o077`; der Schlüssel wird weiter genutzt. Tests: 0644 → Warnung, 0600 → keine.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_secret_key_file.py
Doku: docs/admin/installation.html + EN (Datei `.secret_key` 0600, Warnung beim Start) · changelog.d/kern-server-1.md

### T3 — Eigenes HOME für den Hook-Worker (R-0836)  [x]
Komponente: server · Dateien: apps/server/app/modules/hooks/script_runner.py, apps/server/tests/test_hook_isolation.py, docs/developer/hooks.html, docs/en/developer/hooks.html, changelog.d/kern-server-1.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @f940f864 2026-10-29T17:53:22+01:00
Review: approve (.ah-out/review/kern-server-1/T3.verdict.json)
Änderung: Der Worker bekommt `HOME` = ein Verzeichnis unter `DATA_DIR` (0700, beim ersten Lauf angelegt), statt des Rückfalls `/tmp` (`script_runner.py:122`). Test: HOME im Worker zeigt dorthin, Modus 0700.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hook_isolation.py
Doku: docs/developer/hooks.html + EN (Umgebung des Workers) · changelog.d/kern-server-1.md

### T4 — Hook-Runner: Payload mit Zeitlimit schreiben, Ausgabe stückweise sammeln (R-0845, R-0846)  [ ]
Komponente: server · Dateien: apps/server/app/modules/hooks/script_runner.py, apps/server/tests/test_hooks_webhook_dos.py, docs/developer/hooks.html, docs/en/developer/hooks.html, changelog.d/kern-server-1.md
Änderung: Das Schreiben des Payloads (`script_runner.py:204-208`) läuft in einem Thread, `proc.wait(timeout)` begrenzt den ganzen Aufruf; `_drain` (`:179-187`) liest in Stücken und sammelt bis zum Budget, sodass nach der Gnadenfrist das bis dahin Gelesene ausgewertet wird. Tests zuerst rot: (a) Worker liest stdin nicht, Payload größer als der Pipe-Puffer → Ende nach dem Timeout; (b) Worker schreibt sein Ergebnis und startet einen Nachfahren in eigener Session, der stdout offen hält → Ergebnis kommt an.
Beweis: Code-Lesung `script_runner.py:179-209` (feature/hooks-hardening@d597130e, Fund des builders)
Dedup-Key: bug:server:script_runner.py:stdin-write-no-timeout · bug:server:script_runner.py:detached-child-holds-stdout
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hooks_webhook_dos.py tests/test_hook_isolation.py
Doku: docs/developer/hooks.html + EN (Ausgabe bei offenem stdout) · changelog.d/kern-server-1.md
Abhängt von: T3

### T5 — Webhook-Body mit NaN/Infinity → 422 (R-0837)  [x]
Komponente: server · Dateien: apps/server/app/modules/hooks/router.py, apps/server/tests/test_hooks_webhook_payload.py, changelog.d/kern-server-1.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @47d87394 2026-10-29T17:56:05+01:00
Review: approve (.ah-out/review/kern-server-1/T5.verdict.json)
Änderung: Erst den Fund mit einem Test belegen (Body `{"x": NaN}` an den Webhook-Trigger). Ist er rot (500), lehnt der Router nicht-endliche Zahlen wie die übrigen unspeicherbaren Werte mit 422 ab; ist er grün, bleibt der Test als Beleg und der Code unverändert (Entscheidungszeile).
Beweis: Code-Lesung `app/modules/hooks/router.py:213-216` (nicht verifiziert)
Dedup-Key: bug:server:hooks/router.py:nan-body
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hooks_webhook_payload.py tests/test_openapi_snapshot.py
Doku: changelog.d/kern-server-1.md (nur bei Code-Änderung)

### T6 — CLI: Passwort über 128 Zeichen abweisen (R-0839)  [x]
Komponente: server · Dateien: apps/server/app/cli.py, apps/server/tests/test_cli.py, changelog.d/kern-server-1.md, apps/server/app/modules/users/schemas.py, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @2eb1f866 2026-10-29T17:58:47+01:00
Review: approve (.ah-out/review/kern-server-1/T6.verdict.json)
Änderung: Erst belegen: ein CLI-Passwort mit 129 Zeichen wird angenommen, der Login damit scheitert an der Schema-Grenze (`app/modules/users/schemas.py:23`). Dann weisen `create_admin` und `reset_admin` (`app/cli.py:50-93`) wie bei der Mindestlänge mit Exit 1 ab, die Grenze aus derselben Konstante wie das Schema.
Beweis: Code-Lesung `app/cli.py:52`, `:86` (nicht verifiziert)
Dedup-Key: bug:server:cli.py:password-max-len
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_cli.py tests/test_openapi_snapshot.py
Doku: changelog.d/kern-server-1.md

### T7 — Bootstrap: Prüfen und Anlegen unter einer Sperre (R-0942)  [x]
Komponente: server · Dateien: apps/server/app/modules/users/auth_router.py, apps/server/tests/test_bootstrap.py, changelog.d/kern-server-1.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @5e971cb0 2026-10-29T18:03:54+01:00
Review: approve (.ah-out/review/kern-server-1/T7.verdict.json)
Änderung: `bootstrap` (`app/modules/users/auth_router.py:321-398`) nimmt vor der Prüfung „kein Nutzer“ einen Transaktions-Advisory-Lock auf Postgres (Form wie `app/modules/enrollment/models.py:108`) und hält ihn bis zum Commit. Test (Postgres): zwei gleichzeitige Bootstrap-Aufrufe mit gültigem Token und verschiedenen Namen → genau ein Admin, der andere 409.
Beweis: Code-Lesung `auth_router.py:338-372` (feature/server-multiworker@572b6b5d)
Dedup-Key: bug:server:auth_router.py:bootstrap
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_bootstrap.py tests/test_bootstrap_workers.py
Doku: changelog.d/kern-server-1.md

### T8 — Gateway- und Proxy-Namen: Auflösung ab dem Start, nur gemeinte Namen (R-0897, R-0901)  [ ]
Komponente: server · Dateien: apps/server/app/core/middleware.py, apps/server/app/core/identity.py, apps/server/app/main.py, apps/server/tests/test_ip_filter.py, apps/server/tests/test_identity_source.py, docs/admin/installation.html, docs/en/admin/installation.html, changelog.d/kern-server-1.md
Änderung: Der Resolver-Thread startet im lifespan (`app/main.py`), `_run` (`middleware.py:164-166`) überlebt eine unerwartete Ausnahme (loggen, `_NAME_RETRY`). Die Namen werden als absolute Namen aufgelöst, und ein Name, den `getaddrinfo` als Adresse liest, gilt nicht als Name (`_is_host_name`, `middleware.py:24-33`). Einzelheiten privat (tasks/private). Tests je Regel, mit Gegenprobe.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ip_filter.py tests/test_identity_source.py
Doku: docs/admin/installation.html + EN (TRUSTED_PROXIES-Namen) · changelog.d/kern-server-1.md

## Entscheidungen
- T3: Nur der Rückfall wird ersetzt (Zeilentitel R-0836): ein gesetztes `HOME` des Servers geht weiter unverändert durch. Ein vorhandenes `hooks-home` mit weiteren Rechten wird auf 0700 gesetzt; ist es nicht nutzbar (OSError), scheitert der Lauf vor dem Semaphor mit Fehler statt auf `/tmp` zurückzufallen. Die zwei Bestandstests zum `/tmp`-Rückfall erwarten jetzt `DATA_DIR/hooks-home` (gewollte Verhaltensänderung).
- T6: Die Grenze liegt jetzt als `PASSWORD_MAX_LEN` in `users/schemas.py` (alle vier Passwortfelder nutzen sie), die CLI importiert sie; vorher stand 128 viermal als Literal. Doku in `troubleshooting.html` DE+EN, wo `reset-admin` beschrieben ist (benutzer.html/users.html nennen die CLI nicht).
