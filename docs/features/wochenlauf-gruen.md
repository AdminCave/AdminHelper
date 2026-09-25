<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Wochenlauf grün — Spec

Roadmap: R-0087 (REG), R-0086, R-0085, R-0089 (BUG) und ein fünfter Fund ohne Zeile (BUG,
`backup_restore`). Quelle: Wochenlauf 2026-09-25, drei Läufe (`08:23`, `09:39`, `09:41`) plus
zwei Schemathesis-Retries; Artefakte lokal unter `.ah-out/weekly/2026-09-25-*` des Worktrees,
aus dem der Lauf kam (nicht versioniert).

## Problem / Motivation

Der erste Wochenlauf nach Stufe 8b ist rot. Der Lauf `2026-09-25-0941` (Commit `df03910e`,
Box 3000, `run.sh all --strict`) endet mit `30 passed, 3 failed, 0 skipped`; rot sind
`schemathesis`, `scripts (hermetic)` und `backup_restore (crown-jewel DR)`. Der Lauf `09:39`
davor kam gar nicht an die Suiten: `vm.py: sync failed: rsync exited 23`, also UNVERIFIED.

Ein roter Wochenlauf blockiert den `beta`-Kanal (CLAUDE.md §2), und solange er aus bekannten
Gründen rot ist, sieht niemand eine neue Regression. Alle fünf Ursachen sind unten belegt,
keine ist geraten.

## Befund je Fund

### F1 — R-0087: `iter_flags_test.sh` hängt an zwei Dingen aus seiner Umgebung (REG)

`iter_flags_test: 23 passed, 4 failed` auf der Box, identisch in `08:23` und `09:41`. Die vier
Fälle haben **zwei verschiedene Ursachen**; die Roadmap-Zeile nennt nur die erste.

1. **`AH_SCHEMATHESIS_EXAMPLES` wird geerbt.** `heavy.sh:76` exportiert `100`, `iter.sh`
   reicht es an die Box weiter (`iter.sh:180-184`), der `scripts`-Block dort vererbt es an jeden
   Test. `iter_flags_test.sh:18` leert `AH_ONLY AH_NO_SYNC AH_REQUIRED`, diese Variable nicht.
   Betroffen: `AH_REQUIRED forwarding` (der erwartete Befehl endet ohne das Budget) und
   `AH_SCHEMATHESIS_EXAMPLES appears although unset`. Lokal nachgestellt mit dem exportierten
   Wert: `25 passed, 2 failed`, genau diese zwei.
