<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stufe 7b — der Worker bringt ein Ledger bis PR-fertig: Ebene 3, Heavy aus dem Loop, Übergabe

Roadmap: R-0010 (Teil 7b), R-0175, R-0177, R-0178 · Stand: main@bf9cee5e, Stufe 7a gebaut auf
`harness/stufe-7a@47dc4db6` (lokal, ungepusht; T10–T13 offen) — **alle Zeilenangaben zu 7a-Dateien beziehen sich auf
47dc4db6 und werden nach dem 7a-Merge neu gegrept** · Geplant 2026-10-05 von Worker A für die Aufsicht
(adminhelper-ac); Entscheidungen E1–E10 der Aufsicht 2026-10-05, E4 offen für Kevin · gebaut wird erst nach dem
Pilot-Lauf von 7a (E9)

## Problem / Motivation

Seit 7a baut `scripts/dev/ledger-loop.sh` ein freigegebenes Ledger Task für Task als `adminhelper-runner`. Am Ende
schreibt er heute den PR-Text und ein Bundle und hört auf (`handover`, `ledger-loop.sh:717`). Was zwischen „alle
Tasks zu“ und „PR offen“ liegt, macht weiter eine interaktive Session von Hand:

- **Keiner liest den ganzen Branch.** Die Reviewer von 7a sehen je eine Task. Wechselwirkungen zwischen Tasks,
  Partnerstellen und Lücken über Task-Grenzen fallen erst in Kevins Review auf. Das Roadmap-Dokument nennt die
  fehlende Prüfung „Ebene 3, Merge-Readiness“ (§10.2).
- **Heavy fährt die Aufsicht.** Ein Ledger mit `Heavy: linux-full` endet im Loop mit dem Vermerk
  „Heavy offen — fährt die Aufsicht“ (`ledger-loop.sh:721–723`), und jemand muss eine VM leasen, `run.sh integration`
  fahren und das Ergebnis in den PR tragen. `heavy.sh` kennt heute nur `all|capstone|weekly`
  (`scripts/tests/heavy.sh:64`). Der Schritt steht in `feature-build` als Prosa (`SKILL.md:249–272`).
- **Die Übergabe ist Handarbeit.** Bundle holen, Worktree anlegen, `origin/main` mergen, Schnellsuite, PR-Text,
  Push, Draft-PR, CI begleiten: sechs Handgriffe, die jedes Mal gleich sind und von denen keiner als Skript existiert
  (kein Skript ruft `gh pr create`, `gh run watch` oder `gh run rerun`).
- **Drei Reste aus 7a:** Nach Runde 2 gibt es keinen geregelten Weg, wenn sie belegte Funde fand und die behoben sind
  (R-0175). Das r1-Verdict, das Runde 2 als `--prior` liest, ist eine Datei in der Lane (R-0177). Ein Reviewer, der in
  `task-close` ins Nutzungslimit läuft, endet als `stop: infra` statt `usage-limit` (R-0178).

## Ziel & Nicht-Ziele

Ziel:
- **Ebene 3 im Loop:** Nach der letzten Task startet der Loop einen Branch-Review als eigenen Prozess. Ein zweiter
  Prozess prüft dessen Funde adversarial. Bestätigte Funde in Branch-Dateien werden Fix-Tasks (E4, Empfehlung).
- **Heavy aus dem Loop:** `heavy.sh gate --for <ledger>` fährt `Heavy: linux-full` auf einer Pool-VM, mit dem Token
  des Runners. Derselbe Aufruf ersetzt interaktiv den Prosa-Schritt in `feature-build`.
- **Sessions ohne Hypervisor:** Nur der Heavy-Schritt sieht das Proxmox-Token des Runners. Bau-, Review- und
  Ebene-3-Sessions bekommen weder Token noch VM-Verben.
- **Übergabe in Kevins Session:** `lane.sh pr <slug> --bundle <datei>` macht aus dem Bundle einen geprüften,
  gemergten Branch samt PR-Text und **druckt** Push- und PR-Befehl. `lane.sh watch-ci <slug>` begleitet die CI.
- **7a-Reste:** R-0175 (Kevins Regel vom 2026-10-05: eine frische Review-Serie), R-0177, R-0178, dazu das Abbauen der
  Runner-Lane nach der Übergabe.

