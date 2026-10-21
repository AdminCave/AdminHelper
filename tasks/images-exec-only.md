<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Images server, ca-issuer, monitoring: Programme nur ausführbar, Prozesse von app nicht dumpable — Task-Ledger
Status: aktiv · Branch: feature/images-exec-only · Review: pro Task
Spec: keine eigene Datei (Härtung der Images server/scheduler, ca-issuer und monitoring nach dem Muster des frps-Image, Kevin 2026-10-21)
Heavy: linux-full — T1 und T3 ändern die Images von server und scheduler (`Dockerfile`), `apps/ca-issuer/Dockerfile` und `apps/monitoring/Dockerfile` (CLAUDE.md §5), T2 die Stack-Prüfung `scripts/tests/integration_stack_test.sh`; die gebauten Images fährt der Job `integration-stack` im Sammellauf über `main`; auf PRs läuft er nicht, daher vor dem Merge `gh workflow run ci.yml --ref feature/images-exec-only`. Der Job `docker-build` baut alle Images auf dem PR. Kein `scenario`: `docker-compose.yml`, Install/Update, FRP und PKI bleiben unverändert; kein `windows`.
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Ziel: In den Images von server und scheduler (`Dockerfile`), ca-issuer und monitoring gehören die Programme in
den bin-Verzeichnissen root und sind für alle anderen nur ausführbar (jede ELF-Datei dort `go-r`), wie im
frps-Image `/usr/bin/frps` und `/usr/bin/curl`. Ein Prozess des Nutzers `app` (UID 10001), den der Entrypoint
über `gosu` startet, ist damit nicht dumpable: seine Einträge unter `/proc/<pid>` gehören root:root
(proc_pid(5)), und kein anderer Prozess ohne `CAP_SYS_PTRACE` besteht die Ptrace-Zugriffsprüfung gegen ihn
(ptrace(2), „Ptrace access mode checking“). Skripte (Entrypoint, `uvicorn`, `alembic`, der Code der App) bleiben
lesbar; ihre Interpreter (`python3.12`, `dash`, `perl`) sind es nicht, und es zählt nur das ausgeführte Programm
(Kernel `fs/exec.c`: `would_dump(bprm, bprm->file)` in `begin_new_exec`; Kernel-Doku admin-guide/sysctl/fs,
`suid_dumpable`: „Any process which has changed privilege levels or is execute only will not be dumped.“).
Heute gehört `/proc/<pid>` jedes solchen Prozesses 10001:999 (Probe an den Test-Images, 2026-10-21: dash,
sleep, python, ein Python-Skript, uvicorn samt Workern); mit dem Schritt 0:0, und python, psycopg, alembic,
uvicorn, pip und ping laufen unverändert. Testprozesse starten wie der Entrypoint über einen Starter, der vor
dem exec die UID wechselt (gosu, oder in Python `os.setgroups([])`, `os.setgid`, `os.setuid`, `os.execvp`):
`docker exec -u` und `setpriv` exec'en mit den Capabilities des Containers, und ihr Prozess bleibt auch aus
einem nur ausführbaren Programm dumpable (Probe). T1 und T3 liegen auf dem Risikopfad `apps/ca-issuer/*`
(`scripts/dev/review-risk.txt`): der Bau holt dort zusätzlich den Sicherheitsprüfer. Zeilenangaben:
origin/main@8dec2275.

