# Harness: Wackler-Politik, Triage-Dauerauftrag, Sammellauf nachts — Task-Ledger
Status: bereit · Branch: feature/arch-workflow-1 · Review: pro Task
Spec: docs/features/arch-workflow-1.md (Roadmap R-1335, R-1336, R-1337, R-1338, R-1346)
Heavy: none — Harness-Text und Harness-Skripte mit hermetischen Tests; den echten Beweis für nightly.sh und die heavy.sh-Klasse `fund` liefert der erste nächtliche Lauf nach dem Merge
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1335: Wackler-Fix nur mit Dauerlauf, keine kurzen festen Fristen in Tests  [x]
Komponente: scripts · Dateien: .claude/rules/testing.md, .claude/agents/reviewer.md, .claude/skills/feature-build/SKILL.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @63b8a3380 2026-11-11T17:16:17+01:00
Review: approve (.ah-out/review/arch-workflow-1/T1.verdict.json)
Änderung: testing.md bekommt die Regel „Wackler“: Ein Fix für einen belegten Wackler gilt erst nach einem grünen Dauerlauf des betroffenen Tests (50 Wiederholungen: Go `-count=50`, Rust/Python als Schleife über den Einzeltest), dessen Summary in den Commit-Body gehört. Für einen Windows-only-Wackler ohne Schleifenweg heißt der Fix „nicht verifiziert“. Dazu die Regel „Fristen“: Tests warten auf eine Bedingung mit einer Obergrenze von mindestens 30 s statt auf eine kurze feste Frist; ausgenommen ist ein Test, der die Frist selbst prüft. reviewer.md Kriterium 3: eine neue kurze feste Frist und ein Wackler-Fix ohne Dauerlauf-Beleg sind `wichtig`. /feature-build §3 Schritt 3 verweist darauf.
Beweis: Workflow-Analyse 2026-11-11 (privat), Wackler-Tabelle: Wiederkehr nach #423, #310, #461, #445, #277/#336/#446 · Dedup-Key: ref:harness:wackler:politik
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: keine (Ablauf steht in .claude/; cicd.html verweist dorthin)

### T2 — R-1336: Triage-Dauerauftrag und Nit-Sammelzeile  [x]
Komponente: scripts · Dateien: .claude/skills/roadmap/SKILL.md, .claude/skills/feature-build/SKILL.md, .claude/agents/reviewer.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @475078937 2026-11-11T18:14:56+01:00
Review: approve (.ah-out/review/arch-workflow-1/T2.verdict.json)
Änderung: roadmap-Skill, neuer Abschnitt „Dauerauftrag (Kevin 2026-11-11)“: Bedingungen (BUG/REF mit Beweis, klein-Bereich; kein SEC, kein `security`-Fund, keine Datei aus `review-risk.txt`, kein Harness-Pfad, keine Verhaltens-/API-/Migrationsänderung). Annahme und Einplanung ohne Triage gelten erst, wenn CLAUDE.md §4 den Dauerauftrag nennt (T8); bis dahin bleiben gedeckte Funde `neu`. `/roadmap` zählt die ungesichteten Dauerauftrag-Zeilen, `/roadmap triage` legt sie zum Veto vor und vermerkt „gesichtet“. Nit-Regel (gilt sofort): mitbeheben nur in einer laufenden Korrekturrunde; sonst Sammelzeile aus Nits, die die Bedingungen erfüllen, Harness-Nits `zurückgestellt`, Sicherheits-Nits neutral in Kevins Triage. /feature-build §3 und reviewer.md verweisen darauf.
Beweis: Roadmap-Historie 09-09…11-11: 29 Zeilen/Tag seit 10-29, Triage Median 15,4 h, 91 von 115 Nits gebaut · Dedup-Key: ref:harness:roadmap:triage-dauerauftrag
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: keine (Ablauf steht in CLAUDE.md und .claude/)

