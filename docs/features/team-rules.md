<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Team-Plan Phase 1, Schritt 2: die Regeln des Teams in CLAUDE.md §2/§3

Stand 2026-10-10 · Roadmap: die Zeile legt der Chef an · Ledger `tasks/team-rules.md` · Branch `harness/team-rules`

## Problem / Motivation

CLAUDE.md beschreibt noch das Betriebsmodell vor dem Team. Dort steht:
- genau ein Bau `aktiv`, eine Lane nur als Ausnahme;
- ein Runner-Nutzer, der baut;
- die „Aufsichts-Session“;
- keine Regel für einen Dauerlauf, für die Sandbox vor einem unbeaufsichtigten Lauf und für das Wochenlimit;
- Merge-Rechte nur als Satz in „Entscheidungen“.

Kevin hat am 2026-10-08 und 2026-10-09 entschieden, wie das Team arbeitet (siehe unten). Dieses Vorhaben schreibt das
als Regeln in §2/§3, zieht die Deckel im Code nach und räumt Sätze in den Skills auf, die den neuen Regeln
widersprechen. Nebenbei stellt es eine falsche Angabe richtig: §8 sagt, die Dev-Box habe kein Docker. Gemessen läuft
hier Docker (29.8.1).

Messzahlen, auf die sich die Deckel stützen:
- Messlauf 1 (#99): etwa 2–3 $ und 30 min je Task.
- Messlauf 2 (Abnahme von 4b): 7,65 $ in 2 h für 2 Tasks und 1 abgelehnte, ohne Handgriff.
- Die Grundlage, der `verify.sh`-Lauf vor der ersten Task, dauert 10–38 min, je nach Wartezeit an der py.lock.

## Kevins Entscheidungen (2026-10-08, 2026-10-09; von der Aufsicht übermittelt)

1. Die Aufsicht heißt künftig **Chef**. Sie startet täglich frisch und übernimmt ihren Stand aus Dateien: AH-STATUS,
   Roadmap, Ledger, Tagesbericht.
2. Das **Team** läuft unter Kevins UID, ohne Docker und ohne sudo: Builder-Profil (`builder-home.sh`), Sperrregeln,
   später ein Stolperdraht. Der Runner-Nutzer ist eingefroren.
3. **Restrisiko hingenommen:** Code einer Task läuft mit Kevins Rechten, die Sperrregeln erschweren nur. Ein in R-0258
   beschriebener Kanal ist nur für beaufsichtigte Läufe hingenommen. **Vor jedem unbeaufsichtigten Dauerlauf kommt die
   Sandbox (R-0241)**, und das steht als Regel drin.
4. **Deckel:** 2 Bau-Slots, 1 VM-Lauf zugleich. Das Team nutzt höchstens die Hälfte des Wochenlimits, bis es gemessen
   ist.
5. **Modelle:** Opus baut, bis gemessen ist. Sonnet nur für Reviews je Task außerhalb der Risikopfade, Opus über den
   ganzen Branch. Nie Sonnet, das Sonnet prüft.
6. **Merge-Recht:**
   - Der Chef merged Produkt-PRs nach grüner CI im ersten Versuch, ein Merge je CI-Zyklus, vorher die
     Kombinationsprüfung.
   - PRs an Harness und Gates merged Kevin, oder der Chef auf Kevins ausdrückliches Wort im selben Zug.
   - Ein roter `main` wird nicht nach vorn gefixt; flaky heißt Rerun plus Roadmap-Zeile.
7. **Triage:** Was Kevin diktiert, gilt als angenommen. Alles andere schlägt der Chef nur vor, Kevin bestätigt
   gesammelt. Kein eigener Fund wird ohne Kevin auf `geplant` gesetzt.
8. **Dauerlauf:** eine Ausnahme von „kein Timer“. Der Leitstand bzw. Loop läuft weiter, sobald Kevin ihn einmal
   gestartet hat, innerhalb der Deckel, und erst nach der Sandbox.

## Ziel & Nicht-Ziele

Ziel:
- §2 trägt die acht Entscheidungen als knappe Regeln, ohne Prosa-Dopplung zu AUTONOMOUS.md. Details stehen dort oder
  in den Skills, CLAUDE.md verweist.
- §3 Trigger 3 nennt die neuen Deckel.
- §6 nennt den Chef bei push und merge.
- §8 sagt richtig, dass die Dev-Box Docker hat.
- CLAUDE.md bleibt unter dem bisherigen Zeilenbudget: heute 226 Zeilen, der Entwurf unten ergibt 225.
- Die Deckel im Code folgen: `aktiv` 2 in `roadmap.py` und `session-status.sh`. Ein Paritätstest hält CLAUDE.md,
  `roadmap.py`, `session-status.sh` und den `/roadmap`-Skill zusammen.
- Sätze in Skills und AUTONOMOUS.md, die den neuen Regeln widersprechen, werden geändert, wenn es je eine Zeile ist.
  Sonst landen sie in der Liste unten als Folge-Zeile.

Nicht-Ziele:
- Das Umbenennen „Aufsicht“ → „Chef“ außerhalb von CLAUDE.md: 28 Stellen in Skills, AUTONOMOUS.md, DEVELOPMENT.md und
  `scripts/`, darunter ein PR-Text in `ledger-loop.sh`, den `ledger_loop_test` prüft. CLAUDE.md sagt bis dahin
  „Chef (bisher Aufsicht)“.
- Ein Tagesbericht, ein Leitstand, ein Stolperdraht, die Sandbox (R-0241). Die Regeln nennen sie; gebaut werden sie in
  eigenen Stufen.
- Die alten Specs unter `docs/features/` bleiben, wie sie sind; sie sind Geschichte.

## Betroffene Komponenten & Dateien

- `CLAUDE.md`: §2 neu, §3 Trigger 3 und der Satz zu Irreversiblem, §6 eine Zeile, §8 eine Zeile.
- `CHANGELOG.md`: ein Eintrag unter Changed.
- `scripts/dev/roadmap.py` `WIP_CAPS` (`:151`) und `scripts/dev/hooks/session-status.sh` `WIP_CAPS` (`:119`), dazu
  die Kommentare `:35` und `:117`: `aktiv` 1 → 2.
- Tests, die den Deckel `aktiv` 1 festhalten, gemessen mit einem Probelauf mit `aktiv` 2:
  - `scripts/dev/tests/test_roadmap.py`: 4 Tests;
  - `scripts/tests/session_status_test.sh`: 2 Prüfungen;
  - `scripts/tests/heavy_test.sh`: 1 Prüfung.
- `scripts/tests/skill_consistency_test.sh`: der neue Paritätstest der Deckel.
- `.claude/skills/roadmap/SKILL.md:36` (Deckel), `.claude/skills/feature-plan/SKILL.md:191` (Triage) und `:232`
  (Lane), `.claude/skills/feature-build/SKILL.md:281` (Modell des Reviews am Ende),
  `.claude/skills/test/SKILL.md:277` und `AUTONOMOUS.md:370` (Docker).

## Der Entwurf für CLAUDE.md

§2, vollständig (ersetzt `CLAUDE.md:25–97`):

```markdown
## 2. Betriebsmodell

<!-- Stufe 0 · Quelle §3.1, §3.2, §5 Leitprinzipien 4/5/7/10, Stufe 13 · Team-Plan Phase 1 (Kevin, 2026-10-08/09) -->

**Nichts läuft ohne Kevins Start.** Kein Timer, kein Cron, keine Routine. Kevin startet jede Session, jeden Testlauf
und jeden Bau, oder der Chef gibt einem laufenden Worker den Startauftrag („Entscheidungen“); er setzt die
Reihenfolge, entscheidet, was unter „Entscheidungen“ steht, und publiziert. Einzige Ausnahme ist der **Dauerlauf**:
Hat Kevin den Leitstand bzw. Loop einmal gestartet, läuft er innerhalb der Deckel weiter — erst nach der Sandbox.
**Das Team** läuft unter Kevins UID, ohne Docker und ohne sudo: Builder-Profil (`scripts/dev/builder-home.sh`), die
Sperrregeln seiner Settings, später ein Stolperdraht; der Runner-Nutzer ist eingefroren (AUTONOMOUS.md, „Der Worker“).
**Restrisiko (Kevin, hingenommen):** Code einer Task läuft mit Kevins Rechten, die Sperrregeln erschweren nur;
hingenommen für beaufsichtigte Läufe. **Vor jedem unbeaufsichtigten Dauerlauf kommt die Sandbox (R-0241).**
**Deckel:** 2 Bau-Slots (zwei Ledger `aktiv`, nur disjunkt: AUTONOMOUS.md „Parallel-Betrieb“) · 1 VM-Lauf zugleich ·
das Team nutzt höchstens die Hälfte von Kevins Wochenlimit, bis es gemessen ist.
**Lange Läufe laufen überwacht:** Wochenlauf, Capstone, Bake, CI-Watch startet Claude auf Kevins Zuruf in tmux mit
Wächter, bleibt bis zum Report dran, nie nackt im Terminal, nie von selbst (Regeln: `.claude/skills/test/SKILL.md`).

**Modelle:** Planen, Bauen und Planungs-Helfer auf Opus (oder Fable), bis gemessen ist. Sonnet nur im Review je Task
außerhalb der Risikopfade (`review.sh risk`); den ganzen Branch prüft Opus. Nie prüft Sonnet, was Sonnet baute.

**Verben, die es heute gibt:** `/feature-plan` (Spec + Ledger, stoppt am Design-Gate), `/feature-build` (Ledger bis zur
Übergabe), `/feature-review` (frischer Reviewer für einen Diff), `/test` (schwere Suiten auf VMs), `/roadmap` (zeigen,
triagieren); weitere folgen stufenweise. **Ein Verb, das hier fehlt, gibt es noch nicht: sagen, nicht improvisieren.**

**Lebenslauf einer Einheit:** Zeile in `tasks/private/ROADMAP.md` (Klasse SEC > REG > REL > BUG > FEAT > REF > IDEE)
→ `/feature-plan` schreibt `docs/features/<slug>.md` + `tasks/<slug>.md` mit `Status: geplant` → **Freigabe** (der
Pflicht-Checkpoint: Kevin, außer bei kleinen Fund-Paketen) → `/feature-build` Task für Task (Verify → Schnellsuite →
Review → Commit) → PR → Merge (unten „Merge“) → Roadmap-Zeile nach „Abgeschlossen“.

**Entscheidungen (Kevin, 2026-10-05):** Kevin entscheidet (1) Reihenfolge und Inhalt der Roadmap (Triage: annehmen,
zurückstellen, ablehnen, bündeln), (2) die Freigabe von Stufen-Plänen, (3) was ein Nutzer von AdminHelper merkt
(sichtbares Verhalten, API-Verträge, Datenmigrationen), (4) bewusst hingenommenes Restrisiko, (5) Geld- und Zeitdeckel
und ein Paket, das sie sprengt, (6) Irreversibles und nach außen Wirkendes, abschließend: Release, Tag, Publish,
Ruleset, Repo-Einstellungen, (7) was nur er tun kann (sudo, Tokens, Passwörter); dazu startet nur er den Loop. Der
**Chef** (bisher „Aufsicht“; Skills und AUTONOMOUS.md sagen es noch so) ist die eine Session, die Kevin ausdrücklich
als Chef gestartet oder benannt hat, in Kevins eigenem Wort. Er startet täglich frisch und übernimmt seinen Stand
aus Dateien: AH-STATUS, Roadmap, Ledger, Tagesbericht. Jede Session, die `/feature-build` fährt, in einem Lane- oder
Worker-Worktree läuft oder ihren Auftrag von einer anderen Session bekommt, ist ein **Worker**, gleich wer sie
gestartet hat; im Zweifel ist eine Session nicht der Chef. Der Chef entscheidet alles andere innerhalb angenommener
Roadmap-Zeilen und berichtet danach (Zuschnitt, Umsetzungsweg, Teststrategie, Nachbesserungen aus Reviews,
Einordnung von Review-Funden); er gibt kleine Fund-Pakete frei (höchstens drei Tasks, aus Zeilen, die Kevin
angenommen hat, nichts aus (1)–(7)), gibt Workern Startaufträge für freigegebene Ledger, pusht Branches und das
private Roadmap-Repo und öffnet PRs. Fragen an Kevin gehen gesammelt und mit Empfehlung; im Zweifel fragen statt raten.
**Triage:** Was Kevin diktiert, gilt als angenommen; alles andere schlägt der Chef vor, Kevin bestätigt gesammelt.
Kein eigener Fund wird ohne Kevin `geplant`.
**Merge:** Der Chef merged Produkt-PRs nach grüner CI im ersten Versuch, einen je CI-Zyklus, vorher die
Kombinationsprüfung (main mit dem PR in einem Wegwerf-Worktree). PRs an Harness und Gates (§2/§3 dieser Datei, die
Pfade aus `scripts/dev/harness-paths.txt`) merged Kevin, oder der Chef auf Kevins ausdrückliches Wort im selben Zug.
Ein roter `main` wird nicht nach vorn gefixt; flaky heißt Rerun plus Roadmap-Zeile.

**Zwei Wahrheiten:** `tasks/private/ROADMAP.md` ist die einzige Reihenfolge-Wahrheit (Kevin kuratiert von Hand; eigenes
privates Repo, nie im öffentlichen Baum), `tasks/<slug>.md` die einzige Fortschritts-Wahrheit (`[ ]`/`[x]`/`[~]`/`[?]`,
`tasks/README.md`). Kein Skript und keine Session sucht sich Arbeit außerhalb dieser beiden Dateien.

**Claude tut nie von sich aus:** pushen · PR öffnen oder mergen · taggen oder publizieren · `main` direkt ändern ·
Freigaben setzen oder Gates überspringen · einen Bau über die Bau-Slots hinaus starten · VMs außerhalb des
Proxmox-Pools `adminhelper-ci` anfassen oder Templates löschen · Homelab-Namen, Tokens oder Sicherheitsfunde in
versionierte Dateien schreiben. Wo ein Skill heute am Ende pushen oder einen PR öffnen will, ist der
Permission-Prompt Kevins Entscheidung. Ausnahme ist der Chef im Rahmen von „Entscheidungen“ und „Merge“; Worker
pushen, mergen und geben nie frei. Innerhalb des Pools `adminhelper-ci` darf Claude VMs klonen, baken und zerstören
(Freigabe 2026-09-08). **Committen tut seit Stufe 4 `scripts/dev/task-close.sh`, nicht die Session:** es fährt das
`Verify:` der Task, prüft Diff-Scan, Scope und Sec-Sperre, setzt den Haken mit der Summary-Zeile als Evidenz und
committet Code + Ledger. Im Loop sind `git add|commit|checkout|restore|stash` in den Settings hart verboten; in
Kevins Sessions prompten sie nicht (eine Abfrage, die immer bestätigt wird, hält nur den Bau auf).
**Harness-Schutz:** Ein PreToolUse-Hook verweigert im autonomen Lauf Änderungen an `scripts/dev/harness-paths.txt`
(Regeln, Skills, Gates), in jedem Modus Löschen per Glob in geteilten Temp-Verzeichnissen und die Umgehung des
pre-commit-Hooks (`review.sh sec`); Einzelheiten und der Kill-Switch `bash scripts/dev/harness.sh off|on|status`
(Kevins Handgriff): AUTONOMOUS.md, „Die Automatisierungs-Schicht“.

**Release-Kanäle (ab Stufe 13 per Skript, bis dahin von Hand):** `beta` nach jedem grünen Wochenlauf, `rc` schneidet
Kevin, `stable` frühestens 7 Tage nach dem RC, `hotfix` als einziger Weg daran vorbei: `.claude/rules/release.md`.
```

§3 Trigger 3 (ersetzt `CLAUDE.md:112–113`):

```markdown
3. Ein Deckel ist erreicht (`aktiv` 2 · `bereit` 2 · `pr` 3 · `neu` 20), oder ein dritter Bau-Lauf, ein zweiter
   VM-Lauf oder ein Bau neben einem nicht disjunkten würde starten.
```

§3, letzter Satz der Schweigeregel (`CLAUDE.md:123`): „… ausgenommen push und merge des Chefs nach §2 „Merge“.“

§6 (`CLAUDE.md:174–175`): „Tags setzt Kevin; push und merge der Chef (§2 „Merge“), ohne Chef Kevin.“

§8 (`CLAUDE.md:203`): „Die Dev-Box hat Docker, aber kein Display. Schwere Suiten laufen auf ephemeren Proxmox-VMs, …“

Was der Entwurf gegenüber heute weglässt oder verschiebt:
- Den Satz „heute `adminhelper-ac`“: Der Chef startet täglich frisch, der Name der Session wechselt.
- Die Einzelheiten des Harness-Schutzes (die Temp-Verzeichnisse, `core.hooksPath`) und des Kill-Switch. Sie stehen
  in AUTONOMOUS.md „Die Automatisierungs-Schicht“ und DEVELOPMENT.md „Harness-Schutz und Kill-Switch“. CLAUDE.md
  behält die Regel und den Verweis.
- Die Release-Kanäle auf zwei Zeilen; der Ablauf steht in `.claude/rules/release.md`.
- „Für den Runner sind `git add` … verboten“ wird zu „Im Loop …“, denn der Builder nimmt die Settings des Runners.

## Widersprüche in Skills und Doku (geprüft gegen origin/main@d2a654cd)

| Stelle | Widerspruch | Umgang |
|---|---|---|
| `.claude/skills/roadmap/SKILL.md:36` | Deckel `aktiv` 1 | eine Zeile, T2 |
| `.claude/skills/feature-plan/SKILL.md:232` | „Die Lane ist die Ausnahme vom Deckel „genau ein Bau aktiv““ | eine Zeile, T3 |
| `.claude/skills/feature-plan/SKILL.md:191` | Das Gate legt eine neue Zeile an und setzt sie auf `geplant`, auch für einen eigenen Fund (Regel 7) | ein Halbsatz, T3 |
| `.claude/skills/feature-build/SKILL.md:281` | Das Modell des Reviews am Ende kommt aus `review.sh risk`, kann also Sonnet sein (Regel 5) | eine Zeile, T3 |
| `.claude/skills/test/SKILL.md:277`, `AUTONOMOUS.md:370` | „this dev box deliberately has no docker“, „die Dev-Box hat bewusst kein Docker“ | je eine Zeile, T3 |
| Skills, AUTONOMOUS.md, DEVELOPMENT.md, `scripts/` (28 Stellen) | „Aufsicht“, „Aufsichts-Session“ | Folge-Zeile; CLAUDE.md bildet die Brücke |
| `.claude/skills/feature-review/SKILL.md:10` | „Läuft auf Sonnet — Opus nur bei einem Risikopfad“ | kein Widerspruch: das ist der Review je Task |
| `/roadmap triage` | „Annehmen“ setzt `geplant` | kein Widerspruch: Kevin antwortet in der Triage selbst |

## Trade-offs & Alternativen

- **Zeilenbudget.**
  - Das Roadmap-Dokument nennt als Ziel ≤ 185 Zeilen. Das erreicht dieses Vorhaben nicht; dafür müsste es etwa
    40 Zeilen aus §5–§7 verschieben, was ein eigener Schnitt wäre.
  - Empfehlung: kein Zuwachs (≤ 226), dazu eine Prüfung in `skill_consistency_test`, die mehr als 226 Zeilen rot macht.
    Dann wächst die Datei nicht unbemerkt. Offene Frage 1.
- **Deckel im Code.**
  - „2 Bau-Slots“ heißt `aktiv` 2 in `roadmap.py` und im Status-Hook. Ohne das warnte der AH-STATUS schon beim
    zweiten Bau.
  - Disjunkt bleiben müssen die beiden Bauten trotzdem: Die Parallel-Prüfung am Gate bleibt.
- **Umbenennen jetzt oder später.** Ein Rename über 28 Stellen samt Test bläht einen Regel-PR auf, den Kevin Satz für
  Satz liest. Empfehlung: eigene Folge-Zeile, Brücke in CLAUDE.md.

## Risiken & Rollback

- Ein Regel-PR ändert, was jede Session tut. Rollback ist `git revert` des Merges.
- `aktiv` 2 lässt einen zweiten Bau zu. Die Schutzwirkung, dass nur disjunkte Ledger parallel laufen, liegt weiter im
  Gate (`feature-plan`) und in `next --exclude-components`, nicht im Deckel.
- Fehlt eine Brücke beim Namen, sucht eine frische Session die „Aufsicht“ und findet den „Chef“ nicht. Die Brücke
  steht deshalb in dem Satz, der den Chef definiert.

## Doku-Impact

CLAUDE.md ist selbst die Doku. Dazu ein CHANGELOG-Eintrag unter Changed und die Einzeiler in Skills und AUTONOMOUS.md.
`docs/` bleibt unberührt.

## Offene Fragen am Gate (Kevin)

1. **Zeilenbudget:** ≤ 226 halten und mit einer Prüfung festschreiben (Empfehlung), oder schon jetzt Richtung ≤ 185?
2. **„2 Bau-Slots“:** Heißt das Deckel `aktiv` 2 in Code und Status, und bleibt die Disjunkt-Pflicht? Empfehlung: ja,
   beides.
3. **„Ein roter `main` wird nicht nach vorn gefixt“:** Ist gemeint, dass der Merge zurückgenommen wird (Revert), bis
   die Ursache klar ist? Der Entwurf übernimmt den Satz wörtlich; mit einem Ja käme „der Merge wird zurückgenommen“
   dazu.
4. **Tagesbericht:** Es gibt ihn noch nicht. Soll die Regel ihn schon nennen (Entwurf) oder erst mit seiner Stufe?
5. **Öffentlicher Wortlaut des Restrisikos:** Der Entwurf sagt allgemein „Code einer Task läuft mit Kevins Rechten“
   und nennt den Kanal aus R-0258 nicht, weil CLAUDE.md öffentlich ist. Passt das?
6. **„1 VM-Lauf zugleich“:** Gemeint sind Läufe über `/test` bzw. `heavy.sh`/`multibox.sh`, nicht eine warme Box, die
   nur steht. Richtig?
