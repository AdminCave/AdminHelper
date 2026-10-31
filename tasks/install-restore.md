<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Install und Restore: bestehende Installation erkennen, `--reset` mit Bestätigung, Start mit `--wait`, Restore auf leerem Host — Task-Ledger
Status: bereit · Branch: feature/install-restore · Review: pro Task
Spec: docs/features/install-restore.md (Roadmap R-0665, R-0668 und der install.sh-Teil von R-0614; der Rest von R-0614 in tasks/update-rollback.md auf feature/update-rollback)
Hängt ab von: feature/ops-install-hardening, feature/ops-scripts-hardening, feature/compose-hardening (gemergt vor dem Bau; Überschneidungen je Funktion in der Spec)
Heavy: linux-full — `scripts/install.sh` im Diff (Install, CLAUDE.md §5) und `scripts/restore.sh`, das `backup_restore_test.sh` (`run.sh integration`) real fährt, mit dem Abschnitt aus T8 (Restore auf einem leeren Host); auf PRs läuft der Stack-Job nicht, daher vor dem Merge `gh workflow run ci.yml --ref feature/install-restore`. Kein `scenario`: kein `multibox.sh`-Flag und kein `box_*.sh` ruft `install.sh`, `restore.sh` oder `uninstall.sh` auf; `install.sh` fährt keine Suite gegen echte Container (Spec, Offene Frage 2). Kein `windows`
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: (1) `install.sh` bricht über einer bestehenden Installation ab, `--reset` löscht nur nach getippter
Bestätigung, ohne `--domain` bleibt die `DOMAIN` der `.env`, der Start wartet mit `--wait` auf gesunde Dienste.
(2) `restore.sh` nimmt Projekt- und Volume-Namen von Compose und ein gepinntes Image, legt auf einem leeren Host die
`.env` aus dem Backup vor dem Start von postgres an und bricht ab, bevor ein Restore halb gelingen kann. (3)
`uninstall.sh` sweept das Projekt, das Compose kennt. Zeilenangaben: origin/main@e2304a8b; die Abhängigkeiten
verschieben sie, der builder greppt vor dem Schreiben neu.

Für alle Tasks:
- Den PR merged Kevin (`scripts/install.sh` im Diff, CLAUDE.md §2).
- Reihenfolge: T1 zuerst, dann T2, T3, T4 (alle `install.sh`/`install_test.sh`; T2 und T4 nutzen die Prüfung und
  den Stub aus T1); T5 → T6 → T8 (T6 nutzt die Namen aus T5, T8 beide); T7 ist unabhängig.
- `security` zusätzlich für T1–T4 (`scripts/install.sh` in `scripts/dev/review-risk.txt`) und T6 (`restore.sh`
  schreibt eine `.env` mit Secrets), für T5 empfohlen (Image über dem CA-Volume).
- Neue Meldungen, Hilfe- und Flag-Texte englisch; bestehende deutsche Texte bleiben.
- Keine Meldung und kein Log nennt ein Passwort oder einen `.env`-Wert; Tests prüfen das mit einem Marker (`zz9…`) im
  Wert.
- Projektname überall gleich: die erste Zeile von `docker compose config` (`name: <projekt>`); Volume-Namen
  `<projekt>_<volume>` (die Compose-Datei gibt keinem Volume einen eigenen `name:`).
- Stubs: Ändert eine Task einen bestehenden Fall nur, damit er mit den neuen Compose-Aufrufen weiterläuft (Antwort auf
  `compose config`, `volume inspect`, eine `.env` in der Fixture), bleibt seine Aussage gleich; der Commit-Body nennt
  jeden solchen Fall.

