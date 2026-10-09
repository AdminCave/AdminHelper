<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server-Kleinpaket 2: SSRF-Schutz bei kaputtem IPv6-Literal, 422 der Hooks im versprochenen Format — Task-Ledger
Status: freigegeben · Branch: feature/server-kleinpaket-2 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-09 (kleines Fund-Paket aus R-0181 und R-0207, von Kevin in der Triage angenommen; Delegation Kevin 2026-10-05). Offene Fragen entschieden: 1 T3 ja (Kevin, 2026-10-09, sichtbares Verhalten); 2 Heavy linux-full bleibt (Aufsicht: Fehler-Format der Server-API); 3 ein Parse-Fehler ergibt PRIVATE (Aufsicht, fail closed wie der Docstring)
Spec: Roadmap R-0181, R-0207 (Kurz-Ledger ohne Spec)
Heavy: linux-full — die Hook-API antwortet auf ungültige Eingaben in einem anderen Fehler-Format, und die Web-Oberfläche liest es; `run.sh integration` mit `web_live` gegen den echten Stack.
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber bzw. eslint/prettier, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-09 von Worker B im Auftrag der Aufsicht (adminhelper-ac) aus zwei Zeilen, die Kevin angenommen hat
(R-0207 in der Triage vom 2026-10-06 mit dem Zielbild „422 im Format, das die OpenAPI verspricht“). Die private Roadmap
ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht. R-0181 ist gegen origin/main@7129dc57
nachgeprüft und nicht erledigt (Beweis unter T1). Zeilenangaben main@7129dc57.

### T1 — `classify_url` wirft bei einem kaputten IPv6-Literal nicht mehr, sondern lehnt ab (R-0181)  [ ]
Komponente: server · Dateien: apps/server/app/core/ssrf.py, apps/monitoring/app/core/ssrf.py, apps/server/tests/test_ssrf.py, apps/monitoring/tests/test_ssrf.py
Änderung: `classify_url` ruft `urlparse(url)` ungeschützt auf (`ssrf.py:138`, in beiden Kopien gleich), und `urlparse`
wirft bei `http://[::1`, `http://[` oder `https://[::1:8443/x` einen `ValueError` („Invalid IPv6 URL“). Damit platzt die
Ausnahme bei den Aufrufern: `script_worker.py:55`/`:73` im Server; `alerter.py:392` und `checkers/http.py:32`/`:62` im
Monitoring, wo die URL beim Redirect aus einem fremden `Location`-Header stammt.
- Ein Fehler beim Zerlegen der URL ergibt `UrlVerdict.PRIVATE`, fail closed.
- Begründung für PRIVATE: Der Docstring von `is_private_url` verspricht „a parse error … counts as private“, und der von
  `classify_url` zählt „an unreadable address“ zu PRIVATE.
- Beide Kopien ändern sich gleich; `tests/test_ssrf_parity.py` hält sie gleich.

Tests in beiden `test_ssrf.py`: die drei Eingaben ergeben PRIVATE, `is_private_url` True, ohne Ausnahme. Rot vor dem Fix.
Beweis: main@7129dc57, in `apps/server` mit dem devenv:
`python3 -c "from app.core.ssrf import classify_url; classify_url('http://[::1')"` → `ValueError: Invalid IPv6 URL`.
Dasselbe für `http://[`, `http://[fe80::1%25eth0` und `https://[::1:8443/x`; `http://[::1]:80/` ergibt korrekt PRIVATE.
Die Monitoring-Kopie ist zeilengleich.
HEAD: 7129dc57
Semantik: `docs/admin/monitoring.html:56`: „http-Checks und Alert-Webhooks lehnen private/reservierte Ziele weiterhin ab
(SSRF-Schutz)“. Ablehnen heißt ein Urteil, keine Ausnahme. Wörtlich zum Zerlegen sagt es nur der Docstring von
`is_private_url` (`ssrf.py:167`): „Fail-closed: an unresolvable host, a parse error, or an unspecified/mapped address counts
as private“.
Verify: bash scripts/tests/run.sh quick --strict --only server monitoring
Doku: keine (die Doku verspricht das Verhalten schon)

### T2 — Hooks: 422 im Format `HTTPValidationError` (R-0207)  [ ]
Komponente: server · Dateien: apps/server/app/modules/hooks/router.py, apps/server/tests/test_hooks.py, apps/server/tests/schemathesis_exclude.toml, CHANGELOG.md
Änderung: Fünf Stellen in `hooks/router.py` antworten mit `HTTPException(422, detail=<String>)`:
- `_validate_schedule_interval` (`:85`, „Ungültiges Intervall …“), geteilt von create und update;
- `_validate_create`: `event_triggers` fehlt (`:96`), ein unbekanntes Event (`:101`), `schedule_interval` fehlt (`:106`);
- `update_hook`: ein unbekanntes Event (`:261`).