Nicht-Ziele (7c oder eigene Zeilen):
- `Heavy: scenario …` (Capstone, Multibox) aus dem Loop und die **Boundary-Regel** des Roadmap-Dokuments
  (Risikopfad ⇒ Capstone): sieben Boxen, dem Host fehlten am 2026-09-25 rund 7 GB RAM, und D21 verlangt Aufsicht. In 7b
  endet ein solches Ledger als `bereit*` mit Vermerk.
- Skill-Umbenennung (`feature-*` → `/spec /build /audit`) und das Verb `/build pr|ci`: Die Verbliste in CLAUDE.md
  ist Kevins Datei. 7b liefert die Skripte, das Verb kommt mit der Umbenennung.
- `roadmap.py next|stats` aus `state.json` und `--queue`: erst mit Daten aus Pilot-Läufen. Entscheidung B von 7a
  (Kevins Liste, der Loop liest die Roadmap nie) bleibt.
- Fixes für rote CI aus dem Loop: In 7b baut sie eine interaktive Session.
- R-0154.3 (eigene Probe-DB): Im Loop laufen Bau-Verify, Probe und Abschluss strikt nacheinander auf der Runner-DB,
  dort gibt es keinen Konflikt. R-0151.3 (Laufzeit der Verträge): erst messen. Beide bleiben Roadmap-Zeilen.
- Ein zweiter Worker (D16), Windows (Stufe 12).

## Betroffene Komponenten & Dateien

Alles Harness (Entscheidung G von 7a: interaktiv gebaut, nie vom Loop).
- `scripts/tests/heavy.sh` (+ `heavy_test.sh`): Modus `gate --for <ledger>`.
- `scripts/dev/ledger-loop.sh` (+ `scripts/tests/ledger_loop_test.sh`): Ablauf am Ledger-Ende, 7a-Reste.
- `scripts/dev/review-run.sh`, `scripts/dev/review-agent.md` (+ `review_run_test.sh`): Modi `--branch` und
  `--confirm`; neu `scripts/dev/review-confirm.schema.json` (ohne SPDX-Kopf wie die beiden anderen Schemas, Eintrag in
  `scripts/dev/harness-paths.txt`).
- `scripts/dev/ledger.sh` (+ `ledger_test.sh`, `tasks/README.md`): `new-task` mit Feldern, Abschnitt `## Abschluss`.
- `scripts/dev/runner-env.sh`, `scripts/dev/runner-setup.sh` (+ `runner_setup_test.sh`): Hypervisor-Ziel aus der
  root-eigenen Datei, VM-Schlüssel, frpc-Sidecar im Klon.
- `scripts/dev/runner-settings.json` (+ `hooks_test.sh`): keine VM-Verben mehr für Modell-Sessions.
- `scripts/dev/runner-redteam.sh` (+ `redteam_test.sh`): Probe 4 erweitert.
- `scripts/dev/lane.sh` (+ `scripts/tests/lane_test.sh`): `pr`, `watch-ci`.
- `.claude/skills/feature-build/SKILL.md` (+ `skill_consistency_test.sh`): Schritt 3 über `heavy.sh gate`, Übergabe
  über `lane.sh pr`.
- Doku: `AUTONOMOUS.md`, `DEVELOPMENT.md`, `docs/developer/cicd.html` + `docs/en/developer/cicd.html`, `CHANGELOG.md`.

Kein Produktcode, keine API, keine Migration, kein Wire-Format.

## Design

### Ablauf am Ledger-Ende (E2)

Heute (`build_ledger`, `ledger-loop.sh:842`): letzte Task zu ⇒ `bereit` ⇒ `handover`. Neu:

1. Die letzte Task schließt wie bisher. `task-close` setzt `bereit` (`task-close.sh:483–486`); das passt zur Bedeutung
   in `tasks/README.md` („alle Tasks sind zu; der Abschluss … und der PR stehen aus“).
2. **Ebene 3** (unten). Legt sie Fix-Tasks an, setzt der Loop `aktiv`, baut sie über den normalen Task-Weg, und die
   letzte setzt wieder `bereit`. Ebene 3 läuft danach nicht noch einmal.
3. **Heavy** (unten): zuletzt, damit es den Endstand prüft. Das Roadmap-Dokument hatte Heavy vor Ebene 3.
4. **Übergabe** wie in 7a (`handover`: PR-Text, Bundle, `git bundle verify`), danach `lane.sh done <slug>` aus dem
   Klon: VMs der Lane weg, Worktree weg, Branch bleibt (nicht gemergt).

