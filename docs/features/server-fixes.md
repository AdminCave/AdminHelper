<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server-Fixes: Intervall-Hooks, SSE-Verbindung, Hook-Beschreibung, Monitoring-Proxy, Tunnel-Anlage und -Ports, Passwort in Test-Ausgaben

Stand des Codes: `origin/main@b1432223`. Für `apps/server/app/modules/hooks/*` und `apps/server/tests/test_hooks.py`
gilt der Stand von PR #254 (`origin/feature/hooks-followups@d9f9db22`), der vor dem Bau gemergt wird; alle übrigen
`datei:zeile` beziehen sich auf `origin/main@b1432223`. Ledger: `tasks/server-fixes.md`. Roadmap: R-0591 (T1),
R-0617 (T2), R-0651 (T3), R-0618 (T4), R-0655 (T5), R-0656 (T6), R-0560 (T7, T8), R-0570 (T9).

## Problem / Motivation

1. **Passwort der Test-Datenbank in der Ausgabe der Server-Tests (R-0591).** Scheitert die Verbindung zur
   Test-Datenbank ungefangen, etwa in `pg_engine` (`apps/server/tests/conftest.py:234-279`, `create_all` in `:253`),
   druckt pytest die Argumente des letzten Rahmens einer Traceback-Kette: `conninfo` und `kwargs` von psycopgs
   `connect` samt `password=…`; mit `-l` zusätzlich die Locals der SQLAlchemy-Rahmen (`cparams`) und von psycopg
   (`attempt`, `params`) sowie `env_url` in `pg_engine`. Das landet im Terminal, im JUnit-XML von `run.sh` und in den
   Transkripten der Sessions. Seit R-0529 ist das lokale Test-Passwort ein eigenes Geheimnis. Beleg (Probe im Scratch,
   pytest aus dem Haupt-Venv, Platzhalter-Passwort, Server `127.0.0.1:1`, Session-Fixture wie `pg_engine`): ohne `-l`
   steht das Passwort in `conninfo` und `kwargs` beider Ausnahmen der Kette, mit `-l` zusätzlich in `cparams`,
   `attempt`, `params` und im Local `env_url`; mit `--tb=short` nirgends. Die Suite kennt das Problem an einer Stelle:
   `_AppEngineGate.__call__` versteckt seinen Rahmen, weil dessen Argumente „the connect parameters, password
   included“ sind (`conftest.py:143-148`), und `tests/test_conftest_app_engine.py:144-148` prüft, dass kein
   Platzhalter der URL in der Ausgabe steht.

2. **Schedule-Hooks mit Intervall laufen nie (R-0617).** `reconcile_scheduled_hooks` läuft alle 30 s
   (`schedule_hook_reconcile`, `scheduler.py:245-254`) und ruft für jeden aktiven Hook `add_hook` (`:204`), das mit
   einem neu gebauten Trigger und `replace_existing=True` registriert (`:144-153`). Ein neuer `IntervalTrigger` setzt
   den nächsten Lauf auf jetzt + Intervall; bei Intervallen ab `1m` (`INTERVAL_MAP`, `:33-42`) wird er also alle 30 s
   nach hinten geschoben und nie erreicht. Cron-Trigger rechnen vom Kalender aus und sind nicht betroffen. Beleg
   (Probe, APScheduler 3.11.3 im Haupt-Venv, gepinnt ist 3.11.2): zweimal `add_job(..., IntervalTrigger(minutes=1),
   replace_existing=True)` im Abstand von 1,2 s verschiebt `next_run_time` um 1,2 s, mit `CronTrigger.from_crontab`
   bleibt sie gleich; dreimal identisch. Soll: `docs/developer/server.html:161` — „Trigger-Typen: vordefinierte
   Intervalle (1m, 5m, 15m, 30m, 1h, 6h, 12h, 24h) oder Cron (5 Felder)“, `:162` — „gleicht die Schedule-Hooks alle
   30&nbsp;s aus der DB ab (<code>reconcile_scheduled_hooks()</code> — neu/ge&auml;ndert/gel&ouml;scht)“.

