<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Fuzz-Gate deterministisch (R-0063) — Task-Ledger
Status: erledigt · Branch: harness/fuzz-gate-determinism · Commit-Granularität: pro Task · Review: pro Task (feature-review; Harness-Pfade ⇒ Reviewer Opus) · Modell: Opus
Freigabe: Kevin, 2026-09-30 („alle freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: docs/features/fuzz-gate-determinism.md (Roadmap R-0063)
Heavy: none — nur Test-Konfiguration, Test-Stubs, ein Lint und Request-Schranken im Monitoring-Schema; kein Stack-, Gateway-, PKI- oder Install-Pfad. Die Tiefe (alle Phasen, 100 Beispiele) bleibt im Wochenlauf; ein grüner Wochenlauf nach dem Merge ist die Evidenz dafür.
DoD je Task: CLAUDE.md (Tests grün, ruff check + ruff format + shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-09-30 von der Aufsicht (adminhelper-ac) auf Kevins Wort (Entscheidungen 2026-09-30: PR-Gate nur
`Phase.explicit`, Monitoring-Schranken statt Allowlist, `hypothesis`/`schemathesis` exakt pinnen, R-0058 abgelehnt
und Proxy-Stub, ein Ledger mit fünf Tasks). Branch `harness/`, weil `scripts/tests/run.sh` und
`.github/workflows/ci.yml` Harness-Pfade sind: Bau interaktiv, keine Lane. Server-Suiten nur mit eigener Test-DB.

### T1 — Beweis-Instrument: zwei gleiche Läufe, ein `curl`-Diff  [x]
Komponente: scripts · Dateien: scripts/tests/schemathesis_determinism.sh, scripts/tests/schemathesis_curl_log.py, scripts/tests/schemathesis_determinism_test.sh, scripts/tests/run.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @3b2a5696 2026-10-02T10:54:19+02:00
Review: approve nach 2 Runden (opus): Sanitization aus, compare fail-closed (unlesbar, ohne Newline, NUL)
Änderung: Neues Skript (SPDX) `schemathesis_determinism.sh [--only <dienste…>]`: fährt je Dienst den
Schemathesis-Lauf (`pytest -q -m schemathesis` wie `run.sh:651–683`) zweimal mit einem pytest-Plugin
`schemathesis_curl_log.py` (SPDX; per `-p` geladen, patcht `Case.call_and_validate` und schreibt je Fall
`case.as_curl_command()` in eine Datei, ohne die Testdateien anzufassen) und vergleicht die beiden Protokolle.
Ausgabe je Dienst `<dienst>: N cases, M differing lines`; Exit 0 nur, wenn beide Läufe liefen, gleich viele
Fälle > 0 hatten und 0 Zeilen abweichen. Ein Start- oder Sammelfehler, ein leeres Protokoll oder ein roter
pytest-Lauf ist Exit 1 (nie grün). Hermetischer Test `schemathesis_determinism_test.sh` über die Auswertung
mit Fixture-Protokollen (gleich → 0, abweichend → 1, leer → 1, nur ein Lauf → 1), eingetragen in
`AH_SCRIPT_TESTS_DEFAULT` (`run.sh:557–560`).
Beweis: origin/main@8224e84c · `bash scripts/tests/schemathesis_determinism.sh --only monitoring` → rot mit
„monitoring: 3915 cases, 942 differing lines“ (Zahlen vom Explorer der Aufsicht, 2026-09-30; der Bau misst neu).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (T5)

### T2 — PR-Gate nur `Phase.explicit`, Versionen exakt gepinnt  [x]
Komponente: scripts · Dateien: apps/server/tests/test_schemathesis.py, apps/monitoring/tests/test_schemathesis.py, apps/ca-issuer/tests/test_schemathesis.py, scripts/tests/run.sh, .github/workflows/ci.yml, apps/server/requirements-dev.txt, apps/monitoring/requirements-dev.txt, apps/ca-issuer/requirements-dev.txt, scripts/tests/schemathesis_determinism.sh, scripts/tests/schemathesis_determinism_test.sh
Evidenz: run.sh[quick] scripts server monitoring ca-issuer: 12 passed, 0 failed, 6 skipped @84e043b7 2026-10-02T11:55:56+02:00
Review: request_changes (opus) → W1/W2 behoben, W1 per Test + Gegenprobe belegt; nits miterledigt
Änderung: In den drei `test_schemathesis.py` (`MAX_EXAMPLES` bei server :139, monitoring :140, ca-issuer
:133; `@settings` bei :242–263, :205–210, :188–193): `AH_SCHEMATHESIS_EXAMPLES=0` heißt
`phases=[Phase.explicit]` (dann `max_examples=1`, falls Hypothesis 0 ablehnt); jede Zahl > 0 wie bisher alle
Phasen. `run.sh:652` Default `:-5` → `:-0`, Kommentar `:638`; `ci.yml:320` `"5"` → `"0"`, Kommentar
`:318–319`. `heavy.sh:76` (100) und `scripts/vm/iter.sh:183–187` bleiben; `iter_flags_test.sh` bleibt grün.
Die Kommentare der drei Suiten (server `:136–138`, `:244–254`) sagen, was gilt. Pins: `hypothesis==` und
`schemathesis==` in allen drei `requirements-dev.txt` (server `:22–23`, monitoring `:18–19`, ca-issuer `:20`
plus eine neue `hypothesis`-Zeile), in genau den Versionen, die die letzte grüne CI des Jobs „Schema fuzzing“
auflöst (aus ihrem Log, nicht aus der Dev-Box). Die Jobs `python-lock-*` installieren `requirements-dev.txt`
über den Lock; `lock-pins.py` muss dort grün bleiben.
Beweis: T1-Instrument auf origin/main rot (Monitoring); nach T2 `--only server monitoring ca-issuer` 0 Zeilen.
Verify: bash scripts/tests/run.sh unit --strict --step schemathesis --only scripts server monitoring ca-issuer
Zusatzbeleg: bash scripts/tests/schemathesis_determinism.sh --only server monitoring ca-issuer → je Dienst 0 abweichende Zeilen (Summary in die Evidenz)
Doku: keine (T5)
Abhängt von: T1

### T3 — Lint „jeder Integer-Eingang hat ein `maximum`“, Monitoring-Schranken  [x]
Komponente: monitoring · Dateien: apps/server/tests/test_openapi_integer_bounds.py, apps/monitoring/tests/test_openapi_integer_bounds.py, apps/ca-issuer/tests/test_openapi_integer_bounds.py, apps/monitoring/app/schemas.py, apps/monitoring/app/core/bounds.py, CHANGELOG.md, apps/monitoring/tests/openapi.snapshot.json
Evidenz: run.sh[quick] server monitoring ca-issuer: 6 passed, 0 failed, 12 skipped @1f916266 2026-10-02T12:12:06+02:00
Review: approve (sonnet), nit Selbsttest miterledigt
Änderung: Je Dienst ein neuer Test (SPDX) über `app.openapi()`: jedes `integer` auf der Request-Seite
(Parameter und Request-Bodies, `$ref` aufgelöst, auch in `anyOf` und `items`) hat `maximum` oder
`exclusiveMaximum`; FastAPIs eigene `ValidationError`/`HTTPValidationError` zählen nicht; die Meldung nennt
jedes Feld. Monitoring: Schranken über `app/core/bounds.py` (neben `Offset` :28) für die Felder in
`schemas.py:27, :47, :56, :66, :78, :120, :183, :185` — Domänengrenze, wo das Modell eine hat (`weekdays`
0–6, heute nur im Validator :196–200), sonst die int32-Obergrenze wie bei R-0052. Server und CA-Issuer: der
Lint ist heute voraussichtlich grün (Server laut Explorer 0 Treffer; CA-Issuer nicht geprüft) und pinnt den
Stand. Ist er es nicht, gleiche Regel.
Beweis: origin/main@8224e84c · der Monitoring-Lint nennt heute die Felder oben (Planung: 8 über `app.openapi()`,
Explorer: 12); gegen den alten Stand rot.
oasdiff: eine neue Obergrenze ist `request-property-max-set warn` (`scripts/dev/oasdiff-severity.levels:9`),
kein ERR; `bash scripts/dev/openapi-breaking.sh monitoring` bleibt Exit 0 (Zusatzbeleg).
Verify: bash scripts/tests/run.sh quick --strict --only server monitoring ca-issuer
Doku: CHANGELOG [Unreleased] „Changed“ (Monitoring lehnt Werte über den neuen Schranken mit 422 ab); docs/ keine (die Felder sind dort ohne Grenzen beschrieben, prüfen)

### T4 — Stub für den Proxy-Client des Servers, die fünf `raises`-Ausschlüsse fallen  [x]
Komponente: server · Dateien: apps/server/tests/test_schemathesis.py, apps/server/tests/schemathesis_exclude.toml
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped @d7f4e27f 2026-10-02T12:35:24+02:00
Review: approve (sonnet)
Änderung: Eine Fixture ersetzt für die Schemathesis-Suite `monitoring_proxy_mod._client`
(`app/modules/monitoring_proxy/router.py:42`, geschlossen in `app/main.py:230`) durch einen
`httpx.AsyncClient` mit `httpx.MockTransport` je Test (eine feste 200-JSON-Antwort genügt; der Vertrag des
Proxys ist nicht Gegenstand), und stellt den Originalclient danach wieder her. Die fünf Proxy-Einträge in
`schemathesis_exclude.toml:178–211` (`proxy_to_monitoring_api_monitoring__path__{get,put,post,delete}`,
`proxy_agent_report_…`) fallen; `notification_stream` (:213ff) bleibt. Der Kopf der Datei nennt die Änderung.
Beweis: origin/main@8224e84c ohne die fünf Einträge → `4 failed, 304 passed` (`proxy_agent_report` in allen
vier Kontexten, `RuntimeError … client has been closed`; Explorer 2026-09-30); nach T4 grün.
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (intern)

### T5 — Doku: was der PR-Gate prüft und was der Wochenlauf  [x]
Komponente: scripts · Dateien: DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @7302011b 2026-10-02T12:46:56+02:00
Review: approve (sonnet), nit miterledigt
Änderung: `DEVELOPMENT.md:107–116`: die Aussage „reproduzierbar bei gleichem Baum“ ist widerlegt; stattdessen:
der PR-Gate (lokal und CI, `AH_SCHEMATHESIS_EXAMPLES=0`) fährt nur die expliziten Phasen und ist
deterministisch, der Wochenlauf fährt alle Phasen mit 100 Beispielen und schreibt Funde in die Roadmap; der
Integer-Lint ersetzt die bekannte Klasse; die Versionen sind gepinnt; `schemathesis_determinism.sh` ist das
Prüfwerkzeug. `docs/developer/cicd.html:251` und `docs/en/developer/cicd.html:249` (Zeile Schema-Fuzzing)
entsprechend. CHANGELOG [Unreleased] ein Eintrag.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: die Task ist die Doku
Abhängt von: T2, T3, T4

### T6 — Nachträge aus /code-review: Domänengrenze duration_minutes, wirksame 422-Tests, Protokoll-Kodierung, Pin-Satz  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/core/bounds.py, apps/monitoring/app/schemas.py, apps/monitoring/tests/test_openapi_integer_bounds.py, apps/monitoring/tests/openapi.snapshot.json, scripts/tests/schemathesis_curl_log.py, DEVELOPMENT.md, CHANGELOG.md
Evidenz: run.sh[quick] monitoring scripts: 10 passed, 0 failed, 8 skipped @2b3e9907 2026-10-02T13:25:10+02:00
Review: approve (sonnet), nit miterledigt
Herkunft: /code-review über den Branch-Diff (2026-10-02)
Änderung: (1) `duration_minutes` trägt die Domänengrenze des Modells (1..1440, Validator `_kind_fields`) im Schema statt der
int32-Spanne, wie es die Regel aus T3 verlangt (Typ `WindowMinutes` in `bounds.py`); der Desktop sendet bei `once` `null`, bei
`weekly` 1..1440. (2) Die 422-Tests prüfen, dass die Feldschranke greift (`detail[].type` und `loc` des Felds), nicht nur
irgendeine 422 — zwei Zeilen fing schon vorher ein Validator. (3) Das curl-Protokoll schreibt `ensure_ascii=True`, damit ein
einzelnes Surrogat den Messlauf nicht mit falscher Ursache rot macht. (4) DEVELOPMENT.md: Die Pins gelten im CI-Job und in
jedem run.sh-Lauf, dessen pytest-Schritte `requirements-dev.txt` installieren; ein nackter `--step schemathesis` nimmt das
venv, wie es ist. CHANGELOG-Eintrag aus T3 nachziehen.
Verify: bash scripts/tests/run.sh quick --strict --only monitoring scripts
Doku: DEVELOPMENT.md (Teil der Task), CHANGELOG

Abschluss-Evidenz (2026-10-02):
- Instrument (T1) auf dem alten Gate (5 Beispiele, alle Phasen): `monitoring: 3915 cases, 5968 differing lines`, exit 1.
  Nach T2 (Vergleich je Test, weil pytest-randomly die Testreihenfolge mischt) mit dem neuen Gate (0, nur explicit):
  `server: 9576 cases, 0 differing lines`, `monitoring: 3552 cases, 0 differing lines`, `ca-issuer: 177 cases, 0 differing lines`,
  exit 0. Gegenprobe mit 5 Beispielen: `monitoring: 4062 cases, 930 differing lines`, exit 1.
- Pins: hypothesis==6.168.3, schemathesis==4.29.0. Der Job „Schema fuzzing“ nennt keine Versionen (pip -q); die Lock-Jobs desselben
  grünen Laufs 36983502860 zeigen sie, die Aufsicht hat das bestätigt.
- T3: Der Monitoring-Lint fand 12 Einträge (acht Felder); oasdiff monitoring exit 0, nur WARN. T4: ohne Stub `4 failed, 304 passed`
  (proxy_agent_report, client has been closed), mit Stub `308 passed`.
- /code-review über den Branch-Diff: zehn Punkte. Vier wurden T6 (Domänengrenze duration_minutes, wirksame 422-Tests,
  Protokoll-Kodierung, Pin-Satz); vier gingen als Roadmap-Kandidaten an die Aufsicht; der Rest bleibt unverändert, begründet in der
  Übergabe.
- Nach dem Merge von origin/main (abef751a, mit #65): `run.sh quick --strict` → `18 passed, 0 failed, 0 skipped, 12 test-skips,
  0 reruns`; danach T6 per task-close `run.sh[quick] monitoring scripts: 10 passed, 0 failed`.
- Heavy: none. Der nächste grüne Wochenlauf nach dem Merge ist die Evidenz für die Tiefe (alle Phasen, 100 Beispiele).
