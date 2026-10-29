<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# SSRF-Guard: direkter Weg neben einem Proxy, unlesbare URLs, Kommentar- und Test-Nachzug

Stand des Codes: `origin/main@53a7dbc5`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/ssrf-followups.md`. Roadmap R-0606 (T3, T4), R-0599 (T3 Docstring, T5); T1 und T2 gehören zum Paket (Kevin
2026-10-22). Proben: Python 3.13.5, httpx 0.28.1, httpcore 1.0.9 im Dev-Venv, je dreimal mit gleicher md5 der Ausgabe.

## Problem / Motivation

1. **Direkte Verbindung neben einem gesetzten Proxy (T1, T2).** `pinned_client` (`apps/server/app/core/ssrf.py:277-305`,
   gleich `apps/monitoring/app/core/ssrf.py:275-303`) fragt `getproxies()` nach einem Proxy für das Schema der URL oder
   für alle (`:291-292`). Gibt es einen, liefert es einen gewöhnlichen `httpx.Client(verify=verify)` (`:299`) und lässt
   httpx wählen; sonst den gepinnten Client (`:304-305`). httpx nimmt dann für ein Ziel unter `NO_PROXY` (und bei
   `NO_PROXY=*` für jedes) keinen Proxy, sondern verbindet direkt über den Namen, also ohne den Pin, den derselbe
   direkte Weg ohne Proxy hat. Probe (`ssrf._resolve` ersetzt, `socket.create_connection` aufgezeichnet und
   abgewiesen, Host unter `.example`): `HTTP_PROXY` plus `NO_PROXY` = `*`, `<host>` oder `.example`,
   `HTTPS_PROXY` plus `no_proxy="other.example, *"`, `ALL_PROXY` plus `NO_PROXY=<host>:8080` → Verbindung an
   `(<host>, port)`; ohne Proxy → an `("93.184.216.34", port)`, die geprüfte Adresse. Kommentar (`:293-298`) und Doku
   (`docs/developer/hooks.html:77`, `docs/developer/monitoring.html:175`, `docs/admin/monitoring.html:339`, EN je
   gleiche Zeile) beschreiben das so. Gewollt: Ob httpx direkt verbindet, weil kein Proxy gesetzt ist oder weil
   `NO_PROXY` das Ziel ausnimmt, macht keinen Unterschied; beide Male geht die Verbindung an eine geprüfte Adresse.

2. **URL mit einem einzelnen Surrogat (T3, T4; R-0606).** `check_target` fängt beim Lesen durch httpx nur
   `httpx.InvalidURL` (`ssrf.py:174-177`, Monitoring `:172-175`). Ein `str` mit einem einzelnen Surrogat in Pfad,
   Query, Fragment oder Userinfo (`"http://example.com/\ud800"`) lässt httpx beim Kodieren `UnicodeEncodeError` werfen;
   `check_target` wirft dann, statt abzulehnen (Probe: alle vier Stellen werfen, der Resolver wird nicht gefragt; ein
   Surrogat im Host oder Port ist schon `InvalidURL` → `PRIVATE`). Folgen: der HTTP-Check ruft `check_target` vor
   seinem `try` (`apps/monitoring/app/checkers/http.py:34`), die Exception landet in der Engine als `unknown`,
   „Unexpected error: …“ mit Traceback (`apps/monitoring/app/check_engine.py:314-320`); der Webhook
   (`apps/monitoring/app/alerter.py:576`) landet in der Dispatch-Schleife als „Dispatch failed (UnicodeEncodeError)“
   (`alerter.py:203-210`); ein Hook bekommt von `http_get`/`http_post` einen `UnicodeEncodeError` statt der Ablehnung.
   Gespeicherte Checks und Regeln tragen so einen Wert nicht (er lässt sich nicht als UTF-8 kodieren), ein Hook
   bekommt ihn aber aus einem JSON-Payload (`json.loads('"\\ud800"')` ergibt das Surrogat).

3. **Kommentar-Beispiel (R-0606).** `ssrf.py:168-169` (Monitoring `:166-167`) nennt `"http://[::1"` als URL, die httpx
   „als Host `%5B`“ liest. Probe: dort wirft httpx `InvalidURL: Invalid port: ':1'`; den Host `%5B` liest httpx bei
   `"http://["`. `urlparse` wirft bei beiden.

4. **Kommentare zum `InvalidURL`-Weg (R-0606).** `http.py:50-51` und `alerter.py:599-600` begründen den Platz von
   `pinned_client` im `try` mit „it parses the URL already“; der Docstring von `pinned_client` (`ssrf.py:285-287`,
   Monitoring `:283-285`) sagt, ohne Proxy könne der Aufruf schon `httpx.InvalidURL` werfen. Seit R-0590 liest
   `check_target` die URL mit httpx (`:174-177`); ein Target mit Adressen hat eine URL, die httpx liest. Im `try`
   gehört `pinned_client` aus einem anderen Grund: Der Client scheitert beim Bau an einer unbrauchbaren Proxy-Angabe
   für das Schema (Probe: `HTTPS_PROXY=ftp://…` → `ValueError`, `socks5://…` ohne `socksio` → `ImportError`).

