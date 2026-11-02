<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-server-3 — Task-Ledger
Status: aktiv · Branch: feature/klein-ref-server-3 · Review: am Ende
Spec: docs/features/klein-ref-server-3.md (Roadmap R-1011, R-1025)
Heavy: none — Warn-Schlüssel, Doku und ein SQLAlchemy-Aufruf mit gleicher Menge; keine API, kein Gateway
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1011: Warn-Grund der extra_config-Keys präfixen, Kommentar und Sync-Absatz richtigstellen  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/config_generator.py, apps/server/tests/test_config_generator.py, docs/developer/server.html, docs/en/developer/server.html
Beweis: reviewer+security kern-frp-2 T3 (Nits), 2026-10-30 · feature/kern-frp-2@ecd1b16a apps/server/app/modules/frp/config_generator.py:142, docs/developer/server.html:101
Dedup-Key: ref:server:config_generator.py:warn-reason-collision
Änderung: Erst ein roter Test: ein Tunnel mit `extra_config` `{"no secret": 1}` (Key mit Leerzeichen, wird abgelehnt) neben einem stcp-Tunnel ohne Secret gleichen Namens warnt zweimal (heute einmal). Dann `_first_warning(tunnel.name, ("extra_config", *refused))` und den Kommentar Z. 142–146 auf die Präfix-Regel umstellen. Den Sync-Absatz in server.html (DE+EN, Z. 101) um den abgelehnten Servernamen und die frpc-toml-Gleichheit ergänzen, nach dem Code gelesen.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_config_generator.py
Doku: docs/developer/server.html, docs/en/developer/server.html (die Änderung selbst)

### T2 — R-1025: DISTINCT ON über postgresql.distinct_on  [ ]
Komponente: server · Dateien: apps/server/app/modules/enrollment/expiry.py, apps/server/tests/test_certificate_expiry.py
Beweis: reviewer branch kern-ca-4 2026-10-31, apps/server/app/modules/enrollment/expiry.py:68
Änderung: `.distinct(IssuedCertificate.line_id)` durch `postgresql.distinct_on` ersetzen, gleiche Sortierung. Test: `agents()` liefert je Linie den neuesten Eintrag (besteht ggf. schon) und der Aufruf löst keine `SADeprecationWarning` aus (`pytest.warns`-Gegenstück, `warnings.catch_warnings(error)`).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_certificate_expiry.py
Doku: keine (interne Abfrage, gleiches Ergebnis)
