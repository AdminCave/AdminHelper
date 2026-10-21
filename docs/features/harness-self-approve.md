<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness: die Session gibt geplante Vorhaben selbst frei

Roadmap R-0567 (REF, Harness) · Kevins Wort 2026-10-21: „Ich möchte die Dinge, wenn diese geplant sind, nicht mehr
freigeben müssen … gebe diese bitte immer selber frei … passe die Regeln ggf. an.“
Zeilenangaben gelten für `origin/main@82e4a7b8`; die Bau-Session greppt sie beim Start neu.

## Problem / Motivation

- Die Freigabe eines Plans ist heute Kevins Schritt: Er tippt `! python3 scripts/dev/roadmap.py approve R-nnnn`, erst
  danach baut `/feature-build`. Das steht an den Stellen der Tabelle unten und hält jedes geplante Vorhaben an,
  bis Kevin zurück ist, auch wenn der Plan keine Frage an ihn offen hat.
- `roadmap.py approve` löscht die Notiz der Zeile: `cmd_approve` ruft `roadmap.set_status(args.id, new, None,
  args.today)` (`scripts/dev/roadmap.py:737`), und `set_status` schreibt bei einem Statuswechsel nur das neue Wort
  plus die übergebene Notiz (`:401-405`). Probe auf `82e4a7b8`: eine Zeile `geplant (Semantik-Frage: x)` steht nach
  `approve` als `freigegeben` da. Anders als `status` hat `approve` kein `--note`, die Notiz lässt sich nicht
  mitgeben. Notizen an `geplant`-Zeilen tragen oft Kevins Vorgaben für den Plan („Weg beim Plan …“, „Semantik-Frage:
  …“); führt die Session `approve` jetzt bei jedem Plan selbst aus, gingen sie regelmäßig verloren.

Stellen, die die Freigabe Kevin vorbehalten (grep nach „approve“, „Freigabe“, „freigegeben“, „gibt frei“, „tippt“
auf `82e4a7b8`; Treffer zum Prüfer-Urteil `approve` und zu Produkt-Texten ausgenommen):

