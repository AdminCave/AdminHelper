<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Loop-Harness 2: Suchen in der Bau-Session, das frpc-Sidecar im Builder-Klon, ein Symlink .vm — Task-Ledger
Status: bereit · Branch: harness/loop-harness-2 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket aus R-0319, R-0325, R-0326, Triage Kevin 2026-10-12; R-0319 Weg B: keine Allow-Regel fuer git grep, die Deny-Entscheidung R-0164 bleibt, der Skill verweist auf das Grep-Werkzeug; T3 mit eigener Testdatei; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0319, R-0325, R-0326 (Kurz-Ledger ohne Spec)
Heavy: none — Skill-Text und ein hermetischer Skill-Test, ein Einrichtungsskript des Builders mit hermetischem Test, eine Zeile `.gitignore`; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Kevin hat die drei Zeilen am 2026-10-12
angenommen. Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht.
Zeilenangaben origin/main@710b68a2. Alle Dateien sind Harness-Pfade oder liegen neben ihnen; den PR merged Kevin oder
die Aufsicht auf sein Wort. Disjunkt zu Worker As `harness/harness-lane-2` (`scripts/dev/lane.sh`,
`scripts/tests/lane_test.sh`, `scripts/dev/harness-paths.txt`, `scripts/tests/hooks_test.sh`, `DEVELOPMENT.md` bisher
ohne Hunk) und `harness/status-guard` (`scripts/dev/hooks/session-status.sh`, `scripts/vm/lib.sh`, `scripts/vm/vm.py`,
`scripts/tests/lib_vm_test.sh` u. a.); keine Task hier berührt sie.

### T1 — build-task: Suchen mit dem Grep-Werkzeug; `git grep` steht unter „Nie" (R-0319)  [x]
Komponente: scripts · Dateien: .claude/skills/build-task/SKILL.md, scripts/tests/skill_consistency_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b3fa5459 2026-10-13T02:28:38+02:00
Review: Review am Ende (Kurz-Ledger, Opus): approve in Runde 2
Befund und Empfehlung:
- Messlauf-5 hat fünf `permission_denials`, alle `Bash` mit `git grep` (`~/.cache/ah-builder/loop/loop-kleinpaket-3/`):
  - `T1.s1.json`: drei.
  - `T2.s1.json`: eine.
  - `T3.s1.json`: eine.
- Die Verweigerung ist eine Entscheidung, kein Versehen. `scripts/dev/runner-settings.json` hat `Bash(git grep:*)` in
  `deny`, und `scripts/tests/hooks_test.sh` hält das zweimal fest:
  - `:1535`: die Deny-Regel.
  - `:1599-1611`: keine Allow-Regel, die mit `Bash(git grep` beginnt, „R-0164: rg --pre, git grep -O, sed e/w“.
- `git grep -O`/`--open-files-in-pager` startet ein Programm. Eine Bash-Regel prüft den Kommandotext mit `*` als
  Platzhalter und kann ein `-O` an beliebiger Stelle nicht ausschließen; `hooks_test.sh:1126-1132` führt die Formen
  auf.
- **Empfehlung: keine Allow-Regel. R-0164 bleibt, der Skill verweist auf das Grep-Werkzeug.**
  - Das Grep-Werkzeug braucht im `dontAsk`-Modus der Bau-Session keine Regel, laut Doku
    (code.claude.com/docs/en/permissions, abgerufen 2026-10-13): Lesende Werkzeuge („File reads, Grep“) brauchen
    „No [approval], within the working directory“. `dontAsk` „Auto-denies every call that would otherwise prompt;
    file reads in your working directories and other actions that need no approval still run“.
  - `ledger-loop.sh:798-801` schränkt die Werkzeuge der Session nicht ein.
- Der Skill lädt heute zum Versuch ein: „Git nur lesend“ (`SKILL.md:74`).
Änderung:
- `SKILL.md`, Schritt 2 („Lesen“, `:24-26`): ein Satz, dass die Session mit dem Grep-Werkzeug sucht (Dateinamen mit
  Glob). `git grep` und `rg` verweigern die Settings, weil `git grep -O` und `rg --pre` ein Programm starten (R-0164).
