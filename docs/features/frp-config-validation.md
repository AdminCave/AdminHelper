<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# FRP-Eingaben: C1-Steuerzeichen und Proxy-Plugin-Schlüssel an der Server-Grenze

Stand des Codes: `origin/main@b25c65a6`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/frp-config-validation.md`. Roadmap R-0786 (T1); T2 und T3 gehören zum Paket (Kevin 2026-10-22).

## Problem / Motivation

Der Server baut die frpc.toml eines Hosts per String-Interpolation (`apps/server/app/modules/frp/config_generator.py:247-311`);
was in die Datei darf, entscheidet die Boundary-Validierung in `apps/server/app/modules/frp/schemas.py`. Mit PR #264
(agent-hardening) prüft der Agent den Text des Servers selbst und wendet eine frpc.toml nur in der Form an, die der
Generator erzeugt (`apps/agent/internal/frpc/servertoml.go`, Branch `feature/agent-hardening`). An zwei Stellen nimmt
der Server heute Werte an, mit denen der Agent die Konfiguration des ganzen Hosts nicht anwendet:

1. **C1-Steuerzeichen (R-0786).** `_reject_toml_breakers` (`schemas.py:24-36`) lehnt Anführungszeichen, Backslash,
   CR/LF, U+0000–U+001F und U+007F ab (`:27-28`), aber nicht U+0080–U+009F. TOML 1.0 erlaubt diese Zeichen in einem
   Basic-String; der Agent ab #264 verweigert jede Zeile mit `unicode.IsControl` (`servertoml.go:67`), und das umfasst
   U+0080–U+009F. Ein Host, dessen Tunnel ein solches Zeichen in `name`, `secret_key` oder einem `extra_config`-Wert
   trägt, bekäme von diesem Agent nie eine Konfiguration. Betroffen sind alle Felder hinter `_reject_toml_breakers`:
   die Textfelder von `FrpTunnelCreate`/`FrpTunnelUpdate` (`:257`, `:260`, `:281`, `:284`), von
   `FrpServerConfigCreate`/`FrpServerConfigUpdate` (`:189`, `:195`, `:222`, `:228`), die `extra_config`-Werte (`:73`)
   und der Servername (`apps/server/app/modules/servers/schemas.py:25`), der in der frpc.toml als `user` steht.
2. **Proxy-Plugin-Schlüssel in `extra_config`.** frpc kennt neben dem Weiterleiten auf `localIP:localPort`
   Proxy-Plugins (`plugin.type`, `plugin.localPath` …). Der Server richtet keine ein; keine UI und keine Doku
   beschreibt sie. `_check_extra_config` (`schemas.py:57-76`) prüft nur die Form des Schlüssels (`_TOML_BARE_KEY`,
   `:54`), der Generator schreibt jeden Schlüssel wörtlich in den Proxy (`config_generator.py:297-309`). Der Agent ab
   #264 verweigert in einem Proxy jeden Schlüssel, dessen erstes Segment `plugin` ist, gleich in welcher Schreibweise
   (`servertoml.go:114`), weil frp die Felder ohne Rücksicht auf Groß-/Kleinschreibung zuordnet (agent-hardening,
   „Externe Integrationen“). Der Server soll dieselbe Regel an der Grenze halten, statt eine Zeile zu speichern, mit
   der der Host keine Konfiguration mehr bekommt.

Beleg (Probe an `origin/main@b25c65a6`, Server-Venv, Python 3.13.5, `DATA_DIR` in einem eigenen Temp-Verzeichnis,
dreimal identisch): `FrpTunnelCreate` nimmt U+0080, U+0085 und U+009F in `name`, `secret_key` und einem
`extra_config`-Wert an, `FrpServerConfigCreate` in `server_addr`, `ServerCreate` im `name`; `FrpTunnelCreate` und
`FrpTunnelUpdate` nehmen die `extra_config`-Schlüssel `plugin.type`, `PLUGIN.type`, `Plugin.localPath` und `plugin`
an. `generate_frpc_toml` schreibt `plugin.type = "static_file"` und `name = "a\x85b"` (mit dem echten Zeichen)
unverändert in die Datei. Die Nachbarn U+007E und U+00A0 sowie die Schlüssel `plugins.x` und
`transport.useCompression` werden angenommen und sollen es bleiben.

## Ziel & Nicht-Ziele

Ziel:
- **T1 (R-0786):** `_reject_toml_breakers` lehnt zusätzlich U+0080–U+009F ab, mit derselben Meldung wie für die
  übrigen Steuerzeichen. Danach lehnt der Server genau die Zeichen ab, die der Agent per `unicode.IsControl`
  verweigert (Kategorie `Cc`: U+0000–U+001F, U+007F–U+009F; Tab, CR und LF stehen ohnehin auf der Liste).
  `POST`/`PUT` auf `/api/frp/tunnels`, `/api/frp/server-config` und `/api/servers` antworten `422` mit dem Feld im `loc`.
- **T2 (gehört zum Paket):** Das `extra_config` eines Tunnels nimmt keinen Schlüssel, dessen erstes Segment (bis zum
  ersten `.`) ohne Rücksicht auf Groß-/Kleinschreibung `plugin` ist: `plugin`, `plugin.type`, `PLUGIN.type`,
  `Plugin.localPath` → `422`, ebenso im `PUT`. `plugins.x`, `transport.*` und alle übrigen Bare-Keys bleiben.
- **T3 [?]:** Ein schon gespeicherter Tunnel mit einem solchen Schlüssel fehlt in der frpc.toml, wie ein stcp-Tunnel
  ohne Secret (`config_generator.py:95-109`): WARNING mit Tunnelname und Schlüssel, nie dem Wert; die Zeile bleibt.
  Die übrigen Tunnel des Hosts bekommen so weiter eine Konfiguration (offene Frage 1).

Nicht-Ziele:
- Keine Datenmigration und keine Bereinigung beim Start: Bestandszeilen bleiben, wie sie sind (offene Fragen 1, 2).
- `value_allowed` (`apps/server/app/modules/frp/extra_config.py:45-59`) bleibt: es bildet die Zeichenregel des
  frps-Supervisors nach (`apps/frps/frps-supervisor.sh`, `check_config` unter `LC_ALL=C`), und die lässt Bytes ab
  0x80 durch. Die Schemas sind ab T1 strenger als der Supervisor; der Startup-Check (`apps/server/app/main.py:200-275`)
  prüft weiter nur gegen den Supervisor.
- Keine feste Allowlist der Proxy-Schlüssel (Trade-off 2).
- Die Antwortmodelle (`schemas.py:295-328`) validieren nicht und bleiben so; ein `GET` zeigt Bestandszeilen weiter.
- Andere Formen, die Server und Agent unterschiedlich beurteilen, gehören nicht zu den Zeilen dieses Pakets und
  stehen als eigene Roadmap-Kandidaten im Bericht.

## Betroffene Komponenten & Dateien

Nur `apps/server` (verify.sh-Komponente `server`):
- `apps/server/app/modules/frp/schemas.py` — `_reject_toml_breakers` (T1); neuer Validator für das `extra_config`
  eines Tunnels, registriert in `FrpTunnelCreate` (`:261`) und `FrpTunnelUpdate` (`:285`) (T2).
- `apps/server/app/modules/frp/config_generator.py` — neuer Filter neben `without_secretless_stcp`, eingehängt in
  `active_tunnels` (`:134-142`) (T3).
- `apps/server/app/modules/frp/generate_router.py` — derselbe Filter vor der 404-Prüfung von
  `GET /api/frp/generate/frpc-toml/{server_id}` (`:83-92`) und vor der Gruppierung im Bulk-ZIP (`:189`) (T3).
- Tests: `apps/server/tests/test_frp_input_hardening.py` (T1–T3), `apps/server/tests/test_frp_toml_roundtrip.py` (T1).
- Doku: `docs/developer/api-reference.html` + `docs/en/developer/api-reference.html` (T1–T3),
  `docs/developer/server.html` + `docs/en/developer/server.html` (T3), `CHANGELOG.md` (T1–T3).

## Datenmodell / API / Migrationen

- Keine Migration, kein neues Feld, keine Route, kein Route-Docstring: die OpenAPI-Beschreibung bleibt
  (`tests/test_openapi_snapshot.py` bleibt grün; T3 fährt ihn mit, weil es eine Router-Datei ändert).
- Vertrag: Eingaben, die bisher `201`/`200` bekamen, bekommen `422` (C1 in den genannten Textfeldern; ein
  plugin-Schlüssel in `extra_config` eines Tunnels). Kevin hat beides am 2026-10-22 entschieden.
- Web und Desktop-UI senden kein `extra_config` (grep über `apps/web/src` und `apps/desktop/ui/src` leer); ein
  Bearbeiten im Web bleibt bei einer Bestandszeile mit plugin-Schlüssel möglich. Ein C1-Zeichen in einem Feld, das der
  Client beim Speichern mitschickt, ergibt dort ab T1 `422`, bis das Feld neu gesetzt ist.
- Agent: keine Änderung; die Regeln stimmen ab T1/T2 mit `checkServerConfig` aus #264 überein.

## Externe Integrationen

- frp v0.69.1 (https://github.com/fatedier/frp/tree/v0.69.1): die TOML geht über JSON in die Structs
  (`pkg/config/load.go`, `pkg/util/jsonx/json_v1.go`, Zuordnung ohne Groß-/Kleinschreibung), der Proxy liest sein
  Plugin aus dem Member `plugin` (`pkg/config/v1/decode.go`); belegt in `docs/features/agent-hardening.md`
  (Branch `feature/agent-hardening`), dort mit `frpc verify -c` für `plugin.type` und `PLUGIN.type`.
- TOML 1.0 (https://toml.io/en/v1.0.0#string): ein Basic-String darf jedes Unicode-Zeichen enthalten außer `"`, `\`
  und den Steuerzeichen U+0000–U+0008, U+000A–U+001F, U+007F. C1 ist erlaubt; die strengere Regel kommt vom Agent.
