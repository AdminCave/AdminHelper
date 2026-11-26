# Harness: Gates und Werkzeuge der Sessions — Task-Ledger
Status: aktiv · Branch: feature/kern-harness-11 · Review: pro Task
Spec: docs/features/kern-harness-11.md (Roadmap R-0375, R-0438, R-0546, R-1314, R-1362, R-1631, R-1647, R-1654, R-1659, R-1745, R-1781, R-1315)
Heavy: none — nur Harness-Skripte und Skill-Texte; jede Aenderung hermetisch in scripts/tests bzw. scripts/dev/tests geprueft
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- Kevin 2026-11-25 (Notiz jeder Zeile): „Harness-Fund angenommen (Durchsicht)“ — deckt die Harness-Pfade dieses
  Zugs (`scripts/dev/`, `scripts/tests/`, `.claude/skills/`). CLAUDE.md bleibt unberuehrt (R-1781: nur mit Kevins Ja).
- R-1753 verschoben in kern-harness-13 (2026-11-26): `harness_consistency_test.sh` aendert feature/kern-netretry-1.
- R-1315 auf main behoben durch 1c35ba5de (T8 `[~]`).
- R-0375 als private Sperrliste (Spec, Trade-off a): die Liste liegt nur in `tasks/private/`, nie im Repo.

- T2: Ein Wechsel aus `zurückgestellt`/`abgelehnt` ohne `--note` leert die Notiz (Review: deren Kevin-Marke ist keine
  Annahme und passierte sonst `approve`). `KEVIN_MARK` bleibt, die Annahmeformen variieren: Frage an Kevin; `blockiert`
  und `status … freigegeben` in R-1814 (zurückgestellt).
### T1 — sec sperrt Namen und Netze des Labs aus einer privaten Liste (R-0375)  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @c777bd0b8 2026-11-26T14:47:39+01:00
Review: approve (.ah-out/review/kern-harness-11/T1.verdict.json)
Änderung: `review.sh sec` liest `tasks/private/public-deny.txt` (eine feste Zeichenkette je Zeile, `#` Kommentar,
ohne Gross/Klein), wenn es sie gibt, und meldet jede hinzugefuegte Zeile mit einem Eintrag als `datei:zeile private`
(Exit 4), nie ihren Text; ohne Datei wie bisher. Test mit eigener Liste im Fixture-Repo plus Gegenprobe.
Verify: bash scripts/dev/verify.sh scripts --strict -- review_scripts_test
Doku: Kopfkommentar review.sh

### T2 — roadmap.py: Notiz bleibt, --ledger normalisiert (R-0438, R-1314)  [x]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py, .claude/skills/feature-plan/SKILL.md, .claude/skills/feature-build/SKILL.md, .claude/skills/roadmap/SKILL.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @7b2393340 2026-11-26T15:19:21+01:00
Review: approve (.ah-out/review/kern-harness-11/T2.verdict.json)
Änderung: `status` ohne `--note` behaelt die Notiz (`set_status`, roadmap.py:419-423), `--clear-note` leert sie;
`--ledger` wird vor `refuse_merged_ledger` (:979) normalisiert (Leerraum, `normpath`); die aelteren `--ledger`-Tests
laufen auf `branch_repo`. Skill-Saetze „status ohne --note löscht sie“ angepasst, `/feature-plan` §3a nennt
`git fetch` vor der Slug-Pruefung.
Beweis: R-0438 tasks/private 58dbf91; R-1314 PR #466 Nits
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test
Doku: die drei SKILL.md

