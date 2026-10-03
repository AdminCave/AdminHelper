<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stufe 7a — der Worker: `ledger-loop.sh` baut freigegebene Ledger als `adminhelper-runner`

Roadmap: R-0010 (Teil 7a), R-0108 · Stand: main@2508f092 · Geplant 2026-10-03 von der Aufsicht, Entscheidungen
Kevin 2026-10-03 (A–G, unten „Design“) · 7b folgt als eigener Plan (Ausblick am Ende)

## Problem / Motivation

Seit Stufe 4 gibt es den Runner-Nutzer `adminhelper-runner`: eigener Klon `/srv/ah/repo` ohne Push-Recht, eigene
Test-DB, Abo-Token, `dontAsk` mit Deny-Liste (`scripts/dev/runner-settings.json`), Red Team. Seit 6a/6b schließt
`task-close.sh` eine Task mechanisch, mit Reviewer als eigenem Prozess (`--review auto`). Was fehlt, ist der
Teil, der all das ohne Kevins Anwesenheit nacheinander aufruft: Heute baut jede Task eine interaktive Session in
Kevins Rechten, und jemand muss neben ihr sitzen. Die AH-STATUS-Zeile sagt es selbst: „Worker: — (ab 7)“
(`scripts/dev/hooks/session-status.sh:187`).

Dazu ein offener Fund (R-0108): Unter `dontAsk` laufen nur die eingebauten Nur-Lese-Befehle und Allow-Regeln. Laut
Doku (code.claude.com/docs/en/permissions, „Read-only commands“: `ls`, `cat`, `echo`, `pwd`, `head`, `tail`, `grep`,
`find`, `wc`, `which`, `diff`, `stat`, `du`, `cd`, Nur-Lese-Formen von `git`) gehören `mktemp`, `rm` und
`git worktree add` nicht dazu, und `runner-settings.json` erlaubt keinen davon (Allow-Liste `:55–105`). Eine
Bau-Session des Runners, die einen Scratch-Ordner anlegt und wieder löscht, wird also abgewiesen.

## Ziel & Nicht-Ziele

Ziel:
- **`scripts/dev/ledger-loop.sh`**: läuft als `adminhelper-runner` in tmux, baut eine von Kevin übergebene Liste
  freigegebener Ledger Task für Task — je Task eine frische `claude -p`-Session mit `/build-task`, dann
  `task-close.sh --review auto` durch den Loop —, hält an sichtbaren Deckeln an und schreibt Zustand und Summary.
- **`/build-task`**: ein Skill für genau eine Task, ohne Commit, ohne Haken, ohne Edits unter `tasks/`.
- **Bau-Session-Grenzen** in `runner-settings.json`: Deny auf `tasks/**`, Scratch nur über einen Wrapper
  (`scripts/dev/scratch.sh`, R-0108).
- **Abbruch-Aufräumen**, Stall-Erkennung, Stopp-Klassen und eine Übergabe ohne Git-Zugriff Kevins auf das
  Runner-Repo.
- **Sichtbarkeit**: `ledger-loop.sh status` und eine echte Worker-Zeile im AH-STATUS.
- **Red Team** prüft die Grenzen einer Bau-Session.

Nicht-Ziele (7b oder später):
- Heavy-Läufe aus dem Loop (`heavy.sh gate|capstone` mit Runner-Token), Ebene 3 Merge-Readiness als Prozess,
  `/build pr|ci`, Boundary-Regel, Roadmap-Anbindung (`roadmap.py next`/`stats` aus `state.json`),
  Skill-Umbenennung `feature-*` → `plan/build/review`, eigene Probe-DB für den Runner (R-0154.3).
- Ein Verb `/build status`: CLAUDE.md §2 kennt es nicht; den Stand zeigen in 7a das Skript und AH-STATUS.
- Harness-Ledger im Loop (Entscheidung G).
- Ein zweiter Worker (D16).

## Betroffene Komponenten & Dateien

