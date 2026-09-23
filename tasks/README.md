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

**Kopf jedes Ledgers** trägt eine Konventions-Zeile, u. a. das Feld **`Status:`**:

| `Status:` | Bedeutung |
|---|---|
| `geplant` | von `/feature-plan` erstellt, **noch nicht freigegeben**. Wird nie automatisch gebaut. Das Starten von `/feature-build` ist die Freigabe (setzt auf `aktiv`). |
| `aktiv` | freigegeben, wird bearbeitet. Im **Parallel-Betrieb** (AUTONOMOUS.md) sind mehrere `aktiv` normal — **eine Lane pro Ledger, nie zwei Builds auf demselben Ledger**. Ohne Pfad nimmt `/feature-build` ein Ledger nur, wenn **genau eines** `aktiv` ist; sonst bricht er ab und verlangt den Pfad. |
| `erledigt` | fertig + PR offen/gemergt; bleibt als Historie liegen. |
| `blockiert` | wartet auf Entscheidung/Abhängigkeit (`[?]`-Punkte) oder ist bewusst nicht für `/feature-build` (z. B. Release-Handarbeit). |

**Invariante:** kein `[ ]` mehr offen ⇒ `Status:` darf nicht `aktiv` bleiben. Der Loop **fragt
nie interaktiv** — findet er ohne Pfad mehrere/keine `aktiv`, bricht er mit klarer Meldung ab.

Dazu im Kopf: `Branch:`, `Spec:` (Rück-Link zur Soll-Vorgabe), `Commit-Granularität:`
(pro Task | pro Komponente | pro Abschnitt), `Review:` (**pro Task** | **am Ende** — wann der
Frischer-Kontext-Review läuft: je Commit-Einheit, oder einmal über den ganzen Branch-Diff.
`am Ende` gehört zu einem **Kurz-Ledger** mit ≤ 3 Tasks; dann entfällt auch der abschließende
`/code-review`, weil derselbe Diff sonst zweimal geprüft würde), `Modell:`, `Fast-Suite:`
(lokal | vm — wo Verify + Schnellsuite laufen; `vm` in Worktree-Lanes),
`Warm-Profil:` (desktop | pond — Box-Bedarf; optional `Abschluss: multibox <flags>`,
bleibt ask-first), DoD-Verweis auf `CLAUDE.md`.

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
bash scripts/dev/ledger.sh lint <ledger>                           # Verify-Präfix, [x] ohne Evidenz, Invariante
```

`<ledger>` ist der Pfad oder der reine Slug (`harness-stufe-4`), `<id>` die Task-Kennung aus
der Überschrift (`### T3 — …` ⇒ `T3`). Neue Tasks entstehen aus
[`templates/task.md`](templates/task.md); die Vorlage trägt nur die Pflichtfelder — was eine
Task „autonomietauglich" macht, steht in [`../AUTONOMOUS.md`](../AUTONOMOUS.md).

**`set-files` statt Scope lockern:** braucht eine Task eine Datei, die nicht in ihrem
`Dateien:` steht, wird die Liste **sichtbar** erweitert — `task-close.sh` prüft die gestagten
Pfade dagegen.

## `Test-Löschung:` — ein ganzer Test geht mit

`task-close.sh` lässt `review.sh diff-scan` über den Diff laufen, und der wertet jede
gelöschte Assertion als „der Diff kauft sich sein Grün". Den einen Fall, in dem ein Test
zu Recht verschwindet, kündigt die Task an:

```
Test-Löschung: <datei>::<test> — <Grund>[; <datei>::<test> — <Grund> …]
```

Ein `;` trennt nur vor dem nächsten `<datei>::`, im Grund darf es also stehen.
`<test>` ist der Name, wie er im Kopf steht: `test_x` (pytest), `TestX` (Go), die
Beschreibung aus `it("…")`/`test("…")` (vitest/jest), die `fn` hinter `#[test]` (Rust).
Übergangen wird eine gelöschte Assertion nur, wenn **beides** gilt: Der Kopf des Tests steht
im selben zusammenhängenden Block gelöschter Zeilen, der ganze Test geht also mit. Und
`<datei>::<test>` ist angekündigt. Eine Assertion aus einem Test, der stehen bleibt, bleibt ein
Fund, angekündigt oder nicht. Stehen bleibt ein Test auch, wenn der Diff einen Kopf gleichen
Namens in derselben Datei wieder hinzufügt; ein Ersatztest trägt deshalb einen eigenen Namen.
Zum Test gehört nur, was unter seinem Kopf tiefer eingerückt ist: Die nächste gelöschte Zeile,
die nicht tiefer steht (die nächste Funktion, das schließende `}`), beendet ihn. Der Lauf nennt,
was er übergangen hat (`diff-scan: clean (1 declared test deletion(s): …)`).

**Passt:** toter Code geht samt seinem Test; ein Test wird durch einen genaueren ersetzt, der
im selben Commit kommt. **Passt nicht:** ein roter Test, der „weg soll". Das ist ein Befund
über den Code und gehört repariert oder als `[?]` vor Kevin, nicht gelöscht.
`ledger.sh lint` prüft die Form: `<pfad>::<name> — <Grund>`, **der Grund ist Pflicht**. Eine
Löschung, die niemand begründet, ist genau das, was das Gate verhindern soll.

## Aktueller Stand

- **`harness-stufe-3.md`** — `Status: aktiv`. Stufe 3 der Autonomie-Roadmap („Ausführung
  zuerst"): Artefakt-Assertionen im Release-Workflow, `check-versions.sh`, `-race`, der
  Wochenlauf `heavy.sh` mit Klassifikation und Historie, der Upgrade-Pfad und die fünf
  verwaisten Desktop-Specs. Spec: `docs/features/harness-stufe-3.md`.
- **`reg-<datum>-<schritt>.md`** — von `scripts/tests/heavy.sh` geschrieben, nicht von
  `/feature-plan`: eine bestätigte Regression aus einem Wochenlauf (Schritt auf zwei
  Boxen rot, auf dem letzten PASS-Commit grün). `Status: geplant` mit einem Beweis-Absatz
  über die drei Stationen (erste Box 3×, frische Zweit-VM, Basis-Commit); die Freigabe bleibt Kevins Haken, danach ist es ein Ledger wie
  jedes andere. Die zugehörige Roadmap-Zeile (Klasse REG) hängt `heavy.sh` selbst an.
- **`harness-stufe-1.md`** — `Status: erledigt` (gemergt, PR #11). Stufe 1 der Autonomie-Roadmap („Grün heißt
  Beweis"): SKIP wird Exit 75, `run.sh` bekommt `--strict`/`--only`/`--step`, dazu `verify.sh`,
  der Session-Status-Hook und der CI-Job `agent-windows`. Spec: `docs/features/harness-stufe-1.md`.
- **`audit-fixes.md`** — `Status: erledigt`, gitignored (der Report enumeriert ungefixte Funde
  inkl. ausnutzbarer Lücken; dieses Repo ist öffentlich). Die 681 Funde aus dem Fable-Audit;
  Fix-Detail je Fund in der Quelle, auf die das `Spec:`-Feld zeigt (gleiche IDs).
- **`test-infra-capstone-release.md`** — `Status: erledigt`. Test-Infrastruktur/Capstone/
  Release komplett (Phasen A–E), **Release v0.39.0 ist raus** (2026-07-04). Bleibt als Historie.
