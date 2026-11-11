# Harness: Wackler-Politik, Triage-Dauerauftrag, Sammellauf nachts

Zug `arch-workflow-1` (Roadmap R-1335, R-1336, R-1337, R-1338, R-1346). Kevin hat die Vorschläge am 2026-11-11 diktiert; die
Messwerte stehen in der privaten Workflow-Analyse. Der CI-Teil (Stack-Job auf PRs, schlanke PR-CI, Shard-Ausgleich,
`merge_group`, `nightly.yml`) ist ein eigener Zug (`arch-workflow-ci-1`), weil `ci.yml` gerade in zwei offenen PRs
steht und Workflow-PRs Kevin merged.

## Problem je Zeile

- **R-1335 Wackler:** Fünf Wackler-Familien kamen nach ihrem „Fix“ zurück (Windows-pty, launcher-Frist 900 ms,
  `test_frps_supervisor` 10 s, `xrdp_live_session`, Downloads). Kein Fix war vor dem Merge durch einen Dauerlauf belegt;
  die Ursachen sind meist kurze feste Fristen und Nachrichtenreihenfolge.
- **R-1336 Dauerauftrag:** Seit 10-29 entstehen 29 Roadmap-Zeilen je Tag, 16 davon aus Prüfern. Kevin triagiert in
  Schüben (Median 15,4 h, p90 96 h) und nimmt fast alles an (91 von 115 Nits gebaut). Eine gebaute Zeile wartet im
  Median 11,4 h bis zur Einplanung.
- **R-1337 Sammellauf nachts:** Heute startet die Session den Sammellauf nach drei `linux-full`-Merges, zuletzt
  14-mal je Woche (je ~105–114 min, ~45 VM-h je Woche). Er bindet Proxmox-RAM, sodass die Capstone seit 10-22 kein
  Fenster fand. Von 6 Produktfunden in 52 Läufen kamen 4 aus schemathesis; heavy.sh hat 4 davon als „flaky“ oder
  „extern“ etikettiert, weil ein Fuzz-Fund im Retry nicht zuverlässig wiederkehrt und auf dem Basis-Commit
  (vorbestehend) ebenfalls rot ist.
- **R-1338 Server-pytest auf der VM:** Teil `rest` fährt die Server-Suite (~30 min seit 11-05) ein drittes Mal neben
  PR- und main-CI. Ob die VM dabei Tests fährt, die die CI überspringt, ist offen.

## Ziel und Nicht-Ziele

- Ziel: ein Wackler-Fix kommt nur mit Dauerlauf-Beleg; neue Tests ohne kurze feste Fristen (reviewer-Kriterium).
- Ziel: Funde, die der Dauerauftrag deckt, plant die Session ohne Einzel-Triage in einen `klein-`-Zug; Kevin sieht sie
  als Wochenliste mit Veto. Prüfer-Nits werden keine Einzelzeilen.
- Ziel: der Sammellauf startet nachts per Cron (`scripts/tests/nightly.sh`), samstags als `weekly` mit Capstone; die
  Session startet ihn nicht mehr nach Merges. Ein schemathesis-Fund ist nie „flaky“ oder „extern“, sondern `fund`.
- Ziel: die Server-Suite fällt aus dem Box-Lauf, wenn die Probe zeigt, dass die CI dieselben Tests fährt.
- Ziel (R-1346, Kevin 2026-11-11): ab dem ersten grünen `weekly` mit Capstone jede Woche ein Beta-Tag auf genau dem vom `weekly` geprüften Commit
  (Release-Branch, nächstes Minor);
  Latest bleibt an den Umfang von R-1110 gebunden (`.claude/rules/release.md`).
- Nicht-Ziel: `ci.yml`, `nightly.yml`, Merge Queue (Zug `arch-workflow-ci-1`, R-1344/R-1345).

## Betroffene Dateien

`.claude/rules/testing.md`, `.claude/agents/reviewer.md`, `.claude/skills/feature-build/SKILL.md`,
`.claude/skills/roadmap/SKILL.md`, `.claude/skills/test/SKILL.md`, `CLAUDE.md`, `scripts/tests/heavy.sh`,
`scripts/tests/heavy_test.sh`, `scripts/tests/nightly.sh` (neu), `scripts/tests/nightly_test.sh` (neu),
`scripts/tests/run.sh`, `DEVELOPMENT.md`, `docs/developer/cicd.html`, `docs/en/developer/cicd.html`.

