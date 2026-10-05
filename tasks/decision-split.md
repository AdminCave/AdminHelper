<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Entscheidungs-Aufteilung zwischen Kevin und der Aufsicht — Task-Ledger
Status: aktiv · Branch: harness/decision-split · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Kevin, 2026-10-05 („Ja, so gilt es“ und „Ja, als Harness-PR“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: Kevins Entscheidung vom 2026-10-05 (keine Roadmap-Zeile; Regeländerung am Harness)
Heavy: none — nur Regeltexte (CLAUDE.md, AUTONOMOUS.md, tasks/README.md, Skills) und ein Konsistenztest; kein Produktcode.
DoD je Task: CLAUDE.md (Doku im selben Commit).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Anlass: Kevin hat fast jede Empfehlung der Aufsicht übernommen; jede Rückfrage kostete Wartezeit, und Leerlauf war
der größte Zeitverlust (2026-10-02 bis 05). Er setzt die Reihenfolge der Roadmap und entscheidet sieben Arten von
Fragen; alles andere innerhalb angenommener Roadmap-Zeilen entscheidet die Aufsichts-Session und berichtet danach.

### T1 — CLAUDE.md §2 und die zwei Skills: wer was entscheidet  [x]
Komponente: scripts · Dateien: CLAUDE.md, .claude/skills/feature-plan/SKILL.md, .claude/skills/roadmap/SKILL.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @6511043d 2026-10-05T13:58:12+02:00
Review: approve (opus, Runde 2; alle Punkte aus Runde 1 und 2 behoben, keine dritte Runde)
Änderung: CLAUDE.md §2 bekommt einen Absatz „Entscheidungen“: Kevin entscheidet (1) Reihenfolge und Inhalt der
Roadmap, (2) die Freigabe von Stufen-Plänen, (3) was ein Nutzer von AdminHelper merkt (sichtbares Verhalten,
API-Verträge, Datenmigrationen), (4) bewusst hingenommenes Restrisiko, (5) Geld- und Zeitdeckel, (6) Irreversibles und
nach außen Wirkendes (Release, Tag, Ruleset, Repo-Einstellungen), (7) was nur er tun kann. Die Aufsichts-Session
entscheidet alles andere innerhalb angenommener Zeilen, gibt kleine Fund-Pakete (höchstens drei Tasks, aus Zeilen,
die Kevin in der Triage angenommen hat) selbst frei, pusht, öffnet PRs und merged nach eigener Prüfung, wenn CI grün
ist (Kevins Dauerauftrag vom 2026-09-29), und berichtet danach. Der Lebenslauf einer Einheit und die Liste „Claude
tut nie von sich aus“ nennen diese Ausnahme der Aufsichts-Session; Worker und Runner pushen, mergen und geben nie
frei. feature-plan (Gate) und roadmap (`approve`) verweisen auf den Absatz statt „nur Kevins Wort“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: CLAUDE.md, die zwei Skills (sie sind die Doku)

### T2 — feature-build, AUTONOMOUS.md und tasks/README.md an die Aufteilung angleichen  [ ]
Komponente: scripts · Dateien: .claude/skills/feature-build/SKILL.md, AUTONOMOUS.md, tasks/README.md, .claude/skills/test/SKILL.md, scripts/tests/skill_consistency_test.sh
Änderung: Aus dem Review von T1 (Opus): feature-build startet ein `geplant`-Ledger nur auf Kevins eigenes Wort in
der Session, nie auf Auftrag einer anderen Session; der Worker übergibt am Ende an die Aufsichts-Session statt
selbst zu pushen und den PR zu öffnen (baut Kevin ohne Aufsicht, tut er es); AUTONOMOUS.md (Gate, Phase 2,
Freigabe, Push/PR/Merge) und tasks/README.md (Freigabe der Regressions-Ledger) folgen CLAUDE.md §2.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die Dateien selbst

