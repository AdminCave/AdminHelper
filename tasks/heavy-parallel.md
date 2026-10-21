<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness: Sammellauf mit Sekunden je Schritt und auf zwei Boxen parallel — Task-Ledger
Status: bereit · Branch: feature/heavy-parallel · Review: pro Task
Spec: docs/features/heavy-parallel.md (Roadmap R-0603)
Heavy: linux-full — ein realer Beweislauf vor dem Merge (Kevin 2026-10-21): `bash scripts/tests/heavy.sh all` aus dem Worktree, in tmux nach CLAUDE.md §2, mit zwei Boxen der Lane des Vorhabens (beide kalt). Erwartet: beide Teile laufen gleichzeitig, der Report nennt je Schritt Ergebnis und Sekunden, das Gesamturteil steht in Zeile 1, `vm.py list` danach ohne Leck. Voraussetzung: keine laufende Box einer fremden Lane (sonst bricht der Pre-flight mit 74 ab), also kein gleichzeitiger Sammellauf aus dem Haupt-Checkout. Die Historie des Beweislaufs bleibt im Worktree (`tasks/private` gibt es dort nicht im Repo), nicht in der echten `history.csv`. T1 zeigt sich real erst im ersten Sammellauf aus dem Haupt-Checkout nach dem Merge (aus einem Worktree hat die Box kein Repo); bis dahin belegt ihn `run_flags_test.sh`.
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-21: R-0603 diktiert, damit Kevins Wort für die Harness-Pfade dieses Vorhabens (CLAUDE.md §4). Alle
Tasks berühren Risikopfade (`scripts/tests/run.sh`, `scripts/tests/heavy.sh`, `scripts/vm/*`, `.claude/*`): zum
Review jeder Task kommt `security`. Geprüft gegen `origin/main@8dec2275`. Die Tasks laufen in Ledger-Reihenfolge;
T1–T7 hängen nicht an T8–T12. T11 und T12 hat Kevin am 2026-10-21 beantwortet (Spec „Offene Fragen“). Gebaut wird nur im
Worktree: Im Haupt-Checkout läuft womöglich `heavy.sh`, und ein laufendes bash-Skript darf nicht in place geändert
werden. In den einfach gequoteten awk- und python-Programmen von `heavy.sh` steht kein Apostroph. Neue Test-Adressen
nur aus RFC 5737 (192.0.2.x). Gemergt wird nach dem Beta-Release.

