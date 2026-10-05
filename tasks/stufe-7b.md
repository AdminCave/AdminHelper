<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stufe 7b — der Worker bringt ein Ledger bis PR-fertig: Ebene 3, Heavy aus dem Loop, Übergabe — Task-Ledger
Status: freigegeben · Branch: harness/stufe-7b · Commit-Granularität: pro Task · Review: auto · Modell: Opus
Freigabe: Kevin, 2026-10-05 (Stufen-Plan 7b „Freigeben“; E4: Fix-Tasks aus Ebene 3 automatisch, eng begrenzt; Proxmox-Token: Pilot ohne Token, dann 7b), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: docs/features/stufe-7b.md (Roadmap R-0010, R-0175, R-0177, R-0178)
Heavy: linux-full — einmal echt am Ende: `bash scripts/tests/heavy.sh gate --for tasks/stufe-7b.md` (dieses Ledger, eine Pool-VM, `run.sh integration`), interaktiv in tmux mit Wächter (D21). Der Lauf als Runner kommt mit Pilot 2 (Spec, „Kevins Handarbeit“ 6). Alle Task-Tests sind hermetisch (claude-, gh-, vm- und heavy-Stubs).
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Voraussetzungen (vor dem Start prüfen, sonst nicht anfangen): Stufe 7a gemergt samt Nachbesserungen (die Bau-Session startet ohne Hypervisor-Werte) **und** ihr Pilot gefahren (E9). Die Messwerte des Piloten (Verweigerungen, Kosten und Dauer je Task, Form der Fehler-JSON, Bundle-Übergabe) stehen vor T1 in der Spec; Deckel und `lane.sh pr` richten sich danach.

Geplant 2026-10-05 von Worker A für die Aufsicht (adminhelper-ac). Entscheidungen E1–E10 der Aufsicht vom 2026-10-05,
E4 (Fix-Tasks aus Ebene 3) ist Kevins Entscheidung am Gate (Spec, „Offene Fragen“). Zeilenangaben zu 7a-Dateien gelten für
`harness/stufe-7a@47dc4db6` (lokal, ungepusht) — **nach dem 7a-Merge neu greppen**, vor jeder Task an Symbolen
orientieren, nicht an Zeilen. Bau interaktiv (Harness-Pfade, Entscheidung G von 7a), keine Lane. Jede neue Datei unter
`scripts/dev/` kommt in derselben Task nach `scripts/dev/harness-paths.txt`, jeder neue Test in
`AH_SCRIPT_TESTS_DEFAULT` (`scripts/tests/run.sh:586`). Kein Test ruft die echte CLI, `gh` oder Proxmox: Stubs nach
dem Muster von `review_run_test.sh` (claude), `heavy_test.sh` (`AH_HEAVY_WRAPPERS`) und `lane_test.sh` (Recorder).
Nie `sudo`, nie ein Lauf als `adminhelper-runner` und kein echter Red-Team-Lauf im Bau; den fährt Kevin nach dem Merge
(Spec, „Kevins Handarbeit“ 4).

### T1 — `heavy.sh gate --for <ledger>`: `Heavy:` aus dem Kopf, `linux-full` auf einer Pool-VM  [ ]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Änderung: Neuer Modus `gate` (Usage `heavy.sh:8`, Parser `:48–64`) mit Pflicht-Flag `--for tasks/<slug>.md` (Form wie
der Slug-Regex des Loops, `ledger-loop.sh:178`). Liest `Heavy:` aus dem Kopf (bis zur ersten `###`-Zeile, Wert bis ` — `):
- `none` ⇒ ein Satz, Exit 0, kein VM-Aufruf.
- `linux-full` ⇒ zuerst `vm.py doctor --roles desktop`; fehlende Kapazität ⇒ `UNVERIFIED (capacity)`, Exit 74. Dann
  `warm.sh desktop` → `iter.sh integration --strict`, und `iter.sh e2e --strict` nur, wenn `git diff --name-only
  origin/main...HEAD` etwas unter `apps/web/` oder `apps/desktop/` nennt.
  - PASS ⇒ die Box geht per `vm.py destroy` weg, aber nur eine, die dieser Lauf selbst angelegt hat (eine schon
    laufende Warm-Box aus `.vm/warm.env` bleibt).
  - FAIL ⇒ die Box bleibt.
- `scenario …`, `windows`, ein fehlender oder unbekannter Wert ⇒ `UNVERIFIED (Heavy: … — fährt die Aufsicht)`,
  Exit 74, keine VM.

