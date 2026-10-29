<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# tasks/ — Task-Ledger

Dieses Verzeichnis ist der **eine Ort für alle Task-Ledger**. Ein Ledger = eine von oben nach
unten abarbeitbare Liste mit einem `Verify:`-Ziel pro Aufgabe. `/feature-plan` schreibt hier eine
Datei pro Vorhaben und schneidet die Tasks (`.claude/skills/feature-plan/SKILL.md` §3);
`/feature-build` arbeitet sie ab. Der Ablauf steht in [`../CLAUDE.md`](../CLAUDE.md) §4–§8. Dieses
Dokument ist die Referenz für das **Format**.

**Eine Datei pro Vorhaben:** `tasks/<slug>.md` (z. B. `connection-note.md`). Kein Anhängen
an eine Sammel-Datei mehr — jedes Feature/Effort bekommt sein eigenes Ledger.

**Kopf jedes Ledgers** trägt eine Konventions-Zeile, u. a. das Feld **`Status:`**. Die Folge ist
`geplant` → `aktiv` → `bereit` → `erledigt`, daneben `freigegeben` (ältere Ledger) und `blockiert`:

| `Status:` | Bedeutung |
|---|---|
| `geplant` | von `/feature-plan` erstellt. Die Freigabe ist `roadmap.py approve` für die Roadmap-Zeile, die die Session gleich nach dem Plan-Commit selbst setzt; erst dann setzt `/feature-build` den Kopf im Worktree auf `aktiv` (CLAUDE.md §4). |
| `freigegeben` | Form älterer Ledger, deren Kopf die Freigabe trug; `/feature-build` behandelt sie wie `geplant` mit freigegebener Roadmap-Zeile. |
| `aktiv` | wird gebaut, in einem eigenen Worktree — **je Ledger und Worktree baut ein Akteur**. |
| `bereit` | alle Tasks sind zu (auch die Doku-Task); Abschlussprüfung (`reviewer`, Einsatzart `branch`) und PR stehen aus. |
| `erledigt` | gesetzt im letzten Commit vor dem Push, damit er mit dem PR geht; der PR ist offen oder gemergt. |
| `blockiert` | wartet auf Entscheidung/Abhängigkeit (`[?]`-Punkte) oder ist bewusst nicht für `/feature-build` (z. B. Release-Handarbeit). |

**Invariante:** kein `[ ]` mehr offen ⇒ `Status:` darf nicht `aktiv` bleiben.

Dazu im Kopf: `Branch:`, `Spec:` (Rück-Link zur Soll-Vorgabe, mit der Roadmap-ID), `Review:`
(**pro Task** | **am Ende** — wann der Reviewer läuft: vor jedem Task-Commit, oder einmal über den
ganzen Branch-Diff; `am Ende` gehört zu einem **Kurz-Ledger** mit ≤ 3 Tasks) und `Heavy:`.

**`Heavy: none | linux-full | scenario <flags> | windows`** sagt, welche schwere Suite das
Vorhaben braucht (`linux-full` im Sammellauf über `main`, `scenario` und `windows` vor dem Merge;
`/feature-build` §3–§5): keine, den
Linux-Stack auf einer Pool-VM (`run.sh integration`/`e2e`), einen
Multibox-Lauf mit diesen Flags (etwa `scenario --agents 3 --desktop`, bleibt ask-first) oder die
Windows-VM. Hinter dem Wert darf nach ` — ` eine Begründung stehen.

**Task-Felder:** `Komponente:` (der Name aus `verify.sh`, etwa `server`, kein Pfad), `Dateien:` (die
Pfade, die `task-close.sh --stage` stagt, durch Komma getrennt), `Verify:` (Flag-Form ohne Env-Präfix:
`bash scripts/dev/verify.sh <komp> --strict [-- <test>]`), `Doku:`, bei Bedarf `Test-Löschung:` (unten) und
`Task-Review: am Ende` (eine reine Doku-Task: `task-close.sh` verlangt dann kein Task-Urteil, solange sie nur
Markdown oder HTML unter `docs/` stagt, keinen Symlink und keinen Harness-Text — `CLAUDE.md`, `.claude/` in jeder
Tiefe, `tasks/`; der Inhalt geht in die Abschlussprüfung).

**Züge:** Ein Ledger `tasks/<zug>.md` nimmt alle Roadmap-Zeilen auf, deren Spalte `Ledger` ihn nennt
(`roadmap.py zuege`, CLAUDE.md §2); `klein-<…>` baut die Klein-Session, jedes andere die Kern-Session. Eine Zeile,
die nicht mitfahren kann, wird `[~] verschoben in <nächster-zug>: <Grund>` und wechselt dort hin
(`/feature-build` §3).

**`Doku:`** hat drei Formen: die Dateien, die diese Task selbst nachzieht (`docs/… DE+EN`, `README`,
`changelog.d/<slug>.md`); `→ T<n>`, wenn die Doku-Task `T<n>` desselben Ledgers sie gebündelt nachzieht (offen, bis
`T<n>` `[x]` ist; `ledger.sh lint` prüft, dass es `T<n>` gibt); oder `keine (<Grund>)` für Änderungen
ohne dokumentierten Einfluss. Wann Doku fällig ist, regelt `.claude/rules/docs.md`.

