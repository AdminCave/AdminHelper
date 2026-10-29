---
name: feature-build
description: Arbeite ein freigegebenes Task-Ledger (tasks/<slug>.md auf feature/<slug>) in einem eigenen Worktree ab — die Session baut jede Task selbst, der Sub-Agent reviewer prüft (Einsatzart task), scripts/dev/task-close.sh committet; am Ende die Abschlussprüfung des reviewer über Code und Tests (Einsatzart branch), review.sh final, PR, Merge nach grüner CI und Teardown (CLAUDE.md §4–§8). Nutzen, sobald die Roadmap-Zeile freigegeben ist; die Session gibt sie nach dem Plan-Commit selbst frei (CLAUDE.md §4).
---

# Ein Vorhaben bauen

Eingabe: `tasks/<slug>.md` (Pflicht). Das Ledger liegt bis zum Merge nur auf `feature/<slug>`, nie auf `main`.
Ohne Pfad: melden und den Pfad verlangen. Regeln: CLAUDE.md §2 (wer entscheidet, wer baut), §5 (Tests), §6 (Rollen,
Prüfer, Modelle), §7 (Commit), §8 (Worktrees), §13 (Unterbrechung, Übergabe).

## 1. Worktree

```bash
git worktree add ../AdminHelper-<slug> feature/<slug>          # existenz-tolerant: steht er schon, weiter
bash scripts/dev/worktree-setup.sh ../AdminHelper-<slug> <slug>
```

`WT` = der absolute Pfad von `../AdminHelper-<slug>`. Alles läuft als `git -C WT …` und `bash WT/scripts/…`; jeder
Sub-Agent bekommt `WT`. Pfadgebundene Regeln (`.claude/rules/`) greifen für Dateien unter `WT` nicht von selbst:
vor der ersten Task `.claude/rules/testing.md` lesen, bei Doku-Anteil `docs.md`, bei Release-Dateien `release.md`.

## 2. Kopf und Freigabe

Kopf im Worktree lesen: `Status`, `Branch`, `Spec`, `Review` (`pro Task` | `am Ende`), `Heavy`. Den Roadmap-Status
der Zeile aus `Spec:` prüfen (`python3 scripts/dev/roadmap.py show R-nnnn`). Nennt `Spec:` mehrere Zeilen (Bündel),
gilt jeder Roadmap-Schritt dieses Skills für jede von ihnen:
- Roadmap `freigegeben`, Kopf `geplant` (oder `freigegeben`, ältere Form) → Kopf im Worktree auf `aktiv`
  (`bash WT/scripts/dev/ledger.sh status WT/tasks/<slug>.md aktiv`, `git -C WT commit` als `chore(ledger)`) und
  `python3 scripts/dev/roadmap.py status R-nnnn aktiv`.
- Kopf `aktiv` → weiter mit der ersten offenen Task (nach einer Unterbrechung CLAUDE.md §13).
- Roadmap `geplant` (von Kevin angenommen oder diktiert, CLAUDE.md §4), Kopf `geplant`, das Ledger auf
  `feature/<slug>` committet und nicht jede Task `[?]` → die Session gibt frei (`python3 scripts/dev/roadmap.py
  approve R-nnnn`, CLAUDE.md §4), dann wie im ersten Punkt.
- Sonst nicht `freigegeben` → melden, nicht bauen.
- Kopf `bereit` → weiter mit 4; `erledigt` oder `blockiert` → melden.

Jeder `roadmap.py status`-Aufruf dieses Skills gibt eine Notiz der Zeile wörtlich mit `--note` wieder mit (`status`
ohne `--note` löscht sie).

