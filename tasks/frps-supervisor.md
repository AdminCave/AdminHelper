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
Änderung: Neues Image (SPDX-Header in beiden Dateien): `FROM snowdreamtech/frps:0.69.1@sha256:a615a3e42f174050fbd902a989f9c21eed2dc0b016932d10ab599743cca0e41a`, der Supervisor verwaltet `/etc/frp` allein, Entrypoint `/bin/sh /usr/local/bin/frps-supervisor.sh`. Der Supervisor prüft eine Kandidaten-Konfiguration: `frps.toml` nicht leer, `auth.token` ≥ 16 Zeichen, `[transport.tls] force = true`, die drei TLS-Pfade zeigen auf `/etc/frp-pki/{frps.crt,frps.key,ca.crt}`, die Dateien existieren, das Leaf ist nicht abgelaufen und passt zum Schlüssel (`openssl`), `frps verify` grün. Gültig → Kopie mit umgeschriebenen Pfaden nach `$FRPS_ACTIVE_DIR/current/` (atomar über `next/`), frps startet immer von dort; ungültig ohne `current/` → `waiting`, nichts startet; ungültig mit `current/` → frps startet mit `current/`, Zustand `degraded`. Statusdatei (Schema wie T3) atomar schreiben, Pfade per Env überschreibbar. Test (pytest treibt das Skript mit einem Stub-`frps` auf `PATH`, Zertifikate per `cryptography` erzeugt): jede Prüfregel einzeln, Start mit gültiger, ungültiger und fehlender Konfiguration, Statusdatei besteht den Leser aus T3.
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

### T20 — Compose: Port 443 ohne Engine-Default, Grund bei verweigertem Start bleibt sichtbar  [x]
Komponente: server · Dateien: docker-compose.yml, apps/server/tests/test_compose_frps.py, apps/frps/frps-supervisor.sh, apps/server/tests/test_frps_supervisor.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @f94b0358 2026-10-17T05:23:01+02:00
Review: approve (.ah-out/review/frps-supervisor/T20.verdict.json)
Änderung: Der frps-Dienst bekommt `sysctls: { net.ipv4.ip_unprivileged_port_start: 0 }` (Kevin, 2026-10-17): frps bindet 443 ohne Capability unabhängig vom Default der Engine; eine zu alte Engine oder ein zu alter Kernel scheitert laut bei `up` statt still. Der Compose-Test prüft den Eintrag, der Docker-Fall bindet 443 mit genau den Compose-Einstellungen. Außerdem: Verweigert `start_frps` bei ungültiger Eingabe und vorhandener Kopie den Start (`processes_left`), überschreibt `take_over` den Grund nicht mehr mit dem der Eingabe; der Status zeigt `processes_left`, wie die API-Referenz sagt. Tests zuerst rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_compose_frps.py tests/test_frps_supervisor.py
Doku: keine (intern; Betrieb in T17)
Abhängt von: T19

### T21 — update.sh: Rollback, wenn das Ziehen der Images scheitert  [x]
Komponente: scripts · Dateien: scripts/update.sh, scripts/tests/update_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @0e9ddb5b 2026-10-17T05:40:06+02:00
Review: approve (.ah-out/review/frps-supervisor/T21.verdict.json)
Änderung: Scheitert `docker compose pull` nach dem Austausch der Dateien und dem Neu-Pinnen (Netz, Rate-Limit, nicht veröffentlichtes Image), rollt `update.sh` auf den installierten Stand zurück und endet mit einer klaren Meldung, statt abzubrechen und `.env`/Compose auf dem neuen Stand zu lassen (Kevin, 2026-10-17). Gilt für alle Images. Test zuerst rot in `update_test.sh`: Pull-Stub scheitert → Dateien und Pins wieder auf dem alten Stand, Exit ≠ 0, Meldung nennt den Rollback; ein folgendes `update.sh` versucht das Update erneut statt „bereits aktuell“ zu melden. **Harness-Pfad: PR merged Kevin.**
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test
Doku: keine (intern; Betrieb in T17)
Abhängt von: T11