- Neu: `scripts/dev/ledger-loop.sh`, `scripts/dev/scratch.sh`, `.claude/skills/build-task/SKILL.md`; Tests
  `scripts/tests/ledger_loop_test.sh`, `scripts/tests/scratch_test.sh` (beide in `AH_SCRIPT_TESTS_DEFAULT`,
  `scripts/tests/run.sh:586`; die zwei Skripte in `scripts/dev/harness-paths.txt`).
- Geändert: `scripts/dev/runner-settings.json` (Deny `tasks/**`, Allow Scratch-Wrapper und `.ah-out/loop/**`),
  `scripts/dev/hooks/session-status.sh` (`:187`), `scripts/dev/runner-redteam.sh` (Abschnitt 5, `:338`),
  Tests `hooks_test.sh` (Abschnitt runner-settings.json, `:1231`), `session_status_test.sh`, `redteam_test.sh`,
  `skill_consistency_test.sh`; Doku `AUTONOMOUS.md`, `DEVELOPMENT.md`, `docs/developer/cicd.html` +
  `docs/en/developer/cicd.html`, `CHANGELOG.md`.
- Unverändert benutzt: `task-close.sh` (mit `--stage --review auto --message-file`, `:8–10` plus 6b), `ledger.sh`,
  `lane.sh` (`new` legt `../AdminHelper-<slug>` an, `:131`, also `/srv/ah/AdminHelper-<slug>`; das von
  `runner-setup.sh:247` angelegte `$SRV/lanes` bleibt ungenutzt), `verify.sh`, `review.sh pr-body`,
  `runner-env.sh`.

## Design

### Entscheidungen (Kevin, 2026-10-03)

- **A — Pläne zum Runner:** Die Aufsicht pusht freigegebene Plan-Branches (`feature/<slug>`) zu GitHub; der Runner
  fetcht `origin` (HTTPS, öffentliches Repo, kein Credential nötig). Kein gemeinsam beschreibbarer Pfad.
- **B — Ledger-Wahl:** Kevin übergibt beim Start eine explizite Liste (`--ledger tasks/a.md --ledger tasks/b.md`,
  in seiner Reihenfolge). Die Roadmap bleibt privat; der Loop liest sie nie.
- **C — Nutzungslimit:** Stopp mit Reset-Zeit (`stop: usage-limit`), die Task bleibt `[ ]`, die Lane wird
  aufgeräumt. Kein Warten.
- **D — `[?]` oder Blocker nach Runde 2:** das Ledger wird `blockiert`, der Loop nimmt das nächste der Liste.
- **E — Teilung:** jetzt 7a (dieser Plan), 7b später.
- **F — Deckel:** großzügiges Netz, als Flags mit Default, damit der Pilot ohne Code-Änderung nachstellen kann:
  Bau-Session `--task-minutes 60 --task-turns 80 --task-budget 12`, Lauf `--max-hours 8 --max-tasks 20
  --max-budget-usd 200`.
- **G — Harness-Ledger:** lehnt der Loop ab (Branch `harness/…` oder ein `Dateien:`-Eintrag aus
  `harness-paths.txt`); sie bleiben interaktiv.

### Start und Preflight

Kevin startet (nie ein Timer, CLAUDE.md §2; die Aufsicht beobachtet nach D21):

```
sudo -u adminhelper-runner tmux new -d -s ah-loop \
  'cd /srv/ah/repo && bash scripts/dev/ledger-loop.sh --ledger tasks/<a>.md [--ledger tasks/<b>.md] [--max-hours 8]'
```

Preflight, jeder Fehlschlag `stop: infra` (Exit 74) mit einem Satz:
- `runner-env.sh` lädt (Token, `AH_AUTONOMOUS=1`); `claude --version` = `scripts/dev/runner-claude.version`;
  `claude auth status` meldet `authMethod: oauth_token` (laut CLI-Referenz ohne Modell-Aufruf); `flock`, `git`,
  `python3` vorhanden.