Die Ergebnisse von Ebene 3 und Heavy stehen als Zeilen unter `## Abschluss` im Ledger. Der Loop schreibt sie über
`ledger.sh` als eigenen Ledger-Commit. So reisen sie mit dem Bundle, und `review.sh pr-body` rendert sie. Ergebnisse im
Loop: `bereit`, `bereit*` (Heavy offen: `scenario`/`windows`, keine Kapazität, zweimal Exit 74) oder `blockiert (…)`.

### Ebene 3 — Branch-Review und Bestätigung (E3)

- **Review:** `review-run.sh --branch <ledger> --range origin/main...HEAD` ist ein eigener Prozess in derselben Form
  wie der Task-Reviewer von 6b: `--setting-sources ""`, `review-settings.json`, Agent als `--agents`-JSON,
  StructuredOutput, Prompt über stdin. Der Prompt enthält Ledger, Spec-Pfad, Branch-Diff, die Review-Zeilen der Tasks
  und den Auftrag, Wechselwirkungen, Partnerstellen, Doku-Paare und Lücken über Task-Grenzen zu suchen. Das Schema ist
  `review-output.schema.json` (Funde `blocker|wichtig|nit`).
  - Modell immer Opus; `xhigh` bei Risikopfad im Branch-Diff (`review.sh risk --range origin/main...HEAD`), sonst
    `high` (Roadmap-Dokument §10.2).
  - Ebene 3 läuft **immer**, auch bei Kurz-Ledgern: Im Loop liest sonst niemand den ganzen Branch.
- **Bestätigung:** `review-run.sh --confirm <branch-verdict>` ist ein zweiter, frischer Prozess, ebenfalls Opus. Er
  bekommt nur die Funde `blocker|wichtig` und den Diff und versucht jeden zu widerlegen. Je Fund antwortet er
  `CONFIRMED` (mit Datei:Zeile und Begründung) oder `PLAUSIBLE` (nicht belegt). Das Schema ist
  `review-confirm.schema.json`. Funde `nit` gehen ohne Bestätigung in den PR-Text.
- **Deckel** als Flags des Loops: `--merge-budget 15` und `--confirm-budget 10` (Summe 25 $ wie im
  Roadmap-Dokument), Turns und Timeout je Prozess. Die Kosten zählen in `--max-budget-usd` des Laufs.
- **Dateien:** Vor dem Review schiebt der Loop alte `branch.*`-Dateien beiseite (R-0170: Code einer Session kann
  `.ah-out/review/` schreiben). Die Verdicts liest er in den Speicher, bevor eine Fix-Session läuft.

### Funde aus Ebene 3 (E4 — Empfehlung; Kevins Entscheidung am Gate)

- Ein `CONFIRMED`-Fund in einer Datei, die der Branch schon ändert (`git diff --name-only origin/main...HEAD`) und
  die kein Harness-Pfad ist, wird eine Fix-Task unter `## Review-Funde Abschluss`, angelegt mit
  `ledger.sh new-task … --component --files --verify --change`. Die Komponente kommt aus dem Pfad wie bei `verify.sh`.
  Für Pfade ohne Komponente (`docs/`, `CHANGELOG.md`) gilt die Komponente der letzten Task. Der Fund-Text kommt einzeilig,
  druckbar und gekürzt hinein. Der Ledger-Commit des Loops prüft, dass der Diff genau der eine neue Block ist, und der
  pre-commit-Hook fährt `review.sh sec`.
- Höchstens **3** solche Tasks und **eine** Fix-Runde. Mehr Funde, ein Fund außerhalb der Branch-Dateien oder auf
  einem Harness-Pfad, oder eine Fix-Task, die selbst `[?]` wird ⇒ `blockiert (Ebene 3)` mit der Liste.
- `PLAUSIBLE` und `nit` landen unter `## Abschluss` und damit im PR-Text. Kandidaten außerhalb des Umfangs landen im
  Summary unter „Roadmap-Kandidaten“: Der Runner schreibt keine Roadmap, die Aufsicht trägt ein.
