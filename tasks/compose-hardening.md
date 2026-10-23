<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Compose-Härtung: Client-Adresse hinter dem Gateway, Grenzen der Container, CA-Passphrase als Secret, Netz frpedge — Task-Ledger
Status: erledigt · Branch: feature/compose-hardening · Review: pro Task
Spec: docs/features/compose-hardening.md (Härtung, Kevin 2026-10-22)
Heavy: linux-full + scenario --agents 1 --tunnel --enforce — `docker-compose.yml` (alle Dienste: `no-new-privileges`, Prozess- und Speichergrenzen, Capabilities des Gateways, Secret des ca-issuer, Netz `frpedge`, `TRUSTED_PROXIES`), `apps/gateway/nginx.conf`, `apps/ca-issuer` und `scripts/init-secrets.sh` laufen im Sammellauf über `main` (`integration-stack` mit den Schritten aus T8 und T13, `backup-restore`, `upgrade-path` vom letzten Release); auf PRs läuft der Stack-Job nicht, daher vor dem Merge `gh workflow run ci.yml --ref feature/compose-hardening`. `scenario` vor dem Merge (ask-first): nur er erreicht die veröffentlichten Ports von frps von einem zweiten Host (Tunnel-Datenpfad durch `frpedge` ohne Masquerading, T4, und die Prüfung aus T9) und fährt das Gateway unter `MTLS_ENFORCE=true` mit Clients eines anderen Hosts (T2, T3, T12). Kein `windows`: kein Agent- und kein Desktop-Code.
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) Jeder Dienst läuft mit `no-new-privileges` und einer Prozessgrenze, das Gateway nur mit den Capabilities,
die nginx braucht, und die certless Ebenen :8444/:8445 begrenzen gleichzeitige Anfragen und untätige Verbindungen.
(2) frps hat aus `frpedge` keinen ausgehenden Verkehr über den Host hinaus; die Doku beschreibt die Netze, wie
Compose sie anlegt. (3) Die CA-Root-Passphrase erreicht den ca-issuer als Compose-Secret; nach dem ersten Start darf
sie in `.env` leer sein, ohne dass ein Update eine neue erzeugt. (4) Nach Kevins Antwort: Speichergrenzen (T10), und
der Server wertet hinter dem Gateway die Client-Adresse aus (T11–T13). Zeilenangaben: origin/main@b1432223; der
builder greppt sie vor dem Schreiben neu.

Für alle Tasks:
- Reihenfolge: T1 legt `apps/server/tests/test_compose_hardening.py` an (T4, T6, T10, T12 ergänzen sie), T2 legt
  `apps/server/tests/test_gateway_container.py` an (T3 ergänzt sie). T5 vor T6 (sonst stürzt der ca-issuer mit
  leerem Secret ab). T8 nach T1, T2, T4, T6; T9 nach T4; T7 nach T6 (die Doku nennt das Verhalten von Compose).
  T10–T13 warten auf Kevin (Spec, offene Fragen 1–3).
- Risikopfade (`scripts/dev/review-risk.txt`): `docker-compose*.yml` (T1, T2, T4, T6, T10, T12), `apps/gateway/*`
  (T3), `apps/ca-issuer/*` (T5): zusätzlich `security`; ebenso T11 (`middleware.py`, Vertrauen in Forwarded-Header).
- Neue Schlüssel eines Dienstes in `docker-compose.yml` stehen direkt nach dessen `restart: unless-stopped`; die
  `environment:`-Blöcke bleiben bis auf `:233` (T6) und `:97-102` (T12) unberührt (paralleles Vorhaben an den
  SMTP-Zeilen).
- Compose-Tests lesen nur `docker-compose.yml` mit `yaml.safe_load` (wie `apps/server/tests/test_compose_frps.py:88-89`;
  `docker-compose.test.yml` trägt `!override`). Docker-Tests: Skip wie `_built_frps_image`
  (`apps/server/tests/test_frps_supervisor.py:2047-2064`), wenn Docker oder das gepinnte Basis-Image fehlt; vor dem
  Verify das Basis-Image ziehen, die Summary zeigt die neuen Tests als passed, keinen skipped.
- Neue Code-Strings (Kommentare, Log-Zeilen, Hinweise der Skripte) englisch; bestehende deutsche Texte bleiben.
  CHANGELOG unter `## [Unreleased]` → `### Changed`, umlautfrei. Platzhalter-Adressen nur RFC 5737.

