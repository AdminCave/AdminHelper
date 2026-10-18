<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# extra_config-Schlüssel eines Tunnels ohne abschließenden Zeilenumbruch — Task-Ledger
Status: aktiv · Branch: feature/frp-bare-key · Review: am Ende
Spec: Roadmap R-0468
Heavy: linux-full — Boundary-Validierung von `POST`/`PUT /api/frp/tunnels` im frp-Modul (`frp/schemas.py`), deren Werte in die frpc-Config der Agents gehen; kein Datenpfad, kein Cross-Host, keine Antwortform geändert; läuft im Sammellauf
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-18: `/feature-plan --kurz R-0468`. Geprüft gegen origin/main@5855a9b5 (nach R-0411/#205): der Fund gilt unverändert. Weitere Stellen mit demselben Muster (`re.match`/`$` statt `fullmatch`/`\Z`) in der Boundary-Validierung des frp-Moduls: keine. `grep -nE 're\.(compile|match|search|fullmatch)|\.match\(' apps/server/app/modules/frp/*.py` findet außer `schemas.py:48`/`:61` nur `supervisor_status.py:72-74`, und die prüft mit `fullmatch` (`:203`, `:209`). Der Weg der FRP-Server-Konfiguration (`_check_frps_extra_config`, `schemas.py:73`) ist nicht betroffen: Er verlangt zusätzlich einen Schlüssel aus `ALLOWED_KEYS` (`:78`), und `"log.level\n"` ergibt dort schon heute 422 (Probe unten).

### T1 — `_check_extra_config` prüft den ganzen Schlüssel  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/tests/test_frp_input_hardening.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, CHANGELOG.md
Änderung: `_TOML_BARE_KEY` (`schemas.py:48`, `re.compile(r"^[A-Za-z0-9_.-]+$")`) wird in `_check_extra_config` mit `.match` angewandt (`:61`). In Python passt `$` auch vor einem abschließenden `\n`. Deshalb nehmen `FrpTunnelCreate` und `FrpTunnelUpdate` (`_v_extra`, `:224`/`:248`) den Schlüssel `"abc\n"` an. `generate_frpc_toml` schreibt ihn ungequotet (`config_generator.py:274-278`), und die frpc-Config des Hosts ist danach kein gültiges TOML mehr. Neu: `fullmatch` mit dem Muster ohne Anker (gleichwertig: `\Z` statt `$`). Die Fehlermeldung bleibt. Test zuerst rot, neben `test_extra_config_rejects_non_bare_keys` (`test_frp_input_hardening.py:136`): `test_extra_config_rejects_key_with_trailing_newline`, parametrisiert über `FrpTunnelCreate` (Helfer `_tunnel`, `:31`) und `FrpTunnelUpdate`. `extra_config={"abc\n": 1}` → `ValidationError`, die Assertion nennt den Schlüssel. API-Referenz DE+EN (`api-reference.html:141`, `POST /api/frp/tunnels`): ein Satz zur Schlüsselregel, also nur `A-Z a-z 0-9 _ . -`, sonst `422`, ebenso im `PUT`. CHANGELOG unter `### Fixed`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_input_hardening.py
Doku: docs/developer/api-reference.html + docs/en/developer/api-reference.html (`:141`) · CHANGELOG.md (Fixed)
Beweis: origin/main@5855a9b5 · im Server-Venv aus `apps/server`, `DATA_DIR` auf ein eigenes Temp-Verzeichnis: `python -c 'from app.modules.frp.schemas import FrpTunnelUpdate as U; print(U(extra_config={"abc\n": 1}).extra_config)'` → dreimal identisch `{'abc\n': 1}` (erwartet: `ValidationError`). Ebenso angenommen: `FrpTunnelCreate(…, extra_config={"abc\n": 1})`. Abgelehnt werden `"abc\r"`, `"abc\n\n"` und `"\nabc"`, ebenso `FrpServerConfigUpdate(extra_config={"log.level\n": "info"})`. `generate_frpc_toml` mit dem angenommenen Tunnel endet auf den Zeilen `abc` und ` = 1`; `tomllib.loads` → `TOMLDecodeError: Expected '=' after a key in a key/value pair` (dreimal identisch)
Orakel: contract — die Boundary verspricht einen TOML-Bare-Key (Kommentar `schemas.py:45-47`, Meldung „erlaubt: A-Z a-z 0-9 _ . -“), der Generator schreibt ihn ungequotet
Refuter: reviewer frps-supervisor T29 (Probe `FrpTunnelUpdate`, 2026-10-17); Planer 2026-10-18 auf origin/main@5855a9b5 → bestätigt, nicht widerlegt
Dedup-Key: bug:server:frp/schemas.py:bare-key-trailing-newline
HEAD: 5855a9b5
Semantik: keine Stelle in docs/ — gesucht in `docs/**/*.html` (DE+EN) nach `extra_config`, `bare key`, `TOML-Key`, `A-Z a-z`, `Zeilenumbruch`/`newline`. Am nächsten kommt docs/developer/server.html:117 — „<code>extra_config</code> (JSON) wird je Tunnel typ-erhaltend angehaengt: Strings gequotet, Bools als <code>true</code>/<code>false</code>, Zahlen roh.“ (EN `docs/en/developer/server.html:117`); über die Schlüssel sagt die Stelle nichts. Die Absicht steht nur im Code-Kommentar `schemas.py:45-47` („they must be TOML bare keys (dotted keys allowed). Anything else would break — or worse, extend — the generated config.“). Die Task trägt die Regel in die API-Referenz nach.