- **Restrisiko, bewusst:** Aus einem Modell-Fund wird ohne Menschen eine Modell-Task. Begrenzt wird das durch den
  zweiten Prozess, die Branch-Dateien, den Deckel 3, die eine Runde und die Gates von `task-close` (Review je
  Fix-Task, Diff-Scan, Scope, sec). Die Alternative steht unter „Offene Fragen“.

### Heavy aus dem Loop (E5)

`bash scripts/tests/heavy.sh gate --for tasks/<slug>.md` liest `Heavy:` aus dem Kopf:
- `none` ⇒ „nichts zu fahren“, Exit 0, keine VM. Der Loop ruft es dafür gar nicht erst auf.
- `linux-full` ⇒ zuerst `vm.py doctor --roles desktop`; fehlt Kapazität ⇒ `UNVERIFIED (capacity)`, Exit 74.
  Dann `warm.sh desktop` → `iter.sh integration --strict`, und `iter.sh e2e --strict` nur, wenn der Branch-Diff
  `apps/web/` oder `apps/desktop/` berührt (die Regel aus `feature-build`, jetzt als Code).
  - PASS ⇒ die Box geht weg.
  - FAIL ⇒ die Box bleibt mit ihrer Frist, zum Ansehen per `vm.py ssh`.
- `scenario …` und `windows` ⇒ `UNVERIFIED (Heavy: … — fährt die Aufsicht)`, Exit 74, keine VM (7c bzw. Stufe 12).
- Bericht unter `$AH_OUT_DIR/gate/<slug>-<stempel>/report.md`, erste Zeile `PASS|FAIL|UNVERIFIED (<grund>)`,
  Schlusszeile `heavy.sh[gate]: <VERDICT>`. **Kein** Schreiben nach `tasks/private`, keine Roadmap-Zeile, keine
  `history.csv`, kein `--notify`: Der Runner hat das private Repo nicht, und ein Gate ist kein Wochenlauf.

Im Loop: Nach `lane_harness_changed` (ein Harness-Pfad der Lane gleich `origin/main`, also gleich dem Klon) ruft der
Loop das `heavy.sh` **der Lane** auf, wie schon `task-close.sh`: `warm.sh` und `iter.sh` syncen den Checkout, in dem
sie liegen. Das Token hat nur dieser Aufruf (unten). Ergebnisse:
- 0 ⇒ weiter zur Übergabe.
- 1 ⇒ `blockiert (heavy rot)` mit Report-Pfad, ohne Auto-Fix.
- 74 ⇒ einmal wiederholen, dann `bereit*`, und der PR-Text sagt „Heavy offen — fährt die Aufsicht (<grund>)“.

Interaktiv ersetzt `heavy.sh gate --for` den Prosa-Schritt 3 in `feature-build`. Der Multibox-Lauf bei `scenario`
bleibt dort eine Frage an Kevin.

### Sessions ohne Hypervisor (E6)

Ziel-Design:
- Das Proxmox-Token und der VM-Schlüssel erreichen nur `heavy.sh gate`.
- Jede Modell-Session startet ohne `AH_PVE_*` und `AH_VM_*`: die Bau-Session, der Task-Reviewer (`review-run.sh`, auch
  in Kevins Sessions, deren Umgebung die Werte trägt) und die beiden Ebene-3-Prozesse.
- `runner-settings.json` verliert die Allow-Regeln für `vm.py clone|wait|ssh|sync|run|pull|snap|rollback|delsnap|
  destroy|reap|list|doctor`, `warm.sh`, `iter.sh` und `reap.sh` (`:70–72`, `:94–106` auf 47dc4db6). Eine Bau-Session
  braucht keine VM.
- Das Red Team prüft beides: Eine Modellprobe sieht kein `AH_PVE_*`, und die Settings erlauben kein VM-Verb.
- Die Bau-Session deckt 7a selbst ab (Voraussetzung); 7b zieht den Rest nach.

### Hypervisor-Ziel des Runners

`runner-env.sh` liest heute alle `AH_PVE_*` aus der Runner-eigenen `pve.env` (`runner-env.sh:135–154`). Die Vorlage
nennt nur URL, Node und Token (`runner-setup.sh:537–543`). Für `vm.py clone` fehlen Pool, Storage, Bridge, CA und der
VMID-Bereich, und `vm_load_env` liest `settings.local.json` nicht mehr, sobald `AH_PVE_URL` gesetzt ist
(`scripts/vm/lib.sh:27`). Neu:
- Das **Ziel** (URL, Node, Pool, CA, Storage, Bridge, VMID-Bereich) kommt aus der root-eigenen
  `/usr/local/lib/adminhelper-dev/pve-target.env`, die `runner-setup.sh` schon für Probe 4 schreibt
  (`runner-setup.sh:363–389`) und um Storage, Bridge und VMID-Bereich erweitert. So kann Code einer Session den Loop
  nicht auf einen anderen Hypervisor lenken.
