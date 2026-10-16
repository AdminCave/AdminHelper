<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Feste Reihenfolge von allowUsers — Task-Ledger
Status: geplant · Branch: feature/allow-users-order · Review: am Ende
Spec: Roadmap R-0435
Heavy: linux-full — Server erzeugt die frpc-Config der Agents (`frp/_helpers.py`, über `generate_frpc_toml` in `config`, `config-hash` und dem Provisionierungs-Paket); läuft im Sammellauf
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-16: `/feature-plan --kurz R-0435`, nach R-0398.

### T1 — `get_allow_users` liefert die Namen sortiert  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/_helpers.py, apps/server/tests/test_frp_permissions.py, docs/developer/server.html, docs/en/developer/server.html, CHANGELOG.md
Änderung: `get_allow_users` (`_helpers.py:80`) baut die Liste heute mit `list({u.username for u in [*assigned, *admins]})` (`:92`). Die Reihenfolge eines Python-`set` aus Strings hängt am Hash-Seed des Prozesses, der bei jedem Start zufällig ist (`PYTHONHASHSEED` ist im Server nicht gesetzt). Bei zwei oder mehr berechtigten Nutzern ändern sich damit nach jedem Neustart des Servers (mit `WEB_CONCURRENCY` > 1 auch je Worker) `allowUsers` in der frpc-Config und der `config-hash`, ohne dass sich etwas geändert hat. Neu: `sorted(...)` statt `list(...)`, die Duplikat-Entfernung bleibt. Test in `test_frp_permissions.py` neben `test_frpc_toml_endpoint_wires_allow_users` (`:186`), zuerst rot: zwölf Nutzer mit Zugriff auf einen Server (darunter Admins und doppelt zugeordnete) → `get_allow_users` gibt jeden Namen genau einmal und aufsteigend sortiert zurück; zwei Aufrufe ergeben dieselbe Liste. Doku DE+EN (`server.html:114`): `allowUsers` steht sortiert in der Config. CHANGELOG unter `### Fixed`, mit dem Hinweis, dass sich der Config-Hash von Hosts mit mehreren berechtigten Nutzern nach dem Update einmal ändert.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_permissions.py
Doku: docs/developer/server.html + docs/en/developer/server.html (`:114`) · CHANGELOG.md (Fixed)
Beweis: main@e995bba6 · `apps/server/app/modules/frp/_helpers.py:92` `names = list({u.username for u in [*assigned, *admins]})`; dreimal identisch: `for seed in 1 2 3; do PYTHONHASHSEED=$seed python3 -c 'print(list({u for u in ["admin","alice","bob","carol"]}))'; done` → seed 1 `['alice', 'carol', 'bob', 'admin']`, seed 2 `['admin', 'carol', 'alice', 'bob']`, seed 3 `['admin', 'alice', 'bob', 'carol']`; `grep -rn PYTHONHASHSEED apps/server docker-compose*.yml` → kein Treffer
Orakel: property — gleiche Eingabe ergibt in jedem Prozess dieselbe Liste
Dedup-Key: bug:server:frp/_helpers.py:allow-users-order
HEAD: e995bba6
Semantik: docs/developer/agent.html:65 — „Periodischer Config-Sync per Hash-Vergleich; schreibt nur, wenn sich der Server-seitige Hash ge&auml;ndert hat.“ (EN `docs/en/developer/agent.html:65`): der Hash soll sich nur mit der Config ändern