### T1 — Compose: alle Dienste mit no-new-privileges und Prozessgrenze  [x]
Komponente: server · Dateien: docker-compose.yml, apps/server/tests/test_compose_hardening.py, docs/admin/betrieb.html, docs/en/admin/operations.html, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @7ff78078 2026-10-22T12:13:15+02:00
Review: approve (.ah-out/review/compose-hardening/T1.verdict.json)
Änderung: Jeder Dienst in `docker-compose.yml` (postgres, server, scheduler, gateway, ca-issuer, redis, frps, monitoring, victoria) bekommt `security_opt: [no-new-privileges:true]` (frps hat es schon, `:331-333`) und `pids_limit`: server 4096; scheduler, monitoring, victoria 1024; ca-issuer, gateway, frps, postgres 512; redis 256 (Spec Trade-off 5), je mit einer Kommentarzeile zum Warum des Werts (server: je uvicorn-Worker ein Thread-Pool, bis acht Hook-Prozesse, `WEB_CONCURRENCY` nach `.env.example:144-149`; postgres: ein Prozess je Verbindung, Default `max_connections` 100). monitoring bekommt dazu `sysctls: net.ipv4.ping_group_range: "0 2147483647"`: der Ping-Check startet `ping` als `app` (`apps/monitoring/app/checkers/ping.py:36`); unter `no-new-privileges` bekommt ein setuid- oder Capability-`ping` keine Rechte und nutzt ICMP-Datagram-Sockets, die dieser Bereich erlaubt — Docker-Default (Probe Docker 29.8.1), hier gesetzt, damit es nicht an der Engine hängt (wie frps, `:325-330`). Neue Testdatei `apps/server/tests/test_compose_hardening.py` mit SPDX-Header (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later`): (a) die Menge der Dienste mit `no-new-privileges:true` in `security_opt` ist die Menge aller Dienste; (b) jeder Dienst hat ein ganzzahliges `pids_limit` ≥ 128, server ≥ 2048; (c) monitoring hat den `ping_group_range` oben. Zuerst rot: (a)–(c) auf HEAD. `apps/server/tests/test_compose_frps.py` bleibt unverändert grün.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_compose_hardening.py
Doku: `docs/admin/betrieb.html` neuer Abschnitt „Grenzen der Container“ nach „Multi-Worker-Betrieb“ (`:155-166`), `docs/en/admin/operations.html` „Container limits“ nach „Multi-Worker Notes“ (`:108-124`): alle Dienste mit `no-new-privileges`; Prozessgrenzen je Dienst als Tabelle; anheben per `docker-compose.override.yml` (Beispiel mit `pids_limit` für server; Compose lädt die Datei selbst, `update.sh` lässt sie stehen); ein Satz: wer `WEB_CONCURRENCY` stark erhöht, prüft die Grenze des server · CHANGELOG (Changed, umlautfrei: alle Dienste mit no-new-privileges und Prozessgrenze)
Beweis: Code-Lesung docker-compose.yml:331-333 (nur frps mit `security_opt`); kein `pids_limit` in der Datei
HEAD: b1432223

### T2 — Gateway: nur die Capabilities, die nginx braucht  [x]
Komponente: server · Dateien: docker-compose.yml, apps/server/tests/test_gateway_container.py, docs/admin/betrieb.html, docs/en/admin/operations.html, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @64df1d31 2026-10-22T13:14:40+02:00
Review: approve (.ah-out/review/compose-hardening/T2.verdict.json)
Änderung: Der Dienst gateway (`docker-compose.yml:178-210`) bekommt `cap_drop: [ALL]`, `cap_add` mit der kleinsten Liste, mit der der Test unten grün ist — Start mit `CHOWN` (nginx legt seine Temp-Verzeichnisse an und übergibt sie dem Worker-Nutzer), `SETUID` und `SETGID` (Worker als `nginx`), `DAC_OVERRIDE` (`gateway.key` liegt 0600 unter der UID des ca-issuer, `apps/ca-issuer/app/storage.py:67-77`, `:224`; nicht `DAC_READ_SEARCH`, Spec Trade-off 6); `KILL` nur, wenn ohne es der Stopp nicht sauber endet — und `sysctls: net.ipv4.ip_unprivileged_port_start: 0` (443/8444/8445 im Container ohne `NET_BIND_SERVICE`, wie frps `:325-330`). Ein Kommentar über den Schlüsseln nennt je Capability das Warum (wie `:317-322`). Neue Testdatei `apps/server/tests/test_gateway_container.py` mit SPDX-Header: (1) ohne Docker: die Compose-Werte des gateway — `cap_drop == ["ALL"]`, `cap_add` sortiert gleich der im Test gepinnten Liste, `no-new-privileges:true` in `security_opt`, das `sysctl`. (2) mit Docker: Image aus `apps/gateway` bauen (Basis-Image aus `apps/gateway/Dockerfile:1`); Container in einem eigenen Docker-Netz (eingebettetes DNS für `resolver 127.0.0.11`, `apps/gateway/nginx.conf:44`) mit genau den Sicherheits-Argumenten aus `docker-compose.yml` (wie `_security_args`, `test_frps_supervisor.py:2036-2044`), `MTLS_ENFORCE=false`, einem Volume für `/etc/nginx/certs` mit Wegwerf-Zertifikaten (wie der CI-Job `gateway-config`, `.github/workflows/ci.yml:887-899`), `gateway.key` per Hilfscontainer auf `10001:10001` und 0600, und einem Repo-Verzeichnis mit `apt/probe`. Erwartet: `https://<container>:8445/apt/probe` → 200; `CapEff` und `CapBnd` von PID 1 (nginx-Master) sind genau die Liste; jeder Worker hat eine UID ≠ 0; `NoNewPrivs: 1`; `docker stop -t 10` endet mit Exit-Code 0. Gegenprobe je Capability der Liste (parametrisiert): ohne sie scheitert Start, Antwort oder sauberer Stopp. Zuerst rot: (1) auf HEAD.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_gateway_container.py
Doku: Abschnitt „Grenzen der Container“ aus T1 (DE+EN): ein Satz, dass das Gateway nur die genannten Capabilities behält · CHANGELOG (Changed, umlautfrei)
Abhängt von: T1
Beweis: Code-Lesung docker-compose.yml:178-210 (kein `cap_drop`, keine `security_opt`)
HEAD: b1432223

### T3 — Gateway: certless Ebenen mit Verbindungsgrenzen und kurzen Timeouts  [x]
Komponente: server · Dateien: apps/gateway/nginx.conf, apps/server/tests/test_gateway_container.py, docs/admin/betrieb.html, docs/en/admin/operations.html, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @e33b01e0 2026-10-22T14:16:59+02:00
Review: approve (.ah-out/review/compose-hardening/T3.verdict.json)
Änderung: In `apps/gateway/nginx.conf` im `http`-Block bei den `limit_req_zone`s (`:60-70`): `limit_conn_zone $binary_remote_addr zone=certless_addr:10m;`, `limit_conn_zone $server_port zone=certless_plane:1m;`, `limit_conn_status 429;`. Im `server` :8444 (`:132-170`): `limit_conn certless_addr 16;`, `limit_conn certless_plane 128;`; im `server` :8445 (`:181-199`): `limit_conn certless_addr 64;`, `limit_conn certless_plane 256;`; in beiden `client_header_timeout 10s;`, `client_body_timeout 10s;`, `keepalive_timeout 15s;`. Ein Kommentar sagt, warum (gezählt werden nur Anfragen in Bearbeitung, nginx-Doku; die Timeouts begrenzen untätige Verbindungen; 64 auf :8445 für viele Agent-Hosts hinter einer NAT-Adresse; die Grenzen je Ebene halten beide zusammen unter der Hälfte von `worker_connections`, `:12-14`). Der Block :443 (`:77-124`) bleibt unverändert. Tests in `test_gateway_container.py`: (1) ohne Docker, aus `nginx.conf` gelesen: die zwei Zonen und `limit_conn_status 429` im `http`-Block; in den Blöcken :8444 und :8445 je beide `limit_conn` mit den Werten oben und die drei Timeouts; im Block :443 keines davon. (2) mit Docker (Container wie T2): eine Datei von 32 MiB unter `apt/`; 65 gleichzeitige Downloads von einer Adresse mit `--limit-rate 1k` → mindestens einer endet mit 429, die übrigen laufen (200); nach ihrem Abbruch liefert eine neue Anfrage 200. (3) mit Docker: eine TLS-Verbindung zu :8445, die nach dem Handshake keinen Header schickt, schließt das Gateway nach höchstens 15 s. Zuerst rot: (1)–(3) auf HEAD.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_gateway_container.py
Doku: Abschnitt aus T1 (DE+EN): Antwort 429 auf :8444/:8445 ab 16 bzw. 64 gleichzeitigen Anfragen je Adresse · CHANGELOG (Changed, umlautfrei)
Abhängt von: T2
Beweis: Code-Lesung apps/gateway/nginx.conf:12-14, :60-70, :132-199 (kein `limit_conn`, Timeouts auf dem Default von 60 s)
HEAD: b1432223

### T4 — Netze: frpedge ohne Masquerading, Doku der Netze  [x]
Komponente: server · Dateien: docker-compose.yml, apps/server/tests/test_compose_hardening.py, docs/developer/index.html, docs/en/developer/index.html, CHANGELOG.md, docs/admin/betrieb.html, docs/en/admin/operations.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @1aba8848 2026-10-23T06:59:54+02:00
Review: approve (.ah-out/review/compose-hardening/T4.verdict.json)
Änderung: `networks.frpedge` (`docker-compose.yml:453-456`) bekommt `driver_opts: com.docker.network.bridge.enable_ip_masquerade: "false"`. Der Kommentar darüber sagt: frps nimmt nur Verbindungen an, seine veröffentlichten Ports wirken weiter; ausgehenden Verkehr braucht es nicht, Plugin-Einträge lässt der Supervisor nicht zu (`apps/frps/frps-supervisor.sh:119-122`, `:212-221`); Dienste des Hosts selbst bleiben aus dem Netz erreichbar. Kommentare `:214-216` und `:445-448` korrigieren: im Netz `pki` hängen Gateway, ca-issuer und Postgres (wie `:266-268`). Tests in `test_compose_hardening.py`: (a) `frpedge` hat die Option mit dem String `"false"`, ist nicht `internal`, und nur frps hängt darin; (b) Gegenprobe: `default` und `pki` haben die Option nicht. Zuerst rot: (a).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_compose_hardening.py
Doku: `docs/developer/index.html:106` + `docs/en/developer/index.html:84`: (1) im Netz `pki` hängen Gateway, ca-issuer und Postgres; den ca-issuer erreichen Gateway und Postgres, nicht frps und nicht die übrigen Dienste des Default-Netzes; (2) `frpedge` ohne Masquerading: frps hat keinen ausgehenden Verkehr über den Host hinaus, seine veröffentlichten Ports bleiben erreichbar · CHANGELOG (Changed, umlautfrei)
Abhängt von: T1
Beweis: Code-Lesung docker-compose.yml:35, :214-216, :453-456; Probe 2026-10-22 (Docker 29.8.1, Compose v5.5.1, Alpine-Container in einem Bridge-Netz mit und ohne Option): ohne Masquerading scheitern Verbindungen ins Internet und zum LAN-Router, ein veröffentlichter Port und ein Dienst des Hosts bleiben vom Host aus erreichbar; Compose legt das Netz beim nächsten `up` mit der Option neu an
HEAD: b1432223

### T5 — ca-issuer: fehlende Passphrase-Datei heißt keine Passphrase  [x]
Komponente: ca-issuer · Dateien: apps/ca-issuer/app/config.py, apps/ca-issuer/tests/test_config.py
Evidenz: run.sh[quick] ca-issuer: 3 passed, 0 failed, 15 skipped @6859681d 2026-10-23T07:19:40+02:00
Review: approve (.ah-out/review/compose-hardening/T5.verdict.json)
Änderung: `root_passphrase()` (`apps/ca-issuer/app/config.py:43-54`): zeigt `CA_ROOT_PASSPHRASE_FILE` auf einen Pfad ohne Datei, liest die Funktion weiter `CA_ROOT_PASSPHRASE` (leer → `None`) statt mit `FileNotFoundError` abzubrechen (`:51-53`); andere `OSError` (keine Leserechte, ein Verzeichnis) wirft sie weiter. Docstring: Compose übergibt die Passphrase als Secret-Datei; ein leerer Wert erzeugt keine Datei (Probe Compose v5.5.1), und nach dem ersten Start ist ein leerer Wert gewollt. Der Kommentar `:93-101` sagt richtig, wer den Listener erreicht: über das Netz `pki` das Gateway und Postgres, nicht frps und nicht die Dienste des Default-Netzes. Tests in `test_config.py` neben `:33-55`: (a) `CA_ROOT_PASSPHRASE_FILE` auf einen Pfad in `tmp_path` ohne Datei, `CA_ROOT_PASSPHRASE` ungesetzt → `None`; (b) dasselbe mit `CA_ROOT_PASSPHRASE=env-secret` → `b"env-secret"`; (c) `CA_ROOT_PASSPHRASE_FILE` auf ein Verzeichnis → `IsADirectoryError` (wird nicht verschluckt). Zuerst rot: (a), (b). Die bestehenden Tests `:27-55` bleiben unverändert grün.
Verify: bash scripts/dev/verify.sh ca-issuer --strict -- tests/test_config.py
Doku: keine (intern; die Betreiber-Doku kommt mit T6 und T7)
Beweis: Code-Lesung apps/ca-issuer/app/config.py:51-53 (`Path(path).read_bytes()` ohne Fall für eine fehlende Datei); Probe Compose v5.5.1: Secret aus leerer Variable → kein `/run/secrets/<name>`
HEAD: b1432223

### T6 — Compose: CA-Passphrase als Secret statt Umgebungsvariable  [x]
Komponente: server · Dateien: docker-compose.yml, .env.example, apps/server/tests/test_compose_hardening.py, apps/server/tests/test_env_parity.py, docs/admin/installation.html, docs/en/admin/installation.html, CHANGELOG.md, docs/en/admin/index.html, docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @83b448bb 2026-10-23T08:45:28+02:00
Review: approve (.ah-out/review/compose-hardening/T6.verdict.json)
Änderung: Neuer Top-Level-Block `secrets:` mit `ca_root_passphrase: { environment: CA_ROOT_PASSPHRASE }`. Der ca-issuer (`docker-compose.yml:227-245`) verliert `- CA_ROOT_PASSPHRASE=${CA_ROOT_PASSPHRASE:-}` (`:233`), bekommt `- CA_ROOT_PASSPHRASE_FILE=/run/secrets/ca_root_passphrase` und `secrets: [ca_root_passphrase]`. Der Kommentar `:231-232` sagt: die Passphrase kommt als Datei, nicht als Umgebungsvariable; nur der erste Start braucht sie; danach darf der Wert in `.env` leer sein, die Zeile muss bleiben (fehlt sie, bricht `docker compose up` ab; `environment` als Quelle eines Secrets ab Compose v2.6.0). `.env.example:75-82` sagt dasselbe; die Zeile bleibt aktiv (`update.sh` ergänzt fehlende aktive Zeilen, `scripts/update.sh:545-573`). `test_env_parity.py`: `_substituted_and_documented` (`:167-171`) zählt die Variablen aus `secrets.*.environment` (per YAML gelesen; ohne Top-Level-`secrets` die leere Menge) zu den übergebenen Knöpfen; die Nicht-leer-Wächter in `test_the_scan_reads_all_three_sides` (`:114-133`) bleiben. Tests in `test_compose_hardening.py`: (a) kein Dienst hat `CA_ROOT_PASSPHRASE` in `environment`; (b) der ca-issuer hat `CA_ROOT_PASSPHRASE_FILE=/run/secrets/ca_root_passphrase` und das Secret `ca_root_passphrase`, dessen Quelle `environment: CA_ROOT_PASSPHRASE` ist; (c) `.env.example` trägt `CA_ROOT_PASSPHRASE=` als aktive Zeile. Zuerst rot: (a), (b). `test_env_parity.py` danach ganz grün; Gegenprobe im Commit-Body: ohne die Änderung an `_substituted_and_documented` meldet `test_every_documented_knob_reaches_a_service` `CA_ROOT_PASSPHRASE`.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_compose_hardening.py tests/test_env_parity.py
Doku: `docs/admin/installation.html:142` + `docs/en/admin/installation.html:53`: die Passphrase erreicht den ca-issuer als Compose-Secret (Datei unter `/run/secrets`, nicht in der Umgebung des Containers), `CA_ROOT_PASSPHRASE_FILE` setzt Compose selbst; nach dem ersten Start den Wert leeren, die Zeile behalten; der Satz „Bevorzuge `CA_ROOT_PASSPHRASE_FILE` …“ entfällt · CHANGELOG (Changed, umlautfrei)
Abhängt von: T5, T1
Beweis: Code-Lesung docker-compose.yml:233; Probe 2026-10-22 (Docker 29.8.1, Compose v5.5.1): Secret mit `environment:` aus der `.env` des Projekts → `/run/secrets/<name>` 0444 root, `Config.Env` nur mit `CA_ROOT_PASSPHRASE_FILE`; leere Variable → keine Datei; fehlende Variable → `up` bricht ab
HEAD: b1432223

### T7 — init-secrets.sh: CA-Passphrase nur bei frischer Installation  [x]
Komponente: scripts · Dateien: scripts/init-secrets.sh, scripts/tests/init-secrets_test.sh, docs/admin/betrieb.html, docs/en/admin/operations.html, CHANGELOG.md, scripts/restore.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @4bc6cc7b 2026-10-23T09:07:43+02:00
Review: approve (.ah-out/review/compose-hardening/T7.verdict.json)
Änderung: `scripts/init-secrets.sh:103-111`: `CA_ROOT_PASSPHRASE` wird nur erzeugt, wenn derselbe Lauf auch `POSTGRES_PASSWORD` erzeugt hat (frische Installation: Postgres- und PKI-Volume entstehen gemeinsam; Spec Trade-off 4). Ist `POSTGRES_PASSWORD` schon gesetzt und `CA_ROOT_PASSPHRASE` leer, bleibt die Zeile, wie sie ist, und das Skript schreibt eine Zeile (englisch) auf stdout: der Wert bleibt leer, nur der erste Start des ca-issuer braucht ihn; bei einer Neuinstallation mit vorab gesetztem `POSTGRES_PASSWORD` von Hand setzen. Der Kopfkommentar `:7-11` nennt die Regel. Tests in `scripts/tests/init-secrets_test.sh` (neuer Fall nach `:105-110`): (a) `.env` mit `POSTGRES_PASSWORD=already-set` und `CA_ROOT_PASSPHRASE=` → danach genau eine Zeile `CA_ROOT_PASSPHRASE=` (leer), Exit 0, der Hinweis auf stdout; (b) neben (a): `.env` mit leerem `POSTGRES_PASSWORD` und leerem `CA_ROOT_PASSPHRASE` → beide 64 Hex. Zuerst rot: (a) auf HEAD (heute 64 Hex). Die Fälle 1–7 bleiben grün (in 1 und 6 erzeugt derselbe Lauf `POSTGRES_PASSWORD`).
Verify: bash scripts/dev/verify.sh scripts --strict -- init-secrets_test
Doku: `docs/admin/betrieb.html:95` + `docs/en/admin/operations.html:62` (Callout): nach dem ersten Start den Wert in `.env` leeren und die Zeile `CA_ROOT_PASSPHRASE=` behalten; Updates erzeugen keine neue; `:103` + EN `:70` (Restore): `.env.restored` trägt die Zeile nicht — beim Übernehmen `CA_ROOT_PASSPHRASE=` ergänzen (leer oder mit der aufbewahrten Passphrase), sonst startet Compose nicht · CHANGELOG (Changed, umlautfrei)
Abhängt von: T6
Beweis: Code-Lesung scripts/init-secrets.sh:103-111 und scripts/update.sh:563 (`migrate_env` ruft `init-secrets.sh` bei jedem Update)
HEAD: b1432223

### T8 — Stack-Prüfung: Grenzen, Capabilities, Secret und frpedge im laufenden Stack  [x]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @fb3c93f4 2026-10-23T09:53:00+02:00
Review: approve (.ah-out/review/compose-hardening/T8.verdict.json)
Änderung: Neuer Schritt vor der Summary (`scripts/tests/integration_stack_test.sh:636`; Nummer nach dem letzten Schritt auf `main` zur Bauzeit). Er startet scheduler und monitoring mit `e2e_dc up -d --no-deps`, falls sie nicht laufen (wie `:476`); frps und victoria laufen seit Schritt 12 (`:623`). (a) In jedem laufenden Dienst des Projekts hat `/proc/1/status` `NoNewPrivs: 1`, und `docker inspect --format '{{.HostConfig.PidsLimit}}'` ist der Wert aus `e2e_dc config --format json`; Gegenprobe: ein Container desselben gateway-Images außerhalb des Projekts ohne Sicherheits-Optionen zeigt `NoNewPrivs: 0` (die Prüfung kann fallen). (b) gateway: `CapEff` von PID 1 ist die Maske der `cap_add`-Liste aus `e2e_dc config`, jeder nginx-Worker hat eine UID ≠ 0. (c) monitoring: `gosu app:app ping -c1 -W2 127.0.0.1` im Container endet mit 0. (d) ca-issuer: `Config.Env` ohne `CA_ROOT_PASSPHRASE=`, mit `CA_ROOT_PASSPHRASE_FILE=`; `/run/secrets/ca_root_passphrase` ist nicht leer (der Test-Stack setzt die Passphrase, `scripts/tests/lib_e2e_stack.sh:233`); Gegenprobe: `Config.Env` des server enthält `SECRET_KEY=`. (e) Das Netz `frpedge` des Projekts hat `com.docker.network.bridge.enable_ip_masquerade` = `false` (`docker network inspect`), das Default-Netz nicht. Den echten Lauf fährt die Session (Dispatch des `integration-stack`-Jobs auf dem Branch oder `/test` in der Lane); seine Summary-Zeile `integration_stack_test: N passed, 0 failed` kommt in den PR-Text.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test)
Abhängt von: T1, T2, T4, T6