### T3 — R-1337: nightly.sh startet den Sammellauf per Cron  [x]
Komponente: scripts · Dateien: scripts/tests/nightly.sh, scripts/tests/nightly_test.sh, scripts/tests/run.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ce4d5de95 2026-11-11T17:51:08+01:00
Review: approve (.ah-out/review/arch-workflow-1/T3.verdict.json)
Änderung: Neues Skript `nightly.sh run|install|uninstall|status [--dry-run]` nach der Spec:
- Vorprüfung: Haupt-Checkout auf `main` und sauber; kein tmux `ah-*`; `fetch` + `merge --ff-only`; `vm.py list` endet mit 0 (vm.py liest `pve.env` und `settings.local.json` selbst, die Cron-Umgebung reicht; seine Liste nur nach `.ah-out/nightly-vmlist.out`).
- Start: `heavy.sh all`, samstags `weekly`, in tmux `ah-nightly`; ein Überspringen mit Grund nach `.ah-out/nightly.log`.
- `install`/`uninstall`: genau eine markierte Crontab-Zeile.

Hermetischer Test über Overrides: Befehl statt heavy.sh, eigenes Git-Repo mit Origin als Root, `crontab` und `tmux` als Fakes im PATH, vm.py als Fake. Er deckt Skip-Gründe, Probelauf ohne Seiteneffekte, Moduswahl nach Wochentag, Idempotenz von install und uninstall und dass die VM-Liste nicht ins Log gerät. Der Test wird in die Liste von run.sh aufgenommen. SPDX-Header in beiden neuen Dateien.
Beweis: Sammelläufe 10-15…11-11: 14 je Woche nach der Schwelle 3 Merges, Capstone-Platz nur in 12 von 54 Startmomenten · Dedup-Key: ref:harness:sammellauf:nachts
Verify: bash scripts/dev/verify.sh scripts --strict -- nightly_test run_flags_test
Doku: → T7

### T4 — R-1337: heavy.sh — schemathesis-Rot ist `fund`, nicht flaky/extern  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ac1aebc91 2026-11-11T17:58:53+01:00
Review: approve (.ah-out/review/arch-workflow-1/T4.verdict.json)
Änderung: classify_red_step gibt dem Schritt `schemathesis` sofort das Urteil `fund`: kein Retry, keine Zweit-VM, Detail „Fuzz-Fund: Beispiel im Log, BUG-Zeile anlegen“. Der Teil zählt den Schritt als rot (FAIL). Der Report führt `fund` in der Sichtungsliste, ohne REG-Zeile. Prüfen und nötigenfalls ergänzen, dass `weekly` vor der Capstone die eigene warm gehaltene Box des Teils `all` freigibt. heavy_test.sh deckt `fund` ab (Teil FAIL, kein Retry-Aufruf, kein REG-Eintrag).
Beweis: Sammelläufe 09-25, 11-02, 11-04-0628, 11-04-1951: schemathesis-Produktfehler als flaky/extern etikettiert (R-0089, R-1107, R-1131) · Dedup-Key: ref:harness:heavy:schemathesis-fund
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: → T7

### T5 — R-1337: Regeln auf den nächtlichen Sammellauf umstellen  [x]
Komponente: scripts · Dateien: .claude/skills/feature-build/SKILL.md, .claude/skills/test/SKILL.md, .claude/rules/testing.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @a848521c4 2026-11-11T20:01:32+01:00
Review: approve (.ah-out/review/arch-workflow-1/T5.verdict.json)
Änderung: /feature-build §5 neu. Der Sammellauf läuft nachts per `nightly.sh`, die Session startet ihn nicht mehr nach Merges. Beim Start und nach jedem Merge liest sie den neuesten Report. Rot → Verursacher suchen, REG-Zeile; bis der rote Schritt per `--step`-Lauf über `main` wieder grün ist, gibt es keinen `linux-full`-Merge (außer Fix, Revert, SEC auf Kevins Wort). `fund` ist eine BUG-Zeile ohne Sperre, UNVERIFIED wie bisher. Dazu §4.3 und §4.8 angleichen. test-Skill: `all` und `weekly` startet der Cron-Lauf (Kevin 2026-11-11) als Ausnahme zu „nichts startet von selbst“; kein ff-merge im Haupt-Checkout, solange `ah-nightly` läuft. testing.md „Lange Läufe“ und CLAUDE.md §3 („ist der Sammellauf fällig“ → „braucht der Report der Nacht eine Reaktion“) und §5 (Heavy) angleichen.
Beweis: wie T3 · Dedup-Key: ref:harness:sammellauf:nachts
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test session_status_test
Doku: → T7
Abhängt von: T3, T4

