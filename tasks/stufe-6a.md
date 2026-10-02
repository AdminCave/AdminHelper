<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stufe 6a — deterministische Review-Prüfer — Task-Ledger
Status: aktiv · Branch: harness/stufe-6a · Commit-Granularität: pro Task · Review: pro Task (feature-review; Harness-Pfade ⇒ Reviewer Opus) · Modell: Opus
Freigabe: Kevin, 2026-10-02 („6a freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: docs/features/stufe-6a.md (Roadmap R-0009, Teil 6a)
Heavy: none — nur Harness-Skripte unter scripts/dev, ihre hermetischen Tests, ein Skill und Doku; kein Stack-, Gateway-, PKI- oder Install-Pfad. Die Seed-Probe in T5 läuft lokal über verify.sh (monitoring, sqlite).
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-02 von der Aufsicht (adminhelper-ac); Entscheidungen Kevin 2026-10-02. Zeilenangaben main@abef751a.
Bau: Worker B in ../AdminHelper-harness-b (eigene Test-DB adminhelper_test_harness_b), interaktiv (Harness-Pfade),
**erst nach dem Merge von harness/schutz-nachziehen-2** — beide ändern `review.sh` und `review_scripts_test.sh`.
Jede neue Datei unter `scripts/dev/` kommt in derselben Task nach `scripts/dev/harness-paths.txt`.

### T1 — Verdict-Schema und `review.sh check-verdict`; task-close delegiert  [x]
Komponente: scripts · Dateien: scripts/dev/review-verdict.schema.json, scripts/dev/review.sh, scripts/dev/task-close.sh, scripts/dev/harness-paths.txt, scripts/tests/review_scripts_test.sh, scripts/tests/task_close_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @bf1ca555 2026-10-02T14:55:04+02:00
Review: approve (opus, one round; nits on schema load, pattern anchor and test cp taken in)
Änderung: Neues Schema (Felder und Regeln wie Spec „Datenmodell“, ohne `coverage`). Neues Verb
`review.sh check-verdict <datei> --tree <hash>` mit python3-Bordmitteln (Pflichtfelder, Enums, Regeln). Exit 0 gültig ·
2 unlesbar/schemawidrig · 3 Urteil kein approve oder unzulässiges approve · 4 fremder Tree; ein `blocker` ohne
`evidence` wird im Ergebnis zu `nit`. `task-close.sh` ersetzt seine Inline-Prüfung (`:292–311`) durch den Aufruf;
die Exit-Codes von task-close bleiben. Das Schema kommt nach `harness-paths.txt`.
Rot vorher (in review_scripts_test.sh, neues Verb fehlt heute ⇒ Exit 2 „unknown verb“): approve mit
`probe.applicable: true, red_without_change: false` ⇒ 3; approve mit einem `blocker` ⇒ 3; `blocker` ohne `evidence` ⇒
als `nit` gezählt, approve bleibt gültig; fremder `tree_hash` ⇒ 4; fehlendes Pflichtfeld ⇒ 2. task_close_test
(`:550–575`) bleibt grün und bekommt den Fall „approve mit blocker ⇒ 3, kein Commit“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T7)

### T2 — `review-risk.txt` und `review.sh risk`  [ ]
Komponente: scripts · Dateien: scripts/dev/review-risk.txt, scripts/dev/review.sh, scripts/dev/harness-paths.txt, scripts/tests/review_scripts_test.sh
Änderung: `review-risk.txt` (ein Glob je Zeile, Kommentar je Block: PKI/mTLS, Auth/AuthZ, SSRF-Guards, Alembic,
Release-Workflows, Harness-Pfade aus `harness-paths.txt`, dazu `apps/monitoring/app/alerter.py` und die übrigen
Startpfade aus Roadmap-Dokument §10.3, die es alle gibt). `review.sh risk [--staged | --range <a>..<b>]` druckt
`xhigh` und die getroffenen Pfade, wenn ein geänderter Pfad passt, sonst `standard`; Exit 0 in beiden Fällen, 2 bei
Aufruffehler. Die Datei kommt nach `harness-paths.txt`.
Rot vorher: `apps/monitoring/app/alerter.py` gestaged ⇒ `xhigh`; nur `docs/admin/benutzer.html` ⇒ `standard`;
`scripts/dev/task-close.sh` ⇒ `xhigh` (Harness-Pfad); ein Pfad mit Leerzeichen bricht nichts.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T7, T8)