### T1 — install.sh: bestehende Installation erkennen und abbrechen  [x]
Komponente: scripts · Dateien: scripts/install.sh, scripts/tests/install_test.sh, docs/admin/installation.html, docs/en/admin/installation.html, changelog.d/install-restore.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @4654ff93 2026-10-31T10:01:25+01:00
Review: approve (.ah-out/review/install-restore/T1.verdict.json)
Änderung: (1) Bootstrap-Modus (`install.sh:149-173`): liegt in `$TARGET_DIR` schon eine `.env` oder eine `docker-compose.yml`, Abbruch vor jedem Download (englisch): dort liegt eine Installation oder ein abgebrochener Versuch; Update mit `cd <dir> && ./scripts/update.sh`, neu aufsetzen nach einem abgebrochenen Versuch mit `cd <dir> && ./scripts/install.sh --reset …`; im Zielordner ändert sich nichts. (2) In beiden Modi nach dem Preflight (`:175-177`) und vor jeder Änderung an `.env` (`:207`): Projektname aus `docker compose config` (scheitert es, Abbruch mit der Ausgabe von Compose); eine Installation liegt vor, wenn `docker compose ps --all --quiet` etwas ausgibt oder `docker volume inspect` für `<projekt>_postgres-data` oder `<projekt>_ca-pki` gelingt. Dann ohne `--reset` Abbruch (englisch): nennt das Projekt und was gefunden wurde, Update mit `./scripts/update.sh`, die Daten bleiben; `--reset` nur für einen abgebrochenen Versuch (T2). Eine `.env` allein ist keine Installation (Spec Trade-off 1, Offene Frage 1). (3) Kopfkommentar `:3-26` nennt das. Tests in `install_test.sh`, Stub `:44-58`: `compose config` → `name: ${AH_TEST_PROJECT:-ahtest}`; `compose ps --all --quiet` → `$AH_TEST_CONTAINERS` (Default leer); `volume inspect <name>` → Exit 0 nur für Namen in `$AH_TEST_VOLUMES` (Default keine), sonst 1. (a) Bootstrap (`--ref v0.34.0 --dir <ordner>` wie Test 1) in einen Ordner mit `.env` (`SECRET_KEY=zz9secret`) → Exit ≠ 0, Meldung nennt `update.sh`, keine `docker-compose.yml` im Ordner, `.env` byte-gleich, `zz9secret` nicht in der Ausgabe; ebenso ein Ordner nur mit `docker-compose.yml` (Inhalt byte-gleich danach). (b) Checkout wie Test 5 mit `AH_TEST_VOLUMES=ahtest_postgres-data` → Exit ≠ 0, `.env` byte-gleich, kein `compose pull|up|down` im Aufruf-Log, Meldung nennt `update.sh` und `ahtest`. (c) wie (b) mit `AH_TEST_CONTAINERS=abc123` statt Volume. (d) `AH_TEST_PROJECT=ah-prod`, `AH_TEST_VOLUMES=ah-prod_ca-pki` → Abbruch; Gegenprobe `AH_TEST_VOLUMES=adminhelper_ca-pki` → kein Abbruch (der Name kommt aus `compose config`). Tests 1–7 bleiben grün. Zuerst rot: (a)–(d).
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test doc_smoke_test
Doku: docs/admin/installation.html:94-99 + docs/en/admin/installation.html:72-77 (Kommentar im Codeblock: über einer bestehenden Installation bricht der Installer ab, Updates mit `./scripts/update.sh`) · :214 + EN :167 („einmal über den Install-Einzeiler neu holen“ entfällt, der Weg über `--ref v0.34.0` bleibt) · changelog.d/install-restore.md (Fixed, umlautfrei; als changelog.d/install-restore.md)
Beweis: Code-Lesung scripts/install.sh:149-173, :207, :218-229, :239-246, :269, :299-300; apps/server/app/cli.py:50-52 (create-admin: Benutzer existiert, Exit 1)
Dedup-Key: bug:ops:install.sh:rerun-overwrites-existing-install
HEAD: e2304a8b

