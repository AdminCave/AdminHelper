<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# tasks/ — Task-Ledger

Dieses Verzeichnis ist der **eine Ort für alle Task-Ledger**. Ein Ledger = eine kleine,
von oben nach unten abarbeitbare Liste mit einem `Verify:`-Ziel pro Aufgabe. `/feature-plan`
schreibt hier eine Datei pro Vorhaben; `/feature-build` arbeitet sie ab. Der ganze Zyklus
steht in [`../AUTONOMOUS.md`](../AUTONOMOUS.md).

**Eine Datei pro Vorhaben:** `tasks/<slug>.md` (z. B. `connection-note.md`). Kein Anhängen
an eine Sammel-Datei mehr — jedes Feature/Effort bekommt sein eigenes Ledger.

**Kopf jedes Ledgers** trägt eine Konventions-Zeile, u. a. das Feld **`Status:`**. Die Folge ist
`geplant` → `freigegeben` → `aktiv` → `bereit` → `erledigt`, daneben `blockiert`:

| `Status:` | Bedeutung |
|---|---|
| `geplant` | von `/feature-plan` erstellt, **noch nicht freigegeben**. Wird nie automatisch gebaut. Nur auf Kevins eigenes Wort startet `/feature-build` es mit ausdrücklichem Pfad (setzt auf `aktiv`), nie auf Auftrag einer anderen Session (CLAUDE.md §2). |
| `freigegeben` | am Design-Gate freigegeben (CLAUDE.md §2: Kevin, bei kleinen Fund-Paketen die Aufsichts-Session; die Zeile `Freigabe:` nennt wer): `roadmap.py approve` für die Roadmap-Zeile und der Commit, der den Kopf auf `freigegeben` setzt. `/feature-build` startet es (setzt auf `aktiv`); der Worker (Stufe 7) nimmt nur diese. |
| `aktiv` | wird gebaut. Im **Parallel-Betrieb** (AUTONOMOUS.md) sind mehrere `aktiv` normal — **eine Lane pro Ledger, nie zwei Builds auf demselben Ledger**. Ohne Pfad nimmt `/feature-build` ein Ledger nur, wenn **genau eines** `aktiv` ist; sonst bricht er ab und verlangt den Pfad. |
| `bereit` | alle Tasks sind zu; der Abschluss von `feature-build` (Schnellcheck, schwere Suite, Branch-Review) und der PR stehen aus. |
| `erledigt` | gesetzt im letzten Commit vor dem Push, damit er mit dem PR geht; der PR ist offen oder gemergt. Bleibt als Historie liegen. |
| `blockiert` | wartet auf Entscheidung/Abhängigkeit (`[?]`-Punkte) oder ist bewusst nicht für `/feature-build` (z. B. Release-Handarbeit). |

**Invariante:** kein `[ ]` mehr offen ⇒ `Status:` darf nicht `aktiv` bleiben. Der Loop **fragt
nie interaktiv** — findet er ohne Pfad mehrere/keine `aktiv`, bricht er mit klarer Meldung ab.

