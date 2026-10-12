<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket harness-text: Review-Modell, Lane-Bedingung, Docker-Kommentar (R-0298, R-0299, R-0300) — Task-Ledger
Status: bereit · Branch: harness/harness-text · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-12 (kleines Fund-Paket aus R-0298, R-0299, R-0300, Triage Kevin 2026-10-11; CLAUDE.md ist die Vorlage, keine Änderung daran; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0298, R-0299, R-0300 (Kurz-Ledger ohne Spec)
Heavy: none — Skill-Texte, AUTONOMOUS.md und zwei Kommentare unter scripts/tests mit hermetischen Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-12 von Worker A für die Aufsicht (adminhelper-ac). Kevin hat die drei Zeilen am 2026-10-11 in der
Triage als Harness-Paket angenommen. Zeilenangaben origin/main@3200e421, also nach #119 (Regeln des Teams); beim Bau an
Symbolen orientieren.

Vorab geprüft:
- CLAUDE.md sagt schon, was die Texte hier nachziehen; dort ist nichts zu ändern.
  - :43–44 (Modelle) „Sonnet nur im Review je Task außerhalb der Risikopfade (`review.sh risk`); den ganzen
    Branch prüft Opus.“
  - :37–38 (Deckel) „1 VM-Lauf zugleich (`/test`, `heavy.sh`, `multibox.sh`; eine stehende Warm-Box zählt nicht)“.
  - §8 (:203) „Die Dev-Box hat Docker, aber kein Display.“ Der Auftrag, CLAUDE.md §8 auf die Docker-Aussage zu
    prüfen, ergibt also keinen §-Punkt für Kevin.
- feature-build sagt für den Review über den Branch schon Opus (:281, mit Prüfung `branch_review_opus` in
  skill_consistency_test). Es fehlen feature-review und AUTONOMOUS.md.
- Die übrigen „no docker“-Stellen unter scripts/tests sind richtig und bleiben: Sie sagen, dass ein hermetischer Test
  kein Docker braucht (desktop_e2e_skip_test :16, heavy_test :12, run_flags_test :9, init-secrets_test :5,
  diagnostics_test :3, check_versions_test :9, run.sh :15, :757). Falsch sind nur die beiden Aussagen über die
  Dev-Box (T3).

### T1 — feature-review und AUTONOMOUS.md: je Task Sonnet, über den ganzen Branch Opus (R-0298)  [x]
Komponente: scripts · Dateien: .claude/skills/feature-review/SKILL.md, AUTONOMOUS.md, scripts/tests/skill_consistency_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @f221ab67 2026-10-12T07:42:01+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- feature-review/SKILL.md:10–11 sagt heute „Läuft auf **Sonnet** — Opus nur bei einem Risikopfad im Diff
  (`feature-build`, Schritt 4)“. Neu:
  - Je Task läuft der Review auf Sonnet, Opus bei einem Risikopfad (`feature-build`, Schritt 4, `review.sh risk`).
  - Der Review über den ganzen Branch läuft immer auf Opus, auch der eine Review am Ende eines Kurz-Ledgers
    (CLAUDE.md §2 „Modelle“).
- AUTONOMOUS.md, Absatz „Zwei Review-Ebenen“ (:82–91): Der eine `feature-review` über den ganzen Branch-Diff eines
  Kurz-Ledgers (:88–89) läuft auf Opus. Die Tabelle (:46, Phase 4) nennt beim Review über den ganzen Branch Opus.
- `skill_consistency_test.sh` prüft:
  - In der Einleitung von feature-review (vor „**Wichtig:**“) nennt ein Satz den ganzen Branch und Opus;
  - im Absatz „Zwei Review-Ebenen“ von AUTONOMOUS.md ebenso;
  - je eine Fixture mit dem alten Text fällt;
  - die bestehende Prüfung `branch_review_opus` für feature-build bleibt grün.
Rot vorher: Die neue Prüfung fällt auf main. Die Einleitung von feature-review sagt nur Sonnet mit Opus beim Risikopfad,
AUTONOMOUS.md nennt beim Kurz-Ledger kein Modell.
Beweis:
- Review im Bau team-rules T3 (Opus), harness/team-rules@05986330.
- origin/main@3200e421:
  - `sed -n 10,11p .claude/skills/feature-review/SKILL.md` gibt „Läuft auf **Sonnet** — Opus / nur bei einem
    Risikopfad im Diff“;
  - `sed -n 88,89p AUTONOMOUS.md` gibt „ein `feature-review` über / den ganzen Branch-Diff“, ohne Modell.
- Wer den Reviewer startet und nur den Skill liest, nimmt für den Review am Ende Sonnet, außer `review.sh risk` meldet
  einen Risikopfad.
Dedup-Key: ref:skills:feature-review:branch-review-opus
HEAD: 3200e421
Semantik: CLAUDE.md:43–44 „Sonnet nur im Review je Task außerhalb der Risikopfade (`review.sh risk`); den ganzen
Branch prüft Opus. Nie prüft Sonnet, was Sonnet baute.“ Die Regel steht in CLAUDE.md, nicht unter docs/.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: AUTONOMOUS.md (zwei Stellen); der Skill-Text ist die Anleitung

### T2 — Die Lane-Bedingung folgt dem VM-Deckel (R-0300)  [x]
Komponente: scripts · Dateien: .claude/skills/feature-plan/SKILL.md, AUTONOMOUS.md, scripts/tests/skill_consistency_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @37180b5f 2026-10-12T07:54:26+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- feature-plan/SKILL.md, „Lanes aktiv vorschlagen“ (:225–228) und AUTONOMOUS.md, „Lanes komponenten-disjunkt
  schneiden“ (:207–211) setzen heute „braucht höchstens eines der beiden VMs“ als Bedingung für den Lane-Vorschlag.
- Neu:
  - Die Bedingung entfällt.
  - An ihrer Stelle steht der Deckel aus CLAUDE.md §2: 1 VM-Lauf zugleich, eine stehende Warm-Box zählt nicht.
    Brauchen beide Vorhaben VMs, laufen ihre VM-Läufe nacheinander.
  - Disjunkt und ohne gemeinsame Test-Datenbank bleiben die Bedingungen.
- `skill_consistency_test.sh` prüft für beide Stellen:
  - Der Absatz nennt den Deckel („1 VM-Lauf zugleich“) und nicht mehr „höchstens eines“;
  - eine Fixture mit dem alten Absatz fällt;
  - eine mit dem neuen Absatz, aber ohne Deckel, fällt auch.
Rot vorher: Die neue Prüfung fällt auf main, denn beide Absätze tragen „höchstens eines“ und keinen VM-Deckel.
Beweis:
- Opus-Review über den Branch team-rules, harness/team-rules@009c442d.
- origin/main@3200e421: `grep -n 'höchstens eines' .claude/skills/feature-plan/SKILL.md AUTONOMOUS.md` trifft :227 und
  :210; CLAUDE.md:37–38 nennt nur den VM-Lauf als Deckel.
Dedup-Key: ref:skills:feature-plan:lane-vm-condition
HEAD: 3200e421
Semantik: CLAUDE.md:37–38 „**Deckel:** 2 Bau-Slots (zwei Ledger `aktiv`, nur disjunkt: AUTONOMOUS.md
„Parallel-Betrieb“) · 1 VM-Lauf zugleich (`/test`, `heavy.sh`, `multibox.sh`; eine stehende Warm-Box zählt nicht)“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: AUTONOMOUS.md (eine Stelle); der Skill-Text ist die Anleitung
Abhängt von: T1

### T3 — run.sh und heavy.sh: die Dev-Box hat Docker, aber kein Display (R-0299)  [x]
Komponente: scripts · Dateien: scripts/tests/run.sh, scripts/tests/heavy.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @9300f432 2026-10-12T08:05:11+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- run.sh:39 („because the dev box has no docker and no display while a VM box has both“) und heavy.sh:67 („from
  .devenv.sh: no docker, no display, so no heavy ids“) nennen den richtigen Grund.
  - Die Dev-Box hat Docker, aber kein Display.
  - Ihre schweren Schritte laufen auf VMs (CLAUDE.md §6 und §8).
  - Deshalb trägt das `AH_REQUIRED` der Dev-Box keine schweren Schritte.
- Nur Kommentare. Am Verhalten ändert sich nichts.
- Ein Test kommt nicht dazu (CLAUDE.md §6: bewusst nicht Testenswertes, hier ein Kommentar). Die Suite muss vorher
  und nachher grün sein.
- heavy.sh ändert sich nur im eigenen Worktree. Ein Wochenlauf aus dem Haupt-Checkout liest seine eigene Kopie.
Rot vorher: entfällt (Kommentar). Metrik und Beweis zeigen den Ist-Stand.
Beweis: origin/main@3200e421: `grep -nE 'dev box has no docker|no docker, no display, so no heavy' scripts/tests/run.sh
scripts/tests/heavy.sh` trifft :39 und :67. Die Dev-Box hat Docker: `run.sh quick` druckt `docker=yes … display=no`.
Metrik: derselbe grep: 2 → 0 Treffer.
Dedup-Key: ref:scripts:run.sh:no-docker-comment
HEAD: 3200e421
Semantik: CLAUDE.md:203 „Die Dev-Box hat Docker, aber kein Display. Schwere Suiten laufen auf ephemeren
Proxmox-VMs“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Kommentare)

