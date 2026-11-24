<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-10 — Erstkontakt-Doku in Einklang mit dem Code — Task-Ledger
Status: aktiv · Branch: feature/klein-doku-10 · Review: am Ende
Spec: docs/features/klein-doku-10.md (Roadmap R-1716)
Heavy: none — reine Doku
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Stand `origin/main@7d787e4d2`.

### T1 — Voraussetzungen und Ports: minisign, openssl, 8445, DE und EN gleich (R-1716 a, b)  [x]
Komponente: scripts · Dateien: README.md, docs/admin/installation.html, docs/en/admin/installation.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @c8a3049ca 2026-11-24T21:19:59+01:00
Review: am Ende (Branch-Review)
Beweis: Umschau 2026-11-23 · scripts/install.sh `verify_sums_signature` (bricht ohne minisign ab), scripts/init-secrets.sh (openssl), docs/admin/agent-deployment.html (Repo-Schlüssel von `:8445`)
Semantik: docs/admin/agent-deployment.html: "Es holt den Repo-Signaturschlüssel von der :8445-Plane" (der Agent-Einzeiler braucht den Port)
Dedup-Key: ref:docs:README.md:first-contact-drift-prereq
Änderung: Voraussetzungen in README (Quick start) und beiden Installationsseiten nennen `minisign` (Installer prüft die Signatur von SHA256SUMS, fehlt es, bricht er ab) und `openssl` (`init-secrets.sh`). Port 8445 in DE und EN gleich: der Agent-Einzeiler braucht ihn. Linux-Distributionen und beide DNS-Einträge (`srm`, `frp`) in DE nachgezogen, der manuelle Updateweg `docker compose pull server` / `up -d server` in EN.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Änderung selbst

### T2 — Bootstrap-Token, .env.example, Besucher-Ports (R-1716 c, d)  [x]
Komponente: scripts · Dateien: README.md, .env.example, DEVELOPMENT.md, docs/admin/installation.html, docs/en/admin/installation.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @46ede35b6 2026-11-24T21:24:32+01:00
Review: am Ende (Branch-Review)
Beweis: Umschau 2026-11-23 · apps/server/app/main.py (`write_private_file(BOOTSTRAP_SETUP_FILE, token)`, Log nennt nur Pfad und Befehl), apps/server/app/core/config.py:168-171,187-188, docker-compose.yml (kein `VISITOR_PORT_*` im Server-Block)
Semantik: docs/en/admin/installation.html: `docker compose exec server cat /app/data/.bootstrap_setup`
Dedup-Key: ref:docs:README.md:first-contact-drift-token
Änderung: README, `.env.example` und `DEVELOPMENT.md` nennen den Weg der Installationsseite (`docker compose exec server cat /app/data/.bootstrap_setup`; in `data/.bootstrap_token` liegt der Hash, im Log stehen Pfad und Befehl). `.env.example`: das `certs/` im DOMAIN-Kommentar fällt weg (das Gateway-Zertifikat stellt der ca-issuer aus). `VISITOR_PORT_START`/`_END`: Hinweis in der Variablentabelle DE+EN, dass die mitgelieferte `docker-compose.yml` sie nicht durchreicht.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Änderung selbst

### T3 — SECURITY.md: frps-Capabilities und Image-Pinning (R-1716 e)  [ ]
Komponente: scripts · Dateien: SECURITY.md
Beweis: Umschau 2026-11-23 · docker-compose.yml (frps: `cap_drop: [ALL]`, `cap_add: [DAC_OVERRIDE, SETUID, SETGID, KILL]`), alle `FROM` der Dockerfiles `@sha256`, alle `uses:` der Workflows auf Commit-SHA
Semantik: docker-compose.yml, Kommentar am frps-Block (Capabilities mit Begründung)
Dedup-Key: ref:docs:README.md:first-contact-drift-security
Änderung: Der Eintrag „frps container capability hardening — attempted and reverted“ wird zur Beschreibung des heutigen Stands (cap_drop ALL, vier Capabilities mit Grund); „Base-image / GitHub-Action tag pinning“ verliert den Pinning-Teil (Basis-Images per Digest, Actions per SHA) und behält SMART-Sanitisierung und `MONITOR_API_KEY`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Änderung selbst

## Entscheidungen
- `VISITOR_PORT_START`/`_END` bleiben in Compose unverdrahtet; die Doku sagt es (Spec, offene Frage).
