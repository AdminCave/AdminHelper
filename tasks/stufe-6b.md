<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stufe 6b — der Reviewer als eigener Prozess — Task-Ledger
Status: bereit · Branch: harness/stufe-6b · Commit-Granularität: pro Task · Review: pro Task (feature-review; Harness-Pfade ⇒ Reviewer Opus, eine Runde) · Modell: Opus
Freigabe: Kevin, 2026-10-03 (Design-Gate Stufe 6b, „Freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: docs/features/stufe-6b.md (Roadmap R-0155, R-0147, R-0150, dazu Teile von R-0151 und R-0154)
Heavy: none — nur Harness-Skripte unter scripts/dev, eine Agent-Datei, ihre hermetischen Tests (claude-Stub), ein Skill und Doku; kein Stack-, Gateway-, PKI- oder Install-Pfad. Der echte CLI-Kleinstlauf in T1 ist Evidenz in Kevins Session, der Pilot nach dem Merge Handarbeit.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-03 von der Aufsicht (adminhelper-ac); Entscheidungen Kevin 2026-10-03 (A–E, Spec „Design“).
Zeilenangaben main@8a45c893. Bau interaktiv (Harness-Pfade). Jede neue Datei unter `scripts/dev/` kommt in derselben
Task nach `scripts/dev/harness-paths.txt`; jeder neue Test in `AH_SCRIPT_TESTS_DEFAULT` (`scripts/tests/run.sh:586`).
Kein Test ruft die echte CLI: alle hermetischen Tests nehmen einen `claude`-Stub auf PATH.

### T1 — CLI-Probe als Beweis-Instrument: was `claude -p` für den Reviewer wirklich tut  [x]
Komponente: scripts · Dateien: scripts/dev/review-cli-probe.sh, scripts/tests/review_cli_probe_test.sh, scripts/dev/harness-paths.txt, scripts/tests/run.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @3c69006b 2026-10-03T11:41:12+02:00
Review: approve (opus, two rounds: round 1 request_changes, ok without proof in (4)/(5)/(10) and untested traces, sharpened and re-measured; round 2 approve, one surviving mutant covered). Real probe: 9 ok, 0 fail, 1 unknown
Änderung: `review-cli-probe.sh [--claude <bin>] [--budget <usd>]` fährt einen Kleinstlauf gegen einen Fixture-Diff
(eine Zeile in einer Wegwerf-Worktree, `mktemp -d` im TMPDIR des Aufrufers, `trap` räumt auf) mit den Flags aus Spec
„Design“ Schritt 5 und wertet das JSON aus. Es prüft und druckt je Punkt `ok|fail|unknown` plus eine Summary-Zeile
`review-cli-probe: N ok, M fail, K unknown`:
(1) Anmeldung trägt (Antwort kommt, `is_error` false);
(2) `structured_output` vorhanden und schemakonform (`review-output.schema.json` ab T2, bis dahin ein Minimal-Schema
im Skript);
(3) welches Modell lief (aus `modelUsage`/`system/init`) — übersteuert `--model` das Frontmatter-`model`?;
(4) **Gegenprobe Schreiben:** der Prompt verlangt `echo x > <worktree>/probe.txt`, `git commit --allow-empty -m x` und
`bash scripts/vm/iter.sh --help` ⇒ alle drei in `permission_denials`, `probe.txt` existiert danach nicht, `git log` der
Worktree unverändert;
(5) Projekt-Allow-Regeln bleiben draußen: mit den gewählten `--setting-sources` wird `bash scripts/tests/heavy.sh
--help` verweigert;
(6) Budget-Deckel: zweiter Lauf mit `--max-budget-usd 0.01` ⇒ `error_max_budget_usd` (oder `unknown` mit Begründung);
(7) Feldname der Fehlerart in der CLI-JSON (`subtype`/`error_type`).
**Startfehler = FAIL, nie SKIP-grün:** ein unbekanntes Flag, keine Anmeldung, ein Exit ≠ 0 ohne JSON, eine leere
Antwort ⇒ Exit 1 mit Grund; Exit 0 nur, wenn kein Punkt `fail` ist. Die Auswertung ist eine eigene Funktion, hermetisch
getestet mit einem `claude`-Stub (Fixture-JSONs: Erfolg; `structured_output` fehlt; Schreibversuch ohne Denial;
Datei existiert danach; `error_max_budget_usd`; Exit 2 mit `unknown option`; leere Ausgabe) — **nur dieser hermetische
Teil ist das Verify**. Rot vorher: das Skript fehlt.
**Evidenz in Kevins Session (vor dem Haken, `--budget 0.5`):** `bash scripts/dev/review-cli-probe.sh --budget 0.5`
einmal echt; die Summary-Zeile und das Ergebnis jedes Punkts aus der Spec-Liste „Nicht verifiziert“ (Modell-Override,
Frontmatter-Hooks ohne Workspace-Trust, `--setting-sources`, Budget mit Abo, verschachteltes `claude -p` aus einer
Claude-Session, Feldname) stehen danach als `Messung:`-Zeilen unter dieser Task. Ein `fail` in (4) oder (5) ist ein
STOPP für T2–T7 und geht an Kevin.
Abweichung: statt `bash scripts/vm/iter.sh --help` (4) und `bash scripts/tests/heavy.sh --help` (5) nimmt die Probe
Befehle, die bei einem `fail` nichts anrichten (`iter.sh` kennt kein `--help` und hätte VM-Schritte gestartet):
`python3 -c` mit einer Marke im Probe-Verzeichnis und `git switch -c` (vom Projekt erlaubt) in der Wegwerf-Worktree.
Messung: CLI 2.1.285 (Runner-Pin 2.1.280), aus Kevins laufender Claude-Session (verschachteltes `claude -p` startet);
sechs echte Läufe zusammen ≈ 0,47 $ (je Lauf 0,04–0,13 $, Budget-Lauf 0,02–0,05 $).
Messung: eine Agent-Datei unter `.claude/agents/` findet `claude -p --agent` mit `--setting-sources user` nicht
(Startfehler „--agent … not found“); Projekt-Agenten hängen an der Quelle `project`, die draußen bleiben muss.
`--agents '<json>' --agent <name>` trägt.
Messung: `--tools` bzw. die `tools` des Agenten ohne `StructuredOutput` ⇒ `subtype: success`, aber kein
`structured_output` (das JSON steht nur als Text in `result`); mit `StructuredOutput` in beiden Listen (oder ohne
Allowlist) ist es da.
Messung: `--model sonnet` übersteuert das `model: haiku` des Agenten (gelaufen: claude-sonnet-5-5).
Messung: Schreib-Gegenprobe ok — Umleitung, `git commit`, `python3 -c` verweigert, keine Spur; Projekt-Regeln draußen —
`git switch -c` (vom Projekt erlaubt) verweigert, beides bei `--setting-sources user`.
Messung: PreToolUse-Hooks aus `--settings` feuern im Print-Modus ohne Workspace-Trust; der harness-guard als solcher
Hook (AH_AUTONOMOUS=1) verweigert `cp` auf CLAUDE.md — seine eigene Ausgabe im Hook-Log: `harness path: CLAUDE.md
(autonomous run; bash scripts/dev/harness.sh off lifts this)` —, die Kontroll-Kopie lief; Hook-Verweigerungen stehen in
`permission_denials`. Frontmatter-Hooks: nicht gemessen (die Form agent-file startet nicht) — für den Guard ohne Belang.
Messung: `--max-budget-usd 0.01` greift mit Abo-Anmeldung (`error_max_budget_usd` nach dem ersten Turn, ≈ 0,02 $ —
der Deckel stoppt nach, nicht vor einer Anfrage); die Fehlerart steht im Feld `subtype`.
Messung: `review-cli-probe: 9 ok, 0 fail, 1 unknown` (Form agents-json, Werkzeuge allowlist+so, letzter Lauf mit dem
geschärften Instrument: (4)/(5) „ok“ nur bei Eintrag in `permission_denials`, (10) nur mit dem Deny des Guards selbst;
unknown = (9), keine Agent-Datei in dieser Form).
Messung (Feldnamen wörtlich aus der CLI-JSON, 2.1.285): `type` = `"result"`; `subtype` = `"success"` bzw.
`"error_max_budget_usd"`; `is_error`; `terminal_reason` = `"completed"` bzw. `"budget_exhausted"`; `stop_reason`;
`structured_output`; `result`; `errors` (Budget-Lauf: `["Reached maximum budget ($0.01)"]`); `permission_denials[]` mit
`tool_name`, `tool_use_id`, `tool_input.command`; `modelUsage` (Schlüssel = Modell-ID, etwa `claude-sonnet-5-5`, je
Eintrag `costUSD`); `total_cost_usd`; `num_turns`; `duration_ms`; `api_error_status`; `session_id`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T7)

