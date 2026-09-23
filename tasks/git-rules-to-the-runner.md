<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Die Git-Regeln gehören dem Runner, nicht Kevin — Task-Ledger
Status: geplant · Branch: harness/git-rules-to-the-runner · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Spec: dieses Ledger (Harness-Korrektur an einer Regel aus Stufe 4)
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: nein — der Diff berührt `.claude/settings.json`, einen Skript-Test und zwei Sätze Doku.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Warum

Stufe 4 hat `git add`, `git commit`, `git checkout`, `git restore` und `git stash` in
`.claude/settings.json` auf `ask` gesetzt, damit der Weg zum Commit über `task-close.sh` läuft.
Die Absicht war richtig, der Ort war falsch: die Datei ist versioniert und gilt für **jede**
Session in diesem Repo, also auch für Kevins eigene und für jeden überwachten Worker.

**Der Preis ist gemessen, nicht vermutet.** Am 2026-09-22 hing Worker 1 45 Minuten an einem
`git add`, Worker 2 später genauso — beide Fenster zeigten dabei „bypass permissions on", denn
der Bypass überspringt nur die *Standard*-Abfrage, nicht eine ausdrückliche `ask`-Regel
(Rangfolge deny → ask → allow). Ein Bau, der auf eine Bestätigung wartet, die ohnehin kommt,
ist ein Bau, der stillsteht.

**Eine Ausnahme ließe sich nicht formulieren.** `ask` gewinnt gegen `allow`, unabhängig von der
Spezifität — „frag bei `git add`, außer in `tasks/private`" gibt es nicht. Entweder die Regel
gilt für alle, oder sie steht dort, wo sie hingehört.

## Wo sie hingehört

Adressat der Regel war immer der **autonome Runner**, nicht die überwachte Session. In
`scripts/dev/runner-settings.json` stehen dieselben Kommandos als hartes `deny`, nicht als
`ask` — dort bleiben sie unverändert. Für den Runner trägt die Grenze ohnehin nicht die
Regelliste, sondern die Betriebssystem-Ebene: kein Credential, kein `gh`, kein Push-Weg,
eigene Datenbank, eigener Pool-Token (belegt im T11-Anhang von `tasks/harness-stufe-4.md`).

Für Kevins Sessions bleibt die Disziplin da, wo sie wirkt: `task-close.sh` ist der einzige Weg,
der die Evidenz-Zeile schreibt, und das steht im Build-Skill, in `DEVELOPMENT.md` und in
`tasks/README.md`. Eine Abfrage, die man wegklickt, erzieht niemanden.

## Was ausdrücklich bleibt

`bash scripts/vm/bootstrap_linux.sh`, `bash scripts/dev/harness.sh off` und
`bash scripts/dev/ledger.sh mark-done` bleiben auf `ask`. Die drei sind selten, irreversibel oder
unterlaufen einen Beweis — die sollen wehtun.

### T1 — Die fünf Git-Regeln aus Kevins Settings nehmen  [ ]
Komponente: scripts · Dateien: .claude/settings.json, scripts/tests/hooks_test.sh
Änderung: `Bash(git add:*)`, `Bash(git commit:*)`, `Bash(git checkout:*)`, `Bash(git restore:*)`, `Bash(git stash:*)` aus `permissions.ask` entfernen; die drei übrigen `ask`-Regeln bleiben. In `hooks_test.sh` die `must_ask`-Menge (Z. 641–644) entsprechend kürzen und eine Zusicherung ergänzen, die das Gegenteil festhält: diese fünf dürfen **nicht** in `ask` stehen, damit die Regel nicht unbemerkt zurückkehrt. Die Prüfung der Runner-Settings (Z. 522 ff., dort `deny`) bleibt unberührt — das ist die Liste, die trägt.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (T2)

### T2 — Den Satz in CLAUDE.md richtigstellen  [ ]
Komponente: scripts · Dateien: CLAUDE.md
Änderung: Zeile 62 sagt „`git add|commit|checkout|restore|stash` prompten seitdem". Das gilt ab hier nur noch für den Runner, dort als `deny`. Der Satz wird darauf umgeschrieben, ohne die Aussage zu verlieren, dass `task-close.sh` der Weg zum Commit ist. Kein `CHANGELOG`-Eintrag: das ist Harness-Verhalten im Bau, nichts am Produkt.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: CLAUDE.md
Abhängt von: T1
