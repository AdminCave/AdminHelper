<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-frp-1 — Task-Ledger
Status: bereit · Branch: feature/kern-frp-1 · Review: pro Task
Spec: docs/features/kern-frp-1.md (Roadmap R-0894, R-0926)
Heavy: linux-full — Server-API (FRP-Generator-Routen); kein Wire-Format- oder Install-Pfad ändert sich
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Für alle Tasks: Zeilenangaben `origin/main@33295e76`, vor dem Schreiben neu greppen; Pfade ohne Präfix unter
`apps/server/app/modules/frp/`. Neue Code-Strings englisch, CHANGELOG umlautfrei in `changelog.d/kern-frp-1.md`.
`security` je Task. Einzelheiten der SEC-Zeile privat.

### T1 — Generator lässt Tunnel mit abgelehnten Feldwerten aus (R-0894)  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/config_generator.py, apps/server/tests/test_config_generator.py, changelog.d/kern-frp-1.md, docs/developer/server.html, docs/en/developer/server.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @e9329613 2026-10-29T21:12:18+01:00
Review: approve (.ah-out/review/kern-frp-1/T1.verdict.json)
Änderung: Ein neuer Filter in `config_generator.py` lässt Tunnel aus, deren `name`, `local_ip`, `custom_domains` oder `secret_key` `_reject_toml_breakers` (`schemas.py:27`) nicht bestehen, und warnt mit dem Namen per `repr`, ohne Werte; eingehängt in `active_tunnels` (:240) und in die Kette von `generate_visitor_toml` (:427). Test zuerst rot: je Feld eine Altzeile → kein Block in frpc- und Visitor-TOML, die übrigen Tunnel bleiben.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_config_generator.py
Doku: changelog.d/kern-frp-1.md, docs/developer/server.html:110-111 + EN

### T2 — Generator-Routen filtern wie active_tunnels (R-0926)  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/generate_router.py, apps/server/tests/test_frp_input_hardening.py, changelog.d/kern-frp-1.md, docs/developer/api-reference.html, docs/en/developer/api-reference.html, docs/features/kern-frp-1.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @d4c657e2 2026-10-29T21:21:57+01:00
Review: approve (.ah-out/review/kern-frp-1/T2.verdict.json)
Änderung: `gen_frpc_toml` (`generate_router.py:77`) und der Bulk-ZIP (:193-199) nehmen vor der 404-Prüfung dieselbe Menge wie `active_tunnels`, also auch `without_unreachable_local` und den Filter aus T1; die Visitor-Routen (:125, :154, :216) zusätzlich den Filter aus T1. Kommentare :81-83 und :190-192 nachziehen. Test zuerst rot: ein Server, dessen einziger Tunnel ein ungültiges `local_port` hat → 404, im Bulk-ZIP keine `frpc.toml`.
Beweis: Code-Lesung feature/server-fixes@0eb986e0 generate_router.py; Test: Server nur mit local_port 0 → frpc-toml-Route 200 statt 404
Dedup-Key: ref:server:frp/generate_router.py:active-tunnel-prefilter
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_input_hardening.py
Doku: changelog.d/kern-frp-1.md, docs/developer/api-reference.html:150-153 + EN
Abhängt von: T1

### T3 — Entwickler-Doku: Bedingungen von active_tunnels vollständig (R-0894, Fund der Abschlussprüfung)  [x]
Komponente: scripts · Dateien: docs/developer/server.html, docs/en/developer/server.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @5b6f0954 2026-10-29T21:38:16+01:00
Review: am Ende (nur Doku, Branch-Review)
Änderung: Die Klammer zu `active_tunnels` im Absatz zum Agent-Sync (`docs/developer/server.html:101` + EN) nennt auch `local_port` 1–65535 und die gespeicherten Felder, die `without_refused_fields` prüft; erst damit stimmt „genau die `[[proxies]]` des Generators“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/server.html:101 + EN
Task-Review: am Ende

## Entscheidungen
