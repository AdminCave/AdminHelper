# Servernamen ohne ':' und ohne Windows-Gerätenamen — Task-Ledger
Status: bereit · Branch: feature/kern-server-7 · Review: am Ende
Spec: docs/features/kern-server-7.md (Roadmap R-1056)
Heavy: linux-full — Server-API (zusätzliche 422 in POST/PUT /api/servers), geht in den Sammellauf
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — Server: neue und umbenannte Namen ohne ':' und Windows-Gerätenamen (R-1056)  [x]
Komponente: server · Dateien: apps/server/app/modules/servers/schemas.py, apps/server/app/modules/servers/router.py, apps/server/app/modules/frp/generate_router.py, apps/server/tests/test_servers_schemas.py, apps/server/tests/test_servers_name_windows.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @dd550915a 2026-11-06T20:06:40+01:00
Review: am Ende (Branch-Review)
Änderung: `reject_windows_unsafe_server_name` in `servers/schemas.py` lehnt einen Namen mit `:` ab und einen, dessen Teil vor dem ersten Punkt (ohne Groß-/Kleinschreibung) CON, PRN, AUX, NUL, COM1–9, COM¹²³, LPT1–9 oder LPT¹²³ ist (englischer Text). `create_server` ruft sie immer, `update_server` nur bei gesendetem, gegenüber dem gespeicherten geändertem `name`; Fehler `HTTPException(422)`. Der Docstring von `_path_refused` nennt, dass diese Regel bewusst nicht im Bulk-ZIP greift (Bestand bleibt ausgeliefert). Tests: die reine Funktion (Grenzfälle `com0`, `com10`, `console`, `nul.tar.gz`, `Aux`, `COM¹`) und die Routen (POST 422, PUT auf neuen Namen 422, PUT eines Altnamens mit unverändertem Namen 200; neue Datei mit SPDX-Header).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_servers_schemas.py tests/test_servers_name_windows.py
Doku: → T2

### T2 — Doku und Changelog: Servernamen-Regel (R-1056)  [x]
Komponente: server · Dateien: docs/developer/api-reference.html, docs/en/developer/api-reference.html, changelog.d/kern-server-7.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @013ca3dce 2026-11-06T20:07:08+01:00
Review: am Ende (Branch-Review)
Änderung: Eintrag `POST /api/servers` DE+EN: der neue 422-Fall (':' und reservierte Windows-Namen, auch mit Endung) und dass ein `PUT` mit unverändertem Altnamen erlaubt bleibt; `changelog.d/kern-server-7.md` (`### Changed`, umlautfrei).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_servers_schemas.py
Doku: docs/developer/api-reference.html DE+EN · changelog.d/kern-server-7.md
Task-Review: am Ende
Abhängt von: T1
