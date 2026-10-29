<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# FRP: extra_config eines Tunnels nur in der Form, die der Agent annimmt — Task-Ledger
Status: erledigt · Branch: feature/frp-extra-config-keys · Review: am Ende
Spec: docs/features/frp-extra-config-keys.md
Heavy: linux-full — Server-API (`POST`/`PUT /api/frp/tunnels`) und der frpc-Generator für gespeicherte Altwerte. Kein `scenario`: für jeden Tunnel, dessen `extra_config` die neuen Regeln erfüllt, bleibt die `frpc.toml` byte-gleich; kein Agent-, PKI- oder Install-Pfad. Kein `windows`
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — API: extra_config-Schlüssel und -Zahlen in der Form des Agents  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/tests/test_frp_input_hardening.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @877f7c9a 2026-10-29T05:32:06+01:00
Review: am Ende (Branch-Review)
Änderung: `_TOML_BARE_KEY` (`schemas.py:59`) nimmt nur Segmente `[A-Za-z0-9_-]+` mit `.` dazwischen an (wie `serverKey` im Agent): `.a`, `a.`, `a..b` → 422. `_check_extra_config` (`:62`) begrenzt Ganzzahlen (nicht `bool`) auf -2^63 … 2^63-1. `_check_tunnel_extra_config` (`:94`) lehnt einen Schlüssel ab, der klein geschrieben mit einem Generator-Schlüssel des Proxys (`name`, `type`, `localIP`, `localPort`, `secretKey`, `allowUsers`, `customDomains`, `config_generator.py:370-385`) oder mit einem anderen `extra_config`-Schlüssel zusammenfällt oder ein Präfix davon ist bzw. hat (Regel von `keyTable.add`, `apps/agent/internal/frpc/servertoml.go`). Fehler nennen den Schlüssel, nie den Wert. Tests in `test_frp_input_hardening.py` neben `test_extra_config_rejects_non_bare_keys` (`:216`) und den Routentests (`:694`): (a) Modell `FrpTunnelCreate`/`FrpTunnelUpdate` lehnt `.a`, `a.`, `a..b`, `2**63`, `-2**63-1`, `localport`, `Type`, `localIP.x`, `{"foo": 1, "FOO": 2}`, `{"a": 1, "a.b": 2}` ab; (b) nimmt `2**63-1`, `-2**63`, `transport.useEncryption`, `bandwidthLimit` an; (c) Routen `POST`/`PUT` → 422 an `extra_config`, nichts gespeichert; (d) die frps-`extra_config` (`FrpServerConfigCreate`) nimmt ihre erlaubten Schlüssel weiter an. Zuerst rot: (a), (c).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_input_hardening.py tests/test_frp_tunnels.py tests/test_openapi_snapshot.py
Doku: docs/developer/api-reference.html + docs/en/developer/api-reference.html (`POST /api/frp/tunnels`, Satz zu `extra_config`-Schlüsseln: Segmente aus `A-Z a-z 0-9 _ -`, getrennt durch `.`; kein Schlüssel, der ohne Rücksicht auf Groß-/Kleinschreibung einem Feld des Proxys oder einem anderen Schlüssel gleicht oder Präfix davon ist; Ganzzahlen 64 Bit; sonst `422`, ebenso im `PUT`) · CHANGELOG.md (Fixed, umlautfrei)

### T2 — Generator: gespeicherte extra_config mit solchen Werten lässt nur ihren Tunnel weg  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/config_generator.py, apps/server/tests/test_frp_input_hardening.py, docs/developer/server.html, docs/en/developer/server.html, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @96733b05 2026-10-29T05:34:39+01:00
Review: am Ende (Branch-Review)
Änderung: `without_refused_extra_config` (`config_generator.py:139`) prüft außer jedem Schlüssel einzeln (`_api_takes`, `:131`) die ganze `extra_config` wie die API (`_check_tunnel_extra_config`), damit Kollisionen zweier Schlüssel auffallen; ein abgelehnter Tunnel fällt mit Warnung weg, die die Schlüssel nennt (repr, eine Zeile), nie Werte. Tests im Generator-Abschnitt von `test_frp_input_hardening.py` (`_stored_tunnel`, `_generator_warnings`): gespeicherte Zeilen mit `.a`, `2**63`, `localport`, `{"foo": 1, "FOO": 2}` neben einem sauberen Tunnel → genau ein `[[proxies]]`, Text gleich dem nur mit dem sauberen Tunnel, eine Warnung je weggelassenem Tunnel mit Schlüssel und ohne Wert. Zuerst rot: alle vier.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_input_hardening.py tests/test_config_generator.py tests/test_frp_provision_sync.py
Doku: docs/developer/server.html + docs/en/developer/server.html (`:119`, welche gespeicherte `extra_config` der Generator weglässt: auch eine, die die heutige Schlüssel- und Zahlenprüfung nicht besteht) · CHANGELOG.md (Fixed, umlautfrei)
Abhängt von: T1

### T3 — Funde der Abschlussprüfung: Kollisionsprüfung linear, Generator-Schlüssel gepinnt  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/tests/test_frp_input_hardening.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @9abc2f18 2026-10-29T06:06:06+01:00
Review: am Ende (Branch-Review)
Änderung: Die Kollisionsprüfung in `_check_tunnel_extra_config` vergleicht jeden Schlüssel mit allen bisherigen und wächst quadratisch (reviewer und security, branch: 8000 Schlüssel ≈ 10 s im Event-Loop). Neu wie `keyTable.add` im Agent: ein dict Pfad → „ist Schlüssel“; je Schlüssel nur der Pfad selbst und seine Segment-Präfixe nachschlagen, danach die Präfixe als Tabelle eintragen, O(n·Tiefe). Der Fehlertext zu ungültigen Schlüsseln nennt das Verbot leerer Segmente. Tests: (a) 20000 verschiedene Schlüssel werden in unter 1 s angenommen; (b) die Schlüssel eines vom Generator geschriebenen `[[proxies]]` (stcp und https) sind genau `_GENERATOR_PROXY_KEYS` bzw. eine Teilmenge davon, damit eine neue Generator-Zeile die Liste nicht still überholt. Die bisherigen Fälle bleiben grün. Gegenprobe: (a) mit der alten Schleife rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_input_hardening.py
Doku: keine (Verhalten unverändert)
Abhängt von: T2

### T4 — Kollisionsprüfung auch in der Schlüssellänge linear  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/tests/test_frp_input_hardening.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @5f8f6182 2026-10-29T06:16:41+01:00
Review: am Ende (Branch-Review)
Änderung: T3 baut für jeden Schlüssel alle Segment-Präfixe als neue Strings und behält sie: quadratisch in der Länge eines einzelnen Schlüssels, in Zeit und Speicher (Abschlussprüfung Runde 2: ein 20-KB-Schlüssel ≈ 1 s und 128 MB). Neu: ein Trie aus verschachtelten dicts je Segment; ein Knoten ist ein Schlüssel (sein Name) oder eine Tabelle; jeder Schlüssel läuft seine Segmente einmal ab. Die Meldung bei einer Kollision mit einer Tabelle nennt einen Schlüssel dieser Tabelle statt eines Platzhalters. Test: ein Schlüssel mit 20000 Segmenten wird in unter 1 s angenommen. Gegenprobe: mit T3 rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_input_hardening.py
Doku: keine (Verhalten unverändert)
Abhängt von: T3

## Entscheidungen
