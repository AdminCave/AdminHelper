<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket loop-harness: doc-smoke in der Bau-Session, kein Hintergrund, redteam-Klone (R-0304, R-0301, R-0303) — Task-Ledger
Status: bereit · Branch: harness/loop-harness · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-12 (kleines Fund-Paket aus R-0304, R-0301, R-0303, Triage Kevin 2026-10-11/12; R-0304 als gezielte Allow-Regel nur fuer das lesende doc-smoke.py; R-0301 an der Doku belegt; R-0303 mit differentiellem Orakel, eine geaenderte Probe ist [?]; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0304, R-0301, R-0303 (Kurz-Ledger ohne Spec)
Heavy: none — Runner-Settings, ledger-loop.sh, ein Skill-Text und Shell-Tests unter scripts/ mit hermetischen Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-12 von Worker A für die Aufsicht (adminhelper-ac). Kevin hat die drei Zeilen angenommen. R-0304 hat
Vorrang: vor dem nächsten Messlauf. Zeilenangaben origin/main@c719ace6; beim Bau an Symbolen orientieren.

Vorab geprüft:
- **R-0304, Beweis:**
  - `~/.cache/ah-builder/loop/loop-kleinpaket-2/T1.s1.json`, `permission_denials`: `Bash` mit
    `python3 scripts/dev/doc-smoke.py --strict`.
  - `T2.s1.json`, `permission_denials`: `python3 scripts/dev/doc-smoke.py --paths --env --strict`.
  - `runner-settings.json` hat keine Allow-Regel für `python3 scripts/dev/doc-smoke.py`, der Modus ist `dontAsk`.
- **R-0304, Empfehlung: die Allow-Regel, nicht der Verweis auf `doc_smoke_test`.**
  - `doc_smoke_test.sh` testet das Werkzeug an Fixture-Checkouts („hermetic test for scripts/dev/doc-smoke.py“), nicht
    die echte Doku. Ein Verweis darauf prüft die Doku-Änderung der Task also nicht.
  - Die Prüfung der echten Doku läuft heute nur im CI (`ci.yml:844`, „Documentation smoke test“,
    `python3 scripts/dev/doc-smoke.py --paths --env --strict`), nicht in `run.sh` und nicht in `task-close.sh`.
  - `doc-smoke.py` ist lesend: Es ruft `git ls-files` und `git grep` auf, liest Dateien und gibt Funde aus. `--root`
    liest einen anderen Checkout, schreibt aber nichts. Korrektur aus dem Review am Ende (T4): Mit `--root` führen
    `git ls-files` und `git grep` die Git-Konfiguration des fremden Repos aus. Deshalb gilt die Regel nur für den CI-Befehl ohne
    `--root`.
  - Die Regel erlaubt seit T4 genau den CI-Befehl: `Bash(python3 scripts/dev/doc-smoke.py --paths --env --strict)`.
  - Alternative wäre doc-smoke in `run.sh` oder `task-close.sh`. Das ist größer und ändert jeden Lauf, also nicht in
    diesem Paket.
- **R-0301, gegen die Claude-Code-Doku geprüft (WebFetch, 2026-10-12):**
  - „Environment variables“: „`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` | Set to `1` to disable all background task
    functionality, including the `run_in_background` parameter on Bash and subagent tools, auto-backgrounding, and the
    Ctrl+B shortcut“.
  - „Tools reference“, Bash: „Setting `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` … disables auto-backgrounding along with
    the rest of the background task functionality, so a command that reaches its timeout stops instead.“
  - Die Variable gibt es also wie behauptet; R-0301 wird eine Task (T2).
  - Version: In den lokalen Binaries 2.1.283, 2.1.284 und 2.1.289 steht der Name (`grep -a`, je 4 Treffer). Die
    gepinnte Version des Loops ist 2.1.280 (`runner-claude.version`); für sie ist es **nicht verifiziert**, denn ihr
    Binary liegt nur im Builder-Home. Kennt 2.1.280 die Variable nicht, bleibt sie wirkungslos und schadet nicht.
- **R-0303:** `redteam_test.sh` klont lokal ohne `--no-local`, an :451 (`$FC2`), :468 (`$FC3`) und :487 (`$FC6`):
  `gitq clone -q --template= "$FC" …`.
  - `gitq` setzt `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1` vor `git` (:416).
  - Weitere Klone über Wrapper-Funktionen gibt es unter scripts/ nicht (gegrept).
  - Vorsicht: `$FC` trägt die Köder der Red-Team-Proben (`core.fsmonitor`, `filter.evil.clean`, `credential.helper`,
    `remote.origin.receivepack`, einen pre-push-Hook). Mit `--no-local` läuft beim Klonen `git-upload-pack` in `$FC`.
    Der Bau zeigt, dass sich dadurch keine Probe und keine Marke ändert (T3).

### T1 — Die Bau-Session darf doc-smoke fahren (R-0304)  [x]
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @9fa91bdc 2026-10-12T10:13:47+02:00
Review: Review am Ende (Kurz-Ledger)
Antwort: Kevin 2026-10-12, (a): die Regel aus R-0237 erlaubt neben scripts/vm genau scripts/dev/doc-smoke.py (Rückfrage in der Session der Aufsicht; Plan-Korrektur durch die Aufsicht).
Komponente: scripts · Dateien: scripts/dev/runner-settings.json, .claude/skills/build-task/SKILL.md, scripts/tests/skill_consistency_test.sh, scripts/tests/hooks_test.sh
Änderung:
- `runner-settings.json` bekommt in `allow` die Regel `Bash(python3 scripts/dev/doc-smoke.py:*)`, neben
  `Bash(ruff:*)` (:82).
- `/build-task`, Schritt 4 (:31–44), sagt für eine Task, die Doku ändert: `python3 scripts/dev/doc-smoke.py --paths
  --env --strict`, derselbe Befehl wie im CI. Auch das ist ein Befehl je Aufruf, im Vordergrund.
- `skill_consistency_test.sh`:
  - `build_task_findings` (:167) prüft auch Befehle, die mit `python3 scripts/` beginnen, gegen die Allow-Regeln, wie
    seit R-0263 `ruff`;
  - eine Fixture mit einem `python3 scripts/…`-Aufruf ohne Regel fällt;
  - die bestehende Prüfung „build-task gives no forbidden command and only calls the runner may run“ deckt dann den
    neuen Befehl ab.
- Andere Tests, die die Settings lesen (`builder_home_test` :131 vergleicht mit der Quelle, `hooks_test`), bleiben
  grün. Kein Test hält die Allow-Liste wörtlich fest; geprüft wurde `hooks_test` :1224, das gilt den Settings des
  Reviewers.
Rot vorher:
- Die erweiterte Prüfung fällt auf main, sobald der Skill den Befehl nennt und die Regel fehlt.
- Die Fixture-Gegenprobe zeigt, dass sie fallen kann.
Beweis: siehe „Vorab geprüft“ (R-0304): `permission_denials` in Messlauf-4, T1 und T2.
Dedup-Key: ref:scripts:runner-settings.json:doc-smoke-allow
HEAD: c719ace6
Semantik: `AUTONOMOUS.md:242–245` „**Je Task** eine frische Bau-Session … Die Session baut eine Task, testet mit `verify.sh`
und hinterlässt eine Commit-Nachricht“. Eine Doku-Task muss ihre Doku in der Session prüfen können, wie es der
Doku-Schritt im CI tut.
Assertion-Änderung: scripts/tests/hooks_test.sh::the WebFetch allow rules are exactly the six doc domains, echo allowed, python3 only with a script, no paste — die Regel aus R-0237 erlaubt neben scripts/vm genau scripts/dev/doc-smoke.py (Kevin 2026-10-12, R-0304)
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (der Skill-Text ist die Anleitung)

### T2 — Der Loop schaltet Hintergrund-Befehle der Bau-Session ab (R-0301)  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @36259ea9 2026-10-12T09:56:18+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- Der Aufruf von `claude -p` (`ledger-loop.sh:795`, neben `BASH_DEFAULT_TIMEOUT_MS`/`BASH_MAX_TIMEOUT_MS` aus R-0263)
  bekommt `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1` in die Umgebung.
- Dann gibt es in der Session weder `run_in_background` noch den Umzug in den Hintergrund. Ein Befehl, der seinen
  Timeout erreicht, stoppt. Sein Timeout ist seit R-0263 die Dauer der Session, die äußere Grenze bleibt
  `timeout ${TASK_MINUTES}m`.
- Der Kommentar dort nennt die Doku-Stelle (siehe „Vorab geprüft“).
- `ledger_loop_test.sh`: Die Fake-CLI hält auch `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` fest, an derselben Stelle wie
  die Timeouts (:235, `FIXTURE_TIMEOUTLOG`); der Fall bei :643–645 erwartet `1`.
- Nicht in `runner-settings.json`, denn die Datei trägt keinen `env`-Block (hooks_test).
- Den Reviewer-Prozess (`review-run.sh`) betrifft das nicht: Er hat eigene, lesende Settings.
Rot vorher: Die Session bekommt die Variable nicht; der erweiterte Fall fällt mit `<unset>`.
Beweis:
- Bau R-0263, Review am Ende, harness/loop-verify-foreground@a7904247: Der Reviewer nannte die Variable. Belegt ist sie
  jetzt an der Doku (siehe oben).
- Ohne sie kann die Session einen Befehl in den Hintergrund schicken; das verbietet bisher nur der Skill-Text
  (`/build-task` Schritt 4).
Dedup-Key: ref:scripts:ledger-loop.sh:disable-background-tasks
HEAD: c719ace6
Semantik: wie T1. Der Test der Session muss in der Session zu Ende kommen, und Warten auf einen Hintergrund-Lauf
verweigern die Settings.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; der Kommentar im Loop nennt die Variable)

