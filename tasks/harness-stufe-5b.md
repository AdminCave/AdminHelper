<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 5b — Planen und Beweis — Task-Ledger
Status: aktiv · Branch: harness/stufe-5b · Commit-Granularität: pro Task · Review: pro Task (Sonnet, 10 min) · Modell: Opus
Spec: docs/features/harness-stufe-5.md (Roadmap R-0008, Teil 5b)
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: nein — Skill-Texte, `ledger.sh`, Doku.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Hängt ab von: harness-stufe-5a (gemergt) — die Skills rufen `roadmap.py`

### T1 — Status-Folge und Kopf-Feld `Heavy:` in Ledger-Doku und Lint  [x]
Komponente: scripts · Dateien: tasks/README.md, scripts/dev/ledger.sh, scripts/tests/ledger_test.sh, tasks/harness-stufe-5c.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @b4802aa1 2026-09-25T13:15:58+02:00
Review: approve (sonnet, Runde 2 nach Verankerung)
Änderung:
- `tasks/README.md` beschreibt die Status-Folge `geplant` → `freigegeben` → `aktiv` → `bereit` → `erledigt` | `blockiert` mit der Bedeutung jedes Zustands.
- Dazu das Kopf-Feld `Heavy: none | linux-full | scenario <flags> | windows`. `Fast-Suite:` und `Warm-Profil:` gelten für neue Ledger als veraltet, werden aber weiter gelesen.
- `ledger.sh lint` prüft den Wert von `Heavy:` für Ledger, die das Feld tragen. Ein Ledger mit beiden Formen ist ein Fehler.
- Tests: gültige und ungültige `Heavy:`-Werte, beide Formen zugleich, und ein altes Ledger ohne `Heavy:` bleibt grün.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: tasks/README.md

### T2 — Beweis-Konvention A–D: Felder, Vorlage, Lint  [x]
Komponente: scripts · Dateien: tasks/README.md, tasks/templates/task.md, scripts/dev/ledger.sh, scripts/tests/ledger_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @9a2312e2 2026-09-25T13:31:08+02:00
Review: approve (sonnet, Runde 2 nach Metrik-Abgleich)
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

### T3 — `feature-plan`: Plan auf dem Branch, Roadmap am Gate, `Heavy:`  [x]
Komponente: scripts · Dateien: .claude/skills/feature-plan/SKILL.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @00e39cdc 2026-09-25T13:44:36+02:00
Review: approve (sonnet, Runde 2)
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

### T4 — `feature-plan --kurz` und `--bundle`  [x]
Komponente: scripts · Dateien: .claude/skills/feature-plan/SKILL.md, .claude/skills/roadmap/SKILL.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @6a932b0c 2026-09-25T13:57:17+02:00
Review: approve (sonnet, Runde 2 nach Bündel-Gate)
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

### T5 — `feature-build` kennt `freigegeben`, `bereit` und `Heavy:`  [x]
Komponente: scripts · Dateien: .claude/skills/feature-build/SKILL.md, AUTONOMOUS.md, CLAUDE.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @08637e25 2026-09-25T14:12:29+02:00
Review: approve (sonnet, Runde 2 nach bereit-zuerst)
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

### T6 — Konsistenz-Test der Skill-Texte und Beweis-Konvention in der Entwickler-Doku  [x]
Komponente: scripts · Dateien: scripts/tests/skill_consistency_test.sh (neu, SPDX), scripts/tests/run.sh (nur Registrierung), docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @8856cc2c 2026-09-25T14:57:15+02:00
Review: approve (sonnet, Runde 2)
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

