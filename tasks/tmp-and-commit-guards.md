<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Schutz: /tmp-Globs und pre-commit (R-0098, R-0102) — Task-Ledger
Status: erledigt · Branch: harness/tmp-and-commit-guards · Commit-Granularität: pro Task · Review: pro Task (feature-review; Harness-Pfade ⇒ Reviewer Opus) · Modell: Opus
Freigabe: Kevin, 2026-09-27 („alle freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: docs/features/tmp-and-commit-guards.md (Roadmap R-0098, R-0102)
Heavy: none — nur scripts/dev, scripts/tests, Skills und Doku; kein Stack-, Gateway-, PKI- oder Install-Pfad, alles hermetisch über verify.sh scripts.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Bau nur interaktiv (fast jede Datei ist ein Harness-Pfad; der Wächter verweigert autonom, der Runner per Deny).
Keine Lane: `lane.sh new` legt fest `feature/<slug>` an. Parallel zu Stufe 5c möglich, weil `run.sh` unberührt
bleibt; einzige gemeinsame Datei ist `DEVELOPMENT.md` (andere Abschnitte). Reviewer-Subagenten bekommen ein
eigenes Verzeichnis aus `mktemp -d -p <Scratchpad>` und löschen nur eigene Pfade mit vollem Pfad, nie per Glob.

### T1 — Wächter: Glob-Löschen unter Temp-Wurzeln in jedem Modus verweigern, Schlüsselwort-Lücke schließen  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/harness-guard.sh, scripts/tests/hooks_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @90093678 2026-09-28T08:55:54+02:00
Review: approve (opus, 2nd round)
Änderung: Neuer Fund-Typ „Löschen per Glob unter einer Temp-Wurzel", der **unabhängig** von `AH_AUTONOMOUS` und
vom Marker `.vm/harness.off` verweigert (JSON-`deny` wie bisher, Grundtext: eigene Verzeichnisse mit vollem Pfad
löschen). Muster laut Spec „Trade-offs": `rm`/`rmdir`/`unlink`/`shred` mit Glob-Operand unter `/tmp`,
`/var/tmp`, `/dev/shm`, `$TMPDIR`; `find <Wurzel> … -delete|-exec(dir) rm`; `for v in <Glob unter Wurzel>` plus
rm-Segment; auch nach `cd /tmp`. Dazu überspringt der Tokenizer `do`, `then`, `else`, `elif`, `if`, `while`,
`until` und `!` als Präfixe (die Lücke gilt auch für Harness-Pfade). Den veralteten Kommentar :17–19 zur
Wirkung eines Exit ≠ 0 korrigieren. Test: die wörtliche Vorfallsform `rm -rf /tmp/tmp.* 2>/dev/null; ls -d /tmp/tmp.* 2>/dev/null | head -3`
wird interaktiv, mit `AH_AUTONOMOUS=1` und mit Kill-Switch verweigert; ebenso `cd /tmp && rm -rf tmp.*`,
`find /tmp -name 'x*' -delete`, eine for-Schleife, `bash -c '…'` und ein Harness-Edit im `do`-Rumpf. Frei bleiben
`rm -rf /tmp/scratch` (bestehender Fall), `rm -rf "$W"`, `rm -rf $SP/tmp.*`, derselbe Text in einer
Commit-Message oder einem Here-Doc, repo-relative Globs.
Beweis: origin/main@70e91718 · `printf '%s' '{"tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/tmp.* 2>/dev/null; ls -d /tmp/tmp.* 2>/dev/null | head -3"},"cwd":"<repo>"}' | AH_AUTONOMOUS=1 bash scripts/dev/hooks/harness-guard.sh` → keine Ausgabe (erlaubt); erwartet: `permissionDecision":"deny"`
Dedup-Key: bug:harness:pretooluse:rm-glob-tmp
HEAD: 70e91718
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T8)

### T2 — Reviewer räumen nur eigene Pfade weg  [x]
Komponente: scripts · Dateien: .claude/skills/feature-review/SKILL.md, .claude/skills/feature-build/SKILL.md, scripts/tests/skill_consistency_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @94acac96 2026-09-28T09:06:11+02:00
Review: approve (opus)
Änderung: `feature-review/SKILL.md` bekommt einen kurzen Abschnitt „Proben und Aufräumen": Temp-Verzeichnisse
nur mit `mktemp -d -p <dein Verzeichnis>`, nur eigene Pfade mit vollem Pfad löschen, nie per Glob.
`feature-build/SKILL.md` Iterations-Schritt 4 (Frischer-Kontext-Review, :133 ff.) bekommt einen Punkt: Der Bau
legt je Reviewer `mktemp -d -p <Scratchpad der Session>` an und nennt das Verzeichnis im Prompt. Kein fester
Pfad `/tmp/claude-<uid>` (der Runner hat eine andere uid). Test in `skill_consistency_test.sh`: die Regel steht
in beiden Texten; die Prüfung wird zuerst an einer Fixture ohne den Satz rot.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (die Skills sind selbst Prozess-Doku)