- Go 1.26.9 `unicode.IsControl` und Python `unicodedata.category(c) == "Cc"` (Python 3.13.5, Unicode 15.1.0): beide
  ergeben genau U+0000–U+001F und U+007F–U+009F (Probe, 65 Zeichen).

## Trade-offs & Alternativen

1. **C1 in `_reject_toml_breakers`** (Empfehlung) statt eines eigenen Validators je Feld: eine Stelle für alle Felder,
   die in eine frpc-, frps- oder Visitor-TOML geschrieben werden; der Servername ist mit gemeint, weil er als `user`
   in der frpc.toml steht. Die Prüfung als Kategorie `Cc` statt fester Bereiche wäre gleichwertig; der feste Bereich
   `0x80 <= ord(c) <= 0x9f` neben der bestehenden Bedingung ist näher am Code und hängt an keiner Unicode-Version.
2. **plugin-Familie ablehnen** (Empfehlung, Kevin 2026-10-22) statt einer festen Allowlist der Proxy-Schlüssel: die
   Allowlist wäre strenger, kann bestehende `extra_config`-Einträge ablehnen und muss mit jeder frp-Version gepflegt
   werden. Die Regel gilt nur für Tunnel; die FRP-Server-Konfiguration hat ihre Allowlist schon (`extra_config.py:22-33`).
