<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server-Härtung: Startabgleich-Log, Schlüsseldateien, Redis-URL im Log, Surrogate in Request-Bodies, Quelltypen des internen Eingangs

Stand des Codes: `origin/main@b1432223`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/server-hardening.md`. Härtungs-Paket der Komponente `server` (Kevin 2026-10-22).

## Problem / Motivation

1. **Startabgleich der `frps.toml` loggt den ganzen Traceback.** `_ensure_frps_config`
   (`apps/server/app/main.py:314-339`) fasst `get_frp_config(db)`, `remove_frps_config()` und `write_frps_config()` in
   einen `try` und loggt jeden Fehler mit `logger.exception` (`:339`). Die Startprüfungen direkt davor loggen einen
   Fehler nur mit seinem Typ (`_check_frps_server_configs`, `:277-311`, `:287`, `:306-311`; Docstring `:278-282`).
   Dieselbe Konvention gilt in `apps/server/app/modules/frp/docker_manager.py:57-86`.

2. **Schlüssel- und Setup-Dateien entstehen nicht von Anfang an mit 0600.** `.secret_key`
   (`apps/server/app/core/config.py:33-34`), `.bootstrap_token` und `.bootstrap_setup` (`main.py:136-148`) werden mit
   `write_text` angelegt (Modus nach umask) und erst danach per `chmod(0o600)` eingeschränkt; in `main.py` verwirft
   `except OSError: pass` einen Fehler beim `chmod` (`:139-140`, `:147-148`), `_purge_bootstrap_files` ebenso einen
   Fehler beim Löschen (`:123-129`). `write_frps_config` legt seine Datei dagegen mit `mkstemp` an (0600 ab der
   Erzeugung, unabhängig von der umask), schreibt, `fsync`t und tauscht sie mit `os.replace` ein
   (`docker_manager.py:26-54`, Kommentar `:37-39`). Die Bootstrap-Route loggt einen Löschfehler schon
   (`apps/server/app/modules/users/auth_router.py:345-350`).

3. **Die Redis-URL steht vollständig im Log.** `get_backend` loggt `REDIS_URL` ganz (`apps/server/app/core/rate_limit.py:147`,
   `:152-158`), dazu den Text des Fehlers. Eine Redis-URL kann Zugangsdaten tragen, im Benutzer-Teil
   (`redis://:<pw>@host`) oder als Query-Parameter (redis-py 8.1.0 reicht unbekannte Query-Namen als Verbindungsparameter
   durch, `redis/connection.py:2344-2357`). Für ausgehende Ziele gilt im Projekt, im Log nur den Host zu nennen
   (`apps/monitoring/app/alerter.py:542-549`, `_log_host`).

4. **Ein einzelnes Surrogat in einem Request-Body ergibt 500 oder eine Zeile, die keine Antwort mehr ausgeben kann.**
   `RequestModel` (`apps/server/app/core/bounds.py:72-110`), die Basisklasse jedes Request-Schemas, lehnt ein NUL-Byte
   in jedem String des Bodies ab, weil Postgres es nicht speichert. Ein einzelnes Surrogat (U+D800 bis U+DFFF; JSON
   schreibt es nur als Escape, `\ud800`) hat keine UTF-8-Form und scheitert genauso, wird aber nur in den Feldern
   abgelehnt, die in frp-Configs landen (`apps/server/app/modules/frp/schemas.py:29-31`). Probe (origin/main@b1432223,
   dreimal identisch): `ServerCreate` nimmt `hostname`, `notes` und `tags` mit `"\ud800"` an, `FrpTunnelCreate`
   `protocol`, `connection_id` und `tags`, `ConnectionCreate` `tags`. Folgen (Code-Lesung und Probe der Bausteine,
   nicht gegen Postgres gefahren):
   - Text-Spalten: psycopg 3.3.6 kann den Wert nicht binden (`UnicodeEncodeError`), die Anfrage endet mit 500.
   - Tags: `json.dumps` schreibt das Surrogat als ASCII-Escape (`apps/server/app/modules/servers/router.py:114`,
     `apps/server/app/modules/frp/tunnel_router.py:121`, `apps/server/app/modules/connections/models.py:118`), der
     `INSERT` gelingt und wird committet (`servers/router.py:118`). Danach scheitert jede Antwort, die die Zeile ausgibt
     (`to_dict` liest `json.loads`, `JSONResponse` kann das Surrogat nicht kodieren; Probe FastAPI 0.141.1: 500), also
     auch die Liste (`servers/router.py:89-99`, `connections/router.py:94-106`), bis die Zeile per SQL repariert ist.
   Ein 422 mit einem Surrogat in der Eingabe schreibt der Server schon als ASCII-Escape (`main.py:409-420`).