### T3 — pre-commit-Hook fährt `review.sh sec --staged`  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/pre-commit, scripts/tests/review_scripts_test.sh, scripts/tests/task_close_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @0d547e7e 2026-09-28T09:18:18+02:00
Review: approve (opus)
Änderung: Neue Datei `scripts/dev/hooks/pre-commit` (SPDX-Kommentar `GPL-3.0-or-later`, Modus 100755, shellcheck
sauber): löst seinen Checkout aus `$0` auf und ruft `exec bash <root>/scripts/dev/review.sh sec --staged`. Test in
einer Fixture mit `git config core.hooksPath scripts/dev/hooks`: ein blockierter Pfad (`tasks/sec-x.md`) und
eine zur Laufzeit zusammengesetzte sec-Dedup-Zeile (wie review_scripts_test.sh:622) werden über den Index **und**
über `commit -a` abgewiesen; eine saubere Änderung wird committet; ein Worktree fährt den Hook seines eigenen
Branches; im echten Repo gilt Modus 100755 (`git ls-files -s`); shellcheck auf die Datei im Test (die
shellcheck-Zeile in run.sh erfasst nur `*.sh`). In `task_close_test.sh`: ein Close mit scharfem Hook committet
weiter (der dritte sec-Lauf kostet Millisekunden; die Aufrufe in task-close.sh:241 und :301 bleiben für Klone
ohne Hook).
Beweis: origin/main@70e91718 · `git config --get core.hooksPath` → leer (Exit 1); in einer Fixture ohne Hook committet `git commit` die Datei `tasks/sec-x.md` ohne Einwand
Dedup-Key: bug:scripts:review.sh:sec-only-in-task-close
HEAD: 70e91718
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T8)

### T4 — Runner-Klon: `core.hooksPath` fest  [x]
Komponente: scripts · Dateien: scripts/dev/runner-setup.sh, scripts/tests/runner_setup_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @5f9088df 2026-09-28T09:27:54+02:00
Review: approve (opus)
Änderung: In Schritt 2 nach runner-setup.sh:249 (`… config remote.origin.pushurl /dev/null`) eine Zeile
`run su - "$RUNNER" -c "git -C $SRV/repo config core.hooksPath scripts/dev/hooks"`, als Runner, nie als root
(der Kommentar :243–247 nennt root plus hooksPath selbst als Risiko). Test: die Zeile steht im `--dry-run`-Plan,
wie die pushurl-Prüfung runner_setup_test.sh:96–97.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T8)
Abhängt von: T3

### T5 — `harness.sh status` zeigt, ob der pre-commit-Hook scharf ist  [x]
Komponente: scripts · Dateien: scripts/dev/harness.sh, scripts/tests/hooks_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @8dc36492 2026-09-28T09:38:41+02:00
Review: approve (opus)
Änderung: `status` (harness.sh:61) druckt eine zweite Zeile: `pre-commit: armed (core.hooksPath=scripts/dev/hooks)`
oder `pre-commit: NOT set — git config core.hooksPath scripts/dev/hooks`. Test in einer `git init`-Fixture, beide
Zustände.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T8)
Abhängt von: T3

### T6 — Wächter verweigert die Umgehung des pre-commit-Hooks  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/harness-guard.sh, scripts/tests/hooks_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @2cee6ae8 2026-09-28T09:58:56+02:00
Review: approve (opus, 2nd round)
Änderung: Verweigert in jedem Modus `git commit --no-verify` und `-n` (auch in kombinierten Kurzflags wie `-qn`),
`git -c core.hooksPath=…` und `git config [--global|--local|…] core.hooksPath …` (setzen und `--unset`). Kevins
eigene Shell bleibt frei (der Hook sieht nur Modell-Aufrufe). Testzeilen, die `--no-verify` im Klartext tragen,
brauchen `# review: ok <grund>` oder werden zur Laufzeit zusammengesetzt, weil `review.sh diff-scan` (:52) sie
sonst meldet. Test: alle Formen verweigert; `git commit -m "--no-verify erwähnt"` (in der Message) und
`git config --get core.hooksPath` bleiben frei.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T8)
Abhängt von: T1, T3