5. **Monitoring-Test am Aufrufer für eine unlesbare URL fehlt (R-0606).** Am Guard ist sie getestet
   (`apps/server/tests/test_ssrf_pin.py:178-192`), am HTTP-Check und am Webhook mit dem echten Guard nicht;
   `apps/monitoring/tests/test_alerter.py:389-401` deckt nur `"http://[::1"` (den `urlparse`-Weg).

6. **Test-Nachzug (R-0599).** (a) `verify=verify_ssl` am Redirect-Hop (`http.py:80`) ist ungetestet;
   `apps/monitoring/tests/test_http_checker.py:114-135` prüft eine Anfrage ohne Redirect. (b)
   `apps/monitoring/tests/test_alerter_dispatch.py:136` vergleicht den Fehlertext von httpx wörtlich
   (`Invalid port: 'abc'`); eine neue Formulierung in httpx machte den Test rot, ohne dass sich unser Verhalten ändert.
   (c) Der Docstring von `test_the_guard_checks_the_host_that_httpx_will_actually_fetch`
   (`apps/server/tests/test_ssrf_properties.py:142-151`) sagt, bei verschiedenen Hosts „the guard clears one address and
   the client connects to another“ (`:147-148`); seit dem Pin verbindet der Client nur zu geprüften Adressen.

## Ziel & Nicht-Ziele

Ziel:
- `pinned_client`: Ist für das Schema der URL oder für alle ein Proxy gesetzt, wählt httpx mit seiner eigenen Tabelle
  aus der Umgebung (samt `NO_PROXY`) wie bisher, ob eine Anfrage über den Proxy geht; was httpx direkt verbinden würde,
  geht über den Pin an eine geprüfte Adresse, Host-Header und TLS-Name bleiben der Hostname. Welche Anfrage über den
  Proxy geht, ändert sich nicht. Ohne Proxy für das Schema bleibt alles, wie es ist.
- `check_target`: ein `UnicodeError` beim Lesen durch httpx gilt wie `httpx.InvalidURL` als unlesbare URL
  (`Target(PRIVATE)`); HTTP-Check, Webhook und Hook-Helfer melden ihre gewöhnliche Ablehnung.
- Kommentare und Docstrings sagen, was gilt.
- Tests: `NO_PROXY`-Fälle samt Differential gegen httpx, Surrogat am Guard und an beiden Monitoring-Aufrufern,
  unlesbare URL an beiden Monitoring-Aufrufern, `verify` am Hop, Fehlertext aus httpx statt wörtlich.

Nicht-Ziele (YAGNI):
- Kein Pin über einen Proxy: der Proxy löst den Namen selbst auf (CONNECT bzw. absolute URL; Trade-off 4 in
  `docs/features/ssrf-pin.md`).
- Keine eigene Auswertung der `NO_PROXY`-Muster (Trade-off 1).
- `check_target` bleibt im HTTP-Check und im Webhook vor dem `try`: nach T3 wirft es für keine `str`-URL mehr; T4
  pinnt das am Aufrufer.
- `_log_host` (`alerter.py:542-549`) und sein Kommentar `:548` bleiben: dort ist `"http://[::1"` richtig, `urlparse`
  wirft.
- Keine neue Umgebungsvariable, keine Einstellung.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | server | `apps/server/app/core/ssrf.py`, `apps/monitoring/app/core/ssrf.py`, `apps/server/tests/test_ssrf_pin.py`, `docs/developer/hooks.html`, `docs/en/developer/hooks.html`, `docs/developer/monitoring.html`, `docs/en/developer/monitoring.html`, `docs/admin/monitoring.html`, `docs/en/admin/monitoring.html`, `CHANGELOG.md` |
| T2 | monitoring | `apps/monitoring/tests/test_http_checker.py`, `apps/monitoring/tests/test_alerter.py` |
| T3 | server | `apps/server/app/core/ssrf.py`, `apps/monitoring/app/core/ssrf.py`, `apps/server/tests/test_ssrf_pin.py`, `apps/server/tests/test_ssrf_properties.py`, `CHANGELOG.md` |
| T4 | monitoring | `apps/monitoring/app/checkers/http.py`, `apps/monitoring/app/alerter.py`, `apps/monitoring/tests/test_http_checker.py`, `apps/monitoring/tests/test_alerter.py` |
| T5 | monitoring | `apps/monitoring/tests/test_http_checker.py`, `apps/monitoring/tests/test_alerter_dispatch.py` |