### T6 — R-1338: Server-pytest aus dem Box-Lauf, wenn die CI dieselben Tests fährt  [~] (verschoben in arch-workflow-2: Probe 2026-11-11 belegt VM ⊂ CI (CI-Lauf 43029762530 py3.14: 3319 passed, 0 skipped; Box 2026-11-11-0725: 3317 Tests, 39 skipped), aber das Auslassen braucht eine Env-Weiterleitung in scripts/vm/iter.sh und Tests dort — mehr als die zwei geplanten Dateien)
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh
Änderung: Zuerst die Probe: die übersprungenen Server-Tests des letzten grünen Box-Laufs (`.ah-out/weekly/<lauf>/junit/server-pytest.xml`) gegen die eines grünen `main`-Laufs der CI (`-rs`-Ausgabe der drei Server-Legs) vergleichen. Ergebnis und Entscheidung kommen unter `## Entscheidungen`. Bei Gleichheit (oder Unterschied nur im testcontainers-Modus) entfällt `server-pytest` im Teil `rest` des schweren Laufs; Pflichtmenge und `--strict` bleiben sonst unverändert, Test in run_flags_test.sh. Fährt die VM Tests, die die CI überspringt: `[~]` mit Grund, die Zeile bleibt mit der Liste offen.
Beweis: Teil rest p50 111 min seit 11-05, Server-pytest p50 1 817 s; einziger VM-eigener Fund R-0824 (testcontainers-Modus, Testfehler) · Dedup-Key: ref:harness:sammellauf:server-pytest
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test
Doku: → T7

### T7 — Doku: Wochenlauf nachts, Klasse `fund`, Timer  [x]
Komponente: scripts · Dateien: DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b2a0e40c6 2026-11-11T20:03:37+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: DEVELOPMENT.md, Abschnitt „Wochenlauf (heavy.sh)“: Auslöser nachts per `nightly.sh` (install/uninstall/status, Logdatei), samstags `weekly`; ggf. Server-pytest außerhalb des Box-Laufs. cicd.html DE+EN, Abschnitt „Wochenlauf“: Auslöser und die Klasse `fund`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: DEVELOPMENT.md, docs/developer/cicd.html DE+EN
Task-Review: am Ende
Abhängt von: T3, T4, T5, T6

### T9 — R-1346: Release-Takt — wöchentlich Beta nach grünem weekly  [x]
Komponente: scripts · Dateien: .claude/rules/release.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @02fa28d13 2026-11-11T19:54:19+01:00
Review: approve (.ah-out/review/arch-workflow-1/T9.verdict.json)
Änderung: release.md, „Ablauf und Kanäle“: Beta ist ab dem ersten grünen `weekly` mit Capstone ein wöchentliches Pre-release-Tag vom `main` (Kevin taggt, die Session bereitet Bump-Commit und `check-versions.sh` vor). „Latest“ (Stable) bleibt an den Umfang von R-1110 gebunden. Vor jedem Beta-Tag gelten die drei Ebenen wie bisher.
Beweis: Workflow-Analyse 2026-11-11: Merge → Release Median 9,5 d, p90 29 d, 215 Merges unveröffentlicht · Dedup-Key: ref:harness:release:weekly-beta
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: keine (release.md ist die Stelle; cicd.html verweist für Kanäle dorthin — in T7 prüfen)

### T8 — CLAUDE.md an Dauerauftrag und nächtlichen Sammellauf angleichen  [x]
Komponente: scripts · Dateien: CLAUDE.md, .claude/rules/release.md, docs/features/arch-workflow-1.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @181ff3f15 2026-11-11T20:08:07+01:00
Review: approve (.ah-out/review/arch-workflow-1/T8.verdict.json)
Änderung: Dazu die Nits aus der T9-Prüfung in release.md (allgemeiner Ablauf verweist auf den Takt; Evidenz kommt vom nächtlichen Samstags-`weekly`). Drei Sätze in CLAUDE.md: §4 nennt den Dauerauftrag des roadmap-Skills als Annahme durch Kevin; §3 fragt statt „ist der Sammellauf fällig“, ob der Report der Nacht eine Reaktion braucht; §5 (Heavy) sagt, dass `linux-full` in den nächtlichen Sammellauf über `main` geht (`nightly.sh`, Kevin 2026-11-11), den die Session nicht mehr selbst startet. Kevin hat die Änderung durch die Session am 2026-11-11 freigegeben.
Verify: bash scripts/dev/verify.sh scripts --strict -- harness_consistency_test
Doku: keine (CLAUDE.md ist die Stelle)
Abhängt von: T2, T5

