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

- **`audit-fixes.md`** — `Status: aktiv`. Die 681 Funde aus dem Fable-Audit; Fix-Detail je Fund
  in `../fabelreport.md` (gleiche IDs). Bewusst schlanke Checkliste, keine 681 Einzel-Tasks.
- **`test-infra-capstone-release.md`** — `Status: erledigt`. Test-Infrastruktur/Capstone/
  Release komplett (Phasen A–E), **Release v0.39.0 ist raus** (2026-07-04). Bleibt als Historie.
