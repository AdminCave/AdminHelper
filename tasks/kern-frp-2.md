<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-frp-2 — Task-Ledger
Status: geplant · Branch: feature/kern-frp-2 · Review: pro Task
Spec: docs/features/kern-frp-2.md (Roadmap R-0972, R-0973, R-0969, R-0970, R-0971)
Heavy: linux-full — Server-API (FRP-Generate- und Sync-Routen)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — FRP-Generator prüft Server- und Nutzernamen (R-0972)  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/config_generator.py, apps/server/app/modules/frp/generate_router.py, apps/server/tests/test_frp_toml_roundtrip.py, apps/server/tests/test_frp_permissions.py
Änderung: Namen mit Zeichen, die `_reject_toml_breakers` ablehnt, landen in keiner TOML (Spec, Ziel 1): frpc-`user` → Text ohne Tunnel und ohne `user`-Zeile, Route 404, Bulk-ZIP ohne den Server; `allowUsers` ohne den Namen; Visitor ohne Tunnel des Zielservers; abgelehnter Visitor-Nutzer → 404 bzw. kein Eintrag. Tests je Fall.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_toml_roundtrip.py tests/test_frp_permissions.py
Doku: → T3
Test-Löschung: apps/server/tests/test_frp_toml_roundtrip.py::test_allow_users_is_only_safe_because_usernames_are_validated — hält fest, dass der Generator allowUsers ungeprüft schreibt; ersetzt durch einen Test, dass er den Namen auslässt (die Schema-Hälfte bleibt).

### T2 — frpc-toml-Route über frpc_sync_inputs (R-0973)  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/generate_router.py, apps/server/tests/test_frp_permissions.py
Beweis: security kern-frp-1 T2 2026-10-29 · generate_router.py `gen_frpc_toml` (Config aus `tunnels[0].frp_config_id`)
Änderung: `gen_frpc_toml` holt Config, Tunnel und allowUsers aus `frpc_sync_inputs`, wie Sync und Bundle; Test: Server mit Tunneln in zwei Configs bekommt denselben Text wie `GET /api/frp/provision/{id}/config` (erst rot).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_permissions.py tests/test_frp_provision_sync.py
Doku: → T3
Abhängt von: T1

### T3 — Generator-Warnungen einmal, Wortlaut, Doku (R-0969, R-0970, R-0971)  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/config_generator.py, apps/server/tests/test_frp_permissions.py, docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-frp-2.md
Änderung: `without_refused_fields`, `without_unreachable_local`, `without_unbindable_visitor`, `without_secretless_stcp` und die Namensprüfung aus T1 warnen über `_first_warning` einmal je Tunnel und Grund, Namen mit `%r`; Docstrings und Doku „Zeichen, die die API ablehnt“ statt „die die API ablehnen würde“; Doku DE+EN für T1–T3, Changelog. Test: zweiter Aufruf warnt nicht erneut.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_permissions.py tests/test_frp_toml_roundtrip.py
Doku: docs/developer/server.html, docs/en/developer/server.html, changelog.d/kern-frp-2.md
Abhängt von: T1

## Entscheidungen
- 2026-10-30 Plan: abgelehnte Namen auslassen statt escapen (Spec, Trade-offs); bei leerer allowUsers nach dem Auslassen
  gilt der bestehende Fallback des Generators.
