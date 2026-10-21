<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# SSRF-Schutz: zur geprüften Adresse verbinden

Stand des Codes: `origin/main@82e4a7b8`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/ssrf-pin.md`.

## Problem / Motivation

Den SSRF-Schutz gibt es zweimal mit identischem Code: `apps/server/app/core/ssrf.py` und
`apps/monitoring/app/core/ssrf.py`; `apps/server/tests/test_ssrf_parity.py:67` vergleicht beide ohne Docstrings und
Kommentare, `_ALLOWED_DIVERGENCES` (`:30`) ist leer. `classify_url` (monitoring `:128-166`, server `:130-168`)
löst den Host einmal auf (`_resolve`, `:72`/`:74`) und prüft jede Adresse. Danach baut der Aufrufer die Anfrage mit
httpx, und httpx löst den Namen beim Verbinden selbst noch einmal auf (httpcore ruft `socket.create_connection` mit
dem Hostnamen). Prüfung und Verbindung beruhen damit auf zwei getrennten Auflösungen; die Verbindung geht nicht
zwingend an eine Adresse, die der Guard geprüft hat. Der Docstring von `is_private_url` sagt das schon
(monitoring `:174-176`, server `:176-178`).

Aufrufer des Guards:

- Monitoring, Alert-Webhook: `_send_webhook` (`apps/monitoring/app/alerter.py:562-606`), Prüfung `:576`,
  `httpx.post` `:599`.
- Monitoring, HTTP-Check: `HttpChecker.run` (`apps/monitoring/app/checkers/http.py:21-124`), Prüfung `:34`,
  Anfrage `:50-56`, Redirects von Hand mit Prüfung je Hop `:63-89`.
- Server, Hook-Helfer `http_get`/`http_post`: `_safe_http_get` und `_safe_http_post`
  (`apps/server/app/modules/hooks/script_worker.py:58-96`), je `httpx.stream`.

Beleg auf `origin/main@82e4a7b8` (dreimal identisch, je Aufrufer): `_resolve` des Guards liefert eine öffentliche
Adresse, `socket.create_connection` zeichnet die Zieladresse auf und lehnt ab. HTTP-Check, Webhook und `http_get`
verbinden zu `("<hostname>", <port>)`, nicht zur geprüften Adresse.

## Ziel & Nicht-Ziele

Ziel:

- Der Guard löst je Ziel genau einmal auf, prüft alle Adressen wie heute und gibt die geprüften Adressen zurück.
- Die Anfrage verbindet zu einer dieser Adressen. Host-Header und TLS-Name (SNI und Zertifikatsprüfung) bleiben der
  Hostname der URL. Antwortet die erste Adresse nicht (Verbindungsfehler oder Verbindungs-Timeout), kommt die nächste
  geprüfte an die Reihe, in der Reihenfolge des Resolvers, wie es `socket.create_connection` heute tut.
- IPv6: Adressen werden mit eckigen Klammern in die URL gesetzt, der Host-Header bleibt der Name. Eine IPv4-gemappte
  IPv6-Adresse wird wie heute als ihre IPv4-Adresse geprüft und als diese verbunden.
- Redirects: Der HTTP-Check prüft und verbindet jeden Hop auf diese Weise; die Hop-URL wird weiter gegen die
  ursprüngliche URL aufgelöst. Webhook und Hook-Helfer folgen weiter keinem Redirect.
- Proxy: Ist für das Schema der URL ein Proxy aus der Umgebung gesetzt (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`,
  groß oder klein), bleibt der Weg wie heute: httpx wählt den Proxy (samt `NO_PROXY`), der Proxy verbindet. Die
  Prüfung vor der Anfrage bleibt. Der Hook-Runner reicht die Proxy-Variablen bewusst durch
  (`apps/server/app/modules/hooks/script_runner.py:104-125`); dieser Vertrag bleibt.
- Beide Guard-Kopien bleiben identisch (Paritätstest).

Nicht-Ziele:

- Kein neuer Guard für weitere Aufrufer (TCP-, Ping-Check und SMTP prüfen bewusst keine privaten Ziele,
  `docs/admin/monitoring.html:57`).
- Keine Änderung an Meldungen, Fehlertexten, Timeouts oder an der Liste der abgelehnten Adressbereiche.
- Keine Änderung am Hub-Aufruf des Monitorings (`_post_hub_event`, `alerter.py:418-439`, internes Ziel ohne Guard).
- Kein Verbinden über den Proxy zur geprüften Adresse (siehe Trade-offs).

## Betroffene Komponenten & Dateien

