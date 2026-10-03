<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stufe 6b — der Reviewer als eigener Prozess

Roadmap: R-0155 (Stufe 6, Teil 6b; Rest von R-0009), dazu R-0147, R-0150 und Teile von R-0151, R-0154 · Stand:
main@8a45c893 (6a gemergt mit #71) · Geplant 2026-10-03 von der Aufsicht, Entscheidungen Kevin 2026-10-03

## Problem / Motivation

Seit 6a gibt es die deterministischen Prüfer (`review.sh check-verdict|risk|docs-pairs|contracts|pr-body`,
`review-probe.sh`) und ein Verdict-Schema. Der Reviewer selbst ist aber noch ein Subagent der Bau-Session
(feature-build `SKILL.md:135–177`): die Session schreibt seinen Prompt, liest sein Urteil und reicht `task-close.sh`
nur eine Freitext-Zeile (`--review-note "approve (sonnet)"`). Ein Urteil, das die Bau-Session zusammenstellt und
weitergibt, prüft die Bau-Session gegen sich selbst (Roadmap-Dokument §10.1, U8). `task-close.sh` kann seit 6a ein
Verdict prüfen (`--review verdict:<datei>`, `:310–318`), aber niemand erzeugt eines.

6b schließt diese Lücke: `task-close.sh` startet den Reviewer selbst als `claude -p`-Prozess mit festem Prompt, nimmt
das schemagebundene Urteil entgegen, ergänzt die Felder, die es selbst gemessen hat, und prüft es mit
`check-verdict`. Die Bau-Session sieht weder Prompt noch Verdict.

## Ziel & Nicht-Ziele

Ziel:
- **CLI-Probe** `scripts/dev/review-cli-probe.sh`: misst, was die Claude-Code-CLI für diesen Aufruf wirklich tut
  (Anmeldung, `structured_output`, Modell, Werkzeug-Sperren, Budget-Deckel). Beweis-Instrument vor allem anderen.
- **Agent-Datei** `.claude/agents/review-task.md` und eigene Settings `scripts/dev/review-settings.json`: der Reviewer
  liest, darf `git diff|show|log` und höchstens zwei `review-probe.sh --mutate`; kein Edit/Write, kein Netz, kein
  `verify.sh`.
- **`scripts/dev/review-run.sh`**: baut den Prompt, startet den Prozess mit den Deckeln, wertet das JSON aus, schreibt
  das Verdict unter `.ah-out/review/<slug>/<id>.r<n>.verdict.json`.
- **`task-close.sh --review auto`** (Opt-in): billige Prüfer zuerst, dann Verify, Contracts, Probe durch den Runner,
  dann der Reviewer; Bindung des Verdicts an Ledger, Task, Tree-Hash und Probe.
- **`review.sh log`** und `pr-body` aus dem Log: jede Runde als JSONL-Zeile mit Kosten, Turns und Dauer.

Nicht-Ziele:
- `--review auto` als Default — erst nach dem Pilot (Kevin, Entscheidung B), eigener Schritt.
- Alles aus Stufe 7: Loop/Runner, zweite Build-Session für Runde 2, `restore`/`rejected.diff`, `[?]`-Automatik,
  Ebene 3 als Prozess, Stall-Stopp, Verhalten am Abo-Limit (Stub-Test dort).
- Refuter (Stufe 9), Ebene 2, `coverage` im Schema.
- Ein Rückfall auf den Subagent-Review, wenn der Prozess scheitert (Entscheidung D).

## Betroffene Komponenten & Dateien

- Neu: `scripts/dev/review-cli-probe.sh`, `scripts/dev/review-run.sh`, `scripts/dev/review-settings.json`,
  `scripts/dev/review-output.schema.json`, `.claude/agents/review-task.md`; Tests `scripts/tests/review_cli_probe_test.sh`,
  `scripts/tests/review_run_test.sh` (beide in `AH_SCRIPT_TESTS_DEFAULT`, `scripts/tests/run.sh:586`).
- Geändert: `scripts/dev/review-verdict.schema.json`, `scripts/dev/review.sh` (`check-verdict` `:650`, `pr-body` `:942`,
  neues Verb `log`), `scripts/dev/task-close.sh` (Schritt 3 `:273–301`, Schritt 4 `:303–320`, Kopf `:46`),
  `scripts/dev/harness-paths.txt`, `scripts/tests/review_scripts_test.sh`, `scripts/tests/task_close_test.sh`,
  `scripts/tests/hooks_test.sh`, `scripts/tests/skill_consistency_test.sh`.
- Skill: `.claude/skills/feature-build/SKILL.md` (Schritt 4 `:135`, Schritt 5 `:179`).
- Doku: `DEVELOPMENT.md` („Task schliessen" `:437`), `AUTONOMOUS.md` (`:59–74`), `docs/developer/cicd.html:241` +
  `docs/en/developer/cicd.html:239` („Review-Prüfer und Verdict"), `CHANGELOG.md`.

## Design

**Ablauf von `task-close.sh <ledger> <id> --stage --review auto -m …`:**
1. Staging und Tree-Hash wie heute.
2. Die billigen Prüfer zuerst: `diff-scan`, `scope`, `docs-pairs`, `sec` (heute nach dem Verify, `:273–301`; R-0150).
   Ein einseitiger Doku-Close kostet damit keinen Suite-Lauf mehr.
3. `verify.sh` (das `Verify:` der Task) und `contracts`.
4. **Probe durch den Runner:** ändert die Task Test- und Nicht-Test-Dateien, `review-probe.sh <komponente> --staged
   [-- <test>]` (der Test aus dem `Verify:`-Argument, falls die Zeile einen nennt; R-0154.2). Das Ergebnis ist der
   `probe`-Block; den füllt der Runner, nie der Reviewer (R-0147b). Ändert die Task keine Testdatei (Refactor, reine
   Doku), steht `applicable: false, reason: no-test-change` — kein Grund zur Ablehnung (R-0151.2).
5. **Reviewer:** `review-run.sh` mit Modell und Effort aus `review.sh risk --staged` (`standard` ⇒ sonnet/high,
   `xhigh` ⇒ opus/xhigh). Aufruf (Flags in T1 verifiziert; was T1 widerlegt, ändert T4):
   ```
   timeout 1200 claude -p --agents '<json aus .claude/agents/review-task.md>' --agent review-task \
     --model <m> --effort <e> \
     --setting-sources user --settings scripts/dev/review-settings.json \
     --tools "Read,Grep,Glob,Bash,StructuredOutput" \
     --disallowedTools "Edit,Write,NotebookEdit,WebFetch,WebSearch,mcp__*" \
     --permission-mode dontAsk --permission-prompts none \
     --json-schema "$(cat scripts/dev/review-output.schema.json)" --output-format json \
     --max-turns <60|80> --max-budget-usd <5|15> --no-session-persistence "<fester Prompt>"
   ```
   **Entscheidung nach T1 (Messung 2026-10-03, CLI 2.1.285):** Der Reviewer wird mit `--agents '<json>' --agent
   review-task` definiert, nicht als Datei unter `.claude/agents/` — die findet `claude -p` mit `--setting-sources user`
   nicht, und die Quelle `project` muss draußen bleiben; das JSON baut review-run.sh aus der Agent-Datei, und `--tools`
   wie die `tools` des Agenten nennen `StructuredOutput` mit, sonst fehlt `structured_output` (Ledger T1, `Messung:`).
   Fester Prompt: Task-Text, Spec-Pfad, `git diff --staged`, Liste der neuen Dateien, Tree-Hash, Probe- und
   Contracts-Ergebnis, Summary-Zeile des Verify; in Runde 2 der Pfad des Verdicts der Runde 1.
6. **Verdict:** `review-run.sh` nimmt `structured_output` (Teilschema `review-output.schema.json`: `verdict`,
   `findings`, optional `mutants`) und ergänzt `schema_version`, `task{ledger,id}`, `tree_hash`, `reviewer{model,
   effort}`, `probe`, `verify` (aus `last-verify.json`), `contracts`, `cost_usd`, `num_turns`, `duration_s`. Ablage
   `.ah-out/review/<slug>/<id>.r<n>.verdict.json` plus die rohe CLI-Antwort `<id>.r<n>.raw.json` (gitignored,
   `.ah-out/`). `check-verdict` prüft zusätzlich, dass `task.ledger`/`task.id` die zu schließende Task sind (R-0147a).
7. **Ergebnis:** approve ⇒ Commit mit der Review-Zeile aus `check-verdict`; request_changes ⇒ Exit 3, die Session
   behebt und ruft erneut (Runde 2 = zweite Verdict-Datei); eine dritte Runde gibt es nicht: Runde 2 nicht approve ⇒
   Exit 3 mit Hinweis `ledger.sh mark-question`. `review.sh log` schreibt jede Runde.

**Scheitern des Prozesses (Entscheidung D):** Startfehler, Timeout, `error_max_turns`, `error_max_budget_usd`,
`error_max_structured_output_retries`, `error_during_execution` oder ein unlesbares JSON ⇒ Exit 74, kein Commit, keine
Verdict-Datei mit approve. Die Session versucht es einmal neu; scheitert auch das, STOPP mit Meldung. Kein Rückfall auf
den Subagent-Review: SKIP ist nicht grün.

**Was der Reviewer darf (Entscheidung C):** lesen (`Read`, `Grep`, `Glob`), `git diff|show|log|status`, höchstens zwei
`bash scripts/dev/review-probe.sh <k> --staged --mutate …` (in deren eigener Worktree, 6a T5); kein `Edit`/`Write`,
kein Netz, kein `verify.sh` (lief schon in Schritt 3, und eine zweite Server-Suite auf derselben DB zerstört die
erste — `pg_engine`). Die Allow-Regeln stehen in `review-settings.json`, der harness-guard läuft dort als
PreToolUse-Hook. Die Projekt-Settings (`.claude/settings.json`) dürfen nicht hineinwirken: sie erlauben `vm.py`,
`heavy.sh`, `task-close.sh` und `git switch` — T1 misst, wie das mit `--setting-sources` sicher geht.

**Deckel (Entscheidung E, großzügiges Netz):** hart sind `timeout 1200` (20 min) und `--max-turns` 60 (Sonnet) bzw.
80 (Opus); locker `--max-budget-usd` 5 $ bzw. 15 $ als zusätzliches Netz, falls der Deckel mit Abo-Anmeldung greift
(T1 misst es). Der Pilot misst Kosten, Turns und Dauer über `review.sh log`; die Deckel werden danach aus den
Messwerten nachgestellt.

**`review.sh log`:** eine JSONL-Zeile je Runde in `.ah-out/review/review-log.jsonl` (Datum, Ledger, Task, Runde,
Modell, Effort, Verdict, blocker/wichtig/nit, Probe, Mutanten gesetzt/gekillt, `cost_usd`, `num_turns`,
`duration_s`, Tree). `review.sh log [--ledger <l>]` druckt sie als Tabelle; `pr-body` liest die Verdicts über
dieselbe Prüflogik wie `check-verdict` (R-0151.6). Grundlage der Metrik in Stufe 10.

## Datenmodell / API / Migrationen

Keine App-Änderung. Schema: `review-verdict.schema.json` bekommt `schema_version: 2`, `round`, `num_turns`,
`duration_s` und optional `mutants[]` (`{file, line, replacement, result}`, wie in `review-output.schema.json`);
Version 1 bleibt lesbar (6a-Verdicts gibt es keine).
Neues Teilschema `review-output.schema.json` für `--json-schema` (nur, was das Modell liefert).

## Externe Integrationen

Claude Code CLI (Runner-Pin `scripts/dev/runner-claude.version` = 2.1.280). Belegt aus der offiziellen Doku
(code.claude.com/docs, cli-reference, headless, sub-agents, authentication, permissions; gelesen 2026-10-03):
- `--agent <name>` macht den Agenten zur Haupt-Session; sein Prompt ersetzt den System-Prompt, CLAUDE.md lädt
  trotzdem; `tools`, `disallowedTools`, `model`, `permissionMode`, `effort` gelten.
- `--json-schema` (nur Print-Modus) mit `--output-format json` liefert `structured_output`; Fehlerarten
  `error_max_turns`, `error_max_budget_usd`, `error_max_structured_output_retries`, `error_during_execution`.
- `dontAsk` verweigert alles, was fragen würde; eingebaute Nur-lese-Befehle und Allow-Regeln laufen.
  `--permission-prompts none` ab 2.1.259.
- `--max-turns` und `--max-budget-usd` nur im Print-Modus; der Betrag ist eine Client-Schätzung.
- `--model` übersteuert die Einstellung `model` und `ANTHROPIC_MODEL`; `--effort`, `--tools`, `--setting-sources`,
  `--settings`, `--no-session-persistence` existieren.
- **`--bare` liest weder OAuth noch `CLAUDE_CODE_OAUTH_TOKEN`** — mit D18 (Abo) unbrauchbar, also nie `--bare`.
- Anmeldung: `CLAUDE_CODE_OAUTH_TOKEN` (Präzedenz 5, `claude setup-token`, ein Jahr, nur Modell-Anfragen) für den
  Runner; in Kevins Sessions `~/.claude/.credentials.json` (Präzedenz 7).
- Bash-Regeln gelten je Teilkommando; Ziele von Umleitungen (`> f`) werden gegen Edit-Regeln geprüft.

**Nicht verifiziert — T1 misst und schreibt das Ergebnis ins Ledger:** ob `--model` das Frontmatter-`model`
übersteuert; ob Frontmatter-Hooks eines Projekt-Agenten im Print-Modus ohne Workspace-Trust feuern; welche
`--setting-sources` die Projekt-Allow-Regeln draußen halten; ob `--max-budget-usd` mit Abo-Anmeldung greift; ob ein
`claude -p` aus einer laufenden Claude-Session (geerbte Umgebung) startet; der genaue Feldname der Fehlerart in der
CLI-JSON (`subtype` oder `error_type`).

## Trade-offs & Alternativen

- **task-close startet den Reviewer** (Entscheidung A) statt eines Skripts, das die Session vor task-close ruft:
  sonst ginge das Verdict wieder durch die Bau-Session und wäre interaktiv fälschbar.
- **Probe durch den Runner** statt durch den Reviewer: deterministisch, nicht fälschbar, und der Reviewer braucht
  keinen Suite-Zugriff.
- **Eine Agent-Datei**, Modell und Effort per Flag: zwei Dateien (sonnet/opus) unterschieden sich nur im Frontmatter.
  Hält T1 das Übersteuern per `--model` nicht, werden es zwei.
- **Kein `--agents`-JSON aus einer Datei**: erst ab 2.1.281, über dem Runner-Pin.

## Risiken & Rollback

- **Nutzungsfenster:** jede Task ein kalter Prozess, auf Risikopfaden Opus-xhigh, geteilt mit Kevins Arbeit. Deshalb
  Opt-in und Pilot; der Pilot misst.
- **Prompt-Injection über den Diff:** der Reviewer hat keine Schreib-Werkzeuge und kein Netz, läuft mit `dontAsk`,
  liefert schemagebundene Ausgabe; Probe, Verify und Contracts rechnet der Runner; `check-verdict` erzwingt die
  Regeln. Schlimmster Fall ist ein falsches approve wie heute oder ein falsches request_changes, das die 2-Runden-
  Grenze auffängt.
- **Ein Reviewer, der Dateien ändert:** Edit/Write fehlen, Umleitungsziele prüft Claude Code gegen Edit-Regeln,
  `--mutate` schreibt nur in seiner Worktree. Belegt erst durch die Gegenprobe in T1.
- **Dauer:** Verify + Probe + Reviewer kann über 10 Minuten gehen — länger als ein Bash-Aufruf einer interaktiven
  Session. Der Skill fährt `task-close --review auto` deshalb im Hintergrund mit Wächter (T7).
- **Rollback:** `--review auto` ist Opt-in; ohne das Flag läuft task-close wie nach 6a. Revert je Task.

## Pilot (Handarbeit nach dem Merge, nicht Teil des Ledgers)

Ein echtes, freigegebenes Ledger (Vorschlag: das nächste kleine REF- oder BUG-Ledger) wird mit `--review auto` gebaut,
interaktiv in Kevins Session. Danach liest Kevin `review.sh log`: Kosten, Turns, Dauer je Runde, Anteil
request_changes, Anteil gescheiterter Prozesse. Daraus folgen die nachgestellten Deckel und die Entscheidung, ob
`--review auto` Default wird (eigener kleiner Plan).

## Zuordnung der Kandidaten aus 6a

| Zeile | Punkt | Wohin |
|---|---|---|
| R-0147 | a (Task-Abgleich), b (Probe optional) | 6b T3, T5 |
| R-0147 | c (Exit-Kopf von task-close) | 6b T5 |
| R-0150 | billige Prüfer vor dem Verify | 6b T5 |
| R-0151 | 1 (Probe sieht nur den Index) | erledigt durch das Design: `--review auto` läuft nach `--stage` |
| R-0151 | 2 (Refactor ohne Probe), 6 (pr-body ohne check-verdict-Logik) | 6b T3, T6 |
| R-0151 | 3 (Contract-Laufzeit) | Stufe 7 |
| R-0151 | 4 (`release.yml`-Pin), 5 (Scrub-Listen) | eigene REF-Zeilen, nicht 6b |
| R-0154 | 2 (Probe-Präzision, `-- <test>`) | 6b T5 |
| R-0154 | 3 (geteilte Test-DB) | in 6b entschärft (Probe nach dem Verify, nacheinander); eigene Probe-DB Stufe 7 |
| R-0154 | 1 (Rust-Tests inline in `src/`) | Stufe 7/10 |

## Doku-Impact

DEVELOPMENT.md (Task schliessen: `--review auto`, Ablage, `review.sh log`), AUTONOMOUS.md (Reviewer als Prozess),
cicd.html DE+EN („Review-Prüfer und Verdict"), CHANGELOG, feature-build-Skill.

## Offene Fragen

Keine Produktfragen; entschieden am 2026-10-03 (A–E). Was T1 misst, kann T2/T4 im Rahmen dieser Spec anpassen (etwa
zwei Agent-Dateien statt einer); ändert eine Messung das Verhalten aus Sicht der Session (etwa: der Budget-Deckel
greift mit Abo nicht), wird es Kevin am Ende von T1 gemeldet.