Die OpenAPI verspricht für 422 `HTTPValidationError`, also `detail` als Liste von `{loc, msg, type}`.
- Die Stellen werfen künftig `fastapi.exceptions.RequestValidationError` mit einem Eintrag:
  `loc = ("body", "<feld>")`, `msg` mit dem bisherigen Text, `type = "value_error"`, `input` = der abgelehnte Wert.
  FastAPIs eigener Handler rendert ihn im versprochenen Format; einen eigenen Handler hat die App nicht.
- Die Prüfungen bleiben, wo sie sind; die Texte bleiben gleich.
- Der Ausschluss `create_hook_api_hooks_post` in `tests/schemathesis_exclude.toml` (`until` = R-0207) entfällt. Schemathesis
  prüft das Format danach selbst.

Tests in `test_hooks.py`: je Stelle ein 422 mit `detail` als Liste, mit dem erwarteten `loc` und `msg`; create und update.
Kein bestehender Test prüft die Strings, also ändert sich keine Assertion.
CHANGELOG unter Fixed: Die Hook-Routen antworten auf ungültige Eingaben im dokumentierten Fehler-Format.
Beweis: main@7129dc57:
- `sed -n 106,108p apps/server/app/modules/hooks/router.py` zeigt das `HTTPException` mit String-`detail`.
- Der Ausschluss in `schemathesis_exclude.toml` nennt den Lauf vom 2026-10-06: `POST /api/hooks` mit
  `{"hook_type": "schedule", "schedule_interval": null, …}` → 422 mit String-`detail`.
- `update_hook` trifft dasselbe über `_validate_schedule_interval`. Schemathesis sieht es dort nicht, weil zufällige
  `hook_id`s vorher mit 404 enden.

HEAD: 7129dc57
Semantik: `docs/developer/api-reference.html`, Abschnitt „Fehler-Format“ (EN „Error Format“, `:207`): „HTTP/1.1 422
Unprocessable Entity … { "detail": [ { "loc": ["body", "port"], "msg": "ensure this value is less than 65536", "type":
"value_error" } ] }“.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hooks.py
Doku: CHANGELOG.md (Fixed); die API-Referenz zeigt das Format schon

### T3 — Web: ein 422 mit `detail` als Liste zeigt die Meldung statt „HTTP 422“  [ ]
Komponente: web · Dateien: apps/web/src/lib/api/client.ts, apps/web/src/lib/api/client.test.ts
Änderung: Nur bei Ja zu offener Frage 1, sonst `ledger.sh mark-skip` mit Verweis auf die Antwort.
- Heute übernimmt `request` nur ein `detail` vom Typ String als Meldung (`client.ts:119`), sonst `HTTP <status>`.
- Damit zeigte der Hook-Dialog nach T2 für ein ungültiges Cron-Intervall nur noch „HTTP 422“. Diese Prüfung macht nur
  der Server; `HookModal.svelte` prüft Event und Intervall-Wahl vorab, die Cron-Syntax nicht.
- Künftig gilt: Ist `detail` eine Liste von Objekten mit `msg` als String, wird die Meldung aus diesen `msg`
  zusammengesetzt, mit „; “ verbunden. Ein String bleibt wie heute, alles andere bleibt `HTTP <status>`.
- Das gilt für jedes 422 der Web-Oberfläche, auch für die Pydantic-Fehler, die heute schon „HTTP 422“ zeigen.

Tests in `client.test.ts`:
- eine Liste mit einem und mit zwei Einträgen;
- ein String wie bisher;
- eine Liste ohne `msg` ergibt `HTTP 422`.
Beweis: `sed -n 117,121p apps/web/src/lib/api/client.ts` auf main@7129dc57 nimmt nur `typeof data.detail === 'string'`;
`HookModal.svelte:114` zeigt den Fehler über `showError(err)` → `err.message`.
HEAD: 7129dc57
Semantik: wie T2, die API-Referenz nennt die Liste als Fehler-Format. Wie die Web-Oberfläche sie anzeigt, beschreibt
docs/ nicht (offene Frage 1).
Verify: bash scripts/dev/verify.sh web --strict
Doku: keine (Anzeige; der CHANGELOG-Eintrag aus T2 nennt sie mit)
Abhängt von: T2
