### Changed
- **Entwicklung: Plaene entstehen im eigenen Worktree:** `/feature-plan` legt den Worktree des Vorhabens an und
  committet Spec und Ledger dort, statt im Hauptcheckout den Branch zu wechseln, den alle Sessions teilen.
  `scripts/dev/hooks/harness-guard.sh` lehnt `git switch` und `git checkout` im Hauptcheckout ab; der Weg zurueck auf
  `main` und ein Restore mit `--` bleiben frei.