### T1 — Images server, ca-issuer, monitoring: Programme in den bin-Verzeichnissen nur ausführbar  [x]
Komponente: server · Dateien: Dockerfile, apps/ca-issuer/Dockerfile, apps/monitoring/Dockerfile, apps/server/tests/test_images_exec_only.py, docs/admin/betrieb.html, docs/en/admin/operations.html, CHANGELOG.md
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @73a620c0 2026-10-21T13:02:46+02:00
Review: approve (.ah-out/review/images-exec-only/T1.verdict.json)
Änderung: Jedes der drei Dockerfiles bekommt als letzten `RUN` der letzten Stage, nach dem Anlegen von `app` (`Dockerfile:45-47`, `apps/ca-issuer/Dockerfile:24-26`, `apps/monitoring/Dockerfile:26-28`) und damit nach `apt-get install` und `pip install`, denselben Schritt, Zeichen für Zeichen gleich in allen drei: jede reguläre Datei mit einem x-Bit unter `/usr/local/bin`, `/usr/local/sbin`, `/usr/bin` und `/usr/sbin`, deren erste vier Bytes die ELF-Kennung `\177ELF` sind, verliert das Leserecht für Gruppe und andere (`chmod go-r`: aus 0755 wird 0711; Eigentümer und setuid-Bits bleiben). Skripte und Symlinks bleiben, wie sie sind. Ein Kommentar darüber sagt in zwei, drei Sätzen, warum (Prozesse von app nicht dumpable, `/proc/<pid>` gehört root, wie im frps-Image), und dass der Schritt der letzte `RUN` bleiben muss, damit er alles darüber Installierte erfasst. Test zuerst rot, neue Datei mit SPDX-Header (`reuse annotate --copyright "Kevin Stenzel" --license GPL-3.0-or-later`): (1) ohne Docker: in allen drei Dockerfiles ist der letzte `RUN` der letzten Stage derselbe Schritt, er nennt die vier Verzeichnisse, und nach ihm folgt kein `RUN`, `COPY` oder `ADD`; ein Schritt, der in einem Dockerfile fehlt, abweicht oder vor `pip install` steht, macht den Test rot. (2) Mit Docker, Skip wie bei den frps-Image-Tests (`_built_frps_image`, `apps/server/tests/test_frps_supervisor.py:1882`), wenn Docker oder das gepinnte Basis-Image der letzten Stage nicht da ist; alle drei pinnen dasselbe, das prüft der Test mit: in einem Container des Basis-Images (`--network none`, Default-Capabilities) läuft der aus dem Dockerfile gelesene Schritt als root. Danach hat jede ELF-Datei mit x-Bit in den vier Verzeichnissen kein Leserecht für Gruppe und andere, und `/usr/local/bin/pip3` (Skript) hat weiter 755. Über den Python-Starter aus dem Ziel unter 10001:999 gestartet, haben `python3 -c` (schläft), `sh -c 'sleep 600; :'` (dash und sein `sleep`) und ein lesbares Skript mit `#!/usr/local/bin/python3.12` je `/proc/<pid>/status` mit Eigentümer 0:0; Gegenprobe im selben Container: eine lesbare Kopie (0755) von `sleep` über denselben Starter hat 10001:999; `pip3 --version` unter 10001:999 endet mit 0. Heute sind (1) und (2) rot (kein Schritt im Dockerfile). Vor dem Verify das Basis-Image ziehen (`docker pull` der `FROM`-Zeile der letzten Stage); die Summary-Zeile zeigt die neuen Tests als passed, keinen skipped.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_images_exec_only.py
Doku: `docs/admin/betrieb.html:84` + `docs/en/admin/operations.html:51` — nach der Tabelle im Abschnitt Datenverzeichnis ein Absatz: server, scheduler, ca-issuer und monitoring laufen unter dem Nutzer `app` (UID 10001) aus Programmen, die dieser Nutzer nur ausführen, nicht lesen kann; dazu ein Satz: die UID 10001 sollte auf dem Host keinem anderen Konto oder Dienst gehören (offene Frage am Gate, wie beim frps-Image; bei Nein entfällt er) · CHANGELOG `## [Unreleased]` → `### Changed` (`CHANGELOG.md:1081`), ohne Roadmap-ID, in der Form des Eintrags „Agent: Datenverzeichnis unter Windows mit festen Rechten“ (`:1207`)

