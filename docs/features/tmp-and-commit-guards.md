<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Schutz: kein Glob-Löschen unter /tmp, `review.sh sec` vor jedem Commit

Roadmap: R-0098, R-0102 · Ledger: `tasks/tmp-and-commit-guards.md` · Branch: `harness/tmp-and-commit-guards`
Geplant 2026-09-27 von der Aufsicht (adminhelper-ac) auf Kevins Wort; Entscheidungen am Gate unten.

## Problem / Motivation

**R-0098.** Am 2026-09-25 gegen 14:48 hat ein Review-Subagent (Opus, in der Lane `wochenlauf-gruen`) ein
mehrzeiliges Bash-Kommando mit `rm -rf /tmp/tmp.* 2>/dev/null; ls -d /tmp/tmp.* …` beendet. Er hatte seine
Probe-Verzeichnisse vorher mit `mktemp -d` angelegt, also ohne `-p`, und räumte per Glob auf. Weg waren alle
`mktemp`-Verzeichnisse des Nutzers, auch die anderer Sessions; `task-close` von Stufe 5b T6 im Haupt-Checkout
scheiterte daran (`task_close_test` verlor sein Fixture). Der Auto-Modus hat das Kommando durchgelassen, obwohl
der Classifier Glob-Löschen unter `/tmp` laut Claude-Code-Doku seit v2.1.198 standardmäßig blockieren soll
(die CLI war 2.1.280). Der Classifier ist ein Modell; eine deterministische Regel fehlt. Der heutige Wächter
`scripts/dev/hooks/harness-guard.sh` sieht Pfade außerhalb des Checkouts gar nicht (`rel()`, Z. 91–98) und lässt
die Vorfallsform in jedem Modus durch.

Nebenbefund derselben Untersuchung: Der Wächter überspringt Shell-Schlüsselwörter nicht. `for f in a; do sed -i
s/x/y/ CLAUDE.md; done` und `if true; then rm CLAUDE.md; fi` gehen auch mit `AH_AUTONOMOUS=1` ohne Meldung
durch, weil `do`/`then` als Befehl gelesen wird (`WRAPPERS`, Z. 83).

**R-0102.** `review.sh sec` (was nie in dieses öffentliche Repo darf: private Roadmap, SEC-Ledger,
`sec:`-Dedup-Keys, `.devenv.sh`, `settings.local.json`) läuft nur in `task-close.sh` (Z. 241 und 301). Der
Plan-Commit am Gate (`feature-plan` §4) und jeder andere Commit von Hand sind mechanisch ungeprüft;
`core.hooksPath` ist nirgends gesetzt, Git-Hooks gibt es im Repo keine.

## Ziel und Nicht-Ziele

Ziel:
- Glob-Löschen unter den Temp-Wurzeln ist deterministisch gesperrt, **in jedem Modus**: interaktiv, Auto-Modus,
  Subagent, autonom, Runner, **ohne Kill-Switch** (Kevin, 2026-09-27).
- Vor jedem Commit läuft `review.sh sec --staged` als pre-commit-Hook; das Modell kann ihn nicht umgehen
  (Kevin, 2026-09-27: Umgehung verweigern).
- Reviewer und alle Sessions kennen die Aufräum-Regel: Temp-Verzeichnisse nur mit `mktemp -p <eigenes
  Verzeichnis>`, nur eigene Pfade mit vollem Pfad löschen, nie per Glob (Skills und CLAUDE.md §7, Kevin 2026-09-27).
- Jeder `verify.sh`-Lauf bekommt ein eigenes `TMPDIR`, damit ein Aufräumer die Fixtures eines anderen Laufs
  nicht mehr trifft.
- Die Schlüsselwort-Lücke des Wächters ist geschlossen.

Nicht-Ziele:
- Kein Sandboxing; `rm -rf "$VAR"` und `$VAR/*` bleiben frei (der Hook kann Variablen nicht auflösen; in rund
  18 600 Bash-Aufrufen der Transkripte waren fünf solche Aufräumer, alle legitim im eigenen Scratch).
- Kein Schutz gegen Löschen aus python heraus oder über `xargs rm` (dokumentierte Lücke).
- `run.sh` bleibt unangetastet, solange Stufe 5c baut; ein `TMPDIR` je `run.sh`-Lauf ist eine eigene Zeile nach
  dem 5c-Merge.
- Kein pre-merge- oder pre-push-Hook.

## Betroffene Komponenten und Dateien