- Aus `pve.env` liest `runner-env.sh` nur noch das **Token**. Eine `pve.env` mit Zielzeilen ist eine Warnung, kein
  Wert.
- `runner-setup.sh` legt den VM-Schlüssel des Runners an (`~/.config/adminhelper/vm_ed25519`, 0600, der Default von
  `vm.py:78`; `vm.py clone` spielt den öffentlichen Teil per cloud-init ein, `vm.py:928`, `:948`).
- `runner-setup.sh` legt außerdem den frpc-Sidecar in den Klon, mit derselben gepinnten Version und demselben Weg wie
  `scripts/vm/bootstrap_linux.sh:212–215`. Ein Sync aus einem Checkout ohne Sidecar kostet die Box ihren Sidecar
  (beobachtet 2026-09-25 beim Wochenlauf aus einem Worktree; ob der Delete-Sync die Ursache ist: **nicht verifiziert**).
- Ob `rsync` und `ssh` für den Runner auf dem PATH liegen, prüft `runner-setup.sh` mit.

### Übergabe in Kevins Session (E7)

`bash scripts/dev/lane.sh pr <slug> --bundle <datei>` im Haupt-Checkout:
1. `git fetch origin`. Die Bundle-Datei wird in den eigenen `.ah-out/` kopiert: nur Lesen einer fremden Datei, kein
   fremdes Repo. Ob der Fetch auch direkt aus der Runner-Datei ohne `safe.directory` ginge, wird damit egal.
2. `git bundle verify` auf der Kopie: Fehlen die Voraussetzungs-Commits (Doku: „checking that the prerequisite commits
   exist“), endet es hier.
3. `git fetch <kopie> feature/<slug>:feature/<slug>`, nur fast-forward (der lokale Plan-Branch ist Vorfahr), nie
   `--force`.
4. `lane.sh new <slug>`, im Worktree `git merge origin/main` (nicht `rebase`, wie 7a). Ein Konflikt ⇒ `merge --abort`,
   Exit 3, „von Hand lösen“.
5. `bash scripts/tests/run.sh quick --strict` im Worktree; rot ⇒ Exit 1.
6. `review.sh pr-body tasks/<slug>.md` neu **in Kevins Checkout** (nie den Text aus dem Runner-Verzeichnis
   übernehmen) nach `<lane>/.ah-out/pr-body.md`.
7. Am Ende **druckt** es `git -C <lane> push -u origin feature/<slug>:feature/<slug>` und
   `gh pr create --draft --base main --head feature/<slug> --title "…" --body-file <lane>/.ah-out/pr-body.md`. Es führt
   keinen der beiden aus: Push und PR bleiben sichtbare Einzelbefehle (CLAUDE.md §2).

`bash scripts/dev/lane.sh watch-ci <slug>`: die Läufe zu `HEAD` von `feature/<slug>` (`gh run list --branch
feature/<slug> --json databaseId,headSha,status,conclusion,workflowName`), je Lauf `gh run watch <id> --exit-status
--compact`. Ein roter Lauf ⇒ höchstens zweimal `gh run rerun <id> --failed`, das Log von `gh run view <id>
--log-failed` nach `.ah-out/`.
- Exit 0 grün.
- Exit 1 rot.
- Exit 3 grün erst nach einem Rerun = **flaky, nicht PASS** (CLAUDE.md §6).
- Lang laufend, also in tmux mit Wächter (D21, `/test`).

### 7a-Reste im Loop (E8)

- **R-0175, Kevins Regel vom 2026-10-05:** Endet Runde 2 einer Task mit `request_changes` über belegte Funde, und die
  Fix-Session behebt sie, dann startet **höchstens einmal je Task** eine frische Review-Serie. r1/r2 gehen unter festen
  Namen beiseite (`archive_reviews`, `:511`, kein Glob), dann Runde 1 neu. Danach ⇒ `[?]`.