Bericht unter `$AH_OUT_DIR/gate/<slug>-<stempel>/report.md` (erste Zeile `PASS|FAIL|UNVERIFIED (<grund>)`), Schlusszeile
`heavy.sh[gate]: <VERDICT>`. Im Gate laufen weder `write_history` (`:898`), `commit_private` (`:993`), `roadmap_append`
(`:597`) noch `notify` (`:978`): kein Schreiben nach `tasks/private`.

Tests mit `AH_HEAVY_WRAPPERS`-Stubs: je Heavy-Wert der Weg und der Exit; e2e nur mit Diff unter `apps/web|apps/desktop`;
das private Verzeichnis (`AH_PRIVATE_DIR`) bleibt unberührt; PASS räumt die eigene Box ab, FAIL und eine fremde Warm-Box
bleiben. Rot vorher: `gate` ist kein Modus (Usage, Exit 2).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T13)

### T2 — Runner: Hypervisor-Ziel aus `pve-target.env`, Token aus `pve.env`, VM-Schlüssel, Sidecar  [ ]
Komponente: scripts · Dateien: scripts/dev/runner-env.sh, scripts/dev/runner-setup.sh, scripts/tests/runner_setup_test.sh, scripts/tests/hooks_test.sh
Änderung:
- `runner-env.sh` (`:135–154`) übernimmt aus `pve.env` nur noch `AH_PVE_TOKEN`; eine Zielzeile dort ist eine Warnung auf
  stderr, kein Wert. Das Ziel (`AH_PVE_URL`, `_NODE`, `_POOL`, `_CA`, `_STORAGE`, `_BRIDGE`, `_VMID_RANGE`) liest es aus
  `${AH_PVE_TARGET:-/usr/local/lib/adminhelper-dev/pve-target.env}`, gelesen wie die Token-Dateien, nicht gesourct.
  `AH_PVE_TARGET` ist Test-Override; im autonomen Lauf wird er ignoriert, wie `CLAUDE_BIN` in `review-run.sh`.
- `runner-setup.sh` schreibt in `pve-target.env` (`:363–389`) zusätzlich Storage, Bridge und VMID-Bereich.
- `runner-setup.sh` legt `~/.config/adminhelper/vm_ed25519` an (0600, `ssh-keygen -t ed25519 -N ''` als Runner; nur wenn
  er fehlt).
- `runner-setup.sh` legt den frpc-Sidecar `apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu` in den Klon,
  mit Version und Weg aus `scripts/vm/bootstrap_linux.sh:212–215` (nur wenn er fehlt).
- `runner-setup.sh` prüft `rsync` und `ssh` auf dem PATH des Runners.
- Die Vorlage von `pve.env` (`:537–543`) nennt nur noch die Token-Zeile.

Tests: `runner_setup_test.sh` (Dry-Run-Ausgabe nennt die neuen Schritte, eine vorhandene Datei bleibt). `hooks_test.sh`
deckt den Abschnitt zu runner-env ab: das Ziel kommt aus der Zieldatei, das Token aus `pve.env`, eine Ziel-URL in
`pve.env` ändert nichts, `AH_PVE_TARGET` zählt bei `AH_AUTONOMOUS=1` nicht.
Rot vorher: eine `AH_PVE_URL=` in `pve.env` setzt heute das Ziel.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T13)

### T3 — Modell-Sessions ohne Hypervisor: keine VM-Verben, Reviewer ohne `AH_PVE_*`  [ ]
Komponente: scripts · Dateien: scripts/dev/runner-settings.json, scripts/tests/hooks_test.sh, scripts/dev/review-run.sh, scripts/tests/review_run_test.sh
Änderung:
- `runner-settings.json` verliert die Allow-Regeln für `vm.py doctor|clone|wait|ssh|sync|run|pull|snap|rollback|delsnap|
  destroy|reap|list`, `warm.sh`, `iter.sh` und `reap.sh` (`:70–72`, `:94–106`). Die Denys bleiben.
- `review-run.sh` startet die CLI mit `env -u` für jede gesetzte `AH_PVE_*`- und `AH_VM_*`-Variable. Das gilt auch in
  Kevins Sessions, deren Umgebung die Werte trägt.