3. **Hook-Beschreibung lässt sich nicht löschen (R-0651).** Der Web-Dialog schickt eine geleerte Beschreibung als
   `null` (`apps/web/src/modals/HookModal.svelte:88`, `description: description.trim() || null`), `update_hook` liest
   `None` als „nicht gesendet“ (`apps/server/app/modules/hooks/router.py:269-270`). Die Antwort ist 200, der Dialog
   meldet „gespeichert“, die alte Beschreibung bleibt. Die Spalte ist nullable (`hooks/models.py:16`). Vorbild für
   „gesendet“ statt „nicht `None`“: `update_server_config` mit `model_fields_set` (`apps/server/app/modules/frp/
   config_router.py:121`) und `update_tunnel` (`tunnel_router.py:172`).

4. **Der SSE-Stream hält eine Pool-Verbindung (R-0618).** `notifications_stream_router` hängt mit
   `dependencies=_access` ein (`apps/server/app/main.py:466`, `:485`). `require_scope` zieht `get_db`
   (`apps/server/app/core/identity.py:240-244`) und fragt bei einem Zertifikat mit Access-Scope das Register ab
   (`:249-252`, `_refused` → `_is_revoked`). `get_db` ist eine Dependency mit `yield`; FastAPI führt ihren Exit-Code
   nach dem Senden der Antwort aus (Doku unten), bei einer `StreamingResponse` also erst, wenn der Stream endet. Jeder
   offene Stream eines Desktops mit Zertifikat hält damit eine Verbindung „idle in transaction“, bis zum Abmelden.
   Beleg (Probe, FastAPI 0.141.1 im Haupt-Venv, gepinnt ist 0.138.0): eine Router-Dependency mit `yield` ist während
   aller Frames eines `StreamingResponse` offen und erst danach zu, dreimal identisch. `authenticate_stream_user`
   (`apps/server/app/modules/notifications/stream.py:64-90`) nutzt dagegen bewusst eine kurze Session; der Docstring
   nennt genau diesen Grund. Soll: `docs/developer/server.html:193` — „Der Stream-Handler ist <em>async</em> und hält
   keine DB-Connection über seine gesamte Lebensdauer … er authentifiziert per kurzlebiger Session beim Connect“.

5. **Monitoring-Proxy: Netzwerkfehler werden 500 (R-0655).** `proxy_agent_report` und `proxy_to_monitoring`
   (`apps/server/app/modules/monitoring_proxy/router.py:86-93`, `:141-150`) rufen `_client.post`/`_client.request`
   ohne `try`; einen globalen Handler für httpx-Fehler gibt es nicht (`app/main.py:423` registriert nur
   `RequestValidationError`). Startet der Monitoring-Dienst neu oder antwortet er nicht binnen 30 s (`:43`), endet
   jeder Agent-Report (je Server einer pro Minute) und jeder Admin-Aufruf als 500 mit Traceback im Log.

6. **Tunnel anlegen: `flush` vor dem `try`, `connection_id` ungeprüft (R-0656).** `create_tunnel` ruft
   `db.flush()` vor dem `try` (`apps/server/app/modules/frp/tunnel_router.py:123-124`), ebenso
   `_attach_auto_connection` mit eigenem `flush` (`:126-127`, `:55-63`); Unique- und FK-Fehler fallen damit außerhalb
   von `except IntegrityError` (`:129-138`), dessen Race-Zweig toter Code ist. `update_tunnel` hat dasselbe Muster für
   die automatische Verbindung (`:236-237` vor `:239-245`). `connection_id` (`frp/schemas.py:249`, `:273`) wird nicht
   auf Existenz geprüft, der FK ist nicht deferrable (`frp/models.py:99-101`). Folgen: unbekannte `connection_id`
   beim Anlegen 500; beim Ändern 409 „Proxy-Name oder Visitor-Port ist bereits belegt“ (falsche Meldung); ein
   verlorenes Rennen um Namen oder Visitor-Port beim Anlegen 500 statt 409. Vorbild für die Prüfung:
   `_reject_unknown_server` (`apps/server/app/modules/connections/router.py:66-91`).