- Der Klon `/srv/ah/repo` ist sauber und auf `main`. `git fetch origin`; ist `main` hinter `origin/main`, zieht der
  Loop `--ff-only` nach — **nur** wenn dabei kein Pfad aus `harness-paths.txt` wechselt. Sonst
  `stop: infra (Harness auf main geändert — Pull + Red Team durch Kevin)`: neue Harness-Regeln gelten erst nach
  Kevins Setup- und Red-Team-Lauf.
- Der Loop ruft immer die Harness-Skripte **seines Klons** (`/srv/ah/repo/scripts/dev/…`), nie die einer Lane.

### Je Ledger

1. `git fetch origin feature/<slug>`; der Ledger-Kopf auf dem Branch: `Branch: feature/<slug>`, `Status:
   freigegeben` (oder `aktiv` beim Fortsetzen) **und** eine `Freigabe:`-Zeile. Sonst überspringen mit Grund.
2. Harness-Prüfung (G): Branch `harness/…` oder ein `Dateien:`-Pfad aus `harness-paths.txt` ⇒ `blockiert
   (harness)`, ohne Lane.
3. Lane: `lane.sh new <slug>` (Worktree `/srv/ah/AdminHelper-<slug>`). Gibt es sie schon (Fortsetzen): weiter, wenn
   sie sauber auf `feature/<slug>` steht; schmutzig ⇒ `blockiert (Lane schmutzig)` — nie `stash`, `checkout --`,
   `clean`.
4. `git merge origin/main` in der Lane, nicht `rebase`: der Plan-Branch liegt auf GitHub (A), ein Rebase ließe ihn
   dort divergieren; und GitHub wertet `merge=union` nicht aus. Konflikt ⇒ `git merge --abort`, `blockiert
   (merge)`.
5. Fundament: `verify.sh <Komponenten der offenen Tasks> --strict` in der Lane. Rot ⇒ `blockiert (Fundament rot)`
   mit Log-Pfad; Exit 74 ⇒ `stop: infra`.
6. `ledger.sh status aktiv`, als Ledger-Commit des Loops (siehe unten).

### Je Task

1. Nächste Task = erste `### T… [ ]` im Ledger der Lane; `ledger.sh start`.
2. Bau-Session in der Lane:
   `timeout <task-minutes>m claude -p "/build-task tasks/<slug>.md <id>" --permission-mode dontAsk
   --permission-prompts none --max-turns <task-turns> --max-budget-usd <task-budget> --output-format json
   --no-session-persistence` — frisch je Task, nie `--bare` (liest keine Abo-Anmeldung, D18). Modell und Effort
   kommen aus dem Runner-Pin (`runner-settings.json`).
3. Auswertung des JSON: Kosten, Turns, Verweigerungen, Fehlerart, Ergebnistext. Das Fehlerfeld (`subtype` oder
   anderes) übernimmt 7a aus der Messung von 6b T1 (`Messung:`-Zeilen im 6b-Ledger).
4. Danach entscheidet allein der Loop:
   - **Limit** (Ergebnistext „You've hit your … limit · resets …“, laut Doku code.claude.com/docs/en/errors ein
     Ausführungsfehler im `-p`-Lauf; JSON-Form **nicht verifiziert**, Stub-Test) ⇒ Aufräumen, Task bleibt `[ ]`,
     `stop: usage-limit` mit Reset-Zeit (C).
   - **Timeout (124/143), `error_max_turns`, `error_max_budget_usd`, sonstiger Fehler** ⇒ Aufräumen, `[?]
     timeout|turns|budget|error` per `ledger.sh mark-question`, Ledger `blockiert` (D).
   - **`[~]` gesetzt** ⇒ Aufräumen bis auf das Ledger, Ledger-Commit, nächste Task.
   - **`[?]` gesetzt** ⇒ Aufräumen bis auf das Ledger, Ledger-Commit, Ledger `blockiert` (D).
   - **Commit-Nachricht liegt vor** (`.ah-out/loop/<slug>/<id>.commit-msg.txt`) ⇒
     `task-close.sh tasks/<slug>.md <id> --stage --review auto --message-file <datei>`:
     - `0` ⇒ nächste Task.
     - `3` (Verify rot, Diff-Scan, Doku-Paar, Vertrag oder `request_changes`) ⇒ **eine** zweite Bau-Session
       `/build-task tasks/<slug>.md <id> --fix <close-log> [<verdict>]`, dann `task-close` erneut. Wieder `3` ⇒
       `[?]` mit dem ersten Blocker als Frage, Aufräumen, Ledger `blockiert` (D).
     - `4` (sec, scope, Blocker nach Runde 2) ⇒ `[?]`, Aufräumen, `blockiert` (D).
     - `74` ⇒ ein Wiederholungsversuch; wieder `74` ⇒ Aufräumen, Task bleibt `[ ]`, `stop: infra`.
     - `2` (nichts gestagt, Baum geändert) ⇒ zählt als Iteration ohne Fortschritt (Stall).
   - **Nichts davon** (keine Nachricht, kein Marker) ⇒ Iteration ohne Fortschritt.