### T3 — verify.sh: geerbte Filter weg, leerer Filter rot, Agent-Paket eingegrenzt (R-1362, R-0546, R-1659)  [x]
Komponente: scripts · Dateien: scripts/dev/verify.sh, scripts/tests/run.sh, scripts/tests/verify_test.sh, scripts/tests/run_flags_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @3c972e596 2026-11-26T16:04:08+01:00
Review: approve (.ah-out/review/kern-harness-11/T3.verdict.json)
Änderung: `verify.sh` setzt `AH_STEP`, `AH_PART`, `AH_EXCLUDE`, `AH_ONLY` vor dem Lauf zurueck; mit gesetztem
`AH_ARGS` wird ein cargo-, go- oder vitest-Schritt rot, wenn sein Log keinen ausgefuehrten Test zeigt; nennt
`AH_ARGS` ein Go-Paket (`./…`), ersetzt es `./...` im `go test` (run.sh:882). Faelle mit Gegenprobe.
Beweis: R-0546 verify.sh desktop-rs --strict -- workspace:: → 0 passed, 291 filtered out, rc 0
Verify: bash scripts/dev/verify.sh scripts --strict -- verify_test run_flags_test
Doku: Kopfkommentare verify.sh und run.sh

### T4 — task-close.sh: mehrere Komponenten, Dateien woertlich (R-1631, R-1654)  [x]
Komponente: scripts · Dateien: scripts/dev/task-close.sh, scripts/tests/task_close_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @213e0a50f 2026-11-26T16:27:37+01:00
Review: approve (.ah-out/review/kern-harness-11/T4.verdict.json)
Änderung: `Komponente:` mit mehreren Namen wird als Menge mit den Komponenten des `Verify:` verglichen (:103);
`git add` stagt die `Dateien:` mit `--literal-pathspecs` (:140). Faelle mit Gegenprobe.
Beweis: R-1631 kern-monitoring-50 T3, task-close.sh:103
Verify: bash scripts/dev/verify.sh scripts --strict -- task_close_test
Doku: Kopfkommentar task-close.sh

### T5 — queue-wait: Kommentare nach §4.7 (R-1745)  [~] (bereits stimmig: /feature-build 4.7 reiht gleich nach gh pr create ein, die Kommentare queue-wait.sh:53 und queue_wait_test.sh:71 sagen genau das)
Komponente: scripts · Dateien: scripts/dev/queue-wait.sh, scripts/tests/queue_wait_test.sh
Änderung: Die Kommentare queue-wait.sh:53 und queue_wait_test.sh:71 beschreiben das Einreihen gleich nach
`gh pr create`, auf die Pflicht-Checks wartend; kein Verhalten aendert sich.
Verify: bash scripts/dev/verify.sh scripts --strict -- queue_wait_test
Doku: keine (Kommentare)

### T6 — pipe_guard: docker logs als Schreiber, desktop_e2e-Skripte (R-1647)  [ ]
Komponente: scripts · Dateien: scripts/tests/pipe_guard_test.sh
Änderung: Der Guard zaehlt `docker logs`/`docker compose logs` zu den Schreibern und scannt auch
`scripts/tests/desktop_e2e_*.sh`; Funde in diesen Skripten werden behoben (Variable vor grep). Selbsttest-Fall plus
Gegenprobe.
Beweis: R-1493, R-1522 (docker logs | grep -q in desktop_e2e_*.sh)
Verify: bash scripts/dev/verify.sh scripts --strict -- pipe_guard_test
Doku: Kopfkommentar pipe_guard_test.sh

### T7 — roadmap-Skill: Harness-Nits mit --until (R-1781)  [ ]
Komponente: scripts · Dateien: .claude/skills/roadmap/SKILL.md
Änderung: Die Nit-Regel (SKILL.md:127) stellt die Harness-Nit-Zeile mit `--until <heute+28>` zurueck (Kevin
2026-11-25: Datum in 4 Wochen). Kein changelog.d-Fragment (Harness, kein Nutzerverhalten).
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: .claude/skills/roadmap/SKILL.md

### T8 — .github/scripts-Tests lokal (R-1315)  [~] (bereits behoben: 1c35ba5de)
Komponente: scripts · Dateien: scripts/tests/run.sh
Änderung: keine; behoben durch 1c35ba5de (run.sh:724-725).
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test
Doku: keine (behoben)
