# kern-harness-8: Adressfilter im PR-Text, .github-Skripttests im scripts-Block, Commit-Betreff geprüft

Roadmap: R-1325, R-1352, R-1359 (Kevin 2026-11-12, Triage an die Session gegeben, angenommen; R-1359 „kläre die
commit sachen“). Alle drei ändern Harness-Pfade auf Kevins Wort (CLAUDE.md §4).

## Problem / Motivation

- **R-1325:** `review.sh pr-body|final` maskiert Adressen mit `ADDR` (`scripts/dev/review.sh:400`) und prüft jeden
  Treffer mit `ipaddress.ip_address`. In einem Rust-Pfad wie `pty::tests::closing_` trifft `ADDR` die Folge `::c`,
  die eine gültige IPv6-Adresse ist; der PR-Text liest dann `pty::tests<addr>losing_`.
- **R-1352:** `verify.sh scripts` fährt den Block `scripts (hermetic)` aus `scripts/tests/run.sh` (Liste
  `AH_SCRIPT_TESTS_DEFAULT`, `run.sh:688`), der nur unter `scripts/tests/` sucht. Die Tests unter `.github/scripts/`
  (`retry_test.sh`, `apt_archives_verify_test.sh`, `tauri_cli_pins_test.sh`, `cache_settings_test.sh`) fährt nur
  die PR-CI als eigene Schritte. Die Evidenz einer Task, die eines dieser Skripte ändert, belegt dessen Test nicht.
- **R-1359:** Weder `task-close.sh` noch der Hook `commit-msg` prüfen den Betreff. Drei Task-Commits liegen auf `main`
  mit `Task: …` bzw. Fließtext als Betreff (Message-File ohne Betreffzeile). Die Historie auf `main` bleibt.

## Ziel & Nicht-Ziele

- **Ziel:**
  - `review.sh`: eine IPv6-Adresse, vor oder hinter der direkt ein Wortzeichen steht, bleibt stehen
    (`a::b`-Pfade); IPv4 und IPv6 hinter `word:` werden weiter maskiert.
  - `run.sh`: ein Eintrag der Liste mit `/` gilt relativ zur Wurzel des Checkouts; die vier
    `.github/scripts/*_test`-Einträge stehen in `AH_SCRIPT_TESTS_DEFAULT`. Ein Test prüft, dass jedes
    `.github/scripts/*_test.sh` dort steht.
  - `commit-msg` und `task-close.sh` (vor dem Verify) verlangen als erste Zeile, die weder leer noch ein Kommentar
    ist, einen Conventional-Commit-Betreff `<typ>[(scope)][!]: <text>`, Typen `feat fix chore refactor docs test perf
    tune build ci style revert`. Ausgenommen sind `Merge …`, `Revert "…"` und `fixup!`/`squash!`/`amend!`.
- **Nicht-Ziele:** kein Umschreiben der Historie; keine Prüfung bei cherry-pick/rebase/am (`commit-msg` läuft dort
  nicht, githooks(5)); die doppelten Einzelschritte in `ci.yml` bleiben (ein Workflow-PR ist Kevins Merge; eigene
  Folgezeile).

## Betroffene Komponenten & Dateien

Komponente `scripts`: `scripts/dev/review.sh`, `scripts/tests/review_scripts_test.sh`, `scripts/tests/run.sh`,
`scripts/tests/run_flags_test.sh`, `scripts/tests/harness_consistency_test.sh`, `scripts/dev/hooks/commit-msg`,
`scripts/dev/task-close.sh`, `scripts/tests/task_close_test.sh`, `scripts/tests/guard_test.sh`, `DEVELOPMENT.md`.

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

githooks(5): `commit-msg` bekommt die Nachrichtendatei, läuft bei `git commit` und `git merge`, nicht bei
cherry-pick, revert, rebase oder `git am` (so schon im Kopf des Hooks). Conventional Commits 1.0.0:
`<type>[optional scope][!]: <description>` (https://www.conventionalcommits.org/en/v1.0.0/).

## Trade-offs & Alternativen

- Betreff-Regex an zwei Stellen (Hook und `task-close.sh`) statt eines neuen Helfers: zwei Zeilen; ein gemeinsamer
  Helfer müsste in jede Fixture, die die Skripte kopiert.
- Pfad-Einträge in der bestehenden Liste statt einer zweiten Liste: ein Block, eine Summary, dieselbe
  SKIP-/Fehlerlogik.

## Risiken & Rollback

Ein Commit mit freiem Betreff (Fixtures in Tests, Handarbeit) scheitert künftig am Hook; die Tests, die Hooks
scharf schalten, bekommen konforme Betreffs. Rollback: Revert der Task-Commits.

## Doku-Impact

`DEVELOPMENT.md` (Token-Hooks: `commit-msg` prüft auch den Betreff). Kein CHANGELOG (nur Harness).

## Offene Fragen

Keine.
