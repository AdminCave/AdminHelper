---
name: feature-build
description: Arbeite ein freigegebenes Task-Ledger (tasks/<slug>.md auf feature/<slug>) in einem eigenen Worktree ab — je Task baut der Sub-Agent builder, prüft der Sub-Agent reviewer, committet scripts/dev/task-close.sh; am Ende tester, Branch-Review, PR, Merge nach grüner CI und Teardown (CLAUDE.md §4–§8). Nutzen, nachdem Kevin die Roadmap-Zeile freigegeben hat.
---

# Ein Vorhaben bauen

Eingabe: `tasks/<slug>.md` (Pflicht). Das Ledger liegt bis zum Merge nur auf `feature/<slug>`, nie auf `main`.
Ohne Pfad: melden und den Pfad verlangen. Regeln: CLAUDE.md §2 (wer entscheidet), §5 (Tests), §6 (Prüfer),
§7 (Commit), §8 (Worktrees).

## 1. Worktree

```bash
git worktree add ../AdminHelper-<slug> feature/<slug>          # existenz-tolerant: steht er schon, weiter
bash scripts/dev/worktree-setup.sh ../AdminHelper-<slug> <slug>
```

`WT` = der absolute Pfad von `../AdminHelper-<slug>`. Jeder Sub-Agent bekommt `WT`; alles Weitere läuft als
`git -C WT …` und `bash WT/scripts/…`.

## 2. Kopf und Freigabe

Kopf im Worktree lesen: `Status`, `Branch`, `Spec`, `Review` (`pro Task` | `am Ende`), `Heavy`. Den Roadmap-Status
der Zeile aus `Spec:` prüfen (`python3 scripts/dev/roadmap.py show R-nnnn`). Nennt `Spec:` mehrere Zeilen (Bündel),
gilt jeder Roadmap-Schritt dieses Skills für jede von ihnen:
- Roadmap `freigegeben`, Kopf `geplant` (oder `freigegeben`, ältere Form) → Kopf im Worktree auf `aktiv`
  (`bash WT/scripts/dev/ledger.sh status WT/tasks/<slug>.md aktiv`, `git -C WT commit` als `chore(ledger)`) und
  `python3 scripts/dev/roadmap.py status R-nnnn aktiv`.
- Kopf `aktiv` → weiter mit der ersten offenen Task.
- Roadmap nicht `freigegeben` → melden, nicht bauen. Die Freigabe ist Kevins `roadmap.py approve`.
- Kopf `bereit` → weiter mit 4; `erledigt` oder `blockiert` → melden.

Höchstens zwei Ledger `aktiv` zugleich (Deckel in `roadmap.py`), auf disjunkten Komponenten, je eigener Worktree.
Nie zwei Bauer auf demselben Ledger.

## 3. Je offener Task, in Ledger-Reihenfolge

1. `bash WT/scripts/dev/ledger.sh start WT/tasks/<slug>.md <id>`.
2. `builder` (Agent-Werkzeug, `subagent_type: builder`) mit WT, Ledger, Task-ID, Spec-Stelle und einem eigenen
   Scratch-Verzeichnis (`mktemp -d -p <Scratchpad der Session>`). Er baut, fährt das `Verify:` und gibt geänderte
   Dateien, Summary-Zeile und Commit-Nachricht zurück; er committet nicht.
3. Setzt er `[?]`: Kevin die Frage stellen, gesammelt mit Empfehlung; mit der Antwort denselben `builder`
   fortsetzen (SendMessage). Setzt er `[~]`: weiter mit der nächsten Task.
4. Bei `Review: pro Task`: `reviewer` mit WT, Slug, Task-ID, Diff-Pfaden (`git -C WT diff HEAD -- <pfade>` plus die
   neuen Dateien), Summary-Zeile und eigenem Scratch-Verzeichnis. Risikopfad (`bash WT/scripts/dev/review.sh risk`):
   zusätzlich `security`.
   - `approve` → Schritt 5.
   - `request_changes` mit `blocker` oder belegtem `wichtig` → `builder` mit den Funden, einmal; dann `reviewer`
     noch einmal. Danach Schritt 5 oder `[?]`. Nits blockieren nie, eine dritte Runde gibt es nicht.
   - Kein Urteil nach zehn Minuten → stoppen, einmal enger neu starten; dann selbst prüfen (CLAUDE.md §6).
5. `bash WT/scripts/dev/task-close.sh WT/tasks/<slug>.md <id> --stage -m "<msg>"`. Exit 0 → nächste Task;
   2 → stagen bzw. Eingabe reparieren, erneut; 3 → `builder` mit dem Grund, einmal, dann erneut schließen; 4 →
   STOPP, Kevin; 74 → STOPP, berichten. Wiederholbar.

Neue Funde außerhalb der Task werden Roadmap-Zeilen, keine Tasks in diesem Ledger (CLAUDE.md §4).

## 4. Abschluss

1. Kopf steht auf `bereit` (setzt `task-close.sh` mit der letzten Task); sonst `ledger.sh status … bereit` als
   `chore(ledger)`. `roadmap.py status R-nnnn bereit`.
2. `bash WT/scripts/dev/verify.sh <komp> --strict` je berührter Komponente; lange Läufe im tmux-Fenster
   (CLAUDE.md §2).
3. Heavy am realen Diff entscheiden (`Heavy:` im Kopf, CLAUDE.md §5): `none` → nichts; `linux-full` → `/test`;
   `scenario <flags>` → Kevin fragen. Danach `python3 scripts/vm/vm.py list`.
4. `tester` über `git -C WT diff main...`, `reviewer` über den Branch (Task-ID `branch`), bei Risikopfad
   `security`. Echte Funde: Task ins Ledger, Kopf und Roadmap zurück auf `aktiv`, bauen wie in 3.
5. Kopf `erledigt` als `chore(ledger)`; `git -C WT push -u origin feature/<slug>`;
   `bash WT/scripts/dev/review.sh pr-body WT/tasks/<slug>.md > <Scratchpad>/pr-body.md`, die Urteile von `tester`
   und `reviewer` dazu; `gh pr create --title "<type>: <feature>" --body-file <Scratchpad>/pr-body.md`;
   `roadmap.py status R-nnnn pr --pr "#<n>"`.
6. `gh pr checks <n> --watch --fail-fast`. Produkt-PR, CI im ersten Anlauf grün → Kombinationsprüfung (CLAUDE.md
   §2), dann `gh pr merge <n> --merge` (ohne `--delete-branch`: gh entfernt sonst den Worktree; den Remote-Branch
   danach mit `git push origin --delete feature/<slug>`). Harness-PR oder rote CI → Übergabe an Kevin.
7. Nach dem Merge den Lauf auf `main` beobachten (`gh run list --branch main -L 1`, dann
   `gh run watch <id> --exit-status`): rot → nichts weiter mergen, Revert nach CLAUDE.md §2. Dann
   `python3 scripts/dev/roadmap.py sync`, `git -C tasks/private push`,
   `bash scripts/dev/worktree-teardown.sh ../AdminHelper-<slug> <slug>`, `git worktree list` und
   `python3 scripts/vm/vm.py list` sauber.

## Recovery

`git -C WT revert <task-commit>` nimmt eine Task zurück; `task-close.sh` ist wiederholbar. Nie einen roten Stand
committen: grün und committen, oder zurücknehmen und `[~]`, oder STOPP.