Weitere freigegebene Zeilen, die beim Start die Kriterien aus `/feature-plan` §4 erfüllen (neu geprüft, auch
`df -h /`), bekommen ihren eigenen Worktree; die Session baut sie im Wechsel, wenn das laufende Vorhaben auf Prüfer,
CI oder VM wartet, oder schlägt Kevin eine eigene Session je Vorhaben vor (CLAUDE.md §2). Ein großes Vorhaben mit
disjunkten Blöcken teilt die Session auf Kevins Wort in Teil-Ledger: je Block ein Teil-Branch mit eigenem Worktree,
gemergt in den Vorhabens-Branch. Ein Teil-Ledger hängt an der Roadmap-Zeile des Vorhabens und trägt nur Tasks aus
dessen freigegebenem Plan; seinen Kopf setzt die Session beim Aufteilen auf `aktiv`, den Roadmap-Status führt nur das
Vorhabens-Ledger. Ein Teil-Branch bekommt keinen eigenen PR: ist sein Ledger fertig, merged die Session ihn in den
Vorhabens-Branch (dort neu prüfen, was die Spuren gemeinsam berühren), §4 läuft einmal über den Vorhabens-Branch,
und der PR-Text nimmt die Belege aller Teil-Ledger auf. Ein Lauf aus §4.3, der vor dem Ende startet, gilt nur,
solange spätere Tasks nichts ändern, was er prüft.

## 3. Je offener Task, in Ledger-Reihenfolge

Zusammenhängende Tasks baut die Session am Stück und liest Spec-Stelle und Code dafür einmal. Eine `[?]`-Task
überspringt sie, bis Kevin antwortet; unabhängige Tasks laufen weiter.

**Ein Zug wartet nicht** (CLAUDE.md §2): hängt eine Task bis zum Abschluss (4.1) noch an Kevins Antwort, oder wird
sie in zwei Versuchen nicht grün (3, zurückgenommen), wandert ihre Zeile in den nächsten Zug: `bash
WT/scripts/dev/ledger.sh mark-skip WT/tasks/<slug>.md <id> "verschoben in <nächster-zug>: <Grund>"` als
`chore(ledger)` und `roadmap.py status R-nnnn geplant --ledger tasks/<nächster-zug>.md --note "<bisherige Notiz>;
<Grund>"`. Der Zug fährt mit dem Rest.

1. `bash WT/scripts/dev/ledger.sh start WT/tasks/<slug>.md <id>`.
2. **Bauen.** Task, Spec-Stelle und den echten Code samt Aufrufern und Tests lesen; surgical umsetzen, im Stil des
   umgebenden Codes. Neuer Flow → Test dazu (Bug: erst rot), neue Datei → SPDX-Header, Doku nach dem `Doku:`-Feld
   (`→ T<n>`: die Doku-Task zieht sie nach). Braucht die Task eine Datei, die nicht in `Dateien:` steht: `bash
   WT/scripts/dev/ledger.sh set-files WT/tasks/<slug>.md <id> <pfade>`. Eigene Implementierungsentscheidungen: eine
   Zeile unter `## Entscheidungen` (`tasks/README.md`). Eine Entscheidung aus Kevins Bereich (CLAUDE.md §2): `bash
   WT/scripts/dev/ledger.sh mark-question … "<frage>"`, Frage gesammelt mit Empfehlung an Kevin, weiter mit der
   nächsten unabhängigen Task; mit seiner Antwort baut die Session die Task wie 1–5.
3. **Verify.** Das `Verify:` der Task fahren (`bash WT/scripts/dev/verify.sh …`), den Digest lesen, mehr nur gezielt
   aus dem Log. Rot durch die Änderung → beheben; bleibt sie nach zwei Versuchen rot → zurücknehmen und `[~]`
   (CLAUDE.md §7); ist die Ursache nach zwei ähnlichen Versuchen unklar, vorher einmal `advisor` (CLAUDE.md §6). Rot
   unabhängig von der Änderung oder nicht lauffähig (Exit 2, 74, ein Pflicht-SKIP) → STOPP für diese Task, die
   Infrastruktur melden, kein stärkeres Modell.