5. **Stall:** Ist die Ledger-Datei nach zwei aufeinanderfolgenden Iterationen derselben Task byte-identisch ⇒
   `[?] stall`, Ledger `blockiert`.
6. **Verweigerungen** (`permission_denials`) blockieren nicht von selbst: Der Loop zählt sie je Task mit Regel ins
   Summary; ob die Task trotzdem gut ist, entscheidet `task-close`. Ein abgelehnter harmloser Griff aus Gewohnheit
   (`git add`) ist kein Fehler der Task — aber der Pilot muss ihn sehen, damit Allowlist oder Skill nachgezogen
   werden.

**Aufräumen** ist eine Operation des Loops, nie des Modells (die Settings verbieten dem Modell `restore`/`stash`):
`git diff HEAD > <loop>/<slug>/<id>.aborted.diff`, `git restore --source=HEAD --staged --worktree -- <alles außer
tasks/<slug>.md, wenn das Ledger bleiben soll>`, neue Dateien aus `git status --porcelain --untracked-files=all`
einzeln mit vollem Pfad löschen (nie per Glob), der Scratch-Ordner der Lane (`scratch.sh`) ebenso.

**Ledger-Commits des Loops** (`aktiv`, `[~]`, `[?]`, `blockiert`): der Loop committet nur, wenn `git diff --name-only`
genau `tasks/<slug>.md` ist und die Änderung nur Status-Kopf, Task-Marker und die Zeilen von `ledger.sh` betrifft;
sonst `stop: infra`. Nachricht `chore(ledger): <slug> <was>`; der pre-commit-Hook (`review.sh sec`) läuft.

### Deckel und Stopp-Klassen

Geprüft an jeder Task-Grenze (eine laufende Task wird nie abgebrochen, außer durch ihre eigenen Deckel):
`--max-hours`, `--max-tasks`, `--max-budget-usd` (Summe `total_cost_usd`, Listenpreis-Äquivalent, D18),
`--max-ready 2` (zwei Ledger in diesem Lauf auf `bereit` ⇒ `stop: kevin-queue`, der Deckel `bereit 2` aus
CLAUDE.md §3).

Stopp-Klassen in der letzten Zeile: `ledger-leer` (jedes Ledger der Liste `bereit` oder `blockiert`), `max-hours`,
`max-tasks`, `max-budget`, `kevin-queue`, `usage-limit`, `infra`, `harness-modified` (der Lane-Diff berührt einen
Pfad aus `harness-paths.txt` — die Deny-Regeln hätten das verhindern müssen, also STOPP, nicht `blockiert`).

### Ledger-Ende

`task-close` setzt `bereit` mit der letzten Task. Danach schreibt der Loop:
- `<loop>/<slug>/pr-body.md` aus `review.sh pr-body tasks/<slug>.md`, bei `Heavy:` ≠ `none` mit dem Vermerk
  „Heavy offen — fährt die Aufsicht“ (Heavy aus dem Loop ist 7b).