### T1 — run.sh: Kopf und Tree-Hash des Clients gehen vor dem git der Box  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh, scripts/vm/rsync-exclude.txt, DEVELOPMENT.md, CHANGELOG.md, scripts/vm/iter.sh, scripts/vm/tests/test_vm.py, scripts/dev/task-close.sh, scripts/tests/task_close_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @3bc36d5e 2026-10-21T13:40:36+02:00
Review: approve (.ah-out/review/heavy-parallel/T1.verdict.json)
Änderung: Zuerst die Tests in `run_flags_test.sh`, auf HEAD dreimal identisch rot, die Summary-Zeilen in den Commit-Body. Der Fall „a git that answers wins over the client value“ (`:540-560`) dreht sich auf Kevins Entscheidung vom 2026-09-25 („Die Box braucht kein Repo … Kopf und Tree-Hash gibt `iter.sh` vom Client mit“, `DEVELOPMENT.md:1235-1236`): Mit `AH_HEAD=1111…` und einem `git`, das `rev-parse HEAD` mit `3333…` beantwortet, trägt das Artefakt `1111…`. Das ist eine gewollte Änderung der Erwartung, keine Schwächung; der Reviewer-Prompt nennt sie. Neu daneben: ein `git`-Stub, der auch die Aufrufe von `scripts/dev/tree-hash.sh` beantwortet (`rev-parse --show-toplevel` mit dem Checkout, `add`/`rm` mit 0, `write-tree` mit `3333…`), mit `AH_TREE_HASH=2222…` → `"tree_hash": "2222…"`; derselbe Stub ohne `AH_HEAD`/`AH_TREE_HASH` → `3333…` in beiden Feldern (die Box ohne Client-Werte fragt weiter ihr `git`); ein Client-Wert, der nicht aus genau 40 Hex-Zeichen besteht, zählt nicht (das `git` der Box antwortet). Die Fälle „no .git: … comes from the client“ (`:521-538`) bleiben unverändert grün.
Fix in `run.sh` (`:449-472`): `evidence_head`/`evidence_tree_hash` nehmen zuerst den Client-Wert, wenn er 40 Hex-Zeichen hat, sonst die Antwort des eigenen `git`, sonst leer. Der Kommentar sagt das Warum: Der eigene Hash der Box entsteht am Ende des Laufs über einen Baum, den der Sync geformt (die getrackte `apps/server/data/.gitkeep` fehlt) und der Lauf verändert hat; aus dem Haupt-Checkout trifft er den des Clients deshalb nie, und `heavy.sh` verwarf jedes Artefakt. `iter.sh` gibt die Werte nur bei einem Lauf mit Sync mit (`iter.sh:62-66`), ein Lauf ohne Sync behält die Antwort der Box. `rsync-exclude.txt:4-10`: Der Kommentar hört auf, `apps/server/data` „safe“ zu nennen; er sagt, dass der Hash der Box nie entscheidet, wenn `iter.sh` die Werte des Clients mitgibt.
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test
Doku: `DEVELOPMENT.md:1235-1237` ein Halbsatz: die Werte des Clients gehen vor dem `git` der Box, auch wenn der Sync aus dem Haupt-Checkout ein Repo mitbringt. `CHANGELOG.md` unter `[Unreleased]` → `### Fixed`: „**Sammellauf: Schritt-Tabelle und Sekunden je Schritt wieder im Report (R-0603):** …“ (umlautfrei, Gedankenstrich „—“).
Beweis: origin/main@8dec2275 · `.ah-out/weekly/*/report.md`: alle 16 Läufe aus dem Haupt-Checkout seit 2026-09-18 tragen „last-all.json describes another tree — ignored“ und eine leere `steps-all.tsv`, die beiden aus einem Worktree vom 2026-09-25 je 33/34 Schritt-Zeilen · Planer-Probe: Klon + `rsync -a --delete --exclude-from scripts/vm/rsync-exclude.txt` → `tree-hash.sh` `ca4abbc1…` gegen `3924a443…`, mit zurückgelegter `apps/server/data/.gitkeep` gleich
Orakel: contract — Kevins Entscheidung 2026-09-25: Kopf und Tree-Hash eines Box-Laufs kommen vom Client
HEAD: 8dec2275

### T2 — heavy.sh: ein verworfenes Artefakt nennt beide Identitäten  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @f7b417cd 2026-10-21T13:54:53+02:00
Review: approve (.ah-out/review/heavy-parallel/T2.verdict.json)
Änderung: Die Notiz bei einem Artefakt aus einem anderen Baum (`heavy.sh:369-373`) nennt `head` und `tree_hash` des Artefakts und `COMMIT`/`TREE` dieses Laufs (Hex-Werte, keine Adresse), damit die Ursache im Report steht. `heavy_test.sh` Fall 4l (`:780-789`): Die Ausgabe nennt `000…`/`111…` und den Commit des Fixture-Repos; die bestehenden Assertions bleiben. Auf HEAD rot (die Notiz nennt heute nichts).
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: keine (intern; die Zeile steht im Report)