4. **Review** (bei `Review: pro Task`; eine Task mit `Task-Review: am Ende`, die nur Doku stagt, geht gleich zu 5):
   `reviewer` mit Einsatzart `task`, WT, Slug, Task-ID, Diff-Pfaden (`git -C WT diff HEAD -- <pfade>` plus die neuen
   Dateien), Summary-Zeile und eigenem Scratch-Verzeichnis (`mktemp -d -p <Scratchpad der Session>`); in einem
   `klein-`-Zug mit `model: "sonnet"`. **Ein Prüfer je Zug** (CLAUDE.md §6): die erste Task startet ihn, jede weitere
   setzt ihn fort (SendMessage mit denselben Eingaben für die neue Task); nach fünf Tasks oder wenn er von einer
   Kompaktierung berichtet, startet ein frischer. Risikopfad (`bash WT/scripts/dev/review.sh risk`): zusätzlich
   `security` (immer Opus), parallel. Während beide prüfen, baut die Session nichts an dieser Task weiter.
   - `approve` → 5.
   - `request_changes` mit `blocker` oder belegtem `wichtig` → die Session korrigiert, fährt das `Verify:` erneut und
     setzt denselben `reviewer` fort (SendMessage), einmal. Danach 5 oder `[?]`. Nits blockieren nie; eine dritte
     Runde gibt es nicht.
   - Turn-Limit oder Hänger → CLAUDE.md §6.
5. **Schließen.** `bash WT/scripts/dev/task-close.sh WT/tasks/<slug>.md <id> --stage -m "<msg>"` (Conventional
   Commit, englisch, Body mit `Task: <slug> <id> (R-nnnn)`). Exit 0 → nächste Task; 2 → stagen bzw. Eingabe
   reparieren, erneut; 3 → Suite rot: wie 3; Urteil fehlt oder ist älter als eine Datei: 4 erneut; dann erneut
   schließen; 4 → STOPP, Kevin; 74 → STOPP, berichten. Wiederholbar.

Neue Funde außerhalb der Task werden Roadmap-Zeilen, keine Tasks in diesem Ledger (CLAUDE.md §4).

## 4. Abschluss

1. Kopf steht auf `bereit` (setzt `task-close.sh` mit der letzten Task); sonst `ledger.sh status … bereit` als
   `chore(ledger)`. `roadmap.py status R-nnnn bereit`. Steht noch eine `[?]`-Task: in einem Zug verschieben (3,
   „Ein Zug wartet nicht“), sonst wartet der Abschluss auf Kevins Antwort (bauen oder `[~]`).
2. Keine volle Komponenten-Suite lokal: die fährt die PR-CI (CLAUDE.md §5).
3. Heavy am realen Diff entscheiden (`Heavy:` im Kopf, CLAUDE.md §5): `none` → nichts; `linux-full` → kein Lauf
   hier, das Vorhaben geht in den Sammellauf (§5), der PR-Text sagt „Heavy: Sammellauf“ (Ausnahme: der Fix eines
   REG-Ledgers aus dem Sammellauf, §5); `scenario <flags>` und `windows` → vor dem Merge, Kevin fragen. Danach
   `python3 scripts/vm/vm.py list`.
4. **Abschlussprüfung:** `reviewer` mit Einsatzart `branch` (WT, Slug, eigenes Scratch-Verzeichnis; keine
   Diff-Auswahl, keine Bewertung), bei Risikopfad im Branch (`bash WT/scripts/dev/review.sh risk --range
   origin/main..HEAD`) parallel `security` mit Einsatzart `branch`. Echte Funde: Task ins Ledger, Kopf und Roadmap
   zurück auf `aktiv`, bauen wie in 3, dann denselben `reviewer` fortsetzen; nach der zweiten Runde ohne `approve`
   → Übergabe an Kevin.
5. **Abschlussbedingung:** `bash WT/scripts/dev/review.sh final WT/tasks/<slug>.md > <Scratchpad>/final.md`. Exit 0:
   alle Tasks zu, Urteil aktuell, Code und Tests `approve`; Exit 3 nennt, was fehlt (etwa ein Commit nach dem
   Urteil → `reviewer` fortsetzen).
