# Harness: Texte, heavy.sh, clippy, review.sh risk, approve und Test-Loeschung (kern-harness-12)

Roadmap: R-0441, R-0578, R-0579, R-0580, R-0745, R-1096, R-1123, R-1754, R-1755 · Kevin 2026-11-25 („faellig,
Harness-Pfad freigegeben, Session baut und merged kern-harness-12“)

## Problem / Motivation
- **R-0441** `.claude/skills/test/SKILL.md` nennt frps als oeffentliches snowdreamtech-Image; seit frps-supervisor
  baut der Test-Stack frps lokal aus `apps/frps` (`adminhelper-test/frps`).
- **R-1754** `/feature-build` §4.7 und `docs/developer/cicd.html` (DE+EN) sagen „jeder Check eines PRs ist Pflicht“;
  das gilt fuer `ci.yml`. `nightly.yml` laeuft bei eigener Aenderung auch auf `pull_request`, seine Checks sind
  nicht Pflicht.
- **R-0745** `heavy.sh`: stirbt der Job des Teils gui nach erfolgreichem `warm.sh gui`, schreibt er kein `gui.rc`
  mit `run`; `GUI_HELD` bleibt 0, die geleaste GUI-Box wird weder freigegeben noch als „kept for inspection“
  notiert und haelt RAM bis zum Fristablauf.
- **R-1123** `heavy.sh` bildet den Slug eines REG-Ledgers aus dem Schrittnamen mit Grossbuchstaben und ohne
  Laengengrenze (`reg-2026-11-03-backup-restore-crown-jewel-DR`, 42 Zeichen); `worktree-setup.sh` verlangt
  `[a-z0-9-]` und hoechstens 40 Zeichen.
- **R-1096** `run.sh` (Schritt `desktop-cargo`) und der CI-Job Desktop-Backend fahren `cargo clippy` ohne
  `--all-targets`: Testcode bleibt ungelintet.
- **R-1755** `review.sh risk --range A..B` vergleicht zweipunktig: ist `origin/main` seit dem Abzweigen
  vorgerueckt, zaehlen die Aenderungen auf main als Dateien des Branches.
- **R-0580 / R-0579** `roadmap.py approve` setzt `freigegeben` ohne mechanischen Halt. Die Regel (CLAUDE.md §4)
  verlangt eine von Kevin angenommene oder diktierte Zeile mit committetem Plan auf `feature/<slug>`; Kevins Wort
  in einer Notiz ist nicht von einer Notiz der Session zu unterscheiden.
- **R-0578** Eine `Test-Loeschung:` an einem Test unter einem Risikopfad (`scripts/dev/review-risk.txt`) steht heute
  nur im Gate-Bericht; sie soll Kevins Entscheidung brauchen.

## Ziel & Nicht-Ziele
- Ziel: die Texte stimmen; `heavy.sh` haelt eine geleaste GUI-Box auch nach einem toten Job fest und bildet gueltige
  REG-Slugs; clippy lintet Testcode in run.sh und CI gleich; `risk --range` liest ab der Merge-Base; `approve`
  verweigert ohne Ledger-Spalte, ohne Branch `feature/<slug>` und ohne Kevins Marke; `ledger.sh lint` verlangt fuer
  eine Test-Loeschung unter einem Risikopfad `[?]` oder Kevins Entscheidung im Ledger.
- Nicht-Ziel: R-1753 (Ruleset-Gleichlauf, ueberlappt `feature/kern-netretry-1`, jetzt `kern-harness-11`), R-1189
  (ruff-Regeln, eigener Zug `kern-ruff-1` nach Kevin 2026-11-09).

## Betroffene Komponenten & Dateien
`.claude/skills/test/SKILL.md`, `.claude/skills/feature-build/SKILL.md`, `.claude/skills/feature-plan/SKILL.md`,
`CLAUDE.md`, `tasks/README.md`, `docs/developer/cicd.html` + `docs/en/developer/cicd.html`, `scripts/tests/heavy.sh`
+ `heavy_test.sh`, `scripts/tests/run.sh`, `.github/workflows/ci.yml`, Rust-Testcode unter
`apps/desktop/src-tauri/` (nur clippy-Funde), `scripts/dev/review.sh` + `scripts/tests/review_scripts_test.sh`,
`scripts/dev/roadmap.py` + `scripts/dev/tests/test_roadmap.py`, `scripts/dev/ledger.sh` + `scripts/tests/ledger_test.sh`.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
`cargo clippy --all-targets` (lintet lib, bins, tests, examples, benches; clippy-Doku). `git diff A...B` = Diff ab
`git merge-base A B` (git-diff(1)).

## Trade-offs & Alternativen
- **approve-Marke:** gezaehlt wird `Kevin JJJJ-MM-TT` in der Notiz der Zeile (die heutigen Notizen tragen sie
  so, mit oder ohne Doppelpunkt). Alternative „Quelle beginnt mit `kevin <datum>`“ verworfen: die Quelle schreibt
  ebenfalls die Session (`add --source`). Ein diktiertes Vorhaben bekommt am Gate die Notiz
  `Kevin JJJJ-MM-TT: diktiert`. Empfehlung: nur die Notiz-Marke.
- **Branch-Pruefung:** `feature/<slug>` lokal oder auf `origin`; der Slug kommt aus der Spalte `Ledger`. Ein Branch
  ohne committetes Ledger prueft `approve` nicht (der Plan-Commit ist der erste auf dem Branch, `/feature-plan` §4).
- **Test-Loeschung:** die Muster aus `review-risk.txt` greifen direkt auf Testdateien unter Risikopfaden (Go- und
  Rust-Tests neben dem Code, `apps/ca-issuer/*`, `apps/gateway/*`); ein Server-Test unter `apps/server/tests/`, der
  einen Risikopfad prueft, faellt nicht darunter — fuer ihn bleibt die Regel als Text in `/feature-plan` §3.
- **risk --range A..B:** zweipunktig liest `risk` ab jetzt wie `A...B` (Merge-Base); eine echte Zweipunkt-Spanne
  braucht `risk` nicht, `sec --range` bleibt unveraendert (es liest Commits, nicht den Netto-Diff).

## Risiken & Rollback
Harness-only: jede Task einzeln per `git revert` zuruecknehmbar. `approve` verweigert danach Zeilen ohne Marke —
eine heute `geplant`e Zeile ohne Marke braucht vor der Freigabe Kevins Wort (gewollt).

## Doku-Impact
`docs/developer/cicd.html` DE+EN (Pflicht-Checks, clippy-Umfang); die Ablauf-Regeln in `CLAUDE.md`, `.claude/`,
`tasks/README.md`. Kein CHANGELOG-Eintrag (Harness, nicht im Produkt).

## Offene Fragen
Keine: die Harness-Pfade hat Kevin am 2026-11-25 fuer diesen Zug freigegeben.