### T2 — install.sh: `--reset` nur nach getippter Bestätigung, die die Volumes nennt  [x]
Komponente: scripts · Dateien: scripts/install.sh, scripts/tests/install_test.sh, docs/admin/installation.html, docs/en/admin/installation.html, docs/admin/troubleshooting.html, docs/en/admin/troubleshooting.html, changelog.d/install-restore.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @7d08084d 2026-10-31T10:25:19+01:00
Review: approve (.ah-out/review/install-restore/T2.verdict.json)
Änderung: Findet die Prüfung aus T1 mit `--reset` Container oder Volumes, listet `install.sh` die vorhandenen Volumes des Projekts (die Schlüssel aus `docker compose config --volumes`, je `<projekt>_<schlüssel>`, die `docker volume inspect` findet) und verlangt am Terminal (`$TTY`, wie `:216`) die Eingabe des Projektnamens; nur bei genau dieser Eingabe läuft später `docker compose down -v` (`:262-265`), sonst Abbruch ohne Änderung. Die Abfrage kommt vor jeder Änderung an `.env`; `--yes` überspringt sie nicht; ohne Terminal Abbruch (englisch: `--reset` deletes data and needs a typed confirmation on a terminal). Nach `down -v` prüft das Skript wie in T1 erneut; steht noch ein Volume oder Container, Abbruch vor dem Pull (heute `|| true`). Findet T1 nichts, läuft `--reset` ohne Abfrage wie heute. Hilfe und Kopfkommentar (`:25`) nennen die Bestätigung. Tests in `install_test.sh` am Terminal wie Test 7 (`script` aus util-linux, FIFO als Eingabe; ohne `script` Ende mit 75 wie dort): (a) `--reset --yes`, `AH_TEST_VOLUMES="ahtest_postgres-data ahtest_ca-pki"`, Eingabe `ahtest` → `compose down -v` im Aufruf-Log, die Ausgabe nennt beide Volumes; (b) Eingabe `nein` → Exit ≠ 0, kein `compose down`, `.env` byte-gleich; (c) ohne Terminal (`</dev/null`) mit `--reset --yes` und Volumes → Exit ≠ 0, kein `compose down`; (d) `--reset` ohne Bestand → keine Abfrage, Exit 0; (e) der Stub lässt die Volumes nach `down -v` stehen → Exit ≠ 0 vor `compose pull`. Zuerst rot: (b), (c), (e) (heute löscht `--yes` ohne Frage).
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test doc_smoke_test
Doku: docs/admin/installation.html:99 + EN :77 (`--reset`: löscht nach Eingabe des Projektnamens Container und Volumes eines abgebrochenen Versuchs, auch mit `--yes` nur am Terminal) · docs/admin/troubleshooting.html:38-46 + EN :36-44 (der Installer erkennt das alte `postgres-data`-Volume vor dem Start und bricht mit dem Hinweis auf `update.sh` bzw. `--reset` ab; „wartet 240 s“ entfällt; `--reset` fragt nach dem Projektnamen) · changelog.d/install-restore.md (Changed, umlautfrei)
Abhängt von: T1
Beweis: Code-Lesung scripts/install.sh:250-254 (`--yes` überspringt die einzige Rückfrage), :262-265
Dedup-Key: bug:ops:install.sh:rerun-overwrites-existing-install
HEAD: e2304a8b

### T3 — install.sh: ohne `--domain` bleibt die DOMAIN der vorhandenen `.env`  [x]
Komponente: scripts · Dateien: scripts/install.sh, scripts/tests/install_test.sh, changelog.d/install-restore.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @0e0820ec 2026-10-31T10:35:17+01:00
Review: approve (.ah-out/review/install-restore/T3.verdict.json)
Änderung: `install.sh:218-221`: die Vorgabe für die Abfrage und für `--yes` ist der Text hinter `DOMAIN=` der letzten aktiven Zeile der `.env` (gelesen mit `LC_ALL=C grep -a` wie `upsert_env`, `:200`, unverändert zurückgeschrieben), sonst `localhost`; die Abfrage zeigt sie in `[…]`. `--domain` hat Vorrang. Tests in `install_test.sh`: (a) Checkout wie Test 5, `.env` mit `DOMAIN=old.example`, `--yes` ohne `--domain` → danach genau eine Zeile `DOMAIN=old.example`; (b) `.env` ohne `DOMAIN` → `DOMAIN=localhost`; (c) `--domain new.example` → `DOMAIN=new.example` (wie Test 5). Zuerst rot: (a) (heute `DOMAIN=localhost`).
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test
Doku: changelog.d/install-restore.md (Fixed, umlautfrei)
Beweis: Code-Lesung scripts/install.sh:218-221, :229
Dedup-Key: bug:ops:install.sh:rerun-overwrites-existing-install
HEAD: e2304a8b

