<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Autonomes Arbeiten an AdminHelper mit Claude Code

Diese Anleitung beschreibt, wie du AdminHelper so weit wie möglich **autonom** mit Claude
Code weiterentwickelst — vom Feature-Wunsch (oder einem Fable-Audit-Report) bis zum fertigen
Draft-PR. Sie baut auf einer Erkenntnis auf: **du machst das Kernmuster längst von Hand.**
Dein früheres root-`tasks.md` war bereits eine _durable Task-Ledger_ mit verifizierbaren
Zielen pro Aufgabe. Dieses System formalisiert genau das.

**Alle Ledger leben unter [`tasks/`](tasks/)** — eine Datei pro Vorhaben (`tasks/<slug>.md`),
kein Anhängen an eine Sammel-Datei mehr. Jedes Ledger trägt im Kopf ein Feld `Status:` in der
Folge `geplant` → `freigegeben` → `aktiv` → `bereit` → `erledigt`, daneben `blockiert`;
`/feature-build` baut ein `freigegeben`es und das eine `aktiv`e. Konvention: `tasks/README.md`.

## Die Idee in fünf Sätzen

1. **Ledger-getrieben.** Jede Arbeit lebt in einer Markdown-Ledger aus kleinen, einzeln
   verifizierbaren Tasks. Die Ledger ist die einzige Wahrheit über den Fortschritt und
   übersteht Kontext-Resets — das macht lange autonome Läufe erst möglich.
2. **Klein genug.** Eine Task ≈ eine fokussierte Änderung, möglichst eine Komponente,
   mit einem konkreten `Verify:`. Nur so kann sie ohne Rückfrage abgearbeitet werden.
3. **Ein Gate.** Der feste Kontrollpunkt ist das **Design-Gate** nach der Planung: Kevin gibt
   frei, bei kleinen Fund-Paketen die Aufsichts-Session (CLAUDE.md §2 „Entscheidungen“). Danach
   läuft Bauen → Testen → PR autonom.
4. **Granulare Commits = einfache Recovery.** Ein Commit pro Task auf einem Feature-Branch,
   geschrieben von [`scripts/dev/task-close.sh`](scripts/dev/task-close.sh) — nicht von der
   Session. Geht etwas schief: `git revert <commit>` statt Handarbeit. Ein abgeschalteter Test
   hält den Commit auf (`review.sh diff-scan`); ein ganzer Test darf nur gehen (toter Code oder
   ein genauerer Ersatz), wenn die Task ihn schon **committet** als `Test-Löschung:` ankündigt, und
   eine Assertion in einem bleibenden Test sich nur ändern, wenn sie ebenso committet als
   `Assertion-Änderung:` dasteht ([`tasks/README.md`](tasks/README.md)).
5. **Test-Tiering.** Schnelle Suiten laufen nach jeder Task; die schwere VM-Suite erst
   am Ende, einmal.

## Der Zyklus

| Phase | Aufruf | Ergebnis |
|---|---|---|
| **1 · Design** | `/feature-plan <idee>` (oder `--kurz R-nnnn`, `--bundle <komponente>`) | **Interaktiv** (fragt bei echter Mehrdeutigkeit sofort per Rückfrage): erzeugt `docs/features/<slug>.md` (Spec) + `tasks/<slug>.md` (Ledger, `Status: geplant`) als ersten Commit auf `feature/<slug>` und trägt die Roadmap-Zeile auf `geplant`. **Stoppt am Design-Gate.** |
| **2 · Freigabe** | _du_ (kleine Fund-Pakete: die Aufsichts-Session, CLAUDE.md §2) | Spec + Ledger lesen/anpassen, offene Fragen beantworten. Die Freigabe setzt `roadmap.py approve` und den Kopf auf `freigegeben` mit der Zeile `Freigabe:`. |
| **3 · Build** | `/feature-build tasks/<slug>.md` | Task für Task: `ledger.sh start` → umsetzen → schnelle Tests → **frischer Review** (`feature-review`) → `task-close.sh` setzt den Haken und committet Code + Ledger auf `feature/<slug>`. |
| **4 · Verify + PR** | _(automatisch am Ende von Phase 3)_ | `run.sh quick` → schwere VM-Suite → Review über den ganzen Branch (`/code-review`; beim Kurz-Ledger stattdessen der eine `feature-review`) → **Übergabe an die Aufsicht**, die prüft, pusht, den PR öffnet und merged (CLAUDE.md §2). |

