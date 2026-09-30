<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# FRP: Tunnel-Secrets beim Bearbeiten erhalten, in JSON-Antworten maskieren — Task-Ledger
Status: bereit · Branch: feature/frp-secret-handling · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Freigabe: Kevin, 2026-09-30 („alle freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: docs/features/frp-secret-handling.md (Roadmap R-0113, R-0106, R-0053)
Heavy: scenario --tunnel — Generator, Datenmigration und Tunnel-API ändern sich; der Tunnel-Datenpfad über zwei Hosts belegt, dass gültige Tunnel unverändert laufen und stcp ohne Secret beim Anlegen weiter ein Secret bekommt (box_serverbox.sh). Bleibt ask-first; dazu die Desktop-Journey tunnel-crud.live.js (Umbenennen nach dem Maskieren)
DoD je Task: CLAUDE.md (Tests grün, ruff check + ruff format bzw. eslint/svelte-check sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-09-30 von der Aufsicht (adminhelper-ac); Entscheidungen Kevin 2026-09-30. Zeilenangaben main@8224e84c.
Reihenfolge: T1 vor T4 (ohne T1 würde das Maskieren beim Bearbeiten das Secret leeren).

### T1 — PUT: ein leeres Secret lässt das gespeicherte unverändert, stcp ohne Secret bekommt eins  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/tunnel_router.py, apps/server/tests/test_frp_tunnels.py
Evidenz: run.sh[quick]: 4 passed, 0 failed, 14 skipped @946f01af 2026-09-30T11:46:41+02:00
Review: approve (sonnet)
Änderung: In `update_tunnel` (`tunnel_router.py:145`) gilt ein gesendetes `secret_key` mit `null` oder `""` als nicht
gesendet (aus `sent`, `:156`, entfernen, bevor die Schleife `:180–193` schreibt). Nach der Schleife, neben der
Visitor-Port-Regel (`:195–196`): ist der Tunnel stcp und hat kein Secret, erzeugt `FrpTunnel.generate_secret()` eins.
Create (`:71–73`) bleibt. Tests in `test_frp_tunnels.py` (Stil `_seed`/`_body`/`_login`), jeweils über die Datenbank
geprüft: PUT mit `{"secret_key": null}` und mit `""` lässt das Secret gleich; PUT `tunnel_type: stcp` auf einen
https-Tunnel ohne Secret erzeugt ein Secret mit mindestens 32 Zeichen; PUT mit einem neuen gültigen Secret ersetzt es;
PUT ohne `secret_key` lässt es gleich. Die ersten drei sind vor dem Fix rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_tunnels.py tests/test_frp_input_hardening.py
Doku: keine (T4 und T5 tragen die sichtbare Änderung)

### T2 — Generator: ein stcp-Tunnel ohne Secret wird übersprungen, nicht mit leerem Secret geschrieben  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/config_generator.py, apps/server/tests/test_config_generator.py
Evidenz: run.sh[quick]: 4 passed, 0 failed, 14 skipped @a2aaafb1 2026-09-30T12:05:10+02:00
Review: approve (sonnet)
Änderung: `generate_frpc_toml` (Filter `:160`) und `generate_visitor_toml` (Filter `:219`) lassen einen stcp-Tunnel
ohne Secret (`None` oder `""`) weg und schreiben je Tunnel ein `logger.warning` mit Tunnel-Name; kein `raise`. Für
alle anderen Tunnel bleibt die Ausgabe byte-gleich. Tests: ein stcp-Tunnel mit `secret_key=None` und einer mit `""`
tauchen in frpc- und Visitor-TOML nicht auf (die Datei enthält weder `"None"` noch ein leeres `secretKey`), die
Warnung wird geloggt (`caplog`), ein gültiger Tunnel daneben steht unverändert drin. Vor dem Fix rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_config_generator.py tests/test_frp_toml_roundtrip.py
Doku: keine (intern)

### T3 — Datenmigration: bestehende stcp-Tunnel ohne Secret bekommen je ein eigenes  [x]
Komponente: server · Dateien: apps/server/alembic/versions/<neu>_fill_empty_stcp_secrets.py, apps/server/tests/test_migrations_smoke.py, apps/server/alembic/versions/8bdf9641a51f_fill_empty_stcp_secrets.py, CHANGELOG.md
Evidenz: run.sh[quick]: 4 passed, 0 failed, 14 skipped @70b463ba 2026-09-30T12:24:46+02:00
Review: approve (opus)
Änderung: Neue Alembic-Revision (SPDX-Header) auf den Head `e5f7a1b3c9d0`: für jede Zeile in `frp_tunnels` mit
`tunnel_type = 'stcp'` und `secret_key IS NULL OR secret_key = ''` ein eigenes `secrets.token_urlsafe(32)` in Python
(keine SQL-Zufallsfunktion, kein gemeinsamer Wert); Downgrade ist ein No-op mit Kommentar. Test nach dem Muster
`test_migrations_smoke.py:142`: drei stcp-Zeilen (NULL, `''`, gesetzt) und eine https-Zeile vor der Revision, danach
haben die zwei leeren je ein eigenes Secret (verschieden, ≥ 32 Zeichen), die gesetzte und die https-Zeile sind
unverändert. `test_migration_chain_*` bleiben grün.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_migrations_smoke.py
Doku: CHANGELOG (Changed: Migration füllt leere stcp-Secrets; laufende Desktop-Visitoren dieser Tunnel brauchen einen Neustart)

### T4 — JSON-Antworten liefern secretKey als null; TOML und Provisioning unverändert  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/models.py, apps/server/app/modules/frp/tunnel_router.py, apps/server/app/modules/frp/status_router.py, apps/server/app/modules/servers/models.py, apps/server/tests/test_frp_tunnels.py, apps/server/tests/test_frp_status.py, apps/server/tests/test_frp_config.py, apps/server/tests/test_servers_authz.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, CHANGELOG.md
Evidenz: run.sh[quick]: 4 passed, 0 failed, 14 skipped @26155818 2026-09-30T12:46:41+02:00
Review: approve (sonnet)
Änderung: `FrpTunnel.to_dict(mask_secrets: bool = False)` (`frp/models.py:111`, Muster `FrpServerConfig.to_dict`
`:41`) setzt `secretKey` auf `None`, wenn maskiert. Maskiert wird in den Tunnel-Routen (`tunnel_router.py:38/133/141/224`),
in `status_router.py:105`, in `FrpServerConfig.to_dict` für `include_tunnels` (`:64`, `mask_secrets` durchreichen) und
in `Server.to_dict` (`servers/models.py:53`). Die Generatoren und `/provision/{id}/config` lesen das Attribut direkt und
bleiben unverändert. Tests mit ausdrücklichem `secretKey is None` für Tunnels GET-Liste/GET/POST/PUT, `/api/frp/status`,
`/api/frp/server-config/{id}` und `/api/servers`; dazu ein Test, dass `/provision/{id}/config` und
`/generate/visitor-bundle` das Secret weiter tragen. Die Vergleiche gegen `to_dict()` in `test_frp_status.py:59` und
`test_frp_config.py:297` bekommen die ausdrückliche Assertion zusätzlich. Zusatzbeleg: `bash scripts/dev/openapi-breaking.sh server`
→ Exit 0 (nur der Wert ändert sich, nicht das Schema).
Test-Löschung: apps/server/tests/test_frp_tunnels.py::test_stcp_create_autogenerates_secret_and_port — die POST-Antwort trägt secretKey nicht mehr; der Ersatz prüft Secret und Visitor-Port über die Datenbank und die Maske in der Antwort
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_tunnels.py tests/test_frp_status.py tests/test_frp_config.py tests/test_servers_authz.py tests/test_frp_provision_authz.py
Doku: docs/developer/api-reference.html DE+EN bei `/api/frp/tunnels` (:130): Antworten liefern `secretKey` als `null`, das Secret steht nur in den erzeugten TOML-Dateien und im Provisioning; ein PUT mit leerem `secret_key` lässt es unverändert. CHANGELOG (Changed)
Abhängt von: T1

### T5 — Desktop-Editor: beim Bearbeiten „leer = unverändert“  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/src/lib/i18n/dictionaries.ts, apps/desktop/ui/src/components/infra/TunnelModal.svelte, apps/desktop/ui/src/components/infra/TunnelModal.test.ts, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html
Evidenz: run.sh[quick]: 1 passed, 0 failed, 17 skipped @ec6ac7f0 2026-09-30T12:52:45+02:00
Review: approve (sonnet)
Änderung: Neuer Schlüssel `infra.tun.secretHintEdit` („leer = unverändert“ / „empty = unchanged“) neben
`infra.tun.secretHint` (`dictionaries.ts:107`, EN `:702`); `TunnelModal.svelte` zeigt ihn im Bearbeiten-Modus, den
alten beim Anlegen. Test in `TunnelModal.test.ts`: Anlegen zeigt „automatisch generiert“, Bearbeiten „unverändert“.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: docs/admin/frp-tunnel.html DE+EN, ein Satz zum Secret-Feld (leer beim Anlegen = erzeugt, beim Bearbeiten = unverändert, Rotieren = neuen Wert eintragen)

### T6 — Schema lehnt U+007F (DEL) in TOML-Werten ab  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/tests/test_frp_toml_roundtrip.py, apps/server/tests/test_frp_input_hardening.py, apps/server/tests/test_servers_schemas.py, CHANGELOG.md
Evidenz: run.sh[quick]: 4 passed, 0 failed, 14 skipped @aa19f5f6 2026-09-30T13:12:01+02:00
Review: approve (sonnet)
Änderung: `_reject_toml_breakers` (`frp/schemas.py:20–25`) weist neben `ord(c) < 0x20` auch `0x7F` ab (gleiche
Meldung). Der strikte xfail `test_del_character_breaks_the_generated_toml` (`test_frp_toml_roundtrip.py:276`) wird
ersetzt durch einen Test, der denselben Wert (`auth_token` mit DEL) als `ValidationError` erwartet; dazu ein Fall in
`test_frp_input_hardening.py` für ein Tunnel-Feld (etwa `name`) und für `servers/schemas.py`, das denselben Helfer nutzt.
Test-Löschung: apps/server/tests/test_frp_toml_roundtrip.py::test_del_character_breaks_the_generated_toml — der strikte xfail war die Erinnerung an diesen Fix; der Ersatz erwartet die Ablehnung im Schema
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_toml_roundtrip.py tests/test_frp_input_hardening.py tests/test_servers_schemas.py
Doku: CHANGELOG (Fixed)