### T2 — Agent-Datei, Review-Settings und Ausgabe-Schema  [x]
Komponente: scripts · Dateien: .claude/agents/review-task.md, scripts/dev/review-settings.json, scripts/dev/review-output.schema.json, scripts/dev/harness-paths.txt, scripts/tests/hooks_test.sh, scripts/tests/review_scripts_test.sh, docs/features/stufe-6b.md, scripts/dev/review-cli-probe.sh, scripts/tests/review_cli_probe_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @1dd0ce7e 2026-10-03T12:08:16+02:00
Review: approve with two rounds spent (opus): round 1 request_changes on the hook not setting AH_AUTONOMOUS, git --output/--no-index and the mutants shape, fixed; round 2 request_changes on git diff reading a path outside without --no-index, fixed with the reviewer cases as a rule test, no third round
Änderung: `.claude/agents/review-task.md` mit `name`, `description`, `tools: Read, Grep, Glob, Bash`,
`disallowedTools: Edit, Write, NotebookEdit, WebFetch, WebSearch`, `model: sonnet`, `maxTurns: 80`, ohne `memory`;
der Text sind die 7 Kriterien aus `.claude/skills/feature-review/SKILL.md` (Verweis, keine Kopie) plus die
Ausführungspflichten: Probe- und Contracts-Ergebnis stehen im Prompt und werden nicht nachgefahren, höchstens zwei
`--mutate`, `evidence` je blocker/wichtig (konkrete Eingabe → falsches Ergebnis), Ausgabe nur über das Schema.
`review-settings.json`: `permissions.defaultMode: dontAsk`, Allow nur `Bash(git diff *)`, `Bash(git show *)`,
`Bash(git log *)`, `Bash(git status *)`, `Bash(bash scripts/dev/review-probe.sh *)`, Deny `Edit`, `Write`,
`Bash(bash scripts/dev/verify.sh *)`, `Bash(bash scripts/tests/run.sh *)`, `Bash(git add *)`, `Bash(git commit *)`,
`Bash(curl *)`, `Bash(wget *)`; der harness-guard als PreToolUse-Hook wie in `runner-settings.json`. Was T1 über
`--model` und Frontmatter-Hooks gemessen hat, entscheidet: eine Datei mit Modell per Flag, sonst zwei
(`review-task.md`, `review-task-xhigh.md`). `review-output.schema.json`: `verdict` (Enum wie 6a), `findings[]` (wie 6a),
optional `mutants[]` `{file, line, replacement, result}`; `additionalProperties: false`.
Abweichung (T1-Messung, Spec „Design“ Schritt 5): `tools` nennt zusätzlich `StructuredOutput`; der Reviewer kommt
als `--agents`-JSON, die Agent-Datei bleibt die Quelle. Aus dem Review: der Hook setzt selbst `AH_AUTONOMOUS=1`, Deny
auch `Bash(git *--output*)`, `Bash(git *--no-index*)` und Pfade außerhalb (`Bash(git * /*)`, `Bash(git *../*)`,
`Bash(git * ~*)`), Allow für review-probe.sh nur mit `--mutate`; die CLI-Probe
nimmt ab hier das echte Ausgabe-Schema.
Messung: `claude -p --json-schema` (2.1.285) nimmt das echte `review-output.schema.json` an — CLI-Probe mit diesem
Schema `9 ok, 0 fail, 1 unknown`, ≈ 0,08 $ (T1 und T2 zusammen ≈ 0,55 $).
Rot vorher: hooks_test — mit `review-settings.json` als Settings verweigert der Guard `sed -i` auf eine Repo-Datei und
`rm -rf /tmp/tmp.*` (wie in jeder Session), `bash scripts/dev/review-probe.sh … --mutate …` geht durch;
review_scripts_test — das Ausgabe-Schema ist gültiges draft-07, eine Musterantwort passt, eine mit `tree_hash` (Feld des
Runners) wird verworfen; die Agent-Datei hat genau die Werkzeug-Liste oben (grep-Paar). `review-settings.json` und
`review-output.schema.json` kommen nach `harness-paths.txt` (`.claude/**` steht schon drin).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T7)
Abhängt von: T1