## Entwurf

- **nightly.sh** (`run | install | uninstall | status`, `--dry-run`):
  - `run` prüft vor dem Start:
    - der Haupt-Checkout ist auf `main` und sauber;
    - keine tmux-Sitzung `ah-*` läuft;
    - `git fetch` und `merge --ff-only origin/main` gelingen;
    - die Provider-Umgebung lädt ohne Ausgabe aus `~/.config/adminhelper/pve.env` und dem `env`-Block von
      `.claude/settings.local.json`;
    - `vm.py list` endet mit 0.
  - Danach startet `run` `heavy.sh all` bzw. samstags `heavy.sh weekly` in tmux `ah-nightly`. Ein übersprungener Lauf
    schreibt seinen Grund nach `.ah-out/nightly.log`.
  - `install` setzt eine markierte Crontab-Zeile (01:30), idempotent; `uninstall` entfernt genau diese Zeile.
  - Hermetischer Test über Overrides (Wrapper-Verzeichnis, Root, `crontab` per PATH).
- **heavy.sh:** Ein roter Schritt `schemathesis` wird nicht wiederholt und nicht gegen die Basis geprüft. Er erhält
  das Urteil `fund`: der Teil ist FAIL, der Report sagt „Fuzz-Fund: BUG-Zeile anlegen“. Die Regel in `/feature-build`
  §5: `fund` ist eine BUG-Zeile und sperrt keine `linux-full`-Merges; `reg` und `kandidat` sperren wie bisher, bis der
  rote Schritt per `--step`-Lauf über `main` wieder grün ist.
- **Dauerauftrag:** Er deckt Funde aus Prüfer oder Bau, die alle Bedingungen erfüllen:
  - Klasse BUG oder REF, mit Beweis (Datei:Zeile oder Befehl);
  - klein-Bereich nach dem Zug-Schlüssel der Triage;
  - kein SEC, kein Harness-Pfad, keine Verhaltens-, API- oder Migrationsänderung.

  Solche Funde legt die Session mit `add` an und setzt sie sofort mit `status geplant --ledger tasks/<klein-zug>.md
  --note "Dauerauftrag Kevin 2026-11-11"` in einen Zug. `/roadmap` nennt ihre Zahl seit der letzten Triage,
  `/roadmap triage` listet sie zum Veto. Der Abschnitt gilt erst, wenn CLAUDE.md §4 ihn nennt (Kevin, T8). Prüfer-Nits: in einer ohnehin laufenden Korrekturrunde mitbeheben, sonst eine Sammelzeile je Zug aus Nits, die die Bedingungen erfüllen.

## Risiken und Rollback

- Ein Cron-Lauf ohne Session: Bei Rot schreibt heavy.sh Report, `history.csv` und REG-Zeilen wie heute; die nächste
  Session liest den Report beim Start (AH-STATUS). Rollback: `nightly.sh uninstall`.
- Die Provider-Umgebung unter Cron: Fehlt sie, bricht `vm.py` ab. Die Probe `nightly.sh run --dry-run` unter `env -i`
  belegt das Laden vor der Installation.
- Merge-Sperre: Rückmeldung Merge → Urteil wird länger (heute p50 4,9 h, künftig bis ~1 Tag). Gemessen gab es 1
  Regression in 52 Läufen.
- Server-pytest aus dem Box-Lauf: nur bei belegter Gleichheit; sonst bleibt der Schritt (Task `[~]`).

## Doku-Impact

`DEVELOPMENT.md` (Wochenlauf, Installation des Timers), `docs/developer/cicd.html` DE+EN (Abschnitt Wochenlauf:
Auslöser und Klasse `fund`). Der Ablauf selbst steht in `CLAUDE.md` und `.claude/`.

## Offene Fragen

Keine. Kevin hat am 2026-11-11 entschieden: CLAUDE.md ändert die Session (T8), wöchentlich Beta (R-1346), Cron nach dem Merge.