Tests:
- `hooks_test.sh` (Abschnitt runner-settings.json): kein Allow mit `vm.py`, `warm.sh`, `iter.sh`, `reap.sh`. Die
  heutige Erwartung „allow: vm.py clone/destroy“ (`hooks_test.sh:1429` auf 47dc4db6) wird damit bewusst umgedreht:
  eine geänderte Erwartung in einem bleibenden Test, begründet durch E6.
- `review_run_test.sh`: der claude-Stub schreibt seine Umgebung; mit gesetztem `AH_PVE_TOKEN` und `AH_VM_SSH_KEY` beim
  Aufrufer fehlen beide im Stub.

Rot vorher: der Stub sieht heute `AH_PVE_TOKEN`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T13)

### T4 — Red Team: Probe 4 mit `vm.py doctor`, Modell-Session ohne `AH_PVE_*`, keine VM-Verben  [ ]
Komponente: scripts · Dateien: scripts/dev/runner-redteam.sh, scripts/tests/redteam_test.sh
Änderung: Probe 4 (`runner-redteam.sh:351–410` auf main) fragt zusätzlich `vm.py doctor --roles desktop` mit dem Token
des Runners. Die Zeile `privileges` muss `ok` sein (sonst FAIL); `capacity` ist `info`, denn RAM ist kein Rechte-Fund.
Zwei neue Prüfungen:
- In einer Modellprobe in der Form der Bau-Session (`--setting-sources user`, `dontAsk`) liefert `env` keine
  `AH_PVE_*`/`AH_VM_*`-Zeile; ein Treffer ist FAIL.
- Die Settings des Runners erlauben kein VM-Verb; ein Treffer ist FAIL.

Tests mit den Stubs von `redteam_test.sh`: je Probe ok und FAIL.
Rot vorher: die drei Prüfungen fehlen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T13)
Abhängt von: T2, T3

### T5 — `review-run.sh --branch`: Ebene 3 als Prozess  [ ]
Komponente: scripts · Dateien: scripts/dev/review-run.sh, scripts/dev/review-agent.md, scripts/tests/review_run_test.sh
Änderung: Neuer Modus `review-run.sh --branch <ledger> --range <a>...<b> [--budget <usd>]` neben dem Task-Modus, gleiche
Aufrufform (`--setting-sources ""`, `review-settings.json`, Agent als `--agents`-JSON, StructuredOutput, Prompt über
stdin).
- Der Prompt enthält das Ledger, den Spec-Pfad aus `Spec:`, `git diff <range>`, die neuen Dateien, die
  `Review:`-Zeilen der Tasks und den Auftrag: Wechselwirkungen und Partnerstellen über Task-Grenzen, Doku-Paare, Lücken
  zwischen Tasks, keine Wiederholung der Task-Reviews.
- Modell `opus`, Effort `xhigh`, wenn `review.sh risk --range <range>` xhigh sagt, sonst `high`; 100 Turns; Budget
  Default 15.
- Das Verdict geht nach `.ah-out/review/<slug>/branch.r1.verdict.json`: Schema `review-output.schema.json` plus die
  Felder des Runners (Range, Modell, Kosten). Exit wie im Task-Modus (0 · 2 · 74).
- `review-agent.md` bekommt einen Abschnitt „Branch-Modus“.

Tests mit dem claude-Stub: der Prompt trägt Range-Diff und Ledger; die Modellwahl folgt `risk`; das Budget-Flag erreicht
die CLI; eine Ausgabe außerhalb des Schemas ist 74. Rot vorher: `--branch` ist unbekannt (2).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T13)
Abhängt von: T3

### T6 — `review-run.sh --confirm`: Funde adversarial bestätigen  [ ]
Komponente: scripts · Dateien: scripts/dev/review-run.sh, scripts/dev/review-agent.md, scripts/dev/review-confirm.schema.json, scripts/dev/harness-paths.txt, scripts/tests/review_run_test.sh
Änderung: `review-run.sh --confirm <branch-verdict> --range <a>...<b> [--budget <usd>]` ist ein frischer Prozess, `opus`.
- Er bekommt nur die Funde `blocker|wichtig` (mit Index, Datei, Behauptung) und den Diff, nicht die Begründung des
  Reviewers. Er versucht jeden zu widerlegen.
- Antwort je Index: `CONFIRMED` (Datei, Zeile, Grund) oder `PLAUSIBLE` (Grund).
- Neues Schema `review-confirm.schema.json` (Draft-07 wie die beiden anderen, ohne SPDX-Kopf wie sie), Eintrag in
  `harness-paths.txt`. Ausgabe nach `branch.confirm.json`, Budget Default 10.