### T3 — Verdict-Bindung: Schema v2 und `check-verdict` gegen Ledger und Task  [x]
Komponente: scripts · Dateien: scripts/dev/review-verdict.schema.json, scripts/dev/review.sh, scripts/tests/review_scripts_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b52ee5b2 2026-10-03T12:30:20+02:00
Review: approve after one round (opus): round 1 request_changes on round: true passing the enum (python's True == 1), fixed in check() with type-strict enum/const and the reviewer's case as a test; nits done: --task with an empty id binds, exit head names another task
Änderung: Schema `schema_version` 1 oder 2; v2 bekommt `round` (1|2), `num_turns`, `duration_s`, optional `mutants[]`
und macht `probe` Pflicht (R-0147b; `applicable: false` braucht `reason`). `check-verdict <datei> --tree <hash>
[--task <ledger> <id>]` (`review.sh:650`): mit `--task` muss `task.ledger`/`task.id` passen, sonst Exit 4 (R-0147a).
Refactor-Regel (R-0151.2): `probe.applicable: false, reason: no-test-change` ist für approve kein Hindernis; `applicable:
true, red_without_change: false` bleibt Exit 3. Ein `mutants`-Eintrag mit `survived` macht approve nicht ungültig, wird
aber in der Review-Zeile genannt.
Rot vorher: Verdict für T1 mit `--task <l> T2` ⇒ 4; v2 ohne `probe` ⇒ 2; v2 mit `no-test-change` und approve ⇒ 0;
v2 mit `round: 3` ⇒ 2; ein v1-Verdict wie in den 6a-Tests bleibt gültig.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T7)

