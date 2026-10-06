<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# pyjwt 2.14.0 → 2.15.1 im Server-Lock (R-0193) — Task-Ledger
Status: erledigt · Branch: feature/deps-pyjwt · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-06 (Kevin hat R-0193 am 2026-10-06 angenommen und den Bau durch Worker A gewählt; Ein-Task-Paket, Delegation Kevin 2026-10-05)
Spec: Roadmap R-0193 (Kurz-Ledger ohne Spec)
Heavy: none — nur der gehashte Lock und die Untergrenze einer reinen Python-Bibliothek in apps/server; kein Dockerfile, kein Compose, kein Gateway-, PKI- oder Install-Pfad. Den JWT-Pfad (`app/core/auth.py`, `jwt.encode`/`jwt.decode` mit HS256) deckt die Server-Unit-Suite, der Lock-Stand des Images läuft im CI-Job `python-lock-server`.
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-06 von der Aufsicht (adminhelper-ac). Vorbild ist der Bump 2.13.0 → 2.14.0 (`5d824207`) und der
anyio-Bump (`9ead47da`): Lock mit pip-compile neu, im Diff ändert sich nur das eine Paket, Evidenz im Commit-Body.
Der Fund trifft laut Advisory den JWKS-Pfad (`PyJWKClient.get_signing_key_from_jwt`) und jedes Dekodieren ohne
Signaturprüfung; der Server nutzt nur `jwt.decode` mit Schlüssel und `algorithms=[…]` (`app/core/auth.py:83`, `:125`,
`:151`, `:173`). Der Bump macht den Audit wieder grün, eine Code-Änderung gehört nicht dazu.

### T1 — pyjwt im Server-Lock auf 2.15.1 heben (R-0193)  [x]
Komponente: server · Dateien: apps/server/requirements.in, apps/server/requirements.txt, CHANGELOG.md, THIRD_PARTY_LICENSES.md
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped · contracts: 1 ok @f3baa7fa 2026-10-06T01:32:36+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Untergrenze in `requirements.in` auf `PyJWT>=2.15.0`. Den Lock nach DEVELOPMENT.md „Lock neu erzeugen“
erzeugen (Python 3.12 wie das Dockerfile, pip-tools, `--generate-hashes`, dazu `--upgrade-package pyjwt==2.15.1`);
im Diff von `requirements.txt` ändern sich nur Version und Hashes von pyjwt, der Kopf bleibt. Vorher das offizielle
CHANGELOG von PyJWT 2.14.0 → 2.15.1 lesen (Repo `jpadilla/pyjwt`): keine inkompatible Änderung an `jwt.encode` und
`jwt.decode` mit HS256, wie `app/core/auth.py` sie nutzt; die Hashes gegen PyPI prüfen. CHANGELOG unter
`[Unreleased]` → `### Security` wie der Eintrag „pyjwt 2.13.0 → 2.14.0“, in dessen Form (Advisory-ID, Quelle
Audit, Changelog-Befund, Testzahl, `pip-audit` ohne Befund). Im Commit-Body zusätzlich: `pytest` gegen den exakten
neuen Lock (`--require-hashes`, Python 3.12, Venv unter `~/.cache`, Rezept DEVELOPMENT.md) und
`(cd apps/server && pip-audit -r requirements.txt --disable-pip)` wie in `audit.yml`, alter Lock mit Fund, neuer ohne.
Beweis: `gh run view 37325402429 --log-failed` (audit.yml 2026-10-05, Job „pip-audit (server + monitoring +
ca-issuer)“) ⇒ `pyjwt 2.14.0  PYSEC-2026-4141 2.15.0`; monitoring und ca-issuer ohne Fund (sie nutzen pyjwt nicht).
Dedup-Key: rel:server:requirements.txt:pyjwt
HEAD: 45bce049
Semantik: DEVELOPMENT.md „Audit-Tools lokal“: „`audit.yml` faehrt den woechentlichen CVE-Sweep in CI.“ und zum Lock
(DEVELOPMENT.md „Python-Dependencies & Lockfiles“): „die **generierte, gepinnte + gehashte** Lockfile, die der
Production-Container per `pip install --require-hashes` installiert (Supply-Chain-Integrität). **Nicht von Hand
editieren.**“
Verify: bash scripts/dev/verify.sh server --strict
Doku: CHANGELOG.md