### T9 — Multibox: frps erreicht aus frpedge keinen zweiten Host  [x]
Komponente: scripts · Dateien: scripts/tests/multibox.sh, scripts/tests/box_serverbox.sh, scripts/tests/multibox_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @5ba55902 2026-10-23T10:38:47+02:00
Review: approve (.ah-out/review/compose-hardening/T9.verdict.json)
Änderung: Neuer Unterbefehl `frps-egress <ip> <port>` in `scripts/tests/box_serverbox.sh` (neben `frps-mark`/`frps-restart`, `:182-183`), mit dem Compose-Aufruf, den die frps-Schritte dort nutzen: eine TCP-Verbindung aus dem frps-Container (`nc -z -w3 <ip> <port>`) muss scheitern, aus dem server-Container (`python -c` mit `socket.create_connection((ip, port), 3)`) muss sie gelingen (Gegenprobe: das Ziel ist erreichbar); Ausgabe eine Zeile mit beiden Ergebnissen, Exit 0 nur, wenn beide stimmen. `scripts/tests/multibox.sh` ruft ihn in der Tunnel-Stufe (`:424-`) nach dem Lease der Tunnel-Box mit deren Adresse und Port 22 über `ask "$SRV_VM"` auf (wie `frps_restart`, `:380-400`) und zählt `ok`/`bad`; ohne `--tunnel` läuft er nicht. Die hermetischen Tests (`scripts/tests/multibox_test.sh`, `scripts/tests/box_scripts_guard_test.sh`) bleiben grün; braucht einer eine Anpassung, `ledger.sh set-files`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test)
Abhängt von: T4