### T4 — `review-run.sh`: Prompt bauen, Prozess starten, Verdict schreiben  [x]
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @dd387ad6 2026-10-03T13:06:15+02:00
Review: approve (opus, one round; nits done: a non-zero CLI exit is 74, --probe needs applicable, a tasks/private ledger and a timeout of 0 are refused, the spec names what the guard itself still swallows, the maxTurns deviation is in the ledger)
Entscheidung Kevin (2026-10-03, über die Aufsicht): die Reviewer-Definition zieht nach `scripts/dev/review-agent.md`
(kein Subagent unter `.claude/agents/` mehr, nur Quelle für review-run.sh); die Verschiebung kommt in diese Task —
Pfad in `harness-paths.txt`, Spec-Satz, Test.
Entscheidung Kevin (2026-10-03, über die Aufsicht, R-0159): der Guard-Hook in `review-settings.json` wird fail-closed —
fehlt der Guard, scheitert oder hängt er, endet der Hook mit Exit 2 (Exit 127 und ein Hook-Timeout blockieren laut
Doku nicht); Regel-Test auf den Befehlstext und der Fall „Guard fehlt ⇒ blockiert“ in `hooks_test.sh`.
Komponente: scripts · Dateien: scripts/dev/review-run.sh, scripts/tests/review_run_test.sh, scripts/dev/harness-paths.txt, scripts/tests/run.sh, scripts/dev/review-agent.md, .claude/agents/review-task.md, scripts/tests/review_scripts_test.sh, docs/features/stufe-6b.md, scripts/dev/review-settings.json, scripts/tests/hooks_test.sh
Änderung: `review-run.sh <ledger> <id> --tree <hash> --round <n> --probe <json> --contracts <json> [--prior
<verdict>]` (nur von task-close gerufen): Modell und Effort aus `review.sh risk --staged`; Prompt aus Task-Text, Spec-
Pfad, `git diff --staged`, neuen Dateien, Tree-Hash, Probe, Contracts, Verify-Summary, bei Runde 2 dem Pfad der
Runde 1; Aufruf mit den Flags und Deckeln aus Spec „Design“ (Timeout 1200 s; `--max-turns` 60/80;
`--max-budget-usd` 5/15; die Flag-Liste so, wie T1 sie bestätigt hat); `CLAUDE_BIN` überschreibbar (Test-Stub).
Schreibt `.ah-out/review/<slug>/<id>.r<n>.raw.json` und, aus `structured_output` plus Runner-Feldern (Spec „Design“
Schritt 6), `<id>.r<n>.verdict.json`; druckt dessen Pfad. Exit 0 Verdict geschrieben (gleich welches Urteil) · 2
Aufruffehler · 74 Startfehler, Timeout, `error_*`, kein oder schemawidriges `structured_output` (Entscheidung D; dann
keine Verdict-Datei).
Rot vorher (Stub-Fälle): Erfolg mit approve ⇒ 0 und Verdict mit allen Runner-Feldern, `check-verdict` nimmt es;
request_changes ⇒ 0, Verdict request_changes; Müll-JSON ⇒ 74, keine Datei; Stub schläft über ein auf 2 s gesetztes
Timeout ⇒ 74; `error_max_budget_usd` ⇒ 74; Exit 2 mit `unknown option` ⇒ 74; `xhigh`-Diff ⇒ der Stub sieht
`--model opus --effort xhigh --max-turns 80`; der Prompt enthält Tree-Hash und Probe-JSON und keine Datei aus
`tasks/private/`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T7)
Abhängt von: T2, T3
Messung (2026-10-03, CLI 2.1.285): der Prompt über stdin plus eine Anweisung als Argument kommt mit `--agents`/`--agent`
und `--json-schema` an — Kleinstlauf (haiku) mit dem Codewort nur im stdin: `subtype: success`, `is_error: false`,
`structured_output: {"word": "PELICAN-7"}`, `num_turns: 2`, `total_cost_usd: 0.003077`.
Abweichung: `maxTurns` fällt aus `review-agent.md` (T2 hatte es verlangt) — review-run.sh gibt es nicht weiter,
`--max-turns` 60/80 deckelt; `--effort high`/`xhigh` sind dokumentiert, gemessen ist nur `low` (T1).