### T4 — Nachbesserung aus dem Review am Ende: der Modell-Absatz in AUTONOMOUS.md, schärfere Prüfungen (R-0298, R-0300)  [x]
Komponente: scripts · Dateien: AUTONOMOUS.md, scripts/tests/skill_consistency_test.sh, .claude/skills/feature-review/SKILL.md, .claude/skills/feature-plan/SKILL.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @7fcde6fa 2026-10-12T08:26:36+02:00
Review: Nachbesserung, Opus-Review über den Diff der Nachbesserungen folgt
Änderung: Angelegt 2026-10-12 aus dem Review am Ende (Opus, `request_changes`: zwei belegte Funde, drei nits).
- AUTONOMOUS.md, Absatz zum Modell (:59–64), sagt allgemein „Der **Reviewer** ist die Ausnahme: er läuft auf
  **Sonnet** und nur dann auf Opus, wenn `review.sh risk` einen Risikopfad … meldet“. Wer dort nachschlägt, nimmt für
  den Review am Ende eines Kurz-Ledgers Sonnet. Das ist dieselbe Lücke wie in T1, an einer Stelle, die T1 nicht sah.
  - Neu: „Der **Reviewer je Task**“, dazu der Satz, dass den Review über den ganzen Branch immer Opus fährt
    (CLAUDE.md §2 „Modelle“).
  - `skill_consistency_test` prüft diesen Absatz mit `whole_branch_opus`.
- `whole_branch_opus` (T1) ließ zwei Texte durch:
  - „Je Task und über den ganzen Branch läuft er auf Sonnet, Opus nur bei einem Risikopfad.“
  - „Den Review über den ganzen Branch fährt nicht Opus, sondern Sonnet.“
  - Neu: Ein Satz zählt nur, wenn er „ganzen Branch“ und „Opus“ nennt, aber weder „Sonnet“ noch „nicht“. Je eine
    Fixture für beide Fälle fällt.
- Nits aus demselben Review:
  - `lane_vm_cap` (T2) erkennt „höchstens eines“ auch über einen Zeilenumbruch und als „höchstens einer“.
  - feature-review nennt beim Risikopfad `review.sh risk`.
  - feature-plan sagt „zwei der Deckel“, denn CLAUDE.md §2 nennt einen dritten, das Wochenlimit.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: AUTONOMOUS.md (eine Stelle); der Skill-Text ist die Anleitung
Abhängt von: T3
