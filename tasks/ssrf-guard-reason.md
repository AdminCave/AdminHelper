<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# SSRF-Guard nennt den Grund: privat oder nicht auflösbar (R-0045) — Task-Ledger
Status: erledigt · Branch: feature/ssrf-guard-reason · Commit-Granularität: pro Task · Review: auto · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-05 (kleines Fund-Paket aus der angenommenen Zeile R-0045, Pilot Stufe 7a; delegiert von Kevin am 2026-10-05)
Pilot: Stufe 7a — erstes Übungs-Ledger für den Worker (`ledger-loop.sh` als `adminhelper-runner`, unbeaufsichtigt, `task-close.sh --review auto` je Task). Gebaut wird es erst nach dem Merge von 7a und Kevins Setup- und Red-Team-Lauf, und nur vom Loop: interaktiv vorgezogen wäre die Übung verbraucht (Spec Stufe 7a, „Pilot“).
Pilot entfällt: Runner eingefroren (Kevin 2026-10-07), interaktiv gebaut.
Spec: Roadmap R-0045 (privat; was der Bau braucht, steht in diesem Ledger)
Heavy: none — Python in apps/server und apps/monitoring (SSRF-Guard und seine drei Aufrufer) mit Unit-Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad, kein Wire-Format, keine Migration. Die Runner-Box hat Python, Shell und Git (`runner-setup.sh`), also genau diese beiden Suiten.
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-05 von Worker A für die Aufsicht (adminhelper-ac), Auswahl unter R-0040, R-0044 und R-0045.
Befund: `is_private_url` (`apps/server/app/core/ssrf.py:121`, `apps/monitoring/app/core/ssrf.py:119`) antwortet `True`
aus zwei verschiedenen Gründen: das Ziel löst auf eine private oder reservierte Adresse auf — oder es löst gar nicht
auf (kein Host in der URL, Nameserver tot, Frist von 5 s verpasst, Deckel von 64 laufenden Auflösungen erreicht;
Server `:132` und `:135`, Monitoring `:130` und `:133`). Die Aufrufer kennen nur den ersten Grund und melden bei totem
Nameserver „privat/reserviert“: `apps/monitoring/app/checkers/http.py:32–33` und `:55–58`,
`apps/monitoring/app/alerter.py:392–394`, `apps/server/app/modules/hooks/script_worker.py:55–56` und `:67–68`. Der
Betreiber sucht dann in der URL einen Fehler, der in seinem DNS liegt.

Entwurf (für alle drei Tasks; Zeilenangaben main@bf9cee5e, beim Bau an Symbolen orientieren):
- Beide `ssrf.py` bekommen `class UrlVerdict(enum.Enum)` mit `ALLOWED = "allowed"`, `PRIVATE = "private"`,
  `UNRESOLVED = "unresolved"` und `def classify_url(url: str) -> UrlVerdict`. `UNRESOLVED`: die URL hat keinen Host,
  oder `_resolve` liefert `None` (Fehler, Frist, Deckel) bzw. eine leere Liste. `PRIVATE`: eine Adresse der Antwort
  fällt in die gesperrten Kategorien, oder sie ist nicht lesbar (wie heute, fail-closed). Sonst `ALLOWED`.
- `is_private_url(url: str) -> bool` bleibt, als `return classify_url(url) is not UrlVerdict.ALLOWED`: fail-closed wie
  bisher, und die bestehenden Tests in beiden `test_ssrf.py` und in `test_ssrf_properties.py` (38 Zeilen mit
  `is_private_url`) bleiben unberührt.
- Abgelehnt wird weiter beides, die Status-Werte bleiben; nur die Meldung unterscheidet die Gründe. Die Meldungen für
  `PRIVATE` bleiben wörtlich (Tests prüfen `"SSRF"` darin). Die neuen Meldungen für `UNRESOLVED` sind englisch
  (Code-Strings englisch, der deutsche Alt-Bestand bleibt) und stehen wörtlich in T2 und T3.
- Die beiden `ssrf.py` bleiben eine Implementierung: `apps/server/tests/test_ssrf_parity.py` vergleicht sie ohne
  Docstrings und Kommentare, `_ALLOWED_DIVERGENCES` bleibt leer.
