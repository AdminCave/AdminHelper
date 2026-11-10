# Betriebsskripte: .env-Leser, Rollen-Passwörter, PostgreSQL-18-Umzug — Task-Ledger
Status: aktiv · Branch: feature/ops-7 · Review: pro Task
Spec: docs/features/ops-7.md (Roadmap R-1114, R-1115, R-1138)
Heavy: linux-full — `scripts/backup.sh`, `scripts/restore.sh` und `scripts/update.sh` im Diff: der Sammellauf über `main` fährt `upgrade-path` und `backup-restore`. Kein `scenario`, kein `windows`.
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1114: .env-Leser bei Nicht-ASCII-Schlüsseln vorsichtig  [x]
Komponente: scripts · Dateien: scripts/backup.sh, scripts/diagnostics.sh, scripts/restore.sh, scripts/tests/restore_guard_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @abe8c3fe9 2026-11-10T05:23:32+01:00
Review: approve (.ah-out/review/ops-7/T1.verdict.json)
Änderung: `tok_exact` in `ENV_TOK` setzt `tbad` auch bei einem Schlüssel mit einem Byte ab `\200`, gleich in allen
drei Kopien; Test für backup.sh (env.sanitized) mit einem solchen Schlüssel.
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test diagnostics_test
Doku: keine (kein dokumentiertes Verhalten; CHANGELOG → T4)

### T2 — R-1115: Rollen-Passwort mit $$ annehmen, Meldung mit Ausweg  [x]
Komponente: scripts · Dateien: scripts/restore.sh, scripts/tests/restore_guard_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b86cd262c 2026-11-10T05:42:08+01:00
Review: approve (.ah-out/review/ops-7/T2.verdict.json)
Änderung: `role_password` nimmt außerhalb einfacher Quotes ein `$`, das nur paarweise als `$$` steht, und liest es
als ein `$`; ein einzelnes `$` stoppt weiter, die Meldung nennt das Setzen in der Umgebung. Test 29: Wert von
`SCHEDULER_DB_PASSWORD`, `$$` unquotiert und doppelt gequotet, Backslash in Quotes, `$` in einfachen Quotes.
Beweis: reviewer branch ops-6 2026-11-03 · feature/ops-6@6a68e53e scripts/restore.sh:306 :311
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test
Doku: → T4

### T3 — R-1138: PostgreSQL-18-Umzug prüft den Zielcontainer vor dem DROP  [x]
Komponente: scripts · Dateien: scripts/update.sh, scripts/tests/update_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d29e1cebb 2026-11-10T05:37:41+01:00
Review: approve (.ah-out/review/ops-7/T3.verdict.json)
Änderung: `pg18_migrate` prüft nach dem Start des neuen postgres, dass der Container `postgres18-data` eingehängt hat
und `server_version_num` 18 meldet, bevor es `DROP DATABASE` schickt; sonst Fehlschlag und Rollback. Tests mit dem
Docker-Stub: falscher Mount, falsche Version.
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test
Doku: keine (Rollback-Verhalten unverändert dokumentiert; CHANGELOG → T4)

### T4 — Doku und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/ops-7.md
Änderung: DE+EN: Rollen-Passwörter beim Restore (`$$`, Ausweg über die Umgebung); CHANGELOG-Eintrag neutral.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- T1: kein Test in diagnostics_test.sh: nur backup.sh liest `tbad`, in diagnostics.sh und restore.sh hält die Zeile nur die drei Kopien gleich (diagnostics_test (r) prüft das, es bleibt im Verify); ein Test dort könnte ohne den Fix nicht rot werden.
- T3: Nits der Prüfer hingenommen: die Mount-Prüfung gleicht nicht das Datenverzeichnis ab (nur ein eigenes Override des Betreibers käme durch), Prüfung über `ps -q | head -n 1` gegen DROP über `compose exec` (postgres hat eine Replik), der Rollback-Grund nennt weiter „dump or restore“ (die ERROR-Zeile davor nennt den Grund).
- T2: `$$` nach compose-go dotenv (Kommentar in `expandEscapes`: `FOO=$$bar` ergibt `$bar`); einfach gequotet bleibt jedes `$` wörtlich; ein Backslash in Quotes stoppt weiter.