| Datei | Änderung |
|---|---|
| `scripts/dev/hooks/harness-guard.sh` | Lösch-Fund in jedem Modus; Schlüsselwort-Präfixe; Umgehung des pre-commit-Hooks |
| `scripts/tests/hooks_test.sh` | Tests dazu, `harness.sh status` |
| `scripts/dev/hooks/pre-commit` (neu, Modus 100755) | `exec bash <root>/scripts/dev/review.sh sec --staged` |
| `scripts/tests/review_scripts_test.sh`, `scripts/tests/task_close_test.sh` | Hook in einer Fixture mit `core.hooksPath` |
| `scripts/dev/runner-setup.sh`, `scripts/tests/runner_setup_test.sh` | `core.hooksPath` im Runner-Klon |
| `scripts/dev/harness.sh` | `status` zeigt, ob der pre-commit-Hook scharf ist |
| `scripts/dev/verify.sh`, `scripts/tests/verify_test.sh` | eigenes `TMPDIR` je Lauf |
| `.claude/skills/feature-review/SKILL.md`, `.claude/skills/feature-build/SKILL.md`, `scripts/tests/skill_consistency_test.sh` | Aufräum-Regel für Reviewer |
| `CLAUDE.md` (§2, §7), `AUTONOMOUS.md`, `DEVELOPMENT.md`, `CHANGELOG.md` | Doku |

Bis auf `DEVELOPMENT.md` und `CHANGELOG.md` sind alle geänderten Dateien Harness-Pfade
(`scripts/dev/harness-paths.txt`): Branch `harness/`, Bau nur interaktiv, Reviewer Opus.

## Datenmodell / API / Migrationen

Keine. Das Hook-JSON der Claude-Code-Hooks bleibt, wie `harness-guard.sh` es heute schreibt (Exit 0 und auf
stdout `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny",
"permissionDecisionReason":"…"}}`). Der Vertrag eines Git-Hooks: Exit ≠ 0 bricht den Commit ab.

## Externe Integrationen

- Claude Code Hooks und Permissions, nachgelesen 2026-09-27 (code.claude.com/docs/en/hooks, /permissions):
  PreToolUse läuft vor der Berechtigungsabfrage und **auch in Subagenten**; Exit 2 blockiert immer, jeder
  andere Exit blockiert nicht; gültiges JSON mit `permissionDecision` wird auch bei Exit 0 befolgt; Deny-Regeln
  wie `Bash(rm -rf /tmp/*)` nennt die Doku „fragile". Nicht verifiziert: welche Entscheidung gewinnt, wenn
  mehrere Hooks verschieden antworten, und ob ein JSON-`deny` im Modus `bypassPermissions` greift — der Test
  prüft die Ausgabe des Hooks, die Wirkung im jeweiligen Modus bestätigt erst der Bau.
- git 2.47.3, githooks(5), git-config(1), git-worktree(1): Ein relativer `core.hooksPath` gilt relativ zur Wurzel
  des jeweiligen Arbeitsbaums; die Repo-Konfiguration teilen sich alle Worktrees. Einmal im Haupt-Checkout
  gesetzt, fährt jede Lane den Hook **ihres** Branches; Branches ohne die Datei haben keinen Hook. Ein Hook
  ohne Ausführungsbit wird ignoriert. Nicht geprüft: ob `git revert`/`cherry-pick` pre-commit ausführen und ob
  `commit -a` den Hook über einen temporären Index fährt — das zeigt der Test in T3.

## Trade-offs und Alternativen

- **rm-Schutz im bestehenden Wächter statt eines zweiten Hooks** (gewählt): der getestete Tokenizer (Here-Doc,
  `bash -c`, `cd`) wird weiter genutzt, kein zweiter python-Start je Aufruf (~60 ms), keine Änderung an
  `settings.json` oder `runner-settings.json`, also kein neuer Lauf von `runner-setup.sh` für den rm-Schutz.
  Verworfen: Deny-Regeln (umgehbar mit `bash -c`, `/bin/rm`), `ask` statt `deny` (hält eine Lane an, unter
  `dontAsk` ohnehin eine Verweigerung), ein Hook in `~/.claude` (nicht versioniert).