### T7 — eigenes `TMPDIR` je `verify.sh`-Lauf  [x]
Komponente: scripts · Dateien: scripts/dev/verify.sh, scripts/tests/verify_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @96d5948b 2026-09-28T10:14:55+02:00
Review: approve (opus, 2nd round)
Änderung: `verify.sh` legt je Lauf `mktemp -d "${TMPDIR:-/tmp}/ah-verify.XXXXXXXX"` an, exportiert es als `TMPDIR`
und löscht genau diesen Pfad beim Beenden. Den EXIT-Trap erst **nach** dem devenv-Block (:82–91) setzen, damit er
dessen Trap nicht überschreibt; der Exit-Code von verify.sh bleibt unverändert. Test: das Fake-`run.sh` des Tests
protokolliert `TMPDIR`; geprüft werden Präfix `ah-verify.`, ein neues Verzeichnis je Lauf, dass es danach weg ist,
und dass der Exit-Code (0, 1, 75) durchgereicht wird.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T8)

### T8 — Doku: Harness-Schutz, Handgriff `core.hooksPath`, Aufräum-Regel  [x]
Komponente: scripts · Dateien: DEVELOPMENT.md, AUTONOMOUS.md, CLAUDE.md, CHANGELOG.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @a8290fd8 2026-09-28T10:28:32+02:00
Review: approve (opus, 2nd round)
Änderung: `DEVELOPMENT.md` „Harness-Schutz und Kill-Switch" (:512 ff.): die rm-Sperre gilt in jedem Modus ohne
Kill-Switch, die Umgehungs-Sperre, der pre-commit-Hook und der Einmal-Handgriff `git config core.hooksPath
scripts/dev/hooks` (danach `harness.sh status`); Runner-User: `runner-setup.sh` erneut ausführen; verify.sh:
eigenes `TMPDIR`. `AUTONOMOUS.md` PreToolUse-Absatz (:258 ff.). `CLAUDE.md` §2 (:65–67): der Satz „interaktiv warnt
er nur" gilt für Harness-Pfade, nicht für die rm- und die Umgehungs-Sperre; §7: eine Zeile zur Aufräum-Regel
(`mktemp -p <eigenes Verzeichnis>`, nur eigene Pfade mit vollem Pfad löschen, nie per Glob). `CHANGELOG.md` unter
`[Unreleased]` / Added.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md, AUTONOMOUS.md, CLAUDE.md, CHANGELOG.md (die Task ist die Doku)
Abhängt von: T1, T2, T3, T4, T5, T6, T7

### T9 — Wächter: Befehlswort hinter Wrappern, case-Arme, Long-Option-Abkürzungen, Steuerzeichen  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/harness-guard.sh, scripts/tests/hooks_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @fdeccd26 2026-09-28T11:22:29+02:00
Review: opus: 2 rounds; round-2 finding (flag cluster) fixed as the reviewer proposed, then self-checked
Änderung: Befund aus `/code-review high` über den Branch-Diff (2026-09-28): Das Befehlswort hinter Wrappern ging verloren, weil eine gemeinsame `VALUE_FLAGS`-Menge galt und nur reine Ziffern als Dauer zählten. Dadurch liefen `sudo -n rm -rf /tmp/tmp.*`, `time -p …`, `timeout 10s …`, `setsid …` und `case x in x) rm … ;; esac` in jedem Modus durch, ebenso `timeout 1m git commit -n`. Jetzt hat jeder Wrapper seine eigenen Wert-Flags, Dauern wie `10s`/`1.5m` werden übersprungen, `setsid`, `ionice`, `builtin` und `time` (als `/usr/bin/time`) sind Wrapper, und case-Arme werden hinter `)` gelesen. Dazu: Abgekürzte Long-Options mit Wert (`git commit --mess "-n x"`) sind kein Fehlalarm mehr. `deny()` ersetzt Steuerzeichen, sonst gibt ein Tab im Harness-Pfad ungültiges JSON und der Hook versagt offen. Der Kopf listet git-Alias und direktes Schreiben von `.git/config` als Lücken.
Beweis: harness/tmp-and-commit-guards@7d9cd60f · JSON `{"command":"timeout 10s rm -rf /tmp/tmp.*"}` in den Wächter → keine Ausgabe (frei); erwartet: deny
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (DEVELOPMENT.md beschreibt die Regeln, nicht den Parser)