### T4 — install.sh: Start mit `docker compose up -d --wait` statt TCP-Schleife  [x]
Komponente: scripts · Dateien: scripts/install.sh, scripts/tests/install_test.sh, changelog.d/install-restore.md, docs/admin/installation.html, docs/en/admin/installation.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @452f039f 2026-10-31T10:45:19+01:00
Review: approve (.ah-out/review/install-restore/T4.verdict.json)
Änderung: Preflight (`:175-177`) wie `tasks/update-rollback.md` T4: die Hilfe von `docker compose up` einmal in eine Variable, fehlt `--wait` oder `--wait-timeout`, Abbruch vor jeder Änderung (englisch, mit `docker compose version --short`). `:266-294`: nach dem Pull `docker compose up -d --wait --wait-timeout "${AH_WAIT_TIMEOUT:-600}" </dev/null` statt `up -d` und der TCP-Schleife; scheitert es, prüft das Skript wie heute die Server-Logs auf `password authentication failed` (Meldung `:284-288` bleibt) und bricht sonst mit einer Meldung ab, die `docker compose ps` und `docker compose logs <dienst>` nennt. `create-admin` erst danach. Tests in `install_test.sh`, Stub aus T1: `compose up --help` → Text mit `--wait` und `--wait-timeout` (außer `AH_TEST_NO_WAIT=1`); `compose up` mit `AH_TEST_UP_FAIL=1` → Exit 1; `compose logs` mit `AH_TEST_PG_AUTH=1` → eine Zeile mit `password authentication failed`. (a) Checkout wie Test 5 → `compose up -d --wait --wait-timeout` im Aufruf-Log, kein `create_connection`, Exit 0; (b) `AH_TEST_UP_FAIL=1` → Exit ≠ 0, kein `create-admin` im Log, Meldung nennt `docker compose ps`; (c) zusätzlich `AH_TEST_PG_AUTH=1` → die Postgres-Passwort-Meldung; (d) `AH_TEST_NO_WAIT=1` → Exit ≠ 0, `.env` byte-gleich, kein `compose pull|up`. Zuerst rot: (a), (b), (d).
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test
Doku: changelog.d/install-restore.md (Fixed, umlautfrei). Die Voraussetzung `up --wait` beschreibt `tasks/update-rollback.md` T4 in `docs/admin/installation.html:84`; steht sie zur Bauzeit nicht auf `main`, ergänzt T4 hier sie dort (DE + EN, `ledger.sh set-files`)
Abhängt von: T1
Beweis: Code-Lesung scripts/install.sh:269-294; Probe zu `up --wait` in docs/features/update-rollback.md (Problem 1)
Dedup-Key: bug:ops:update.sh:no-compose-wait-gateway-healthcheck
HEAD: e2304a8b