- Ohne Funde `blocker|wichtig` wird keine CLI gestartet; die Bestätigung ist leer.
- Ein Index, den es nicht gibt, oder ein fehlender Index ist 74.

Tests mit Stub: CONFIRMED/PLAUSIBLE landen je Index; `nit` erreicht den Prompt nicht; ohne Funde kein Aufruf; ein fremder
Index ist 74. Rot vorher: `--confirm` ist unbekannt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T13)
Abhängt von: T5

### T7 — `ledger.sh`: `new-task` mit Feldern und Abschnitt, `closing` für `## Abschluss`  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger.sh, scripts/tests/ledger_test.sh, tasks/README.md
Änderung:
- `new-task <ledger> --title "…"` bekommt optional `--section "<überschrift>"`, `--component`, `--files "<a, b>"`,
  `--verify "<befehl>"` und `--change "<text>"`. Sie füllen die Felder der Vorlage (`tasks/templates/task.md`) als Text
  über ENVIRON, wie `--title` heute (`ledger.sh:241–281`). `--section` legt `## <überschrift>` einmal an und hängt die
  Task darunter, vor `## Abschluss`.
- Neues Verb `closing <ledger> <key> "<zeile>"` schreibt oder ersetzt die Zeile `<key>: <zeile>` unter `## Abschluss`
  (legt den Abschnitt am Ende an). Schlüssel nur `Ebene 3`, `Ebene 3 Funde`, `Heavy`. Die Zeile wird einzeilig,
  druckbar und auf 400 Zeichen gekürzt (wie `oneline` in `task-close.sh`).
- `lint` kennt beides. `tasks/README.md` beschreibt die zwei Formen.

Tests: die Felder landen; Freitext mit `&`, `|`, `\`, Zeilenumbruch und Steuerzeichen bleibt eine Zeile Text;
`closing` ersetzt statt zu verdoppeln; ein unbekannter Schlüssel ist 2; `lint` grün auf dem Ergebnis.
Rot vorher: die Flags sind unbekannt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: tasks/README.md (ledger.sh-Abschnitt, im selben Commit)

### T8 — Loop: Ebene 3 am Ledger-Ende (E2, E3, E4)  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Änderung: In `build_ledger` (`ledger-loop.sh:842`) vor `handover` läuft Ebene 3:
1. `lane_harness_changed` (`:499`) prüfen, alte `branch.*` unter `.ah-out/review/<slug>/` mit festem Namen beiseite.
2. `review-run.sh --branch` aus der Lane (wie `task-close.sh`), danach `--confirm`; beide Ergebnisse in den Speicher des
   Loops.
3. `CONFIRMED`-Funde in Dateien aus `git diff --name-only origin/main...HEAD`, ohne Harness-Pfad, höchstens 3:
   - je Fund `ledger.sh new-task --section "Review-Funde Abschluss" --component … --files … --verify "bash
     scripts/dev/verify.sh <komponente> --strict" --change …`; die Komponente kommt aus dem Pfad wie bei `verify.sh`,
     ohne Komponente gilt die der letzten Task;
   - dann `ledger.sh status aktiv` und ein Ledger-Commit. `ledger_commit` (`:380`) bekommt dafür einen zweiten Modus:
     erlaubt sind genau die neuen Blöcke plus die Status-Zeile;
   - dann die Tasks über `run_task`. Wird eine davon `[?]` ⇒ `blockiert (Ebene 3)`.
4. Mehr als 3 Funde, ein Fund außerhalb der Branch-Dateien oder auf einem Harness-Pfad ⇒ `blockiert (Ebene 3)` mit
   der Liste, ohne Tasks.
5. Ergebniszeilen über `ledger.sh closing`: `Ebene 3` (Verdict, Modell, Kosten, CONFIRMED → Task-IDs) und
   `Ebene 3 Funde` (PLAUSIBLE und nit, gekürzt), dann ein Ledger-Commit.
6. Kandidaten außerhalb des Umfangs gehen nach `state.json` (`candidates`) und in den Summary-Abschnitt
   „Roadmap-Kandidaten“. Die Schlusszeile des Summary bleibt unverändert (AH-STATUS liest sie).

Neue Flags `--merge-budget 15` und `--confirm-budget 10`; die Kosten zählen in `RUN_COST`. Ebene 3 läuft je Ledger
einmal: Steht beim Fortsetzen schon `Ebene 3:` unter `## Abschluss`, läuft sie nicht noch einmal.

