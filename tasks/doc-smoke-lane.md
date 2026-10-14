<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket doc-smoke-lane: doc-smoke --env ohne Lücken, und ein angehängter Worktree ohne Lane läuft nicht still auf main (R-0215, R-0211) — Task-Ledger
Status: aktiv · Branch: harness/doc-smoke-lane · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-14 (kleines Fund-Paket, Triage Kevin 2026-10-07; F1 Variante A auf Kevins Wort 2026-10-14: nur angehaengte Worktrees ohne Lane werden abgewiesen; Review am Ende Opus; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0215, R-0211 (Kurz-Ledger ohne Spec)
Heavy: none — doc-smoke.py mit doc_smoke_test (Fixture-Repos), vm.py mit test_vm.py (Fixture-Checkouts, git worktree in tmp), lib.sh mit lib_vm_test; keine echte VM.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku DE+EN im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-14 von Worker A für den Chef (adminhelper-ac). Kevin hat beide Zeilen am 2026-10-07 angenommen
(„Kleinpaket-5, nach dem Merge-Stapel“). Zeilenangaben origin/main@26125c5a; beim Bau an Symbolen orientieren.

Vorab geprüft:
- doc-smoke.py `_repo_words` (:152–204):
  - Es fährt `git grep` mit vier `-c`-Optionen (:173–180), damit eine Nutzer-Konfiguration die Ausgabe nicht verändert:
    Zeilennummern, Spalten, Farbe und `fallbackToNoIndex` außerhalb eines Repos. Kein Test hält sie fest
    (doc_smoke_test.sh: kein `GIT_CONFIG_GLOBAL`).
  - `except OSError: return None` (:194) fällt still auf config.py und .env.example zurück, wenn git fehlt. Der Zweig mit
    einem Exit-Code von git meldet sich auf stderr (:198–202).
  - `_REPO_WORD_EXCLUDES` (:71) nimmt docs/, CHANGELOG.md und tasks/ aus. Markdown außerhalb von docs/ (README.md,
    DEVELOPMENT.md, AUTONOMOUS.md, .claude/) zählt als Träger. Ein Name, der in docs/ und in einer dieser Dateien
    zugleich veraltet ist, fällt nicht auf.
  - Probe auf dem echten Baum: Mit `:!*.md` dazu meldet `doc-smoke.py --env` weiter „documentation matches the tree“
    (rc 0). Der Ausschluss kostet heute also nichts.
- Lane (R-0211):
  - `vm.py current_lane` (:583–595) und lib.sh `vm_lane` (:82–95) nehmen `--lane`, sonst `AH_LANE`, sonst `.vm/lane`,
    sonst `main`.
  - `lane.sh new` schreibt `.vm/lane`, ein von Hand angelegter Worktree (`git worktree add`, etwa die harness/-Worktrees
    unter ~/.cache) hat keine. Er läuft dann auf Lane main, der Lane des Haupt-Checkouts. Dort gelten `reap`, der
    Expired-Sweep und „ours“ in `vm.py list` für main.
  - Beide Funktionen prüfen den eigenen Zustand schon heute: `own_state` / `require_untracked_state` in vm.py, der
    Abgleich von `AH_VM_STATE_DIR` mit `$VM_ROOT/.vm` in lib.sh. Tests mit eigenem Zustandsverzeichnis (lib_vm_test,
    vm_wrappers_test, test_vm.py) sind davon nicht betroffen.
  - Angehängter Worktree heißt: `git rev-parse --git-dir` und `--git-common-dir` zeigen auf verschiedene Verzeichnisse.

## Offene Frage (für Kevin, über den Chef)

**F1: Wie streng wird Lane main?** Der Ansatz ist offen, es ist eine Sperrregel für Läufe unter Kevins Benutzer.
- **A (Empfehlung):** Nur ein angehängter Worktree mit eigenem `.vm`, ohne `.vm/lane`, ohne `AH_LANE` und ohne
  `--lane` wird abgewiesen (Exit 2 mit Hinweis: `AH_LANE=<lane>` setzen, oder ausdrücklich `AH_LANE=main`).
  - Der Haupt-Checkout behält main als Default, an Kevins Handgriffen ändert sich nichts.
  - Lanes aus `lane.sh new` sind nicht betroffen.
  - Ein Worker-Lauf auf main braucht künftig `AH_LANE=main`. Das ist genau die Stelle, an der heute still main
    genommen wird.
- **B:** Jeder Lauf auf main braucht `AH_LANE=main`, auch im Haupt-Checkout. Das ist strenger und ändert Kevins
  Handgriffe (warm, iter, reap, heavy).
- **C:** Keine Sperre, nur Doku. Die Lücke bleibt.

T2 und T3 sind für A geschrieben. Bei B ändert sich in beiden nur die Bedingung, bei C entfallen beide.

### T1 — doc-smoke --env: Tests für die git-Optionen, ein lauter Rückfall ohne git, Markdown trägt keine Namen (R-0215)  [x]
Komponente: scripts · Dateien: scripts/dev/doc-smoke.py, scripts/tests/doc_smoke_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @74028c1d 2026-10-14T06:55:10+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- (a) Fälle in doc_smoke_test, mit `GIT_CONFIG_GLOBAL` auf eine Datei im Arbeitsverzeichnis des Tests und
  `GIT_CONFIG_NOSYSTEM=1`:
  - `grep.lineNumber=true`, `grep.column=true`, `color.grep=always` → der Name aus einem getrackten Skript bleibt bekannt
    („matches the tree“);
  - außerhalb eines Repos `grep.fallbackToNoIndex=true` → nur config.py und .env.example zählen, wie im bestehenden Fall.
- (b) `except OSError` meldet sich auf stderr wie der Zweig mit Exit-Code: „git not found; --env falls back to config.py
  and .env.example“. Fall: PATH ohne git (nur ein Verzeichnis mit `python3`) → die Meldung steht in der Ausgabe, und ein
  Name nur aus einem getrackten Skript ist ein Fund.
- (c) `_REPO_WORD_EXCLUDES` bekommt `:!*.md`. Docstring, Hilfetext, cicd.html DE+EN (:416–417 bzw. :409) und
  DEVELOPMENT.md (:377–378) nennen Markdown als ausgenommen. Fall: ein Name nur in README.md → Fund.
Rot vorher:
- (c): Auf main ist ein Name nur in README.md bekannt, kein Fund.
- (b): Ohne git schweigt `--env` über den Rückfall.
- (a): Mit `grep.lineNumber=true` fehlt die Option. Das zeigt die Mutation „`-c grep.lineNumber=false` entfernt“ →
  der neue Fall wird rot.
Beweis: origin/main@26125c5a, doc-smoke.py :71, :173–180, :194. Fund: Review R-0044 Runde 2, Worker A, 2026-10-06
(harness/doc-env-triage@c8abd5ad).
Dedup-Key: ref:scripts:doc-smoke.py:env-followups
HEAD: 26125c5a
Semantik: doc-smoke.py, Docstring: „Only names nothing else carries are reported“; DEVELOPMENT.md :377–378.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html, DEVELOPMENT.md

### T2 — vm.py: ein angehängter Worktree ohne Lane läuft nicht still auf main (R-0211, Ansatz A)  [ ]
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/tests/test_vm.py, DEVELOPMENT.md
Änderung:
- `current_lane` (:583–595): Ist der Zustand der eigene (`own_state`), kommt die Lane weder aus `--lane` noch aus
  `AH_LANE` noch aus `.vm/lane`, und ist der Checkout ein angehängter Worktree, dann `Usage`.
  - Die Meldung: „this worktree has no .vm/lane — set AH_LANE=<lane>, or AH_LANE=main to run on the main checkout's
    lane on purpose“.
  - Geprüft wird über `git rev-parse --git-dir --git-common-dir` ohne geerbtes GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE, wie
    `require_untracked_state`.
- Fälle in test_vm.py, als neue Testfunktionen am Dateiende, mit einem echten `git worktree add` unter tmp_path:
  - angehängter Worktree ohne Lane → Usage;
  - derselbe mit `AH_LANE=main` bzw. `--lane main` → `main`;
  - mit `.vm/lane` → die Lane;
  - der Haupt-Checkout ohne Lane → `main` wie heute.
- DEVELOPMENT.md, Lane-Absatz (:1792–1796): ein Satz zur Regel.
Rot vorher: Auf main liefert `current_lane` im angehängten Worktree ohne Lane still `main`.
Beweis: origin/main@26125c5a, vm.py :595 `return tag_safe(lane) or "main"`. Fund: Worker B, Heavy-Lauf R-0064,
2026-10-06 (../AdminHelper-harness-b ohne .vm/lane).
Dedup-Key: ref:scripts:vm/lib.sh:vm_lane-default-main
HEAD: 26125c5a
Semantik: DEVELOPMENT.md :1792–1796 „… sonst ist sie `main` — der Hauptcheckout“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Lane-Absatz)