| Datei | Änderung |
|---|---|
| `apps/server/app/core/ssrf.py`, `apps/monitoring/app/core/ssrf.py` | `Target` + `check_target`, `classify_url` als dünner Wrapper, `pinned_client` mit eigenem Transport; beide Dateien gleich |
| `apps/server/tests/test_ssrf_pin.py` (neu) | Tests des Helfers, darunter ein echter TLS-Handshake gegen einen lokalen Server |
| `apps/monitoring/app/alerter.py` | `_send_webhook` über `check_target` + `pinned_client` |
| `apps/monitoring/app/checkers/http.py` | erste Anfrage und jeder Hop über `check_target` + `pinned_client` |
| `apps/server/app/modules/hooks/script_worker.py` | `_safe_http_get`/`_safe_http_post` über `check_target` + `pinned_client` |
| Tests der Aufrufer | Stubs ziehen von `httpx.post`/`httpx.request`/`httpx.stream`/`classify_url` auf eine Naht unter dem Pin um |
| Doku | `docs/admin/monitoring.html:339`, `docs/developer/monitoring.html:175`, `docs/developer/hooks.html:77`, je DE+EN; `CHANGELOG.md` |

Form des Helfers (Empfehlung, Namen darf der Bau anpassen, beide Kopien identisch):

```python
@dataclass(frozen=True)
class Target:
    verdict: UrlVerdict
    host: str = ""                      # der Host, den der Guard aufgelöst hat
    addresses: tuple[str, ...] = ()     # nur bei ALLOWED: alle geprüften Adressen, ohne Dubletten, Resolver-Reihenfolge

def check_target(url: str) -> Target: ...          # eine Auflösung, Prüfung wie classify_url heute
def classify_url(url: str) -> UrlVerdict: ...      # return check_target(url).verdict
def pinned_client(url: str, target: Target, *, verify: bool | ssl.SSLContext = True) -> httpx.Client: ...
```

`pinned_client` wirft `ValueError` ohne geprüfte Adressen. Ist laut `urllib.request.getproxies()` für das Schema der
URL oder für `all` ein Proxy gesetzt, liefert es `httpx.Client(verify=verify)` wie bisher. Sonst
`httpx.Client(transport=_PinnedTransport(...))`; der Transport

- bedient nur Anfragen, deren httpx-Host gleich `target.host` ist, und lehnt andere ab, ohne zu verbinden
  (`httpx.ConnectError`);
- setzt je Adresse `request.url.copy_with(host=<adresse>)`, behält die Header (der Host-Header samt Port stammt aus
  der ursprünglichen URL) und setzt die Request-Extension `sni_hostname` auf den IDNA-Host (`url.raw_host`);
- reicht an ein inneres `httpx.HTTPTransport(verify=verify)` weiter, wechselt nur bei `httpx.ConnectError` und
  `httpx.ConnectTimeout` zur nächsten Adresse und wirft sonst den letzten Fehler; `close()` schließt den inneren
  Transport.

Weil der Client die ursprüngliche Anfrage an die Antwort hängt (`response.request = request`, httpx 0.28.1
`_client.py:1018`), bleibt `resp.url` die URL mit dem Hostnamen; Redirect-Auflösung und Log-Zeilen bleiben gleich.

## Datenmodell / API / Migrationen

Keine. Kein HTTP-Endpunkt, kein Schema, keine Migration, kein Vertrag zwischen Server, Web, Desktop und Agent.
Die Signaturen von `http_get`/`http_post` im Hook bleiben.

## Externe Integrationen

httpx 0.28.1 und httpcore 1.0.9 (beide `requirements.txt`, Server und Monitoring).