### T3 — run.sh: --part gui|rest teilt die Schritte in zwei disjunkte Teile  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/run_flags_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html, DEVELOPMENT.md, .claude/rules/testing.md, .claude/skills/test/SKILL.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @74b43686 2026-10-21T14:30:11+02:00
Review: approve (.ah-out/review/heavy-parallel/T3.verdict.json)
Änderung: Neues Flag `--part <gui|rest>` im Parser (`:54-71`, setzt `AH_PART` wie `--step` `AH_STEP`), Kopf-Usage (`:12-27`) und die Meldung bei unbekanntem Flag (`:66`) nennen es. Ein anderer Wert als `gui`/`rest` ist Exit 2, bevor ein Schritt läuft. Teil `gui` = `desktop-e2e smoke`, `desktop GUI E2E` und jeder Name `desktop_e2e_*` (die Namen aus `layer_e2e`, `:879-905`); Teil `rest` = jeder andere Schritt. Ein Prädikat und seine Verneinung, damit jeder Schritt, auch ein künftiger, in genau einem Teil liegt; ein Kommentar sagt das Warum. Gefiltert wird in `want_step` (`:214-218`) vor dem `--step`-Abgleich: Ein Schritt außerhalb des Teils läuft nicht und steht nicht im Artefakt (kein SKIP); `--step` sucht nur im Teil. `write_artifact` schreibt `"part"` nach `"step"` (`:487`). Unter `--strict` ist „no step ran“ je Teil weiter ein Fehler.
Tests in `run_flags_test.sh`: ohne Docker und Display, `AH_ALLOW_REAL=1`: `run.sh e2e --part gui` → Artefakt-Schritte genau `desktop-e2e smoke` und `desktop GUI E2E`; `--part rest` → genau `web Playwright E2E`; die Vereinigung ist die Namensliste von `run.sh e2e` ohne `--part`, der Schnitt leer; `run.sh lint --part gui --strict` → Exit 1 mit `strict-failed: no step ran`; `--part nope` und `--part` ohne Wert → Exit 2; `"part": "gui"` im Artefakt, `"part": ""` ohne Flag. Mit Stubs für `docker info`, `xvfb-run`, `WebKitWebDriver` und `tauri-driver` (nur der Trockenlauf von `--step`, keine Suite startet): für jede Datei `scripts/tests/desktop_e2e_*.sh` außer `desktop_e2e_skip_test` endet `--part rest --step <name>` mit „unknown step“ (Exit 2), und `--part gui --step "web Playwright"` ebenso.
Verify: bash scripts/dev/verify.sh scripts --strict -- run_flags_test
Doku: `docs/developer/cicd.html` und `docs/en/developer/cicd.html`, Flag-Tabelle von `run.sh` (nach `--step`, `:76`/`:77`): eine Zeile `--part gui|rest` (DE/EN sinngleich: welche Schritte zu `gui` gehören, dass jeder Schritt in genau einem Teil liegt, wofür `heavy.sh` es nutzt). `DEVELOPMENT.md:1201`, `.claude/rules/testing.md:14`, `.claude/skills/test/SKILL.md:175`: die Usage-Zeile nennt `[--part gui|rest]`.

### T4 — lib.sh: warm.env wird nur unter einer Sperre geschrieben  [x]
Komponente: scripts · Dateien: scripts/vm/lib.sh, scripts/tests/lib_vm_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b88df314 2026-10-21T14:44:25+02:00
Review: approve (.ah-out/review/heavy-parallel/T4.verdict.json)
Änderung: `warm_set` und `warm_clear` (`:128-135`) lesen, ändern und ersetzen `warm.env` in einer Subshell unter `flock -w 30` auf `warm.env.lock` neben der Datei (`( flock -w 30 9 || exit 1; … ) 9>"$f.lock"`), mit einer Temp-Datei je Prozess (`$f.tmp.$$`) statt der geteilten `$f.tmp`. Warum (Kommentar): Mit zwei Teilen eines Sammellaufs schreiben zwei Wrapper desselben Checkouts gleichzeitig, und ein Lesen-Ändern-Ersetzen ohne Sperre verliert einen Schlüssel oder verschränkt die Temp-Datei. Eine Sperre, die in 30 s nicht frei wird, ist Rückgabe 1 mit einer Zeile auf stderr, ohne Schreiben. Ohne `flock` schreibt die Funktion wie bisher und sagt es einmal (wie `py_lock`, `run.sh:273-276`). `vm.py` liest als VMID nur Schlüssel ohne Unterstrich aus `warm.env`; die Sperrdatei ist eine eigene Datei und berührt das nicht.
Tests in `lib_vm_test.sh`: Hält der Test die Sperre 2 s lang (`flock` im Hintergrund auf `warm.env.lock`), wartet `warm_set` und schreibt danach; die gemessene Dauer ist ≥ 1 s, der Wert steht in der Datei (auf HEAD rot: kein Warten). 20 parallele `warm_set` verschiedener Schlüssel → alle 20 stehen in `warm.env`, keine `warm.env.tmp*` bleibt liegen. `warm_clear` neben einem parallelen `warm_set` eines anderen Schlüssels lässt diesen stehen.
Verify: bash scripts/dev/verify.sh scripts --strict -- lib_vm_test
Doku: keine (intern)

