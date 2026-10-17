<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# frps-Supervisor: Konfiguration und Zertifikate selbst übernehmen — Task-Ledger
Status: aktiv · Branch: feature/frps-supervisor · Review: pro Task
Spec: Roadmap R-0411
Heavy: linux-full + scenario --tunnel --enforce — neues frps-Image mit Supervisor, neue Compose-Volumes und das Übernehmen von Konfiguration und Zertifikaten lassen sich nur im echten Stack belegen (`run.sh integration`); der Tunnel-Datenpfad über Hosts mit einem frps-Neustart mitten im Lauf nur im Multibox-Lauf `--tunnel --enforce` (vor dem Merge, Kevin 2026-10-16)
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Kevin 2026-10-16: frps läuft unter einem Supervisor aus eigenem Image `apps/frps`, startet nur mit vollständiger, von
AdminHelper erzeugter Konfiguration und übernimmt Konfigurations- und Zertifikatsänderungen selbst. Eine neue, ungültige
Konfiguration wird nicht übernommen: frps läuft mit der letzten gültigen weiter, Admins sehen den Fehler auf der
FRP-Seite und in der Glocke. Wird die FRP-Konfiguration gelöscht, stoppt frps. Jeder Neustart durch eine übernommene
Änderung geht als Mitteilung an Admins und Nutzer mit Tunnel-Zugriff (bei neuem Token mit dem Hinweis, dass
Agent-Tunnel bis zu ~5 min brauchen); die Web-Maske sagt es vor dem Speichern. Ein `bind_port`, der nicht zum
Compose-Mapping passt, ist nur ein Warnhinweis. Leeres `auth_token` im PUT heißt „unverändert“.
**PR merged Kevin:** T10–T12 und T15/T16 ändern `.github/` und `scripts/` (CLAUDE.md §2).

### T1 — Server: frps.toml atomar schreiben, beim Start in beide Richtungen abgleichen  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/docker_manager.py, apps/server/app/main.py, apps/server/tests/test_frp_docker_manager.py, apps/server/tests/test_config_generator.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @b2a95925 2026-10-16T13:36:00+02:00
Review: approve (.ah-out/review/frps-supervisor/T1.verdict.json)
Änderung: `write_frps_config` (`docker_manager.py:17-47`) schreibt in eine Temp-Datei im selben Verzeichnis (0600, `fsync`) und tauscht per `os.replace`; die `warn_restart`-Warnung (`:40-46`) wird eine Info-Zeile, dass frps die Änderung selbst übernimmt. `remove_frps_config` (`:50-55`) ist best effort: ein `OSError` wird geloggt, nie geworfen (die DB ist die Quelle). `_ensure_frps_config` (`main.py:169-185`) löscht eine vorhandene `frps.toml`, wenn keine FRP-Config in der DB existiert. Neue Testdatei (SPDX-Header), test-first: Austausch atomar (kein Leser sieht eine halbe Datei, Modus 0600), Löschen mit `OSError` wirft nicht, Start ohne DB-Config entfernt die Datei, mit DB-Config schreibt er sie.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_docker_manager.py
Doku: keine (intern)
Test-Löschung: apps/server/tests/test_config_generator.py::test_write_frps_config_warns_only_on_runtime_change — gewolltes Verhalten geändert (Info statt Warnung), ersetzt durch test_frp_docker_manager.py::test_a_runtime_change_logs_that_frps_applies_it_itself (Kevin 2026-10-16)

### T2 — Server: leeres `auth_token` im PUT lässt das Token unverändert  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/config_router.py, apps/server/tests/test_frp_config.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @b72fd28a 2026-10-16T14:18:21+02:00
Review: approve (.ah-out/review/frps-supervisor/T2.verdict.json)
Änderung: In `update_server_config` (`config_router.py:118-132`) wird `auth_token` nur übernommen, wenn es gesendet und nicht leer ist; `""` und `null` lassen das gespeicherte Token stehen. Tests in `test_frp_config.py`, erst rot: PUT mit `auth_token: ""` und mit `null` ändert das Token nicht, ein neues Token ≥ 16 Zeichen wird übernommen, ein kurzes bleibt 422.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_config.py
Doku: keine (intern)

