<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Wochenlauf grün — Task-Ledger
Status: geplant · Branch: feature/wochenlauf-gruen · Commit-Granularität: pro Task · Review: pro Task (feature-review) · Modell: Opus
Spec: docs/features/wochenlauf-gruen.md
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: linux-full (Abschluss: Wochenlauf-Wiederholung `heavy.sh weekly` auf Kevins Freigabe, überwacht; siehe „Abschluss" unten)
DoD je Task: CLAUDE.md (Tests grün, ruff/shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: R-0087 (REG), R-0086, R-0085, R-0089 (BUG), F5 `backup_restore` (BUG, Zeile legt Kevin am Gate an) · Hängt ab von: —

**Regeln für dieses Vorhaben.** Je Task erst der Test, der den Fund ohne Fix rot zeigt, dann
der Fix (CLAUDE.md §6). Die **Gegenprobe** (der neue Test fällt ohne den Fix) steht mit ihrem
Ergebnis im Task-Commit bzw. in der Review-Notiz, sonst beweist der Test nichts. Keine
bestehende `assert`-Zeile löschen oder umschreiben, und in neuen Zeilen weder `pytest.skip(`
noch `|| true` noch `set +e`: `review.sh diff-scan` wertet beides als Fund, und für keine Task
ist eine `Test-Löschung:` angekündigt. Der Server-Schritt teilt sich `adminhelper_test` und
`~/.cache/ah-venv` mit dem Haupt-Checkout; `run.sh` stellt die beiden Python-Läufe per `flock`
in die Schlange, ein Warten auf die Sperre ist also kein Fehler.

### T1 — `iter_flags_test.sh` hermetisch: geerbtes Budget und Worktree-`.git` (R-0087)  [ ]
Komponente: scripts · Dateien: scripts/tests/iter_flags_test.sh
Änderung: `AH_SCHEMATHESIS_EXAMPLES` in die `unset`-Zeile (Z. 18). Vor dem ersten `iter.sh`-Aufruf ein Wegwerf-Repo anlegen (`mktemp -d` unter dem bestehenden `$SHIM`-Aufräumen, `git init`, ein Commit mit fester Identität per `-c user.name=… -c user.email=…`) und `GIT_DIR`/`GIT_WORK_TREE` darauf exportieren (`iter.sh` macht `cd "$VM_ROOT"`, ein `cd` im Test reicht nicht; der Weg ist in der Spec verifiziert). Zwei neue Fälle: `AH_HEAD` ist gleich `git rev-parse HEAD` des Wegwerf-Repos; mit `GIT_DIR` auf einem Pfad ohne Repo kommt keine Evidenz, `rc=0`, und der Befehl endet auf `run.sh quick --strict`. Die bestehenden `ok`/`bad`-Zeilen bleiben wörtlich. Gegenprobe, vor und nach dem Fix: (a) `AH_SCHEMATHESIS_EXAMPLES=100` exportiert; (b) eine Kopie von `scripts/` in einem Temp-Verzeichnis mit `.git` = `gitdir: /nonexistent`, dort den Test starten. Vorher je 2 rot (Spec F1), nachher 0.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test)

### T2 — `/data/` bleibt beim Box-Sync außen vor (R-0086)  [ ]
Komponente: scripts · Dateien: scripts/vm/rsync-exclude.txt, scripts/vm/tests/test_vm.py
Änderung: `/data/` **mit führendem `/`** in `rsync-exclude.txt`, mit einem Kommentar im Stil der Datei (gitignored Laufzeitverzeichnis des Compose-Stacks, als root angelegt, `--delete` scheitert sonst mit Code 23). In `test_the_exclude_list_never_hides_tracked_source` ein Muster mit führendem `/` als am Root verankert behandeln (Anker abstreifen, Präfixvergleich), ohne `assert`-Zeilen zu ändern. Ein neuer Test fährt echtes `rsync -a --delete --exclude-from vm.RSYNC_EXCLUDE` zwischen zwei `tmp_path`-Verzeichnissen und prüft den Zustand danach: `data/…` nur im Ziel bleibt, `data/…` nur in der Quelle reist nicht, `apps/x/data/…` nur im Ziel wird gelöscht. Kein `pytest.skip` bei fehlendem rsync. Gegenprobe: ohne die neue Zeile ist der neue Test rot. Fehlt rsync im CI-Job `ops-scripts` (nicht verifiziert), ist der Job rot; dann `[?]` setzen und eine Installzeile in `ci.yml` vorschlagen, nicht still skippen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (der Kommentar in `rsync-exclude.txt` ist die Doku)

### T3 — SSE-Stream verlässt den Fuzz-Lauf, mit gemessenem Grund (R-0085)  [ ]
Komponente: server · Dateien: apps/server/tests/schemathesis_exclude.toml
Änderung: Ein `[[exclude]]` für `notification_stream_api_notifications_stream_get` mit `raises = true`, `# GET /api/notifications/stream`, `reason` aus Spec F3 (Kette `stream.py:70` → `auth.py:86` → Fallback `config.py:56`; Box 500, Dev/CI 401 aus dem falschen Grund, gebunden `ReadTimeout` nach 10 s; Messdatum 2026-09-25; wo der Rest abgedeckt ist: `test_stream.py::TestStreamAuth`/`TestStreamReauth`, `sse_push_e2e`, `desktop_e2e_sse_push`) und `until`. Den Satz im Dateikopf, jeder `raises`-Eintrag sei ein echter Produktfehler, so korrigieren, dass er die Fixture-Fälle (Proxy, Stream) einschließt. Nachweis: Der Server-Schemathesis-Schritt sammelt 288 statt 292 Fälle und ist grün. Gegenprobe unter Box-Bedingung mit dem Plugin aus Spec F3 (vorher der Fehler, nachher `-k "stream and admin_jwt"` ohne Treffer), Ergebnis in die Review-Notiz.
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (die Ausschlussdatei ist ihre eigene Doku)

### T4 — Monitoring: Offset am Kalenderrand ist 422, nicht 500 (R-0089)  [ ]
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/tests/test_maintenance_router.py, CHANGELOG.md
Änderung: Test zuerst: `0001-01-01T00:00:00+00:01` und `9999-12-31T23:59:59-00:01`, je auf `starts_at` und `ends_at`, über `POST /maintenance` und `PUT /maintenance/{id}` → 422, `loc` endet auf dem Feld. Dazu: naives `0001-01-01T00:00:00` bleibt gültig. Vor dem Fix rot (Exception bzw. 500). Dann in `_naive_utc` den `OverflowError` aus `astimezone` in einen `ValueError` mit klarer Meldung umwandeln. Der OpenAPI-Snapshot bleibt unverändert (`test_openapi_snapshot.py` grün).
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: CHANGELOG.md `[Unreleased]` → `Fixed` (Monitoring antwortet auf ein Datum mit Offset am Kalenderrand mit 422 statt 500)

### T5 — `restore.sh` und `sse_push_e2e.sh` warten über TCP (F5, ohne Roadmap-Zeile)  [ ]
Komponente: scripts · Dateien: scripts/restore.sh, scripts/tests/sse_push_e2e.sh, scripts/tests/restore_guard_test.sh, CHANGELOG.md
Änderung: Test zuerst, in `restore_guard_test.sh` (der Kopfkommentar wird auf „hermetische Tests für restore.sh" erweitert): ein `docker`-Stub im `PATH` bildet den Socket-only-Init-Server nach. `pg_isready` ohne `-h` antwortet sofort 0, mit `-h 127.0.0.1` ab dem dritten Aufruf; `sh -c …psql…` davor endet ≠ 0, alles andere endet mit 0 und wird protokolliert. Das Archiv enthält `adminhelper.dump`, Aufruf mit `--yes`. Erwartung: Exit 0, und im Protokoll steht ein erfolgreiches TCP-`pg_isready` vor dem ersten `psql`. Vor dem Fix rot. Dann `restore.sh:114` und `sse_push_e2e.sh:65` auf `pg_isready -h 127.0.0.1 -U adminhelper`, mit einem Satz Kommentar zum Warum (Init-Server nur auf dem Socket, Beleg in der Spec). `sse_push_e2e.sh` braucht Docker; sein Beweis ist der Heavy-Lauf.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: CHANGELOG.md `[Unreleased]` → `Fixed` (`restore.sh` auf einem frischen Host: Warten auf Postgres über TCP statt über den Socket)

## Abschluss (Heavy, auf Kevins Freigabe)

Wochenlauf-Wiederholung `bash scripts/tests/heavy.sh weekly` als überwachter Hintergrund-Lauf
(tmux plus Wächter, `.claude/skills/test/SKILL.md`), **nicht** von selbst gestartet. Aus diesem
Worktree geht das nach T1; das frpc-Sidecar und `.claude/settings.local.json` müssen wie
bisher verlinkt sein, sonst endet der Lauf UNVERIFIED. Erwartet: `schemathesis`,
`scripts (hermetic)` und `backup_restore` grün, und ein zweiter Sync auf dieselbe Box geht durch
(Beweis für T2). `backup_restore` hängt am Timing: Ein grüner Lauf allein beweist T5 nicht, den
deterministischen Beweis liefert der Stub-Test. Nach dem Lauf `python3 scripts/vm/vm.py list`.
