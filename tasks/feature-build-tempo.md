<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# feature-build: schnellere Reviews und Testläufe — Task-Ledger (Kurz)
Status: aktiv · Branch: harness/feature-build-tempo · Commit-Granularität: pro Task · Review: am Ende (feature-review, ein Gesamt-Review) · Modell: Opus
Spec: .claude/skills/feature-build/SKILL.md und .claude/skills/feature-review/SKILL.md (Ist-Stand) — Kurz-Ledger, keine eigene Spec; Befunde aus den Bauten 2026-09-15/16 (audit-hygiene, ssrf-resolver-isolation)
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: keine (nur Skill- und Doku-Text)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: — (Harness-Hygiene, Kevin 2026-09-16) · Hängt ab von: —
Warnung (CLAUDE.md Trigger 4): dieser Ledger ändert Harness-Dateien unter `.claude/skills/` und `AUTONOMOUS.md` — von Kevin beauftragt.
Review-Nachtrag (2026-09-17, Gesamt-Review): `AUTONOMOUS.md` beschrieb dieselben zwei Regeln (Reviewer auf Opus; zwei Review-Ebenen immer) und war durch T1/T2 falsch geworden — nachgezogen (`.claude/rules/docs.md`: falsche Doku ist ein Bug). Dazu der neue DEVELOPMENT.md-Absatz an den Umlaut-Stil der Umgebung angeglichen.
Befund: In audit-hygiene liefen drei Reviewer-Subagenten je 20–35 min ohne Urteil und der abschließende `/code-review` 20 min; in ssrf-resolver-isolation dauerte Review-Runde 2 von T1 14 min, weil der Reviewer die Suiten selbst nachfuhr. Reviewer mit Sonnet liefen in 1–8 min. Dazu wurde einmal die volle Server-Suite parallel zu einem zweiten Lauf gegen dieselbe Test-DB gefahren und verworfen.

### T1 — Reviewer: Modell, Zeitbudget, Abbruchregel  [x] (Sonnet-Default + Risikopfad-Liste, 10-min-Budget, Abbruchregel)
Komponente: .claude · Dateien: .claude/skills/feature-build/SKILL.md, .claude/skills/feature-review/SKILL.md
Änderung: Im Build-Skill Schritt 4 („Frischer-Kontext-Review"): der Reviewer wird mit `model: sonnet` gestartet (Opus nur, wenn der Diff einen Risikopfad berührt: PKI/mTLS, Auth, SSRF, Migrationen, Release-Workflows — Liste im Skill); der Reviewer bekommt den Hinweis, die Schnellsuite **nicht** selbst nachzufahren, sondern die vom Builder zitierte Summary-Zeile zu prüfen und nur gezielte Mutations-Proben zu machen; liegt nach 10 Minuten kein Urteil vor, wird der Agent gestoppt und ein frischer mit engerem Prompt gestartet (einmal), danach Selbst-Review mit Kennzeichnung im Ledger. Im Review-Skill ein Absatz „Zeitbudget 10 Minuten, keine vollen Suiten".
Verify: grep -c 'model: sonnet' .claude/skills/feature-build/SKILL.md   (≥ 1)   und   grep -c '10 Minuten' .claude/skills/feature-build/SKILL.md .claude/skills/feature-review/SKILL.md   (je ≥ 1)
Doku: keine (die Skills sind die Doku)

### T2 — Kurz-Ledger: Review am Ende, kein zweiter Gesamt-Review  [x] (Kopf-Feld `Review:` in plan/build/README, `/code-review` entfällt bei `am Ende`)
Komponente: .claude · Dateien: .claude/skills/feature-build/SKILL.md, .claude/skills/feature-plan/SKILL.md, tasks/README.md
Änderung: Ein Ledger mit ≤ 3 Tasks (Kurz-Ledger) bekommt von `feature-plan` den Kopf `Review: am Ende`; `feature-build` fährt dann genau **einen** Frischer-Kontext-Review über den Branch-Diff und lässt den abschließenden `/code-review` weg (der eine Reviewer sieht denselben Diff). Große Ledger bleiben bei Review pro Task plus `/code-review`. `tasks/README.md`: Kopf-Konvention `Review: pro Task | am Ende` erklärt.
Verify: grep -n 'am Ende' .claude/skills/feature-build/SKILL.md .claude/skills/feature-plan/SKILL.md tasks/README.md   (je ≥ 1 Treffer)
Doku: tasks/README.md

### T3 — Testläufe: gezielt pro Task, voll vor dem Commit, nie parallel  [x] (zwei Test-Ebenen in Schritt 3, Ein-Lauf-Regel, tmux; DEVELOPMENT.md + CHANGELOG)
Komponente: .claude · Dateien: .claude/skills/feature-build/SKILL.md, DEVELOPMENT.md
Änderung: Schritt 3 des Build-Skills: pro Task nur das `Verify:` mit gezielten Args; die volle Komponenten-Suite einmal unmittelbar vor dem Commit; **nie zwei Testläufe gleichzeitig** (die Server-Suite teilt sich eine Postgres-Datenbank; ein paralleler Lauf ist verworfen, nicht rot); lange Läufe nicht als Hintergrund-Bash, sondern per tmux (D21). DEVELOPMENT.md „Python-Tests lokal": ein Satz zur geteilten Test-DB.
Verify: bash scripts/tests/run.sh lint --strict --only scripts   (Doku/Skill-Text; shellcheck unberührt) und   grep -c 'nie zwei' .claude/skills/feature-build/SKILL.md   (≥ 1)
Doku: DEVELOPMENT.md · CHANGELOG Unreleased/Changed ein Satz