### T3 — `review.sh docs-pairs`: Doku-Seite ohne Gegenstück ist ein Fund  [ ]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/dev/task-close.sh, scripts/tests/review_scripts_test.sh
Änderung: `review.sh docs-pairs [--staged]`: für jede geänderte `docs/**/*.html` das Gegenstück aus dem
`lang-switch`-Link der Seite lesen (etwa `docs/admin/benutzer.html:33` → `../en/admin/users.html`); fehlt das
Gegenstück im Diff ⇒ Fund (Exit 3, Pfadpaar genannt). Seiten ohne `lang-switch` und Nicht-HTML unter `docs/`
(`docs/features/*.md`, `docs/adr/*`) sind ausgenommen. `task-close.sh` fährt es in Schritt 3 nach `scope`.
Rot vorher: einseitig gestagte `docs/admin/benutzer.html` ⇒ 3; das Paar `benutzer.html` + `en/admin/users.html` ⇒ 0;
nur `docs/features/x.md` ⇒ 0; task_close_test: ein Close mit einseitiger Doku ⇒ 3, kein Commit.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T7)

### T4 — `review-contracts.txt` und `review.sh contracts` als Ebene 0 in task-close  [ ]
Komponente: scripts · Dateien: scripts/dev/review-contracts.txt, scripts/dev/review.sh, scripts/dev/task-close.sh, scripts/dev/harness-paths.txt, scripts/tests/review_scripts_test.sh, scripts/tests/task_close_test.sh
Änderung: `review-contracts.txt`: Glob → Prüfung, entweder `test <komponente> <testdatei>` (läuft als
`verify.sh <komponente> --strict -- <testdatei>`) oder `pair <regex> <datei> <datei>` (gleicher Wert in beiden; etwa
`FRP_VERSION`, `MINISIGN_PUBKEY`, die Versions-Stellen von tauri/Cargo/CHANGELOG). Start: `apps/monitoring/app/check_types.py`
→ `test monitoring tests/test_push_only_ui_sync.py`, dazu die Paare, die es heute schon als Einzelprüfung gibt.
`review.sh contracts --staged [--list]` listet bzw. fährt die getroffenen Prüfungen; rot ⇒ Exit 3. `task-close.sh`
fährt es in Schritt 3; das Ergebnis geht in die Evidenz. Die Datei kommt nach `harness-paths.txt`.
Rot vorher: `check_types.py` gestaged ⇒ `--list` nennt `test_push_only_ui_sync.py`; ein Paar mit abweichendem Wert ⇒
3; nichts getroffen ⇒ 0 ohne Lauf; task_close_test mit Stub-`verify.sh`: rote Vertragsprüfung ⇒ 3, kein Commit.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T7)

### T5 — `review-probe.sh`: wäre der Test ohne den Fix rot, und `--mutate`  [ ]
Komponente: scripts · Dateien: scripts/dev/review-probe.sh, scripts/dev/harness-paths.txt, scripts/tests/review_probe_test.sh
Änderung: Neues Skript (SPDX). `review-probe.sh <komponente> [--base <rev>] [--staged | --commit <rev>] [-- <test>]`:
eigene Worktree (`git worktree add --detach` unter einem `mktemp -d -p` des Aufrufers, `trap` entfernt sie samt
`git worktree prune`), nur die Hunks unter den Testpfaden der Komponente (Liste wie `review.sh component_tests`,
`:64–75`) auf die Basis anwenden, `verify.sh <komponente> --tree <wt> --strict -- <test>` mit eigenem `AH_OUT_DIR`
(sonst löscht verify.sh `last-verify.json` des Builders, `verify.sh:76–80`) und `AH_DEVENV` auf die `.devenv.sh` des
Aufrufers. Fehlerart: pytest aus JUnit (`<failure>` zählt, `<error>`/Collection ⇒ `applicable: false, reason:
new-symbol`), Go `--- FAIL:` ohne `[build failed]`, vitest Test-Failure statt Suite-Fehler. Fehlt die Toolchain ⇒
`applicable: false, reason: toolchain`. Ausgabe JSON (`probe`-Block des Schemas). `--mutate <datei>:<zeile> '<ersatz>'`
setzt genau einen Mutanten in die Kopie und meldet `killed|survived`. Skript nach `harness-paths.txt`.
Rot vorher (hermetisch, review_probe_test.sh mit Stub-`verify.sh` und aufgezeichneten Ausgaben): pytest-Failure ⇒
`red_without_change: true`; Collection-Error ⇒ `applicable: false, reason: new-symbol`; Go-Build-Fehler ⇒ nicht
rot; fehlende Toolchain ⇒ `reason: toolchain`; `git status --porcelain` des Aufrufers vorher und nachher bytegleich;
`git worktree list` danach eine Zeile; `--mutate` gedeckte Zeile ⇒ `killed`, ungedeckte ⇒ `survived`.
Zusatzbeleg (nicht hermetisch, in die Evidenz): Seed `53e76924` auf Basis `53e76924^` mit Komponente monitoring ⇒
`red_without_change: true` (409 ≠ 200); `--mutate` auf die Guard-Zeile in `apps/monitoring/app/routers/checks.py`
(409-Zweig um `:302`) ⇒ `killed`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T7)