7. **`local_port` eines Tunnels ist kein Port (R-0560).** `local_port` ist in `FrpTunnelCreate` und
   `FrpTunnelUpdate` ein `IntColumn` (`frp/schemas.py:245`, `:269`; `-2147483648` bis `2147483647`,
   `app/core/bounds.py:42`). Der Generator schreibt den Wert ungeprüft als `localPort` in die `frpc.toml` des Agents
   (`frp/config_generator.py:284`); frpc nimmt dort nur 0 bis 65535 an und lehnt sonst die ganze Konfiguration ab
   (frp v0.69.1, `ValidatePort`, Doku unten) — alle Tunnel dieses Hosts fallen dann aus. Der Desktop liest die
   Tunnel-Liste mit `local_port: u16` (`apps/desktop/src-tauri/src/tunnel.rs:23`, `:60`). Der Tunnel-Dialog des
   Desktops hat kein Maximum (`apps/desktop/ui/src/components/infra/TunnelModal.svelte:210-219`,
   `apps/desktop/ui/src/lib/models/frpTunnel.ts:99` prüft nur `<= 0`), ein Tippfehler wie `33890` wird also
   gespeichert. Ein `PUT` mit `"local_port": null` setzt die NOT-NULL-Spalte (`frp/models.py:95`) auf `None`, der
   Commit scheitert und meldet 409 „Proxy-Name oder Visitor-Port ist bereits belegt“.

8. **Automatische Verbindung mit ungültigem Visitor-Port (R-0570).** Seit R-0533 nimmt das Schema nur 1–65535 an,
   ältere Zeilen behalten ihren Wert. `update_tunnel` ersetzt einen gespeicherten Port nur, wenn er leer oder von
   einem anderen STCP-Tunnel belegt ist (`tunnel_router.py:217-226`); einen Wert wie `70000` oder `-1` behält er. Ein
   `PUT` ohne `visitor_port` mit `auto_create_connection` legt dann über `create_auto_connection`
   (`frp/_helpers.py:33-46`, `port=tunnel.visitor_port` in `:42`) eine Verbindung `127.0.0.1:70000` an. Der Generator
   lässt den Visitor eines solchen Tunnels weg (`without_unbindable_visitor`, `config_generator.py:112-131`), die
   Verbindung zeigt also auf einen Port, an dem nie ein Visitor lauscht. Erreichbar nur über die API: Web- und
   Desktop-Dialog schicken den gespeicherten Port mit und bekommen 422.

## Ziel & Nicht-Ziele

Ziel:
- T1: Kein Passwort aus `DATABASE_URL` steht in einem Test-Report (Terminal, JUnit), mit und ohne `-l`.
- T2: Ein Intervall-Hook läuft im Takt seines Intervalls; der Abgleich lässt einen unveränderten Job samt nächstem
  Lauf stehen und registriert nur neu, wenn sich der Trigger geändert hat.
- T3: `"description": null` im `PUT /api/hooks/{id}` löscht die Beschreibung; ein fehlendes Feld lässt sie stehen.
- T4: Der SSE-Stream hält keine Session aus `get_db`; die Scope-Prüfung läuft auf der kurzen Session von
  `authenticate_stream_user`, in derselben Reihenfolge wie heute (Scope vor Token).
- T5: Ein Timeout zum Monitoring-Dienst wird 504, jeder andere httpx-Fehler 502, in beiden Proxy-Routen; geloggt wird
  eine WARNING mit der Route und dem Exception-Typ, nichts von URL, Header oder Body.
- T6: Unbekannte `connection_id` → 422 (`loc` `["body", "connection_id"]`) beim Anlegen und Ändern; jeder `flush`
  steht im `try`, ein verlorenes Rennen wird 409.
- T7: `local_port` nimmt nur 1–65535 an, sonst 422 (`loc` `["body", "local_port"]`), auch `null` im `PUT`.
- T8: Ein schon gespeicherter `local_port` außerhalb 1–65535 kostet nicht mehr alle Tunnel des Hosts: der Generator
  lässt nur diesen Proxy weg und warnt.
- T9: Ein `PUT` ohne `visitor_port` gibt einem STCP-Tunnel mit gespeichertem Port außerhalb 1–65535 einen freien Port,
  wie heute einem ohne Port; die automatische Verbindung bekommt diesen.

Nicht-Ziele (YAGNI):
- Keine Alembic-Migration gespeicherter Altwerte (`local_port`, `visitor_port`, `Connection.port`); Altwerte
  behandelt der Code beim Lesen (T8) oder beim nächsten `PUT` (T9), wie bei R-0411 und R-0533.
- Kein Schema-Bound für `local_port` (OpenAPI bleibt, Offene Frage 1), keine Änderung an
  `scripts/dev/oasdiff-err-ignore.txt`.