**Task-Status im Body:** `[ ]` offen · `[x]` fertig · `[~]` übersprungen (Grund) ·
`[?]` braucht menschliche Entscheidung.

## `ledger.sh` — wer den Ledger schreibt

**`scripts/dev/ledger.sh`** ändert den Status einer Task, nicht der Editor der Session. Ein `[x]`
ohne den Lauf, der es grün gemacht hat, ist eine Behauptung: `mark-done` verweigert den Haken ohne
`--evidence`, und die Evidenz-Zeile kommt von [`task-close.sh`](../scripts/dev/task-close.sh), das
die Suite selbst fährt.

```bash
bash scripts/dev/ledger.sh start <ledger> <id>        # .vm/active-task: Ledger, ID, Komponente, Dateien
bash scripts/dev/ledger.sh mark-done <ledger> <id> --evidence "<summary>" [--note "…"] [--review "…"]
bash scripts/dev/ledger.sh mark-skip <ledger> <id> "<grund>"      # [~]
bash scripts/dev/ledger.sh mark-question <ledger> <id> "<frage>"  # [?]
bash scripts/dev/ledger.sh set-files <ledger> <id> <pfad…>        # Dateien: erweitern
bash scripts/dev/ledger.sh status                                  # Übersicht aller Ledger
bash scripts/dev/ledger.sh status <ledger> <wert>                  # Kopf-Status setzen
bash scripts/dev/ledger.sh lint <ledger>                           # Verify-Präfix, [x] ohne Evidenz, Invariante,
                                                                   # Reste eines Werkzeugaufrufs in Ledger und Spec
```

`<ledger>` ist der Pfad oder der reine Slug, `<id>` die Task-Kennung aus der Überschrift
(`### T3 — …` ⇒ `T3`). Neue Tasks entstehen aus [`templates/task.md`](templates/task.md); die
Vorlage trägt nur die Pflichtfelder.

## `## Entscheidungen` — was die Session unterwegs festlegt

Am Ende des Ledgers sammelt ein Abschnitt `## Entscheidungen` die Implementierungsentscheidungen der
bauenden Session, eine Zeile je Entscheidung: `- <JJJJ-MM-TT> T<n>: <Entscheidung> — <Grund>`. Er ist
mit dem Ledger committet und damit nach einer Unterbrechung, einem `compact` oder in einer neuen Session
lesbar. Was Kevins Bereich ist (CLAUDE.md §2), steht nicht hier, sondern als `[?]` an der Task.

**`set-files` statt stiller Zusatzdateien:** braucht eine Task eine Datei, die nicht in ihrem
`Dateien:` steht, wird die Liste **sichtbar** erweitert — `task-close.sh --stage` stagt genau
diese Liste.

## `Test-Löschung:` — ein Test oder eine Testdatei geht

Löscht eine Task einen ganzen Test oder eine ganze Testdatei, kündigt sie das an:

```
Test-Löschung: <datei>::<test> — <Grund>[; <datei>::<test> — <Grund> …]
Test-Löschung: <datei>::* — <Grund>                  (die ganze Datei)
```

Ein `;` trennt nur vor dem nächsten `<datei>::`, im Grund darf es also stehen. `<test>` ist der
Name, wie er im Kopf steht: `test_x` (pytest), `TestX` (Go), die Beschreibung aus
`it("…")`/`test("…")` (vitest/jest), die `fn` hinter `#[test]` (Rust).

1. **Die Ankündigung ist committet, und zwar nicht über `task-close.sh`.** Sie kommt mit dem
   Plan-Commit, und der Bericht am Gate nennt sie Kevin. `task-close.sh` nimmt einen Commit zurück (Exit 4), der eine
   `Test-Löschung:`-Zeile ändert. Wer unterwegs merkt, dass ein Test gehen muss, setzt `[?]` und
   fragt.
2. **Sie trägt einen Grund.** `ledger.sh lint` prüft die Form `<pfad>::<name> — <Grund>`; ohne Grund
   ist die Zeile ein Fehler, ebenso eine zweite Zeile in derselben Task.
3. **Eine gelöschte oder weg-umbenannte Testdatei** (unter `tests/` oder `test/`, oder `*_test.*`,
   `test_*`, `*.test.*`, `*.spec.*`, `*.e2e.*`, `*.live.*`) ohne passende Zeile dieser Task lässt
   `task-close.sh` nicht durch (Exit 3).

Ob ein Test schwächer geworden ist (`|| true`, `skip`, eine gestrichene oder triviale Assertion),
prüft der `reviewer` (Kriterium „Tests“ in `.claude/agents/reviewer.md`), kein Skript.

**Passt:** toter Code geht samt seinem Test; ein Test wird durch einen genaueren ersetzt, der
im selben Commit kommt. **Passt nicht:** ein roter Test, der „weg soll". Das ist ein Befund
über den Code und gehört repariert oder als `[?]` vor Kevin, nicht gelöscht.

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
führt die Zeilen im Kopfkommentar auf.

## Aktueller Stand

Neben den Ledgern aus `/feature-plan` entsteht eine Art von Ledger durch ein Skript:

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
  die Freigabe folgt CLAUDE.md §4, danach ist es ein Ledger wie jedes andere. Die zugehörige
  Roadmap-Zeile (Klasse REG) hängt `heavy.sh` selbst an.
