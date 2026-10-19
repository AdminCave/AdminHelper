<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Stack-Suite: ein roter Login nennt HTTP-Code und detail — Task-Ledger
Status: bereit · Branch: feature/stack-login-diag · Review: am Ende
Spec: Roadmap R-0515
Heavy: none — nur `scripts/tests/`, kein Produkt-, Gateway-, PKI- oder Install-Pfad. Beweis vor dem Merge: `gh workflow run ci.yml --ref feature/stack-login-diag`, Job `integration-stack` grün (läuft nicht auf PRs); er fährt beide Logins über die neue Funktion auf dem grünen Pfad
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-18: „Ein Kurz-Ledger mit einer Task: Der rote Zweig gibt HTTP-Code und detail der Login-Antwort aus,
damit der nächste rote Lauf die Ursache zeigt.“ Nur Diagnose: kein Retry, kein längeres `--max-time` (CLAUDE.md §11).
Kein Secret im Log: das Passwort steht im Request, der JWT in der Antwort; ein 200-Body wird nie ausgegeben.

### T1 — Logins der Stack-Suite über `e2e_login`: rote Zweige nennen HTTP-Code, curl-Exit und detail  [x]
Komponente: scripts · Dateien: scripts/tests/lib_e2e_stack.sh, scripts/tests/lib_e2e_stack_test.sh, scripts/tests/integration_stack_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @04344bf7 2026-10-19T09:33:01+02:00
Review: am Ende (Branch-Review)
Änderung: `lib_e2e_stack.sh` bekommt neben `e2e_admin_token` (`:151`) `e2e_login <curl-args…>`: genau ein `curl -k -s <args> --max-time 5 -X POST "$E2E_SERVER_URL/api/auth/login"` als `admin` mit `$E2E_ADMIN_PW`, Status per `-w '\n%{http_code}'` wie `api()` (`integration_stack_test.sh:312-313`), fehlt der Code, gilt `000`. Die Funktion läuft in der aufrufenden Shell, gibt selbst nichts aus und setzt `E2E_JWT` (sonst leer) und `E2E_LOGIN_ERR` (bei Erfolg leer), Rückgabe 0/1. `E2E_LOGIN_ERR` ist eine Zeile auf Englisch, etwa `HTTP 401, curl exit 0, detail: <detail>`: ein String-`detail` wörtlich (Steuerzeichen zu Leerzeichen, höchstens 200 Zeichen); eine Liste (FastAPI-422) nur `loc` und `msg` je Eintrag, nie `input`, das den Request samt Passwort zurückgibt; sonst `no JSON detail`; ein 200 ohne `access_token` nur `HTTP 200, curl exit 0, no access_token`. Keine zeitabhängigen Teile, damit `first_marker` in `heavy.sh:464` dieselbe Ursache als dieselbe FAIL-Zeile erkennt. Der Kopfkommentar der Lib (`:6-11`) nennt die Funktion. In `integration_stack_test.sh` rufen beide Logins `e2e_login`, der erste (`:121-125`, Inline-Python) mit `"${CERT[@]}"`, der in `frps_takeover` (`:470-473`, `json_get`) mit `"${CERT3[@]}"`. Beide FAIL-Zeilen behalten ihren Text und hängen ` ($E2E_LOGIN_ERR)` an. Der Ablauf bleibt: Der erste Fehlschlag läuft mit leerem `JWT` weiter, der zweite endet mit `return`. `lib_e2e_stack_test.sh` bekommt `curl` als PATH-Stub wie `docker`/`openssl` (`:30-46`), der Body, Code und Exit vorgibt und seine Argumente loggt. Die Fälle: (a) 200 mit `access_token` → `E2E_JWT` gesetzt, `E2E_LOGIN_ERR` leer, rc 0; (b) 401 mit String-`detail` → Code und detail in `E2E_LOGIN_ERR`, `E2E_JWT` leer, rc 1; (c) 422 mit dem Passwort in `input` → `loc`/`msg` da, Passwort nicht; (d) curl-Exit 28, Code `000`, leerer Body → `HTTP 000, curl exit 28`; (e) 200 ohne `access_token` mit einem tokenartigen Wert → der Wert fehlt in `E2E_LOGIN_ERR`. In jedem Fall gilt: Die eigene Ausgabe von `e2e_login` (stdout+stderr) ist leer, `E2E_LOGIN_ERR` enthält weder Passwort noch Token, und es gibt genau einen curl-Aufruf mit `--max-time 5` und den durchgereichten Zertifikats-Argumenten.
Verify: bash scripts/dev/verify.sh scripts --strict -- lib_e2e_stack_test
Doku: keine (intern; der Kopfkommentar von lib_e2e_stack.sh nennt die Funktion)
Beweis: main@a23a4387 · `heavy.sh all`, Sammellauf 2026-10-18-1050: integration_stack_test `26 passed, 1 failed`, FAIL-Zeile „frps: login with the new device failed“ (`scripts/tests/integration_stack_test.sh:473`); `iter.sh integration --strict --step integration_stack` 3× auf derselben Box je `45 passed, 0 failed`; CI main a23a4387 Job `integration-stack` grün (run 39112016630). Nicht reproduzierbar, daher keine Fix-Task, sondern die Diagnose für den nächsten roten Lauf. Rot vor der Task sind die neuen Fälle in `lib_e2e_stack_test.sh` (`e2e_login` fehlt auf HEAD); Basis auf HEAD: `lib_e2e_stack_test: 20 passed, 0 failed`.
Dedup-Key: bug:scripts:integration_stack_test.sh:frps-login-flaky
HEAD: a23a4387
Semantik: docs/developer/api-reference.html:61 — „Body: `{ "username", "password" }`. Antwort: `{ "access_token", "refresh_token", "token_type" }`.“; docs/developer/cicd.html:40 — „… den vollen Pfad prüft – Enrollment-Token, CSR → Enroll-Plane (:8444) → Client-Cert, certless → abgewiesen, Cert+JWT → 200“. Wie ein roter Zweig der Stack-Suiten berichtet: keine Stelle in docs/ — gesucht `integration_stack`, `FAIL`, `auth/login` in docs/ und DEVELOPMENT.md.