2. **Der Lauf kam aus einem Git-Worktree.** In `weekly-wt` ist `.git` eine Datei
   (`gitdir: <Haupt-Checkout>/.git/worktrees/weekly-wt`, ein absoluter Pfad auf der Dev-Box).
   `rsync-exclude.txt` lässt `.git` absichtlich mitreisen; auf der Box zeigt der Zeiger ins
   Leere, `git rev-parse HEAD` und `tree-hash.sh` liefern nichts, und `evidence_envs`
   (`iter.sh:58-69`) gibt korrekt keine Evidenz aus („Empty evidence is honest"). Der Test
   verlangt sie aber aus dem Checkout, in dem er läuft. Betroffen: `AH_HEAD` und
   `AH_TREE_HASH`. Belege: Ein Nachbau mit ins Leere zeigendem `.git` gibt lokal genau diese
   zwei (`25 passed, 2 failed`), und der Wochenlauf `2026-09-18-1137` aus dem Haupt-Checkout war
   auf denselben Fällen grün (`24 passed, 0 failed`).

Die zweite Ursache trifft nicht nur den Wochenlauf: jede Lane ist ein Worktree
(`lane.sh new`), und `Fast-Suite: vm` fährt den `scripts`-Block auf der Box.

### F2 — R-0086: `vm.py sync` scheitert auf einer wiederbenutzten Box (BUG)

`09:39`: `rsync: [generator] delete_file: rmdir(data/frp-config) failed: Permission denied (13)`
→ `rsync error … (code 23)` → UNVERIFIED. `docker-compose.yml:46,159` bindet `./data` ein; ein
Integrationslauf legt dort Verzeichnisse als root an. Der nächste `vm.py run --sync` auf
derselben Box will sie mit `--delete` entfernen, weil `data/` lokal fehlt
(`.gitignore:113` `/data/`), und darf es nicht. `scripts/vm/rsync-exclude.txt` nennt
`apps/server/data`, aber nicht `/data` im Repo-Root.

### F3 — R-0085: `GET /api/notifications/stream` unter `admin_jwt` ist in-process nicht fuzzbar (BUG)

Deterministisch, nicht flaky: rot in `08:23`, `09:41` und beiden Retries, immer genau
`test_api_under_every_auth_context[GET /api/notifications/stream][admin_jwt]`, sonst
`291 passed`.

Kette aus dem Traceback: `stream.py:70 authenticate_stream_user` → `auth.py:86` → Engine
`postgresql+psycopg://adminhelper:***@localhost:5432/adminhelper`. Das ist der Fallback aus
`app/core/config.py:56`. `authenticate_stream_user` und `_stream_reauth_ok` öffnen
**absichtlich** `SessionLocal()` direkt statt `Depends(get_db)` (eine SSE-Antwort lebt
Minuten bis Stunden und darf keine Pool-Verbindung halten). Der Override der Fixture `api_db`
(`tests/test_schemathesis.py:187`) ersetzt nur `get_db` und erreicht diese Sitzung nicht.

- **Box:** `run.sh` exportiert `DATABASE_URL="${DATABASE_URL:-${AH_TEST_DB:-}}"`, beides leer.
  Die Test-DB kommt aus testcontainers, `SessionLocal` fällt auf `localhost:5432` zurück, und
  dort läuft nichts → `OperationalError` → der Fall ist rot.
- **Dev-Box und CI:** `DATABASE_URL` zeigt auf die Test-DB, `SessionLocal` erreicht sie, sieht
  den Admin aus der offenen Test-Transaktion aber nicht → 401. **Grün aus dem falschen Grund:**
  der authentifizierte Pfad wurde dort nie gefuzzt.
- **Mit richtig gebundener Sitzung** (Nachstellung mit `SessionLocal` auf der Test-Verbindung)
  kommt 200, und der Stream endet nie: `requests.exceptions.ReadTimeout … (read timeout=10)`
  aus `schemathesis/python/asgi.py`. Ein endloser `text/event-stream` hat in-process keine
  prüfbare Antwort.

Nachstellung auf der Dev-Box (Box-Bedingung ohne Box): ein pytest-Plugin, das beim Laden
`DATABASE_URL` auf einen toten Port setzt (die App-Engine übernimmt ihn beim Import) und ihn in
`pytest_collection_finish` wieder entfernt (die Fixture `pg_engine` nimmt dann testcontainers).
Aufruf: `pytest -p <plugin> -m schemathesis tests/test_schemathesis.py -k "stream and
admin_jwt"`. Ergebnis: derselbe Fehler, dieselben Frames.

### F4 — R-0089: Offset am Kalenderrand ergibt 500 im Monitoring (BUG)

`POST /maintenance`, Kontext `internal_key`, Body
`{"kind": "detail", "ends_at": "0001-01-01T00:00:00+00:01", …}` → `OverflowError: date value
out of range` in `apps/monitoring/app/schemas.py:220` (`_naive_utc`:
`v.astimezone(timezone.utc)`) → 500. Pydantic macht nur aus `ValueError`/`AssertionError` einen
Validierungsfehler; ein `OverflowError` läuft durch. Das Gegenstück am oberen Rand
(`9999-12-31T23:59:59-00:01` → Jahr 10000) ist derselbe Fehler. Ein naives Jahr 1 ist harmlos:
kein Überlauf, Postgres und SQLite speichern es, `maintenance.py:_once_active` vergleicht nur.
`MaintenanceInput.starts_at/ends_at` ist die **einzige** Datums-Eingabe des Monitorings, und der
Server hat keine (Suche über `app/`, 2026-09-25).

### F5 — ohne Roadmap-Zeile: `restore.sh` wartet über den Socket, fragt dann über TCP (BUG)

`09:41`: `FAIL restore.sh failed` → `psql: error: connection to server at "127.0.0.1", port 5432
failed: Connection refused` → `createdb: error: …`, danach `server record LOST after restore` und
`CA chain changed across restore`. Um `08:23` war derselbe Test grün (`8 passed`).

`scripts/restore.sh:114` wartet mit `docker compose exec -T postgres pg_isready -U adminhelper`,
also ohne `-h` und damit über den Unix-Socket. `restore_db` spricht danach über TCP
(`psql -h 127.0.0.1`, Zeile 129). Der Test stellt einen frischen Host nach (`down -v`, neues
Volume), und dann läuft der Init des offiziellen Images: **belegt** in
docker-library/postgres, `17/alpine3.24/docker-entrypoint.sh:288-297`: `docker_temp_server_start`
„does not listen on external TCP/IP", `-c listen_addresses=''`. Der Socket meldet also schon
während des Init „bereit", TCP antwortet erst nach dem Neustart. Wie groß das Fenster ist, hängt
vom Timing ab, daher ein Lauf grün, der nächste rot.

Das ist ein **Produktfehler**: die DR-Wiederherstellung auf einem frischen Host kann genau so
scheitern. `scripts/tests/sse_push_e2e.sh:65` wartet auf dieselbe Weise und verbindet sich danach
über `127.0.0.1:5433` (alembic, uvicorn). Derselbe Fehler steckt dort latent, bisher zweimal grün.

## Ziel & Nicht-Ziele

**Ziel:** `heavy.sh weekly` wird aus einem beliebigen Checkout grün, auch aus einem Worktree
und auf einer Box, die schon einen Lauf hinter sich hat. Die fünf Ursachen sind behoben, nicht
umgangen, und jede hat einen Test, der ohne den Fix rot ist.

**Nicht-Ziele:**
- Kein Umbau von `vm.py sync`, sodass ein Worktree-`.git` auf der Box benutzbar wird
  (Harness-Datei; die Box braucht es nicht, `iter.sh` reicht die Evidenz mit). Siehe
  Nebenfunde.
- Kein Umbau der kurzlebigen Sitzung in `notifications/stream.py`. Sie ist richtig so, und
  auch eine injizierbare Sitzung würde nur zum `ReadTimeout` führen.
- Keine fachliche Datumsgrenze (etwa 2000–2100) im Monitoring (Entscheidung Kevin,
  2026-09-25): nur der Überlauf wird 422.
- Keine Änderung an `run.sh`, `heavy.sh`, `iter.sh`, `vm.py` (Harness-Pfade).

## Entscheidungen (Kevin, 2026-09-25)

1. F5 kommt ins Vorhaben, `restore.sh` **und** `sse_push_e2e.sh`.
2. F1: Der Test wird hermetisch (eigenes Wegwerf-Repo), statt den Wochenlauf nur noch aus dem
   Haupt-Checkout zu fahren.
3. F3: Die Operation verlässt den Fuzz-Lauf per `raises = true` in
   `schemathesis_exclude.toml`, mit gemessenem Grund. Präzedenz: die Monitoring-Proxy-Einträge
   stehen dort schon als „in-process nicht fuzzbar".
4. F4: Der Überlauf wird an beiden Rändern zu 422, ohne fachlichen Bereich.

## Betroffene Komponenten & Dateien

| Fund | Komponente | Dateien |
|---|---|---|
| F1 | scripts | `scripts/tests/iter_flags_test.sh` |
| F2 | scripts (vm-pytest) | `scripts/vm/rsync-exclude.txt`, `scripts/vm/tests/test_vm.py` |
| F3 | server | `apps/server/tests/schemathesis_exclude.toml` |
| F4 | monitoring | `apps/monitoring/app/schemas.py`, `apps/monitoring/tests/test_maintenance_router.py`, `CHANGELOG.md` |
| F5 | scripts | `scripts/restore.sh`, `scripts/tests/sse_push_e2e.sh`, `scripts/tests/restore_guard_test.sh`, `CHANGELOG.md` |

Kein Harness-Pfad (`scripts/dev/harness-paths.txt`) ist berührt. Die neuen Testfälle für
`restore.sh` kommen in `restore_guard_test.sh`, weil der schon im `scripts`-Block von `run.sh`
steht; ein neues Testskript müsste dort eingetragen werden, und `run.sh` ist ein Harness-Pfad.

## Umsetzung je Fund

**F1.** `AH_SCHEMATHESIS_EXAMPLES` kommt in die `unset`-Zeile. Der Test legt ein Wegwerf-Repo
an (`mktemp -d`, `git init`, ein Commit mit fester Identität) und exportiert `GIT_DIR` und
`GIT_WORK_TREE` darauf, bevor der erste `iter.sh`-Aufruf läuft. `iter.sh` wechselt per
`cd "$VM_ROOT"` in seinen eigenen Checkout, ein `cd` im Test reicht also nicht; die
Git-Variablen gelten aber unabhängig vom Arbeitsverzeichnis. **Verifiziert 2026-09-25:** Im
Nachbau mit ins Leere zeigendem `.git` liefert der Dry-Run mit den beiden Variablen `AH_HEAD`
gleich dem HEAD des Wegwerf-Repos und ein 40-stelliges `AH_TREE_HASH`. Neu dazu kommen zwei
Fälle: `AH_HEAD` ist **gleich** dem HEAD des Wegwerf-Repos (schärfer als die bestehende Regex),
und ohne benutzbares Git (`GIT_DIR` auf einen Pfad ohne Repo) kommt keine Evidenz, der Befehl
bleibt aber intakt und `rc=0` — das dokumentierte Box-Verhalten. Die bestehenden Assertions
bleiben wörtlich stehen.

**F2.** `/data/` kommt **verankert** (führender `/`) in `rsync-exclude.txt`, mit Kommentar im
Stil der Datei. Ohne Anker würde rsync jedes Segment `data` treffen, auch
`apps/server/data/.gitkeep` und künftige getrackte `…/data/`-Pfade. Ausgeschlossene Pfade
schützt rsync vor `--delete`, solange kein `--delete-excluded` gesetzt ist (`vm.py:_sync`
setzt es nicht). Dazu zwei Test-Änderungen in `test_vm.py`:
- `test_the_exclude_list_never_hides_tracked_source` behandelt ein Muster mit führendem `/` als
  am Root verankert (Anker abstreifen, dann Präfix prüfen). Heute liefe `/data/` dort leer
  durch, weil kein getrackter Pfad mit `/` beginnt. Die `assert`-Zeilen bleiben.
- Ein neuer Test fährt **echtes** rsync lokal zwischen zwei Temp-Verzeichnissen mit
  `--exclude-from vm.RSYNC_EXCLUDE --delete`: Ein `data/…` nur im Ziel bleibt stehen, ein
  `data/…` nur in der Quelle reist nicht mit, ein verschachteltes `apps/x/data/…` nur im Ziel
  wird gelöscht (Beweis für den Anker). Er prüft den **Zustand** nach dem Sync, nicht
  Berechtigungen, und beweist damit auch auf einem Runner als root etwas. Kein `pytest.skip`
  bei fehlendem rsync: `vm.py` braucht rsync ohnehin, und `review.sh diff-scan` wertet ein neues
  `pytest.skip(` als Fund. Ob rsync auf `ubuntu-latest` (CI-Job `ops-scripts`) vorinstalliert
  ist, ist **nicht verifiziert**. Fehlt es, bleibt der Job rot und braucht eine Installzeile in
  `ci.yml` (kein Harness-Pfad).

**F3.** Ein `[[exclude]]`-Eintrag für `notification_stream_api_notifications_stream_get` mit
`raises = true`, `reason` aus F3 oben (gemessen, mit Datum) und `until` („solange der
In-Process-Transport eine Streaming-Antwort bis zum Ende liest"). Abgedeckt bleibt: der
401-Pfad in `tests/test_stream.py::TestStreamAuth`, die Re-Auth in `TestStreamReauth`, die
Live-Frames in `sse_push_e2e` und `desktop_e2e_sse_push`. Messbar: der Schemathesis-Schritt
des Servers sammelt 288 statt 292 Fälle (vier Kontexte × eine Operation), und die
Box-Nachstellung von oben selektiert keinen Stream-Fall mehr.

**F4.** In `_naive_utc` wird der `OverflowError` aus `astimezone` zu einem `ValueError` mit
klarer Meldung, also 422 mit Feldbezug. Test in `test_maintenance_router.py`: beide Randwerte
auf `starts_at` und `ends_at`, über `POST` und `PUT`, jeweils 422 mit `loc` auf dem Feld. Das
naive Jahr 1 bleibt gültig (kein neuer Ablehnungsfall).

**F5.** Beide Warteschleifen fragen über TCP (`pg_isready -h 127.0.0.1 -U adminhelper`), also
genau über den Weg, den die Befehle danach nehmen. Test in `restore_guard_test.sh` mit einem
`docker`-Stub im `PATH`, der den Init-Server nachbildet: `pg_isready` ohne `-h` antwortet sofort
0, mit `-h` erst ab dem dritten Aufruf; ein `sh -c …psql…` vor diesem Zeitpunkt endet mit
„Connection refused" (≠ 0). Das Archiv enthält `adminhelper.dump`, damit `restore_db` läuft;
Aufruf mit `--yes`. Erwartung: `restore.sh` endet mit 0, und im Aufruf-Log steht ein
erfolgreiches TCP-`pg_isready` vor dem ersten `psql`. Gegenprobe mit dem alten Befehl: rot.
`sse_push_e2e.sh` braucht Docker und läuft nur im Heavy-Lauf; dort ist es derselbe
Einzeiler.

## Datenmodell / API / Migrationen

Keine Migration, kein neuer Endpunkt, keine Vertrags-Drift. Einzige sichtbare API-Änderung:
Monitoring `POST/PUT /maintenance` antwortet auf einen Offset am Kalenderrand mit 422 statt
500. Der Status 422 steht schon im OpenAPI-Schema (FastAPI), der Snapshot
`apps/monitoring/tests/openapi.snapshot.json` bleibt unverändert.

## Externe Integrationen

- Postgres-Image (docker-library/postgres): Verhalten des Init-Servers **verifiziert** an
  `17/alpine3.24/docker-entrypoint.sh:288-297` (per `gh api`, 2026-09-25). Das Image in
  `docker-compose.yml:13` ist `postgres:17-alpine@sha256:979c…`; die Alpine-Unterversion hinter
  dem Digest ist nicht geprüft, das Init-Verhalten ist über alle Varianten dasselbe Skript.
- rsync: Ausschlüsse sind vor `--delete` geschützt, solange kein `--delete-excluded` gesetzt
  ist. Das belegt der neue Test mit echtem rsync.

## Trade-offs & Alternativen

- **F1 Wegwerf-Repo vs. Wochenlauf nur aus dem Haupt-Checkout:** Der Haupt-Checkout wäre
  kostenlos, ließe aber jede Lane auf der Box rot, und der Haupt-Checkout ist heute von Stufe
  5a belegt. Das Wegwerf-Repo kostet einige Zeilen.
- **F3 `raises = true` vs. eigener Schlüssel `stream = true`:** Ein eigener Schlüssel wäre
  sauberer benannt, bringt aber mehr Reader-Code und eine weitere Regel. Die Präzedenz
  (Proxy-Einträge, „kein Produktfehler, sondern eine Eigenschaft der Fixture") existiert schon.
  Der Satz im Dateikopf, jeder `raises`-Eintrag sei ein echter Produktfehler, stimmt schon heute
  nicht mehr. Ihn zu korrigieren gehört zu T3, weil der neue Eintrag ihm sonst widerspricht.
- **F3 `SessionLocal` in `api_db` binden:** verworfen. Es macht den Fall nicht grün
  (ReadTimeout), und der Event-Bus (`core/events.py`, eigener Thread-Pool) teilte sich dann eine
  psycopg-Verbindung über Threads hinweg.
- **F5 TCP-Warteschleife vs. `sleep`/Retry um `psql`:** Retry verschiebt nur. Die
  Warteschleife prüft dann genau den Weg, den der nächste Befehl nimmt.

## Risiken & Rollback

- F2: Ein falsch verankertes Muster schlösse getrackte Quellen aus. Der Invarianten-Test
  (nach der Anpassung) und der rsync-Test fangen beides. Rollback: die Zeile entfernen.
- F3: Die Stream-Operation verliert ihre Fuzz-Abdeckung. Real war sie auf Dev/CI nie gefuzzt
  (401 aus dem falschen Grund) und auf der Box rot. Rollback: den Eintrag entfernen.
- F5: `pg_isready -h 127.0.0.1` im Container setzt voraus, dass Postgres im Container auf
  Loopback lauscht; im Normalbetrieb tut es das (verifiziert: `17/alpine3.24/Dockerfile:188`
  setzt `listen_addresses = '*'` in der Beispiel-Konfiguration), und `restore_db` verlässt sich
  schon heute darauf. Rollback: `-h` entfernen.
- Alle Tasks sind unabhängig und einzeln revertierbar.

## Doku-Impact

`CHANGELOG.md` → `Fixed`: F4 (Monitoring 422 statt 500 am Kalenderrand) und F5 (`restore.sh`
auf einem frischen Host). Alles andere ist Test-Infrastruktur: keine Doku.

## Offene Fragen

Keine — die vier Entscheidungen oben sind gefallen. Am Gate bleibt: die Roadmap-Zeile für F5
anlegen und R-0087 auf die zwei Ursachen korrigieren (Kevins Datei).

## Nebenfunde (nicht in diesem Vorhaben, Roadmap-Kandidaten)

- **N1 — Event-Bus in den Server-Tests auf der echten Engine.** `fire_event` →
  `core/events.py:_run_event` und `notifications/event_bridge.py:handle_event` öffnen
  `SessionLocal()` im Thread-Pool. Auf der Box scheitern sie still (in der Nachstellung
  sichtbar: `Event-Dispatch fehlgeschlagen (event=server.startup)`); auf Dev/CI schreiben sie in
  die Test-DB **an der Rollback-Klammer vorbei**. Nicht rot, aber ein Isolationsleck.
- **N2 — Worktree-`.git` auf der Box.** Aus einem Worktree gesynct, ist `.git` auf der Box ein
  toter Zeiger. `iter.sh` reicht die Evidenz mit, aber jeder Box-Pfad, der auf git zurückfällt
  (`run.sh` ohne mitgereichtes `AH_HEAD`, etwa unter `AH_NO_SYNC`), bekommt nichts. Dazu ein
  veralteter Kommentar: `iter.sh:50` sagt „The box has no .git", `rsync-exclude.txt` sagt
  „.git stays". Harness.
- **N3 — Positiver Auth-Pfad des SSE-Streams** (gültiges JWT → 200, erster Frame) ist nur
  noch E2E abgedeckt, nicht unterhalb.