### T7 — Schritt-Verweise im Abschluss von feature-build nach der Umnummerierung  [x]
Komponente: scripts · Dateien: .claude/skills/feature-build/SKILL.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @2528c88d 2026-09-25T15:06:03+02:00
Review: approve (sonnet)
Änderung: Fund nach T6 (T5 hat die Abschluss-Schritte umnummeriert, `Bereit — zuerst` ist neu Schritt 1):
- Schritt 3 sagt „schwere Suite überspringen … direkt zu Schritt 3“, zeigt also auf sich selbst; gemeint ist Schritt 4, der Review über den Branch-Diff.
- Schritt 4 sagt „Sub-Agent wie in Schritt 4“ und liest sich damit als Selbstverweis; gemeint ist Schritt 4 der Iteration.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (der Skill ist die Doku)
Abhängt von: T5

### T8 — `--kurz`: was bei `Semantik:` = Absicht geschieht, und die Commit-Vorlage ohne Spec  [x]
Komponente: scripts · Dateien: .claude/skills/feature-plan/SKILL.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @9e05209a 2026-09-25T15:43:35+02:00
Review: approve (sonnet, Runde 2)
Änderung: Fund aus der Abschluss-Probe (R-0095, 2026-09-25), Auftrag Kevin über die Aufsicht:
- §3a: Zeigt `Semantik:` das heutige Verhalten als Absicht, entsteht kein Ledger und kein Plan-Branch. Die Zeile bleibt `neu`, die Frage geht in Kevins Triage, erst seine Antwort macht wieder einen Plan daraus. Bisher sagte der Text nur „kein Fix-Task“, und das stand quer zu „1–3 Tasks“.
- §4: Die Commit-Vorlage am Gate nennt für `--kurz`, das keine Spec hat, `chore(plan): add ledger for <slug>`.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (der Skill ist die Doku)

### T9 — `roadmap.py status --ledger`: das Gate füllt die Spalte `Ledger`  [x]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py, .claude/skills/feature-plan/SKILL.md, DEVELOPMENT.md, scripts/tests/skill_consistency_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @03df6004 2026-09-25T15:56:51+02:00
Review: approve (opus, Runde 2; nit: Fixture für section nachgezogen, Mutationsprobe rot)
Änderung: Fund (4) aus der Abschluss-Probe (R-0095). Auftrag Kevin über die Aufsicht, 2026-09-25, Review mit Opus (roadmap.py ist ein Harness-Pfad aus 5a):
- `status … --note "tasks/<slug>.md"` schrieb den Pfad in die Status-Zelle, die Spalte `Ledger` blieb `—`. `--ledger` gab es nur bei `add`. Die Parallel-Prüfung am Gate und `next` (`components_of`) lesen aber die Spalte.
- `roadmap.py status` bekommt `--ledger L` und schreibt die Spalte `Ledger` wie `add --ledger`. Das wirkt auch ohne Statuswechsel (`new == old` ist erlaubt), so lassen sich Altzeilen nachziehen. Der Commit-Betreff nennt das Flag wie ` --revoke` bei `approve`.
- Tests in `test_roadmap.py`: Die Spalte wird gesetzt, die Status-Zelle bleibt ohne Pfad, der Aufruf ohne Statuswechsel geht, die Zeilenzahl hält, und der Betreff nennt das Flag.
- Der Gate-Text in `feature-plan` (§4 und der `--bundle`-Weg je Zeile) nutzt `--ledger` statt `--note "tasks/<slug>.md"`. `DEVELOPMENT.md` zählt das Flag bei `status` auf. Der Konsistenz-Test kennt die neue Form: keine Anleitung mehr mit `--note "tasks/…"`, und der Gate-Text nennt `--ledger`.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: DEVELOPMENT.md
Abhängt von: T8

