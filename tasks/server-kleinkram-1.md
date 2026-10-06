<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server-Kleinkram 1: Modelle im Test-conftest, `EnrollmentToken.to_dict` ohne Aufrufer — Task-Ledger
Status: geplant · Branch: feature/server-kleinkram-1 · Commit-Granularität: pro Task · Review: auto · Modell: Opus
Spec: Roadmap R-0205, R-0208 (Kurz-Ledger ohne Spec)
Heavy: none — Server-Testinfrastruktur und eine ungenutzte Methode; kein Stack-, Gateway-, PKI- oder Install-Pfad, kein API-Vertrag, keine Migration. Python und die Server-Suite reichen, also auch auf der Runner-Box baubar.
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-06 von der Aufsicht (adminhelper-ac) aus zwei Zeilen, die Kevin in der Triage vom 2026-10-06 als
Runner-Futter angenommen hat. Zeilenangaben main@3c1aac69 (nach R-0064, #87).

### T1 — conftest importiert jedes Modell-Modul, ein Schutztest hält es fest (R-0205)  [ ]
Komponente: server · Dateien: apps/server/tests/conftest.py, apps/server/tests/test_conftest_models.py (neu, SPDX)
Änderung: `tests/conftest.py:25–35` importiert die Modell-Module ausdrücklich, damit `Base.metadata` jede Tabelle
für `create_all` kennt; `app.modules.provisioning.models` fehlt. Wer `provision_tokens` braucht und allein läuft,
findet die Tabelle nicht, im vollen Lauf importiert `test_provisioning.py` sie beim Sammeln (Reihenfolge-Abhängigkeit).
Den Import ergänzen, in der Reihenfolge der übrigen. Neuer Schutztest: er liest `tests/conftest.py` mit `ast` (nicht
über die geladenen Module, sonst hinge er wieder an der Reihenfolge) und verlangt für jede Datei
`app/modules/*/models.py` einen Import des Moduls in conftest (`import app.modules.<x>.models` oder `from
app.modules.<x>.models import …`). Erst der Test, rot auf `HEAD` (er nennt `provisioning`), dann der Import.
Beweis: Roadmap R-0205 — Worker A beim Bau von R-0201 (2026-10-06): ein neuer Test ohne eigenen Modell-Import fand
`provision_tokens` allein gefahren nicht; `tests/conftest.py:25–35` auf main@3c1aac69 ohne `provisioning`.
Semantik: der Kommentar in `tests/conftest.py`: „Explicitly import all models — otherwise Base.metadata does not
know about them.“ — heute stimmt „all“ nicht.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_conftest_models.py
Doku: keine (intern)

### T2 — `EnrollmentToken.to_dict` entfernen (R-0208)  [ ]
Komponente: server · Dateien: apps/server/app/modules/enrollment/models.py, apps/server/tests/test_enrollment_mint.py
Änderung: `EnrollmentToken.to_dict` (`app/modules/enrollment/models.py:54`) hat im Server keinen Aufrufer (kein
Router gibt Enrollment-Token aus); R-0064 T4 hat ihr nur das Zeitformat nachgezogen und einen Test dazu geschrieben.
Methode und Test entfernen, ebenso Imports, die danach verwaisen (`Any`, `iso_utc`, falls nur hier genutzt). Vorher
mit `git grep -n 'to_dict' apps/server` und über `apps/ca-issuer` bestätigen, dass niemand sie aufruft; findet sich
ein Aufrufer, `[~]` mit dem Fund statt löschen.
Test-Löschung: apps/server/tests/test_enrollment_mint.py::test_to_dict_timestamps_are_rfc3339_utc — testet nur die entfernte Methode ohne Aufrufer (R-0208)
Beweis: Roadmap R-0208 — Worker B beim Bau von R-0064 (2026-10-06): `EnrollmentToken.to_dict` ohne Aufrufer im
Server; die Spec `docs/features/tz-aware-datetimes.md` vermerkt dasselbe (F6/F7).
Semantik: keine Stelle in docs/ beschreibt eine Ausgabe von Enrollment-Token über die API; `app/core/time.py`
(F7) nennt `to_dict` nicht.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_enrollment_mint.py
Doku: keine (intern)