### T5 — warm.sh: zweiter Warm-Slot gui  [x]
Komponente: scripts · Dateien: scripts/vm/warm.sh, scripts/vm/profiles.json, scripts/vm/tests/test_vm.py, scripts/tests/vm_wrappers_test.sh, .claude/skills/vm/SKILL.md, .claude/skills/test/SKILL.md, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @a048ec25 2026-10-21T14:59:39+02:00
Review: approve (.ah-out/review/heavy-parallel/T5.verdict.json)
Änderung: `warm.sh gui` (`:166-171`) wärmt einen zweiten Slot derselben Lane: `warm_role gui linux-full full`, also `vm.py clone --profile linux-full --role gui --ttl …`, Bootstrap `full`, Schlüssel `gui`, `gui_name`, `gui_ttl`. Kopf (`:11-15`) und Usage (`:170`) nennen `gui`. `profiles.json`: Rolle `gui` mit der Form von `desktop` (`"memory": 6144, "cores": 6`, neben `:26`), damit `vm.py` ihren RAM vor dem Klon prüft und `doctor --roles gui` sie kennt. Der Slot `desktop` bleibt unberührt.
Tests: `test_vm.py` `test_the_roles_the_wrappers_use_all_exist` (`:487-501`) nennt `gui`; ein neuer Test hält `gui` und `desktop` in Speicher und Kernen gleich. `vm_wrappers_test.sh`: `warm.sh gui` ruft `clone --profile linux-full --role gui --ttl 8h`, schreibt `gui`/`gui_name`/`gui_ttl` und lässt einen vorhandenen `desktop`-Slot stehen; ein laufender `gui`-Slot wird wiederverwendet; eine Box mit Rolle `desktop` auf der VMID des `gui`-Slots wird nicht übernommen („carries role desktop, not gui — re-warming“).
Verify: bash scripts/dev/verify.sh scripts --strict -- vm_wrappers_test
Doku: `.claude/skills/vm/SKILL.md:17` (`warm.sh <desktop|gui|server|pond>`, `gui` = zweite volle Box für den GUI-Teil des Sammellaufs), `.claude/skills/test/SKILL.md:145-149` (Liste der Rollen), `DEVELOPMENT.md:1208`.

### T6 — reap.sh: Slot gui und --role gibt genau einen Slot frei  [x]
Komponente: scripts · Dateien: scripts/vm/reap.sh, scripts/tests/vm_wrappers_test.sh, .claude/skills/vm/SKILL.md, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @e9eb5bbb 2026-10-21T15:10:24+02:00
Review: approve (.ah-out/review/heavy-parallel/T6.verdict.json)
Änderung: Die Slot-Schleife (`:43`) nimmt `desktop server gui`. Neu `--role <desktop|server|gui>`: nur dieser Slot geht an `vm.py destroy` (derselbe Aufruf wie heute, `:66-70`: `--lane`, `--role`, `--no-scenario`, `--expect-name`), und nur seine Schlüssel werden geleert (`<rolle>` und `<rolle>_*`, beim Server also auch die Zugangsdaten); der Ablauf-Sweep und die abschließende Liste laufen wie bisher. Ein anderer Wert oder `--role` ohne Wert ist Exit 2, bevor `vm.py` gerufen wird. Kopf (`:11-15`) nennt das Flag.
Tests in `vm_wrappers_test.sh`: `reap.sh` ohne Flag zerstört die Slots `desktop`, `server` und `gui` (je ein `destroy`); `reap.sh --role gui` ruft genau ein `destroy --lane main --role gui --no-scenario --expect-name <name> <vmid>`, leert `gui`, `gui_name`, `gui_ttl` und lässt `desktop` und `desktop_name` stehen; `--role nope` → Exit 2, kein Eintrag im `FAKE_LOG`.
Verify: bash scripts/dev/verify.sh scripts --strict -- vm_wrappers_test
Doku: `.claude/skills/vm/SKILL.md:21` (`reap.sh [--lane l] [--all] [--role <rolle>]`), `DEVELOPMENT.md` Absatz Schneller Loop (`:1206-1220`).

