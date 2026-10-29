<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CI: Deckel der Server-pytest-Jobs über ihrer Laufzeit — Task-Ledger
Status: erledigt · Branch: feature/ci-server-timeout · Review: am Ende
Spec: Roadmap R-0947
Heavy: none — nur `timeout-minutes` zweier Jobs in `.github/workflows/ci.yml`; kein Stack-, Gateway-, PKI- oder Install-Pfad; den Beweis liefert die PR-CI selbst
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-29: angenommen; die Session entscheidet (Deckel heben, die Laufzeit selbst als eigene Roadmap-Zeile) und merged den PR selbst, obwohl er `.github/workflows/` ändert.

### T1 — timeout-minutes der Server-pytest-Jobs auf 25  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @e55d8efa 2026-10-29T14:42:38+01:00
Review: am Ende (Branch-Review)
Änderung: `server` (Matrix py3.12/py3.13, `ci.yml:34`, heute 20) und `python-lock-server` (`ci.yml:237`, heute 15) bekommen `timeout-minutes: 25`. Gemessen auf den letzten acht `ci.yml`-Läufen (2026-10-29): 10–15 min je Job, `python-lock-server` 12–14 min gegen 15; der Abbruch in Lauf 40853628355 kam vom Deckel, nicht von einem Hänger. 25 lässt gut zehn Minuten Luft und begrenzt einen echten Hänger weiter. Die übrigen Jobs bleiben, wie sie sind.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (CI-intern; `docs/features/ci-gates.md:131` ist der Plan eines abgeschlossenen Vorhabens und beschreibt den damaligen Stand)
Beweis: main-CI 2026-10-29 run 40853628355 (Server-pytest bei 88 % abgebrochen) · Job-Laufzeiten der Läufe 40859163507 bis 40878701847: 10–15 min
Dedup-Key: rel:ci:ci.yml:server-timeout
HEAD: cd72514b
Semantik: keine Stelle in docs/ — gesucht nach `timeout-minutes` und Laufzeiten der Server-Jobs in docs/developer (DE+EN); nur `docs/features/ci-gates.md:131` nennt den 20-min-Deckel als Begründung eines früheren Plans
