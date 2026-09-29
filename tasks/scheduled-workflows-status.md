<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# AH-STATUS nennt die geplanten Workflows (R-0120) — Task-Ledger
Status: geplant · Branch: harness/scheduled-workflows-status · Commit-Granularität: pro Task · Review: am Ende (Harness-Pfad ⇒ Reviewer Opus) · Modell: Opus
Spec: Roadmap R-0120
Heavy: none — nur der lesende SessionStart-Hook und sein hermetischer Test; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-09-29 von der Aufsicht (adminhelper-ac) auf Kevins Wort („Beide planen“).
Branch `harness/`, weil `scripts/dev/hooks/**` ein Harness-Pfad ist: Bau interaktiv, keine Lane
(`lane.sh new` legt fest `feature/<slug>` an).
Befund: Der wöchentliche Dependency Audit (`.github/workflows/audit.yml:13–14`, `cron: "17 6 * * 1"`, der
einzige Workflow mit `schedule:`) war vom 2026-09-21 bis 2026-09-29 rot. `heavy.sh` liest ihn im Wochenlauf
(`check_audit`, `scripts/tests/heavy.sh:698`) und legte am 2026-09-25 R-0084 an. Zwischen zwei Wochenläufen, die
nur auf Kevins Zuruf starten, zeigt aber keine Session den Stand. `session-status.sh` fragt `gh` nur nach Drafts
(`:94`) und offenen PRs (`:147`), nie nach Läufen.

### T1 — Zeile „Geplant:“ je geplantem Workflow, WARN bei rot oder veraltet  [ ]
Komponente: scripts · Dateien: scripts/dev/hooks/session-status.sh, scripts/tests/session_status_test.sh, DEVELOPMENT.md, CHANGELOG.md
Änderung: Nach Zeile 4 (`session-status.sh:181`) druckt der Hook je Datei unter `.github/workflows/`, die ein
`schedule:` trägt, eine Zeile `Geplant: <name:> <jjjj-mm-tt> (<n> d): <conclusion>`. Die Daten kommen über
`gh_json` (`:59–63`, `timeout 3`): `run list --workflow <datei> --event schedule --branch main --status completed
--limit 1 --json conclusion,createdAt,databaseId` mit einem `-q`-Ausdruck, der eine leere Liste als `kein Lauf`
ausgibt (sonst macht `gh_json` aus der leeren Ausgabe fälschlich `?`). Das Alter rechnet der Hook wie
`weekly_line` (`:152–180`) in UTC-Tagen. Eine `WARN:`-Zeile über `warn()` (`:58`) gibt es bei `failure`,
`timed_out` oder `startup_failure` (mit `gh run view <id> --log-failed` als Handgriff) und bei einem Lauf älter als
8 Tage; `cancelled` wird nur angezeigt. `gh` nicht erreichbar oder ohne Auth: `?`, keine `WARN:`-Zeile, wie bei
„PRs offen“. Kopfkommentar `:25–34` („Implemented“) nachziehen.
Test: Der gh-Shim (`session_status_test.sh:42–55`) bekommt einen Zweig `run)` mit grünem Default, damit der saubere
Fall (`:177–195`, keine `WARN:`-Zeile) grün bleibt. Neue Fälle: rot → Zeile + WARN; `cancelled` → Zeile, kein WARN;
leere Liste → `kein Lauf`, kein WARN; `SHIM_GH=fail` → `?`, kein WARN; älter als 8 Tage → WARN. Der Shim umgeht
`-q`; den Ausdruck prüft deshalb ein echter Lauf: `bash scripts/dev/hooks/session-status.sh` zeigt genau eine Zeile
`Geplant: Dependency Audit …` (Ausgabe in die Evidenz).
Beweis: origin/main@60544235 · protokollierender gh-Shim auf PATH, der für `run` einen roten Audit-Lauf liefert,
dann `bash scripts/dev/hooks/session-status.sh` → nur `release list` und `pr list` werden gerufen, 0 Treffer für
`audit|Geplant|schedule`, keine `WARN:`-Zeile (Explorer der Aufsicht, 2026-09-29). Die neuen Fälle gegen den alten
Hook müssen rot sein (Gegenprobe im Wegwerf-Worktree).
Metrik: Laufzeit des Hooks vor und nach T1 (heute ~1,6 s mit zwei gh-Aufrufen; ein `gh run list` ~1 s).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md „Session-Status-Hook“ (:368–378) ein Satz zur neuen Zeile und ihrer WARN-Regel; CHANGELOG [Unreleased]
Dedup-Key: rel:scripts:ah-status:scheduled-workflows · HEAD: 60544235
Semantik: DEVELOPMENT.md:370–378 beschreibt den Block heute ohne geplante Workflows („… dann aktive Ledger, offene
PRs und warme Boxen“) — das ist der heutige, gewollte Umfang; die Erweiterung hat Kevin am 2026-09-29 zur Planung
freigegeben. CLAUDE.md §3 („Stand feststellen, nicht raten“) nennt den Inhalt des Blocks; eine Zeile dort ergänzt
Kevin von Hand, falls er will.