- **Muster, die verweigert werden:** ein Operand von `rm`/`rmdir`/`unlink`/`shred` mit `*?[`, dessen wörtlicher
  Präfix unter `/tmp`, `/var/tmp`, `/dev/shm` oder `$TMPDIR` (als Text oder als Wert) liegt oder diese Wurzel
  selbst ist; `find` mit einer dieser Wurzeln als Startpfad und `-delete` oder `-exec`/`-execdir rm`;
  `for v in <Glob unter einer Wurzel>` mit einem rm-Segment im selben Kommando; auch nach `cd /tmp`
  (`cd /tmp && rm -rf tmp.*`). Frei bleiben `rm -rf "$D"`, `rm -rf /tmp/scratch` (ohne Glob), Globs relativ
  zum Repo und derselbe Text in einer Commit-Message oder einem Here-Doc-Rumpf.
- **TMPDIR in `verify.sh` statt in `run.sh`:** deckt jedes `Verify:` und jeden `task-close` ab, also genau den
  Weg des Vorfalls, und kollidiert nicht mit Stufe 5c. Direkte Aufrufe von `run.sh` bleiben bis zur Folgezeile
  in `/tmp`.
- **`core.hooksPath` setzt Kevin einmal von Hand** (`git config core.hooksPath scripts/dev/hooks`),
  `harness.sh status` zeigt den Stand; `runner-setup.sh` setzt es im Runner-Klon. Verworfen: `.devenv.sh`
  (nicht versioniert, jeder Verify-Lauf hätte die Konfiguration als Nebenwirkung), ein neues
  `install-hooks.sh` (müsste selbst auf die Harness-Liste), `lane.sh` (die Lanes erben es ohnehin).
- **Hook-Ort `scripts/dev/hooks/`:** fällt unter `scripts/dev/hooks/**` in `harness-paths.txt` und unter das
  Runner-Deny `Edit(./scripts/dev/**)`.

## Risiken und Rollback

- Ein Fehlalarm der rm-Regel trifft nach dem Merge alle Sessions, es gibt bewusst keinen Kill-Switch dafür.
  Rollback: `git revert` des T1-Commits.
- Eine Exception im Parser führt zu „erlaubt" (fail-open, wie heute).
- Der Schutz hängt am ausgecheckten Branch (`CLAUDE_PROJECT_DIR`): alte Branches und laufende Lanes bekommen
  ihn erst nach einem Rebase.
- Ein kaputtes `review.sh` blockiert Commits (fail-closed). Kevins Ausweg: `git config --unset core.hooksPath`
  oder `--no-verify` in der eigenen Shell. Rollback: Revert plus `--unset`.
- Nach T4 muss Kevin `sudo bash scripts/dev/runner-setup.sh` erneut ausführen.
- Das `tmp_path` von pytest ist nach einem `verify.sh`-Lauf weg; zum Debuggen fehlt es dann.

## Doku-Impact

`DEVELOPMENT.md` (Harness-Schutz und Kill-Switch Z. 512 ff., Runner-User, verify.sh, der Einmal-Handgriff mit
`core.hooksPath`), `AUTONOMOUS.md` (PreToolUse-Absatz Z. 258 ff.), `CLAUDE.md` §2 (der Satz „interaktiv warnt er
nur" gilt nicht mehr für die rm-Sperre) und §7 (Aufräum-Regel), `CHANGELOG.md` unter Added.

## Entscheidungen am Gate (Kevin, 2026-09-27)

1. rm-Sperre in allen Modi, ohne Kill-Switch.
2. Das Modell darf den pre-commit-Hook nicht umgehen: `git commit --no-verify`/`-n` (auch in kombinierten
   Kurzflags), `git -c core.hooksPath=…` und `git config … core.hooksPath` werden verweigert; Kevins eigene
   Shell bleibt frei.
3. Die Aufräum-Regel kommt zusätzlich in CLAUDE.md §7, und §2 wird nachgezogen.

Von der Aufsicht gewählt (Implementierung, am Gate genannt): `TMPDIR` in `verify.sh` jetzt; `core.hooksPath`
von Hand plus Statuszeile; Hook-Ort `scripts/dev/hooks/pre-commit`; Branch `harness/`, keine Lane.

## Offene Fragen

Keine. Nebenbefunde für die Roadmap, nicht Teil dieses Vorhabens: `DEVELOPMENT.md:421–423` und
`AUTONOMOUS.md:249–251` nennen `git add`/`git commit` noch unter `ask`, `settings.json` und `hooks_test.sh`
sagen das Gegenteil; der Kommentar `harness-guard.sh:17–19` zur Wirkung eines Exit ≠ 0 ist veraltet (wird in T1
mitkorrigiert, weil T1 die Datei ohnehin ändert).
