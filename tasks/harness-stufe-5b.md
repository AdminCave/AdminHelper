<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 5b — Planen und Beweis — Task-Ledger
Status: freigegeben · Branch: harness/stufe-5b · Commit-Granularität: pro Task · Review: pro Task (Sonnet, 10 min) · Modell: Opus
Spec: docs/features/harness-stufe-5.md (Roadmap R-0008, Teil 5b)
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: nein — Skill-Texte, `ledger.sh`, Doku.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Hängt ab von: harness-stufe-5a (gemergt) — die Skills rufen `roadmap.py`

### T1 — Status-Folge und Kopf-Feld `Heavy:` in Ledger-Doku und Lint  [ ]
Komponente: scripts · Dateien: tasks/README.md, scripts/dev/ledger.sh, scripts/tests/ledger_test.sh
Änderung:
- `tasks/README.md` beschreibt die Status-Folge `geplant` → `freigegeben` → `aktiv` → `bereit` → `erledigt` | `blockiert` mit der Bedeutung jedes Zustands.
- Dazu das Kopf-Feld `Heavy: none | linux-full | scenario <flags> | windows`. `Fast-Suite:` und `Warm-Profil:` gelten für neue Ledger als veraltet, werden aber weiter gelesen.
- `ledger.sh lint` prüft den Wert von `Heavy:` für Ledger, die das Feld tragen. Ein Ledger mit beiden Formen ist ein Fehler.
- Tests: gültige und ungültige `Heavy:`-Werte, beide Formen zugleich, und ein altes Ledger ohne `Heavy:` bleibt grün.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: tasks/README.md

### T2 — Beweis-Konvention A–D: Felder, Vorlage, Lint  [ ]
Komponente: scripts · Dateien: tasks/README.md, tasks/templates/task.md, scripts/dev/ledger.sh
Änderung:
- `tasks/README.md` beschreibt die vier Beweisklassen aus dem Roadmap-Dokument §8.3 und die optionalen Task-Zeilen:
  - `Beweis:` (Branch + SHA + Kommando + erwartete Ausgabe),
  - `Orakel:` (crash|contract|property|differential|mutation-sample|coverage|analyzer|metric),
  - `Refuter:`,
  - `Dedup-Key:` (`<klasse>:<komponente>:<datei>:<symbol>`),
  - `Metrik:` (Klasse B),
  - `Kosten:`,
  - `HEAD:`.
- Dazu kommt `Semantik:`, Pflicht im Modus `--kurz`.
- Die Vorlage `tasks/templates/task.md` trägt die optionalen Zeilen als Kommentar.
- `ledger.sh lint` prüft die Form, wo die Zeilen vorkommen: `Orakel:` aus der Liste, `Dedup-Key:` mit genau drei `:`, `HEAD:` als SHA.
- Tests in `ledger_test.sh` (die Datei ist implizit erlaubt): je Feld gültig und ungültig.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: tasks/README.md
Abhängt von: T1

### T3 — `feature-plan`: Plan auf dem Branch, Roadmap am Gate, `Heavy:`  [ ]
Komponente: scripts · Dateien: .claude/skills/feature-plan/SKILL.md
Änderung:
- **R-0065:** Spec und Ledger sind der erste Commit auf dem Feature-Branch (`chore(plan): …`), gesetzt am Gate. Die Freigabe ist `roadmap.py approve` plus der Commit, der den Ledger-Kopf auf `freigegeben` setzt. Die veralteten Stellen fallen weg: :11, :133–135, :143–148.
- **Roadmap am Gate:**
  - Das Gate liest die Zeile per `roadmap.py show <id>` und trägt ein neues Vorhaben per `roadmap.py add` ein, bevor es präsentiert wird.
  - Die Parallel-Prüfung läuft gegen **alle** `aktiv`- und `freigegeben`-Zeilen: Komponenten-Disjunktheit und geteilte Contract-Dateien.
  - Zeilenangaben werden vor dem Schreiben neu gegrept.
- **Ledger-Kopf:** Die Vorlage nutzt `Heavy:`.
- Nachweis: Der Skill-Text enthält keine Stelle mehr, die „auf `main` committen“ verlangt (grep im Test von T6).
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (T6)
Abhängt von: T1

### T4 — `feature-plan --kurz` und `--bundle`  [ ]
Komponente: scripts · Dateien: .claude/skills/feature-plan/SKILL.md
Änderung:
- **`--kurz <R-id>`:**
  - erzeugt ein Kurz-Ledger mit 1–3 Tasks aus Roadmap-Zeile und Beweis, ohne Spec;
  - `Review: am Ende`;
  - Pflichtzeile `Semantik:`, geprüft gegen die passende Stelle unter `docs/`, mit Zitat;
  - `Beweis:` aus der Zeile.
- **`--bundle <komponente>`:**
  - bündelt `neu`- oder `geplant`-Zeilen der Klasse REF einer Komponente zu einem Sammel-Ledger mit höchstens 15 Tasks;
  - andere Klassen werden verweigert, mit Grund.
- Beide Modi enden am selben Gate.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (T6)
Abhängt von: T3

### T5 — `feature-build` kennt `freigegeben`, `bereit` und `Heavy:`  [ ]
Komponente: scripts · Dateien: .claude/skills/feature-build/SKILL.md, AUTONOMOUS.md
Änderung:
- **Start:** `feature-build` startet `freigegeben` (setzt `aktiv`) und interaktiv wie bisher auch `geplant` mit ausdrücklichem Pfad.
- **Abschluss:**
  - setzt `bereit`, sobald alle Tasks zu sind und die Verifikation läuft;
  - setzt `erledigt` mit dem PR;
  - zieht die Roadmap-Zeile per `roadmap.py status` mit.
- **Heavy:** `Heavy:` wird gelesen, `Fast-Suite:`/`Warm-Profil:` weiter als Rückfall.
- **AUTONOMOUS.md:** :15–16 nennt die vollständige Status-Folge; die Stellen zu R-0065 stimmen mit dem Skill überein.
- Nachweis: der Test in T6.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: AUTONOMOUS.md
Abhängt von: T3

### T6 — Konsistenz-Test der Skill-Texte und Beweis-Konvention in der Entwickler-Doku  [ ]
Komponente: scripts · Dateien: scripts/tests/skill_consistency_test.sh (neu, SPDX), scripts/tests/run.sh (nur Registrierung), docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung:
- Ein hermetischer Test prüft die Skill- und Doku-Texte auf die Widersprüche, die hier behoben werden. Er schlägt fehl, wenn:
  - ein Skill oder `AUTONOMOUS.md` „Spec + Ledger auf `main`“ verlangt;
  - eine Status-Liste `freigegeben` oder `bereit` auslässt;
  - `feature-plan` eine Kopf-Vorlage ohne `Heavy:` zeigt.
- `cicd.html` DE+EN beschreibt die Beweis-Konvention: Klassen, Felder und wo sie geprüft werden.
- Gegenprobe: gegen den Stand vor T3 wird der Test rot.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: docs/developer/cicd.html · docs/en/developer/cicd.html
Abhängt von: T2, T3, T4, T5

## Abschluss (nach T6, vor dem PR)

`/feature-plan --kurz` auf einer echten `neu`-Zeile, einem Kandidaten der Aufsicht: das Ergebnis ist ein
2-Task-Ledger mit `Beweis:` und `Semantik:`. Das Ledger wird verworfen oder behalten, wie Kevin will. Dazu ein
Plan-Lauf auf einer Zeile, deren Komponente mit einer `aktiv`-Zeile kollidiert: Er muss warnen.
