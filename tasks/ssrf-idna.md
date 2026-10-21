<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# SSRF-Guard: den Hostnamen in der Form auflösen, die httpx sendet — Task-Ledger
Status: erledigt · Branch: feature/ssrf-idna · Review: am Ende
Spec: Roadmap R-0590
Heavy: none — kein HTTP-Endpunkt, kein Schema, keine Migration, kein Gateway-, PKI-, FRP-, Compose- oder Install-Pfad; geändert wird nur, welchen Namen `check_target` in beiden Guard-Kopien auflöst, die Aufrufer (HTTP-Check, Alert-Webhook, Hook-Helfer `http_get`/`http_post`) bleiben unverändert, und keine schwere Suite fährt diese Wege (wie bei ssrf-pin); belegt wird am Resolver (`socket.getaddrinfo`) und unter dem Pin (`httpx.HTTPTransport.handle_request`)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: Der Guard löst genau den Namen auf, den die Anfrage danach als Host-Header und TLS-Name trägt. Heute übergibt
`check_target` dem Resolver den Unicode-Namen aus `urlparse`; `socket.getaddrinfo` kodiert ihn mit dem eingebauten
Codec `idna` (IDNA 2003, RFC 3490), httpx kodiert denselben Host mit dem Paket `idna` (IDNA 2008). Bei `ß`, `ς` und
ähnlichen Zeichen sind das zwei verschiedene Namen: geprüft und verbunden wird zu den Adressen des einen, Host-Header und
SNI tragen den anderen. Zeilenangaben: origin/main@6f05b316.

Belege (installierte Pakete, `apps/server/.venv`: Python 3.13.5, httpx 0.28.1, idna 3.18):
- httpx `_urlparse.py:348-392` `encode_host`: ASCII-Host → `quote(host.lower(), …)`, sonst
  `idna.encode(host.lower())`, bei `idna.IDNAError` → `InvalidURL("Invalid IDNA hostname: …")`. `idna/core.py:510-516`
  `encode(…, uts46=False, …)`: ohne UTS-46-Mapping, IDNA 2008.
