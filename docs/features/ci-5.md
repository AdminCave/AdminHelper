# ci-5: ruff 0.15.20 -> 0.17.4

Zug `tasks/ci-5.md`, Roadmap R-1038 (Kevin 2026-11-02: alles auf aktuelle LTS/Stable).

## Problem / Motivation

- **R-1038:** Lint und Format der Python-Komponenten laufen mit `ruff==0.15.20`, gepinnt an vier Stellen:
  `ruff.toml:16` (`required-version`), `apps/server/requirements-dev.txt:18`, `.github/workflows/ci.yml:201` und
  `scripts/vm/bootstrap_linux.sh:31`. Aktuell ist 0.17.4 (PyPI, 2026-11-08); die Zeile nannte 0.17.3, das ist
  inzwischen ein Patch zurueck.
- ruff 0.16.0 hat den Standard-Regelsatz von 59 auf 413 Regeln erweitert und 18 E/F-Regeln daraus entfernt
  (`changelogs/0.16.x.md` im ruff-Repo). Unsere `ruff.toml` waehlt nur `extend-select = ["I"]` auf den Standard;
  mit 0.17.4 ergibt das 1317 Treffer in 39 Regeln (gemessen 2026-11-08 ueber die vier Lint-Pfade), der Formatter
  aendert keine Datei (457 Dateien unveraendert).

## Ziel & Nicht-Ziele

**Ziel:** Alle vier Pins auf 0.17.4, die Regeln bleiben die bisherigen: `ruff.toml` waehlt den alten
Standard ausdruecklich (`select = ["E4", "E7", "E9", "F", "I"]`); mit 0.17.4 sind das 0 Treffer.

**Nicht-Ziele:**
- Die neuen Standardregeln (1317 Treffer, darunter 241 `B008` an FastAPI-`Depends`) einzufuehren: eine eigene
  Roadmap-Zeile (`neu`), die je Regel entscheidet, was wir wollen.
- Die Fixtures von `scripts/tests/toolchain_lockstep_test.sh` (Version `0.15.20` in einem Wegwerf-Baum): sie
  pruefen die Gleichheit, nicht die Version.

## Betroffene Komponenten & Dateien

- `ruff.toml` (`required-version`, `select`, Kommentar), `apps/server/requirements-dev.txt`,
  `.github/workflows/ci.yml` (Job `python-lint`), `scripts/vm/bootstrap_linux.sh` (`RUFF_VERSION`).
- `changelog.d/ci-5.md`.

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

- ruff, Changelog `CHANGELOG.md` und `changelogs/0.16.x.md` (github.com/astral-sh/ruff): 0.16.0 Standardregeln,
  0.17.0 DTZ-Regeln aus dem Standard, F406 hinein (beides ausserhalb unseres `select`), Pragma-Kommentare zaehlen
  nicht mehr zur Zeilenlaenge (Formatter unveraendert gemessen).

## Trade-offs & Alternativen

- **Alten Regelsatz festhalten (gewaehlt):** der Versionssprung bleibt ohne Code-Diff und einzeln zuruecknehmbar.
- Neue Standardregeln gleich mitnehmen: ein Diff ueber den ganzen Python-Baum plus Ausnahmen je Regel, vermischt
  mit dem Pin-Wechsel; eigene Zeile.

## Risiken & Rollback

- Nach dem Merge zeigt `~/.local/bin/ruff` (Link ins `AH_VENV` des Haupt-Checkouts) noch auf 0.15.20, und
  `required-version` bricht mit Exit 2, bis `server-pytest` das venv auf den Pin zieht (DEVELOPMENT.md) oder
  `pip install -r apps/server/requirements-dev.txt` laeuft. Worktrees auf altem `main` behalten ihren Pin.
- Merger ist Kevin (`.github/workflows/`).
- Rollback: Revert des Merge-Commits.

## Doku-Impact

Keine Seite nennt die ruff-Version (die Lockstep-Beschreibung in `docs/developer/cicd.html` ist versionsfrei);
`changelog.d/ci-5.md` (`### Changed`).

## Offene Fragen

Keine.