### T22 — update.sh: Rollback auch bei Floating-Tags und nach einem gescheiterten Agent-Repo-Abgleich  [x]
Komponente: scripts · Dateien: scripts/update.sh, scripts/tests/update_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @5f4a9ebb 2026-10-17T06:24:29+02:00
Review: approve (.ah-out/review/frps-supervisor/T22.verdict.json)
Änderung: Aus den Reviews von T21 (2026-10-17): (1) Der Rollback nach gescheitertem Health-Check stellt bei `INSTALLED=unknown` (Floating-Tag, z. B. `:latest`/`:main`) die Image-Pins aus der in T21 angelegten Kopie der alten `.env` wieder her, sonst meldet der nächste Lauf „bereits aktuell“ und der alte Stand läuft still weiter; übrige neue Keys und Secrets bleiben, weil Container schon gelaufen sind. (2) Scheitert `update_agent_repo` nach dem Neu-Pinnen, rollt `update.sh` wie beim Pull-Fehler zurück. (3) Fehlt `.env`, bricht `update.sh` mit eigener Meldung vor Backup und Snapshot ab. (4) Die alte `.env` wird atomar zurückgespielt (Kopie daneben, dann `mv`). (5) `--no-rollback` mit Pull-Fehler nennt in der Meldung den Ausweg (`--redeploy` bzw. `--ref <tag>`). Tests zuerst rot in `update_test.sh`: Health-Fail mit Floating-Tag → Pins zurück, nächster Lauf versucht erneut; Agent-Repo-Fehler → Rollback; fehlende `.env` → Abbruch ohne Backup; Meldung bei `--no-rollback`. **Harness-Pfad: PR merged Kevin.**
Verify: bash scripts/dev/verify.sh scripts --strict -- update_test
Doku: keine (intern; Betrieb in T17)
Abhängt von: T21

### T12 — Risikopfade: `apps/frps/` aufnehmen  [x]
Komponente: scripts · Dateien: scripts/dev/review-risk.txt
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @4388d54f 2026-10-17T06:34:54+02:00
Review: approve (.ah-out/review/frps-supervisor/T12.verdict.json)
Änderung: `apps/frps/*` unter „FRP tunnels“ (`review-risk.txt:42`). **Harness-Pfad: PR merged Kevin.**
Verify: bash scripts/dev/verify.sh scripts --strict -- review_scripts_test
Doku: keine (intern)
Abhängt von: T7

### T13 — Web: Zustand des frps auf der FRP-Seite  [x]
Komponente: web · Dateien: apps/web/src/lib/api/frp.ts, apps/web/src/pages/Frp.svelte, apps/web/src/lib/i18n/dictionaries.ts, apps/web/src/pages/Frp.test.ts, apps/web/tests/e2e/mocks.ts, apps/web/src/lib/api/mocks.contract.test.ts, apps/web/tests/e2e/smoke.spec.ts-snapshots/frp-chromium-linux.png
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @53ea3171 2026-10-17T07:10:19+02:00
Review: approve (.ah-out/review/frps-supervisor/T13.verdict.json)
Änderung: `supervisorStatus()` in `frp.ts` (Muster `status()`, `:49`); `Frp.svelte` zeigt einen Statusblock (Zustand, Grund als übersetzter Text je Code, seit wann, „antwortet nicht“ bei `stale`), Aktualisierung beim Öffnen und alle 30 s. Texte DE+EN in `dictionaries.ts`, nur aus Codes. Neue Testdatei (SPDX): jeder Zustand und `stale` erzeugen den erwarteten Text, unbekannter Code fällt auf einen allgemeinen Text.
Verify: bash scripts/dev/verify.sh web --strict -- src/pages/Frp.test.ts
Doku: keine (intern)
Abhängt von: T4