### T10 — Compose: Speichergrenzen je Dienst  [x]
Komponente: server · Dateien: docker-compose.yml, apps/server/tests/test_compose_hardening.py, docs/admin/betrieb.html, docs/en/admin/operations.html, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @666894bd 2026-10-23T12:06:00+02:00
Review: approve (.ah-out/review/compose-hardening/T10.verdict.json)
Änderung (Empfehlung, Spec offene Frage 3): jeder Dienst bekommt `mem_limit` direkt nach seinem `pids_limit` (T1), mit einer Kommentarzeile zum Warum des Werts. Die Werte stehen vor dem Bau fest: Messung `docker stats --no-stream` aller Dienste während eines Stack-Laufs (nach T8), Wert ein großzügiges Vielfaches der Spitze, mindestens server 2g, scheduler 1g, monitoring 1g, postgres 1g, victoria 2g, ca-issuer 256m, gateway 256m, frps 256m, redis 256m; die Session trägt sie nach Kevins Antwort hier ein. Kevins Antwort (2026-10-22): feste Werte postgres 8g, victoria 8g, server 6g, monitoring 4g, scheduler 2g, frps 2g, gateway 1g, ca-issuer 512m, redis 512m; anhebbar per `docker-compose.override.yml` (Doku mit Beispiel); vor dem Bau am laufenden Stack (eigener Projektname, danach entfernt) mit `docker stats --no-stream` prüfen, dass der Leerlauf weit darunter liegt, Messwerte in den Commit-Body. Test in `test_compose_hardening.py`: jeder Dienst hat ein `mem_limit` in einer Form, die Compose annimmt (Zahl mit `k`/`m`/`g`), und keines unter 128m. Zuerst rot.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_compose_hardening.py
Doku: Abschnitt aus T1 (DE+EN): Speichergrenzen je Dienst in der Tabelle, Override-Beispiel mit `mem_limit` · CHANGELOG (Changed, umlautfrei)
Abhängt von: T1