- **Übergabe:** `git bundle create <loop>/<slug>.bundle origin/main..feature/<slug>` (+ `git bundle verify`).
  Kevin holt den Branch in **seinem** Checkout mit `git fetch <loop>/<slug>.bundle
  feature/<slug>:feature/<slug>`. Kevins Git arbeitet nie in einem Repo, das dem Runner gehört: dafür müsste er
  `safe.directory` für `/srv/ah/repo` setzen, und dann könnte eine Runner-eigene `.git/config` (etwa
  `core.fsmonitor`, `core.hooksPath`) Programme in Kevins Rechten starten. Ein Bundle ist nur Daten. Dass `git fetch`
  aus der Bundle-Datei eines anderen Nutzers ohne `safe.directory` geht, ist **nicht verifiziert** — der Pilot prüft
  es. Push und PR bleiben Kevins (und die Aufsicht) Handgriff.

### Sichtbarkeit

Der Loop schreibt nach `${AH_LOOP_DIR:-/srv/ah/loop}` (Runner-eigen, für Kevin lesbar):
`state.json` (Lauf, Ledger, Task, Runde, Kosten, Turns, Dauer, Verweigerungen, Stopp-Grund, Reset-Zeit),
`summary-<datum>.md` mit der Schlusszeile `ledger-loop: <n> tasks, <k> ready, <b> blocked, <$> total, stop:
<klasse>`, je Task die Logs unter `<slug>/`. Kevin liest das mit `bash scripts/dev/ledger-loop.sh status [--state
<datei>]` **aus seinem eigenen Checkout** (nie ein Runner-eigenes Skript in Kevins Rechten) und im AH-STATUS
(„Worker: läuft T3/8 tasks/x.md · 4,10 $ · seit 01:12“ bzw. „Worker: stop: ledger-leer 06:40“). Beide lesen nur die
Datei und geben ihre Texte gereinigt aus (druckbare Zeichen, Länge begrenzt — wie die Halter-Zeile der Python-Sperre).

### Bau-Session-Grenzen und R-0108

`runner-settings.json` heute: Allow `Edit(./tasks/**)` (`:88`), Deny nur `Edit(./tasks/private/**)` (`:31`).
Der Plan verlangt: das Modell ändert ein Ledger nur über `ledger.sh` (Allow `start`, `mark-skip`, `mark-question`,
`set-files`, `status`, `lint`, `:60–65`). Neu: Deny `Edit(./tasks/**)` und `Edit(//srv/ah/**/tasks/**)` (das Allow
`:88` entfällt), Allow `Edit(./.ah-out/loop/**)` für die Commit-Nachricht. Deny schlägt Allow (Doku: „Rules are
evaluated in order: deny, then ask, then allow“), auch für Umleitungsziele (`> tasks/x.md` wird gegen Edit-Regeln
geprüft).

**R-0108 — Scratch für den Builder: Wrapper statt Allow-Regel.** Eine enge Allow-Regel wie `Bash(mktemp -d -p
/srv/ah/scratch/*)` oder `Bash(rm -rf /srv/ah/scratch/*)` begrenzt Argumente per Textmuster; die Doku warnt genau
davor („Bash permission patterns that try to constrain command arguments are fragile“): `rm -rf
/srv/ah/scratch/../repo` passt auf das Muster. Enger ist ein Wrapper, dessen Prüfung Code ist:
`bash scripts/dev/scratch.sh new [<name>]` legt `mktemp -d -p <lane>/.ah-out/scratch <name>.XXXXXX` an (gitignored,
eine Marker-Datei darin) und druckt den Pfad; `bash scripts/dev/scratch.sh rm <pfad>` löscht nur, was `realpath` als
direktes Kind dieses Ordners **mit** Marker ausweist — kein Glob, kein Symlink, keine Traversal. Allow nur für
diese zwei Verben; das Skript liegt unter `scripts/dev/` und ist für das Modell nicht editierbar (Deny `:27`).
**`git worktree add` für Revert-Proben bekommt der Builder gar nicht:** Den Beweis „Test ohne Änderung rot“ fährt
seit 6b der Runner selbst (`review-probe.sh` in `task-close --review auto`), in seinem eigenen Worktree — die enge
Lösung ist hier, dass der Builder sie nicht braucht.