- Die Tunnel-Liste für den Desktop (`GET /api/frp/tunnels`) liefert gespeicherte Altwerte weiter roh; ein Wert
  außerhalb von `u16` lässt das Deserialisieren der ganzen Liste im Desktop scheitern (`tunnel.rs:60`). Das ist
  Desktop- oder API-Vertrag, nicht Teil dieses Pakets (Offene Frage 2).
- Andere Routen derselben Klasse wie R-0618 (`proxy_to_monitoring` mit `get_current_admin` und `require_scope`,
  der Webhook-Trigger mit `get_db`) halten ihre Session nur bis zum Ende der Anfrage, begrenzt durch 30 s Timeout
  (`monitoring_proxy/router.py:43`) bzw. das Hook-Timeout. Kein Umbau hier (Offene Frage 3).
- `null` für andere NOT-NULL-Felder im `PUT /api/frp/tunnels/{id}` (`name`, `tunnel_type`, `protocol`) bleibt, wie
  es ist; T7 behandelt nur `local_port`, weil seine Grenzprüfung `null` ohnehin abweist.
- Kein Retry im Monitoring-Proxy, keine Änderung an Agent, Web oder Desktop.
- T1 ändert weder `run.sh` noch die pytest-Optionen; ein Lauf mit `-s` (keine Ausgabe-Erfassung) bleibt ungeschützt.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | server | `apps/server/tests/conftest.py`, `apps/server/tests/test_conftest_db_password.py` (neu) |
| T2 | server | `apps/server/app/modules/hooks/scheduler.py`, `apps/server/tests/test_scheduler_reconcile.py`, `CHANGELOG.md` |
| T3 | server | `apps/server/app/modules/hooks/router.py`, `apps/server/tests/test_hooks.py`, `docs/developer/api-reference.html`, `docs/en/developer/api-reference.html`, `CHANGELOG.md` |
| T4 | server | `apps/server/app/core/identity.py`, `apps/server/app/modules/notifications/stream.py`, `apps/server/app/main.py`, `apps/server/tests/test_stream.py`, `CHANGELOG.md` |
| T5 | server | `apps/server/app/modules/monitoring_proxy/router.py`, `apps/server/tests/test_monitoring_proxy_errors.py` (neu), `docs/developer/api-reference.html`, `docs/en/developer/api-reference.html`, `CHANGELOG.md` |
| T6 | server | `apps/server/app/modules/frp/tunnel_router.py`, `apps/server/tests/test_frp_tunnels.py`, `docs/developer/api-reference.html`, `docs/en/developer/api-reference.html`, `CHANGELOG.md` |
| T7 | server | `apps/server/app/modules/frp/tunnel_router.py`, `apps/server/tests/test_frp_input_hardening.py`, `docs/developer/api-reference.html`, `docs/en/developer/api-reference.html`, `CHANGELOG.md` |
| T8 | server | `apps/server/app/modules/frp/config_generator.py`, `apps/server/tests/test_config_generator.py`, `docs/admin/frp-tunnel.html`, `docs/en/admin/frp-tunnel.html`, `CHANGELOG.md` |
| T9 | server | `apps/server/app/modules/frp/tunnel_router.py`, `apps/server/tests/test_frp_tunnels.py`, `docs/admin/frp-tunnel.html`, `docs/en/admin/frp-tunnel.html`, `docs/developer/api-reference.html`, `docs/en/developer/api-reference.html`, `CHANGELOG.md` |

Risikopfade (`scripts/dev/review-risk.txt`): `app/core/identity.py` und `app/modules/notifications/*` (T4),
`app/modules/monitoring_proxy/*` (T5), `app/modules/frp/*` (T6–T9) — diese Tasks bekommen zusätzlich `security`.
Kein Harness-Pfad: `tests/conftest.py` ist Testcode der Komponente.

## Datenmodell / API / Migrationen

Keine Migration, keine neue Route, kein neues Feld. **OpenAPI bleibt in allen Tasks unverändert**: alle neuen 422
entstehen im Handler als `RequestValidationError` im Format `HTTPValidationError` (wie `_reject_unknown_server` und
`_invalid`, `hooks/router.py:81-86`), 409, 502 und 504 sind in keiner Route deklariert, kein Routen-Docstring ändert
sich. `scripts/dev/openapi-breaking.sh server` bleibt damit grün; jede Task mit Routen-Code hat
`tests/test_openapi_snapshot.py` im `Verify:`.