| Datei | Stelle | heute |
|---|---|---|
| `CLAUDE.md` | §2 `:24` | „Kevin … entscheidet: … Freigabe eines Plans, …“ |
| `CLAUDE.md` | §4 `:62-63` | „→ Kevin gibt frei: er tippt `! python3 scripts/dev/roadmap.py approve R-nnnn`“ |
| `CLAUDE.md` | §8 `:127` | „neu → geplant → freigegeben (nur Kevin) → …“ |
| `CLAUDE.md` | §11 `:171` | „Claude tut nie … eine Freigabe setzen“ |
| `.claude/skills/feature-plan/SKILL.md` | `:3`, `:10`, `:137`, `:139-142` | „Design-Gate zur menschlichen Freigabe“, „auf Freigabe warten“, „Kevin kann beide freigeben“, Satz „Freigabe: `! python3 …`“, „Die Freigabe ist Kevins … die Session setzt sie nie“ |
| `.claude/skills/feature-build/SKILL.md` | `:3`, `:31` | „nachdem Kevin die Roadmap-Zeile freigegeben hat“, „Die Freigabe ist Kevins `roadmap.py approve`“ |
| `.claude/skills/roadmap/SKILL.md` | `:17-19`, `:80-81` | „Nie: … `approve` (die Freigabe tippt Kevin selbst)“, „`approve` tippt Kevin selbst“ |
| `tasks/README.md` | `:21`, `:88-89` | „Die Freigabe ist Kevins `roadmap.py approve`“, Test-Löschung „kommt mit dem Plan-Commit, den Kevin liest“ |
| `DEVELOPMENT.md` | `:600` | „`approve` ist `geplant` -> `freigegeben`, Kevins Freigabe“ |
| `docs/developer/cicd.html` / `docs/en/developer/cicd.html` | `:184` / `:182` | REG-Zeile: „Die Freigabe bleibt Kevins Haken.“ / „Releasing it stays Kevin's tick.“ |
| `scripts/dev/roadmap.py` | `:16`, `:1152` | Hilfetext „geplant -> freigegeben (Kevin's approval)“ |

Geprüft und ohne Änderung: `scripts/dev/hooks/harness-guard.sh` (prüft nur Glob-Löschen in Temp-Verzeichnissen und
Hook-Umgehung, nichts zu `approve`), `.claude/settings.json` (`Bash(python3 scripts/dev/roadmap.py:*)` ist erlaubt,
nichts gesperrt), `scripts/dev/hooks/session-status.sh` (kein Freigabe-Text, keine Warnung zu `geplant`),
`.claude/agents/*.md` (dort ist `approve` das Prüfer-Urteil). Historische Specs unter `docs/features/` bleiben, wie
sie sind.

## Ziel & Nicht-Ziele

**Ziel:** Eine knappe, eindeutige Regel an jeder Stelle oben:

- **Wer:** die Session. **Wann:** sofort nach dem Plan-Commit von `/feature-plan` (Gate). **Wie:**
  `python3 scripts/dev/roadmap.py approve R-nnnn` (beim Bündel je Zeile); `approve` behält die Notiz der Zeile.
- **Was Kevin bleibt:** alles aus CLAUDE.md §2 außer der Freigabe des Plans: Reihenfolge und Inhalt der Roadmap
  (also auch, welche Zeile überhaupt `geplant` wird), sichtbares Verhalten, API-Verträge, Datenmigrationen,
  hingenommenes Restrisiko, Geld- und Zeitdeckel, Release, Tag, Ruleset, Repo-Einstellungen, sudo, Tokens,
  Passwörter.
- **Offene Fragen aus Kevins Bereich:** Eine Entscheidung aus diesem Bereich, die weder die Roadmap-Zeile noch Kevins
  Wort schon trifft, stellt das Gate als Frage mit Empfehlung. Die Task, die an ihr hängt, steht im Plan auf
  `[?] (<Frage>)` und wird erst nach seiner Antwort gebaut; die übrigen baut die Session sofort. Hängt jede Task an
  einer solchen Frage, bleibt die Zeile `geplant` (ein Ledger `aktiv` ohne offene `[ ]`-Task verletzt die Invariante
  aus `tasks/README.md`, `ledger.sh lint` meldet das).
- **Nie:** eine Zeile ohne committeten Plan freigeben (eine in der Triage angenommene Zeile ist `geplant`, hat aber
  noch kein Ledger).

**Nicht-Ziele:**

- Kein mechanischer Riegel in `roadmap.py`, der `approve` ohne Ledger-Spalte verweigert (siehe Trade-offs).
- `roadmap.py status` ohne `--note` löscht die Notiz weiterhin (R-0438, zurückgestellt). Die Skills sagen, dass jeder
  `status`-Aufruf die Notiz wörtlich mitgibt; den Code dafür ändert dieses Vorhaben nicht (offene Frage 2).
- Keine Änderung an `heavy.sh`: es legt REG-Zeilen weiter als `neu` an, das Annehmen bleibt Kevins Triage.

## Betroffene Komponenten & Dateien

Komponente `scripts` (Harness): `scripts/dev/roadmap.py`, `scripts/dev/tests/test_roadmap.py`,
`scripts/tests/ledger_test.sh`, `CLAUDE.md`, `tasks/README.md`, `.claude/skills/feature-plan/SKILL.md`,
`.claude/skills/feature-build/SKILL.md`, `.claude/skills/roadmap/SKILL.md`, `DEVELOPMENT.md`, `CHANGELOG.md`,
`docs/developer/cicd.html`, `docs/en/developer/cicd.html`. Alles Harness-Pfade (Risikopfad, `security` prüft mit).

## Datenmodell / API / Migrationen

Keine Server-API, kein Alembic, kein Vertrag zwischen Server, Web, Desktop und Agent. Einzige Verhaltensänderung im
Code: `roadmap.py approve` (und `approve --revoke`) ersetzt nur das Statuswort und lässt den Text dahinter in der
Status-Spalte wörtlich stehen. Die Roadmap-Datei behält ihr Format.

## Externe Integrationen

Keine.

## Neue Texte (Vorgabe für die Tasks)

**CLAUDE.md**

- §2 (`:24-27`): „Freigabe eines Plans,“ entfällt aus der Liste; nach dem ersten Satz neu: „Den Plan eines Vorhabens
  gibt die Session selbst frei (§4, Kevin 2026-10-21).“
- §4 (`:61-65`): „→ Kevin gibt frei: er tippt `! python3 scripts/dev/roadmap.py approve R-nnnn`; die Freigabe ist
  dieser Roadmap-Status →“ wird „→ die Session gibt sofort danach selbst frei: `python3 scripts/dev/roadmap.py approve
  R-nnnn` (Kevin 2026-10-21; die Notiz der Zeile bleibt); die Freigabe ist dieser Roadmap-Status →“. Hinter dem Satz
  bis `roadmap.py sync` neu: „Eine Entscheidung aus Kevins Bereich (§2), die weder die Roadmap-Zeile noch Kevins Wort
  schon trifft, stellt das Gate als Frage mit Empfehlung; die Task, die an ihr hängt, steht auf `[?]`, bis er
  antwortet, die übrigen baut die Session. Hängt jede Task an einer solchen Frage, bleibt die Zeile `geplant`.“
- §8 (`:127`): „freigegeben (nur Kevin)“ wird „freigegeben (die Session nach dem Plan-Commit, §4)“.
- §11 (`:171`): „eine Freigabe setzen“ wird „eine Zeile ohne committeten Plan freigeben“.

**tasks/README.md**

- `:21`: „Die Freigabe ist Kevins `roadmap.py approve` für die Roadmap-Zeile; erst dann setzt …“ wird „Die Freigabe ist
  `roadmap.py approve` für die Roadmap-Zeile, die die Session gleich nach dem Plan-Commit selbst setzt; erst dann
  setzt …“.
- `:88-89`: „Sie kommt mit dem Plan-Commit, den Kevin liest.“ wird „Sie kommt mit dem Plan-Commit, und der Bericht am
  Gate nennt sie Kevin.“

**.claude/skills/feature-plan/SKILL.md**

- `:3` (description): „Endet an einem Design-Gate zur menschlichen Freigabe — implementiert selbst nichts.“ wird
  „Endet an einem Design-Gate mit Bericht an Kevin; danach gibt die Session die Zeile selbst frei — implementiert
  selbst nichts.“
- `:10`: „**Am Ende: Design-Gate — stoppen, auf Freigabe warten.“ wird „**Am Ende: Design-Gate — Bericht an Kevin,
  dann gibt die Session selbst frei (4).“
- `:69`, hinter „… gehört sie als offene Frage in die Spec.“: „Ist es eine Entscheidung aus Kevins Bereich (CLAUDE.md
  §2), die weder die Roadmap-Zeile noch sein Wort schon trifft, trägt die Task `[?] (<Frage>)` in der Überschrift
  (die Form von `ledger.sh mark-question`) und wird erst nach seiner Antwort gebaut.“
- `:118-121` (Roadmap): hinter „`roadmap.py status R-nnnn geplant --ledger tasks/<slug>.md`“ neu: „; trägt die Zeile
  eine Notiz, gibt das Gate sie wörtlich mit `--note` wieder mit (`status` ohne `--note` löscht sie)“.
- `:137`: „(`geplant`, Kevin kann beide freigeben)“ wird „(`geplant` mit Plan auf seinem Branch: die Session gibt
  beide frei)“.
- `:139-141` (Präsentieren): „… **alle offenen Fragen** herausgestellt, und den Satz: „Freigabe: … `/feature-build
  tasks/<slug>.md`.““ wird „… **alle offenen Fragen** herausgestellt, je mit Empfehlung und den `[?]`-Tasks, dazu
  jede `Test-Löschung:`.“
- `:142` wird „**Freigabe:** gleich nach dem Bericht gibt die Session frei, `python3 scripts/dev/roadmap.py approve
  R-nnnn` (beim Bündel je Zeile; die Notiz bleibt), außer jede Task steht auf `[?]`; danach
  `/feature-build tasks/<slug>.md`. Nie für eine Zeile ohne committeten Plan (CLAUDE.md §4, §11).“

**.claude/skills/feature-build/SKILL.md**

- `:3` (description): „Nutzen, nachdem Kevin die Roadmap-Zeile freigegeben hat.“ wird „Nutzen, sobald die
  Roadmap-Zeile freigegeben ist; die Session gibt sie nach dem Plan-Commit selbst frei (CLAUDE.md §4).“
- §2 `:31` „Roadmap nicht `freigegeben` → melden, nicht bauen. Die Freigabe ist Kevins `roadmap.py approve`.“ wird zu
  zwei Punkten: „Roadmap `geplant`, Kopf `geplant`, das Ledger auf `feature/<slug>` committet und nicht jede Task
  `[?]` → die Session gibt frei (`python3 scripts/dev/roadmap.py approve R-nnnn`, CLAUDE.md §4), dann wie im ersten
  Punkt.“ und „Sonst nicht `freigegeben` → melden, nicht bauen.“ Unter der Liste neu: „Jeder `roadmap.py
  status`-Aufruf dieses Skills gibt eine Notiz der Zeile wörtlich mit `--note` wieder mit (`status` ohne `--note`
  löscht sie).“
- §3, vor „Neue Funde außerhalb der Task …“ (`:66`): „Eine `[?]`-Task aus dem Gate (CLAUDE.md §4) wartet auf Kevins
  Antwort und baut dann wie 1–5, die Antwort im Auftrag an den `builder`.“
- §4.1 (`:70-71`), angehängt: „Steht noch eine `[?]`-Task, wartet der Abschluss auf Kevins Antwort (bauen oder
  `[~]`).“

**.claude/skills/roadmap/SKILL.md**

- `:17-19`: „`approve` (die Freigabe tippt Kevin selbst, CLAUDE.md §4)“ wird „`approve` (die Freigabe setzt die
  Session nach dem Plan-Commit von `/feature-plan`, CLAUDE.md §4)“.
- `:80-81`: „(`approve` tippt Kevin selbst: `! python3 scripts/dev/roadmap.py approve R-nnnn`, CLAUDE.md §4)“ wird
  „(`approve` setzt die Session nach dem Plan-Commit von `/feature-plan`, CLAUDE.md §4)“.

**DEVELOPMENT.md** `:600`: „`approve` ist `geplant` -> `freigegeben`, die Freigabe, die die Session nach dem
Plan-Commit von `/feature-plan` setzt (CLAUDE.md §4); `--revoke` nimmt sie zurueck. Beide lassen die Notiz der Zeile
stehen, anders als `status` ohne `--note`.“

**cicd.html** REG-Zeile: DE „Die Freigabe bleibt Kevins Haken.“ wird „Annehmen bleibt Kevins Haken
(<code>/roadmap triage</code>); den Plan gibt danach die Session frei.“; EN „Releasing it stays Kevin's tick.“ wird
„Accepting it stays Kevin's tick (<code>/roadmap triage</code>); the session approves the plan afterwards.“

**roadmap.py** Hilfetexte: `:16` „approve <id> [--revoke]     geplant -> freigegeben, or back; the note stays“;
`:1152` „geplant -> freigegeben (the session's approval after the plan commit); the note stays“.

**CHANGELOG.md**, `## [Unreleased]` → `### Changed`, oben: „**Plaene gibt die Session selbst frei
(Entwickler-Werkzeuge, Kevin 2026-10-21):** Nach dem Plan-Commit von `/feature-plan` setzt die Session
`roadmap.py approve` selbst und baut. Kevin behaelt seine Entscheidungen aus `CLAUDE.md` §2 (Roadmap, sichtbares
Verhalten, API-Vertraege, Datenmigrationen, Restrisiko, Release); eine offene Frage aus seinem Bereich haelt nur die
Task, die an ihr haengt (`[?]`). `roadmap.py approve` behaelt die Notiz der Zeile. Regeln: `CLAUDE.md` §2, §4, §8,
§11 und `tasks/README.md`.“

## Trade-offs & Alternativen

1. **Die Notiz bei `approve` — Code statt Verfahren (Empfehlung, gebaut).** `approve` hat kein `--note`; das
   Verfahren „Notiz lesen, `approve`, dann `status R-nnnn freigegeben --note "<alt>"`“ wären zwei Schreibvorgänge und
   zwei Commits im privaten Repo je Freigabe, und die Notiz liefe durch Shell-Quoting (Klammern, Anführungszeichen,
   Apostrophe), also genau die Stelle, an der Notizen heute verloren gehen. Der Code-Weg ist eine Zeile Logik in
   `cmd_approve` mit einem Test. Er bleibt richtig, wenn R-0438 später `status` ändert.
2. **R-0438 mitnehmen (alle Statuswechsel behalten die Notiz).** Root-Cause für `status`, aber eine eigene Semantik
   (veraltete Notizen bleiben stehen, bis jemand `--note ""` setzt) und eine zurückgestellte Zeile, die nur auf Kevins
   Wort kommt. Nicht gebaut; offene Frage 2.
3. **Riegel in `approve`: ohne Ledger-Spalte Exit 2.** Würde „nie ohne committeten Plan“ mechanisch prüfen, bricht
   aber zwei bestehende Tests mit Zeilen ohne Ledger (`test_approve_and_revoke`, `test_the_life_of_a_row`) und prüft
   nur die Spalte, nicht den Commit auf dem Branch. Verworfen (YAGNI); die Regel steht in §11 und in beiden Skills.
4. **Offene Kevin-Frage: Task wartet (`[?]`, Empfehlung, gebaut) oder die Session baut ihre Empfehlung sofort.**
   Warten lässt die Entscheidung bei Kevin, wie §2 es sagt; ein späteres Nein nach dem Bau kostet Rückbau. Dafür warten
   die betroffenen Tasks auf ihn. Offene Frage 1.

## Risiken & Rollback

- Ein Plan geht ohne Kevins Blick in den Bau. Gegengewicht: Inhalt und Reihenfolge der Roadmap bleiben Kevins (nur
  angenommene Zeilen werden geplant), Fragen aus seinem Bereich halten ihre Task an, der Gate-Bericht nennt jede
  `Test-Löschung:`, und Reviewer, `tester` und `security` prüfen wie bisher.
- Rollback: `git revert` des Merge-Commits stellt Texte und `approve` wieder her; eine schon freigegebene Zeile nimmt
  `roadmap.py approve R-nnnn --revoke` zurück.

## Doku-Impact

`DEVELOPMENT.md` (`approve`), `docs/developer/cicd.html` DE + EN (REG-Zeile), `CHANGELOG.md` (Changed); die Regeln
selbst stehen in `CLAUDE.md`, `tasks/README.md` und den Skills.

## Offene Fragen

1. **Hält eine offene Frage aus Kevins Bereich ihre Task bis zur Antwort an?** Empfehlung (gebaut): ja, `[?]` für die
   Task, die übrigen baut die Session; hängt jede Task an einer Frage, bleibt die Zeile `geplant`. Alternative: die
   Session baut ihre Empfehlung sofort, Kevin kann bis zum Merge widersprechen.
2. **R-0438 mitnehmen?** Empfehlung: nein, getrennt als eigenes `--kurz`-Vorhaben, wenn Kevin es will. Bis dahin
   geben die Skills die Notiz bei `status` wörtlich mit.
3. **Test-Löschungen ohne Kevins Blick vor dem Bau?** Empfehlung (gebaut): der Gate-Bericht nennt jede
   `Test-Löschung:`, die Task wartet nicht. Alternative: jede Task mit `Test-Löschung:` steht auf `[?]`.
4. **Gilt die Selbstfreigabe auch für SEC-Zeilen?** Empfehlung (gebaut, Kevins „immer“): ja; Restrisiko bleibt seine
   Frage und hält ihre Task an.