### T10 — Wächter: Löschen über Schleifen- und Pipe-Variablen, nur in geteilten Temp-Verzeichnissen  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/harness-guard.sh, scripts/tests/hooks_test.sh, DEVELOPMENT.md, AUTONOMOUS.md, CLAUDE.md, CHANGELOG.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @c78300dd 2026-09-28T11:58:46+02:00
Review: approve (opus, 2nd round)
Änderung: Befund aus `/code-review high` (2026-09-28): `ls -d /tmp/tmp.* | while read d; do rm -rf "$d"; done`, `… | xargs rm` und `find /tmp/claude-1000 -mindepth 1 -delete` liefen durch, und eine `for`-Schleife über einen Temp-Glob war verweigert, sobald irgendwo im selben Kommando ein unbeteiligtes `rm` stand. Jetzt gilt eine Schleife über einen Temp-Glob (`for v in <glob>`, `… | while read v`), in deren Rumpf gelöscht wird, als Treffer, auch über `cd "$v"` oder `bash -c`; ein Löschen nach `done` zählt nicht. Dazu `… | xargs rm` hinter einem Lister oder einer solchen Schleife, auch durch mehrere Pipe-Stufen. Regel nach der Messung der Aufsicht (adminhelper-ac, Kevins Auftrag, 2026-09-28: 34 513 echte Befehle, 4 echte Treffer, 13 Fehlalarme in Scratchpads): Verweigert wird nur, wenn das wörtliche Verzeichnis des Globs ein **geteiltes** Verzeichnis IST, also `/tmp`, `/var/tmp`, `/dev/shm`, `$TMPDIR`, `/tmp/claude-<uid>`, `…/<projekt>` oder `…/<projekt>/<session>`, bzw. ein `find`-Startpfad dort. Alles tiefer ist erlaubt. Regressions-Test mit den gemessenen Formen: Die 4 Treffer sind verweigert, alle 9 Scratchpad-Formen gehen durch. Kopf, DEVELOPMENT.md, AUTONOMOUS.md, CLAUDE.md §2 und CHANGELOG nennen die Regel und ihre Grenzen.
Beweis: harness/tmp-and-commit-guards@7d9cd60f · `ls -d /tmp/tmp.* | while read d; do rm -rf "$d"; done` → frei; `for f in /tmp/ah-*.log; do cat "$f"; done; rm -f build.o` → deny (Fehlalarm)
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md „Harness-Schutz und Kill-Switch", AUTONOMOUS.md, CLAUDE.md §2, CHANGELOG.md (die Regel ist enger)
Abhängt von: T9

### T11 — harness.sh status prüft die Hook-Datei; Modus-Test ohne .git  [x]
Komponente: scripts · Dateien: scripts/dev/harness.sh, scripts/tests/hooks_test.sh, scripts/tests/review_scripts_test.sh, scripts/tests/verify_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @f71ef349 2026-09-28T12:16:36+02:00
Review: approve (opus, 2nd round)
Änderung: Befunde aus `/code-review high` (2026-09-28). `harness.sh status` meldete „armed“ allein wegen `core.hooksPath`, auch in einem Worktree, dessen Branch keine ausführbare `scripts/dev/hooks/pre-commit` hat; jetzt heißt es dort „NOT armed“. Die Modus-Prüfung in `review_scripts_test.sh` fällt ohne funktionierendes `.git` (Box-Worktree, Tarball) auf das Ausführungsbit zurück, statt aus Umgebungsgründen rot zu werden. Eigener Befund des Baus: Mutationsproben mit kaputtem Aufräumer ließen 30 `ah-verify.*` in /tmp liegen. `verify_test.sh` legt deshalb das `TMPDIR` aller seiner `verify.sh`-Läufe unter sein eigenes Arbeitsverzeichnis.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (ein Halbsatz zu `NOT armed`)
Abhängt von: T9

### T12 — Wächter: benannte Einträge unter /tmp/claude-<uid> sind frei, nur Claudes eigene Verzeichnisse sind geteilt  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/harness-guard.sh, scripts/tests/hooks_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @0ae762a1 2026-09-28T13:00:00+02:00
Review: approve (opus, 2nd round)
Änderung: Fehlalarm aus der Nachmessung der Aufsicht auf fad69048 (dieselben 34 513 Befehle, 2026-09-28): `rm -f /tmp/claude-1000/rm.out`, `rmdir /tmp/claude-1000/tmp.XXXX` und `rm -rf /tmp/claude-1000/tmp.XXXX` wurden verweigert (11 Fälle), weil `is_shared` jeden Namen direkt unter `/tmp/claude-<uid>` als Projektverzeichnis las. Jetzt gelten als geteilt nur Claudes eigene Verzeichnisse: `/tmp/claude-<uid>`, ein Projekt (kodierter Pfad mit führendem `-`), eine Session (UUID) darin und die beiden, die Claude Code je uid für alle Sessions führt (`bash-edit-diff/`, `bundled-skills/`; Befund des Reviews, konservativ entschieden, der Aufsicht gemeldet). Jeder andere benannte Eintrag dort ist frei, ebenso ein Glob darin. Weiter verweigert werden die 4 gemessenen Treffer, ein Glob in einem geteilten Verzeichnis und das Löschen eines geteilten Verzeichnisses selbst. Die Deny-Meldung nennt beide Fälle.
Beweis: harness/tmp-and-commit-guards@fad69048 · `rm -f /tmp/claude-1000/rm.out` → deny; erwartet: frei
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (welche Verzeichnisse geteilt sind)