5. **Zwei Quelltypen des Servers lassen sich über den internen Event-Eingang belegen.** Die Startprüfung meldet
   abgelehnte Felder einmal je Feldmenge und erkennt „schon gemeldet“ an einer `notification`-Zeile mit
   `source_type="frp_config"` und `source_id="<config-id>:<felder>"` (`main.py:258-265`); der Supervisor-Watch erkennt
   gemeldete Ereignisse und sein Stundenlimit an Zeilen mit `source_type="frps"`
   (`apps/server/app/modules/frp/supervisor_watch.py:42`, `:145-151`). `POST /api/internal/events`
   (`apps/server/app/modules/notifications/router.py:182-217`) nimmt jeden `source_type` an und schreibt ihn in die
   Zeilen (`apps/server/app/modules/notifications/service.py:216-225`). Eine Meldung über den Eingang kann so als
   Meldung des Servers zählen. Der dokumentierte Erzeuger, der Monitoring-Dienst, sendet nur `source_type="server"`
   (`apps/monitoring/app/alerter.py:406`, `apps/monitoring/app/alert_bundle.py:509`; Doku
   `docs/developer/api-reference.html:208`: „Event-Ingress für den Monitoring→Hub-Pfad“).

## Ziel & Nicht-Ziele

Ziel:
- Scheitert der Startabgleich der `frps.toml`, loggt der Server eine WARNING mit dem Typ des Fehlers, ohne Text und ohne
  Traceback (T1).
- `.secret_key`, `.bootstrap_token` und `.bootstrap_setup` sind ab ihrer Erzeugung 0600, unabhängig von der umask, und
  werden atomar eingetauscht; es gibt kein `chmod` mehr, dessen Fehler verloren gehen könnte. Ein Fehler beim Entfernen
  der Bootstrap-Dateien steht mit Dateiname und Fehlertyp im Log (T2, T3).
- Die Log-Zeilen zum Redis-Backend des Rate-Limits nennen von `REDIS_URL` nur Schema, Host und Port, vom Fehler nur
  den Typ (T4).
- Ein einzelnes Surrogat in irgendeinem String eines Request-Bodies (Wert oder Schlüssel, beliebig tief) ergibt 422
  an seiner Stelle, wie ein NUL-Byte; nichts wird gespeichert (T5).
- `POST /api/internal/events` lehnt `source_type` `frp_config` und `frps` mit 422 ab (T6, wartet auf Kevin, offene
  Frage 1).

Nicht-Ziele (YAGNI):
- Die Folge `{{` in Tunnel- und Servernamen lehnt der Server schon ab (`frp/schemas.py:34-35`, genutzt für Tunnel-
  `name` `:257`, `:281` und Servername `apps/server/app/modules/servers/schemas.py:25`; Test
  `apps/server/tests/test_frp_input_hardening.py:91`, seit `9dd48fe8`); alle Werte der Visitor-TOML
  (`apps/server/app/modules/frp/config_generator.py:314-358`) sind damit gedeckt. Keine Task.
- Keine Reparatur oder Migration schon gespeicherter Zeilen mit Surrogat in Tags (offene Frage 3).
- Query- und Pfad-Parameter: nicht Teil von T5 (die NUL-Prüfung dort macht `NulByteMiddleware`; ob ein Surrogat dort
  ankommt, ist nicht geprüft).
- Andere `logger.exception`-Stellen bleiben (`main.py:381`, `apps/server/app/modules/frp/config_router.py:86`, `:176`,
  `docker_manager.py:99`); `config_router` loggt nur das Dateischreiben nach `db.refresh`, ohne DB-Zugriff im `try`.
- `write_frps_config` bleibt, wie es ist (eigene Temp-Präfixe und Aufräumen beim Start); kein gemeinsamer Helfer über
  `config.py` hinaus.
- Keine Prüfung des tatsächlichen Dateimodus nach dem Schreiben (ein Dateisystem ohne Unix-Rechte gibt weiter, was es
  will) und kein Aufräumen von Temp-Dateien eines abgebrochenen Schreibens in `DATA_DIR`.