### T14 — Web: Hinweis vor dem Speichern, Port-Warnung  [x]
Komponente: web · Dateien: apps/web/src/modals/FrpConfigModal.svelte, apps/web/src/lib/i18n/dictionaries.ts, apps/web/src/modals/FrpConfigModal.test.ts, apps/web/src/lib/components/ui/ConfirmDialog.svelte, apps/web/src/lib/components/ui/ConfirmDialog.test.ts
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped @bf7c6c74 2026-10-17T07:48:09+02:00
Review: approve (.ah-out/review/frps-supervisor/T14.verdict.json)
Änderung: Beim Bearbeiten (`FrpConfigModal.svelte:57-93`) fragt die Maske vor dem Speichern nach, wenn sich ein Feld außer `name` und `server_addr` ändert oder ein Token eingetippt ist: Speichern startet den FRP-Server neu, alle Tunnel sind einige Sekunden getrennt; bei neuem Token zusätzlich, dass Agent-Tunnel bis zu ~5 Minuten brauchen. Weicht `bind_port` von `publishedBindPort` (T4) ab, steht eine Warnung am Feld; Speichern bleibt möglich. Texte DE+EN. Neue Testdatei (SPDX): Rückfrage nur bei relevanten Änderungen, Token-Hinweis nur mit Token, Port-Warnung bei Abweichung, Abbrechen sendet nichts. Entscheidungen Kevin 2026-10-17: Escape bricht jede Rückfrage ab und schließt immer die oberste Ebene; eine offene Rückfrage endet mit „Abbrechen“, wenn die Sitzung endet — beides app-weit in `ConfirmDialog.svelte`.
Verify: bash scripts/dev/verify.sh web --strict -- src/modals/FrpConfigModal.test.ts src/lib/components/ui/ConfirmDialog.test.ts
Doku: keine (intern)
Abhängt von: T4

### T23 — Server: Ports der FRP-Server-Config im Bereich 1–65535, `bind_port` beim Update nicht null  [x]
Komponente: server · Dateien: apps/server/app/modules/frp/schemas.py, apps/server/tests/test_frp_input_hardening.py, apps/server/tests/openapi.snapshot.json, apps/server/app/modules/frp/config_generator.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @348ded14 2026-10-17T08:31:29+02:00
Review: approve (.ah-out/review/frps-supervisor/T23.verdict.json)
Änderung: Entscheidung Kevin 2026-10-17 (Review T14): `FrpServerConfigCreate`/`FrpServerConfigUpdate` (`schemas.py:100ff`/`:123ff`) nehmen `bind_port`, `vhost_https_port` und `dashboard_port` nur im Bereich 1–65535 an (eigener Port-Typ, verschachtelt annotiert, `ge`/`le` je Feld im JSON-Schema geprüft); ein ausdrückliches `"bind_port": null` im Update ist ein 422 (fehlend bleibt erlaubt und lässt den Wert unverändert), damit der Generator nie `bindPort = None` schreibt. `max_ports_per_client` nimmt nur Werte ≥ 0 an (0/leer = Default 16, Kevin 2026-10-17); die Tunnel-Ports bleiben, wie sie sind. Guard im Generator (Kevin 2026-10-17): Bestandszeilen mit `bind_port` NULL oder außerhalb 1–65535 ergeben `bindPort`/`serverPort` 7000, `vhost_https_port`/`dashboard_port` außerhalb des Bereichs fallen weg, ein negatives `max_ports_per_client` ergibt den Default; je Fall eine Log-Zeile, keine Datenmigration. Tests zuerst rot in `test_frp_input_hardening.py`: 0, -1, 65536 und `null` je Feld abgelehnt, 1 und 65535 angenommen, Update ohne `bind_port` lässt ihn stehen; OpenAPI-Snapshot nachziehen (`pytest tests/test_openapi_snapshot.py --update-openapi-snapshot`).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_input_hardening.py tests/test_openapi_snapshot.py
Doku: keine (CHANGELOG in T17)
Abhängt von: T14

