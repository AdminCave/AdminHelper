# Harness: Wackler-Politik, Triage-Dauerauftrag, Sammellauf nachts — Task-Ledger
Status: aktiv · Branch: feature/arch-workflow-1 · Review: pro Task
Spec: docs/features/arch-workflow-1.md (Roadmap R-1335, R-1336, R-1337, R-1338)
Heavy: none — Harness-Text und Harness-Skripte mit hermetischen Tests; den echten Beweis für nightly.sh und die heavy.sh-Klasse `fund` liefert der erste nächtliche Lauf nach dem Merge
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1335: Wackler-Fix nur mit Dauerlauf, keine kurzen festen Fristen in Tests  [ ]
Komponente: scripts · Dateien: .claude/rules/testing.md, .claude/agents/reviewer.md, .claude/skills/feature-build/SKILL.md
Änderung: testing.md bekommt die Regel „Wackler“: Ein Fix für einen belegten Wackler gilt erst nach einem grünen Dauerlauf des betroffenen Tests (50 Wiederholungen: Go `-count=50`, Rust/Python als Schleife über den Einzeltest), dessen Summary in den Commit-Body gehört. Für einen Windows-only-Wackler ohne Schleifenweg heißt der Fix „nicht verifiziert“. Dazu die Regel „Fristen“: Tests warten auf eine Bedingung mit einer Obergrenze von mindestens 30 s statt auf eine kurze feste Frist; ausgenommen ist ein Test, der die Frist selbst prüft. reviewer.md Kriterium 3: eine neue kurze feste Frist und ein Wackler-Fix ohne Dauerlauf-Beleg sind `wichtig`. /feature-build §3 Schritt 3 verweist darauf.
Beweis: Workflow-Analyse 2026-11-11 (privat), Wackler-Tabelle: Wiederkehr nach #423, #310, #461, #445, #277/#336/#446 · Dedup-Key: ref:harness:wackler:politik
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: keine (Ablauf steht in .claude/; cicd.html verweist dorthin)

### T2 — R-1336: Triage-Dauerauftrag und Nit-Sammelzeile  [ ]
Komponente: scripts · Dateien: .claude/skills/roadmap/SKILL.md, .claude/skills/feature-build/SKILL.md, .claude/agents/reviewer.md, CLAUDE.md
Änderung: roadmap-Skill, neuer Abschnitt „Dauerauftrag (Kevin 2026-11-11)“ mit den Bedingungen aus der Spec. Die Session legt einen gedeckten Fund mit `add` an und setzt ihn sofort mit `status geplant --ledger tasks/<klein-zug>.md --note "Dauerauftrag Kevin 2026-11-11"` in einen Zug. `/roadmap` nennt die Zahl seit der letzten Triage, `/roadmap triage` listet sie zum Veto. /feature-build §3 („Neue Funde …“) verweist darauf. Nits: reviewer.md stellt klar, dass Nits im Urteil stehen und keine Zeilen werden; die Session behebt billige Nits in derselben Task, den Rest eines Zugs sammelt sie in einer Zeile. CLAUDE.md §4 und §11: Eine vom Dauerauftrag gedeckte Zeile gilt als von Kevin angenommen.
Beweis: Roadmap-Historie 09-09…11-11: 29 Zeilen/Tag seit 10-29, Triage Median 15,4 h, 91 von 115 Nits gebaut · Dedup-Key: ref:harness:roadmap:triage-dauerauftrag
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: keine (Ablauf steht in CLAUDE.md und .claude/)

### T3 — R-1337: nightly.sh startet den Sammellauf per Cron  [ ]
Komponente: scripts · Dateien: scripts/tests/nightly.sh, scripts/tests/nightly_test.sh, scripts/tests/run.sh
Änderung: Neues Skript `nightly.sh run|install|uninstall|status [--dry-run]` nach der Spec:
- Vorprüfung: Haupt-Checkout auf `main` und sauber; kein tmux `ah-*`; `fetch` + `merge --ff-only`; Provider-Umgebung aus `pve.env` und dem `env`-Block von `.claude/settings.local.json`, nie ausgegeben; `vm.py list` endet mit 0.
- Start: `heavy.sh all`, samstags `weekly`, in tmux `ah-nightly`; ein Überspringen mit Grund nach `.ah-out/nightly.log`.
- `install`/`uninstall`: genau eine markierte Crontab-Zeile.