- **R-0177:** Der Loop hält den sha256 des r1-Verdicts nach dem Abschluss von Runde 1 im Speicher und vergleicht ihn
  vor dem Abschluss von Runde 2. Abweichung ⇒ `stop: harness-modified`.
- **R-0178:** Das Close-Log wird nach demselben Limit-Text durchsucht wie die Session (`session`, `:589`). Ein Treffer
  ⇒ `usage-limit` mit Reset-Zeit statt zweimal 74 ⇒ `infra`.
- **Lane abbauen** nach verifiziertem Bundle (oben, Schritt 4 des Ablaufs).

## Kevins Handarbeit

Vor dem Bau (Voraussetzungen):
1. Stufe 7a gemergt, einschließlich ihrer Nachbesserungen (die Bau-Session ohne Hypervisor-Werte), und der 7a-Pilot
   gefahren (E9). Seine Messwerte (Verweigerungen, Kosten und Dauer je Task, Form der Fehler-JSON, Bundle-Übergabe)
   gehen vor dem Bau in die Deckel und in die Übergabe dieses Plans.

Nach dem Merge von 7b, vor dem ersten Loop-Lauf mit `Heavy: linux-full`:
2. `sudo bash scripts/dev/runner-setup.sh`: schreibt die erweiterte `pve-target.env` (Storage, Bridge,
   VMID-Bereich), legt den VM-Schlüssel des Runners und den frpc-Sidecar im Klon an.
3. `pve.env` des Runners: nur noch die Token-Zeile. Die ACLs des Runner-Tokens decken Clone aus den Templates, VMs im
   Pool, Storage und Bridge ab. Die Probe ist `sudo -u adminhelper-runner bash -lc '. /srv/ah/repo/scripts/dev/runner-env.sh
   && python3 /srv/ah/repo/scripts/vm/vm.py doctor --roles desktop'`; ihre Zeile `privileges` muss `ok` sagen.
4. `sudo -u adminhelper-runner git -C /srv/ah/repo pull --ff-only` und das Red Team als Runner. Neu sind die Proben
   „`vm.py doctor` mit dem Runner-Token: privileges ok“, „Modell-Session sieht kein `AH_PVE_*`“ und „kein VM-Verb in den
   Settings“.
5. Optional eine CLAUDE.md-Zeile (§6, CI begleiten) zu `lane.sh watch-ci`. Das ist Kevins Harness-Datei.
6. **Pilot 2:** ein freigegebenes Ledger mit `Heavy: linux-full` durch den Loop, überwacht (D21). Danach prüfen:
   `## Abschluss` mit Ebene-3- und Heavy-Zeile, `vm.py list` leer, `lane.sh pr` holt das Bundle, `watch-ci` begleitet
   die CI.

## Externe Integrationen

- **gh CLI** (cli.github.com/manual, gelesen 2026-10-05):
  - `gh run watch` hat `--exit-status` („Exit with non-zero status if run fails“) und `--compact`; den genauen Exit-Wert
    nennt die Doku nicht, geprüft wird nur ≠ 0.
  - `gh run rerun --failed` („Rerun only failed jobs, including dependencies“).
  - `gh run list` mit `--branch`, `--limit`, `--json` und den Feldern `databaseId`, `headSha`, `status`, `conclusion`,
    `workflowName`.
  - `gh run view --log-failed`.
  - `gh pr create --draft --body-file` wird nur gedruckt, nie aufgerufen.
- **git bundle** (git-scm.com/docs/git-bundle): Ein Bundle `old..new` verlangt `old` im Empfänger; `verify` prüft das
  und listet fehlende Commits; `git fetch <bundle> <src>:<dst>` ist dokumentiert.
- **Claude Code CLI:** dieselbe Aufrufform wie der Task-Reviewer von 6b (`review-cli-probe.sh`, CLI-Pin
  `runner-claude.version`); `--max-budget-usd`, `--max-turns`, `--output-format json`, `--json-schema` über
  StructuredOutput. Neu ist nur der Prompt. **Nicht verifiziert:** wie lange ein Opus-xhigh-Review über einen
  Branch von 10–15 Tasks braucht und was er kostet; der Pilot 2 misst es.
- **Proxmox:** nichts Neues; `vm.py doctor|clone|destroy` wie heute, mit dem Token des Runners.

## Trade-offs & Alternativen