### T24 — openapi-compat: genaue Ausnahme für die verengten FRP-Ports (`--err-ignore`)  [x]
Komponente: scripts · Dateien: scripts/dev/openapi-breaking.sh, scripts/dev/oasdiff-err-ignore.txt, scripts/tests/openapi_breaking_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html, .github/workflows/ci.yml, scripts/vm/bootstrap_linux.sh, scripts/dev/toolchain-lockstep.sh, scripts/tests/toolchain_lockstep_test.sh, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @e9ae78ed 2026-10-17T12:02:12+02:00
Review: approve (.ah-out/review/frps-supervisor/T24.verdict.json)
Änderung: Entscheidung Kevin 2026-10-17: T23 verengt die Grenzen von `bind_port`/`vhost_https_port`/`dashboard_port` und hebt das Minimum von `max_ports_per_client` auf 0 (oasdiff `request-property-max-decreased`/`-min-increased`) und nimmt `null` für `bind_port` im PUT heraus (`request-property-list-of-types-narrowed`) — 13 ERR im Pflicht-Check `openapi-compat` (die Liste druckt `openapi-breaking.sh server`). Statt die Regeln global herunterzustufen, bekommt `openapi-breaking.sh` eine Ignore-Datei (`--err-ignore`, offizielle oasdiff-Option), die genau diese Änderungen an POST/PUT `/api/frp/server-config` nennt (Zeilenformat gegen oasdiff 1.32.0 belegen: wie Methode/Pfad und Beschreibung verglichen werden). Fehlt die Datei, bleibt das Gate streng. `openapi_breaking_test.sh` prüft zuerst rot: die 13 Änderungen sind mit der Datei grün, eine zusätzliche verengte Grenze an einem anderen Feld oder Endpunkt bleibt ERR, ohne Datei ist alles ERR. `cicd.html` DE+EN beschreibt die Ausnahme-Datei neben der WARN-Liste. **Harness-Pfad** (Kevin 2026-10-17). Entscheidung Kevin 2026-10-17 (Frage des Bauers): der CI-Job `ops-scripts` installiert oasdiff 1.32.0 wie `openapi-compat` (Release-Tarball, gepinnte SHA-256), damit `openapi_breaking_test` dort die echten Fälle fährt; `.github/workflows/ci.yml` gehört deshalb zu T24. Review Runde 1 (Kevin 2026-10-17): auch `scripts/vm/bootstrap_linux.sh` installiert oasdiff 1.32.0 als Tarball mit gepinnter SHA-256 (sonst ist `run.sh --strict` auf den Boxen und damit linux-full rot); `toolchain-lockstep.sh` hält Version und Hash zwischen `ci.yml` und Bootstrap gleich; `DEVELOPMENT.md` nennt oasdiff als Abhängigkeit der Pflicht-Suite.
Verify: bash scripts/dev/verify.sh scripts --strict -- openapi_breaking_test toolchain_lockstep_test
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html
Abhängt von: T23

