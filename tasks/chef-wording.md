<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket chef-wording: „Aufsicht“ heißt „Chef“ (R-0272) — Task-Ledger
Status: freigegeben · Branch: harness/chef-wording · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket aus R-0272, Triage Kevin 2026-10-10; die Bruecke in CLAUDE.md kuerzt Kevin selbst oder auf sein Wort; Bau nach dem Merge von loop-harness-2; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0272 (Kurz-Ledger ohne Spec)
Heavy: none — nur Wortlaut in Skills, Doku und einem PR-Text von ledger-loop.sh samt Test; kein Stack-, Gateway-, PKI- oder Install-Pfad.
Hängt ab von: loop-harness-2 (Worker B) — es ändert build-task/SKILL.md und DEVELOPMENT.md; erst nach dessen Merge
bauen und origin/main vorher hineinmergen.
DoD je Task: CLAUDE.md (Tests grün, shellcheck/ruff sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker A für den Chef (adminhelper-ac). Kevin hat die Zeile am 2026-10-10 angenommen.
Zeilenangaben origin/main@710b68a2; beim Bau frisch greppen und an Symbolen orientieren.

Vorab geprüft:
- Seit #119 nennt CLAUDE.md §2 die Rolle „Chef“, mit der Brücke „(bisher „Aufsicht“; Skills und AUTONOMOUS.md sagen es noch
  so)“. Die Brücke bleibt; CLAUDE.md ändert dieses Ledger nicht (Frage am Gate).
- Gezählt mit `grep -P '(?<![A-Za-zäöü])Aufsicht'` (also ohne „unbeaufsichtigt“, „beaufsichtigte“), 30 Stellen:

  | Datei | Stellen | Zeilen |
  |---|---|---|
  | `.claude/skills/feature-build/SKILL.md` | 9 | :3, :9, :43, :50, :183, :291, :292, :300, :301 |
  | `.claude/skills/feature-plan/SKILL.md` | 1 | :245 |
  | `.claude/skills/roadmap/SKILL.md` | 4 | :19, :21, :78, :83 |
  | `AUTONOMOUS.md` | 10 | :27, :44, :46, :57, :113, :240, :285, :420 |
  | `DEVELOPMENT.md` | 2 | :1138, :1168 |
  | `scripts/dev/ledger-loop.sh` | 2 | :75, :934 |
  | `scripts/tests/ledger_loop_test.sh` | 2 | :663, :674 |

- Bleiben, wie sie sind:
  - die Specs unter `docs/features/` und die Ledger unter `tasks/`, denn sie halten fest, wer damals entschied;
  - CHANGELOG;
  - `skill_consistency_test`: dessen Fixtures prüfen den Wortlaut von CLAUDE.md samt Brücke.
- Wortregel: „die Aufsicht“ und „die Aufsichts-Session“ werden zu „der Chef“, in der jeweiligen Form („des Chefs“, „dem
  Chef“, „ohne Chef“). Der Satzbau wird dabei nur so weit angepasst, wie die Grammatik es verlangt.

### T1 — Die Skills sagen „Chef“  [ ]
Komponente: scripts · Dateien: .claude/skills/feature-build/SKILL.md, .claude/skills/feature-plan/SKILL.md, .claude/skills/roadmap/SKILL.md
Änderung:
- Die 14 Stellen der Tabelle in den drei Skills werden nach der Wortregel zu „Chef“.
- Sonst ändert sich kein Wort; an keiner Regel, keinem Ablauf und keinem Beispiel wird etwas umgebaut.
- Danach liefert `grep -P '(?<![A-Za-zäöü])Aufsicht' .claude/skills/` nichts mehr.
Rot vorher: Auf main ergibt `grep -o -P '(?<![A-Za-zäöü])Aufsicht' -r .claude/skills/ | wc -l` 14.
Beweis: origin/main@710b68a2, die Tabelle oben.
Dedup-Key: ref:docs:wording:aufsicht-chef
HEAD: 710b68a2
Semantik: CLAUDE.md §2 „Der **Chef** (bisher „Aufsicht“; Skills und AUTONOMOUS.md sagen es noch so) ist die eine
Session, die Kevin ausdrücklich als Chef gestartet oder benannt hat“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die Skills selbst

### T2 — AUTONOMOUS.md und DEVELOPMENT.md sagen „Chef“  [ ]
Komponente: scripts · Dateien: AUTONOMOUS.md, DEVELOPMENT.md
Änderung:
- Die Stellen der Tabelle in AUTONOMOUS.md (ohne :285, das zum PR-Text von T3 gehört) und in DEVELOPMENT.md werden nach
  der Wortregel zu „Chef“. Sonst ändert sich nichts.
Rot vorher: Auf main ergibt `grep -o -P '(?<![A-Za-zäöü])Aufsicht' AUTONOMOUS.md DEVELOPMENT.md | wc -l` 12; nach T2 bleibt nur :285 (T3).
Beweis: origin/main@710b68a2, die Tabelle oben.
Dedup-Key: ref:docs:wording:aufsicht-chef
HEAD: 710b68a2
Semantik: wie T1.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die beiden Dateien selbst; beide gibt es nur auf Deutsch

### T3 — Der PR-Text von ledger-loop.sh sagt „fährt der Chef“  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh, AUTONOMOUS.md
Änderung:
- ledger-loop.sh (:934) schreibt in `pr-body.md` „**Heavy offen — fährt die Aufsicht.**“. Neu: „**Heavy offen — fährt
  der Chef.**“. Der Kommentar (:75) zieht mit.
- ledger_loop_test (:663, :674) erwartet den neuen Satz. Das sind Shell-Prüfungen, für diff-scan keine Assertions.
- AUTONOMOUS.md :285 zitiert den Satz und zieht im selben Commit mit, damit Doku und Code nicht auseinanderlaufen.
Rot vorher: Auf main schreibt der Loop „fährt die Aufsicht“.
Beweis: origin/main@710b68a2, ledger-loop.sh :934.
Dedup-Key: ref:docs:wording:aufsicht-chef
HEAD: 710b68a2
Semantik: wie T1.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: AUTONOMOUS.md :285