### T10 — `roadmap.py status --pr`: die PR-Nummer landet in der Spalte, die `sync` liest  [x]
Komponente: scripts · Dateien: scripts/dev/roadmap.py, scripts/dev/tests/test_roadmap.py, .claude/skills/feature-build/SKILL.md, DEVELOPMENT.md, scripts/tests/skill_consistency_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @d518c666 2026-09-25T16:34:53+02:00
Review: approve (opus, Runde 2; nit: erster Teil ohne alte Nummer)
Änderung: Fund (1) des Branch-Reviews, Auftrag der Aufsicht 2026-09-25, Review mit Opus:
- Problem: `feature-build` setzt mit dem PR `status … pr --note "PR #<n>"`, aber `sync` liest nur die Spalte `PR` (`all_merged`), und nichts schrieb sie. Eine Zeile bliebe damit für immer `pr`.
- `roadmap.py status` bekommt `--pr P` und schreibt die Spalte `PR` wie T9 die Spalte `Ledger`, auch ohne Statuswechsel; der Commit-Betreff nennt das Flag.
- Tests: Die Spalte wird gesetzt, die Status-Zelle bleibt ohne Nummer, der Aufruf ohne Statuswechsel geht, und die Kette `status --pr` → `to_close` schließt die Zeile, sobald der PR gemergt ist.
- `feature-build` nutzt `pr --pr "#<n>"`, `DEVELOPMENT.md` zählt das Flag auf. Der Konsistenz-Test findet neben dem Ledger-Pfad auch eine PR-Nummer in `--note`; seine Fixture, die `pr --note "PR #<n>"` als harmlos führte, zieht nach.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: DEVELOPMENT.md
Abhängt von: T9

### T11 — Skill-Texte nach dem Branch-Review: Roadmap-ID im Kopf, Ledger vom Branch, Semantik-Frage in die Triage  [x]
Komponente: scripts · Dateien: .claude/skills/feature-plan/SKILL.md, .claude/skills/feature-build/SKILL.md, tasks/README.md, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @caf82265 2026-09-25T16:44:41+02:00
Review: approve (sonnet; nits: Umbruch nachgezogen)
Änderung: Funde (2), (5, Gate-Teil), (6), (7), (8) des Branch-Reviews und der falsche Satz in `tasks/README.md:43`, Auftrag der Aufsicht 2026-09-25:
- (2) Die Kopf-Vorlage des vollen Wegs schreibt `Spec: docs/features/<slug>.md (Roadmap R-nnnn)`. `feature-build` zieht jede ID mit, die der Kopf nennt, auch alle IDs eines Bündels. Bisher erkannte es nur `Spec: Roadmap R-nnnn`, und die Roadmap folgte einem normalen Plan nie.
- (5) Die Parallel-Prüfung am Gate liest ein Ledger, das nur auf seinem Branch liegt, per `git show <branch>:tasks/<slug>.md`. `next --exclude-components` sieht es noch nicht (R-0099).
- (6) cicd DE+EN nennt, was `skill_consistency_test.sh` wirklich prüft.
- (7) Die Commit-Vorlage ohne Spec gilt für `--kurz` und `--bundle`.
- (8) Zeigt `Semantik:` Absicht, behält die Zeile ihren Status, und die Frage geht per `status R-nnnn <status> --note "Semantik-Frage: …"` in Kevins Triage.
- `tasks/README.md:43`: `lane.sh` liest die alten Felder nicht, es nennt `Fast-Suite: vm` nur als Hinweis; die Frage dazu ist R-0097.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: docs/developer/cicd.html · docs/en/developer/cicd.html · tasks/README.md
Abhängt von: T10