### T3 — Server: Statusdatei des Supervisors streng lesen  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/supervisor_status.py, apps/server/app/core/config.py, apps/server/tests/test_frp_supervisor_status.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @f00f0a14 2026-10-16T14:30:45+02:00
Review: approve (.ah-out/review/frps-supervisor/T3.verdict.json)
Änderung: Neues Modul (SPDX-Header) `read_supervisor_status(path)` liest `status.json` aus `FRPS_STATE_DIR` (neu in `core/config.py` neben `FRP_CONFIG_DIR`, `:72`; dazu `FRP_BIND_PORT`, Default 7000): höchstens 4096 Bytes, JSON-Objekt mit genau den Schlüsseln `v, boot, heartbeat, state, reason, since, appliedHash, rejectedHash, events`; Enums für `state` (`waiting|running|degraded|stopped|crashloop`), `reason` und `event` (`started|applied|rejected|stopped|crashed`), `boot` 16 hex, Hashes 64 hex oder `null`, ISO-UTC-Zeiten, höchstens 8 Ereignisse mit `seq`, `event`, `at`, `reason`, `tokenChanged`. Jede Abweichung, fehlende oder zu große Datei ergibt einen Zustand `unreadable` bzw. `missing`, nie eine Ausnahme; `heartbeat` älter als 60 s setzt `stale`. Tests: gültige Datei, jede Regel einzeln verletzt, 4097 Bytes, fehlende Datei, Herzschlag zu alt.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_supervisor_status.py
Doku: keine (intern)

### T4 — Server: `GET /api/frp/supervisor-status`  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/status_router.py, apps/server/app/modules/frp/schemas.py, apps/server/tests/test_frp_supervisor_status.py, apps/server/tests/openapi.snapshot.json, docs/developer/api-reference.html, docs/en/developer/api-reference.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @545a2c3f 2026-10-16T14:41:57+02:00
Review: approve (.ah-out/review/frps-supervisor/T4.verdict.json)
Änderung: Neue Admin-Route neben `/status` (`status_router.py:39`) mit Antwortmodell `FrpSupervisorStatus` (`state`, `reason`, `since`, `stale`, `lastEvent`, `lastEventAt`, `publishedBindPort` aus `FRP_BIND_PORT`). Tests: Admin sieht den Zustand, Nicht-Admin 403, fehlende Datei → `missing`, `publishedBindPort` aus der Umgebung. OpenAPI-Snapshot nachziehen; API-Referenz DE+EN.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_supervisor_status.py tests/test_openapi_snapshot.py
Doku: docs/developer/api-reference.html + docs/en/developer/api-reference.html
Abhängt von: T3

### T5 — Server: Mitteilung direkt an bestimmte Nutzer  [x]
Komponente: server · Dateien: apps/server/app/modules/notifications/service.py, apps/server/tests/test_notifications.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @00b36fd6 2026-10-16T14:51:28+02:00
Review: approve (.ah-out/review/frps-supervisor/T5.verdict.json)
Änderung: Neue Funktion `notify_users(db, users, event)` neben `ingest_event` (`service.py:157`): schreibt je Nutzer eine Glocken-Zeile ohne Abo-Auflösung und ohne Outbox (keine E-Mail/Telegram), danach den SSE-Anstoß wie `ingest_event` (`:203-206`). Tests: genau die übergebenen Nutzer erhalten eine Zeile, keine Outbox-Zeile, leere Liste schreibt nichts.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_notifications.py
Doku: keine (intern)