## Entscheidungen
- T2 (2026-11-11): Die geplante Ergänzung in CLAUDE.md §4 („angenommen … oder der Dauerauftrag“) hat der Auto-Modus-Klassifikator der Session abgelehnt; CLAUDE.md bleibt in diesem Zug unverändert. Der roadmap-Skill stützt den Dauerauftrag auf „angenommen“ in §4. Die CLAUDE.md-Sätze legt die Session Kevin als Diff vor.
- T2 Runde 2 (2026-11-11, reviewer + security): Der Dauerauftrag gilt erst, wenn CLAUDE.md §4 ihn nennt (T8, Kevin); ausgeschlossen sind zusätzlich Funde des `security`-Agenten und Dateien aus `review-risk.txt`, die Harness-Pfade sind ausdrücklich genannt. Nits: nur in einer laufenden Korrekturrunde mitbeheben, weil eine Änderung nach `approve` eine weitere Prüfrunde auslöst (88 solche Runden in vier Wochen); die Sammelzeile nimmt nur Nits, die die Bedingungen erfüllen, Harness-Nits werden `zurückgestellt`, Sicherheits-Nits gehen neutral in Kevins Triage. CLAUDE.md aus `Dateien:` von T2 und T5 genommen, T8 trägt es.
- T2 Runde 2 (2026-11-11): reviewer `request_changes` (wichtig: bis T8 regelte keine Stelle die Nits), security `approve`. Eingearbeitet: das Gate betrifft nur Annahme und Einplanung, die Nit-Regel gilt sofort, die Nachlese-Zeile bleibt bis T8 `neu`. Eine dritte Prüfrunde sieht /feature-build nicht vor: T2 steht auf `[?]` bis Kevin entscheidet (dritte Runde oder Übergabe), zusammen mit T8.
- T3 (2026-11-11): nightly.sh lädt keine Provider-Umgebung. vm.py und lib.sh lesen `~/.config/adminhelper/pve.env` und den `env`-Block von `.claude/settings.local.json` selbst (vm.py Kopfkommentar, `read_pve_env`). Damit gelangen in nightly.sh weder Token noch Env-Werte. Die Liste von `vm.py list` (Boxen, Adressen) geht nur nach `.ah-out/nightly-vmlist.out`.
- T6 (2026-11-11): Probe VM gegen CI. CI (main-Lauf 43029762530, py3.14, beide Shards): 1660 + 1659 = 3319 passed, 0 skipped. Box (Sammellauf 2026-11-11-0725, junit server-pytest.xml): 3317 Tests, 39 skipped (Alembic ohne Postgres-URL, Image-Tests ohne Docker-Image, Redis). Die Box fährt keinen Test, den die CI überspringt; einzig der testcontainers-Modus läuft nur dort (R-0824 war ein Testfehler in diesem Modus). Umsetzung (Schritt im Teil rest auslassen, Pflichtmenge anpassen, iter.sh-Weiterleitung) in arch-workflow-2.
- Kevin 2026-11-11 (Antworten in der Session): CLAUDE.md darf die Session ändern (T8); T2 bekommt eine dritte Prüfrunde; Release: wöchentlich Beta nach grünem weekly mit Capstone, Latest wie R-1110 (T9, R-1346, Notiz an R-1110); Cron-Zeile nach dem Merge installieren, Restrisiko (unbeaufsichtigter Lauf mit Proxmox-Zugriff) von Kevin getragen.
- T9 (2026-11-11, reviewer + security, Kevins Antworten): Jedes Wochen-Beta ist das nächste Minor (das erste 0.47.0); Latest wird das erste Beta mit dem Umfang von R-1110. Getaggt wird der vom `weekly` geprüfte Commit: Release-Branch `release/vX.Y.Z` ab diesem Commit, Bump darauf, nur Bump-Dateien im Diff; Kevin taggt, publiziert und merged den Branch per PR nach `main`.
- T5 Runde 2 (2026-11-11, reviewer wichtig): Jeder rote Schritt außer `fund` sperrt wie bisher; eine REG-Zeile gibt es nur bei `reg` (legt heavy.sh an), `unbestaetigt`, `extern`, `fail` sichtet Kevin. Mitgenommen: manueller Lauf prüft vorher auf `ah-nightly`, Abschnitt „Rhythm“, security-Nit „im Zweifel neutrale SEC-Zeile“. Die drei T9-Nits (release.md) trägt T8.
