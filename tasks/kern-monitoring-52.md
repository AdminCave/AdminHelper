# „Mehr Log“ unter OPNsense: Systemlog lesen — Task-Ledger
Status: erledigt · Branch: feature/kern-monitoring-52 · Review: am Ende
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

### T2 — Entwickler-Doku und Changelog zum neuen Befehl (R-1630, Abschlussprüfung)  [x]
Komponente: scripts · Dateien: docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-monitoring-52.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @4b941b2c0 2026-11-19T22:43:18+01:00
Review: am Ende (Branch-Review)
Änderung: `terminal_open_ssh_journal` nennt für `freebsd` den Befehl aus T1; der Changelog-Satz trennt die Zeiten.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/desktop.html, docs/en/developer/desktop.html, changelog.d/kern-monitoring-52.md
Task-Review: am Ende

### T3 — UI-Hinweis „Mehr Log“ nennt den OPNsense-Pfad (R-1630)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/i18n/dictionaries.ts
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped @c84bb2afc 2026-11-19T23:15:27+01:00
Review: am Ende (Branch-Review)
Änderung: `monitoring.services.journal.hint` DE+EN nennt neben `FreeBSD: /var/log/messages` auch `OPNsense: /var/log/system` (nach dem Merge von klein-nachlese-15, #613). Reiner Text ohne neue Logik; die i18n-Tests prüfen Schlüsselgleichheit DE/EN.
Verify: bash scripts/dev/verify.sh desktop-ui --strict -- src/lib/i18n src/components/monitoring/section/ServiceList.test.ts
Doku: keine (Doku-Seiten in T1/T2)

## Entscheidungen
- `dictionaries.ts` erst nach dem Merge von klein-nachlese-15 (#613, dieselbe Stelle, overlap.sh 2026-11-19); auf Wunsch der Klein-Session zieht dieser Zug den Hinweistext nach (T3).