### T11 — Server: TRUSTED_PROXIES versteht Hostnamen  [x]
Komponente: server · Dateien: apps/server/app/core/middleware.py, apps/server/tests/test_ip_filter.py, docs/developer/server.html, docs/en/developer/server.html, apps/server/app/core/config.py
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @144784a6 2026-10-23T12:26:17+02:00
Review: approve (.ah-out/review/compose-hardening/T11.verdict.json)
Änderung: `_parse_networks` (`apps/server/app/core/middleware.py:17-28`) behält einen Eintrag, der keine Adresse und kein Netz, aber ein gültiger Hostname ist (Labels aus Buchstaben, Ziffern und `-`, je 1–63 Zeichen, gesamt höchstens 253), als Namen; andere Einträge warnen wie heute. Ein kleiner Resolver löst die Namen mit `socket.getaddrinfo` auf und hält die Adressen 30 s, nach einem Fehlschlag 5 s; `resolve_client_ip` (`:64-90`) vertraut den Headern, wenn die direkte Gegenstelle in den Netzen oder unter den aufgelösten Adressen liegt. Der Anfragepfad blockiert nicht auf DNS: aufgelöst wird in einem Daemon-Thread, der Anfragepfad liest den letzten Stand; bis zur ersten Auflösung gilt ein Name als leer (direkte Adresse wie heute). Ein Fehlschlag loggt einmal je Name und Wechsel auf WARNING, nicht je Anfrage. `TRUST_PROXY_HEADERS` bleibt, wie es ist. Tests in `apps/server/tests/test_ip_filter.py` (Resolver ersetzt, keine echte DNS-Abfrage; Muster `:89-99`): (a) `TRUSTED_PROXIES=gateway`, `gateway` → `192.0.2.10`: Anfrage von `192.0.2.10` mit `X-Forwarded-For: 198.51.100.7` → `198.51.100.7`; (b) dieselbe Anfrage von `192.0.2.11` → `192.0.2.11`; (c) der Name löst danach auf `192.0.2.12` auf: nach der Auffrischung gilt `192.0.2.12`, `192.0.2.10` nicht mehr; (d) die Auflösung scheitert → direkte Adresse und genau eine WARNING über mehrere Anfragen; (e) `gateway,203.0.113.0/24` → beide gelten; (f) ein ungültiger Eintrag (`not a host!`) → Warnung wie heute, ignoriert. Zuerst rot: (a), (c), (e).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_ip_filter.py
Doku: `docs/developer/server.html:45` + `docs/en/developer/server.html:45`: `TRUSTED_PROXIES` nimmt Adressen, Netze oder Hostnamen; Namen werden alle 30 s neu aufgelöst
Beweis: Code-Lesung apps/server/app/core/middleware.py:17-28, :64-90; docker-compose.yml:102
HEAD: b1432223