### T7 — iter.sh: --slot wählt die warme Box, --part geht an run.sh  [x]
Komponente: scripts · Dateien: scripts/vm/iter.sh, scripts/tests/iter_flags_test.sh, scripts/tests/vm_wrappers_test.sh, .claude/skills/vm/SKILL.md, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @0f6846f7 2026-10-21T15:22:26+02:00
Review: approve (.ah-out/review/heavy-parallel/T7.verdict.json)
Änderung: Ein führendes `--slot <desktop|gui>` (Default `desktop`) vor der Form; gilt für die Layer-Form und `--cmd`, mit `--desktop` (Pond) ist es Exit 2, ein anderer Wert ebenso, beides vor `vm_load_env`. Der Slot bestimmt den `warm.sh`-Aufruf (`:140`, `:208`), die Box (`:141`, `:209`), den Namen für `--expect-name` (`:95`), die Frist (`:52`, `<slot>_ttl`) und den Hinweis bei einer Ablehnung (`:103`, `warm.sh <slot>`). Die Flag-Liste der Layer-Form (`:166`) nimmt `--part`; es geht wie `--step` gequotet an `run.sh`. Kopf (`:11-19`) nennt beides.
Tests: `iter_flags_test.sh` (Trockenlauf): `all --strict --part gui` → der Befehl endet auf `run.sh all --strict --part gui`; `--slot nope lint` und `--slot gui --desktop` → Exit 2, `vm.py` nicht gerufen. `vm_wrappers_test.sh` (Fake-`vm.py`): mit `desktop=3001`/`gui=3002` und Namen in `warm.env` fährt `iter.sh --slot gui lint` `run 3002 … --extend <gui_ttl> --expect-name <gui-name>`, ohne `--slot` weiter `run 3001`; `iter.sh --slot gui --cmd true` fährt auf 3002.
Verify: bash scripts/dev/verify.sh scripts --strict -- iter_flags_test vm_wrappers_test
Doku: `.claude/skills/vm/SKILL.md:18-19` (`iter.sh [--slot desktop|gui] <layer> … [--part …]`), `DEVELOPMENT.md` Absatz Schneller Loop.
Abhängt von: T5

### T8 — heavy.sh: die Auswertung einer all-Ebene als Funktion (Refactor)  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d905076a 2026-10-21T15:43:52+02:00
Review: approve (.ah-out/review/heavy-parallel/T8.verdict.json)
Änderung: `run_all` (`:290-450`) wird zu Lease (`warm.sh`, `:298-324`), Lauf (`iter.sh`) und einer Funktion, die einen Lauf auswertet: Log, Exit-Code, Box, Zieh-Verzeichnis, Sekunden und ein Etikett (heute leer) rein; Summary-Zeile, Artefakte, Infra-Marker, Artefakt-Prüfung, `steps-all.tsv`, `strict-failed`, Klassifikation und Ebenen-Zeile wie heute (`:336-449`). `BOX_OUT` (`:220`) und der Pfad von `last-all.json` kommen aus dem Zieh-Verzeichnis. `rerun_step` (`:482-488`) bekommt den Slot (heute `desktop`, ohne `--slot` aufgerufen). Keine Verhaltensänderung: Report, Historie und Ausgabe bleiben Byte für Byte gleich. `heavy_test.sh` bleibt unverändert und ist vor und nach dem Diff grün; beide Summary-Zeilen in den Commit-Body.
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: keine (Refactor)
Orakel: differential — `heavy_test.sh` unverändert vor und nach dem Diff grün

