<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# changelog.d — CHANGELOG-Einträge je Branch

Jeder Branch schreibt seine Einträge in **`changelog.d/<slug>.md`** statt in `CHANGELOG.md`. So ändern parallele
Branches nie dieselbe Datei (GitHub ignoriert die Union-Merge-Regel aus `.gitattributes`).

Ein Fragment enthält nur Keep-a-Changelog-Unterabschnitte mit ihren Einträgen, in der Form von `CHANGELOG.md`
(umlautfrei, Gedankenstrich „—", `.claude/rules/docs.md`):

```
### Fixed

- **Desktop: ein 403 auf das Besucher-Bundle stoppt frpc:** …
```

Erlaubt sind `### Added`, `### Changed`, `### Deprecated`, `### Removed`, `### Fixed` und `### Security`. Vor dem
Release faltet `python3 scripts/release/changelog-assemble.py` alle Fragmente in den Abschnitt `## [Unreleased]` von
`CHANGELOG.md` und löscht sie (`.claude/rules/release.md`); `--check` prüft nur die Form.