### T25 — Server: der Scheduler-Prozess lädt alle ORM-Modelle  [x]
Komponente: server · Dateien: apps/server/app/model_registry.py, apps/server/app/main.py, apps/server/app/scheduler_main.py, apps/server/tests/test_model_registry.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @31d9a1e9 2026-10-17T12:42:00+02:00
Review: approve (.ah-out/review/frps-supervisor/T25.verdict.json)
Änderung: Entscheidung Kevin 2026-10-17 (Fund aus T15, besteht auf main und in v0.45.0): Der Scheduler-Prozess importiert nur die Module seiner Jobs; die Modell-Importe stehen als Nebenwirkung in `app/main.py` (`:21-57`). Mit den Scheduler-Importen scheitert `configure_mappers()` (`'Connection' has no attribute 'server_id'` bzw. `ProvisionToken` → `'Server'`), damit jeder Job mit DB-Zugriff; APScheduler loggt das nur. Neue Datei `app/model_registry.py` (SPDX) importiert alle ORM-Modelle an einer Stelle; `main.py` und `scheduler_main.py` importieren sie, bevor Jobs geplant werden. Test zuerst rot (neue Datei, SPDX): in einem frischen Interpreter (Subprozess) mit genau den Scheduler-Importen läuft `configure_mappers()` durch; jedes `app/modules/*/models.py` ist in der Registry (gegen Drift). Der Stack-Test aus T15 belegt die Mitteilung über den Scheduler.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_model_registry.py tests/test_scheduler_schema_gate.py
Doku: CHANGELOG in T17 (Fixed: Scheduler-Jobs mit DB-Zugriff)

### T26 — Server: alter Outbox-Rückstau verfällt beim Update  [x]
Komponente: server · Dateien: apps/server/alembic/versions/c3e5a7b9d1f2_expire_stale_outbox.py, apps/server/tests/test_outbox_expiry_migration.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @4489945a 2026-10-17T13:00:06+02:00
Review: approve (.ah-out/review/frps-supervisor/T26.verdict.json)
Änderung: Entscheidung Kevin 2026-10-17 (Folge aus T25): Der Scheduler hat seit v0.38.0 nichts aus `notification_outbox` zugestellt; mit T25 ginge der Rückstau (bis ~4 Monate, an damals gespeicherte Adressen) beim ersten Drain raus. Neue Alembic-Revision (SPDX, `down_revision` = aktueller Kopf per `alembic heads`): ausstehende Einträge (`status = 'pending'`), deren `created_at` älter als 7 Tage ist, werden `failed` mit `last_error` „expired before delivery“; neuere bleiben `pending` und gehen normal raus; `downgrade()` ist ein No-op (Daten-Revision, nicht umkehrbar — im Docstring begründet). Die Glocke (Notifications) bleibt unberührt. Test zuerst rot (neue Datei, SPDX): Upgrade auf einer DB mit alten, neuen und schon `sent`/`failed`-Einträgen → nur die alten `pending` werden `failed`, `attempts` unverändert; zweites Upgrade-Szenario ohne Einträge läuft durch; Kette: `test_alembic_builtin.py` (PR-CI). Auf Postgres prüfen (Zeitvergleich mit timezone-aware `created_at`).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_outbox_expiry_migration.py tests/test_alembic_builtin.py
Doku: CHANGELOG in T17

### T15 — Stack-Test: Übernahme im echten Stack  [x]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh, scripts/tests/desktop_e2e_tunnel.sh, scripts/tests/desktop_e2e_connect_tunnel.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @04db3d8a 2026-10-17T13:24:32+02:00
Review: approve (.ah-out/review/frps-supervisor/T15.verdict.json)
Änderung: Neuer Abschnitt in `integration_stack_test.sh` (vor Abschnitt 12, `:279`): frps läuft vor jeder FRP-Konfiguration und antwortet auf `:7000` nicht per TLS (TLS-Probe, nicht `nc -z`); nach dem Anlegen erscheint innerhalb von 20 s die PKI-Kette; identisches PUT löst keinen Neustart aus (Ereignis-`seq` unverändert); neues Token → genau ein Neustart und eine Mitteilung; eine ungültige Zertifikatsdatei im Volume → frps bleibt erreichbar, Zustand `degraded`; Löschen → `:7000` antwortet nicht mehr. `desktop_e2e_tunnel.sh:57` und `desktop_e2e_connect_tunnel.sh:119`: `up -d --build frps`. **Harness-Pfad: PR merged Kevin.**
Verify: bash scripts/dev/verify.sh scripts --strict -- lib_e2e_stack_test
Doku: keine (intern)
Abhängt von: T6, T9, T25