### T3 — lib.sh vm_lane folgt derselben Regel, und lib_vm_test hält beide Seiten gleich (R-0211, Ansatz A)  [ ]
Komponente: scripts · Dateien: scripts/vm/lib.sh, scripts/tests/lib_vm_test.sh
Änderung:
- `vm_lane` (:82–95) wie T2: eigener Zustand, keine Lane aus `AH_LANE` oder `.vm/lane`, angehängter Worktree → Meldung
  auf stderr, `return 2`. Die Aufrufer (warm.sh :28, reap.sh :36, iter.sh :39) brechen schon heute mit Exit 2 ab.
- Fälle in lib_vm_test, mit einem echten `git worktree add` im Arbeitsverzeichnis des Tests:
  - angehängter Worktree ohne Lane → rc 2, die Meldung;
  - mit `AH_LANE=main` → `main`;
  - der Haupt-Checkout → `main`.
  - Dazu derselbe Fall gegen vm.py (wie der bestehende Abgleich :59–72): beide Seiten weisen ab.
Rot vorher: Auf main gibt `vm_lane` im angehängten Worktree ohne Lane `main` aus.
Beweis: origin/main@26125c5a, lib.sh :94 `printf '%s\n' "${lane:-main}"`.
Dedup-Key: ref:scripts:vm/lib.sh:vm_lane-default-main
HEAD: 26125c5a
Semantik: wie T2; lib_vm_test :59–64 „the two implementations have to agree“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (DEVELOPMENT.md zieht T2 mit)
Abhängt von: T2