### T12 — `Dedup-Key:`-Lint nimmt die Schlüssel der Roadmap an  [x]
Komponente: scripts · Dateien: scripts/dev/ledger.sh, scripts/tests/ledger_test.sh, tasks/README.md, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @7e54ad10 2026-09-25T16:54:58+02:00
Review: approve (sonnet)
Änderung: Funde (3) und (9) des Branch-Reviews, Auftrag der Aufsicht 2026-09-25:
- (3) Der Lint verlangte bei `Dedup-Key:` genau vier Teile. Die Roadmap trägt aber auch kurze Schlüssel aus `heavy.sh` (`reg:<schritt>`, `rel:deps-audit`), und `--kurz` übernimmt den Schlüssel aus der Zeile. Das erste `--kurz` auf einer REG-Zeile hätte `ledger_test` rot gemacht, weil es alle echten Ledger lintet. Ein Rust-Symbol `a::b` scheiterte ebenfalls. Künftig gilt: ein Token `<klasse>:<rest>` ohne Leerzeichen, `<klasse>` in Kleinbuchstaben.
- Tests: `reg:web-vitest` und ein Schlüssel mit `::` sind gültig (die bisherige Erwartung „Fehler“ dreht sich um), ohne Klasse, mit leerem Rest oder mit Leerzeichen ist es ein Fehler.
- Die Doku in `tasks/README.md` und cicd DE+EN nennt die volle und die kurze Form.
- (9) Der Heavy-Lint erkennt `· Fast-Suite:` in einer kombinierten Kopfzeile wie schon `· Warm-Profil:`; Tests für beide.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: tasks/README.md · docs/developer/cicd.html · docs/en/developer/cicd.html
Abhängt von: T2, T11

### T13 — `feature-build` findet den Plan auf seinem Branch (R-0065) und setzt einen unterbrochenen Abschluss fort  [x]
Komponente: scripts · Dateien: .claude/skills/feature-build/SKILL.md, AUTONOMOUS.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @23d272f8 2026-09-25T17:30:07+02:00
Review: approve (sonnet, Runde 2)
Änderung: Funde (A), (4, Skill-Teil), (7), (8, AUTONOMOUS-Teil) und (9, feature-build) des zweiten Branch-Reviews, Auftrag der Aufsicht 2026-09-25:
- (A) R-0065 legt den Plan auf `feature/<slug>`, aber `feature-build` las den Kopf aus dem Arbeitsbaum, bevor es den Branch wechselte. Aus `main` heraus fand es den Plan nicht. „Vor dem Start“ beginnt jetzt mit „Plan finden“: zuerst auf den Branch wechseln. Das Beispiel in `AUTONOMOUS.md` („So startest du konkret“) wechselt vor `/feature-build`.
- (4) Bei `bereit` wird keine Task gebaut. Ein unterbrochener Abschluss geht ab Schritt 2 weiter, ein fertiger wird gemeldet.
- (7) „Roadmap mitziehen“ erkennt auch die Kopfzeile `Roadmap: R-nnnn` der Regressions-Ledger aus `heavy.sh`. Schritt 6 verweist für den PR auf „Roadmap mitziehen“ (`--pr`, Teil-Ledger).
- (8) `AUTONOMOUS.md` „Parallel-Betrieb“: Eine Lane mit `Heavy:` kann „Schnellsuite auf der VM“ nicht sagen (R-0097).
- (9) Zwei überlange Zeilen im Abschluss sind umbrochen.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: AUTONOMOUS.md
Abhängt von: T12

### T14 — Semantik-Frage behält die Notiz; Texte und Konsistenz-Test nach dem zweiten Branch-Review  [x]
Komponente: scripts · Dateien: .claude/skills/feature-plan/SKILL.md, .claude/skills/roadmap/SKILL.md, tasks/README.md, docs/developer/cicd.html, docs/en/developer/cicd.html, scripts/tests/skill_consistency_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @c3cbff3b 2026-09-25T17:40:24+02:00
Review: approve (sonnet)
Änderung: Funde (B), (3), (4, README), (5), (6), (8, Ledger/Test) und (9, README) des zweiten Branch-Reviews, Auftrag der Aufsicht 2026-09-25:
- (B) Zeigt `Semantik:` Absicht, fragt der Planer Kevin sofort (Abschnitt 0). Die Zeile hält die Frage fest und behält die alte Notiz: `--note "<bisherige Notiz>; Semantik-Frage: …"`, weil `--note` ersetzt. Die Behauptung „geht in die Triage“ fällt weg, denn `/roadmap triage` sieht nur `neu`-Zeilen.
- (3) Im `/roadmap`-Skill fällt der veraltete Satz „den Kurz-Modus bringt Stufe 5b“ weg.
- (4) `tasks/README.md`: Bei `bereit` stehen der Abschluss von `feature-build` und der PR aus.
- (5) Der Konsistenz-Test prüft positiv, dass `feature-build` die PR-Nummer mit `--pr` setzt. Mutationsprobe: ohne `--pr` wird der Test rot.
- (6) Die Doku von `Dedup-Key:` in README und cicd DE+EN sagt, dass der Lint das erste Token prüft. Der Lint selbst bleibt.
- (8) Die bekannte Grenze von `plan_on_main` (ein Klammer-Einschub trennt Commit und „auf main“) steht im Kommentar des Tests.
- (9) Der `Heavy:`-Absatz in `tasks/README.md` ist umbrochen.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: tasks/README.md · docs/developer/cicd.html · docs/en/developer/cicd.html
Abhängt von: T13