### T6 — `review.sh pr-body <ledger>`: Checkliste mit Evidenz als PR-Text  [ ]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh
Änderung: `review.sh pr-body <ledger>` erzeugt Markdown: Kopf (Spec, Roadmap-IDs, Heavy-Zeile), je Task Titel,
Status-Haken, `Evidenz:`, `Review:` und vorhandene Verdict-Datei (Urteil, Modell); Tasks mit `[~]`/`[?]` gesondert;
eine Task ohne Evidenz erscheint als „unverifiziert“, nie als approve. Keine Hostnamen, IPs oder VMIDs im Text (sie
werden aus den Ledger-Zeilen entfernt).
Rot vorher: Fixture-Ledger mit drei Tasks (eine ohne Evidenz, eine `[?]`, eine mit Adresse `192.168.x.y` in der
Evidenz) ⇒ „unverifiziert“, `[?]`-Abschnitt, keine Adresse im Text; heute „unknown verb“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T7, T8)

### T7 — Doku: Review-Prüfer und Verdict  [ ]
Komponente: scripts · Dateien: DEVELOPMENT.md, AUTONOMOUS.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Änderung: DEVELOPMENT.md „Task schliessen“ (`:411ff.`): die neuen Schritte in task-close (docs-pairs, contracts,
check-verdict) und die Verben `risk`, `probe`, `pr-body`. AUTONOMOUS.md (`:65`): vor den Review-Ebenen steht Ebene 0,
die deterministischen Prüfer. cicd.html DE+EN: Abschnitt „Review-Prüfer und Verdict“. CHANGELOG (Added).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die Task ist die Doku

### T8 — feature-build: Modellwahl über `review.sh risk`, Review-Disziplin, PR-Text aus `pr-body`  [ ]
Komponente: scripts · Dateien: .claude/skills/feature-build/SKILL.md, scripts/tests/skill_consistency_test.sh
Änderung: Schritt 4 (`:135–170`): Das Modell des Reviewers kommt aus `review.sh risk --staged` (`standard` ⇒ Sonnet,
`xhigh` ⇒ Opus) statt aus der Prosa-Liste (`:149–151`). Review-Disziplin (Kevin 2026-10-02): **eine** Runde ist die
Regel, eine zweite nur bei einem `blocker` oder einem belegten `wichtig`; `nit` blockiert nie (in derselben Runde ohne
Re-Review miterledigen oder liegen lassen); kein neuer Umfang mitten im Bau außer bei einer Sicherheitslücke — Funde
gehen über die Aufsicht in die Roadmap. Der PR-Schritt im Abschluss (`:252ff.`) nimmt `review.sh pr-body` als
`--body-file`. Die Aufräum-Regel in Schritt 4 bleibt wörtlich (`skill_consistency_test.sh:235–238`).
Rot vorher: ein neuer Fall in skill_consistency_test verlangt in Schritt 4 `review.sh risk` und „eine Runde“; heute
rot.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (der Skill ist die Anleitung)