### T5 — restore.sh: Projekt- und Volume-Namen von Compose, gepinntes Image statt `alpine`  [x]
Komponente: scripts · Dateien: scripts/restore.sh, scripts/tests/restore_guard_test.sh, changelog.d/install-restore.md, docs/admin/installation.html, docs/en/admin/installation.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @959508c6 2026-10-31T10:53:54+01:00
Review: approve (.ah-out/review/install-restore/T5.verdict.json)
Änderung: `restore.sh:29` und Kopfkommentar `:15-16`: der Projektname kommt aus `docker compose config` (erste Zeile), bestimmt nach dem Entpacken und vor der Rückfrage (`:56`); scheitert `compose config`, Abbruch vor jeder Änderung mit der Ausgabe von Compose. Das Hilfs-Image für `restore_volume` (`:68`) und den Restore von `./data` (`:102`) ist das des Dienstes postgres aus `docker compose config --images postgres` (gepinnt per Digest) statt `alpine`; leer → Abbruch vor jeder Änderung. Die Hilfs-Container laufen mit `--entrypoint sh` (nicht dem Entrypoint des postgres-Images), `--network none` und wie heute als root (Eigentümer der Dateien im Volume bleiben). Tests in `restore_guard_test.sh`: die Stubs der Fälle 5–7 beantworten `compose config` mit `name: drproj` und `compose config --images postgres` mit `postgres:17-alpine@sha256:` + 64 × `a` (keine Aussage ändert sich). Neuer Fall: (a) Archiv mit `ca-pki.tar.gz`, `monitoring-data.tar.gz`, `server-data.tar.gz`, `adminhelper.dump`; Stub mit `name: ah-prod` → das Aufruf-Log hat `ah-prod_ca-pki:/dst` und `ah-prod_monitoring-data:/dst`, jedes `docker run` nutzt das Digest-Image und `--network none`, keines `alpine`; (b) `compose config` scheitert → Exit ≠ 0, kein `compose down`, kein `docker run`. Zuerst rot: (a), (b). Die übrigen Fälle (auch der Abschnitt `backup.sh` aus ops-scripts-hardening) bleiben grün.
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test
Doku: changelog.d/install-restore.md (Fixed, umlautfrei: Restore nutzt den Projektnamen, den Compose nutzt, auch `COMPOSE_PROJECT_NAME` aus der `.env`, und das gepinnte postgres-Image statt `alpine`)
Beweis: Code-Lesung scripts/restore.sh:29, :68, :102; Probe Compose v5.5.1: `.env` mit `COMPOSE_PROJECT_NAME=ah-prod` → `docker compose config` `name: ah-prod`, Volume `ah-prod_ca-pki`; `config --images postgres` → `postgres:17-alpine@sha256:979c4379…`
Dedup-Key: bug:ops:restore.sh:fresh-host-env-and-volume-prefix
HEAD: e2304a8b