### T15 — `bereit` mit vorhandenem PR holt Schritt 6 nach  [x]
Komponente: scripts · Dateien: .claude/skills/feature-build/SKILL.md, .claude/skills/feature-plan/SKILL.md, .claude/skills/roadmap/SKILL.md, scripts/tests/skill_consistency_test.sh, CHANGELOG.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @eb017349 2026-09-25T18:25:59+02:00
Review: approve (opus, Runde 2)
Änderung: Fund der dritten Runde des Branch-Reviews, im Diff von T13, also nach der Abbruchregel zu fixen:
- Die Regel „`bereit` und ein PR existiert ⇒ Abschluss fertig, melden“ übersah Schritt 6. Der setzt mit dem PR den Kopf auf `erledigt` und zieht die Roadmap mit `pr --pr` nach.
- Öffnet Kevin den PR selbst, bliebe das Ledger sonst `bereit`, und `sync` schlösse die Zeile nie.
- Jetzt gilt: Ist ein PR da, wird Schritt 6 nachgeholt (Kopf `erledigt`, Roadmap `pr --pr`) und dann gemeldet.
- Ausnahme von der Abbruchregel, Auftrag der Aufsicht 2026-09-25, weil der Schaden nicht umkehrbar wäre: `--kurz` verweigert SEC mit Grund. SEC-Funde bleiben unter `tasks/private/` (Roadmap-Dokument 3.3.3), und das Gate committet ins öffentliche Repo; bis es einen privaten Kurz-Weg gibt, plant Kevin SEC von Hand.
  - Der `--bundle`-Grund und die Annehmen-Option im `/roadmap`-Skill ziehen mit.
  - Der Konsistenz-Test hält die Sperre fest.
- Der CHANGELOG-Eintrag „Harness Stufe 5b“ unter `[Unreleased]` fehlte; das ist eine Lücke in der DoD.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: CHANGELOG.md (der Skill ist sonst die Doku)
Abhängt von: T13

## Abschluss (nach T6, vor dem PR)

`/feature-plan --kurz` auf einer echten `neu`-Zeile, einem Kandidaten der Aufsicht: das Ergebnis ist ein
2-Task-Ledger mit `Beweis:` und `Semantik:`. Das Ledger wird verworfen oder behalten, wie Kevin will. Dazu ein
Plan-Lauf auf einer Zeile, deren Komponente mit einer `aktiv`-Zeile kollidiert: Er muss warnen.

**Ergebnis der Probe (2026-09-25, Kandidat der Aufsicht: R-0095, BUG, `vm.py sync` aus einem Worktree)**
- Erster Lauf: Die Zeile trägt einen Beweis. Nachgestellt ohne VM auf main@b4802aa1: `rsync -a --exclude-from
  scripts/vm/rsync-exclude.txt <worktree>/ <tmp>/`, dieselben Argumente wie `vm.py:_sync`, legt am Ziel `.git` als
  Datei `gitdir: <Haupt-Checkout>/.git/worktrees/<name>` ab. Die `Semantik:`-Prüfung fand aber `DEVELOPMENT.md:1165–1166`
  („Der Sync aus Worktrees ist validiert; `.git` reist mit, die Evidenzfelder kommen trotzdem vom Client.“) und das
  Nicht-Ziel der Spec wochenlauf-gruen („die Box braucht es nicht“). Beides beschreibt das heutige Verhalten als Absicht,
  also kein Fix-Task, sondern eine offene Frage an Kevin. Daraus wurde T8.