### T16 — Multibox: frps-Neustart im Tunnel-Szenario  [x]
Komponente: scripts · Dateien: scripts/tests/box_serverbox.sh, scripts/tests/multibox.sh, scripts/tests/multibox_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @2a01016b 2026-10-17T14:19:31+02:00
Review: approve (.ah-out/review/frps-supervisor/T16.verdict.json)
Änderung: `box_serverbox.sh` baut frps mit (`:59` in die `--build`-Liste, `:235` ohne eigenes `up`); im `--tunnel`-Szenario nach dem ersten erfolgreichen Visitor-Durchgang die FRP-Konfiguration ändern (z. B. `max_ports_per_client`), dann prüfen: frps startet genau einmal neu, der Agent verbindet sich ohne Eingriff wieder, eine neue Visitor-Verbindung geht durch. `multibox_test.sh` deckt die neue Etappe hermetisch ab. **Harness-Pfad: PR merged Kevin.**
Verify: bash scripts/dev/verify.sh scripts --strict -- multibox_test
Doku: keine (intern)
Abhängt von: T9

### T28 — Server: `extra_config` der FRP-Server-Config nur mit zulässigen Schlüsseln, Altwerte beim Start bereinigt  [ ]
Komponente: server · Dateien: apps/server/app/modules/frp/extra_config.py, apps/server/app/modules/frp/schemas.py, apps/server/app/main.py, apps/server/tests/test_frp_extra_config.py, apps/server/tests/test_frp_input_hardening.py, apps/server/tests/test_frp_config.py, apps/server/tests/test_frp_toml_roundtrip.py
Änderung: Entscheidung Kevin 2026-10-17 (Review T17): Der Supervisor lässt oben nur die Schlüssel aus `TOP_KEYS` (`apps/frps/frps-supervisor.sh`) zu; der Server schrieb bisher jeden `extra_config`-Schlüssel ungefiltert, sodass eine Installation mit z. B. `log.to` nach dem Update keinen frps startet. Neue Datei `extra_config.py` (SPDX): die zulässigen `extra_config`-Schlüssel der FRP-Server-Config (die `TOP_KEYS`, die der Generator nicht selbst schreibt); `FrpServerConfigCreate`/`Update` lehnen andere Schlüssel mit 422 ab (die Tunnel-Schemas bleiben unverändert, das ist frpc). Beim Start (`main.py`, vor `_ensure_frps_config`) entfernt der Server unzulässige Schlüssel aus bestehenden Zeilen, loggt Feldnamen (keine Werte) und schickt Admins eine Mitteilung in der Glocke mit den entfernten Schlüsseln; idempotent. Tests zuerst rot (neue Datei, SPDX): 422 für einen unzulässigen Schlüssel, zulässige gehen durch; Startbereinigung entfernt nur unzulässige, schreibt genau eine Mitteilung, zweiter Start ändert nichts; die Liste stimmt mit `TOP_KEYS` im Supervisor überein (Drift-Test liest das Skript). Dazu (Fund im Bau, selbe Entscheidung): `subdomain_host`, `dashboard_user`, `dashboard_password` und ein gesetztes `auth_token` folgen derselben Zeichenregel wie der Supervisor (`check_config`), sonst 422; verletzt ein Bestandswert sie, schickt der Start Admins eine Mitteilung mit dem Feldnamen (nie dem Wert).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_frp_extra_config.py tests/test_frp_input_hardening.py tests/test_frp_config.py tests/test_frp_toml_roundtrip.py
Doku: CHANGELOG und Betrieb in T17
Test-Löschung: apps/server/tests/test_frp_toml_roundtrip.py::test_extra_config_may_collide_with_the_generators_own_keys — das strict-xfail hielt fest, dass `extra_config` mit Generator-Schlüsseln kollidieren kann; T28 lehnt solche Schlüssel im Schema ab, ein Positivtest (Schema lehnt `auth`/Generator-Schlüssel ab) ersetzt ihn

