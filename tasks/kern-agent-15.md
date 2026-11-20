# Windows-Ansichten: leerer DHCP-Server unknown, nie aktualisierte Signaturen kritisch — Task-Ledger
Status: bereit · Branch: feature/kern-agent-15 · Review: am Ende
Spec: Roadmap R-1465, R-1481
Heavy: none — nur die plattformneutralen Wertfunktionen dhcpValues/defenderValues in winviews.go, Go-Unit-Tests; linux-full fährt keine Windows-Ansicht, die Windows-CI-Jobs bauen den Agent
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1465 + R-1481: dhcpValues ohne Bereich ohne Belegungsfelder, defenderValues meldet 65535  [x]
Komponente: agent · Dateien: apps/agent/internal/probe/winviews.go, apps/agent/internal/probe/winviews_test.go, docs/admin/monitoring.html, docs/en/admin/monitoring.html, changelog.d/kern-agent-15.md
Evidenz: run.sh[quick] agent: 2 passed, 0 failed, 16 skipped @f9374c187 2026-11-20T13:24:10+01:00
Review: am Ende (Branch-Review)
Änderung: `dhcpValues` meldet bei null Bereichen nur `scopes: 0`; die Regeln auf `scopes_over_95`/`scopes_over_80` haben dann keinen Wert, der Check wird `unknown` statt still ok (Kevin 2026-11-20). `defenderValues` meldet `signature_age_d` immer, auch 65535 (nie aktualisiert); die Regel `>= 4` macht das `critical` statt `unknown` (Kevin 2026-11-20). Tests `TestDhcpValuesReportsTheFullestScope` und `TestDefenderValues` drehen sich, erst rot.
Beweis: reviewer kern-monitoring-14 T3 und T8 2026-11-14; apps/agent/internal/probe/winviews.go dhcpValues (`dhcpValues(nil)` liefert scopes_over_95=0 → ok) und defenderValues (`if s.AntivirusSignatureAge != mpSignatureNever`); apps/monitoring/app/checkers/probe.py `_rate`: fehlender Regelwert → unknown
HEAD: 70b4f3719
Dedup-Key: ref:agent:winviews.go:dhcp-empty-defender-never
Semantik: Kevin 2026-11-20 (Fragenblock): scopes=0 als unknown, nie aktualisierte Signaturen kritisch
Verify: bash scripts/dev/verify.sh agent --strict -- ./internal/probe/
Doku: docs/admin/monitoring.html, docs/en/admin/monitoring.html (Zeilen windows-dhcp, defender), changelog.d/kern-agent-15.md