### T12 — Compose: der Server vertraut dem Gateway; Doku zu TRUSTED_PROXIES und ALLOWED_IPS  [x]
Komponente: server · Dateien: docker-compose.yml, .env.example, apps/server/tests/test_compose_hardening.py, docs/admin/installation.html, docs/en/admin/installation.html, docs/admin/benutzer.html, docs/en/admin/users.html, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @bbb3db8b 2026-10-23T13:00:37+02:00
Review: approve (.ah-out/review/compose-hardening/T12.verdict.json)
Änderung (Empfehlung, Spec offene Fragen 1 und 2): `docker-compose.yml:102` wird `- TRUSTED_PROXIES=gateway${TRUSTED_PROXIES:+,${TRUSTED_PROXIES}}` (Probe Compose v5.5.1: ungesetzt oder leer → `gateway`, gesetzt → `gateway,<wert>`). Der Kommentar `:97-101`: das Gateway ist immer vertraut; `TRUSTED_PROXIES` in `.env` ergänzt weitere direkte Gegenstellen des server; `TRUST_PROXY_HEADERS` wirkt in Compose nicht (gesetztes `TRUSTED_PROXIES` hat Vorrang, `middleware.py:76-90`). `.env.example:120-124` sagt dasselbe, Beispiel mit RFC-5737-Adressen. Tests in `test_compose_hardening.py`: (a) der server hat genau diese Zeile; (b) der scheduler hat kein `TRUSTED_PROXIES` (er nimmt keine HTTP-Anfragen an). Zuerst rot: (a).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_compose_hardening.py
Doku: `docs/admin/installation.html:146-147` + `docs/en/admin/installation.html:57-58` (`TRUSTED_PROXIES`: Default `gateway`, in Compose immer vertraut, zusätzliche Einträge nur für weitere direkte Gegenstellen; `TRUST_PROXY_HEADERS` wirkt in Compose nicht); `:160` + EN `:112` (vor dem Gateway: der Server sieht die Adresse des vorgeschalteten Proxys, dessen `X-Forwarded-For` wertet das Gateway nicht aus); `docs/admin/benutzer.html:132` + `docs/en/admin/users.html:126` (`ALLOWED_IPS` prüft die Client-Adresse, die das Gateway sieht) · CHANGELOG (Changed, umlautfrei: Ratenlimits je Adresse, ALLOWED_IPS und die Adresse im Audit-Log beziehen sich hinter dem Gateway auf den Client; wer ALLOWED_IPS gesetzt hat, prueft vor dem Update, dass die Netze der Clients enthalten sind)
Abhängt von: T11
Beweis: Code-Lesung docker-compose.yml:96-102, apps/server/docker-entrypoint.sh:54-58, apps/server/app/core/middleware.py:74-90
HEAD: b1432223

### T13 — Stack-Prüfung: Client-Adresse hinter dem Gateway  [x]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @c05fe4c4 2026-10-23T13:37:44+02:00
Review: approve (.ah-out/review/compose-hardening/T13.verdict.json)
Änderung: Neuer Schritt nach dem aus T8. (a) Eine Anmeldung über das Gateway mit falschem Passwort (Zertifikat aus Schritt 5) schreibt `auth.login_failed` mit der Adresse des Clients (`apps/server/app/modules/users/auth_router.py:124`, `:155`); die neueste solche Zeile in `audit_log.source_ip` (`apps/server/app/modules/audit/models.py:35`, gelesen über `e2e_dc exec -T postgres psql`) ist nicht leer und nicht die Adresse des gateway im Default-Netz (`docker inspect`). (b) Gegenprobe: dieselbe Anmeldung direkt an `server:8080` aus dem scheduler-Container mit `X-Forwarded-For: 203.0.113.9` → die neue Zeile trägt die Adresse des scheduler-Containers, nicht `203.0.113.9` (der Server vertraut nur dem Gateway). Den echten Lauf fährt die Session wie bei T8.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test)
Abhängt von: T12, T8