### T6 — restore.sh: auf einem leeren Host die `.env` aus dem Backup vor dem Start von postgres  [x]
Komponente: scripts · Dateien: scripts/restore.sh, scripts/tests/restore_guard_test.sh, docs/admin/betrieb.html, docs/en/admin/operations.html, changelog.d/install-restore.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @cde07a3b 2026-10-31T11:11:14+01:00
Review: approve (.ah-out/review/install-restore/T6.verdict.json)
Änderung: Vor der Rückfrage (`:56`) entscheidet `restore.sh` nach `docker volume inspect <projekt>_postgres-data` (Spec Trade-off 3): (1) Volume fehlt, keine `.env` → `env.sanitized` aus dem Archiv wird die `.env` (Kopie daneben mit 0600, dann `mv`), mit angehängter Zeile `CA_ROOT_PASSPHRASE=` (leer: ein restaurierter Stack braucht die Passphrase nicht, `docs/admin/betrieb.html:95`; nach compose-hardening T6 braucht Compose die Zeile), bevor ein Compose-Aufruf postgres startet; den Projektnamen bestimmt in diesem Fall `docker compose --env-file <stage>/env.sanitized config` (`COMPOSE_PROJECT_NAME` aus dem Backup); kein `.env.restored`; Meldung (englisch): `.env` aus dem Backup angelegt. Fehlt `env.sanitized` im Archiv → Abbruch vor jeder Änderung (postgres initialisiert ohne `POSTGRES_PASSWORD` nicht). (2) Volume fehlt, `.env` vorhanden → die `.env` bleibt; `.env.restored` wie heute, mit angehängter Zeile `CA_ROOT_PASSPHRASE=`; die Schlussmeldung sagt, dass beim Übernehmen `POSTGRES_PASSWORD` aus der aktuellen `.env` bleibt (das Volume ist damit initialisiert). (3) Volume vorhanden, `POSTGRES_PASSWORD` weder in der Umgebung noch als nicht leere Zeile der `.env` → Abbruch vor jeder Änderung (sonst scheitert `pg_restore` an der Anmeldung, nachdem die Volumes überschrieben sind). (4) sonst wie heute (`.env.restored` mit der Zeile `CA_ROOT_PASSPHRASE=`). Tests in `restore_guard_test.sh` mit den Stubs aus T5: der Stub antwortet auf `volume inspect …_postgres-data` mit Exit 0 nur bei `AH_TEST_PGVOL=1` und kopiert beim `compose up -d postgres` die `.env` nach `<stub-dir>/env.at-pg-start`. (a) keine `.env`, kein Volume, Archiv mit `env.sanitized` (`POSTGRES_PASSWORD=zz9pg-old`, `COMPOSE_PROJECT_NAME=ah-prod`, `DOMAIN=dr.example`) → Exit 0; `env.at-pg-start` ist `env.sanitized` plus `CA_ROOT_PASSPHRASE=` (`cmp`); `.env` 0600; kein `.env.restored`; die Volume-Namen im Log beginnen mit `ah-prod_`; `zz9` nicht in der Ausgabe. (b) wie (a) ohne `env.sanitized` → Exit ≠ 0, kein `compose down|up`, kein `docker run`, keine `.env`. (c) `.env` mit `POSTGRES_PASSWORD=zz9pg-new`, kein Volume → `.env` byte-gleich, `.env.restored` ist `env.sanitized` plus `CA_ROOT_PASSPHRASE=`, die Ausgabe nennt `POSTGRES_PASSWORD`, kein `zz9`. (d) `AH_TEST_PGVOL=1`, keine `.env`, kein `POSTGRES_PASSWORD` in der Umgebung → Exit ≠ 0 vor jeder Änderung. (e) wie (d) mit exportiertem `POSTGRES_PASSWORD` → läuft durch (die Form von `backup_restore_test.sh`). Die Fixture der Fälle 5–7 bekommt `AH_TEST_PGVOL=1` und ein exportiertes `POSTGRES_PASSWORD` (sonst greift (d)); keine Aussage ändert sich. Zuerst rot: (a), (b), (d).
Verify: bash scripts/dev/verify.sh scripts --strict -- restore_guard_test doc_smoke_test
Doku: docs/admin/betrieb.html:103-104 + docs/en/admin/operations.html:70-71 (statt „auf einem frischen Host … nach .env übernehmen“: auf einem Host ohne Datenbank-Volume und ohne `.env` legt `restore.sh` die `.env` aus dem Backup an, bevor Postgres startet, mit leerer Zeile `CA_ROOT_PASSPHRASE=`; mit vorhandener `.env` bleibt sie, Werte aus `.env.restored` übernimmt man von Hand und behält dabei `POSTGRES_PASSWORD`; der Satz aus compose-hardening T7 zur fehlenden Zeile in `.env.restored` entfällt) · changelog.d/install-restore.md (Fixed, umlautfrei)
Abhängt von: T5
Beweis: Code-Lesung scripts/restore.sh:109-121, :163-173; postgres-Image-Doku (Spec, Externe Integrationen); Restore auf frischem Host nicht gefahren (T8 fährt ihn)
Dedup-Key: bug:ops:restore.sh:fresh-host-env-and-volume-prefix
HEAD: e2304a8b

### T7 — uninstall.sh: Projektname für den Label-Sweep von Compose  [x]
Komponente: scripts · Dateien: scripts/uninstall.sh, scripts/tests/uninstall_test.sh, changelog.d/install-restore.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ebf2516c 2026-10-31T11:18:10+01:00
Review: approve (.ah-out/review/install-restore/T7.verdict.json)
Änderung: `uninstall.sh:55-58`: der Projektname kommt aus `docker compose config` (erste Zeile), damit der Label-Sweep (`:130-135`) auch mit `COMPOSE_PROJECT_NAME` in der `.env` das Projekt trifft; scheitert `compose config` (eine defekte Compose-Datei, genau der Fall, für den der Sweep da ist), gilt die heutige Ableitung (Umgebung, sonst Verzeichnisname). Kommentar `:55-57` angepasst. `nuke_path` (`:146`) bleibt (Spec, Nicht-Ziele). Tests in `uninstall_test.sh`, Stub `:31-35`: `compose config` → `name: ${AH_TEST_PROJECT:-$COMPOSE_PROJECT_NAME}`, mit `AH_TEST_CONFIG_FAIL=1` Exit 1. (a) ohne `COMPOSE_PROJECT_NAME` in der Umgebung, `AH_TEST_PROJECT=ah-prod` → `label=com.docker.compose.project=ah-prod` im Aufruf-Log, die Kopfzeile nennt `ah-prod`; (b) `AH_TEST_CONFIG_FAIL=1` → Label aus dem Verzeichnisnamen. Bestehende Fälle bleiben grün. Zuerst rot: (a).
Verify: bash scripts/dev/verify.sh scripts --strict -- uninstall_test
Doku: changelog.d/install-restore.md (Fixed, umlautfrei)
Beweis: Code-Lesung scripts/uninstall.sh:58, :130-135; Probe wie T5
Dedup-Key: bug:ops:restore.sh:fresh-host-env-and-volume-prefix
HEAD: e2304a8b