### T9 — heavy.sh: all auf zwei Boxen parallel, Teil rest und Teil gui  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html, .claude/skills/test/SKILL.md, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d9cca432 2026-10-21T16:43:13+02:00
Review: approve (.ah-out/review/heavy-parallel/T9.verdict.json)
Änderung: Nach Spec „Entwurf“ 4, Punkte 1–6. Pre-flight (`:160-198`): `vm.py list --json` wird vor `doctor` gelesen, und `doctor --roles` (`:177-179`) nennt `desktop` und `gui` nur, wenn ihr Slot (`warm_get`) dort keine laufende Box hat; braucht keiner einen Klon, bekommt `--roles` einen leeren Wert (der Kapazitäts-Check rechnet dann mit 0 MiB, `vm.py:915-918`). Box `desktop` leasen wie heute; scheitert das, `UNVERIFIED`, nichts startet. Dann zwei Hintergrund-Jobs mit `</dev/null`: `gui` = `warm.sh gui` (ein Retry, Exit 2 ohne Retry), danach `iter.sh --slot gui all --strict --part gui`; `rest` = `iter.sh all --strict --part rest`. Je Teil `AH_OUT_DIR=$OUT/<teil>`, Log `$OUT/all-<teil>.log`, Exit-Code und Sekunden in `$OUT/<teil>.rc` (ein `wait`-Status 127 wird nicht als Ergebnis gelesen). Ein `trap` auf INT/TERM/HUP beendet beide Jobs. Nach beiden Jobs je Teil die Auswertung aus T8 mit Etikett `rest`/`gui`; Wiederholungen roter Schritte auf der Box ihres Teils (`iter.sh --slot …`). Kann die GUI-Box nicht geleast werden, ist Teil `gui` `infra` („warm box could not be leased (gui)“), der Lauf `UNVERIFIED` (T12 ändert das). Kombination: `infra` in einem Teil → `UNVERIFIED`, der Grund nennt den Teil und einen roten anderen Teil („FAIL in part rest“), auch wenn dieser später ausgewertet wird; sonst `FAIL`, wenn ein Teil rot bleibt; `PASS` nur mit zwei grünen Teilen. Report: Summary-Zeilen mit Etikett (`[rest] run.sh[all]: …`), alle Schritte beider Teile mit Sekunden und Box, **eine** Ebenen-Zeile `all|-|<urteil>|<wandzeit>|<box-rest>+<box-gui>|rest <s> s, gui <s> s`; `steps-all.tsv` mit vierter Spalte Teil; JUnit beider Teile nach `$OUT/junit/`, Screenshots und Logs unter `$OUT/<teil>/`. `history.csv` im heutigen Format. `weekly` übergibt dem Capstone weiter die Box des Slots `desktop` (`:878`).
Tests in `heavy_test.sh`: Die Shims werden je Slot geführt: Der `iter.sh`-Shim liest `--slot` (Default `desktop`) und führt Zähler, Artefakt (`artifact-<slot>.json`; `desktop` fällt auf `artifact.json` zurück), `SHIM_ITER_SEQ_<SLOT>` und `SHIM_ITER_OUT_<SLOT>` je Slot; der `gui`-Teil ist ohne Vorgabe grün mit einem kleinen Artefakt. Der `warm.sh`-Shim protokolliert die Rolle und kennt `SHIM_WARM_RC_GUI`. Neue Fälle: beide grün → `PASS`, `history.csv` mit den Schritten beider Teile und genau einer Ebenen-Zeile mit `<box>+<box>`; die Report-Zeile jedes Schritts trägt seine Sekunden, `steps-all.tsv` hat Zeilen beider Teile; beide Teile laufen gleichzeitig (der Shim schläft und schreibt Start- und Endzeit, die Zeiträume überlappen); `gui` dreimal rot mit gleichem Marker, `rest` grün → `FAIL`, die Wiederholungen liefen mit `--slot gui`; `gui` `strict-failed`, `rest` grün → `UNVERIFIED` mit `gui` im Grund; `gui` infra und `rest` rot → `UNVERIFIED`, der Grund nennt das FAIL; GUI-Box nicht leasbar → `UNVERIFIED`, nie `PASS`; ein Teil ohne Artefakt und ohne Summary-Zeile → `UNVERIFIED`. Bestehende Fälle behalten ihre Assertions; ändert sich eine erwartete Zahl gewollt (etwa „three step rows + one layer row“, `:247`), nennt der Commit-Body Stelle und Grund. Kein Test wird gelöscht.
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: `DEVELOPMENT.md` Wochenlauf (`:1252ff`, `:1268`, Historie `:1297`), `docs/developer/cicd.html` (`:151-176`) und `docs/en/developer/cicd.html` (`:150-174`): `all` = zwei Boxen parallel, Teil `gui` und `rest`, Urteil nur mit zwei grünen Teilen, die Ebenen-Zeile. `.claude/skills/test/SKILL.md`: `:49` (Dauer; „etwa 1 h, nicht verifiziert bis zum ersten Lauf“), `:52` (die Summary-Zeilen der beiden Teile), `:96`. `CHANGELOG.md` `[Unreleased]` → `### Changed`: „**Sammellauf auf zwei Boxen parallel (R-0603):** …“.
Abhängt von: T3, T4, T5, T7, T8

