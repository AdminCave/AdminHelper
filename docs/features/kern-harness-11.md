# Harness: Gates und Werkzeuge der Sessions (kern-harness-11)

Roadmap: R-0375, R-0438, R-0546, R-1314, R-1362, R-1631, R-1647, R-1654, R-1659, R-1745, R-1781 (dazu R-1315: auf
main schon behoben) · Kevin 2026-11-25: Harness-Fund angenommen (Durchsicht)

## Problem / Motivation
- **R-0375** `review.sh sec` (`scripts/dev/review.sh:124`, awk `finding` :193) sucht im Commit nur Pfade, Token-Muster
  und Dedup-Keys. Adressen und Namen des privaten Netzes filtert nur `pr-body`; im Ledger, Test oder Doc kaemen sie
  unbemerkt ins oeffentliche Repo.
- **R-0438** `roadmap.py status <id> <status>` ohne `--note` loescht die Notiz der Zeile (`set_status`,
  `scripts/dev/roadmap.py:419-423`); R-0398 verlor so private Notizen.
- **R-1314** `--ledger` wird vor der Sperre gegen `origin/main` (`refuse_merged_ledger`, :979) nicht normalisiert
  (` tasks/x.md`, `tasks//x.md` umgehen sie); aeltere `--ledger`-Tests haengen am echten Repo; der Skill sagt nicht,
  dass vor der Slug-Pruefung `git fetch` noetig ist.
- **R-0546** Ein Testfilter, der keinen Test trifft, ist gruen: cargo `0 passed; N filtered out`, go
  `[no tests to run]`, jeweils Exit 0 (`scripts/tests/run.sh:882`, :890). Ein Tippfehler im `Verify:` beweist nichts.
- **R-1362** `verify.sh` erbt `AH_STEP`, `AH_PART`, `AH_EXCLUDE` (und bei `all` `AH_ONLY`) aus der Session-Shell
  (`run.sh:89-92`); Schritte fallen still weg, die Summary-Zeile sagt es nicht.
- **R-1659** `verify.sh agent -- ./internal/<pkg>/...` haengt das Paket hinter `./...` an (`run.sh:882`): alle Pakete
  laufen (`cmd` allein ~121 s).
- **R-1631** `task-close.sh` zieht `Komponente: desktop-rs desktop-ui` per `tr -d ' '` zusammen (:103), das passt nie
  zum `Verify:`.
- **R-1654** `task-close.sh` stagt jedes `Dateien:`-Element als Pathspec (`git add -A -- "$f"`, :140): Globs und
  `:`-Magie wirken.
- **R-1745** Kommentare in `scripts/dev/queue-wait.sh:53` und `scripts/tests/queue_wait_test.sh:71` sagen „vor dem
  Ende der PR-CI eingereiht“; `/feature-build` §4.7 reiht gleich nach `gh pr create` ein, Auto-Merge wartet auf die
  Pflicht-Checks.
- **R-1647** `pipe_guard_test.sh` prueft nur `*_test.sh` und als Schreiber git/printf/echo (:15); `docker logs … |
  grep -q` in `desktop_e2e_*.sh` faellt durch (R-1493, R-1522).
- **R-1781** Die Nit-Regel des roadmap-Skills (`.claude/skills/roadmap/SKILL.md:127`) stellt Harness-Nits zurueck,
  ohne Weckbedingung; `roadmap.py status … zurückgestellt` verlangt seit kern-roadmap-1 `--until`.
- **R-1315** auf main behoben (1c35ba5de: `.github/scripts/*_test` im scripts-Block); `[~]`-Task.

## Ziel & Nicht-Ziele
- Ziel: jede der Luecken oben geschlossen, je mit Test und Gegenprobe in den hermetischen Tests.
- Nicht-Ziel: private Adressen allgemein sperren (146 Treffer heute, viele gewollt: Validierungstests fuer private
  Netze, `.env.example`); CI-Workflows aendern; CLAUDE.md aendern (R-1781: nur Skill-Text, CLAUDE.md §4 bleibt).

## Betroffene Komponenten & Dateien
`scripts/dev/review.sh`, `scripts/dev/roadmap.py`, `scripts/dev/verify.sh`, `scripts/tests/run.sh`,
`scripts/dev/task-close.sh`, `scripts/dev/queue-wait.sh`, `scripts/tests/pipe_guard_test.sh`, `desktop_e2e_*.sh`
(Funde des erweiterten Guards), die zugehoerigen Tests, `.claude/skills/{roadmap,feature-plan,feature-build}/SKILL.md`.

## Datenmodell / API / Migrationen
Keine. `roadmap.py status` behaelt ohne `--note` die Notiz (neu: `--clear-note`); `verify.sh` verwirft geerbte Filter.

## Externe Integrationen
cargo test (`test result: … N passed; … M filtered out`) und go test (`[no tests to run]`): Ausgabeformate der
Werkzeuge, im Test als Fixture festgehalten.

## Trade-offs & Alternativen
- **R-0375:** (a) eine private Sperrliste `tasks/private/public-deny.txt` (feste Zeichenketten, ohne Gross/Klein),
  die `sec` liest, wenn sie da ist; Treffer melden `datei:zeile private`, nie den Text (Empfehlung: sperrt genau die
  Namen und Netze des Labs, ohne sie oeffentlich zu nennen; CI hat die Datei nicht und prueft dort nur das Bisherige);
  (b) alle RFC-1918-Adressen sperren — trifft gewollte Beispiele und Validierungstests.
- **R-0546:** nur bei gesetztem Filter (`AH_ARGS`) und nur fuer cargo, go und vitest: der Schritt wird rot, wenn sein
  Log keinen ausgefuehrten Test zeigt; pytest ist mit Exit 5 schon rot.
- **R-0438:** Notiz bleibt ohne `--note`; leeren nur mit `--clear-note`. `approve` und `sync` aendern sich nicht.

## Risiken & Rollback
Ein zu scharfes Gate blockiert Commits aller Sessions (sec, task-close, verify). Jede Task mit Fall und Gegenprobe;
Rollback per Revert der Task.

## Doku-Impact
Skill-Texte (`/roadmap`, `/feature-plan`, `/feature-build`) und die Kopfkommentare der Skripte; keine Produktdoku,
kein CHANGELOG (Harness).

## Offene Fragen
Keine blockierende. Fuer Kevin am Ende: CLAUDE.md §4 („Harness-Funde … zurückgestellt“) um `--until` ergaenzen?
Empfehlung: nein, der roadmap-Skill traegt das Detail.
