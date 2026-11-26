# Harness: heavy.sh-Klassifizierer und Audit-Abfrage — Task-Ledger
Status: aktiv · Branch: feature/kern-harness-10 · Review: pro Task
Spec: docs/features/kern-harness-10.md (Roadmap R-0737, R-1126, R-1127, R-1284, R-1369, R-1421, R-1672, R-0121, R-1128, R-1133)
Heavy: none — nur heavy.sh und Doku; heavy.sh wird hermetisch in heavy_test.sh geprueft (Shims statt Boxen)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Entscheidungen
- Kevin 2026-11-25 (Notiz jeder Zeile): „Harness-Fund angenommen (Durchsicht)“ — deckt die Harness-Pfade dieses
  Zugs (`scripts/tests/heavy.sh`, `heavy_test.sh`, `.claude/skills/test/SKILL.md`).
- R-0121, R-1128, R-1133 sind auf main 8984d1230 behoben (T7–T9, `[~]` mit Beleg); `roadmap.py status` kennt
  `geplant -> abgeschlossen` nicht, sie schliessen mit diesem Zug.
- Nach `overlap.sh` verschoben in kern-harness-13 (2026-11-26): R-0843, R-0377, R-1364, R-1419, R-1060.

### T1 — check_audit liest nur main; Kopfkommentar buendig (R-0737, R-1369)  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d691c3bc9 2026-11-26T14:25:33+01:00
Review: approve (.ah-out/review/kern-harness-10/T1.verdict.json)
Änderung: `check_audit` (heavy.sh:1093) fragt `runs?branch=main&per_page=1`; heavy_test.sh prueft die Abfrage am
curl-Shim (`curl.args`). Die Zeile `gui` im Kopfkommentar (heavy.sh:14) buendig unter `rest`.
Beweis: R-0737 main@eb976421 scripts/tests/heavy.sh:736 (heute :1093), Abfrage ohne `branch=`
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: keine (Report-Form unveraendert)

### T2 — volle Platte der Box ist infra (R-1284)  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @8e2d7f9c4 2026-11-26T14:41:08+01:00
Review: approve (.ah-out/review/kern-harness-10/T2.verdict.json)
Änderung: `infra_marker` (heavy.sh:270) nimmt auf dem Ein-Box-Layer `no space left on device` auf; ein Teil, dessen
Log das traegt, wird `infra`, nicht `fail`. Fall in heavy_test.sh plus Gegenprobe (capstone-Muster unveraendert).
Beweis: .ah-out/weekly/2026-11-10-1027/gui/last.out.log:392 (`no space left on device`), report: part gui fail
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: → T6

### T3 — Marker ohne Zufallsport; build_failed nur am wdio-Hook (R-1421, R-1672)  [ ]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Änderung: `first_marker` (heavy.sh:707) ersetzt `tcp-<Ziffern>` durch `tcp-<port>`; `build_failed` (heavy.sh:722)
bekommt den Schritt und greift nur bei Desktop-Spec-Schritten und der Hook-Zeile
`Error in hook: SevereServiceError: tauri build failed`. Faelle mit Gegenprobe in heavy_test.sh.
Beweis: R-1421 report 2026-11-13-0130 desktop_e2e_monitoring „3x red, differing markers“; R-1672 launcher.test.js:61
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: keine (Detail-Texte unveraendert)

### T4 — extern nur bei gleichem Box-Bootstrap (R-1126)  [ ]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Änderung: In `second_vm_check` (heavy.sh:893) wird „Basis rot“ nur `extern`, wenn `scripts/vm/bootstrap_linux.sh`
auf Basis und HEAD gleich ist; sonst `unbestaetigt` mit Detail „base ran on a box bootstrapped from HEAD“. Fall
und Gegenprobe in heavy_test.sh.
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: → T6

### T5 — gleiche Fehlersignatur nach extern: keine zweite VM (R-1127)  [ ]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Änderung: `judge_candidates` (heavy.sh:881) merkt sich je `extern` den ersten Node-/errno-Fehlercode des ersten
Retry-Logs; ein weiterer Kandidat mit demselben Code wird ohne Box `extern`, Detail nennt den Bezugsschritt. Ohne
Code die volle Gegenprobe. Fall (zwei Kandidaten, eine w2-Runde) und Gegenprobe (verschiedene Codes) in heavy_test.sh.
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: → T6

### T6 — Klassen-Tabelle DE+EN und /test (R-1284, R-1126, R-1127)  [ ]
Komponente: scripts · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html, .claude/skills/test/SKILL.md
Änderung: Zeilen `infra`, `unbestaetigt`, `extern` der Klassen-Tabelle (cicd.html:267-270, en :263-266,
SKILL.md:138-141) nennen volle Platte, den Bootstrap-Unterschied und die uebernommene Gegenprobe.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/developer/cicd.html, docs/en/developer/cicd.html, .claude/skills/test/SKILL.md
Task-Review: am Ende

### T7 — run.sh evidence_field nimmt den Client zuerst (R-0121)  [~] (bereits behoben: f7b417cd4)
Komponente: scripts · Dateien: scripts/tests/run.sh
Änderung: keine; behoben durch f7b417cd4 (run.sh:561-573).
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test
Doku: keine (behoben)

### T8 — schemathesis nie quarantaeniert (R-1128)  [~] (bereits behoben: R-1337 (181ff3f15))
Komponente: scripts · Dateien: scripts/tests/heavy.sh
Änderung: keine; behoben durch R-1337 (classify_red_step: schemathesis wird `fund`, ohne Retry).
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: keine (behoben)

### T9 — --step schemathesis installiert selbst (R-1133)  [~] (bereits behoben: e36e45015)
Komponente: scripts · Dateien: scripts/tests/run.sh
Änderung: keine; behoben durch e36e45015 (run.sh:815-819, R-1338).
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test
Doku: keine (behoben)