- `SKILL.md`, „## Nie“ (`:73-74`): „Git nur lesend“ wird „Git nur lesend, und ohne `git grep`“.
- `skill_consistency_test.sh`:
  - `FORBIDDEN` (`:173`) nennt auch `git grep`. Ein `git grep …` als Anweisung außerhalb von „## Nie“ ist dann ein
    Fund.
  - Eine Fixture-Probe wie die für `git add` (`:420-433`) zeigt, dass der Check feuert.
  - Ein neuer Check verlangt, dass der Ablauf von build-task das Grep-Werkzeug nennt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine — der Skill ist der Text der Bau-Session (`docs/developer/cicd.html:327` nennt ihn nur); die Settings
ändern sich nicht
Beweis: Messlauf-5, Aufsicht 2026-10-12 (die `permission_denials`):
- `T1.s1.json`:
  - `git grep -n -E "include_router|enrollment_router" -- apps/server/app/main.py`
  - `git grep -n include_router -- apps/server/app/main.py`
  - `git grep -n devices -- apps/server/app/modules/users`
- `T2.s1.json`: `git grep -n test_alembic_consistency`
- `T3.s1.json`: `git grep -l "docs-pairs\|docs_pairs" -- scripts .github`
origin/main@710b68a2: `runner-settings.json` `deny` enthält `Bash(git grep:*)`; `SKILL.md:74` „Git nur lesend.“
Metrik: Verweigerungen von `git grep` je Bau-Session des Loops: 5 in Messlauf-5 → 0 im nächsten Lauf (gemessen am
nächsten Messlauf, nicht in diesem Paket).
Orakel: mutation-sample — ein `` `git grep -n x` `` als Anweisung in Schritt 2: `skill_consistency_test` rot; der
Satz zum Grep-Werkzeug fehlt: ebenso rot.
Dedup-Key: ref:scripts:runner-settings.json:git-grep-allow
HEAD: 710b68a2
Semantik: `scripts/tests/hooks_test.sh:1599-1601`: „the build session … no read command it may run brings a way to run
or write a program along (R-0164: rg --pre, git grep -O, sed e/w)“.

### T2 — builder-home.sh setup kopiert das frpc-Sidecar in den Klon (R-0325)  [x]
Komponente: scripts · Dateien: scripts/dev/builder-home.sh, scripts/tests/builder_home_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @8eb2fa82 2026-10-13T02:40:55+02:00
Review: Review am Ende (Kurz-Ledger, Opus): approve in Runde 2
Änderung:
- **`setup`:** Nach `setup_clone` (`builder-home.sh:147-165`) kopiert der Schritt `apps/desktop/src-tauri/binaries/`
  aus diesem Checkout (`$ROOT`) in den Klon (`$CLONE`), wie `lane.sh new` es für eine Lane tut (`lane.sh:322-338`):
  - `mkdir -p` und `cp -RpL --remove-destination`, also eine Kopie, kein Link.
  - Führt der Pfad im Klon aus dem Klon hinaus, wird nicht kopiert, mit einer WARN-Zeile.
  - Scheitert die Kopie, gibt es eine WARN-Zeile, und `setup` läuft weiter.
  - Hat `$ROOT` das Sidecar nicht, nennt eine WARN-Zeile die Folge: Desktop-Tasks sind nicht loop-tauglich.
- **`status`** (`do_status`, `:281`): Hat `$ROOT` das Sidecar und der Klon nicht, ist das ein „missing“ mit dem Hinweis
  auf `setup`.
- **Tests in `builder_home_test.sh`:** Die Fixture `$MAIN` bekommt ein Fake-Sidecar, das in ihrer `.gitignore` steht.
  - Nach `setup` liegt im Klon eine echte Datei, kein Symlink, mit demselben Inhalt.
  - Ohne Sidecar in `$MAIN`: eine WARN-Zeile, `setup` mit Exit 0.
  - Im Klon entfernt: `status` meldet es, Exit 1.
