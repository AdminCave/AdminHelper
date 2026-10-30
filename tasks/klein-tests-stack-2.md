<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-tests-stack-2 — Task-Ledger
Status: bereit · Branch: feature/klein-tests-stack-2 · Review: am Ende
Spec: docs/features/klein-tests-stack-2.md (Roadmap R-0935, R-0899, R-0955)
Heavy: linux-full — ändert integration_stack_test.sh (Stack-Lauf); Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Enroll erst, wenn :8444 den ca-issuer erreicht (R-0935, R-0955)  [x]
Komponente: scripts · Dateien: scripts/tests/lib_e2e_stack.sh, scripts/tests/lib_e2e_stack_test.sh, scripts/tests/integration_stack_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @9dbd771a 2026-10-30T12:37:03+01:00
Review: am Ende (Branch-Review)
Beweis: R-0935 / R-0955 `FAIL enrollment on the certless plane failed` (HTTP 502 bzw. Connection reset) vor 'ca-issuer Started server process'
Dedup-Key: bug:scripts:integration_stack_test.sh:enroll-502-ca-issuer-start
Änderung: neuer Helfer `e2e_wait_enroll_plane [sekunden]` in `lib_e2e_stack.sh`: fragt `https://localhost:$E2E_ENROLL_PORT/` per curl (max 60 s), Erfolg bei jedem Status ausser 000/502/503/504, sonst rc 1 mit letztem Status. `integration_stack_test.sh` ruft ihn vor dem Enroll auf (FAIL „enroll plane :8444 never reached the ca-issuer (last '…')“). `lib_e2e_stack_test.sh` prueft ihn mit curl-Stub: 502,502,404 → ok nach drei Aufrufen; dauerhaft 502 → rc 1 mit Status in der Meldung (Gegenprobe: die Zeile, die auf 502 wartet, entfernen → rot).
Verify: bash scripts/dev/verify.sh scripts --strict -- lib_e2e_stack_test
Doku: keine (Tests)
Task-Review: am Ende

### T2 — Test-Skripte: stabile FAIL-Zeilen, Negativ-Check mit Beleg, keine .env im Fehlerfall (R-0899)  [x]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh, scripts/tests/multibox_test.sh, scripts/tests/init-secrets_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @745f075c 2026-10-30T12:50:28+01:00
Review: am Ende (Branch-Review)
Beweis: R-0899 integration_stack_test.sh (`app_not_dumpable`: PIDs in zwei FAIL-Zeilen), multibox_test.sh `! grep -q 'frps-egress' "$FAKE_LOG"`, init-secrets_test.sh `tr '\n' ' ' < "$ENV"` in `bad`-Zeilen
Dedup-Key: ref:scripts:integration_stack_test.sh:unstable-fail-ids
Änderung: (a) die zwei FAIL-Zeilen mit PIDs nennen sie nicht mehr (Anzahl und Namen statt PIDs; das Detail geht ins Log darüber); (b) der Negativ-Check in `multibox_test.sh` verlangt zuerst, dass `$FAKE_LOG` existiert und nicht leer ist, Gegenprobe: Log loeschen → rot; (c) `init-secrets_test.sh` zeigt im roten Fall nur die Schluesselnamen (`cut -d= -f1`) statt der Werte.
Verify: bash scripts/dev/verify.sh scripts --strict -- multibox_test init-secrets_test
Doku: keine (Tests)
Task-Review: am Ende

### T3 — Test fuer `_secret_sources()` (R-0899)  [x]
Komponente: server · Dateien: apps/server/tests/test_env_parity.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @c2e4df6e 2026-10-30T13:05:20+01:00
Review: am Ende (Branch-Review)
Beweis: R-0899 apps/server/tests/test_env_parity.py:169 (`_secret_sources` nur indirekt benutzt)
Dedup-Key: ref:scripts:integration_stack_test.sh:unstable-fail-ids
Änderung: `_secret_sources()` gegen ein kleines Compose-Beispiel in `tmp_path` (monkeypatch auf `_COMPOSE`): ein Secret mit `environment`, eines mit `file`, ein leeres; erwartet nur den `environment`-Namen. Gegenprobe: Filter entfernen → rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_env_parity.py
Doku: keine (Tests)

### T4 — Warten auf `/enroll` statt auf `/` (R-0935, R-0955)  [x]
Komponente: scripts · Dateien: scripts/tests/lib_e2e_stack.sh, scripts/tests/lib_e2e_stack_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @af9cefcf 2026-10-30T13:19:05+01:00
Review: am Ende (Branch-Review)
Beweis: Abschlussprüfung 2026-10-30: `apps/gateway/nginx.conf` beantwortet auf :8444 `location / { return 404; }` selbst, nur `location = /enroll` geht an den ca-issuer; T1 fragte `/` und wartete deshalb nie.
Dedup-Key: bug:scripts:integration_stack_test.sh:enroll-502-ca-issuer-start
Änderung: `e2e_wait_enroll_plane` fragt `https://localhost:$E2E_ENROLL_PORT/enroll` (GET; die Route ist POST-only, ein laufender Issuer antwortet 405, ein fehlender 502/Reset). Der Stub-Test verlangt die URL `/enroll`, nutzt 405 als Erfolgsstatus und wartet 000/502/503 aus. Gegenprobe: die Sonde zurück auf `/` → URL-Zeile rot.
Verify: bash scripts/dev/verify.sh scripts --strict -- lib_e2e_stack_test
Doku: keine (Tests)
Task-Review: am Ende
