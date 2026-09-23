<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# `runner-setup.sh` ein zweites Mal fahren können — Task-Ledger
Status: erledigt · Branch: harness/runner-setup-rerun · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Spec: dieses Ledger (Bugfix, gefunden beim Anwenden von R-0072; Roadmap R-0076)
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: nein — der Diff berührt nur `scripts/dev/runner-setup.sh` und `scripts/tests/runner_setup_test.sh`.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Warum

`runner-setup.sh` nennt sich idempotent, aber ein **zweiter** echter Lauf stirbt in Schritt 2
(2026-09-23, beim Anwenden des Runner-Pins aus PR #36):

```
$ git -C /srv/ah/repo config remote.origin.url https://github.com/AdminCave/AdminHelper.git
Schwerwiegend: nicht in einem Git-Repository
```

Ursache: Nach dem ersten Lauf gehört `/srv/ah/repo` dem Runner (`chown -R` am Ende von
Schritt 2). Root fährt `git -C` in einem Repository, das jemand anderem gehört, und Git
verweigert das (`safe.directory`, „dubiose Besitzverhältnisse"; `git config` meldet es als
„nicht in einem Git-Repository"). Der erste Lauf klappt nur, weil der Klon da noch root gehört.
Nichts wurde verändert: der Abbruch liegt vor dem `chown` und vor Schritt 3. Der
Trockenlauf, den `runner_setup_test` prüft, sieht den Fehler nicht, denn er führt nichts aus.

Die Verweigerung ist **richtig**, nicht zu umgehen: ab dem zweiten Lauf ist der Klon vom
Runner kontrolliert, und eine `.git/config` kann Programme nennen (`core.fsmonitor`,
`core.hooksPath`), die root's Git dann ausführen würde. Ein `safe.directory`-Override wäre
genau die Lücke, gegen die der Schutz existiert.

### T1 — Die Git-Konfiguration des Klons schreibt der Runner, nicht root  [x]
Komponente: scripts · Dateien: scripts/dev/runner-setup.sh, scripts/tests/runner_setup_test.sh
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped @599a0d2a 2026-09-23T12:22:32+02:00
Review: am Ende (Kurz-Ledger)
Änderung: Das `chown -R` rückt vor die beiden `git config`, und beide laufen als Runner (`su - <runner> -c 'git -C … config …'`) — beim ersten Lauf wie bei jedem weiteren, sodass root nie in einem Runner-eigenen Repository Git fährt. `ORIGIN` kommt aus Kevins Checkout und wird mit `printf %q` in den Befehl gesetzt. Test: der Trockenlauf-Plan enthält beide `git config` als Runner und **keine** Zeile, in der root `git -C /srv/ah/repo` fährt; die Gegenprobe (alte Reihenfolge) wird rot.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (Bugfix; DEVELOPMENT.md beschreibt den zweiten Lauf bereits als idempotent)

## Review am Ende (Opus, frischer Kontext, 2026-09-23)

`approve`, kein Blocker, kein wichtiger Fund; Gegenprobe vom Reviewer selbst wiederholt (altes Skript + neuer Test ⇒ 68/3). Zwei Nits miterledigt: der Kommentar zum Symlink-Schutz und die Fehlermeldung des Tests nennen nicht mehr root's `git -C`, und die Config-Zusicherung prüft `url` und `pushurl` einzeln. Nicht übernommen, weil außerhalb dieses Fixes: `run()` druckt `$*` ohne Argumentgrenzen (kosmetisch, betrifft den ganzen Plan) und ein theoretisches Rennen, falls der Runner `$SRV/repo` leert und root dann hineinklont — als eigene Roadmap-Zeile aufgenommen.