- **`DEVELOPMENT.md`**, Abschnitt „Das Builder-Profil“ (`:1198-1215`): ein Satz, dass `setup` das Sidecar aus diesem
  Checkout in den Klon kopiert.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Abschnitt Builder-Profil)
Beweis: origin/main@710b68a2:
- `ls ~/.cache/ah-builder/repo/apps/desktop/src-tauri/binaries` → „Datei oder Verzeichnis nicht gefunden“; der Klon
  steht auf b7ab9b6c.
- `setup_clone` (`builder-home.sh:147-165`) klont und spult vor, kopiert aber nichts, was git ignoriert.
- `lane.sh new` kopiert das Sidecar aus seinem `$ROOT`; im Loop ist das der Klon. Der Fundament-Lauf einer Desktop-Task
  bekäme `cargo test (desktop)` als SKIP und wäre unter `--strict` rot (Zeile R-0325).
Orakel: mutation-sample — der Kopierschritt fehlt: der neue Fall in `builder_home_test.sh` rot; der `status`-Check
fehlt: ebenso rot.
Dedup-Key: ref:scripts:builder-home.sh:sidecar
HEAD: 710b68a2
Semantik: `scripts/dev/lane.sh:322-324`: „Gitignored parts of the main checkout that a build needs. The frpc sidecar
cargo test wants is COPIED: a link would reach a box as a link into nothing“. Der Builder-Klon ist für den Loop dieser
Checkout.

### T3 — .gitignore: `/.vm` ignoriert auch einen Symlink .vm (R-0326)  [x]
Komponente: scripts · Dateien: .gitignore, scripts/tests/gitignore_test.sh, scripts/tests/run.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d6c249d1 2026-10-13T02:05:58+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung:
- `.gitignore`: Nach `.vm/` (`:62`) kommt die Zeile `/.vm`. Beide bleiben: `.vm/` trifft wie heute jedes Verzeichnis
  dieses Namens, `/.vm` zusätzlich den Eintrag an der Wurzel in jeder Form, auch als Symlink.
- `scripts/tests/gitignore_test.sh`, neu, SPDX-Kopf (`reuse annotate --copyright "Kevin Stenzel" --license
  GPL-3.0-or-later`), hermetisch:
  - Ein Wegwerf-Repo mit der echten `.gitignore` des Baums ignoriert `.vm` als Verzeichnis, `.vm/lane` und `.vm` als
    Symlink (`git check-ignore -q`).
  - Gegenprobe, dass der Check fallen kann: Mit einer `.gitignore`, die nur `.vm/` enthält, ist der Symlink nicht
    ignoriert.
  - Die Datei prüft ihren eigenen Eintrag in `AH_SCRIPT_TESTS_DEFAULT` (wie `builder_home_test.sh:274-275`).
- `scripts/tests/run.sh`: `gitignore_test` in `AH_SCRIPT_TESTS_DEFAULT`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Beweis: Probe (nicht committet, dreimal identisch), ein Wegwerf-Repo mit `ln -s elsewhere .vm`:
- mit `.gitignore` `.vm/`: `git check-ignore -q .vm` → rc 1;
- mit `.vm/` und `/.vm`: rc 0;
- als Verzeichnis mit `.vm/lane`: rc 0.
Metrik: Formen von `.vm` an der Wurzel, die git nicht ignoriert: 1 (Symlink) → 0.
Orakel: mutation-sample — die Zeile `/.vm` gestrichen: `gitignore_test` rot.
Dedup-Key: ref:repo:gitignore:vm-symlink
HEAD: 710b68a2
Semantik: keine Stelle in docs/ — gesucht nach `.vm` in `docs/developer/` und `DEVELOPMENT.md`. Im Repo:
`.gitignore:60-62`, „Lauf-Artefakte … bleiben lokal“. Ein `.vm` als Symlink ist Lauf-Zustand wie das Verzeichnis
(lane-reap-guard T6 fängt den Fall heute erst beim Anlegen einer Lane).