### T6 — Server: Scheduler-Job meldet Ereignisse des Supervisors  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/supervisor_watch.py, apps/server/app/modules/hooks/scheduler.py, apps/server/app/scheduler_main.py, apps/server/tests/test_frp_supervisor_watch.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @c4c667d9 2026-10-16T15:11:48+02:00
Review: approve (.ah-out/review/frps-supervisor/T6.verdict.json)
Änderung: Neues Modul (SPDX-Header): liest den Status (T3) und schreibt für jedes Ereignis im Ring, das noch keine Mitteilung hat (Schlüssel `source_type="frps"`, `source_id="<boot>:<seq>"`), eine Mitteilung: `applied` → Admins und Nutzer mit Tunnel-Zugriff (Admins ∪ per `user_servers` einem Server mit mindestens einem aktiven Tunnel zugewiesen, vgl. `get_allow_users`, `frp/_helpers.py:80`), Schwere `info`, bei `tokenChanged` mit dem Agent-Hinweis (~5 min); `rejected` und `crashed` → Admins, `warning`; `stopped` → Admins, `info`; `started` → keine. Registrierung wie `schedule_hook_reconcile` (`hooks/scheduler.py:236-247`), alle 15 s, Aufruf in `scheduler_main.py:68-90`. Tests: jedes Ereignis erreicht die richtigen Nutzer, zweiter Lauf schreibt nichts doppelt, `unreadable`/`missing` schreibt nichts, Texte enthalten keinen Wert aus der Datei außer Codes.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_supervisor_watch.py
Doku: keine (intern)
Abhängt von: T3, T5

### T7 — frps-Image mit Supervisor: Start nur mit vollständiger Konfiguration  [x]
Komponente: server · Dateien: apps/frps/Dockerfile, apps/frps/frps-supervisor.sh, apps/server/tests/test_frps_supervisor.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @a63b124d 2026-10-16T16:07:11+02:00
Review: approve (.ah-out/review/frps-supervisor/T7.verdict.json)
Änderung: Neues Image (SPDX-Header in beiden Dateien): `FROM snowdreamtech/frps:0.69.1@sha256:a615a3e42f174050fbd902a989f9c21eed2dc0b016932d10ab599743cca0e41a`, entfernt die mitgelieferte Beispielkonfiguration (der Supervisor verwaltet die Konfiguration allein), Entrypoint `/bin/sh /usr/local/bin/frps-supervisor.sh`. Der Supervisor prüft eine Kandidaten-Konfiguration: `frps.toml` nicht leer, `auth.token` ≥ 16 Zeichen, `[transport.tls] force = true`, die drei TLS-Pfade zeigen auf `/etc/frp-pki/{frps.crt,frps.key,ca.crt}`, die Dateien existieren, das Leaf ist nicht abgelaufen und passt zum Schlüssel (`openssl`), `frps verify` grün. Gültig → Kopie mit umgeschriebenen Pfaden nach `$FRPS_ACTIVE_DIR/current/` (atomar über `next/`), frps startet immer von dort; ungültig ohne `current/` → `waiting`, nichts startet; ungültig mit `current/` → frps startet mit `current/`, Zustand `degraded`. Statusdatei (Schema wie T3) atomar schreiben, Pfade per Env überschreibbar. Test (pytest treibt das Skript mit einem Stub-`frps` auf `PATH`, Zertifikate per `cryptography` erzeugt): jede Prüfregel einzeln, Start mit gültiger, ungültiger und fehlender Konfiguration, Statusdatei besteht den Leser aus T3.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor.py
Doku: keine (intern)
Abhängt von: T3

