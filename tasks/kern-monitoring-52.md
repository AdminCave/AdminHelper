# „Mehr Log“ unter OPNsense: Systemlog lesen — Task-Ledger
Status: bereit · Branch: feature/kern-monitoring-52 · Review: am Ende
Spec: docs/features/kern-monitoring-52.md (Roadmap R-1630)
Heavy: none — fester SSH-Befehl, als Argumentliste im Unit-Test geprüft; keine Journey, kein Stack-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — FreeBSD/OPNsense: „Mehr Log“ liest /var/log/messages und /var/log/system (R-1630)  [x]
Komponente: desktop-rs · Dateien: apps/desktop/src-tauri/src/connection/ssh.rs, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-52.md
Evidenz: run.sh[quick] desktop-rs: 1 passed, 0 failed, 17 skipped @e206a55fc 2026-11-19T22:30:56+01:00
Review: am Ende (Branch-Review)
Beweis: kern-monitoring-50 T4 2026-11-19; opnsense/core master syslog-ng-local.conf (system_YYYYMMDD.log, kein /var/log/messages)
Änderung: Der FreeBSD-Zweig von `build_journal_args` startet `sh -c 'grep -h -F -e "<name>" /var/log/messages /var/log/system/system_*.log 2>/dev/null | tail -n 200'`; der Test `journal_args_on_freebsd_grep_the_syslog` erwartet erst rot die neue Argumentliste. Doku-Satz „nicht verifiziert“ wird durch den belegten Pfad ersetzt.
Verify: bash scripts/dev/verify.sh desktop-rs --strict -- journal_args
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-monitoring-52.md

## Entscheidungen
- `dictionaries.ts` bleibt aus dem Zug: klein-nachlese-15 T3 plant dieselbe Stelle (overlap.sh 2026-11-19); die Klein-Session bekommt den Pfad als Hinweis.