6. Basis nachziehen: `git -C WT fetch origin`; scheitert `git -C WT merge-base --is-ancestor origin/main HEAD`
   (etwa nach dem Merge des parallelen Vorhabens): `git -C WT merge origin/main`, das Union-Ergebnis in
   `CHANGELOG.md` von Hand prüfen (keine doppelten Überschriften; neue Einträge stehen in `changelog.d/<slug>.md`,
   `python3 scripts/release/changelog-assemble.py --check`); die Suiten dazu fährt die PR-CI. Kopf `erledigt`
   als `chore(ledger)`; `git -C WT push -u origin feature/<slug>`; PR-Text:
   `bash WT/scripts/dev/review.sh pr-body WT/tasks/<slug>.md > <Scratchpad>/pr-body.md`, dahinter `final.md` (nach
   dem Basis-Merge neu erzeugt) und das `security`-Urteil; `gh pr create --title "<type>: <feature>" --body-file
   <Scratchpad>/pr-body.md`; `roadmap.py status R-nnnn pr --pr "#<n>"`.
7. `gh pr checks <n> --watch --fail-fast`. Merge (CLAUDE.md §2): CI im ersten Anlauf grün, die Läufe aus 3 grün,
   `review.sh final` Exit 0 auf dem PR-Stand, `security` `approve` wo nötig, keine Ersatzprüfung im Branch (auch
   nicht in einem Task-Commit) → Basis wie in 6 prüfen: der Branch muss `origin/main` enthalten, sonst mergen,
   pushen, neue CI abwarten (die PR-CI testet dann genau `main` + PR; das Ruleset prüft die Kombination nicht); ein
   Merge je CI-Zyklus. Dann `gh pr merge <n> --merge` (ohne `--delete-branch`: gh entfernt sonst den Worktree; den
   Remote-Branch danach mit `git push origin --delete feature/<slug>`). Sonst → Übergabe an Kevin: rote CI, ein Lauf
   aus 3 rot, ein Urteil nicht `approve`, eine Ersatzprüfung, oder der PR ändert `.github/workflows/`,
   `scripts/install.sh`, `scripts/agent-install.sh` oder `scripts/update.sh`.
8. Nach dem Merge den `ci.yml`-Lauf des Merge-Commits beobachten: `gh run list --workflow ci.yml --commit
   <merge-sha> -L 1` wiederholen, bis er erscheint, dann `gh run watch <id> --exit-status`; rot → nichts weiter
   mergen, Revert nach CLAUDE.md §2. Dann `python3 scripts/dev/roadmap.py sync`, `git -C tasks/private push`,
   `bash scripts/dev/worktree-teardown.sh ../AdminHelper-<slug> <slug>`, `git worktree list` und
   `python3 scripts/vm/vm.py list` sauber. Dann §5: ist der Sammellauf jetzt fällig?

## 5. Sammellauf (schwere Suite über `main`)

Fällig, sobald seit dem letzten grünen Lauf (`tasks/private/history.csv`, letzte Zeile mit `all,-,pass`, ihr
Commit `C`) drei Vorhaben mit `Heavy: linux-full` auf `main` gemergt sind (`git log --merges C..origin/main`, deren
Ledger), das erste davon sieben Tage alt ist oder ein Release ansteht. Die Session prüft das beim Start und nach
jedem Merge (§4.8) und startet ihn dann selbst (Kevin, 2026-10-15): Haupt-Checkout sauber auf `main`, `git fetch
origin`, `git merge --ff-only origin/main`, dann `/test all`. Rot → Verursacher über die Merge-Commits suchen,
REG-Zeile; bis er wieder grün ist, merged die Session kein weiteres Vorhaben mit `Heavy: linux-full`, außer dem Fix
oder Revert des roten Schritts und SEC auf Kevins Wort. Ein REG-Ledger aus dem Sammellauf beweist seinen Fix vor
dem Merge mit dem `--step`-Lauf aus seinem `Heavy:`. `UNVERIFIED` (Infrastruktur) ist weder grün noch rot: melden,
keine Merge-Sperre, und die Session startet ihn nicht von selbst neu; die Wiederholung ist Kevins Wort (`/test`).

## Recovery

`git -C WT revert <task-commit>` nimmt eine Task zurück; `task-close.sh` ist wiederholbar. Nie einen roten Stand
committen: grün und committen, oder zurücknehmen und `[~]`, oder STOPP.
