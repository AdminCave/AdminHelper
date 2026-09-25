<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# `SafeText` löschen — Task-Ledger (Kurz)
Status: aktiv · Branch: fix/safetext-delete · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Spec: dieses Ledger (Nachtrag zu R-0067, Entscheidung (b); Weg dafür: R-0079)
Heavy: none
DoD je Task: CLAUDE.md (Tests grün, ruff sauber, Doku im selben Commit).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Hängt ab von: R-0079 (gemergt, #40)

## Warum

Seit der NUL-Flächenregel (R-0067, PR #38) hat der Typ `SafeText` in `apps/server/app/core/bounds.py`
keinen Nutzer mehr. Nur sein eigener Unit-Test hält ihn noch am Leben. Kevin hat am 2026-09-23
entschieden, ihn zu löschen (Entscheidung (b)). T10 von R-0067 war dafür gebaut, grün und reviewt,
scheiterte aber am `diff-scan`: Für einen bewusst gelöschten Test gab es keinen Weg. R-0079 (#40) hat
ihn geschaffen. Diese Task ist zugleich der erste echte Lauf der neuen Regel durch `task-close.sh`.

### T1 — `SafeText` und seinen Test löschen  [ ]
Komponente: server · Dateien: apps/server/app/core/bounds.py, apps/server/tests/test_text_bounds.py
Test-Löschung: apps/server/tests/test_text_bounds.py::test_safetext_passes_everything_but_nul — der Typ SafeText hat seit R-0067 keinen Nutzer mehr und geht mit
Änderung: Den gesicherten Patch `tasks/private/patches/r0079-safetext-delete.patch` anwenden; er passt ohne Konflikt auf `main` @61d1d04d. Er löscht `SafeText` und `_reject_nul` aus `bounds.py`; die Begründung, warum genau dieses Byte, wandert in den Docstring von `RequestModel`. In `test_text_bounds.py` fallen der Typ-Test und seine Importe weg, die Routentests bleiben. Nachweis, dass nichts mehr darauf zeigt: `grep -rn "SafeText\|_reject_nul(" apps/server/app` ist leer, dazu die volle Server-Suite. Beim Schließen muss `diff-scan` melden: `clean (1 declared test deletion(s): apps/server/tests/test_text_bounds.py::test_safetext_passes_everything_but_nul)`.
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (interner Typ; CHANGELOG und Entwickler-Doku nennen ihn nicht)