### T8 — Stack-Prüfung: Restore auf einem leeren Host mit `COMPOSE_PROJECT_NAME` in der `.env`  [x]
Komponente: scripts · Dateien: scripts/tests/backup_restore_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @62efa19f 2026-10-31T12:00:54+01:00
Review: approve (.ah-out/review/install-restore/T8.verdict.json)
Änderung: Neuer Abschnitt nach dem bestehenden Restore, vor der Summary. In einem eigenen Install-Verzeichnis unter `$E2E_WORK` (Kopien von `docker-compose.yml`, `docker-compose.test.yml`, `scripts/backup.sh`, `scripts/restore.sh`) mit einer `.env` aus der E2E-`.env` plus `COMPOSE_PROJECT_NAME=<E2E_PROJECT>` und `COMPOSE_FILE=docker-compose.yml:docker-compose.test.yml`, in einer Subshell ohne die exportierten Variablen des Tests (`COMPOSE_PROJECT_NAME`, `COMPOSE_FILE` und die der E2E-`.env`, `:59-64`): `backup.sh` → `docker compose down -v` (kein Volume des Projekts mehr) → `.env` entfernen → `restore.sh <archiv> --yes`. Erwartet: Exit 0; `.env` 0600 und gleich `env.sanitized` des Archivs plus `CA_ROOT_PASSPHRASE=`; der Seed-Datensatz und der CA-Fingerprint wie vor dem Backup (Helfer des Tests); kein Volume `<verzeichnisname>_ca-pki`. Den echten Lauf fährt die Session (`/test` in der Lane bzw. Dispatch des Jobs mit `run.sh integration`); die Summary-Zeile kommt in den PR-Text.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test)
Abhängt von: T5, T6

## Entscheidungen
- 2026-10-31 T1: CHANGELOG-Einträge aller Tasks in `changelog.d/install-restore.md` statt `CHANGELOG.md` — Konvention `changelog.d/README.md`, parallele Branches ändern nie dieselbe Datei.
- 2026-10-31 T5: der Grammatik-Nit des Task-Prüfers zu T4 (Plural „brechen“/„stop“, `installation.html` DE+EN) geht mit T5, damit T4 nicht erneut geprüft werden muss. Neuer Fall 26(c): ein leeres `config --images postgres` bricht ebenso ab.
- 2026-10-31 T6: `POSTGRES_PASSWORD` der Fixture der Fälle 5–7 und 23–25 steht in deren `.env` (`PG_ENV`, im Fall 24 in der Umgebung), statt exportiert zu sein; die Stubs dieser Fälle antworten auf jedes `volume inspect`. Fall 27(b) und (d) geben die Rollen-Passwörter in der Umgebung mit, damit die Prüfung der Rollen-Passwörter nicht zuerst abbricht. Ohne `.env` und mit Volume (Projekt aus dem Backup) läuft der Restore wie heute gegen Umgebung und Verzeichnisnamen.
- 2026-10-31 T6 (Review): ohne Volume und ohne `.env` bricht der Restore nur ab, wenn auch die Umgebung kein `POSTGRES_PASSWORD` trägt (abweichend vom Wortlaut von (b)): `backup_restore_test.sh` stellt nach `down -v` aus einem Backup ohne `env.sanitized` wieder her, mit exportierten Werten (Fall 27f). Fehlt der `.env` des Backups ein Rollen-Passwort, nennt die Meldung das Backup statt der Staging-Datei (27g).