- Nicht in diesem Ledger: dass `urlparse` bei `http://[::1` `ValueError` wirft, statt fail-closed zu antworten
  (Roadmap-Kandidat über die Aufsicht); ein eigener Grund für den Deckel; Seiten unter `docs/` (sie beschreiben die
  Ablehnung privater Ziele, und das bleibt wahr).

### T1 — `ssrf.py` in beiden Diensten: `classify_url` mit Grund, `is_private_url` als Hülle  [x]
Komponente: server · Dateien: apps/server/app/core/ssrf.py, apps/monitoring/app/core/ssrf.py, apps/server/tests/test_ssrf.py, apps/monitoring/tests/test_ssrf.py
Evidenz: run.sh[quick] server monitoring: 5 passed, 0 failed, 13 skipped @96dc450d 2026-10-07T13:10:30+02:00
Review: approve (opus/xhigh; 2 nit) · round 1
Änderung: In beiden `ssrf.py` derselbe Code (Parität): `import enum`, `UrlVerdict` und `classify_url` wie im Entwurf;
der Körper des heutigen `is_private_url` wandert nach `classify_url` (jedes `return True` wird `UNRESOLVED` oder
`PRIVATE` nach dem Entwurf, `return False` wird `ALLOWED`), `is_private_url` wird die Ein-Zeilen-Hülle. Docstrings
dürfen sich unterscheiden, Code nicht. Neue Tests in beiden `test_ssrf.py` über das dort schon importierte Modul
(`ssrf_mod.classify_url`, `ssrf_mod.UrlVerdict`), kein neues `from … import`, damit die Revert-Probe ohne die Änderung
rote Tests sieht statt eines Importfehlers: `http://127.0.0.1/` ⇒ `PRIVATE`, `http://93.184.216.34/` ⇒ `ALLOWED`,
`_resolve` per `monkeypatch` auf `None` ⇒ `UNRESOLVED`, `http://` ohne Host ⇒ `UNRESOLVED`, und für beide
Ablehnungsgründe bleibt `is_private_url` `True`. Bestehende Tests und Assertions bleiben unverändert.
Rot vorher: die neuen Tests scheitern auf main mit `AttributeError` (kein `classify_url`).
Beweis: main@bf9cee5e · `cd apps/monitoring && DATA_DIR=<scratch> SERVER_HUB_URL= .venv/bin/python -c "from app.core import ssrf; ssrf._resolve = lambda h, t: None; from app.checkers.http import HttpChecker; print(HttpChecker().run({'url': 'http://example.org/'}))"` → dreimal identisch `('unknown', 'URL zeigt auf eine private/reservierte Adresse (SSRF-Schutz)', None)`
Orakel: property — `apps/server/tests/test_ssrf_properties.py` prüft `is_private_url` gegen das `ipaddress`-Modul und bleibt unverändert grün: die Hülle antwortet wie vorher
HEAD: bf9cee5e
Semantik: docs/admin/monitoring.html:188 „Aus Sicherheitsgründen (SSRF) werden Ziele, die auf private/reservierte Adressen auflösen (z. B. 127.0.0.0/8, 10/8, 169.254.0.0/16), abgelehnt“ und docs/developer/monitoring.html:129 „SSRF-Schutz: URLs, die auf private/reservierte IP-Bereiche auflösen, werden abgewiesen.“ — die Doku nennt als Grund nur „löst privat auf“; ein Ziel, das gar nicht auflöst, als privat zu melden, beschreibt sie nicht als Absicht. Die Ablehnung selbst bleibt.
Verify: bash scripts/dev/verify.sh server monitoring --strict
Doku: keine (intern: neue Funktion, `is_private_url` antwortet wie vorher)