Geänderte Antworten (alle in den Roadmap-Zeilen so benannt):

| Fall | heute | danach |
|---|---|---|
| `PUT /api/hooks/{id}` mit `"description": null` (T3) | 200, Beschreibung bleibt | 200, Beschreibung `null` |
| Monitoring-Proxy, Timeout zum Dienst (T5) | 500 | 504 |
| Monitoring-Proxy, Verbindungsfehler o. ä. (T5) | 500 | 502 |
| `POST /api/frp/tunnels`, unbekannte `connection_id` (T6) | 500 | 422 |
| `PUT /api/frp/tunnels/{id}`, unbekannte `connection_id` (T6) | 409 (falsche Meldung) | 422 |
| `POST /api/frp/tunnels`, verlorenes Rennen um Name/Visitor-Port (T6) | 500 | 409 |
| `local_port` außerhalb 1–65535 (T7) | 201/200, gespeichert | 422 |
| `PUT …` mit `"local_port": null` (T7) | 409 (falsche Meldung) | 422 |
| `PUT …` ohne `visitor_port`, gespeicherter Port außerhalb 1–65535 (T9) | Port bleibt | freier Port aus dem Bereich |

Vertrags-Drift zu den Clients: Der Agent behandelt jeden Status ≥ 300 außer 401/403/404 als vorübergehend
(`apps/agent/internal/httpclient/httpclient.go:33-37`, `:216-220`); 502/504 wirken dort wie 500. Web und Desktop
zeigen bei einem Fehler `detail` (`apps/web/src/lib/api/client.ts:118`), danach also den Text aus T5 statt „Internal
Server Error“. Der Desktop-Dialog bekommt für einen lokalen Port über 65535 ein 422 statt eines gespeicherten Werts.

## Externe Integrationen

- **APScheduler 3.11.2** (gepinnt, `apps/server/requirements.txt:26`): Probe oben (Problem 2). `str()` eines Triggers
  ist ohne Startzeit: `interval[0:05:00]`, `cron[month='*', day='*', day_of_week='mon,tue', hour='9', minute='0']`.
  Probe der Abhilfe (T2): Vergleich über `str(job.trigger)`, ein zweiter Abgleich mit gleichem Intervall lässt ein per
  `modify_job` gesetztes `next_run_time` stehen, ein geändertes Intervall registriert neu.
- **FastAPI 0.138.0** (gepinnt), Dependencies mit `yield`, fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/
  (gelesen 2026-10-22): „Normally the exit code of dependencies with <code>yield</code> is executed after the response is
  sent to the client.“ `Depends(…, scope="function")` beendet eine Dependency vor dem Senden; „When you declare a
  dependency with a <code>scope="request"</code> (the default), any sub-dependency needs to also have a scope of
  <code>"request"</code>.“
- **httpx 0.28.1**, python-httpx.org/exceptions/ (gelesen 2026-10-22): `HTTPError` ⊃ `RequestError` ⊃
  `TransportError` ⊃ `TimeoutException` (`ConnectTimeout`, `ReadTimeout`, `WriteTimeout`, `PoolTimeout`); `InvalidURL`
  steht außerhalb von `HTTPError`.
- **frp v0.69.1**, `pkg/config/v1/validation/proxy.go` (`validateProxyBaseConfigForClient`: ohne Plugin
  `ValidatePort(c.LocalPort, "localPort")`) und `common.go` (`ValidatePort`: „if 0 <= port && port <= 65535 { return
  nil }“, sonst Fehler). 0 besteht die Prüfung, ist aber kein Ziel, zu dem frpc verbinden kann; T7 nimmt deshalb
  1–65535 wie `Port` (`frp/schemas.py:143-144`) und wie R-0533 für `visitor_port`.
- **libpq**, postgresql.org/docs/current/libpq-envars.html (nur für die verworfene Alternative in T1): „PGPASSWORD
  behaves the same as the password connection parameter. Use of this environment variable is not recommended for
  security reasons …“
- **pytest** (≥ 9.0.3, `requirements-dev.txt:13`): `pytest_runtest_makereport` als Wrapper (`hookimpl(wrapper=True)`);
  ein Report darf als `longrepr` einen `str` tragen, Terminal und JUnit geben ihn als Text aus. Probe (Scratch,
  Platzhalter): ein solcher Wrapper, der das Passwort in `longrepr` ersetzt, lässt mit und ohne `-l` und im JUnit-XML
  0 Treffer übrig, für beide Tests, die denselben gescheiterten Session-Fixture teilen.