### T8 — Supervisor: Änderungen übernehmen, Neustart, Abbruch, Signale  [x]
Komponente: server · Dateien: apps/frps/frps-supervisor.sh, apps/server/tests/test_frps_supervisor.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @620b4265 2026-10-16T17:01:07+02:00
Review: approve (.ah-out/review/frps-supervisor/T8.verdict.json)
Änderung: Schleife alle `FRPS_POLL_SECONDS` (Default 5): `sha256` über `frps.toml` und die drei PEM-Dateien; gehandelt wird erst, wenn ein neuer Wert zwei Abfragen lang gleich bleibt. Gültig → übernehmen, frps beenden (TERM, nach 10 s KILL) und neu starten, Ereignis `applied` mit `tokenChanged` (Vergleich des Hashes der Token-Zeile, nie das Token selbst); ungültig → frps läuft weiter, Ereignis `rejected` einmal je abgelehntem Hash; `frps.toml` fehlt oder ist leer → frps stoppen, `current/` löschen, Ereignis `stopped`. frps endet unerwartet → Neustart mit `current/` nach 2, 4, 8 … ≤ 60 s, ab drei Abbrüchen in 60 s Zustand `crashloop` und einmal `crashed`. TERM/INT an den Supervisor wird an frps weitergereicht, Exit 0. Unterbefehl `health`: gesund bei `waiting|running|stopped`. Herzschlag in jeder Abfrage. Tests mit kurzem Intervall: identisch neu geschriebene Dateien → kein Neustart; Token geändert → genau ein Neustart mit `tokenChanged`; halb geschriebene Datei → erst nach Stabilität; ungültig → kein Neustart, `rejected` einmal; gelöscht → gestoppt; Stub-frps stirbt → Backoff, `crashloop`; TERM → Kind beendet.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor.py
Doku: keine (intern)
Abhängt von: T7

### T9 — Compose: frps aus eigenem Image, Status- und Arbeits-Volume  [x]
Komponente: server · Dateien: docker-compose.yml, docker-compose.test.yml, .env.example, apps/server/tests/test_compose_frps.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @da64d93c 2026-10-16T17:44:45+02:00
Review: approve (.ah-out/review/frps-supervisor/T9.verdict.json)
Änderung: Dienst `frps` (`docker-compose.yml:276-306`): `image: ${FRPS_IMAGE:-ghcr.io/admincave/adminhelper/frps:latest}`, `frp-config` im Langformat mit `read_only: true` und `volume: { nocopy: true }`, `frps-certs` ro wie bisher, neu `frps-state` (rw) und `frps-active` (rw, nur frps), Healthcheck über `frps-supervisor.sh health`. `server` und `scheduler`: `frps-state` ro unter `/app/frps-state`, Env `FRPS_STATE_DIR` und `FRP_BIND_PORT=${FRP_BIND_PORT:-7000}`. Volumes anlegen (`:408-416`). `docker-compose.test.yml`: `frps` mit `image: adminhelper-test/frps:latest` und `build: { context: apps/frps }` (Muster gateway, `:43-52`). `.env.example`: `FRPS_IMAGE` neben `GATEWAY_IMAGE` (`:8`). Neue Testdatei (SPDX, Muster `tests/test_compose_startup_order.py`): die Mounts und Rechte je Dienst, `frps-active` nur in frps, `nocopy`, Env im Server und Scheduler.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_compose_frps.py
Doku: keine (intern)
Abhängt von: T7

### T18 — Supervisor: Dateirechte, Prüfung vor jedem Start, veröffentlichter Port, zwei neue Gründe  [x]
Komponente: server · Dateien: apps/frps/frps-supervisor.sh, apps/server/tests/test_frps_supervisor.py, apps/server/app/modules/frp/supervisor_status.py, apps/server/tests/test_frp_supervisor_status.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html, apps/server/app/modules/frp/supervisor_watch.py, apps/server/tests/test_frp_supervisor_watch.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @aff876c0 2026-10-16T19:10:22+02:00
Review: approve (.ah-out/review/frps-supervisor/T18.verdict.json)
Änderung: `umask 077` am Skriptanfang (Arbeitskopien nur für den Supervisor lesbar; `status.json` bleibt ausdrücklich 0644 für den Server). Vor jedem `start_frps`, auch beim Neustart nach einem Abbruch, läuft `check_config` erneut auf `current/`; besteht die Kopie nicht, startet nichts, Zustand und Grund wie bei einer ungültigen Eingabe ohne gültige Kopie. Eingaben (`frps.toml`, die drei PEM-Dateien) werden nur als reguläre Dateien gelesen, Symlinks und andere Dateitypen gelten als ungültig; Kopieren und Hashen mit Zeitlimit. Neue Env `FRP_BIND_PORT` (aus Compose, T9): ist sie gesetzt, darf `webServer.port` auch diesen Wert nicht belegen. Zwei neue Gründe (Kevin, 2026-10-16), im Supervisor und in `REASONS` des Lesers (`supervisor_status.py:47`): `input_unreadable` — eine Eingabedatei ist da, aber nicht lesbar, keine reguläre Datei oder ein Symlink (statt `config_missing`); `input_unstable` — die Eingabe ändert sich über mehrere Abfragen in Folge (Schwelle als Env mit Default, etwa 30 s), sie wird nicht übernommen: mit laufendem frps `degraded`, ohne gültige Kopie `waiting`; zurück, sobald sie stabil ist. API-Referenz DE+EN nennt beide Codes. Tests zuerst rot: geänderte `current/frps.toml` + Abbruch → kein Start mit der geänderten Kopie; Symlink als `frps.toml` → `input_unreadable`; nicht lesbare `frps.toml` → `input_unreadable`; FIFO als PEM-Datei → kein Hänger (Zeitlimit); Eingabe ändert sich jede Abfrage → `input_unstable`, danach stabil → übernommen; `webServer.port = FRP_BIND_PORT` → `verify_failed`; Rechte der Arbeitskopien 0600/0700, `status.json` 0644; der Leser nimmt beide neuen Codes an.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor.py tests/test_frp_supervisor_status.py tests/test_frp_supervisor_watch.py
Doku: docs/developer/api-reference.html + docs/en/developer/api-reference.html (Reason-Codes)
Abhängt von: T8

