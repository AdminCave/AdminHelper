<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stufe 6a — deterministische Review-Prüfer

Roadmap: R-0009 (Stufe 6, Teil 6a) · Stand: main@abef751a · Geplant 2026-10-02 von der Aufsicht, Entscheidungen Kevin 2026-10-02

## Problem / Motivation

Das Ziel von Stufe 6 ist ein Task-Review, der dem Builder nicht glaubt, ein maschinenlesbares Urteil liefert und
Kevin zum PR eine Checkliste mit Evidenz statt eines riesigen Diffs gibt (Roadmap-Dokument §Stufe 6, §10). Teile
davon gibt es seit Stufe 4: `scripts/dev/review.sh` mit `diff-scan`, `scope`, `sec` (`:116`, `:403`, `:474`),
`scripts/dev/tree-hash.sh`, `verify.sh --tree` (`:8`, `:45–66`) und in `task-close.sh` eine Verdict-Schnittstelle
(`--review none|verdict:<json>`, `:286–313`), die heute nur `verdict == "approve"` und `tree_hash` prüft. Im Alltag
kommt dort nur Freitext an (`--review-note "approve (sonnet)"`, feature-build `SKILL.md:177`).

Es fehlen die deterministischen Prüfer, die ein Reviewer heute von Hand erraten muss: Welche Pfade sind riskant
(heute Prosa in feature-build `SKILL.md:149–151`)? Fehlt bei einer Doku-Seite ihr Sprach-Gegenstück? Welche
Vertrags-Tests gehören zu einer geänderten Datei? Wäre der neue Test ohne den Fix rot? Dazu ein festes Schema für
das Urteil und ein PR-Text aus dem Ledger statt Prosa.

## Ziel & Nicht-Ziele

Ziel (6a, ohne Modell, alles hermetisch testbar):
- **Verdict-Schema** `scripts/dev/review-verdict.schema.json` und `review.sh check-verdict`; `task-close.sh` delegiert
  seine heutige Inline-Prüfung daran (Exit-Codes bleiben 2/3/4).
- **`review.sh risk`** mit `scripts/dev/review-risk.txt`: Risikoklasse eines Diffs (`standard` | `xhigh`), Grundlage
  der Modellwahl des Reviewers.
- **`review.sh docs-pairs`**: eine geänderte Seite unter `docs/` ohne ihr Gegenstück (gefunden über den
  `lang-switch`-Link der Seite, nicht über den Dateinamen) ist ein Fund.
- **`review.sh contracts`** mit `scripts/dev/review-contracts.txt`: zu einer geänderten Datei gehörende Prüfungen
  (Test-Datei oder grep-Paar) laufen deterministisch in `task-close.sh` (Ebene 0).
- **`scripts/dev/review-probe.sh`**: wendet nur die Test-Hunks eines Diffs in einer eigenen Worktree auf die Basis an
  und meldet, ob der Test ohne den Fix rot ist (`red_without_change`, Fehlerart geprüft), plus `--mutate` für genau
  einen Mutanten (`killed|survived`). Der Builder-Tree bleibt unberührt.
- **`review.sh pr-body <ledger>`**: Checkliste je Task mit Evidenz- und Review-Zeile als PR-Text.
- **Review-Disziplin** (Kevin 2026-10-02) in feature-build Schritt 4.

Nicht-Ziele (6b oder später): den Reviewer als eigenen Prozess starten (`claude -p --agent`, Agent-Dateien,
Bash-Allowlist-Hook, `close.json`, Runde 2 über Verdict-Pfad) — Stufe 6b; `review.sh log` (ohne Verdict-Erzeuger kein
Konsument) — 6b; `refuter.md` — Stufe 9; Ebene 3 als Prozess, `restore`/`rejected.diff`/`[?]`-Automatik — Stufe 7;
`coverage` im Schema (kein Konsument).

## Betroffene Komponenten & Dateien

- `scripts/dev/review.sh`, `scripts/dev/task-close.sh`, neu `scripts/dev/review-verdict.schema.json`,
  `scripts/dev/review-risk.txt`, `scripts/dev/review-contracts.txt`, `scripts/dev/review-probe.sh`,
  `scripts/dev/harness-paths.txt`.
- Tests: `scripts/tests/review_scripts_test.sh`, `scripts/tests/task_close_test.sh`, neu `scripts/tests/review_probe_test.sh`,
  `scripts/tests/skill_consistency_test.sh` (bleibt grün).
- Skills: `.claude/skills/feature-build/SKILL.md` (Schritt 4, PR-Schritt).
- Doku: `DEVELOPMENT.md` („Task schliessen", `:411`), `AUTONOMOUS.md` (`:65`), `docs/developer/cicd.html` +
  `docs/en/developer/cicd.html`, `CHANGELOG.md`.

## Datenmodell / API / Migrationen

Keine App-Änderung. Verdict-Schema (JSON Schema draft-07, schlank): `schema_version`, `task` {`ledger`, `id`},
`tree_hash`, `reviewer` {`model`, `effort`}, `verdict` (`approve` | `request_changes` | `needs_decision`),
`findings[]` {`severity` (`blocker` | `wichtig` | `nit`), `file`, `line`, `claim`, `evidence`}, `probe`
{`applicable`, `reason`, `red_without_change`}; vom Runner gefüllt: `verify` (aus `last-verify.json`), `contracts`,
`cost_usd`. Regeln in `check-verdict`: fremder Tree → 4; `approve` mit einem `blocker` → verworfen (3);
`approve`, obwohl `probe.applicable` und nicht `red_without_change` → verworfen (3); ein `blocker` ohne `evidence`
zählt als `nit`; unlesbar oder schemawidrig → 2.

## Externe Integrationen

Keine. JSON-Schema-Prüfung mit python3-Bordmitteln (kein `jsonschema`-Paket auf dem Runner; die Pflichtfelder und
Enums prüft `check-verdict` selbst).

## Trade-offs & Alternativen

- Reviewer fährt Verify nicht nach: `task-close.sh` hat die Suite schon gefahren und an den Tree-Hash gebunden; der
  Runner füllt den `verify`-Block. Spart einen Suite-Lauf je Task.
- Contracts deterministisch in `task-close.sh` statt im Ermessen des Reviewers: wiederholbar, kostet keine Tokens.
- `docs-pairs` über den `lang-switch`-Link statt über Dateinamen: `admin/benutzer.html` ↔ `en/admin/users.html` —
  Namensgleichheit stimmt für die Admin-Doku nicht.
- Probe per `git worktree` statt `git archive`: `run.sh` und `tree-hash.sh` brauchen ein Repo; `trap` räumt auf.

## Risiken & Rollback

- `contracts` in `task-close.sh` verlängert einen Close um die Laufzeit der zugehörigen Tests; die Liste startet klein.
- `review-probe.sh` braucht die Toolchain der Komponente; fehlt sie (Runner ohne Go/Rust/Node), ist das
  `applicable: false, reason: toolchain`, nie grün.
- `review.sh` ändert sich auch in Schutz 2 (T5/T6) ⇒ 6a baut erst nach dessen Merge.
- Rollback: Revert je Task; `task-close.sh` fällt auf die heutige Inline-Prüfung zurück.

## Doku-Impact

DEVELOPMENT.md (Task schliessen: die neuen Prüfer), AUTONOMOUS.md (Ebene 0 vor dem Reviewer), cicd.html DE+EN
(Review-Prüfer und Verdict), CHANGELOG.

## Offene Fragen

Keine; entschieden am 2026-10-02 (alle Detail-Empfehlungen der Bestandsaufnahme, 6a vor 6b, Review-Disziplin).