### T2 — Monitoring: HTTP-Check und Webhook melden ein nicht auflösbares Ziel als solches  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/checkers/http.py, apps/monitoring/app/alerter.py, apps/monitoring/tests/test_http_checker.py, apps/monitoring/tests/test_alerter.py, CHANGELOG.md
Evidenz: run.sh[quick] monitoring: 4 passed, 0 failed, 14 skipped · contracts: 1 ok @f90f7ffb 2026-10-07T13:22:05+02:00
Review: approve (opus/xhigh; 1 nit) · round 1
Änderung: Beide Module importieren `UrlVerdict` und `classify_url` statt `is_private_url` und verzweigen nach dem Grund.
`HttpChecker.run`: Start-URL `PRIVATE` wie heute; `UNRESOLVED` ⇒ `("unknown", "URL host could not be resolved (DNS
error or timeout), rejected by the SSRF guard", None)`. Redirect-Ziel `PRIVATE` wie heute (`critical`); `UNRESOLVED` ⇒
`("critical", "Redirect target could not be resolved (DNS error or timeout), rejected by the SSRF guard", None)`.
`_send_webhook`: `PRIVATE` wie heute; `UNRESOLVED` ⇒ `logger.warning("Webhook target rejected (could not be
resolved): %s", url)` und `return False, "Webhook target could not be resolved (DNS error or timeout), rejected by the
SSRF guard"`. In beiden Fällen geht kein Request hinaus. In den bestehenden Tests ändern sich nur die drei Zeilen
`monkeypatch.setattr(…, "is_private_url", …)` (`test_http_checker.py:78`, `test_alerter.py:172` und `:189`): sie
patchen `classify_url` mit `UrlVerdict.PRIVATE` bzw. `UrlVerdict.ALLOWED` — ohne sie liefe `hooks.example.com` über
echtes DNS; ihre Assertions bleiben. Neue Tests mit `app.core.ssrf._resolve` per `monkeypatch`: Start-URL nicht
auflösbar ⇒ `unknown`; Redirect von einem öffentlichen IP-Literal auf einen Host, für den der Stub `None` liefert
(für alles andere ruft er das echte `_resolve`) ⇒ `critical`; Webhook nicht auflösbar ⇒ `False` und kein
`httpx.post`. Jede neue Meldung enthält „could not be resolved“ und „SSRF“.
Rot vorher: die neuen Tests scheitern auf T1 ohne diese Änderung (Meldung „private/reservierte“ bzw. „privat/reserviert“).
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: CHANGELOG `[Unreleased]` unter `### Fixed` ein Eintrag „SSRF-Guard nennt den Grund (R-0045)“ für HTTP-Check und Alert-Webhook, transliteriert wie die übrigen (ae/oe/ue); `docs/` keine (beschreibt die Ablehnung, nicht die Meldung)
Abhängt von: T1

### T3 — Server-Hooks: `http_get`/`http_post` melden ein nicht auflösbares Ziel als solches  [x]
Komponente: server · Dateien: apps/server/app/modules/hooks/script_worker.py, apps/server/tests/test_hooks_http_ssrf.py, CHANGELOG.md
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped · contracts: 1 ok @e62b3679 2026-10-07T13:50:22+02:00
Review: approve (opus/xhigh; 1 nit) · round 1
Änderung: `script_worker.py` importiert `UrlVerdict` und `classify_url` statt `is_private_url`; `_safe_http_get` und
`_safe_http_post` werfen bei `PRIVATE` wie heute `ValueError(f"Zieladresse nicht erlaubt (SSRF-Schutz): {url}")`, bei
`UNRESOLVED` `ValueError(f"Target host could not be resolved (DNS error or timeout), rejected by the SSRF guard:
{url}")`. Die Prüfung bleibt in jeder der beiden Funktionen, kein neuer Helfer. Neue Tests in `test_hooks_http_ssrf.py`
mit `app.core.ssrf._resolve` per `monkeypatch` auf `None`: `_safe_http_get` und `_safe_http_post` werfen `ValueError`
mit „could not be resolved“, und `httpx.stream` wird nicht aufgerufen. Bestehende Tests bleiben unverändert (sie
nutzen IP-Literale, kein Patch auf `is_private_url`).
Rot vorher: die neuen Tests scheitern auf T2 ohne diese Änderung (Meldung „Zieladresse nicht erlaubt“).
Verify: bash scripts/dev/verify.sh server --strict
Doku: CHANGELOG — den Eintrag aus T2 um die Hook-Funktionen `http_get`/`http_post` ergänzen
Abhängt von: T1, T2 (der CHANGELOG-Eintrag)