### T2 — Stack-Prüfung: Prozesse von app in server, scheduler, ca-issuer und monitoring nicht dumpable  [ ]
Komponente: scripts · Dateien: scripts/tests/integration_stack_test.sh
Änderung: Neuer Schritt `13.` nach Schritt 12 (`scripts/tests/integration_stack_test.sh:619-634`), vor der Summary (`:636`). Er startet `scheduler` und `monitoring` mit `e2e_dc up -d --no-deps --build` (wie `:476`; server und ca-issuer laufen seit `e2e_up gateway`, `:46`, victoria seit `:623`) und wartet begrenzt (60 s), bis jeder der vier Dienste einen Prozess mit `Uid` 10001 hat; sonst `bad`. Je Dienst über `e2e_dc exec -T <dienst> sh -c …` (als root): (a) mindestens ein Prozess mit `Uid` 10001, und `/proc/<pid>/status` jedes solchen Prozesses gehört 0:0 — `ok` mit Anzahl und Namen, sonst `bad` mit pid, Name und Eigentümer; (b) keine ELF-Datei mit x-Bit in den Verzeichnissen aus T1 ist für Gruppe oder andere lesbar, die Liste der Verzeichnisse steht einmal als Variable im Skript. Gegenprobe einmal in `server`: root legt eine lesbare Kopie (0755) von `/usr/bin/sleep` unter `/tmp` an und startet sie mit `gosu app:app <kopie> 120` im Hintergrund (`e2e_dc exec -d -T`); dieselbe Prüfung wie (a) meldet für diesen Prozess 10001 und die GID von app (sonst `bad`: die Prüfung könnte nicht fallen); danach Prozess beenden und Kopie löschen. Den echten Lauf fährt die Session nach dem Commit (Dispatch des `integration-stack`-Jobs auf dem Branch oder `/test` in der Lane); seine Summary-Zeile `integration_stack_test: N passed, 0 failed` kommt in den PR-Text.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test)
Abhängt von: T1

### T3 — Images server und monitoring: auch die PostgreSQL-Clientprogramme nur ausführbar  [ ]
Komponente: server · Dateien: Dockerfile, apps/ca-issuer/Dockerfile, apps/monitoring/Dockerfile, apps/server/tests/test_images_exec_only.py, scripts/tests/integration_stack_test.sh, CHANGELOG.md
Änderung: Der Schritt aus T1 nimmt in allen drei Dockerfiles, weiter Zeichen für Zeichen gleich, `/usr/lib/postgresql` (die Clientprogramme unter `/usr/lib/postgresql/<version>/bin`, gestartet über den Perl-Wrapper `/usr/bin/pg_isready` bzw. `/usr/bin/psql`) in die Liste auf; ein Verzeichnis der Liste, das es im Image nicht gibt (ca-issuer), überspringt er. Die PostgreSQL-Clients prüfen beim Start, ob sie ihr eigenes Programm lesen können, schreiben sonst `invalid binary "<pfad>": Permission denied` auf stderr und laufen weiter (Probe: `pg_isready --version`, `psql --version` Exit 0). In den Entrypoints gehen stderr von `pg_isready` (`apps/server/docker-entrypoint.sh:21`, `apps/monitoring/docker-entrypoint.sh:19`) und des `psql`-SELECT (`apps/monitoring/docker-entrypoint.sh:35-36`) nach `/dev/null`; sichtbar ist die Zeile nur, wenn monitoring beim ersten Start seine Datenbank anlegt (`:38-39`). Der Kommentar im Dockerfile nennt das. Test zuerst rot: der statische Test aus T1 verlangt zusätzlich `/usr/lib/postgresql` in der Liste; der Docker-Test aus T1 läuft auf einem Verzeichnis der Liste, das es im Basis-Image nicht gibt, ohne Fehler durch. Die Variable der Verzeichnisse in `integration_stack_test.sh` (T2) bekommt `/usr/lib/postgresql`, soweit vorhanden.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_images_exec_only.py
Doku: CHANGELOG (den Eintrag aus T1 um die PostgreSQL-Clients und die stderr-Zeile ergänzen) · `docs/admin/betrieb.html`/`docs/en/admin/operations.html` keine (der Absatz aus T1 gilt unverändert)
Abhängt von: T1, T2