**Woher die Arbeit kommt.** Was als Nächstes gebaut wird, steht in der privaten Roadmap
`tasks/private/ROADMAP.md`. Ihren Abschnitt „Als Nächstes" kuratiert Kevin von Hand. Die
Tabellenzeilen pflegt [`scripts/dev/roadmap.py`](scripts/dev/roadmap.py) (`add`, `status`,
`approve`, `sync`), nie ein Edit an der Datei: Nur das Skript schreibt unter Sperre, mit
`.bak`, Zeilenzahl-Prüfung und einem lokalen Commit im privaten Repo (`DEVELOPMENT.md`, „Die
Roadmap als Skript"). Neue Zeilen legen Kevin und die Skripte an (`heavy.sh` für
Regressionen und ein rotes Dependency-Audit). `/roadmap` zeigt den Stand mit den WIP-Deckeln, und `/roadmap triage` geht die
`neu`-Zeilen mit Kevin durch (annehmen, ablehnen, zurückstellen, bündeln). Eine angenommene
Zeile wird über `/feature-plan` zu Spec und Ledger (Phase 1); freigeben (`approve`) tut
Kevin, bei kleinen Fund-Paketen die Aufsichts-Session (CLAUDE.md §2).

Die Session läuft auf **mindestens Opus** (`/model opus` oder `claude --model opus`; Fable ist
ebenso zulässig). Das gilt für Planen und Bauen und auch für die Explorer- und Verifikations-
Subagenten der Planung (Kevin, 2026-09-18). Der **Reviewer** ist
die Ausnahme: er läuft auf **Sonnet** und nur dann auf Opus, wenn `review.sh risk` einen
Risikopfad im Diff meldet (`scripts/dev/review-risk.txt` plus die Harness-Pfade) — mit Opus lief
er regelmäßig eine halbe Stunde ohne Urteil, mit Sonnet urteilt er in Minuten
(`.claude/skills/feature-build/SKILL.md`, Schritt 4). Eine Review-Runde ist die Regel, eine
zweite nur bei einem `blocker` oder einem belegten `wichtig`. Seit Stufe 6b kann der Reviewer ein
eigener Prozess von `task-close.sh` sein (`--review auto`, im Pilot per Ledger-Kopf `Review: auto`):
der Runner fährt die Probe, `scripts/dev/review-run.sh` startet `claude -p` mit festem Prompt und
eigenen Settings, und Prompt wie Urteil gehen nicht durch die Bau-Session; höchstens zwei Runden, ein
Prozess ohne Verdict ist Exit 74 ohne Rückfall auf den Sub-Agent. Jede Runde steht mit Kosten,
Turns und Dauer in `review.sh log` (`DEVELOPMENT.md`, „Reviewer als Prozess").

**Ebene 0: deterministische Prüfer.** Vor jedem Modell beantworten Skripte, was sich ohne
Urteil entscheiden lässt (Stufe 6a): `review.sh risk` (Risikopfad im Diff, danach das
Reviewer-Modell), `docs-pairs` (beide Sprachen einer Doku-Seite), `contracts` (die Prüfungen,
die an den geänderten Pfaden hängen), `check-verdict` (ein Urteil passt zu Schema und Baum),
`scripts/dev/review-probe.sh` (wäre der neue Test ohne den Fix rot), `pr-body` (der PR-Text
aus dem Ledger) und `log` (jede Reviewer-Runde, Stufe 6b). `task-close.sh` fährt `diff-scan`,
`scope`, `docs-pairs` und `sec` vor der Suite und `contracts` danach, bei jedem Abschluss; Details
in `DEVELOPMENT.md`, „Review-Pruefer (Ebene 0)".

**Zwei Review-Ebenen (dein Reviewer-„dazwischen").** Der Code wird nie ungeprüft committet:
(1) **pro Commit-Einheit** ein **frischer Sub-Agent** (`feature-review`; mit `Review: auto` ein
eigener Prozess von `task-close.sh`), der nur den Diff + die Task + feste Kriterien sieht —
unvoreingenommen, weil er den Bau-Verlauf nicht kennt;
(2) am Ende ein `/code-review` über den ganzen Branch-Diff. Ebene 1 fängt den einzelnen
Fehltritt sofort, Ebene 2 die Wechselwirkungen. **Ausnahme Kurz-Ledger** (≤ 3 Tasks, Kopf
`Review: am Ende`): dort fallen beide Ebenen zu **einer** zusammen — ein `feature-review` über
den ganzen Branch-Diff, kein `/code-review` hinterher, weil der zweite Durchgang denselben Diff
noch einmal sähe. `feature-review` läuft auch standalone (`/feature-review`, oder
`/loop /feature-review` für einen frischen Prüf-Durchlauf).

### So startest du konkret

```bash
# Opus-Session mit reduzierten Nachfragen (Edits/Tests/Git ohne Prompt):
claude --model opus --permission-mode acceptEdits
```

```text
# 1. Planen (stoppt am Gate):
/feature-plan Pro-Connection-Notiz: freies Textfeld an jeder Verbindung, in Web + Desktop editierbar

# 2. Du liest docs/features/connection-note.md + tasks/connection-note.md, passt an, gibst frei.

# 3. Autonom bauen bis Draft-PR, auf dem Branch, auf dem der Plan liegt (R-0065):
git switch feature/connection-note
/feature-build tasks/connection-note.md
```

Push, PR und Merge stehen nicht im Lauf eines Workers: Er übergibt am Ende, die
Aufsichts-Session prüft, pusht, öffnet den PR und merged; ohne Aufsicht nennt die Session die
Befehle und du führst sie aus (Betriebsmodell in `CLAUDE.md` §2). Eine Allow-Regel für
`gh pr create` oder `--dangerously-skip-permissions` ist nicht vorgesehen.

## Zweiter Einstiegspunkt: einen Fable-Report abarbeiten

Der „Report fixen"-Fall ist derselbe Mechanismus — die Report-Funde _sind_ ein Ledger unter
`tasks/`:

```text
/feature-build tasks/audit-fixes.md
```

`tasks/audit-fixes.md` ist die Fortschritts-Ledger zum letzten Audit; das Fix-Detail je Fund
steht in der Quelle, auf die das `Spec:`-Feld des Ledger-Kopfs zeigt (gleiche IDs). Für sehr
große Backlogs (die 681 Funde)
startest du es unter `/loop`, damit es batchweise über viele Iterationen läuft:

```text
/loop /feature-build tasks/audit-fixes.md
```

## Parallel-Betrieb: mehrere Lanes gleichzeitig

Mehrere Vorhaben laufen parallel, indem jedes Ledger seine eigene **Lane** bekommt: ein
Git-Worktree + eigene Opus-Session + eigene warme VM. Geplant wird weiterhin
seriell (das Design-Gate braucht dich); gebaut wird parallel. **Nie zwei Builds auf
demselben Ledger** — der Ledger ist die einzige Fortschritts-Wahrheit, es gibt kein Locking.

```bash
# 1. Planen wie gehabt (/feature-plan → Gate → Freigabe). Spec + Ledger sind der
#    erste Commit von feature/<slug> (R-0065) — Worktrees sehen nur Committetes.
#    lane.sh new sucht den Plan dort (ohne den Branch: auf main) und bricht ohne ihn ab.
# 2. Lane aufmachen — mehr braucht es nicht (Worktree ../AdminHelper-<slug>; eine
#    eigene .devenv.sh mit eigener Test-DB adminhelper_test_<slug> und eigenem Venv,
#    settings.local.json als Kopie — Claude Code schreibt sie bei Grants; das
#    frpc-Sidecar als Kopie — vm.py sync trägt einen Link als Link auf die Box, und
#    dort zeigt er ins Leere; die Komponenten-Venvs mit dem CI-ruff als Links in den
#    Haupt-Checkout, nur zum Lesen — die Links sperren nichts, installiert wird ins
#    eigene Venv der Lane, und auf die Box reist kein .venv):
bash scripts/dev/lane.sh new <slug>
# 3. Lane starten (eigenes Terminal/tmux-Pane):
cd ../AdminHelper-<slug> && claude --model opus --permission-mode acceptEdits
#    → /feature-build tasks/<slug>.md
# 4. Lane gemergt / Feierabend:
bash scripts/dev/lane.sh done <slug>   # reapt die Lane-Boxen, räumt Worktree, Branch, DB, Venv
#    — verweigert, solange noch ein Prozess in der Lane arbeitet (etwa ihre Session):
#    erst die Session dort beenden, dann erneut done
```

Mechanik dahinter:

- **Eigene Lane-Kennung je Worktree.** `scripts/dev/lane.sh new <slug>` schreibt den Slug
  nach `.vm/lane`; `vm.py` und `scripts/vm/lib.sh` lesen beide diese Datei (`AH_LANE`
  überschreibt). Jede VM trägt den Tag `lane-<slug>`, und `reap`, der Auto-Sweep am Ende
  jedes Verbs und die Leak-Prüfung in `list` arbeiten auf der eigenen Lane — Lanes können
  sich nicht gegenseitig die Boxen abräumen, und zwar über den Zustand auf dem Hypervisor,
  nicht über eine lokale Ableitung, die zwei Seiten verschieden raten können. (`destroy`
  filtert über `--lane/--scenario/--role`; eine ausdrücklich genannte VMID wird zerstört —
  darauf beruht `reap.sh`, das die VMIDs aus der warm.env der eigenen Lane nimmt.) Klone werden seriell
  abgeschickt (ein Linked Clone dauert ~2 s); Bootstrap und Iterationen laufen parallel.
  Aus einem Worktree reist `.git` nur als Zeiger mit, der auf der Box ins Leere zeigt
  (`scripts/vm/rsync-exclude.txt` schließt `.git` nicht aus, aber nichts auf der Box verlässt
  sich darauf). Die Box braucht kein Repo (Kevin, 2026-09-25): Kopf und Tree-Hash gibt
  `iter.sh` vom Client mit, und `run.sh` nimmt sie, wenn das `git` der Box nichts antwortet.
- **Die schweren Python-Schritte stehen Schlange.** `server-pytest` und `schemathesis` holen
  in `run.sh` eine Sperre, die alle Checkouts teilen: laufen eine Lane und der Haupt-Checkout
  gleichzeitig, fährt der zweite Server-Lauf sichtbar nach dem ersten, statt ihm Speicher und
  Tabellen zu nehmen. Hat `runner-setup.sh` die geteilte Sperre `/var/lib/adminhelper-dev/py.lock`
  angelegt, warten auch Kevin und der Runner-Nutzer (ab Stufe 7) aufeinander; ohne ihr Verzeichnis
  gilt die Sperre je Unix-Nutzer. Das ersetzt die Absprache „nur ein server-Lauf zur Zeit";
  Wartezeit und Abschalter stehen in `DEVELOPMENT.md` („Python-Tests lokal").
- **`Heavy:` im Ledger-Kopf** (`none | linux-full | scenario <flags> | windows`) sagt, welche
  schwere Suite der Abschluss braucht; es ersetzt für neue Ledger die beiden älteren Felder
  unten, die `feature-build` bei älteren Ledgern weiter liest. Dass eine Lane ihre
  Schnellsuite auf der VM fährt (das alte `Fast-Suite: vm`), kann ein neues Ledger damit nicht
  sagen; das ist offen (R-0097).
- **`Fast-Suite: vm` im Ledger-Kopf** (ältere Ledger). Eine Lane hat keine `node_modules` und kein
  `target`; ihr Python-Testvenv (`AH_VENV`, `~/.cache/ah-venv-<slug>`) hat sie eigens, die
  Komponenten-Venvs mit dem CI-`ruff` sind nur Links in den Haupt-Checkout. N parallele lokale
  Suiten würden die Dev-Box überlasten. Die Test-DB ist es nicht mehr: jede Lane hat ihre
  eigene (`adminhelper_test_<slug>`, angelegt von `lane.sh new`). Der Build
  fährt deshalb das Task-`Verify:` via `bash scripts/vm/iter.sh --cmd '…'` und die
  Komponenten-Schnellsuite via `bash scripts/vm/iter.sh quick --strict --only <komponenten>`
  auf der warmen Lane-Box (~1,5–3,5 min pro Iteration).
- **`Warm-Profil:` im Ledger-Kopf** (ältere Ledger). `desktop` (eine volle Box — Stack, Agent und GUI
  testen dort zusammen) reicht für fast alles; `pond` (2 Boxen) nur für Desktop-Journeys;
  Cross-Host-Pfade bekommen `Abschluss: multibox <flags>` — ein einmaliger, weiterhin
  ask-first-Lauf am Ende, keine warme Dauer-Infrastruktur. `/feature-plan` leitet das aus
  der Spec ab, `feature-build` re-checkt es am realen Branch-Diff.

Regeln:

- **Der Haupt-Checkout bleibt auf `main`** — nur Planen, Mergen, Rebasen. Gebaut wird
  ausschließlich in Lanes.
- **Lanes komponenten-disjunkt schneiden.** Das Gate prüft gegen aktive Lanes:
  Komponenten, geteilte Contracts (API-Schemas, Migrationen, FRP-Format, Tauri-Commands),
  primäre `docs/`-Seiten. Überlappt es → seriell statt parallel. Ist es disjunkt und braucht
  höchstens eines der Vorhaben VMs, **schlägt das Gate die Lane von sich aus vor** und gibt
  die Startbefehle mit (Kevin, 2026-09-18). Zwei Python-Bauten kollidieren nicht mehr auf
  der Test-DB: jede Lane hat ihre eigene.
- **PRs landen einzeln.** Nach jedem Merge in den verbleibenden Lanes
  `git rebase origin/main` + einmal `bash scripts/vm/iter.sh quick`. Bekannte, triviale
  Rebase-Konflikte: `CHANGELOG.md` (Unreleased) und geteilte docs-Seiten — additiv.
- **Kosten:** pro Lane eine warme beast-Box (pond: zwei) über Stunden; Tokens ≈ wie
  seriell, nur die Burn-Rate steigt (Rate-Limits drosseln ggf. von selbst). Mehr als
  2–3 Lanes stauen an deinen Gates/Reviews, nicht am Compute.

## Der Worker (Stufe 7a)

Bis Stufe 6 baut eine Session, die Kevin offen hat. Der **Worker**
[`scripts/dev/ledger-loop.sh`](scripts/dev/ledger-loop.sh) baut freigegebene Ledger ohne
offene Session: als Nutzer `adminhelper-runner`, in dessen Klon `/srv/ah/repo`, jedes Ledger in
seiner Lane (`lane.sh new <slug>`). Er pusht nie, öffnet keinen PR und merged keinen; in die Lane merged
er `origin/main` (ein Konflikt ist `blockiert (merge)`) und fährt dann die Suiten der offenen Tasks als
Fundament (rot ist `blockiert (Fundament rot)`).

**Start** — nur auf Kevins Zuruf, nie per Timer (CLAUDE.md §2), in tmux:

```bash
sudo -u adminhelper-runner tmux new -d -s ah-loop \
  'cd /srv/ah/repo && bash scripts/dev/ledger-loop.sh --ledger tasks/<a>.md --ledger tasks/<b>.md'
```

Die Ledger sind Kevins Liste in seiner Reihenfolge; die Roadmap liest der Loop nie. Ein Plan
erreicht den Runner als gepushter Branch `feature/<slug>` (die Aufsicht pusht ihn, Entscheidung A);
gebaut wird nur ein Kopf mit `Branch: feature/<slug>`, `Status: freigegeben` (oder `aktiv`, dann
geht es weiter) und einer `Freigabe:`-Zeile. Ein Harness-Ledger (Branch `harness/…` oder ein
Harness-Pfad in `Dateien:`) bleibt interaktiv: `blockiert (harness)` ohne Lane.

**Je Task** eine frische Bau-Session: `claude -p` mit dem Text von
[`/build-task`](.claude/skills/build-task/SKILL.md) aus dem Klon, nur den Settings des Runners
(`--setting-sources user`, `dontAsk`), dazu `--task-minutes 60 --task-turns 80 --task-budget 12`. Die
Session baut eine Task, testet mit `verify.sh` und hinterlässt eine Commit-Nachricht; sie committet
nicht, setzt keinen Haken und ändert ein Ledger nur über `ledger.sh` (`mark-skip`, `mark-question`,
`set-files`) und nur in ihrer eigenen Task — Kopf und andere Tasks bleiben, wie sie waren, sonst wird
die Task `[?]`. Danach entscheidet allein der Loop: Er schließt mit `task-close.sh --review auto
--round <n>`; bei Exit 3 gibt es **eine** zweite Session mit `--fix` (Runde 2, wenn die erste ein Verdict
hatte — eine rote Suite oder ein Diff-Scan-Fund schreibt keins, dann bleibt es Runde 1), ein zweites 3 wird
`[?]` mit dem ersten Blocker; 4 wird `[?]`; 74 wird einmal wiederholt, dann `stop: infra`. Eine
Session über Zeit, Turns oder Budget wird `[?] timeout|turns|budget`, ein anderer Fehler
`[?] error`, zwei Iterationen ohne Fortschritt mit byte-gleichem Ledger `[?] stall`; ein API-Fehler
oder eine Session ohne JSON ist dagegen ein Ausfall: `stop: infra`, die Task bleibt offen. Ein `[?]`
setzt das Ledger auf `blockiert`, und der Loop nimmt das nächste der Liste (Entscheidung D); ein
Ledger, in dem nur noch `[?]` offen sind, wird `blockiert`, nie `bereit`. Was eine
Session hinterlässt, ohne dass die Task schließt, nimmt der Loop zurück (`aborted.diff`, `git
restore`, neue Dateien einzeln mit vollem Pfad) — nie `stash`, `clean` oder ein Glob.

**Deckel** (Entscheidung F, als Flags, damit der Pilot ohne Code nachstellt): `--max-hours 8`,
`--max-tasks 20`, `--max-budget-usd 200` (Bau-Sessions **und** Reviewer, im Loop selbst gezählt;
unbekannte Kosten zählen mit ihrem Deckel),
`--max-ready 2` (zwei Ledger `bereit` in diesem Lauf: Kevins Warteschlange). Zeit und Budget gelten an
jeder Task-Grenze und zwischen den Iterationen einer Task; eine laufende Session beendet nur ihr
eigener Deckel.

**Stopp-Klassen** in der letzten Zeile des Summary: `ledger-leer` (die Liste ist durch),
`max-hours`, `max-tasks`, `max-budget`, `kevin-queue`, `usage-limit` (das Abo-Limit, mit Reset-Zeit;
die Task bleibt offen, Entscheidung C), `infra` (Exit 74, ein Satz nennt den Grund) und
`harness-modified` (Exit 74: eine Session hat einen Harness-Pfad geändert oder etwas getan, was nur
ihr Code konnte — der HEAD der Lane oder der Klon haben sich bewegt; das Ledger bleibt danach gesperrt,
bis Kevin `/srv/ah/loop/<slug>/harness-modified` entfernt). Eine CLI, die nicht mehr der
festgehaltenen Prüfsumme entspricht, endet als `infra`; mitten im Lauf ist sie dasselbe Signal
(`DEVELOPMENT.md`, „Der Worker“, Recovery).

**Stand und Übergabe.** Der Loop schreibt nach `/srv/ah/loop`: `state.json`, `loop.log`, je Stopp
`summary-<datum>.md` (Schlusszeile `ledger-loop: <n> tasks, <k> ready, <b> blocked, $<x> total,
stop: <klasse>`), je Ledger die Logs. Kevin liest das mit `bash scripts/dev/ledger-loop.sh status`
**aus seinem eigenen Checkout**; die erste Zeile davon steht als „Worker:“ im AH-STATUS. Ein Ledger auf
`bereit` hinterlässt `<slug>/pr-body.md` (`review.sh pr-body`, mit „Heavy offen — fährt die Aufsicht“
außer bei `Heavy: none`) und `<slug>.bundle`. Kevin holt den Branch in **seinen** Checkout:
`git fetch /srv/ah/loop/<slug>.bundle feature/<slug>:feature/<slug>`. Kevins Git arbeitet nie in einem
Repo des Runners: dafür bräuchte es `safe.directory`, und dann könnte eine Runner-eigene
`.git/config` (`core.fsmonitor`, `core.hooksPath`) Programme mit Kevins Rechten starten — ein Bundle
ist nur Daten. Ob `git fetch` aus der Bundle-Datei eines anderen Nutzers ohne `safe.directory` geht,
ist **nicht verifiziert**; der Pilot prüft es.

**Grenzen.** Die Bau-Session hat keine schreibenden Git-Befehle, keine Edits unter `tasks/`, keine
Harness-Pfade, kein `mktemp` und kein `rm` (ein Scratch-Ordner nur über `scripts/dev/scratch.sh`); das
Red Team prüft diese Grenzen. Code, den eine Session schreibt, läuft aber über `verify.sh` mit den
Rechten des Runners: Was er hinter dem Loop ändert, **erkennt** der Loop nachträglich und hält an,
verhindern kann er es nicht. Die Spec nennt die bewusst offenen Stellen
([`docs/features/stufe-7a.md`](docs/features/stufe-7a.md), „Verdicts im Runner“).

**Pilot.** Den ersten echten Lauf fährt Kevin nach dem Merge mit einem kleinen Übungs-Ledger
(`--max-hours 2`, abends, nach einem Blick auf `/usage`); vorher Setup, Pull und Red Team wie nach
jeder Änderung an den Runner-Settings (`DEVELOPMENT.md`, „Der Worker“).

## Was eine Task „autonomietauglich" macht

Das ist der Punkt, an dem die meiste Qualität entsteht — `/feature-plan` achtet darauf, aber
prüf es am Gate mit:

- **Eine Komponente, ≤ ~3 Dateien.** Zwei Komponenten (z. B. Server-API _und_ Web-Formular)
  → zwei Tasks.
- **Ein konkretes `Verify:`.** Ein Befehl/Assertion, der grün/rot sagt. „Sieht gut aus" ist
  kein Verify.
- **Unabhängig testbar**, Reihenfolge nur bei echter Abhängigkeit.
- **Keine Design-Entscheidung in der Task.** Steckt eine drin, ist die Task zu groß — die
  Entscheidung gehört als offene Frage in die Spec und wird am Gate geklärt.
- **Neuer Flow ⇒ Task enthält den Test. Neue Datei ⇒ Task nennt den SPDX-Header.**

## Recovery — wenn etwas schiefgeht

- **Ein einzelner Fehlgriff:** `git revert <task-commit>` nimmt genau diese Task zurück, der
  Rest bleibt. Genau dafür committet der Loop pro Task.
- **Ein Fix macht Tests rot** und ist nicht schnell lösbar: der Loop nimmt ihn selbst zurück
  (`git restore --source=HEAD --staged --worktree -- <datei>`), markiert die Task
  `[~] (verworfen: Test rot)` und macht weiter. Revert-Proben laufen nie im Builder-Tree,
  sondern in einem eigenen Worktree — sonst löscht die Probe ungestagte Arbeit.
- **Rotes Fundament** (Test rot, unabhängig von der Änderung): der Loop **stoppt** und
  berichtet, statt weiterzubauen.
- **Ganzes Feature verwerfen:** der Branch ist isoliert — `git switch main && git branch -D
  feature/<slug>` und alles ist weg.
- **`[?]`-Tasks** (mehrdeutig/destruktiv) überspringt der Loop bewusst und legt sie dir am
  Ende zur Entscheidung vor.

## Die Automatisierungs-Schicht (`.claude/`)

> **`.claude/` wird per Whitelist geteilt** (das Repo ist PUBLIC). Versioniert sind die
> wiederverwendbare Automatisierung: `settings.json` (Permissions + Hook), `skills/`,
> `rules/` (pfadgebundene Regeln) und `agents/`.
> **Draußen bleibt nur `settings.local.json`** — sie trägt die Proxmox-Infra (`env`, aus
> `settings.json` dorthin verschoben, damit keine Homelab-Details öffentlich werden). Das
> Proxmox-Token liegt außerhalb des Baums in `~/.config/adminhelper/pve.env` (0600, R-0229);
> der `env`-Block bleibt dafür nur der Rückfall. Neue `.claude/`-Dateien sind per Default ignoriert, bis
> du sie in der `.gitignore`-Whitelist freigibst.

Damit „autonom" nicht an ständigen Prompts scheitert, ist Folgendes eingerichtet:

- **`.claude/settings.json` → `permissions.allow`**: schnelle Tests/Linter (`pytest`,
  `ruff`, `go test/vet`, `cargo test/clippy/fmt`, `npm run`), die nicht-destruktiven
  Git-Befehle (`switch`, `branch`, `status`, `diff`, `log`, `show` — dazu `revert`, das zwar
  einen Commit schreibt, aber genau die Recovery ist, auf der dieser Ablauf beruht), die
  Harness-Skripte (`task-close.sh`, `ledger.sh` ohne `mark-done`, `review.sh`,
  `harness.sh status|on`), der Test-Aggregator
  und der ganze VM-Weg (`python3 scripts/vm/vm.py <verb>`, `scripts/vm/*.sh`,
  `scripts/tests/multibox.sh`, `scripts/tests/heavy.sh`) laufen **ohne Nachfrage** —
  innerhalb des Pools sind Klonen, Baken und Zerstören freigegeben (CLAUDE.md §2,
  2026-09-08). **`git add`, `git commit`, `git checkout`, `git restore`, `git stash`** sind in
  den Runner-Settings hart verboten und in Kevins Sessions frei — eine Abfrage, die immer
  bestätigt wird, hielt nur den Bau auf; committet wird über `task-close.sh`, und die drei
  Recovery-Verben löschen im Zweifel ungestagte Arbeit. Unter `permissions.ask` stehen nur
  `bootstrap_linux.sh`, `harness.sh off` und `ledger.sh mark-done`. Nicht freigegeben
  (der eine bewusste Endstopp): `git push`, `gh pr create`, alles unter `rm`/`reset --hard`,
  `harness.sh off` und `ledger.sh mark-done` (der Kill-Switch des Wächters und der Haken
  ohne Lauf sind Kevins Handgriffe, nicht die des Modells) und `scripts/vm/bootstrap_linux.sh` — das einzige Skript, das die Maschine
  verändert, auf der es läuft, und die Dev-Box hat bewusst kein Docker.
  **Einen langen Lauf zu STARTEN ist davon unberührt:** das ist eine Frage der Initiative,
  nicht der Permission, und bleibt bei Kevins Zuruf (CLAUDE.md §2).
- **Ein `PreToolUse`-Hook: der Harness-Wächter.** `scripts/dev/hooks/harness-guard.sh` liest
  vor jedem `Edit`/`Write`/`MultiEdit`/`Bash`, welche Datei der Aufruf schreiben würde, und
  verweigert ihn, wenn sie in [`scripts/dev/harness-paths.txt`](scripts/dev/harness-paths.txt)
  steht — aber **nur im autonomen Lauf** (`AH_AUTONOMOUS=1`) und nur, solange der Kill-Switch
  `bash scripts/dev/harness.sh off` nicht gesetzt ist. Interaktiv warnt er bloß; die Warnung
  sieht man erst mit `claude --debug`, weil Claude Code bei Exit 0 nur das JSON auf stdout
  liest. Ein Ledger, das den Harness selbst ändert (wie Stufe 4), ist genau der Fall für
  `harness.sh off` — den **Kevin** setzt: ein Modell, das seinen eigenen Wächter abschalten
  darf, hat keinen. Zwei Regeln gelten dagegen **in jedem Modus**, auch interaktiv und auch
  mit gesetztem Kill-Switch: kein Löschen per Glob in einem geteilten Temp-Verzeichnis (`/tmp`,
  `/var/tmp`, `/dev/shm`, `$TMPDIR`, `/tmp/claude-<uid>/…` bis zur Session; R-0098), und keine Umgehung des pre-commit-Hooks (R-0102). Vier Git-Hooks
  fahren `review.sh sec --staged`: `scripts/dev/hooks/pre-commit` vor jedem Commit,
  `prepare-commit-msg` bei cherry-pick, revert, rebase (Standard-Backend) und Merge-Commit,
  `pre-merge-commit` vor einem Merge-Commit, `pre-applypatch` bei `git am` und
  `rebase --apply` (R-0110); scharf werden sie je Klon mit
  `git config core.hooksPath scripts/dev/hooks`, `harness.sh status` zeigt es.
  Einzelheiten: DEVELOPMENT.md „Harness-Schutz und Kill-Switch".
- **Kein Auto-Format-Hook.** (Ein früherer PostToolUse-Formatter wurde entfernt: er
  reformatierte ganze Dateien → gegen die Surgical-Regel und die Doku-Commits, und brach
  iterative `Edit`s. Formatierung fangen ohnehin die `ruff format --check`/`npm run lint`-
  Gates.) `scripts/dev/format-file.sh` bleibt als **manuelles** Werkzeug (`bash scripts/dev/
  format-file.sh <datei>`).
- **Skills** unter `.claude/skills/`: `feature-plan` (interaktiv), `feature-build`,
  `feature-review` (frischer-Kontext-Reviewer, auch standalone), `roadmap` (die Roadmap
  zeigen und triagieren, nur über `roadmap.py`), dazu das bestehende `test` (die Suiten) und
  `vm` (die VMs darunter).

### Erweiterungsideen (noch nicht gebaut)

- **`/feature-verify`** als eigener Skill, falls du die schwere Suite unabhängig vom Build
  neu fahren willst (aktuell macht `feature-build` das am Ende selbst).
- **Stop-Hook**, der beim Sitzungsende offene `[?]`-Tasks der aktiven Ledger auflistet.
- **Feature-Issue-Template** in `.github/ISSUE_TEMPLATE/`, falls du doch pro Feature ein
  Tracking-Issue willst (aktuell bewusst lokale Ledger).

## Grenzen & bewusste Entscheidungen

- **VMs kosten.** Der Build-Loop fährt die schwere Suite genau einmal am Ende (deine Wahl
  „Auto-VM-Suite"). Die Boxen tragen eine Frist und sterben beim nächsten `vm.py`-Aufruf
  danach; trotzdem prüft der Loop hinterher `python3 scripts/vm/vm.py list` auf Leichen —
  die Liste endet mit Exit 74, wenn auf dieser Lane etwas läuft, das niemand beansprucht.
- **Plattform-Code** (Windows-Agent, RDP/SSH pro OS) wird laut CLAUDE.md manuell verifiziert
  — solche Tasks markiert `/feature-plan` als `[?]` bzw. mit manuellem Verify-Schritt.
- **Kein Ersatz für Review.** Das Design-Gate gibt Kevin frei (kleine Fund-Pakete die
  Aufsichts-Session), den PR prüft und merged die Aufsichts-Session, Regel-PRs Kevin
  (CLAUDE.md §2); der Loop bereitet vor.
- Es gilt weiterhin **`CLAUDE.md`** (Surgical Changes, Doku-Pflege, Conventional Commits,
  SPDX, Test-DoD) und **`CONTRIBUTING.md`**. Dieses Dokument beschreibt nur, _wie_ die Arbeit
  fließt — nicht neue Regeln.