3. **Bestand mit plugin-Schlüssel (T3, offene Frage 1):** (B) der Generator lässt den Tunnel weg und loggt —
   **Empfehlung**: die übrigen Tunnel des Hosts bleiben, keine Migration, Muster wie `without_secretless_stcp`.
   (A) nichts tun: der Agent ab #264 wendet die Konfiguration des ganzen Hosts nicht an, bis die Zeile per `PUT`
   bereinigt ist. (C) die Schlüssel per Migration oder beim Start entfernen: eine Datenänderung, und ohne die
   Schlüssel leitet der Proxy auf `localIP:localPort` weiter — ein anderes Ziel, als gespeichert ist.
4. **Bestand mit C1 (offene Frage 2):** hinnehmen (Empfehlung) oder T3 auf C1 in den Tunnel-Feldern ausdehnen. C1 in
   Feldern der FRP-Server-Konfiguration oder im Servernamen lässt sich nicht weglassen, ohne die ganze Datei zu
   ändern; dort bleibt nur das Neusetzen per `PUT`.

## Risiken & Rollback

- Ein API-Client, der C1 oder einen plugin-Schlüssel schickt, bekommt `422` statt `201`/`200`. Gewollt.
- T3: Ein Tunnel mit plugin-Schlüssel fehlt nach dem Update in der frpc.toml des Hosts; der Agent zieht die neue
  Datei beim nächsten Sync (Config-Hash über `frpc_sync_inputs`, `apps/server/app/modules/frp/_helpers.py:102-124`; nicht am Host
  geprüft). Die Visitor-TOML für den
  Desktop behält den Visitor (sie trägt kein `extra_config`); er erreicht dann keinen Proxy, bis die Zeile bereinigt ist.
- Rollback: Revert der Task-Commits; keine Daten werden geändert.

## Doku-Impact

API-Referenz DE+EN: C1 bei `POST /api/servers`, `POST /api/frp/server-config`, `POST /api/frp/tunnels` (T1), die
plugin-Regel bei `POST /api/frp/tunnels` (T2), Generate-Routen (T3). Server-Entwicklerseite DE+EN: der Generator lässt
einen Tunnel mit plugin-Schlüssel weg (T3). CHANGELOG je Task.

## Offene Fragen

1. **T3 [?] — Bestand mit plugin-Schlüssel:** einen gespeicherten Tunnel mit einem `extra_config`-Schlüssel der
   plugin-Familie aus der frpc.toml weglassen (B, Empfehlung), nichts tun (A) oder die Schlüssel entfernen (C)?
   Siehe Trade-off 3. Betrifft nur T3; T1 und T2 hängen nicht daran.
2. **C1 in gespeicherten Zeilen** hinnehmen (Empfehlung: selten, der Agent nennt Zeile und Schlüssel, Abhilfe per
   `PUT`) oder T3 auf C1 in den Tunnel-Feldern ausdehnen? Keine eigene Task.
3. **Reihenfolge:** T2 ersetzt einen Satz, den PR #264 in die API-Referenz (`:141`) und ins CHANGELOG schreibt; T2
   und T3 bauen erst, wenn #264 auf `main` ist und `origin/main` in den Branch gemergt wurde. T1 hängt nicht daran.
