<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CI prüft den Lock-Stand der Images (R-0115) — Task-Ledger
Status: erledigt · Branch: harness/lock-state-ci · Commit-Granularität: pro Task · Review: am Ende (Harness-Pfad scripts/dev ⇒ Reviewer Opus) · Modell: Opus
Freigabe: Kevin, 2026-09-29 („R-0115 und R-0120 freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: Roadmap R-0115
Heavy: none — die Images ändern sich nicht; der neue CI-Job selbst ist die Prüfung und läuft im PR (drei Lock-Jobs grün, per `gh run watch` belegt).
DoD je Task: CLAUDE.md (Tests grün, ruff check + ruff format sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-09-29 von der Aufsicht (adminhelper-ac) auf Kevins Wort („Beide planen“).
Branch `harness/`, weil T1 unter `scripts/dev/` liegt (CLAUDE.md §3, Trigger 4): Bau interaktiv, keine Lane.
Befund: Jeder Test-Job installiert die losen Abhängigkeiten, `.github/workflows/ci.yml:80` (server, py3.12/3.13),
`:140` (monitoring), `:162` (ca-issuer), `:211–214` (schemathesis), jeweils `pip install -r requirements-dev.txt`, das
mit `-r requirements.in` beginnt. Die drei Images bauen auf `python:3.12-slim` mit
`pip install --no-cache-dir --require-hashes -r requirements.txt` (`Dockerfile:14,32`,
`apps/monitoring/Dockerfile:1,15`, `apps/ca-issuer/Dockerfile:1,15`). Kein CI-Schritt installiert einen Lock
(`grep -n 'require-hashes\|requirements\.txt' .github/workflows/ci.yml` trifft nur die Kommentare `:78–79`,
`:138–139`, `:159–160`). Server: 27 von 38 Pins weichen zwischen losem Stand und Lock ab, u. a. fastapi
0.138.0 → 0.141.1, starlette 1.3.1 → 1.7.0, sqlalchemy 2.0.50 → 2.1.1. Präzedenz: fastapi 0.138 brach
`test_route_auth_gate` nur im losen Stand (CHANGELOG, Changed). Der Explorer der Aufsicht hat am 2026-09-29
(py3.12.14) den Weg geprüft: Lock mit `--require-hashes`, danach die unveränderte `requirements-dev.txt` →
`pip freeze` ohne verschobene Lock-Zeile, `pip check` sauber, in allen drei Diensten; `-c requirements.txt`
scheitert an Extras („Constraints cannot have extras“).

### T1 — Pin-Check: jeder Lock-Pin ist so installiert, wie der Lock ihn nennt  [x]
Komponente: scripts · Dateien: scripts/dev/lock-pins.py, scripts/dev/tests/test_lock_pins.py
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @2438ef75 2026-09-29T14:26:16+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: Neues stdlib-Skript (SPDX-Header) `lock-pins.py <requirements.txt>`: liest die `name==version`-Zeilen
eines pip-compile-Locks (Extras entfernt, Namen nach PEP 503 normalisiert, Hash- und Kommentarzeilen übersprungen)
und vergleicht sie mit `importlib.metadata` der laufenden Umgebung. Exit 0 nur, wenn jeder Pin in genau dieser
Version installiert ist; Exit 1 nennt jeden verschobenen oder fehlenden Pin; ein leerer oder unlesbarer Lock ist
Exit 2, nie grün. Test mit Fixture-Lock und einer Fixture-Umgebung (`--freeze <datei>` als Eingang statt
`importlib.metadata`): passender Stand → 0, ein verschobener Pin → 1, ein fehlender → 1, Extras im Lock
(`uvicorn[standard]==…`) → verglichen ohne Extra, leerer Lock → 2. Gegenprobe: jede Assertion gegen ein Skript,
das immer 0 liefert, ist rot.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T3)

### T2 — CI-Job `python-lock`: die Suiten gegen den Lock-Stand der Images  [x]
Komponente: scripts · Dateien: .github/workflows/ci.yml, scripts/dev/tests/test_lock_pins.py
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @4d32865a 2026-09-29T14:32:59+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: Neuer Job in `ci.yml`, Python 3.12 wie `FROM python:3.12-slim`, für server, monitoring und ca-issuer
(Matrix oder drei Jobs, je nachdem, ob die Services von server und monitoring sich sauber in eine Matrix fassen
lassen — Postgres/Redis wie in den bestehenden Jobs): `pip install --require-hashes -r requirements.txt`, dann
`pip install -r requirements-dev.txt`, dann `python scripts/dev/lock-pins.py requirements.txt`, dann
`pytest -q -m "not schemathesis"` wie die bestehenden Jobs. Die bestehenden Pflicht-Jobs bleiben unverändert
(Namen und Bedeutung), nur ihre Kommentare `:78–79`, `:138–139`, `:159–160` nennen den neuen Job. Lockstep-Test in
`test_lock_pins.py`: jedes Dockerfile mit `--require-hashes -r requirements.txt` hat einen `python-lock`-Eintrag in
`ci.yml`, und dessen `python-version` ist die aus `FROM python:X`.
Beweis: origin/main@60544235 · das grep aus dem Befund trifft nur Kommentare; der Lockstep-Test ist gegen das
heutige `ci.yml` rot.
Verify: bash scripts/dev/verify.sh scripts --strict
Abschluss-Evidenz: der CI-Lauf des PRs mit drei grünen Lock-Jobs (`gh run watch`), Summary-Zeilen in den PR-Body.
Doku: keine (T3)
Abhängt von: T1

### T3 — Doku: was CI gegen welchen Stand prüft  [x]
Komponente: scripts · Dateien: DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @678e66a7 2026-09-29T14:37:58+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: `DEVELOPMENT.md:66–72` („Tests/CI installieren `requirements.in` …“) nennt den Lock-Job und das lokale
Rezept in drei Zeilen (Venv unter `~/.cache`, Lock mit `--require-hashes`, dann `requirements-dev.txt`, dann
`lock-pins.py`). `cicd.html:40` DE+EN: der neue Job in der `ci.yml`-Zeile. CHANGELOG [Unreleased] ein Eintrag.
`run.sh` bleibt unverändert (Harness-Datei; ein Lock-Stand im geteilten `AH_VENV` würde bei jedem Lauf wechseln).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die Task ist die Doku
Abhängt von: T2

Dedup-Key: rel:deps:requirements.txt:lock-drift · HEAD: 60544235
Semantik: DEVELOPMENT.md:66–67 („Tests/CI installieren `requirements.in` (lose, ungehasht) — `--require-hashes`
verträgt keine Mischung aus gehashten und ungehashten Zeilen.“) beschreibt das heutige Verhalten als gewollt; die
Ergänzung um den Lock-Stand hat Kevin am 2026-09-29 zur Planung freigegeben.
Nach dem Merge, Kevins Handgriff: die neuen Job-Namen ins Ruleset der Pflicht-Checks aufnehmen (sonst ist der Job
nur beratend).

### T4 — Review-Nits: Lockstep-Test ohne Kommentare, lokales Rezept nennt Python 3.12  [x]
Komponente: scripts · Dateien: scripts/dev/tests/test_lock_pins.py, DEVELOPMENT.md
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @17c52041 2026-09-29T15:01:59+02:00
Review: Nits aus dem Opus-Schluss-Review (approve)
Änderung: Aus dem Schluss-Review (Opus, approve, nits). Der Lockstep-Test sucht die Pflicht-Strings eines
`python-lock-*`-Jobs nur in Zeilen, die kein YAML-Kommentar sind (Probe des Reviewers: `lock-pins.py
requirements.txt` nur noch im Kommentar, Schritt `run: "true"` → Test grün), und verlangt zusätzlich
`-m "not schemathesis"`. Das lokale Rezept in `DEVELOPMENT.md` nennt, dass es ein Python 3.12 braucht (auf der
Dev-Box liegt kein `python3.12` im PATH; etwa `uv python install 3.12`).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (die Task ist zur Hälfte Doku)
