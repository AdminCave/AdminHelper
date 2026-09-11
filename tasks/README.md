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
(pro Task | pro Komponente | pro Abschnitt), `Review:`, `Modell:`, `Fast-Suite:`
(lokal | crabbox — wo Verify + Schnellsuite laufen; `crabbox` in Worktree-Lanes),
`Warm-Profil:` (desktop | pond — Box-Bedarf; optional `Abschluss: multibox <flags>`,
bleibt ask-first), DoD-Verweis auf `CLAUDE.md`.

**Task-Status im Body:** `[ ]` offen · `[x]` fertig · `[~]` übersprungen (Grund) ·
`[?]` braucht menschliche Entscheidung.

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