Tests mit dem claude-Stub für beide Prozesse:
- approve ohne Funde ⇒ Übergabe;
- 2 CONFIRMED ⇒ 2 Tasks gebaut, dann `bereit`;
- 4 CONFIRMED ⇒ `blockiert`;
- CONFIRMED auf einem Harness-Pfad oder außerhalb des Branches ⇒ `blockiert`;
- PLAUSIBLE nur unter `## Abschluss`;
- Fortsetzen ohne zweites Ebene 3;
- das Budget zählt.

Rot vorher: der Loop übergibt ohne Ebene 3.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T13)
Abhängt von: T3, T5, T6, T7

### T9 — Loop: Heavy am Ledger-Ende, Lane abbauen nach der Übergabe (E2, E5)  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Änderung: Nach Ebene 3 liest der Loop `Heavy:` aus dem Kopf.
- `none` ⇒ `ledger.sh closing … Heavy "none (geplant)"`.
- Sonst nach `lane_harness_changed` das `heavy.sh gate --for tasks/<slug>.md` **der Lane**. Das Token hat dieser Aufruf
  aus der Umgebung des Loops; die Sessions haben es nicht.
  - 0 ⇒ weiter.
  - 1 ⇒ `blockiert (heavy rot)` mit Report-Pfad.
  - 74 ⇒ einmal wiederholen, dann `ledger_result <slug> "bereit*"`, und der PR-Text sagt „Heavy offen — fährt die
    Aufsicht (<grund>)“. `handover` (`:717–726`) liest dafür die `Heavy:`-Zeile aus `## Abschluss` statt nur den Kopf.
- Die Verdict-Zeile kommt per `ledger.sh closing … Heavy`, als Ledger-Commit vor dem Bundle.
- Nach `handover` und `git bundle verify`: `lane.sh done <slug>` aus dem Klon. Scheitert es, gibt es einen Vermerk im
  Summary, keinen Stopp.
- Das Summary nennt `bereit*` in einer eigenen Zeile; die Schlusszeile bleibt.

Tests mit einem heavy-Stub (Override wie `AH_LOOP_REPO`):
- 0 ⇒ `bereit`, 1 ⇒ `blockiert`, 74, 74 ⇒ `bereit*` mit Vermerk;
- der Stub sieht `AH_PVE_TOKEN`, die Bau-Session (claude-Stub) nicht;
- `lane.sh done` läuft nach `bundle verify`, nicht bei `blockiert`.

Rot vorher: der Loop ruft kein Heavy.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T13)
Abhängt von: T1, T8

### T10 — Loop: 7a-Reste R-0175, R-0177, R-0178  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Änderung:
- **R-0175, Kevins Regel vom 2026-10-05:** In `run_task`, Fall 3 (`:807ff`): Endet die zweite Schließung nach Runde 2
  mit einem `request_changes`-Verdict mit Funden, und die Task hatte noch keine frische Serie, dann:
  - r1 und r2 gehen per `archive_reviews` (`:511`) unter festem Serien-Namen beiseite, kein Glob;
  - `round=1`, eine Fix-Session mit dem r2-Verdict, danach wie bisher;
  - beim zweiten Mal ⇒ `[?]` mit dem ersten Blocker.
- **R-0177:** Nach dem Abschluss von Runde 1 hält der Loop den sha256 von `<id>.r1.verdict.json` im Speicher. Vor dem
  Abschluss von Runde 2 vergleicht er ihn; eine Abweichung ⇒ `tampered` (`:660`).
- **R-0178:** `close_task` (`:669`) sucht im Close-Log nach demselben Limit-Text wie `session` (`:589`). Ein Treffer ⇒
  Aufräumen, Reset-Zeit nach `state.json`, `stop_run usage-limit`, Task bleibt offen, kein Retry.

Tests mit Stubs, je Fall: frische Serie genau einmal, dann `[?]`; ein umgeschriebenes r1-Verdict ⇒ Exit 74
`harness-modified`; der Limit-Text im Close-Log ⇒ `usage-limit` mit Reset.
Rot vorher: alle drei Fälle enden heute anders (`[?]` nach Runde 2, kein Vergleich, `infra`).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T13)

### T11 — `lane.sh pr` und `lane.sh watch-ci`: die Übergabe in Kevins Session (E7)  [ ]
Komponente: scripts · Dateien: scripts/dev/lane.sh, scripts/tests/lane_test.sh
Änderung: Zwei neue Verben (Dispatch `lane.sh:375–378`).