### T10 — heavy.sh: die GUI-Box geht vor einer Zweit-VM-Prüfung und vor dem Capstone  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ecd561e2 2026-10-21T17:06:12+02:00
Review: approve (.ah-out/review/heavy-parallel/T10.verdict.json)
Änderung: Bevor `second_vm_check` die Box der Lane `w2` least (`:580`) und bevor `run_capstone` im Modus `weekly` startet (`:862-880`), gibt `heavy.sh` die GUI-Box frei, wenn der Lauf sie noch hält: `bash "$WRAPPERS/reap.sh" --role gui` (einmal je Lauf; ein Scheitern ist eine Notiz, über den nächsten Klon entscheidet die Kapazitätsprüfung von `vm.py`). Warum (Kommentar): Mit zwei gehaltenen Boxen passt die dritte bzw. passen die Capstone-Rollen nicht, ein Kandidat endete `unbestaetigt` statt `reg`/`extern`, der Capstone `UNVERIFIED`. Der Report nennt die Freigabe in den Notizen. `AH_HEAVY_WRAPPERS` deckt `reap.sh` mit ab (heute nur `warm.sh`/`iter.sh`/`multibox.sh`, `:80-84`).
Tests in `heavy_test.sh` (ein `reap.sh`-Shim im Wrapper-Verzeichnis, der seine Argumente protokolliert): Kandidat in Teil `rest` (Muster 4g, `:411`) → `reap.sh --role gui` vor dem `warm.sh` der Lane `w2`; `weekly` → `reap.sh --role gui` vor `multibox.sh`; ein grüner `all` ohne Kandidat → kein `reap.sh`-Aufruf (das entscheidet T11).
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: `DEVELOPMENT.md` Wochenlauf und `cicd.html` DE/EN (Absatz zur zweiten VM, DE `:188-195`, EN `:186-193`): ein Satz zur Freigabe.
Abhängt von: T6, T9

### T11 — heavy.sh: die GUI-Box nach einem grünen GUI-Teil freigeben  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html, .claude/skills/test/SKILL.md, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @95958cfb 2026-10-21T17:33:50+02:00
Review: approve (.ah-out/review/heavy-parallel/T11.verdict.json)
Änderung: Empfehlung gebaut: Am Ende von `all` gibt `heavy.sh` die GUI-Box frei (`reap.sh --role gui`), wenn Teil `gui` grün ist (kein roter Schritt nach der Klassifikation, kein `infra`); ist er rot, bleibt sie zur Sichtung stehen, sofern T10 sie nicht schon freigegeben hat, und die Notiz nennt `vm.py ssh <vmid>`. Warum (Kommentar): Die Wandzeit bestimmt Teil `rest`; eine warm gehaltene GUI-Box spart dem Lauf kaum Zeit, hielte aber ihren RAM bis zum Ablauf ihrer Frist.
Tests in `heavy_test.sh`: `gui` grün → `reap.sh --role gui` am Ende, die Notiz nennt es; `gui` rot (flaky ausgenommen) → kein `reap.sh`, die Notiz nennt die Box; Modus `capstone` → kein `reap.sh`.
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: `DEVELOPMENT.md` Wochenlauf, `cicd.html` DE/EN, `.claude/skills/test/SKILL.md` (welche Box nach dem Lauf stehen bleibt).
Abhängt von: T10

### T12 — heavy.sh: zweite Box nicht zu bekommen, Teil gui seriell auf der ersten  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh, DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @89c7ab89 2026-10-21T18:06:56+02:00
Review: approve (.ah-out/review/heavy-parallel/T12.verdict.json)
Änderung: Empfehlung gebaut: Scheitert `warm.sh gui` auch im Retry (nicht bei Exit 2, das bleibt `UNVERIFIED`), fährt `heavy.sh` nach Teil `rest` den Teil `gui` auf der Box `desktop`: `iter.sh all --strict --part gui`, Auswertung wie in T9 mit Etikett `gui`. Der Report sagt es in einer Notiz mit der letzten Zeile aus `warm.log` (maskiert wie jede Notiz). Der Pre-flight fragt `doctor` dann nur nach `desktop` (wenn ihr Slot keine laufende Box hat); ob die GUI-Box passt, entscheidet die Kapazitätsprüfung von `vm.py clone`. Das Urteil bleibt: `PASS` nur mit zwei grünen Teilen.
Tests in `heavy_test.sh`: `SHIM_WARM_RC_GUI=1` → Teil `gui` läuft danach mit Slot `desktop` und `--part gui`, das Urteil folgt den beiden Artefakten, die Notiz nennt den seriellen Lauf; `SHIM_WARM_RC_GUI=2` → `UNVERIFIED`, kein serieller Lauf; `doctor` wird nicht mit `gui` gefragt.
Verify: bash scripts/dev/verify.sh scripts --strict -- heavy_test
Doku: `DEVELOPMENT.md` Wochenlauf, `cicd.html` DE/EN: was ohne zweite Box geschieht.
Abhängt von: T9