### T19 — frps unter eigener UID, Supervisor bleibt root  [x]
Komponente: server · Dateien: apps/frps/Dockerfile, apps/frps/frps-supervisor.sh, docker-compose.yml, apps/server/tests/test_frps_supervisor.py, apps/server/tests/test_compose_frps.py, apps/server/app/modules/frp/supervisor_status.py, apps/server/tests/test_frp_supervisor_status.py, apps/server/app/modules/frp/supervisor_watch.py, apps/server/tests/test_frp_supervisor_watch.py, docs/developer/api-reference.html, docs/en/developer/api-reference.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @4f9f57be 2026-10-17T03:59:04+02:00
Review: approve (.ah-out/review/frps-supervisor/T19.verdict.json)
Änderung: Das Image legt einen eigenen Nutzer für frps an; der Supervisor (root) startet frps per `su-exec` unter dieser UID (Kevin, 2026-10-16). frps kann `current/`, `frps-active` und `frps-state` nur lesen, wo nötig (Arbeitskopie über Gruppe lesbar, z. B. `current/` 0750 root:frps, Dateien 0640; T18-Rechte entsprechend anpassen), und nirgends schreiben. Compose: `cap_add` um genau die Capabilities, die der Supervisor dafür braucht (laut Probe in T9: SETUID, SETGID, KILL, ggf. CHOWN oder `group_add`), weiter ohne MKNOD; frps selbst hat keine Capabilities. Der Start per `su-exec` ist per Env abschaltbar, damit die sh-Tests ohne root laufen. Tests zuerst rot: im Docker-Fall läuft frps mit UID ≠ 0 und CapEff 0, kann weder `current/frps.toml` noch `status.json` schreiben, liest Konfiguration und Schlüssel, Neustart und Stopp (TERM/KILL über UIDs hinweg) funktionieren; Compose-Test prüft die Capability-Liste. Wie gebaut (2026-10-16): UID/GID 10002; Arbeitskopie root-eigen und für frps nur lesbar (`FRPS_ACTIVE_DIR` 0711, `current/` 0755, Dateien 0644, ohne CHOWN); vor jedem Start Vergleich eines Hashes über die Kopie samt PEMs, bei Abweichung verwerfen, neu übernehmen und neues Ereignis `copy_changed` (Admin-Mitteilung); Eingaben höchstens 1 MiB (`input_unreadable`); beim Stopp und vor jedem Start beendet der Supervisor als root alle Prozesse des frps-Nutzers (Suche in `/proc`, mit Zeitgrenze `FRPS_KILL_SECONDS`); bleibt einer übrig, startet frps nicht (Zustand `waiting`, Grund `processes_left`, Ereignis `start_refused`, Admin-Mitteilung). Dritte Prüfrunde auf Kevins Wort (2026-10-17).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frps_supervisor.py tests/test_compose_frps.py tests/test_frp_supervisor_status.py tests/test_frp_supervisor_watch.py tests/test_openapi_snapshot.py
Doku: keine (intern; Betrieb in T17)
Abhängt von: T9, T18