- Python-Doku `codecs`, Abschnitt `encodings.idna` (https://docs.python.org/3.13/library/codecs.html): „This module
  implements RFC 3490 …“, „the socket module transparently converts Unicode host names to ACE“, „If you need the IDNA
  2008 standard from RFC 5891 and RFC 5895, use the third-party idna module.“ Lokal: `socket.getaddrinfo("ä"*64 +
  ".example", None)` wirft `UnicodeEncodeError: 'idna' codec can't encode … label too long`, getaddrinfo nutzt den Codec.
- `httpx.InvalidURL` ist keine Unterklasse von `ValueError`; ein Fuzz über `httpx.URL(<str>).raw_host` (20 000 Fälle)
  warf nichts außer `InvalidURL`.

Für die Task:
- Beide Guard-Kopien bleiben identisch: `apps/server/tests/test_ssrf_parity.py:67`, `_ALLOWED_DIVERGENCES` (`:30`) bleibt
  leer. `verify.sh server` lintet `apps/monitoring` mit (`scripts/tests/run.sh:559-560`).
- Kein Test löst wirklich auf oder verbindet nach außen: Naht am Resolver ist `socket.getaddrinfo` (wie
  `apps/server/tests/test_ssrf.py:246`), unter dem Pin `_below_the_pin` (`test_ssrf_pin.py:89`). Geprüfte Adressen sind
  die öffentlichen Literale der Suite (`_V4`, `_V6` in `test_ssrf_pin.py`); RFC-5737-Adressen gelten dem Guard als privat.
- Die Proxy-Variablen leert die autouse-Fixture in `test_ssrf_pin.py` schon.

### T1 — Guard löst den Host in der Form auf, die httpx sendet  [x]
Komponente: server · Dateien: apps/server/app/core/ssrf.py, apps/monitoring/app/core/ssrf.py, apps/server/tests/test_ssrf_pin.py, apps/server/tests/test_ssrf_properties.py, CHANGELOG.md, apps/server/tests/test_hooks_http_ssrf.py, apps/monitoring/tests/test_alerter_dispatch.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @1e992957 2026-10-21T12:26:39+02:00
Review: am Ende (Branch-Review)
Änderung: In beiden Kopien identisch, `check_target` (server `ssrf.py:149-193`, monitoring `:147-191`): `urlparse` bleibt als erste Prüfung wie heute (`ValueError` → `PRIVATE`, kein Host → `UNRESOLVED`; `apps/server/tests/test_ssrf.py:265-271` bleibt unverändert grün, denn `http://[` liest httpx als Host `%5B`). Danach `httpx.URL(url).raw_host` als ASCII-`str`: `httpx.InvalidURL` → `Target(UrlVerdict.PRIVATE)` ohne Auflösung (wie eine unlesbare URL, R-0181; die Anfrage würde an derselben Stelle scheitern), leerer Host → `UNRESOLVED`; aufgelöst (`:167` bzw. `:165`) und in `Target.host` getragen wird dieser Name. `_resolve` behält Signatur und Ablauf. Docstring von `check_target` und Kommentar `:162-163` (monitoring `:160-161`) nennen die neue Quelle des Namens; der Kommentar in `pinned_client` (server `:286-289`, monitoring `:284-287`) nennt `target.host` nicht mehr als `urlparse`-Namen. Tests zuerst rot, in `test_ssrf_pin.py`, Abschnitt `check_target` (`:101-141`): (1) neu, am Resolver: `socket.getaddrinfo` aufzeichnen (Antwort `_V4`), `check_target(f"https://{host}/x")`, parametriert `straße.example` → `xn--strae-oqa.example`, `faß.de` → `xn--fa-hia.de`, `βόλος.example` → `xn--nxasmm1c.example`, Kontrolle `www.bücher.example` → `www.xn--bcher-kva.example`; geprüft wird der Name auf dem Draht, so wie CPython das Argument kodiert (`str` über den Codec `idna`, `bytes` unverändert), gegen das Literal, und das Literal gegen `httpx.URL(url).raw_host`; heute rot für `ß`/`ς`, die Kontrolle grün vorher und nachher. (2) neu: `https://☃.example/`, `https://ｅｘａｍｐｌｅ.com/`, `http://1.2.3.999/` mit `_resolving_to(monkeypatch, _V4)` → `PRIVATE`, keine Adressen, der Resolver nie gefragt (heute `ALLOWED`). (3) `test_host_header_and_tls_name_stay_the_hostname` (`:224-249`): Parameter um `straße.example` → `xn--strae-oqa.example` ergänzen und prüfen, dass der Guard genau den Namen aufgelöst hat, den Host-Header und `sni_hostname` tragen (`asked == [idna]` aus `_resolving_to`), und `check_target(url).host == idna`. In `test_ssrf_properties.py`: `test_the_guard_checks_the_host_that_httpx_will_actually_fetch` (`:131-165`) vergleicht gegen `httpx.URL(url).raw_host` statt `.host` (`:142`; `.host` dekodiert IDNA, sobald der ganze Host mit `xn--` beginnt), die Host-Liste (`:115-117`) bekommt `straße.example` und `xn--bcher-kva.example`, dazu `@example(url="http://straße.example/")`; im Docstring wird nur der Satz zum Parser (`:134`) richtiggestellt, `:136-137` bleibt (R-0599). `CHANGELOG.md` `[Unreleased]` → `### Fixed` (`:466`), umlautfrei, Beispiel nur in ACE-Form: der SSRF-Schutz (Server und Monitoring) prueft einen internationalisierten Hostnamen jetzt in der Form, die die Anfrage traegt (IDNA 2008, etwa `xn--strae-oqa.example`), bisher loeste er bei scharfem s oder finalem Sigma einen anderen Namen auf (IDNA 2003), und die Anfrage konnte am Zertifikat oder am vhost scheitern; ein Hostname, den httpx nicht kodieren kann, wird schon vom Guard abgelehnt wie eine unlesbare URL.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ssrf_pin.py tests/test_ssrf_properties.py tests/test_ssrf.py tests/test_ssrf_parity.py tests/test_hooks_http_ssrf.py
Doku: CHANGELOG (Fixed); docs/ bleibt richtig (`docs/developer/hooks.html:77` lehnt eine unlesbare URL schon ab, „Hostname der URL“ gilt jetzt auch für internationalisierte Namen)
Beweis: origin/main@6f05b316 · Probe (Scratch, `socket.getaddrinfo` aufgezeichnet, Antwort `93.184.216.34`): `check_target("https://straße.example/x")` übergibt `'straße.example'`, auf dem Draht `b'strasse.example'`; `httpx.URL(...).raw_host` = `b'xn--strae-oqa.example'`; der gepinnte Request trägt Host und `sni_hostname` `xn--strae-oqa.example` und geht an `93.184.216.34`; ebenso `faß.de` (`fass.de` gegen `xn--fa-hia.de`) und `βόλος.example` (`xn--nxasmq6b` gegen `xn--nxasmm1c`); `☃.example` und `ｅｘａｍｐｌｅ.com` → `ALLOWED`, httpx wirft `InvalidURL`; dreimal identisch (gleiche md5)
Orakel: contract — der Name, den der Resolver auflöst, ist der Name in Host-Header und TLS-Name der gepinnten Anfrage (`httpx.URL(url).raw_host`)
Dedup-Key: bug:server:ssrf-guard:idna2003-vs-2008
HEAD: 6f05b316
Semantik: docs/developer/hooks.html:77 — „Abgelehnt wird auch eine URL, die sich nicht lesen lässt oder keinen Host hat“ und „Die Anfrage geht an eine der bei der Prüfung aufgelösten Adressen, der Reihe nach, bis eine die Verbindung annimmt, und Host-Header und TLS-Name (SNI und Zertifikatsprüfung) bleiben der Hostname der URL“; ebenso docs/admin/monitoring.html:339 (Kanal `webhook`) und docs/developer/monitoring.html:175 (`http.py`): geprüft und angesprochen wird derselbe Hostname