- **Heavy nach Ebene 3, nicht davor:** Fix-Tasks aus Ebene 3 würden einen frühen Heavy-Lauf entwerten. Dafür kommt ein
  roter Heavy-Lauf erst nach dem teuren Review.
- **Eigene Ebene-3-Maschinerie statt `/code-review` in `claude -p`:** Ob `/code-review` ohne Setting-Quellen zur
  Verfügung steht, ist unverifiziert, und seine Ausgabe ist nicht schemagebunden. Dafür fehlt der Vergleich mit
  `/code-review`; der passt zu Stufe 10 (harness_eval).
- **Zwei Prozesse statt einem:** Ein Reviewer, der seine eigenen Funde bestätigt, bestätigt sie. Der zweite Prozess
  kostet bis zu 10 $.
- **`lane.sh pr` druckt statt pusht:** ein Handgriff mehr, dafür bleiben Push und PR sichtbare Einzelbefehle.
- **PR-Text neu in Kevins Checkout:** Der Text des Runners wäre Code-beeinflussbar (Runner-Rechte). Die Ergebnisse von
  Ebene 3 und Heavy kommen über das Ledger, das durch Bundle, Merge und `review.sh sec` gegangen ist.
- **`linux-full` ja, `scenario` nein:** eine Box ist planbar, sieben sind es heute nicht (RAM). Die Boundary-Lehre
  wartet bis 7c.

## Risiken & Rollback

- **Kosten:** Ebene 3 kostet bis zu 25 $ je Ledger, ein Fix-Durchgang bis zu 3 Tasks mehr. Die Deckel sind Flags;
  `--max-budget-usd` des Laufs bleibt die Obergrenze.
- **VM-Leck:** Der Loop least jetzt selbst. PASS räumt ab, FAIL behält die Box mit Frist, und `lane.sh done` zerstört
  die VMs der Lane nach der Übergabe. Nach jedem Lauf `vm.py list` (Aufsicht, D21).
- **Prompt-Injection über Funde:** Fund-Text wird Ledger-Text. Er wird einzeilig, gekürzt und druckbar gemacht und
  geht durch `review.sh sec`. Fix-Tasks dürfen nur Branch-Dateien berühren.
- **Rollback:** Ohne die neuen Flags verhält sich nichts anders; `git revert` der 7b-Commits und ein Setup-Lauf
  stellen 7a her. `heavy.sh all|capstone|weekly` bleiben unverändert.

## Doku-Impact

- `AUTONOMOUS.md`: Abschnitt „Der Worker“ (Ablauf am Ledger-Ende, Ebene 3, Heavy, Übergabe). Die Ebenen-Übersicht
  wird auf drei Ebenen korrigiert; heute steht dort „Zwei Review-Ebenen“ (`AUTONOMOUS.md:80`).
- `DEVELOPMENT.md`: `lane.sh pr`/`watch-ci`, Hypervisor-Setup des Runners.
- `docs/developer/cicd.html` + `docs/en/developer/cicd.html`: Worker-Abschnitt.
- `CHANGELOG.md`.
- CLAUDE.md bleibt Kevins (Handarbeit 5).

## Offene Fragen (Kevins Gate)

1. **E4 — Fix-Tasks aus Ebene 3 automatisch?** Empfehlung (oben): `CONFIRMED` in Branch-Dateien ⇒ höchstens 3
   Fix-Tasks, eine Runde, sonst `blockiert`. **Alternative:** jeder `CONFIRMED`-Fund ⇒ `blockiert (Ebene 3)` mit
   der Liste, die Aufsicht entscheidet. Kein Restrisiko, aber eine Runde bei Aufsicht oder Kevin je Ledger mit
   Fund, meist am Morgen nach dem Lauf.
2. Am Gate änderbar, von der Aufsicht als Empfehlung übernommen: Heavy nach Ebene 3; FAIL behält die Box; e2e nur
   bei `apps/web/`- oder `apps/desktop/`-Diff; zwei Reruns in `watch-ci`; Deckel 15 $ + 10 $.

## Ausblick 7c

Capstone und `scenario` aus dem Loop samt Boundary-Regel (sobald der Host die Kapazität hat), Skill-Umbenennung mit
dem Verb `/build pr|ci|status`, `roadmap.py next|stats` aus `state.json` und `--queue`, CI-Fixes aus dem Loop.