### T10 — Pipeline: frps-Image bauen und veröffentlichen  [x]
Komponente: server · Dateien: .github/workflows/ci.yml, .github/workflows/docker.yml, .github/workflows/release.yml, apps/server/tests/test_release_images.py, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @486026d3 2026-10-17T04:23:20+02:00
Review: approve (.ah-out/review/frps-supervisor/T10.verdict.json)
Änderung: `frps` in die Build-Matrix von `ci.yml` (`:635-646`) und `docker.yml` (`:31-42`), in die Manifest-Prüfung von `release.yml` (`:510`); `frp-consistency` (`ci.yml:664-690`, heute `:676` aus `docker-compose.yml`) liest die frps-Version künftig aus `apps/frps/Dockerfile`. Neue Testdatei (SPDX): die Image-Listen in `ci.yml`, `docker.yml`, `release.yml` stimmen überein und enthalten `frps`; die frps-Version im Dockerfile ist gleich `FRP_VERSION` in `ci.yml` und `release.yml`. **Harness-Pfad: PR merged Kevin.**
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_release_images.py
Doku: keine (intern)
Abhängt von: T7

### T11 — Install und Update pinnen das frps-Image  [x]
Komponente: scripts · Dateien: scripts/install.sh, scripts/update.sh, scripts/tests/update_test.sh, scripts/tests/install_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @e56a6186 2026-10-17T04:54:54+02:00
Review: approve (.ah-out/review/frps-supervisor/T11.verdict.json)
Änderung: `install.sh` (`:231`) und `update.sh` (`:358-362`, Rollback `:375-380`) setzen `FRPS_IMAGE=ghcr.io/admincave/adminhelper/frps:<Version>` wie `GATEWAY_IMAGE`. `update_test.sh` (`:111`) bekommt den Key in der Ausgangs-`.env` und prüft Pin und Rollback. Test zuerst rot. **Harness-Pfad: PR merged Kevin.**
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test update_test
Doku: keine (intern)
Abhängt von: T9

### T12 — Risikopfade: `apps/frps/` aufnehmen  [ ]
Komponente: scripts · Dateien: scripts/dev/review-risk.txt
Änderung: `apps/frps/*` unter „FRP tunnels“ (`review-risk.txt:42`). **Harness-Pfad: PR merged Kevin.**
Verify: bash scripts/dev/verify.sh scripts --strict -- review_scripts_test
Doku: keine (intern)
Abhängt von: T7

### T13 — Web: Zustand des frps auf der FRP-Seite  [ ]
Komponente: web · Dateien: apps/web/src/lib/api/frp.ts, apps/web/src/pages/Frp.svelte, apps/web/src/lib/i18n/dictionaries.ts, apps/web/src/pages/Frp.test.ts
Änderung: `supervisorStatus()` in `frp.ts` (Muster `status()`, `:49`); `Frp.svelte` zeigt einen Statusblock (Zustand, Grund als übersetzter Text je Code, seit wann, „antwortet nicht“ bei `stale`), Aktualisierung beim Öffnen und alle 30 s. Texte DE+EN in `dictionaries.ts`, nur aus Codes. Neue Testdatei (SPDX): jeder Zustand und `stale` erzeugen den erwarteten Text, unbekannter Code fällt auf einen allgemeinen Text.
Verify: bash scripts/dev/verify.sh web --strict -- src/pages/Frp.test.ts
Doku: keine (intern)
Abhängt von: T4