### T3 — redteam_test klont seine Fixtures mit --no-local (R-0303)  [x]
Komponente: scripts · Dateien: scripts/tests/redteam_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @3e484464 2026-10-12T10:25:45+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- Die drei Klone (:451, :468, :487) laufen mit `gitq clone -q --no-local --template= "$FC" …`.
- Eine Prüfung wie „repo wiring“ in ledger_loop_test (R-0262): In `redteam_test.sh` steht kein `git clone` und kein
  `gitq clone` ohne `--no-local`.
- Gleichwertigkeit, im Bau zu zeigen:
  - Alle `ok`-Zeilen von `redteam_test` sind vor und nach der Änderung dieselben (Liste der Meldungen vergleichen).
  - Im Verzeichnis der Marken (`$M`) entsteht durch das Klonen keine neue Marke. Geprüft wird das in einem Lauf mit
    einem Abzug von `$M` direkt nach den Klonen, im Wegwerf-Worktree.
  - Ändert sich eine Probe, ist das ein `[?]` mit Befund, kein Fix.
Rot vorher: Die neue Prüfung fällt auf main (drei Klone ohne `--no-local`). Der Lauf selbst ist nicht deterministisch
rot, wie bei R-0262 und R-0287.
Beweis: origin/main@c719ace6: `grep -nE 'gitq clone' scripts/tests/redteam_test.sh` trifft :451, :468 und :487, keine
mit `--no-local`. Die Prüfungen aus R-0287 lesen nur builder_home_test, review_scripts_test und builder-home.sh.
Orakel: differential — die Liste der `ok`-Meldungen von redteam_test vor und nach der Änderung.
Dedup-Key: ref:scripts:redteam_test.sh:gitq-local-clone
HEAD: c719ace6
Semantik: `docs/developer/cicd.html:99–101` „reruns bleibt bewusst 0: der Wochenlauf wiederholt einen roten Schritt
selbst und klassifiziert ihn, statt die Suiten heimlich retryen zu lassen“. Ein Fixture, das an fremder Wartung
scheitert, ist ein Flake der Suite selbst.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T4 — Nachbesserung aus dem Review am Ende: doc-smoke genau mit dem CI-Befehl, Funde zu neuen Dateien (R-0304, R-0301)  [x]
Komponente: scripts · Dateien: scripts/dev/runner-settings.json, .claude/skills/build-task/SKILL.md, scripts/tests/hooks_test.sh, scripts/tests/ledger_loop_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @90530363 2026-10-12T11:01:06+02:00
Review: Nachbesserung, Opus-Review über den Diff der Nachbesserungen folgt
Änderung: Angelegt 2026-10-12 aus dem Review am Ende (Opus, `request_changes`: zwei belegte Funde zu T1, vier nits).
- **„lesend“ stimmt mit `--root` nicht.** `Bash(python3 scripts/dev/doc-smoke.py:*)` lässt `--root <verzeichnis>` zu.
  Dort führt `git ls-files` die Git-Konfiguration des fremden Repos aus, etwa `core.fsmonitor`. Der Reviewer hat das
  mit einer Marke belegt; dieselbe UID, also kein `safe.directory`. Die Aussage unter „Vorab geprüft“ war falsch.
  - Neu: Die Regel erlaubt genau den Befehl des CI, `Bash(python3 scripts/dev/doc-smoke.py --paths --env --strict)`.
    Ohne `--root` ist die Wurzel der eigene Checkout, dessen Git-Konfiguration die Session nicht ändern kann.
  - Das bleibt in Kevins (a), „genau doc-smoke.py“, und ist enger.
  - hooks_test: Die Prüfung aus R-0237 lässt genau diesen String durch, der Kommentar sagt warum.
  - Die Gegenprobe prüft die Ausgabe (`wrong: …`) statt nur den Exit. Sie verlangt, dass auch die breite Form
    `Bash(python3 scripts/dev/doc-smoke.py:*)` und ein anderes Skript aus scripts/dev fallen.
