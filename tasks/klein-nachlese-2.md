<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-nachlese-2 — Task-Ledger
Status: bereit · Branch: feature/klein-nachlese-2 · Review: pro Task
Spec: docs/features/klein-nachlese-2.md (Roadmap R-1250)
Heavy: none — Server-Laden, Schema-Limit, Skript-Test und ein Kommentar, kein Stack-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1250: FRP-Config-Detail lädt target_server vor, Tunnel-`name` hat max_length, Kommentar umgebrochen  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/config_router.py, apps/server/app/modules/frp/schemas.py, apps/server/app/modules/frp/config_generator.py, apps/server/tests/test_frp_tunnels.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @6f5441be3 2026-11-12T08:26:22+01:00
Review: approve (.ah-out/review/klein-nachlese-2/T1.verdict.json)
Beweis: reviewer/security arch-namen 2026-11-09 (Nits) · feature/arch-namen@04f6a2e15 frp/config_router.py:106, frp/schemas.py FrpTunnelCreate, frp/config_generator.py:143 · Dedup-Key: REF:cross:arch-namen:review-nits
Änderung: `get_server_config` lädt die Tunnel mit `selectinload(FrpTunnel.target_server)` (Test: eine Abfrage auf `servers` bei mehreren Tunneln); `FrpTunnelCreate.name` und `FrpTunnelUpdate.name` bekommen `Field(None, max_length=255)` (Test: 422 bei 256 Zeichen, 201/200 bei 255); der Kommentar vor `_refused_warned` wird als ein Absatz neu umbrochen, Wortlaut gleich. Der OpenAPI-Snapshot folgt dem Schema.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_tunnels.py tests/test_openapi_snapshot.py tests/test_frp_status.py
Doku: keine (internes Laden, Feldlimit im OpenAPI-Schema)

### T2 — R-1250: `e2e_api.py visitor-port` hat einen Unit-Test  [x]
Komponente: scripts · Dateien: scripts/dev/tests/test_e2e_api.py
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @a239c9a76 2026-11-12T08:51:15+01:00
Review: approve (.ah-out/review/klein-nachlese-2/T2.verdict.json)
Beweis: reviewer arch-namen 2026-11-09 · feature/arch-namen@04f6a2e15 scripts/tests/e2e_api.py:85 · Dedup-Key: REF:cross:arch-namen:review-nits
Änderung: Neuer Test lädt `scripts/tests/e2e_api.py` und prüft `visitor-port` mit ersetztem `_call`: ein Tunnel nach `label`, ein Alt-Tunnel nach `name`, ein Tunnel ohne Besucherport und ein unbekannter Name (leere Ausgabe). Neue Datei mit SPDX-Header.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test)

### T3 — R-1250: Tunnel-`name`-Limit aus T1 zurücknehmen (Vertragsänderung, openapi-compat rot)  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/tests/test_frp_tunnels.py, apps/server/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @d870265c1 2026-11-12T09:04:46+01:00
Review: approve (.ah-out/review/klein-nachlese-2/T3.verdict.json)
Beweis: Abschlussprüfung branch 2026-11-12: `openapi-breaking.sh server --base main` rc=1, `request-property-max-length-set` auf POST/PUT `name`; die Ausnahme wäre ein Harness-Pfad (`oasdiff-err-ignore.txt`), API-Vertrag ist Kevins Entscheidung (CLAUDE.md §2)
Änderung: `max_length=255` an `FrpTunnelCreate.name`/`FrpTunnelUpdate.name` und der dazugehörige Test fallen weg, der Snapshot geht auf den Stand von `main` zurück; das Limit wird eigene Roadmap-Zeile für Kevin. Das Vorladen und der Kommentar aus T1 bleiben.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_tunnels.py tests/test_openapi_snapshot.py tests/test_frp_status.py
Doku: keine (Rücknahme)
Test-Löschung: apps/server/tests/test_frp_tunnels.py::test_a_tunnel_name_is_capped_at_255_characters_like_the_label — aus T1, das Limit entfällt (nie auf main)