`pr <slug> --bundle <datei>`:
1. `git fetch origin`, das Bundle in `.ah-out/` kopieren, `git bundle verify` (fehlende Voraussetzung ⇒ Ende).
2. `git fetch <kopie> feature/<slug>:feature/<slug>`, nur fast-forward, nie `--force`.
3. `lane_new`, im Worktree `git merge origin/main`; ein Konflikt ⇒ `merge --abort`, Exit 3.
4. `run.sh quick --strict`; rot ⇒ Exit 1.
5. `review.sh pr-body tasks/<slug>.md` nach `<lane>/.ah-out/pr-body.md`.
6. Am Ende druckt es `git -C <lane> push -u origin feature/<slug>:feature/<slug>` und
   `gh pr create --draft --base main --head feature/<slug> --title "…" --body-file …`. Es ruft keinen der beiden auf.

`watch-ci <slug>`:
- die Läufe zu `HEAD` von `feature/<slug>` über `gh run list --branch … --json databaseId,headSha,status,conclusion,
  workflowName`, je Lauf `gh run watch <id> --exit-status --compact`;
- rot ⇒ höchstens zweimal `gh run rerun <id> --failed`, das Log von `gh run view <id> --log-failed` nach `.ah-out/`;
- Exit 0 grün, 1 rot, 3 grün erst nach einem Rerun (flaky, nicht PASS).

Ein Test-Override für den Quick-Befehl folgt dem Muster von `heavy.sh`. Tests in einem Wegwerf-Repo mit Bundle, Recordern
für `git push` und einem `gh`-Stub:
- fehlende Voraussetzung, nicht-ff und Konflikt brechen ab;
- Quick rot ⇒ 1;
- die Ausgabe nennt beide Befehle, und weder Push noch `gh pr create` liefen;
- `watch-ci`: grün 0, rot nach zwei Reruns 1, grün nach Rerun 3, nie ein dritter Rerun.

Rot vorher: unbekannte Verben.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T13)

### T12 — feature-build: Schritt 3 über `heavy.sh gate`, Loop-Ledger über `lane.sh pr`  [ ]
Komponente: scripts · Dateien: .claude/skills/feature-build/SKILL.md, scripts/tests/skill_consistency_test.sh
Änderung:
- Schritt 3 (`SKILL.md:249–272`): `linux-full` ⇒ `bash scripts/tests/heavy.sh gate --for tasks/<slug>.md` in tmux mit
  Wächter (`/test`), die Verdict-Zeile wörtlich in den PR. Das ersetzt die Prosa warm → quick → integration.
  `scenario` bleibt eine Frage an Kevin, `windows` „nicht verifiziert“.
- Schritt 5: Ein vom Loop gebautes Ledger kommt über `bash scripts/dev/lane.sh pr <slug> --bundle <datei>` und danach
  `lane.sh watch-ci <slug>`.
- `skill_consistency_test.sh`: Der Skill nennt `heavy.sh gate --for` und `lane.sh pr|watch-ci`, und beide Skripte
  führen diese Verben in ihrer Usage.

Rot vorher: der Test findet die Aufrufe nicht.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T13)
Abhängt von: T1, T11

### T13 — Doku: Worker bis PR-fertig, drei Review-Ebenen, Hypervisor des Runners  [ ]
Komponente: scripts · Dateien: AUTONOMOUS.md, DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Änderung:
- `AUTONOMOUS.md`: Der Abschnitt „Der Worker“ aus 7a bekommt den Ablauf am Ledger-Ende (Ebene 3, Heavy, Übergabe,
  `bereit*`). Die Ebenen-Übersicht wird auf drei Ebenen korrigiert (heute „Zwei Review-Ebenen“, `AUTONOMOUS.md:80`).
- `DEVELOPMENT.md`: `lane.sh pr`/`watch-ci` und das Hypervisor-Setup des Runners (Zieldatei, Token-Zeile,
  VM-Schlüssel, `vm.py doctor` als Probe).
- `cicd.html` DE+EN: der Worker-Abschnitt.
- `CHANGELOG.md`: `[Unreleased]` → Added.
- CLAUDE.md bleibt Kevins Datei.

Rot vorher: entfällt (Doku); `review.sh docs-pairs` und `doc-smoke` laufen in der Suite.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die genannten Dateien
Abhängt von: T1, T2, T3, T4, T5, T6, T7, T8, T9, T10, T11, T12