## Kevins Handarbeit

Vor dem Bau (Voraussetzungen):
1. 6b gemergt **und** der `--review auto`-Pilot gefahren (7a ruft genau diesen Weg).
2. `runner-vorarbeit-2` (R-0152: das Red Team liest nicht mehr die Runner-eigene `.devenv.sh`) gemergt.
3. Nach #70 und nach `runner-vorarbeit-2`: `sudo bash scripts/dev/runner-setup.sh`,
   `sudo -u adminhelper-runner git -C /srv/ah/repo pull --ff-only`, Red Team als Runner.

Nach dem Merge von 7a:
4. Dieselben drei Handgriffe noch einmal (7a ändert `runner-settings.json` und das Red Team).
5. Runner-Token gültig: `sudo -u adminhelper-runner bash -lc '. /srv/ah/repo/scripts/dev/runner-env.sh && claude
   auth status'` (setup-token gilt ein Jahr).
6. Eine CLAUDE.md-Zeile für den Worker (Kevins Harness-Datei), etwa in §2: „Der Worker (`ledger-loop.sh`, Stufe 7)
   startet nur auf Kevins Zuruf als `adminhelper-runner` in tmux; die Aufsicht beobachtet ihn bis zum Summary.“

**Pilot** (Handarbeit nach dem Merge, kein Task): ein 3-Task-Übungs-Ledger in einer Nicht-Harness-Komponente (drei
kleine, belegte REF/BUG-Zeilen), geplant und freigegeben wie jedes andere, Branch von der Aufsicht gepusht (A).
Kevin startet `ledger-loop.sh --ledger tasks/<pilot>.md --max-hours 2`, abends, nachdem er `/usage` gelesen hat. Danach
prüfen: drei Commits auf `feature/<pilot>` (je mit dem Ledger), jede `[x]`-Task mit `Evidenz:` und `Review:`;
`summary` endet `stop: ledger-leer`; Bundle holt sich in Kevins Checkout; Verweigerungen je Task gelesen; Kosten,
Turns und Dauer je Task gemessen ⇒ Deckel aus F nachstellen (Flags, kein Code). Die Fehlerpfade (Limit, Budget,
Stall, Lane schmutzig, Harness-Ledger) beweisen die hermetischen Tests mit dem `claude`-Stub, nicht der Pilot.

## Externe Integrationen

Claude Code CLI, Runner-Pin `scripts/dev/runner-claude.version` (2.1.280). Belegt (code.claude.com/docs, headless,
cli-reference, permissions, permission-modes, errors; gelesen 2026-10-03):
- `-p` endet mit Exit ≠ 0, wenn der Lauf scheitert; ein Fehler im Lauf steht als Ergebnis auf stdout.
- `--output-format json` liefert `total_cost_usd` (Client-Schätzung), `session_id`, `result`; mit
  `--permission-prompts none` stehen Verweigerungen in `permission_denials`. SIGTERM ⇒ Exit 143, die Runde bleibt
  offen.
- `dontAsk` weist alles ab, was fragen würde; Nur-Lese-Befehle und Allow-Regeln laufen. Deny vor Ask vor Allow.
  Umleitungsziele gegen Edit-Regeln. Ein Bash-Deny ist laut Doku keine Sicherheitsgrenze um ein Programm
  (`bash -c 'git push'` trifft `Bash(git push *)` nicht) — die Grenze für Push ist das fehlende Credential plus
  `pushurl=/dev/null`, die Regel ist die zweite Schicht.
- `-p` wartet bis zu 10 min auf Hintergrund-Subagenten (`CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`) — daher das harte
  `timeout` je Session.
- Ohne `--bare` laufen die Projekt-Hooks auch in `-p` (gewollt: harness-guard); `--bare` liest keine OAuth-Anmeldung.
- Am Abo-Limit endet ein `-p`-Lauf mit einem Ausführungsfehler; automatisches Warten gibt es nur interaktiv.