Beide Guard-Kopien ändern sich je im selben Commit (`apps/server/tests/test_ssrf_parity.py`, `_ALLOWED_DIVERGENCES`
bleibt leer); `verify.sh server` lintet `apps/monitoring` mit. Auf der Risikoliste (`scripts/dev/review-risk.txt:32-37`)
stehen beide `ssrf.py` und `alerter.py`: T1, T3 und T4 bekommen zusätzlich `security`.

Überschneidungen: PR #265 (`feature/monitoring-io`) ändert `apps/monitoring/app/checkers/http.py` (die Redirect-Schleife
wird umgebaut, `:46-117`), `apps/monitoring/app/alerter.py`, `apps/monitoring/tests/test_http_checker.py`,
`apps/monitoring/tests/test_alerter.py`, die vier Monitoring-Doku-Seiten und `CHANGELOG.md`. T2, T4 und T5 laufen
deshalb erst, wenn #265 auf `main` ist und `origin/main` in den Branch gemergt ist; sie nennen Code-Stellen nach
Inhalt, der builder greppt die Zeilen neu. `feature/monitoring-hardening-2` ist noch ohne Plan.

## Datenmodell / API / Migrationen

Keine Migration, kein Feld, keine Route, kein Schema; OpenAPI bleibt unverändert. Kein Vertrag zu Desktop, Agent oder
Web. Die Signaturen von `check_target` und `pinned_client` bleiben.

## Externe Integrationen

- httpx 0.28.1, httpcore 1.0.9, idna 3.18, gepinnt in `apps/server/requirements.txt:386`, `:330`, `:390` und
  `apps/monitoring/requirements.txt:187`, `:131`, `:191`.