## Trade-offs & Alternativen

1. **T1, Passwort aus den Reports.** (a) Ein Report-Wrapper in `conftest.py` ersetzt das Passwort aus `DATABASE_URL`
   in `longrepr` und in den erfassten Abschnitten durch `***` — **Empfehlung**: eine Stelle für alle Tests, Rahmen
   und Engines, auch für `-l`, ohne die Verbindungslogik zu berühren; die Ausgabe ist die Grenze, an der das
   Geheimnis austritt. (b) Das Passwort beim Import des conftest aus `DATABASE_URL` nach `PGPASSWORD` verschieben:
   psycopg sieht es dann nicht mehr, aber der Hook-Worker bekommt nur `DATABASE_URL` (`script_runner.py:113-118` auf
   #254) — `test_a_hook_script_saves_connections_to_the_database` (`tests/test_connections_storage.py:59-83`) verlöre
   in der CI die Anmeldung; dazu warnt die libpq-Doku vor `PGPASSWORD`. (c) `--tb=short`: verbirgt die Argumente,
   nicht aber die Locals von `-l`, und nimmt allen Tests Kontext. Formen des Passworts, die (a) ersetzt: dekodiert
   (`sqlalchemy.engine.make_url(...).password`, so liest es SQLAlchemy), roh wie in der URL
   (`urllib.parse.urlsplit(...).password`, ohne Dekodierung), und als `repr`-Inhalt; die längste zuerst.
2. **T2, wann neu registrieren.** (a) `add_hook` vergleicht `str(job.trigger)` mit dem neu gebauten Trigger und lässt
   einen gleichen Job stehen — **Empfehlung**: kein zusätzlicher Zustand, gilt für jeden Aufrufer von `add_hook`.
   (b) Das Intervall des Hooks in einer Modul-Map oder im Job-Namen merken: zweite Wahrheit neben dem Job. (c)
   `reschedule_job` statt `add_job`: setzt den nächsten Lauf ebenfalls neu.
3. **T4, wo die Scope-Prüfung läuft.** (a) Den Körper der Dependency aus `require_scope` als `check_scope(request,
   identity, db, allowed)` herausziehen, `require_scope` ruft sie, `authenticate_stream_user` ruft sie auf seiner
   kurzen Session vor der Token-Prüfung, der Stream-Router hängt ohne `_access` ein — **Empfehlung** (Abhilfe der
   Zeile). (b) `Depends(get_db, scope="function")` in `require_scope`: betrifft jede Access-Route, und `get_db` wird je
   Anfrage gecacht, sodass die Session der Route selbst früher enden könnte (nicht verifiziert). (c) Ein eigener
   Router-Guard nur für den Stream: zweite Kopie der Scope-Logik.
4. **T5, Texte und Log.** `detail` englisch („monitoring service unreachable“, „monitoring service timed out“), wie
   neue Code-Strings im Projekt; WARNING unter `app.modules.monitoring_proxy.router` mit Route (Agent-Report oder
   Admin-Proxy) und `type(exc).__name__`. Kein Ziel-URL im Log: sie trägt `server_id` und Query; `MONITOR_API_KEY`
   steht nur im Header. Reihenfolge der `except`: erst `httpx.TimeoutException`, dann `httpx.HTTPError`.
5. **T7, Grenze im Handler statt im Schema.** Siehe Offene Frage 1. Die Prüfung steht vor jeder DB-Abfrage, wie eine
   Schema-Prüfung; `null` im `PUT` fällt mit durch.
6. **T8, Altwerte im Generator.** Filter in `active_tunnels` (`config_generator.py:134-142`): Config-Text, Hash und
   Provisioning-Bündel kommen von dort und bleiben gleich (Docstring `:136-140`). Alternative: Filter nur in
   `generate_frpc_toml` — der Hash zählte den Tunnel dann mit. Den Visitor eines so weggelassenen Proxys lässt T8
   stehen: er verbindet ins Leere wie heute, die TOML bleibt gültig.
7. **T9, ungültiger Visitor-Port beim `PUT`.** (a) Wie ein leerer Port behandeln und einen freien vergeben —
   **Empfehlung**: dieselbe Regel, die `update_tunnel` schon für leere und belegte Ports hat (`tunnel_router.py:217-226`),
   repariert auch die Visitor-Konfiguration. (b) `create_auto_connection` legt für einen solchen Tunnel keine
   Verbindung an: der Client bekäme still keine, der Tunnel bliebe kaputt.

## Risiken & Rollback

- T1 ersetzt Text im Report nur, wenn er das Passwort enthält; ein sehr kurzes Passwort (die CI nutzt den öffentlichen
  Wert aus `.github/workflows/ci.yml:43`) kann auch an anderer Stelle `***` erzeugen. Kosmetisch, kein Testergebnis
  ändert sich.
- T2: Ein Hook mit `1m` läuft danach jede Minute (Log-Volumen siehe R-0558); bisher lief er nie.
- T4: Fehlt die Scope-Prüfung im Stream, öffnet ein Desktop ohne Zertifikat im erzwungenen mTLS-Modus den Stream.
  Gepinnt durch einen Test im erzwungenen Modus (Route und Funktion).
- T6: Eine Verbindung, die zwischen Prüfung und Commit gelöscht wird, verletzt den FK weiter und wird 409 mit der
  allgemeinen Meldung (wie bei `_reject_unknown_server`, `connections/router.py:75-77`).
- T9 ändert beim nächsten `PUT` den Visitor-Port eines kaputten Tunnels; der Desktop bindet danach einen neuen Port.
  Der alte war nie nutzbar (Visitor weggelassen).
- Rollback: jede Task ist ein eigener Commit ohne Datenänderung; Revert genügt.

## Doku-Impact

CHANGELOG (Fixed, umlautfrei) für T2–T9; T1 keine (intern). API-Referenz DE+EN: T3 (`api-reference.html:117`), T5
(`:171-172`), T6, T7 (`:141`, `:143`), T9 (`:143`). Admin-Doku DE+EN: T8 (`docs/admin/frp-tunnel.html:102`, Abschnitt
„Tunneltypen“), T9 (`frp-tunnel.html:105`, „Visitor-Ports“). T2 und T4: Die Doku beschreibt das Soll schon
(`server.html:161-162`, `:193`).

## Offene Fragen

1. **R-0560: Grenze für `local_port` im Handler (T7) oder im Schema?** Das Schema (`Port` wie bei `visitor_port`)
   wäre der ehrlichere Vertrag und folgte R-0411/R-0533, `oasdiff` meldet aber vier ERR („max was decreased“, „min was
   increased“ für `POST`/`PUT`), die nur Einträge in `scripts/dev/oasdiff-err-ignore.txt` (Harness, Kevins Wort)
   hinnehmen; dazu verlöre `test_integer_body_fields_hold_at_both_edges` (`tests/test_frp_input_hardening.py:255-273`)
   seine letzten zwei Fälle (Test-Löschung) und der Snapshot änderte sich. **Empfehlung: Handler** (T7 wie geplant):
   gleiches Verhalten (422 im selben Format), vertragsneutral, keine Harness-Änderung. Trade-off: OpenAPI nennt
   weiter den INTEGER-Bereich; Schemathesis schickt deshalb Randwerte, die der Handler mit 422 im deklarierten Format
   beantwortet (`negative_data_rejection` betrifft nur schema-ungültige Eingaben). Bei „Schema“ wird T7 umgeschrieben
   und eine Harness-Task wie bei R-0533 kommt dazu.
2. **Gespeicherte Altwerte in der Tunnel-Liste für den Desktop.** `GET /api/frp/tunnels` liefert `localPort` und
   `visitorPort` roh; ein Wert außerhalb `u16` lässt `fetch_tunnels` des Desktops die ganze Liste verwerfen
   (`tunnel.rs:60`). Empfehlung: eigene Roadmap-Zeile (BUG, Desktop: Einträge einzeln deserialisieren und
   überspringen), nicht in diesem Paket — der Desktop gehört zu anderen Ledgern, und eine Server-Filterung der Liste
   wäre eine API-Änderung.
3. **Session über `await` in anderen Routen (Rest von R-0618).** Empfehlung: keine eigene Zeile jetzt; begrenzt durch
   Timeouts, bei Bedarf `zurückgestellt` aufnehmen.
