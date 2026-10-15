<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# compose: ca-issuer startet erst nach der Server-Migration — Task-Ledger
Status: bereit · Branch: feature/ca-issuer-after-migration · Review: am Ende
Spec: Roadmap R-0288
Heavy: linux-full — `docker-compose.yml` (Startkette ca-issuer/server); läuft im Sammellauf (`/feature-build` §5); kein install-/update-Skript ändert sich, daher kein `scenario`
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-15: härten. Im normalen Start und Update ist das Fenster zu, weil das Gateway auf den healthy Server
wartet (`docker-compose.yml:197-198`); offen ist es bei Teil-Starts mit laufendem Gateway (nicht verifiziert).

### T1 — ca-issuer hängt am healthy Server, Test liest die Compose-Datei  [x]
Komponente: server · Dateien: docker-compose.yml, apps/server/tests/test_compose_startup_order.py, docs/admin/installation.html, docs/en/admin/installation.html, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @a4086520 2026-10-15T16:55:05+02:00
Review: am Ende (Branch-Review)
Änderung: Unter `ca-issuer` (`docker-compose.yml:202`) bekommt `depends_on` neben postgres (`:247-249`) `server: condition: service_healthy`, mit einem Kommentar wie am Server-Healthcheck (`:113-115`: Abhängige warten auf `service_healthy`, statt mit Alembic zu rennen). Der Server wird erst nach `alembic upgrade head` healthy (`apps/server/docker-entrypoint.sh:44`, dann uvicorn `:54`); vorher liefen `/enroll` und `/renew` des ca-issuer auf fehlende Register-Tabellen in einen 500. Kein Zyklus (ca-issuer → postgres, server; server → redis, postgres). Neuer Test `tests/test_compose_startup_order.py` (SPDX-Kopf) parst `docker-compose.yml` mit `yaml.safe_load` (nur die Basisdatei: `docker-compose.test.yml` trägt `!override`) und verlangt die Kante; auf HEAD rot. Ein Satz Doku bei den Migrationen der Installation (DE `installation.html:221`, EN-Gegenstück): Der ca-issuer startet erst nach der Migration. CHANGELOG unter Changed.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_compose_startup_order.py
Doku: docs/admin/installation.html + docs/en/admin/installation.html · CHANGELOG
Beweis: main@c18098a4 · `apps/server/.venv/bin/python -I -c "import yaml; d=yaml.safe_load(open('docker-compose.yml')); print(d['services']['ca-issuer']['depends_on'])"` → `{'postgres': {'condition': 'service_healthy'}}` (keine Kante zum Server); Gateway: `{'ca-issuer': {'condition': 'service_started'}, 'server': {'condition': 'service_healthy'}}`
Orakel: contract — Startkante ca-issuer → server (service_healthy) in der Compose-Datei
Dedup-Key: ref:compose:docker-compose.yml:ca-issuer-after-migration
HEAD: c18098a4
Semantik: docs/admin/installation.html:221 — der Entrypoint „wartet erst auf <code>pg_isready</code>, führt dann <code>alembic upgrade head</code> aus, dann erst startet uvicorn“; zur Startreihenfolge des ca-issuer keine Stelle in docs/ (gesucht: Startreihenfolge, depends_on, service_healthy, ca-issuer + Schema/Tabelle); die Absicht steht im Compose-Kommentar `docker-compose.yml:113-115`