**Nicht verifiziert** (Stub-Tests jetzt, Pilot misst): die JSON-Form der Limit-Meldung und der Fehlerart (6b T1 misst
die Fehlerart); `git fetch` aus einem fremden Bundle ohne `safe.directory`; ob `lane.sh new` im Runner-Klon ohne
`.devenv.sh` und ohne `settings.local.json` sauber durchläuft (erwartet: keine eigene Lane-DB, die Runner-DB aus
`runner-env.sh` gilt — bei einem Loop ohne parallele Suiten ausreichend).

## Trade-offs & Alternativen

- **Liste statt Roadmap (B):** weniger Automatik, dafür keine privaten Inhalte für den Runner lesbar.
- **Merge statt Rebase:** eine Merge-Commit-Spur mehr; dafür kein Divergieren gepushter Plan-Branches.
- **Bundle statt `git fetch runner`:** ein Handgriff mehr für Kevin; dafür nie Kevins Git in einem Runner-Repo.
- **Verweigerungen nicht blockierend:** ein falsch erlaubter Weg fällt erst im Summary auf; dafür kostet eine
  Gewohnheit nicht ein ganzes Ledger. `task-close` bleibt das Gate.
- **Scratch-Wrapper statt Allow-Regel:** ein Skript mehr unter `scripts/dev/`; dafür Pfad-Prüfung als Code.

## Risiken & Rollback

- **Nutzungsfenster:** Runner und Kevins Sessions teilen sich das Abo. Nachts starten, vorher `/usage`; `stop:
  usage-limit` räumt auf und hält.
- **1M-Kontext:** Der Runner-Pin `claude-opus-5-5[1m]` lief bisher (R-0072); die Doku nennt „Usage credits required
  for 1M context“ eine Berechtigungsprüfung, nicht Quota. Schlägt sie an, muss der Loop `stop: infra` liefern, nicht
  zwanzig rote Tasks — der Preflight erkennt es nicht, die erste Task schon (Fehlerart ⇒ Exit 74 bei Infra-Text).
- **Prompt-Injection** über Spec, Ledger oder Repo-Inhalt: Bremsen sind `dontAsk`, Deny, harness-guard, kein
  Credential, `task-close` mit 6b-Reviewer und der Stopp `harness-modified`.
- **Rollback:** den Loop nicht starten. Er läuft nur auf Kevins Zuruf; `git revert` der 7a-Commits und ein neuer
  Setup-Lauf stellen die alten Settings her.

## Doku-Impact

`AUTONOMOUS.md` (Abschnitt „Der Worker“: Start, Deckel, Stopp-Klassen, Übergabe), `DEVELOPMENT.md` (Worker starten,
Stand lesen, Bundle holen, Recovery), `docs/developer/cicd.html` + `docs/en/developer/cicd.html`, `CHANGELOG.md`.
Die CLAUDE.md-Zeile ist Kevins Handarbeit (oben).

## Ausblick 7b

Heavy-Gate aus dem Loop (`heavy.sh gate|capstone --for <ledger>`, Runner-PVE-Token, Kapazität per `vm.py doctor`),
Ebene 3 Merge-Readiness als Prozess (`/code-review` + Verifikation), `/build pr|ci` (Bundle holen, `origin/main`
mergen, Push und Draft-PR in Kevins Session), Boundary-Regel, `roadmap.py next`/`stats` aus `state.json`, eigene
Probe-DB (R-0154.3), Contract-Laufzeit (R-0151.3), Skill-Umbenennung mit dem Verb `/build`.

## Offene Fragen

Keine Produktfragen; A–G sind entschieden. Am Gate von der Aufsicht entschieden und änderbar: Bundle als Übergabe,
`merge` statt `rebase`, Verweigerungen nicht blockierend, Fast-Forward des Klons nur ohne Harness-Änderung, kein
`git worktree add` für den Builder.