- httpx-Doku „Environment Variables“ (https://www.python-httpx.org/environment_variables/, gelesen 2026-10-22):
  „`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` set the proxy to be used for `http`, `https`, or all requests
  respectively.“, „`NO_PROXY` disables the proxy for specific urls“, „Environment variables are used by default.“ Zur
  Form der `NO_PROXY`-Einträge (führender Punkt, `*`, Port) sagt die Seite nichts.
- httpx-Doku „Transports“ (https://www.python-httpx.org/advanced/transports/, gelesen 2026-10-22): Routing über
  `mounts=` mit Mustern wie `all://`, `all://example.com`, `all://*example.com` (Domain und Subdomains),
  `all://*.example.com` (nur Subdomains), Ports; ein Muster mit `None` geht nicht über den Proxy; „Matching is done
  from most specific URL patterns“. Wie `mounts=` und `transport=` zusammenwirken, sagt die Seite nicht.
- Aus dem Quelltext der installierten Version (in der Doku nicht beschrieben): `httpx/_client.py:685` liest die
  Umgebung nur ohne eigenen `transport=`; `:697-716` baut die Mounts aus `get_environment_proxies()`, ergänzt `mounts=`
  und sortiert; `:760-769` `_transport_for_url`: das erste passende Muster gewinnt, ein `None`-Mount fällt auf den
  Transport des Clients zurück. `httpx/_utils.py:30-76` `get_environment_proxies()`: liest `getproxies()`, legt
  `http://`, `https://`, `all://` für die Proxys an; `NO_PROXY`: `*` (auch als ein Eintrag der Liste) → `{}`, ein
  Eintrag mit `://` wörtlich, IPv4 → `all://<ip>`, IPv6 → `all://[<ip>]`, `localhost` → `all://localhost`, sonst
  `all://*<eintrag>`, jeweils `None`.
- Nicht verifiziert: ob `httpx._utils.get_environment_proxies` in httpx nach 0.28.1 so heißt und dasselbe liefert.

## Trade-offs & Alternativen

1. **Wie `pinned_client` der Wahl von httpx folgt (T1).** (a) **Empfehlung:** httpx' eigene Tabelle aus
   `httpx._utils.get_environment_proxies()` als `mounts=` (Proxy → `httpx.HTTPTransport(verify=verify, proxy=…)`,
   `None` bleibt `None`), der Pin als `transport=`. Die Wahl trifft httpx' dokumentierte Mount-Logik; privat ist nur
   die Funktion, die httpx selbst für die Tabelle nutzt. Probe: 792 Fälle (6 Proxy-Umgebungen × 22 `NO_PROXY`-Werte ×
   6 URLs, darunter Groß-/Kleinschreibung, Ports, Schema-Muster, `*` in einer Liste, IP, `localhost`, IDN) gegen einen
   gewöhnlichen `httpx.Client()` in derselben Umgebung: 0 Abweichungen; der heutige Code weicht in 121 von 540 Fällen
   ab, alle „direkt ohne Pin“. Benennt ein httpx-Upgrade die Funktion um, scheitert der Import laut (CI rot), nicht
   still. (b) Die Tabelle selbst bauen, gut 20 Zeilen je Kopie, nur öffentliche API: eine Abweichung nach einem Upgrade
   bliebe still. (c) Einen gewöhnlichen `httpx.Client()` fragen (`_transport_for_url`, ebenfalls privat, ein Client
   mehr je Anfrage). (d) `NO_PROXY`-Muster nachbauen: in `docs/features/ssrf-pin.md` Trade-off 5 verworfen. (e) Nur
   `NO_PROXY=*` erkennen: Hosts in `NO_PROXY` blieben ohne Pin. (f) `urllib.request.proxy_bypass_environment`: andere
   Regeln, `.example.com` nimmt dort auch `example.com` aus, httpx nicht; der Proxy-Weg änderte sich sichtbar.
2. **Die Weiche nach Schema bleibt (T1).** Mounts gibt es nur, wenn für das Schema der URL oder für alle ein Proxy
   gesetzt ist, sonst den gepinnten Client wie heute. So liest ohne Proxy niemand `NO_PROXY`, und eine unbrauchbare
   Proxy-Angabe für ein anderes Schema bleibt folgenlos. Probe: mit Weiche baut der Client in denselben Fällen wie
   heute und scheitert in denselben (`NO_PROXY=host:abc` oder `[::1` ohne Proxy: baut; mit Proxy: `InvalidURL`;
   `HTTPS_PROXY=ftp://…` bzw. `socks5://…` bei einer `http`-URL: baut, bei einer `https`-URL: `ValueError` bzw.
   `ImportError`). Ohne Weiche scheiterten auch die heute bauenden Fälle, wie bei einem gewöhnlichen `httpx.Client()`.
3. **Fang in `check_target` (T3).** `except (httpx.InvalidURL, UnicodeError)`: genau die zwei Arten, auf die httpx
   eine URL nicht liest. `except ValueError` wäre breiter, `InvalidURL` ist keine Unterklasse davon.
4. **Fehlertext im Dispatch-Test (T5).** Erwartung aus httpx selbst (`pytest.raises(httpx.InvalidURL)` um
   `httpx.URL(url)`, dann `str(info.value)`): der Test pinnt weiter, dass genau der Text der Exception ins Service-Log
   geht, nicht mehr. Alternative: nur den Anfang der Zeile prüfen, dann bliebe ungeprüft, was danach steht.

## Risiken & Rollback

- Privater Import (Trade-off 1): httpx ist in beiden `requirements.txt` gepinnt; ein Upgrade-PR läuft durch die
  Tests aus T1 (Differential gegen httpx), die eine geänderte Tabelle melden.
- Ein Ziel unter `NO_PROXY` neben einem Proxy verbindet jetzt zu einer geprüften Adresse, der Reihe nach wie ohne
  Proxy, mit SNI und Zertifikatsprüfung auf den Namen. Ein Ziel unter `NO_PROXY`, das privat auflöst, lehnt der Guard
  schon heute ab; daran ändert sich nichts.
- Mit Proxy baut der Client heute einen Transport je Proxy-Muster plus einen Basis-Transport, danach dieselben plus
  den Transport unter dem Pin statt des Basis-Transports: gleich viele.
- T2, T4, T5 kollidieren textlich mit PR #265, wenn sie vorher gebaut werden (siehe oben).
- Rollback: jede Task ist ein eigener Commit ohne Datenänderung; Revert genügt.

## Doku-Impact

T1: in `docs/developer/hooks.html:77`, `docs/developer/monitoring.html:175`, `docs/admin/monitoring.html:339` (EN je
gleiche Zeile) heißt es statt des Teils, nach dem ein Ziel unter `NO_PROXY` direkt über den Namen verbunden wird: ein Ziel, das wegen `NO_PROXY` nicht
über den Proxy geht, verbindet wie ohne Proxy zu einer der geprüften Adressen; CHANGELOG (Changed). T3: CHANGELOG
(Fixed). T2, T4, T5: keine (Tests und Kommentare).

## Offene Fragen

Keine, die eine Task sperrt. Welche Anfrage über einen Proxy geht, bleibt gleich (Trade-off 1, Probe); neu ist nur,
dass der direkte Weg neben einem Proxy gepinnt ist (erstes Ziel oben).