- **doc-smoke ist in der Session rot, obwohl die Doku stimmt.** Es kennt nur, was git trackt (`git ls-files`,
  `git grep`), und die Session kann nicht stagen. Eine neue Datei, die die Task in der Doku nennt, ist bis zum Commit ein
  Fund.
  - Neu: `/build-task` Schritt 4 sagt, dass solche Funde bis zum Commit erwartet sind. Die Session lässt sie stehen und
    nennt sie in der Commit-Nachricht.
- nit aus demselben Review: ledger_loop_test setzt `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` vor seinen Läufen zurück.
  Sonst sähe die Prüfung aus T2 in einer Bau-Session, die die Variable trägt, einen geerbten Wert.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (der Skill-Text ist die Anleitung)
Abhängt von: T3

### T5 — Nachbesserung aus Runde 2: erwartet ist nur ein Fund auf eine neue Datei (R-0304)  [x]
Komponente: scripts · Dateien: .claude/skills/build-task/SKILL.md, scripts/tests/skill_consistency_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @0219e661 2026-10-12T11:20:48+02:00
Review: Nachbesserung aus Runde 2, mit dem Fall des Reviewers als Test (keine dritte Runde)
Änderung: Angelegt 2026-10-12 aus dem Re-Review von T4 (Opus, Runde 2, `request_changes`: ein belegter Fund, drei nits).
Nach der Regel der zweiten Runde behoben, mit dem Fall des Reviewers als Test; eine dritte Runde gibt es nicht.
- Der Satz aus T4 in `/build-task` erklärte jeden Fund auf „eine Datei oder einen Namen, den erst deine Task anlegt“ für
  erwartet.
  - doc-smoke liest aber Namen per `git grep` aus den getrackten Dateien im Arbeitsbaum.
  - Ein Name, den die Task in eine schon getrackte Datei schreibt (`config.py`), ist also kein Fund. Ein gemeldeter Name
    ist dann fast immer ein echter Fehler, etwa `AH_FOO_TIMEOUTS` in der Doku gegen `AH_FOO_TIMEOUT` in `config.py`.
  - Neu: Erwartet ist bis zum Commit nur ein Fund auf eine Datei, die die Task neu anlegt, oder auf einen Namen, der nur
    in einer solchen neuen Datei steht. Jeden anderen Fund behebt die Session.
  - Einen Pfad, den die Task löscht oder umbenennt, sucht sie selbst in der Doku, denn bis zum Commit steht er noch im
    Index.
- `skill_consistency_test` prüft den Satz. Eine Fixture mit dem Satz aus T4 fällt.
- Im Ledger widersprach „Vorab geprüft“ (R-0304) der eigenen Korrektur, denn dort stand noch die Regel mit `:*`. Das ist
  im Commit, der diese Task anlegt, berichtigt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (der Skill-Text ist die Anleitung)
Abhängt von: T4