- Kevins Antwort: kein Box-Repo. Zweiter Lauf: `tasks/box-ohne-repo.md` auf dem lokalen Branch `feature/box-ohne-repo`
  (6754daba von main, nicht gepusht, Commit `chore(plan): add ledger for box-ohne-repo`). 2 Tasks, beide mit `Beweis:`,
  `Semantik:`, `Dedup-Key:` und `HEAD:`, `ledger.sh lint` ok. Ob das Ledger bleibt, entscheidet Kevin.
- Die Warnung am Gate, wörtlich: „parallel-tauglich zu R-0093 (Ledger wochenlauf-gruen, dazu R-0085/86/87/92 derselben
  Lane): nein — gleiche Komponente `scripts`, geteilte Dateien `scripts/vm/rsync-exclude.txt` und
  `scripts/vm/tests/test_vm.py` (wochenlauf-gruen T2), dieselbe Ursache (T1/T7 umgehen den Worktree-`.git`). Seriell nach
  dem Merge von wochenlauf-gruen, nicht parallel.“
- Abweichung: Der Roadmap-Schritt des Gates lief mit `--file` auf einer Kopie der echten Datei, die echte
  `tasks/private/ROADMAP.md` wurde nur gelesen. Eine Kopie ohne `cp -p` wies die 5-s-Regel aus 5a mit Exit 5 ab.
- Funde: (1) Was bei `Semantik:` = Absicht geschieht, und (2) die Commit-Vorlage ohne Spec wurden T8. (4) Der Ledger-Pfad
  landete in der Status-Zelle statt in der Spalte `Ledger`; daraus wurde T9. (3) Die Altzeilen R-0085/86/87/89/92 ohne
  Ledger-Spalte zieht die Aufsicht nach dem Merge mit `status … --ledger` nach.
- Bekannte Grenze, in 5b nicht geändert: Eine Sammelzeile wie R-0008 (5a bis 5c) würde der Abschluss von
  `feature-build` auf `bereit` setzen, obwohl 5c offen ist. Sie blieb deshalb unverändert.

**Branch-Review, Runde 1 (2026-09-25, frischer Opus-Agent über `git diff main...`):** request_changes, 5 wichtig und 5 nit.
Gebaut wurden (1) als T10 (PR-Nummer in der Spalte `PR`), (2) und der Gate-Teil von (5) mit den nits (6), (7) und (8)
als T11, (3) mit nit (9) als T12. Nicht in 5b: (4) `Heavy:` gegen `Fast-Suite: vm` bleibt bei R-0097; der Rest von
(5), also `components_of` liest den Arbeitsbaum, ist R-0099; (10), der Kommentar in `heavy.sh:627`, ist R-0100.

**Branch-Review, Runde 2 (2026-09-25, neuer frischer Opus-Agent):** Die Funde aus Runde 1 sind behoben. Neu:
request_changes mit 2 wichtig und 7 nit. (A), der Plan auf seinem Branch, den `feature-build` nicht fand, wurde T13 mit
den nits (4), (7), (8) und (9). (B), die Semantik-Frage, die eine Notiz ersetzt und die Triage nicht erreicht, wurde T14
mit den nits (3), (4), (5), (6), (8) und (9). Ab Runde 3 gilt die Abbruchregel der Aufsicht: gefixt werden nur `blocker`
und `wichtig` im Diff von T13/T14 oder solche, die den nächsten Lauf sofort brechen; andere `wichtig` werden
Roadmap-Zeilen, nits stehen im PR-Text.