### T27 — Kommentare: frps-Image und Compose neutral  [ ]
Komponente: server · Dateien: apps/frps/Dockerfile, docker-compose.yml, apps/server/tests/test_compose_frps.py, apps/server/app/modules/frp/config_generator.py
Änderung: Review T17 (Wortlaut): Kommentare und Docstrings beschreiben, was der Supervisor tut („verwaltet `/etc/frp` allein“, „das Volume enthält, was der Server schreibt“), nicht, was das Basis-Image mitbringt. Nur Kommentare und Docstrings, kein Verhalten. Dazu der veraltete Kommentar in `config_generator.py` (`:197-199`, „e.g. maxPoolCount“, „_check_extra_config already validated“) nach T28.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_compose_frps.py
Doku: keine (intern)

### T17 — Doku und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html, docs/admin/installation.html, docs/en/admin/installation.html, CHANGELOG.md, docs/admin/betrieb.html, docs/en/admin/operations.html, docs/developer/api-reference.html, docs/en/developer/api-reference.html
Änderung: `frp-tunnel.html` DE+EN: Architektur (`:41-48`) mit frps-Image und Supervisor; „FRP `auth.token` rotieren“ (`:65-74`): kein manueller Neustart mehr, frps übernimmt nach wenigen Sekunden, alle Tunnel sind kurz getrennt, Mitteilung an Admins und Tunnel-Nutzer, Agent-Tunnel bis ~5 min, eine abgelehnte Konfiguration steht auf der FRP-Seite und in der Glocke; Status-Dashboard (`:107`) mit dem neuen Statusblock. `installation.html` DE+EN: frps lauscht, sobald FRP im Web-Interface eingerichtet ist; Voraussetzung Docker-Engine einheitlich in DE und EN (frps bindet 443 ohne root, `ip_unprivileged_port_start` per Compose, T20). Betriebsdoku (`docs/admin/betrieb.html`, `docs/en/admin/operations.html`): Volumes `frps-state`/`frps-active` (nicht im Backup), zulässige `extra_config`-Schlüssel, Gründe und Ereignisse des Supervisors (inkl. `copy_changed`, `start_refused`, `input_unreadable`, `input_unstable`), Update rollt bei Pull-, Paket-Repo- oder Stack-Neustart-Fehler zurück, auch bei Floating-Tags, und bricht ohne `.env` vor dem Backup ab (T21, T22; `installation.html` DE `:211`/EN `:164` nennt den Rollback bisher nur für den Health-Check); nach dem ersten Release das ghcr-Paket `frps` öffentlich. CHANGELOG unter `### Changed`; unter `### Fixed` ein eigener Absatz (Kevin 2026-10-17, Grundlage des Release-Hinweises): der Scheduler-Prozess lud nicht alle Modelle, seit v0.38.0 liefen seine DB-Jobs nicht (E-Mail-Benachrichtigungen, geplante Hooks, Aufbewahrungsfristen); nach dem Update laufen geplante Hooks wieder — vor dem Update prüfen; ausstehende Mails älter als 7 Tage verfallen (T25, T26); Hinweis an Admins: Benutzerliste und Audit-Log (`user.created`) für die Zeit seit v0.38.0 prüfen, weil E-Mail-Hinweise auf neue Admin-Konten nicht zugestellt wurden (Review T26); dazu: die FRP-Server-Config nimmt Ports nur im Bereich 1–65535 und `max_ports_per_client` nur ≥ 0 an (422), gespeicherte Werte außerhalb ersetzt der Generator mit einer Warnung im Log (T23).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: docs/admin/frp-tunnel.html + docs/en/admin/frp-tunnel.html · docs/admin/installation.html + docs/en/admin/installation.html · CHANGELOG.md (Changed)
Abhängt von: T8, T13, T14, T20, T21, T22