### T14 — Web: Hinweis vor dem Speichern, Port-Warnung  [ ]
Komponente: web · Dateien: apps/web/src/modals/FrpConfigModal.svelte, apps/web/src/lib/i18n/dictionaries.ts, apps/web/src/modals/FrpConfigModal.test.ts
Änderung: Beim Bearbeiten (`FrpConfigModal.svelte:57-93`) fragt die Maske vor dem Speichern nach, wenn sich ein Feld außer `name` und `server_addr` ändert oder ein Token eingetippt ist: Speichern startet den FRP-Server neu, alle Tunnel sind einige Sekunden getrennt; bei neuem Token zusätzlich, dass Agent-Tunnel bis zu ~5 Minuten brauchen. Weicht `bind_port` von `publishedBindPort` (T4) ab, steht eine Warnung am Feld; Speichern bleibt möglich. Texte DE+EN. Neue Testdatei (SPDX): Rückfrage nur bei relevanten Änderungen, Token-Hinweis nur mit Token, Port-Warnung bei Abweichung, Abbrechen sendet nichts.
Verify: bash scripts/dev/verify.sh web --strict -- src/modals/FrpConfigModal.test.ts
Doku: keine (intern)
Abhängt von: T4

### T15 — Stack-Test: Übernahme im echten Stack  [ ]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh, scripts/tests/desktop_e2e_tunnel.sh, scripts/tests/desktop_e2e_connect_tunnel.sh
Änderung: Neuer Abschnitt in `integration_stack_test.sh` (vor Abschnitt 12, `:279`): frps läuft vor jeder FRP-Konfiguration und antwortet auf `:7000` nicht per TLS (TLS-Probe, nicht `nc -z`); nach dem Anlegen erscheint innerhalb von 20 s die PKI-Kette; identisches PUT löst keinen Neustart aus (Ereignis-`seq` unverändert); neues Token → genau ein Neustart und eine Mitteilung; eine ungültige Zertifikatsdatei im Volume → frps bleibt erreichbar, Zustand `degraded`; Löschen → `:7000` antwortet nicht mehr. `desktop_e2e_tunnel.sh:57` und `desktop_e2e_connect_tunnel.sh:119`: `up -d --build frps`. **Harness-Pfad: PR merged Kevin.**
Verify: bash scripts/dev/verify.sh scripts --strict -- lib_e2e_stack_test
Doku: keine (intern)
Abhängt von: T6, T9

### T16 — Multibox: frps-Neustart im Tunnel-Szenario  [ ]
Komponente: scripts · Dateien: scripts/tests/box_serverbox.sh, scripts/tests/multibox.sh, scripts/tests/multibox_test.sh
Änderung: `box_serverbox.sh` baut frps mit (`:59` in die `--build`-Liste, `:235` ohne eigenes `up`); im `--tunnel`-Szenario nach dem ersten erfolgreichen Visitor-Durchgang die FRP-Konfiguration ändern (z. B. `max_ports_per_client`), dann prüfen: frps startet genau einmal neu, der Agent verbindet sich ohne Eingriff wieder, eine neue Visitor-Verbindung geht durch. `multibox_test.sh` deckt die neue Etappe hermetisch ab. **Harness-Pfad: PR merged Kevin.**
Verify: bash scripts/dev/verify.sh scripts --strict -- multibox_test
Doku: keine (intern)
Abhängt von: T9

### T17 — Doku und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, docs/admin/installation.html, docs/en/admin/installation.html, CHANGELOG.md
Änderung: `frp-tunnel.html` DE+EN: Architektur (`:41-48`) mit frps-Image und Supervisor; „FRP `auth.token` rotieren“ (`:65-74`): kein manueller Neustart mehr, frps übernimmt nach wenigen Sekunden, alle Tunnel sind kurz getrennt, Mitteilung an Admins und Tunnel-Nutzer, Agent-Tunnel bis ~5 min, eine abgelehnte Konfiguration steht auf der FRP-Seite und in der Glocke; Status-Dashboard (`:107`) mit dem neuen Statusblock. `installation.html` DE+EN: frps lauscht, sobald FRP im Web-Interface eingerichtet ist. CHANGELOG unter `### Changed`.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/frp-tunnel.html + docs/en/admin/frp-tunnel.html · docs/admin/installation.html + docs/en/admin/installation.html · CHANGELOG.md (Changed)
Abhängt von: T8, T13, T14