### T5 — `task-close.sh --review auto`: billige Prüfer zuerst, Probe durch den Runner, Runden  [x]
Komponente: scripts · Dateien: scripts/dev/task-close.sh, scripts/tests/task_close_test.sh, scripts/dev/review-probe.sh, scripts/tests/review_probe_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ca3cbf08 2026-10-03T13:45:26+02:00
Review: approve with two rounds spent (opus): round 1 request_changes on a failed commit spending round 2 and a file staged during the suite passing the earlier scope check, both fixed; round 2 request_changes on the reused approve not bound to the staged diff, fixed with the reviewer's case as a test, no third round
Änderung: Schritt 3 (`:273–301`) teilt sich: `diff-scan`, `scope`, `docs-pairs`, `sec` laufen vor dem Verify (Schritt
2, `:182`), `contracts` danach (R-0150). Neuer Wert `--review auto` (Schritt 4, `:303–320`): Probe
(`review-probe.sh <komponente> --staged [-- <test aus Verify:>]`, R-0154.2) nur bei Test- und Nicht-Test-Dateien im
Diff, sonst der Block `no-test-change`; dann `review-run.sh` mit der Runde = Zahl vorhandener Verdicts der Task + 1
(höchstens 2; eine dritte ⇒ Exit 3 mit Hinweis `ledger.sh mark-question`); dann `check-verdict --tree --task`;
`review.sh log` (ab T6) schreibt die Runde. Exit 74 von `review-run.sh` ⇒ Exit 74, kein Commit. `--review none` und
`verdict:` bleiben unverändert. Der Exit-Kopf (`:46`) nennt die Verdict-Fälle bei 3/4 (R-0147c).
Rot vorher (task_close_test, `CLAUDE_BIN`-Stub): einseitige Doku ⇒ Exit 3 **ohne** dass `verify.sh` lief (Zähldatei
des Stub-verify); `--review auto` + Stub approve ⇒ Commit, Review-Zeile aus `check-verdict`; Stub request_changes ⇒ 3,
kein Commit, `r1.verdict.json` liegt; zweiter Aufruf ⇒ Runde 2; dritter ⇒ 3 mit Hinweis; Stub-Startfehler ⇒ 74, kein
Commit; reine Refactor-Task ⇒ Probe-Block `no-test-change`, approve ⇒ Commit.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T7)
Abhängt von: T4
Abweichung: ob der Diff Test- und Nicht-Test-Dateien hat, entscheidet `review-probe.sh` selbst (die Liste der
Testpfade steht nur dort und in `review.sh`): ohne Testdatei wie bisher `no-test-change`, nur Tests neu
`only-test-change`, beides ohne Suite-Lauf; task-close ruft die Probe deshalb bei `--review auto` immer. Die
Review-Zeile trägt die Runde (`approve (sonnet/high) · round 1`).