Hermetischer Test über Overrides: Wrapper-Verzeichnis statt heavy.sh, eigenes Git-Repo als Root, `crontab` und `tmux` als Fakes im PATH. Er deckt Skip-Gründe, Moduswahl nach Wochentag, Idempotenz von install und uninstall und dass kein Env-Wert in der Ausgabe steht. Der Test wird in die Liste von run.sh aufgenommen. SPDX-Header in beiden neuen Dateien.
Beweis: Sammelläufe 10-15…11-11: 14 je Woche nach der Schwelle 3 Merges, Capstone-Platz nur in 12 von 54 Startmomenten · Dedup-Key: ref:harness:sammellauf:nachts
Verify: bash scripts/dev/verify.sh scripts --strict -- nightly_test run_flags_test
Doku: → T7

### T4 — R-1337: heavy.sh — schemathesis-Rot ist `fund`, nicht flaky/extern  [ ]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Änderung: classify_red_step gibt dem Schritt `schemathesis` sofort das Urteil `fund`: kein Retry, keine Zweit-VM, Detail „Fuzz-Fund: Beispiel im Log, BUG-Zeile anlegen“. Der Teil zählt den Schritt als rot (FAIL). Der Report führt `fund` in der Sichtungsliste, ohne REG-Zeile. Prüfen und nötigenfalls ergänzen, dass `weekly` vor der Capstone die eigene warm gehaltene Box des Teils `all` freigibt. heavy_test.sh deckt `fund` ab (Teil FAIL, kein Retry-Aufruf, kein REG-Eintrag).
Beweis: Sammelläufe 09-25, 11-02, 11-04-0628, 11-04-1951: schemathesis-Produktfehler als flaky/extern etikettiert (R-0089, R-1107, R-1131) · Dedup-Key: ref:harness:heavy:schemathesis-fund
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: → T7

### T5 — R-1337: Regeln auf den nächtlichen Sammellauf umstellen  [ ]
Komponente: scripts · Dateien: .claude/skills/feature-build/SKILL.md, .claude/skills/test/SKILL.md, .claude/rules/testing.md, CLAUDE.md
Änderung: /feature-build §5 neu. Der Sammellauf läuft nachts per `nightly.sh`, die Session startet ihn nicht mehr nach Merges. Beim Start und nach jedem Merge liest sie den neuesten Report. Rot → Verursacher suchen, REG-Zeile; bis der rote Schritt per `--step`-Lauf über `main` wieder grün ist, gibt es keinen `linux-full`-Merge (außer Fix, Revert, SEC auf Kevins Wort). `fund` ist eine BUG-Zeile ohne Sperre, UNVERIFIED wie bisher. Dazu §4.3 und §4.8 angleichen. test-Skill: `all` und `weekly` startet der Cron-Lauf (Kevin 2026-11-11) als Ausnahme zu „nichts startet von selbst“; kein ff-merge im Haupt-Checkout, solange `ah-nightly` läuft. testing.md „Lange Läufe“ und CLAUDE.md §3 („ist der Sammellauf fällig“ → „braucht der Report der Nacht eine Reaktion“) und §5 (Heavy) angleichen.
Beweis: wie T3 · Dedup-Key: ref:harness:sammellauf:nachts
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test session_status_test
Doku: → T7
Abhängt von: T3, T4

### T6 — R-1338: Server-pytest aus dem Box-Lauf, wenn die CI dieselben Tests fährt  [ ]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh
Änderung: Zuerst die Probe: die übersprungenen Server-Tests des letzten grünen Box-Laufs (`.ah-out/weekly/<lauf>/junit/server-pytest.xml`) gegen die eines grünen `main`-Laufs der CI (`-rs`-Ausgabe der drei Server-Legs) vergleichen. Ergebnis und Entscheidung kommen unter `## Entscheidungen`. Bei Gleichheit (oder Unterschied nur im testcontainers-Modus) entfällt `server-pytest` im Teil `rest` des schweren Laufs; Pflichtmenge und `--strict` bleiben sonst unverändert, Test in run_flags_test.sh. Fährt die VM Tests, die die CI überspringt: `[~]` mit Grund, die Zeile bleibt mit der Liste offen.
Beweis: Teil rest p50 111 min seit 11-05, Server-pytest p50 1 817 s; einziger VM-eigener Fund R-0824 (testcontainers-Modus, Testfehler) · Dedup-Key: ref:harness:sammellauf:server-pytest
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test
Doku: → T7

### T7 — Doku: Wochenlauf nachts, Klasse `fund`, Timer  [ ]
Komponente: scripts · Dateien: DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: DEVELOPMENT.md, Abschnitt „Wochenlauf (heavy.sh)“: Auslöser nachts per `nightly.sh` (install/uninstall/status, Logdatei), samstags `weekly`; ggf. Server-pytest außerhalb des Box-Laufs. cicd.html DE+EN, Abschnitt „Wochenlauf“: Auslöser und die Klasse `fund`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: DEVELOPMENT.md, docs/developer/cicd.html DE+EN
Task-Review: am Ende
Abhängt von: T3, T4, T5, T6

## Entscheidungen