Dazu im Kopf: `Branch:`, `Spec:` (Rück-Link zur Soll-Vorgabe), `Commit-Granularität:`
(pro Task | pro Komponente | pro Abschnitt), `Review:` (**pro Task** | **am Ende** — wann der
Frischer-Kontext-Review läuft: je Commit-Einheit, oder einmal über den ganzen Branch-Diff.
`am Ende` gehört zu einem **Kurz-Ledger** mit ≤ 3 Tasks; dann entfällt auch der abschließende
`/code-review`, weil derselbe Diff sonst zweimal geprüft würde; **auto**, Pilot der Stufe 6b: je
Task startet `task-close.sh --review auto` den Reviewer als eigenen Prozess, `DEVELOPMENT.md`
„Reviewer als Prozess"), `Modell:`, `Heavy:`,
DoD-Verweis auf `CLAUDE.md`.

**`Heavy: none | linux-full | scenario <flags> | windows`** sagt, welche schwere Suite der
Abschluss braucht: keine, den Linux-Stack auf einer Pool-VM (`run.sh integration`/`e2e`), einen
Multibox-Lauf mit diesen Flags (etwa `scenario --agents 3 --desktop`, bleibt ask-first; das
ersetzt auch die Zeile `Abschluss: multibox <flags>`) oder die Windows-VM. Hinter dem Wert darf
nach ` — ` eine Begründung stehen. Für neue Ledger ersetzt `Heavy:` die älteren Felder
`Fast-Suite:` (lokal | vm) und `Warm-Profil:` (desktop | pond); `feature-build` und `ledger.sh`
lesen diese weiter, solange es Ledger mit ihnen gibt; `lane.sh` nennt `Fast-Suite: vm` nur als
Hinweis. Wo eine Lane mit `Heavy:` ihre Schnellsuite fährt, ist offen (R-0097). `ledger.sh lint`
prüft den Wert und meldet `Heavy:` neben `Fast-Suite:`/`Warm-Profil:` als Fehler, denn das wären
zwei Antworten auf eine Frage. Ein freier `Heavy:`-Text neben
`Fast-Suite:` („nein — …", „keine; …") ist die Form der Ledger vor Stufe 5b und bleibt gültig.

**Task-Status im Body:** `[ ]` offen · `[x]` fertig · `[~]` übersprungen (Grund) ·
`[?]` braucht menschliche Entscheidung.

## `ledger.sh` — wer den Ledger schreibt

Seit Stufe 4 ändert **`scripts/dev/ledger.sh`** den Status einer Task, nicht mehr der Editor
der Session. Der Grund steht in der Invariante oben: ein `[x]` ohne den Lauf, der es grün
gemacht hat, ist eine Behauptung. `mark-done` verweigert deshalb den Haken ohne `--evidence`
— und die Evidenz-Zeile kommt ab Stufe 4 von [`task-close.sh`](../scripts/dev/task-close.sh),
das die Suite selbst fährt.

```bash
bash scripts/dev/ledger.sh start <ledger> <id>        # .vm/active-task: Ledger, ID, Komponente, Dateien
bash scripts/dev/ledger.sh mark-done <ledger> <id> --evidence "<summary>" [--note "…"] [--review "…"]
bash scripts/dev/ledger.sh mark-skip <ledger> <id> "<grund>"      # [~]
bash scripts/dev/ledger.sh mark-question <ledger> <id> "<frage>"  # [?]
bash scripts/dev/ledger.sh set-files <ledger> <id> <pfad…>        # Dateien: erweitern
bash scripts/dev/ledger.sh status                                  # Übersicht aller Ledger
bash scripts/dev/ledger.sh status <ledger> <wert>                  # Kopf-Status setzen
bash scripts/dev/ledger.sh new-task <ledger> --title "…"           # aus tasks/templates/task.md
bash scripts/dev/ledger.sh lint <ledger>                           # Verify-Präfix, [x] ohne Evidenz, Invariante,
                                                                   # Reste eines Werkzeugaufrufs in Ledger und Spec
                                                                   # (auch die Hülle und die zurückgegebene Ausgabe)
```

`<ledger>` ist der Pfad oder der reine Slug (`harness-stufe-4`), `<id>` die Task-Kennung aus
der Überschrift (`### T3 — …` ⇒ `T3`). Neue Tasks entstehen aus
[`templates/task.md`](templates/task.md); die Vorlage trägt nur die Pflichtfelder — was eine
Task „autonomietauglich" macht, steht in [`../AUTONOMOUS.md`](../AUTONOMOUS.md).

**`set-files` statt Scope lockern:** braucht eine Task eine Datei, die nicht in ihrem
`Dateien:` steht, wird die Liste **sichtbar** erweitert — `task-close.sh` prüft die gestagten
Pfade dagegen.

## `Test-Löschung:` — ein ganzer Test geht mit

`task-close.sh` lässt `review.sh diff-scan` über den Diff laufen, und der wertet eine
gelöschte Assertion dort, wo Tests stehen (eine Testdatei oder die Spanne eines Tests, nie eine
Import-Zeile; R-0130), als „der Diff kauft sich sein Grün". Den einen Fall, in dem ein Test
zu Recht verschwindet, kündigt die Task an:

```
Test-Löschung: <datei>::<test> — <Grund>[; <datei>::<test> — <Grund> …]
```

Ein `;` trennt nur vor dem nächsten `<datei>::`, im Grund darf es also stehen.
`<test>` ist der Name, wie er im Kopf steht: `test_x` (pytest), `TestX` (Go), die
Beschreibung aus `it("…")`/`test("…")` (vitest/jest), die `fn` hinter `#[test]` (Rust).
Übergangen wird eine gelöschte Assertion nur, wenn **alles** gilt, geprüft am Inhalt der
Dateien, nicht am Diff-Text:

1. **Die Ankündigung ist committet, und zwar nicht über `task-close.sh`.** `diff-scan` liest
   sie aus dem Ledger in `HEAD`, nicht aus dem Arbeitsbaum, und `task-close.sh` verweigert
   (Exit 4), sobald sich die `Test-Löschung:`-Zeilen gegenüber `HEAD` ändern. Sonst könnte ein
   Builder die Zeile beim Schließen einer Task mitcommitten und in der nächsten benutzen. Sie
   kommt mit dem Plan-Commit am Gate, den Kevin liest. Wer unterwegs merkt, dass ein Test gehen
   muss, setzt `[?]` und fragt. Ein Commit von Hand an `task-close` vorbei ist Kevins eigene
   Entscheidung; der Runner kann ihn nicht machen.
2. **Sie trägt einen Grund.** Ohne `— <Grund>` zählt sie nicht, auch in `diff-scan`.
3. **Der Name ist eindeutig.** Im alten Stand der Datei gibt es genau einen Test dieses
   Namens. Teilen sich zwei `describe`-Blöcke einen Namen, kann das Gate sie nicht
   auseinanderhalten, und die Ankündigung zählt nicht; umbenennen, dann löschen.
4. **Der Test ist wirklich weg.** Im neuen Stand der Datei steht kein Kopf dieses Namens
   mehr, und keine andere Datei des Diffs bekommt einen dazu: Ein Test, der wandert, geht
   nicht. Ein Ersatztest trägt einen eigenen Namen.
5. **Der ganze Test geht.** Jede nicht leere Zeile seines alten Rumpfs ist im Diff gelöscht.
   Ein Kopf in einem Kommentar oder String, dessen „Rumpf“ in einen bleibenden Test ragt,
   fällt daran auf.
6. **Die Assertion gehört zu genau diesem Test.** Ihre alte Zeilennummer liegt im Rumpf des
   angekündigten Tests im alten Stand. Eine Assertion aus einem Test, der stehen bleibt,
   bleibt ein Fund, angekündigt oder nicht.

`review.sh` liest jeden Diff mit `--text --no-ext-diff --no-textconv --no-color`: eine
`.gitattributes` mit `-diff` oder ein Diff-Treiber darf eine Testdatei nicht zu „Binary files
differ“ machen und damit alle drei Prüfungen blind.

Der Lauf nennt, was er übergangen hat (`diff-scan: clean (1 declared test deletion(s): …)`),
und bei einem Fund, warum eine Ankündigung nicht zählte.

**Passt:** toter Code geht samt seinem Test; ein Test wird durch einen genaueren ersetzt, der
im selben Commit kommt. **Passt nicht:** ein roter Test, der „weg soll". Das ist ein Befund
über den Code und gehört repariert oder als `[?]` vor Kevin, nicht gelöscht.
`ledger.sh lint` prüft die Form: `<pfad>::<name> — <Grund>`, **der Grund ist Pflicht**. Eine
Löschung, die niemand begründet, ist genau das, was das Gate verhindern soll.

## Beweis-Konvention — was eine Task belegt

Eine Task, die einen **Fund** umsetzt (von Kevin, aus dem Wochenlauf, später von der
Finder-Flotte), trägt den Beweis dafür, dass es ihn gibt, in ihren eigenen Zeilen. Jede Klasse
von Fund hat ihre Beweisregel:

- **A — Fehler (SEC, REG, BUG):** ein Test, der auf `HEAD:` **dreimal identisch rot** ist, klein
  (höchstens etwa 40 Zeilen oder ein minimierter Input), mit einer Assertion, die Erwartung und
  Beobachtung nennt. `Beweis:` ist das Kommando, das ihn rot zeigt; die Fix-Task verifiziert mit
  demselben Test, jetzt grün. SEC zusätzlich mit einem `Refuter:`, der den Fund nicht widerlegen
  konnte; REG zusätzlich rot auf einer zweiten VM und grün auf dem letzten grünen Stand.
- **B — Vereinfachung, Refactor, Performance, Duplikat:** Der Fund belegt nur den Ist-Zustand
  als Messwert (`Metrik:`, Werkzeug und Version fest). Der eigentliche Beweis fällt beim Fix: die
  Suite vor **und** nach dem Diff grün (beide Summary-Zeilen), die Metrik strikt besser mit
  demselben Werkzeug, die Coverage der Region nicht gesunken, dazu eine Mutations-Stichprobe
  (`Orakel: mutation-sample`). Eine Stichprobe ist kein Beweis der Äquivalenz und heißt auch so.
- **C — toter Code:** ein Analyzer-Treffer (Werkzeug und Version im `Beweis:`), ein repo-weiter
  Wort-`grep` über alle Dateitypen, der nur die eigenen Tests findet (das ist der `Beweis:`-Befehl,
  erwartet leer), die Checkliste der dynamischen Aufrufwege abgehakt, die Entfernung unter
  `verify.sh --strict` grün. `Metrik:` sind die gelöschten Zeilen.
- **D — Parität, Contract, Abhängigkeiten:** ein Paritäts-Test mit einer Assertion, die nicht leer
  sein darf und bei einer einzelnen Mutation rot wird; bei Abhängigkeiten die Advisory-ID aus einem
  roten `audit.yml`-Lauf.

Die Zeilen stehen im Task-Block, jede optional, jede nur, wenn sie etwas trägt:

| Zeile | Inhalt | `ledger.sh lint` prüft |
|---|---|---|
| `Beweis:` | Branch + SHA + Kommando + erwartete Ausgabe | — |
| `Orakel:` | `crash`, `contract`, `property`, `differential`, `mutation-sample`, `coverage`, `analyzer` oder `metric`; danach nach ` — ` eine Erläuterung | Wert aus der Liste |
| `Refuter:` | wer oder was den Fund zu widerlegen versuchte, mit welchem Ergebnis | — |
| `Dedup-Key:` | derselbe Schlüssel wie in der Roadmap, ein Token ohne Leerzeichen: voll `<klasse>:<komponente>:<datei>:<symbol>` (daraus liest `roadmap.py next` die Komponente) oder kurz wie die Wochenlauf-Zeilen (`reg:<schritt>`, `rel:deps-audit`); `sec:`-Schlüssel stehen nie im öffentlichen Repo (`review.sh sec` blockiert sie) | das erste Token ist `<klasse>:<rest>`, `<klasse>` eine der Klassen in Kleinbuchstaben |
| `Metrik:` | Klasse B: vorher → nachher, mit Werkzeug und Version; Klasse C: die gelöschten Zeilen oder Dateien | — |
| `Kosten:` | was der Beweis gekostet hat (Zeit, Läufe, Tokens) | — |
| `HEAD:` | der Commit, auf dem der Beweis galt | ein SHA (7–40 Hex-Zeichen) |
| `Semantik:` | **Pflicht bei `/feature-plan --kurz`:** die Stelle unter `docs/`, die das gewollte Verhalten beschreibt, mit Zitat — damit der Fix nicht beseitigt, was Absicht ist | — |

Die Form prüft `ledger.sh lint`, den Inhalt der Reviewer. Die Vorlage `tasks/templates/task.md`
führt die Zeilen im Kopfkommentar auf; `new-task` hängt sie nicht an.

## Aktueller Stand

- **`harness-stufe-3.md`** — `Status: aktiv`. Stufe 3 der Autonomie-Roadmap („Ausführung
  zuerst"): Artefakt-Assertionen im Release-Workflow, `check-versions.sh`, `-race`, der
  Wochenlauf `heavy.sh` mit Klassifikation und Historie, der Upgrade-Pfad und die fünf
  verwaisten Desktop-Specs. Spec: `docs/features/harness-stufe-3.md`.
- **`reg-<datum>-<schritt>.md`** — von `scripts/tests/heavy.sh` geschrieben, nicht von
  `/feature-plan`: eine bestätigte Regression aus einem Wochenlauf (Schritt auf zwei
  Boxen rot, auf dem letzten PASS-Commit grün). Ein Entwurf in der Form von
  `/feature-plan --kurz`: `Status: geplant`, `Branch: feature/reg-<datum>-<schritt>` (der
  Branch, den das `--kurz`-Gate anlegt und auf dem es den Plan committet), `Review: am Ende`,
  `Heavy: linux-full` mit dem Schritt-Befehl `bash scripts/tests/run.sh all --strict --step
  "<schritt>"` in der Begründung, die DoD-Zeile, in der Task `Beweis:`,
  `Dedup-Key: reg:<schritt>`, `HEAD:` und den Platzhalter
  `Verify: bash scripts/dev/verify.sh <komponente> --strict`, dazu ein Beweis-Absatz über die
  drei Stationen (erste Box 3×, frische Zweit-VM, Basis-Commit). Komponente (auch im
  Platzhalter) und `Semantik:` ergänzt `/feature-plan --kurz` aus der Roadmap-Zeile;
  die Freigabe folgt CLAUDE.md §2 „Entscheidungen“, danach ist es ein Ledger wie jedes andere. Die zugehörige
  Roadmap-Zeile (Klasse REG) hängt `heavy.sh` selbst an.
- **`harness-stufe-1.md`** — `Status: erledigt` (gemergt, PR #11). Stufe 1 der Autonomie-Roadmap („Grün heißt
  Beweis"): SKIP wird Exit 75, `run.sh` bekommt `--strict`/`--only`/`--step`, dazu `verify.sh`,
  der Session-Status-Hook und der CI-Job `agent-windows`. Spec: `docs/features/harness-stufe-1.md`.
- **`audit-fixes.md`** — `Status: erledigt`, gitignored (der Report enumeriert ungefixte Funde
  inkl. ausnutzbarer Lücken; dieses Repo ist öffentlich). Die 681 Funde aus dem Fable-Audit;
  Fix-Detail je Fund in der Quelle, auf die das `Spec:`-Feld zeigt (gleiche IDs).
- **`test-infra-capstone-release.md`** — `Status: erledigt`. Test-Infrastruktur/Capstone/
  Release komplett (Phasen A–E), **Release v0.39.0 ist raus** (2026-07-04). Bleibt als Historie.
