<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server: Eingaben der FRP-Server-Konfiguration und Fehlertexte der Hooks — Task-Ledger
Status: aktiv · Branch: feature/server-frp-hook-checks · Review: pro Task
Spec: keine eigene Datei (kleines Paket, Reihenfolge Kevin 2026-10-19)
Heavy: linux-full — T2 ändert den Vertrag der FRP-API (`422` für einen Dashboard-Port, den frps nicht übernimmt), T1 die Eingabeprüfung derselben API; Server-Tests in der PR-CI, der Stack im Sammellauf über `main`; kein `scenario`, weil der FRP-Datenpfad unverändert bleibt; kein `windows`, weil nur der Server betroffen ist
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Hängt ab von: desktop-hardening (`feature/desktop-hardening`) wegen `apps/server/app/modules/frp/schemas.py` (dort T6, `_reject_toml_breakers`, direkt über `_check_secret`). Gebaut wird nach dessen Merge; Zeilenangaben gelten für `main@5481b316` und werden beim Baustart neu gegreppt. Risikopfad FRP: `security`-Prüfer nach `review.sh risk`.

Ziel: (1) Ein Geheimnis der FRP-Konfiguration (`auth_token`, `dashboard_password`, `secret_key`) braucht 16 Zeichen ohne Leerzeichen am Anfang und Ende; ein Wert aus Leerzeichen ist kein Geheimnis. (2) Einen Dashboard-Port, den frps nicht übernimmt (443, der Bind Port, `FRP_BIND_PORT`), weist schon die API mit `422` ab, nicht erst der Start von frps. (3) Bricht ein Hook mit einem Datenbankfehler ab, nennen `error` und das Hook-Log nur den Fehlertyp, nicht den Text des Treibers.

Entscheidungen (Kevin 2026-10-19): Ein gespeichertes leeres `auth_token` bleibt, frps startet damit nicht; die Startprüfung meldet es schon (R-0411), hier kommt nur der Testfall dazu (T1). Der Dashboard-Port wird an der API mit `422` abgewiesen (T2). Bestandswerte bleiben unangetastet (keine Datenmigration).

### T1 — Geheimnisse: 16 Zeichen ohne Leerzeichen am Rand  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/tests/test_frp_config.py, apps/server/tests/test_frp_extra_config.py, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, CHANGELOG.md
Änderung: `_check_secret` (`schemas.py:34`) misst die Länge des Werts ohne Leerzeichen am Anfang und Ende; unter 16 Zeichen ist es ein `422` mit englischem Text („must have at least 16 characters besides leading and trailing whitespace“). Der gespeicherte Wert bleibt, wie er gesendet wurde; leer oder `null` bleibt „automatisch erzeugen“ bzw. „unverändert“. Gilt für `auth_token`, `dashboard_password` (`:161`, `:191`) und `secret_key` (`:223`, `:247`). Tests: 16 Leerzeichen, 15 Zeichen plus Leerzeichen am Rand je Feld → `422`; 16 Zeichen mit Leerzeichen innen → angenommen; leer → wie bisher. Zum Starttest `test_startup_tells_the_admins_once_about_a_token_frps_is_not_started_with` (`test_frp_extra_config.py:555`) ein Eintrag mit leerem `auth_token`: gemeldet, Zeile unverändert.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_config.py tests/test_frp_extra_config.py
Doku: docs/admin/frp-tunnel.html + docs/en/admin/frp-tunnel.html (`:69`, `:102`: „mindestens 16 Zeichen, Leerzeichen am Anfang und Ende zählen nicht“) · CHANGELOG
Abhängt von: —

### T2 — Dashboard-Port: 422 statt Startfehler  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/app/modules/frp/config_router.py, apps/server/app/main.py, apps/server/tests/test_frp_config.py, docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, CHANGELOG.md
Änderung: Eine reine Funktion in `schemas.py` sagt, ob ein Dashboard-Port mit 443, dem Bind Port oder `FRP_BIND_PORT` zusammenfällt; `_report_rejected_fields` (`main.py:243`) nutzt sie statt der eigenen Prüfung. `FrpServerConfigCreate` (`schemas.py:142`) weist einen solchen Port mit `422` ab (Bind Port aus der Anfrage, sonst 7000). `update_server_config` (`config_router.py:107`) prüft nach dem Übernehmen der gesendeten Felder (`:119-131`) und vor dem Commit, wenn `dashboard_port` oder `bind_port` gesendet wurde, gegen den Stand danach und antwortet mit `422` im Format der Schema-Fehler; ein PUT ohne diese beiden Felder auf einer Bestandszeile mit solchem Port geht weiter durch (die Startprüfung meldet sie). Tests: Create mit 443, = Bind Port, = `FRP_BIND_PORT` → `422`, nichts gespeichert; Update nur `dashboard_port` bzw. nur `bind_port` → `422`, Zeile unverändert; Update nur `name` auf solcher Bestandszeile → `200`; ein anderer Port → angenommen; die Starttests aus `test_frp_extra_config.py:585` bleiben grün.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_config.py tests/test_frp_extra_config.py
Doku: docs/admin/frp-tunnel.html + docs/en/admin/frp-tunnel.html (`:83`: die API weist ihn mit `422` ab; eine schon gespeicherte Zeile meldet die Startprüfung) · CHANGELOG
Abhängt von: T1

### T3 — Hook-Fehler aus der Datenbank nur mit Typ  [ ]
Komponente: server · Dateien: apps/server/app/modules/hooks/script_worker.py, apps/server/tests/test_hook_isolation.py, docs/developer/hooks.html, docs/en/developer/hooks.html, CHANGELOG.md
Änderung: Der Fehlerzweig des Workers (`script_worker.py:171-178`) schreibt für einen Fehler der Datenbankanbindung (`sqlalchemy.exc.SQLAlchemyError`, `psycopg.Error`) nur `type(exc).__name__` in `error` und in die Log-Zeile `Fehler: …`; andere Fehler eines Hooks behalten ihren Text. Tests über `run_hook_script` (der echte Worker-Prozess): ein Hook, der `load_connections()` gegen eine nicht erreichbare Datenbank-URL mit einem Merkwort in der URL ruft, liefert `success: false`, und weder `error` noch `logs` enthalten das Merkwort, wohl aber den Fehlertyp; ein Hook mit `raise ValueError("…")` behält seinen Text. Nur Adressen nach RFC 5737 oder Loopback mit geschlossenem Port.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_hook_isolation.py
Doku: docs/developer/hooks.html + docs/en/developer/hooks.html (`:97` „Fehlerverhalten“: ein Datenbankfehler erscheint nur mit seinem Typ) · CHANGELOG
Abhängt von: —