- Unverändert bleibt das Verhalten, wenn mehrere Prozesse gleichzeitig den ersten Schlüssel oder Bootstrap-Token
  erzeugen (offene Frage 4).

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | server | `apps/server/app/main.py`, `apps/server/tests/test_frp_docker_manager.py`, `CHANGELOG.md` |
| T2 | server | `apps/server/app/core/config.py`, `apps/server/tests/test_secret_key_file.py` (neu), `CHANGELOG.md` |
| T3 | server | `apps/server/app/main.py`, `apps/server/tests/test_bootstrap.py`, `CHANGELOG.md` |
| T4 | server | `apps/server/app/core/rate_limit.py`, `apps/server/tests/test_rate_limit.py`, `CHANGELOG.md` |
| T5 | server | `apps/server/app/core/bounds.py`, `apps/server/tests/test_nul_body.py`, `apps/server/tests/test_text_bounds.py`, `apps/server/tests/test_validation_response.py`, `apps/server/tests/test_frp_extra_config.py`, `docs/developer/server.html`, `docs/en/developer/server.html`, `CHANGELOG.md` |
| T6 | server | `apps/server/app/modules/notifications/router.py`, `apps/server/tests/test_notifications.py`, `docs/developer/api-reference.html`, `docs/en/developer/api-reference.html`, `CHANGELOG.md` |

Auf `scripts/dev/review-risk.txt` stehen `apps/server/app/core/rate_limit.py` (T4) und
`apps/server/app/modules/notifications/*` (T6); T2, T3 und T5 bekommen `security` ebenfalls (Schlüsseldateien;
Basisklasse aller Request-Schemas, deren `schemas.py` auf der Liste stehen).

## Datenmodell / API / Migrationen

- Keine Migration, keine neue Spalte, keine neue Route.
- OpenAPI unverändert: T5 ändert einen `model_validator` der Basisklasse (kein Schema-Feld; `RequestModel` ist keine
  Komponente des Schemas, sein Docstring steht nicht in `apps/server/tests/openapi.snapshot.json`); T6 prüft im
  Handler. `test_openapi_snapshot.py` steht im `Verify:` von T5 und T6.
- Verhalten: T5 — ein Body mit einem einzelnen Surrogat bekommt 422 statt 500 (Text-Spalten) bzw. statt einer
  gespeicherten Zeile, deren Ausgabe danach 500 ergibt (Tags); eine Eingabe, die heute gelingt und brauchbar bleibt,
  gibt es dabei nicht (jede Antwort und jede Spalte braucht UTF-8). T6 — zwei `source_type`-Werte am internen Eingang
  ergeben 422 statt 202 (offene Frage 1). Kein Vertrags-Drift zu Web, Desktop oder Agent: sie senden keine Surrogate
  (JSON aus wohlgeformten Strings) und nutzen `/api/internal/events` nicht; das Monitoring sendet `server`.

## Externe Integrationen