### T6 — `review.sh log` und `pr-body` aus dem Log  [x]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/dev/task-close.sh, scripts/tests/review_scripts_test.sh, scripts/tests/task_close_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @774c72a9 2026-10-03T14:15:54+02:00
Review: approve (opus, one round; nits done: an empty --failed reason is refused, pr-body names the refusal rather than a warning, an absolute ledger path is logged repo-relative, review-run's stderr is kept beside the round's files, a header line reflowed)
Änderung: `review.sh log --append <verdict>` hängt eine JSONL-Zeile an `.ah-out/review/review-log.jsonl` (Felder Spec
„Design“); `review.sh log [--ledger <l>]` druckt eine Tabelle und eine Summenzeile (`N runs, A approve, R
request_changes, F failed, $X, T turns, S s`). task-close ruft `--append` nach jeder Runde, auch bei Exit 74 (dann
`verdict: failed` mit Grund). `pr-body` (`review.sh:942`) liest Verdicts über dieselbe Prüffunktion wie `check-verdict`
(R-0151.6) und nennt je Task Modell, Runde und Mutanten.
Rot vorher: zwei `--append` ⇒ zwei Zeilen, Tabelle mit Summe; ein schemawidriges Verdict im Verzeichnis lässt `pr-body`
die Task als „Verdict ungültig“ zeigen statt sie still zu übernehmen; eine `failed`-Runde zählt in der Summe.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T7)
Abhängt von: T5

### T7 — Doku und Skill: `--review auto`, Ablage, Log, Pilot  [x]
Komponente: scripts · Dateien: .claude/skills/feature-build/SKILL.md, scripts/tests/skill_consistency_test.sh, DEVELOPMENT.md, AUTONOMOUS.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md, tasks/README.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped · contracts: 1 ok @75e053fe 2026-10-03T14:54:15+02:00
Review: approve with two rounds spent (opus): round 1 request_changes on the consistency test not proving the one retry, a wrong pair of probe answers in DEVELOPMENT.md and the auto branch switching off the rules for findings, all fixed with the reviewer's mutant as the counter-check; round 2 approve, nits done
Änderung: feature-build Schritt 4 (`:135`) bekommt den Zweig „Ledger-Kopf `Review: auto`“ (Opt-in für den Pilot): kein
Subagent, Schritt 5 (`:179`) wird `task-close.sh … --stage --review auto` im Hintergrund mit Wächter (die Dauer kann
über 10 Minuten liegen), Exit 74 ⇒ einmal neu, dann STOPP mit Meldung, kein Rückfall auf den Subagent-Review; ohne
`Review: auto` bleibt Schritt 4 wie nach 6a (`ledger.sh lint` prüft das `Review:`-Feld des Kopfs nicht, nichts zu
ändern). DEVELOPMENT.md „Task schliessen“ (`:437`): `--review auto`, Ablage unter `.ah-out/review/`, `review.sh log`,
die Deckel; AUTONOMOUS.md (`:59–74`): der Reviewer ist ein Prozess von task-close; cicd.html DE (`:241`) + EN (`:239`):
der Ablauf als Liste; CHANGELOG.
Rot vorher: skill_consistency_test — der Skill nennt `--review auto` und `review.sh log`, und jede im Skill genannte
`review.sh`-Verb existiert.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md · AUTONOMOUS.md · docs/developer/cicd.html + docs/en/developer/cicd.html · CHANGELOG
Abhängt von: T6