- httpx-Doku „Extensions“, `sni_hostname` (https://www.python-httpx.org/advanced/extensions/, gelesen 2026-10-21):
  „The server's hostname, which is used to confirm the hostname supplied by the SSL certificate.“ und „If you want to
  connect to an explicit IP address rather than using the standard DNS hostname lookup, then you'll need to use this
  request extension.“ Beispiel dort: Anfrage an `https://185.199.108.153/path` mit `headers={"Host": "www.encode.io"}`
  und `extensions={"sni_hostname": "www.encode.io"}`.
- httpx-Doku „Transports“ (https://www.python-httpx.org/advanced/transports/): eigener Transport als Unterklasse von
  `httpx.BaseTransport` mit `handle_request`; `httpx.MockTransport` für Tests.
- httpx-Doku „Environment Variables“ (https://www.python-httpx.org/environment_variables/): „`HTTP_PROXY`,
  `HTTPS_PROXY`, `ALL_PROXY` set the proxy to be used for `http`, `https`, or all requests respectively.“,
  „`NO_PROXY` disables the proxy for specific urls“, „Environment variables are used by default.“
- Python-Doku `urllib.request.getproxies()` (https://docs.python.org/3.13/library/urllib.request.html): liest
  `<scheme>_proxy` ohne Rücksicht auf Groß-/Kleinschreibung, Kleinschreibung gewinnt. httpx liest die Umgebung über
  dieselbe Funktion (`httpx/_utils.py:37`).
- Aus dem Quelltext, in der Doku nicht beschrieben (nachgelesen in den installierten Paketen):
  - `httpx/_client.py:685`: `allow_env_proxies = trust_env and transport is None` — ein Client mit eigenem
    `transport=` nutzt keine Proxys aus der Umgebung. Deshalb entscheidet `pinned_client` selbst.
  - `httpcore/_sync/connection.py:107`, `:151`: die direkte Verbindung nimmt `sni_hostname` als `server_hostname`.
  - `httpcore/_sync/http_proxy.py:312`: der CONNECT-Tunnel eines HTTP-Proxys setzt `server_hostname` immer aus dem
    Ziel-Host und übergeht `sni_hostname`. Eine Adresse als Ziel durch den Proxy hieße TLS-Prüfung gegen die
    Adresse.
- Probe (Python 3.13, httpx 0.28.1, dreimal identisch): eigener Transport wie oben gegen lokale HTTPS-Server auf
  `127.0.0.1` und `::1` mit einem Zertifikat auf einen Namen. Status 200, der Server sieht SNI = Name und
  `Host: <name>:<port>`, `resp.url` trägt den Namen; ohne `sni_hostname` scheitert die Zertifikatsprüfung;
  `copy_with(host="::1")` ergibt `https://[::1]:<port>/`; erste Adresse abgewiesen → zweite verbunden; ein
  fremder Host wird abgelehnt; mit `HTTPS_PROXY` und `transport=` geht die Anfrage direkt, ohne `transport=` an den
  Proxy.

## Trade-offs & Alternativen

1. **Eigener Transport im Guard (Empfehlung).** Die ursprüngliche Anfrage bleibt unverändert (URL, `resp.url`,
   Redirect-Join, Logs), der Pin sitzt an einer Stelle in beiden Kopien, der Wechsel zur nächsten Adresse ist dort
   testbar. Kosten: ein kleiner Transport (öffentliche httpx-API) und eine eigene Proxy-Weiche.
2. URL am Aufrufer auf die Adresse umschreiben, Host-Header und `sni_hostname` von Hand setzen. Kleiner, aber
   `resp.url` trägt die Adresse (Redirect-Join und Meldungen müssten gegen die alte URL laufen), `NO_PROXY` würde
   gegen die Adresse statt gegen den Namen geprüft, und jeder der drei Aufrufer wiederholt die Logik.
3. Eigenes httpcore-Netzwerk-Backend (`connect_tcp` auf die Adresse umbiegen). Verlangt private Attribute
   (`HTTPTransport` reicht `network_backend` nicht durch). Nein.
4. Auch über einen Proxy zur Adresse verbinden. Für HTTPS über einen HTTP-Proxy nicht machbar
   (`http_proxy.py:312`, s. o.), für HTTP schreibt ein Proxy den Host aus der absoluten URL. Nein.
5. Proxy-Weiche: nach Schema über `getproxies()` (Empfehlung) oder `NO_PROXY` genau wie httpx auswerten (müsste
   httpx' private Muster-Logik nachbauen) oder Anfragen bei gesetztem Proxy ablehnen (bricht den Hook-Vertrag).
   Mit der Empfehlung gilt bei einem Proxy für das Schema alles wie bisher, auch für Ziele unter `NO_PROXY`.

## Risiken & Rollback

- Hosts mit mehreren Adressen: Reihenfolge und Wechsel wie `socket.create_connection`; neu ist, dass auch ein
  TLS-Fehler an der ersten Adresse zur nächsten wechselt (httpcore meldet beides als `ConnectError`). Die
  Verbindungszeit ist wie heute höchstens Adressen × Timeout.
- Tests der Aufrufer stubben heute `httpx.post`, `httpx.request`, `httpx.stream` oder `classify_url`. Nach dem Umbau
  rufen die Aufrufer diese nicht mehr; ein Zähler auf eine nicht mehr gerufene Funktion bestünde leer, und ein
  Test ohne Stub unter dem Pin baute eine echte Verbindung auf. Die betroffenen Tests ziehen deshalb in derselben
  Task auf eine Naht unter dem Pin um (Namen bleiben).
- httpx-Update: `sni_hostname` ist dokumentiert; die Proxy-Weiche hängt nicht an privater httpx-API. Ein Test mit
  echtem TLS-Handshake fällt, wenn sich das Verhalten ändert.
- Rollback: die Task-Commits zurücknehmen; keine Daten, keine Migration.

## Doku-Impact

Entwickler-Doku Hooks (`http_get`/`http_post`, `docs/developer/hooks.html:77`) und Monitoring (`http.py`,
`docs/developer/monitoring.html:175`), Admin-Doku Monitoring (Kanal `webhook`, `docs/admin/monitoring.html:339`),
je DE+EN: die Anfrage geht an eine geprüfte Adresse, Host-Header und TLS-Name bleiben der Hostname, mit einem Proxy
für das Schema verbindet der Proxy wie bisher. `CHANGELOG.md` unter `[Unreleased]` → Changed.

## Offene Fragen

Gebaut wird jeweils die Empfehlung.

1. Proxy-Weiche: Empfehlung nach Schema über `getproxies()`, mit Proxy wie bisher (Alternative 5).
2. Wechsel zur nächsten Adresse: Empfehlung der Reihe nach wie `socket.create_connection`; Alternative nur die
   erste Adresse (einfacher, aber ein Host, dessen erste Adresse aus dem Container nicht erreichbar ist, etwa IPv6
   ohne Route, wäre dann nicht mehr erreichbar).