- Python `tempfile.mkstemp` (docs.python.org/3/library/tempfile.html): „The file is readable and writable only by the
  creating user ID“, angelegt mit `O_EXCL`; `os.replace` (docs.python.org/3/library/os.html#os.replace): atomar auf
  POSIX, ersetzt eine vorhandene Datei. Gleiche Form wie `docker_manager.py:40-47`.
- redis-py 8.1.0 `parse_url` (im Dev-Venv gelesen): Benutzer und Passwort aus dem Netloc, unbekannte Query-Namen als
  Verbindungsparameter. Python `urllib.parse.urlsplit`: `hostname`, `port` (ein ungültiger Port wirft `ValueError`).
- psycopg 3.3.6 / SQLAlchemy 2.0.54 / FastAPI 0.141.1 (Dev-Venv): Probe der Bausteine in Problem 4.

## Trade-offs & Alternativen

1. **Wo die Surrogat-Regel sitzt (T5).** (a) In `RequestModel` neben dem NUL-Byte — **Empfehlung, so geplant**:
   dieselbe Ursache (Postgres und JSON-Antwort brauchen UTF-8), derselbe Ort, keine Klasse kann die Regel auf einem
   neuen Feld vergessen; erfasst auch Verbindungs-Tags und Extra-Felder von Verbindungen. Kosten: zwei bestehende
   Tests ändern ihre Erwartung (T5, „Änderung“). (b) Je Feld (`protocol`, `connection_id`, `hostname`, `notes`,
   `os_type`, `_validate_tags`): keine Testanpassung, aber Verbindungs-Tags und künftige Felder bleiben offen.
   Die Meldung lautet wie heute in `frp/schemas.py:31`, damit Prüfungen auf „surrogate“ grün bleiben.
2. **Dateien schreiben (T2, T3).** (a) `mkstemp` im Zielverzeichnis, schreiben, `fsync`, `os.replace` — **Empfehlung**:
   0600 ab der Erzeugung, atomar, ersetzt einen Symlink am Zielnamen statt durch ihn zu schreiben, dieselbe Form wie
   `write_frps_config`. (b) `os.open(O_CREAT|O_EXCL|O_WRONLY, 0o600)` direkt am Zielnamen: braucht für die
   Bootstrap-Dateien (je Start neu) erst ein `unlink`, und ein zweiter Prozess könnte eine noch leere `.secret_key`
   lesen. Der Helfer `write_private_file` steht in `config.py`, weil `config.py` ihn beim Import braucht und nichts aus
   `app.modules` importieren kann.
3. **Was vom Redis-Ziel im Log steht (T4).** Schema, Host und Port (bei `unix://` der Socket-Pfad), sonst `?` —
   **Empfehlung**, wie `_log_host`. Alternative: URL mit `***` statt Passwort — ließe Query-Parameter stehen. Vom Fehler
   nur der Typ (Konvention `main.py:287`); Alternative `str(e)` gäbe „Connection refused“ mehr, kann aber Teile der URL
   tragen, wenn sie nicht parsebar ist.
4. **Interner Eingang (T6).** (a) `source_type` `frp_config` und `frps` → 422 im Handler — **Empfehlung**: kleinster
   Eingriff, OpenAPI gleich, kein dokumentierter Erzeuger betroffen. (b) Nur `server` und `null` zulassen: strenger,
   würde einen künftigen Quelltyp des Monitorings still abweisen. (c) „Vom Server gemeldet“ als eigene Spalte:
   Migration. (d) Lassen, wie es ist.

## Risiken & Rollback

- T5 wirkt auf jede Route mit Request-Body. Betroffen sind nur Eingaben mit einem einzelnen Surrogat, die heute schon
  scheitern; `test_nul_schemas.py` stellt sicher, dass jedes Request-Schema `RequestModel` erbt. Die schwere Suite
  (`Heavy:`) fährt echte Bodies (Web-E2E, Monitoring→Server).
- T2: `_resolve_secret_key` läuft beim Import von `app.core.config`; ein Fehler beim Schreiben bricht den Start ab,
  wie heute `write_text`.
- T3: Scheitert das Schreiben eines Bootstrap-Files, bricht der Start ab wie heute.
- Rollback: jede Task ein eigener Commit ohne Datenänderung; Revert genügt.

## Doku-Impact

T5: `docs/developer/server.html:46` (DE+EN) — `RequestModel` lehnt ein NUL-Byte oder ein einzelnes Surrogat in jedem
String des Bodies ab; CHANGELOG (Fixed). T6: `docs/developer/api-reference.html:208` (DE+EN) — die zwei Quelltypen;
CHANGELOG (Changed). T1–T4: CHANGELOG (Changed), `docs/` unverändert (`docs/admin/installation.html:165` nennt
`.bootstrap_setup` schon mit 0600).

## Offene Fragen

1. **T6: Der interne Eingang lehnt `source_type` `frp_config` und `frps` mit 422 ab?** Empfehlung ja (Trade-off 4a).
   Es ändert das Verhalten einer internen Route für zwei Werte; deshalb steht T6 auf `[?]`.
2. **T5: Regel in der Basisklasse statt je Feld?** Empfehlung Basisklasse (Trade-off 1a); gebaut wird sie, bei „je
   Feld“ wird T5 umgeschrieben.
3. **Schon gespeicherte Tags mit Surrogat:** keine Reparatur (Empfehlung; eine solche Zeile hätte die Liste schon
   sichtbar unbrauchbar gemacht). Keine Task.
4. **Mehrere Prozesse beim ersten Start** (Web-Worker und `scheduler` erzeugen ohne `SECRET_KEY` je einen eigenen
   Schlüssel; Bootstrap-Hash und Setup-Datei können mit `WEB_CONCURRENCY>1` von verschiedenen Workern stammen):
   vorbestehend, eigene Roadmap-Zeilen (Empfehlung), nicht in diesem Paket.
