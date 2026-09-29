<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Wochenlauf grün — Task-Ledger
Status: erledigt · Branch: feature/wochenlauf-gruen · Commit-Granularität: pro Task · Review: pro Task (feature-review; T6 Harness-Pfad ⇒ Reviewer Opus) · Modell: Opus
Spec: docs/features/wochenlauf-gruen.md
Freigabe: Kevin, 2026-09-25, übermittelt durch die Aufsichts-Session adminhelper-ac; Bau als Lane (`lane.sh new wochenlauf-gruen`)
Heavy: linux-full (Abschluss: Wochenlauf-Wiederholung `heavy.sh weekly` auf Kevins Freigabe, überwacht; siehe „Abschluss" unten)
DoD je Task: CLAUDE.md (Tests grün, ruff/shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: R-0087, R-0092 (REG), R-0086, R-0085, R-0089 (BUG), F5 `backup_restore` (BUG, Zeile legt die Aufsicht an) · Hängt ab von: —

**Regeln für dieses Vorhaben.** Je Task erst der Test, der den Fund ohne Fix rot zeigt, dann
der Fix (CLAUDE.md §6). Die **Gegenprobe** (der neue Test fällt ohne den Fix) steht mit ihrem
Ergebnis im Task-Commit bzw. in der Review-Notiz, sonst beweist der Test nichts. Keine
bestehende `assert`-Zeile löschen oder umschreiben, und in neuen Zeilen weder `pytest.skip(`
noch `|| true` noch `set +e`: `review.sh diff-scan` wertet beides als Fund, und für keine Task
ist eine `Test-Löschung:` angekündigt. Die Lane hat ihre eigene Test-DB und ihr eigenes Venv
(`lane.sh new`). `run.sh` stellt `server-pytest` und `schemathesis` trotzdem je Nutzer per
`flock` in die Schlange, ein Warten auf die Sperre ist also kein Fehler. **T1 zuerst:** Bis T1
committet ist, bleibt `iter_flags_test` auf der Lane-Box rot, weil das `.git` der Lane dort
ins Leere zeigt (Spec F1). Das ist der Befund selbst, kein Fehler der späteren Tasks.

### T1 — `iter_flags_test.sh` hermetisch: geerbtes Budget und Worktree-`.git` (R-0087)  [x]
Komponente: scripts · Dateien: scripts/tests/iter_flags_test.sh
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped @9c6823bb 2026-09-25T13:10:11+02:00
Review: approve (sonnet); Gegenprobe vorher 25/2 + 25/2, nachher 29/0 + 29/0; Lane-Box: iter_flags_test 29 passed
Änderung: `AH_SCHEMATHESIS_EXAMPLES` in die `unset`-Zeile (Z. 18). Vor dem ersten `iter.sh`-Aufruf ein Wegwerf-Repo anlegen (`mktemp -d` unter dem bestehenden `$SHIM`-Aufräumen, `git init`, ein Commit mit fester Identität per `-c user.name=… -c user.email=…`) und `GIT_DIR`/`GIT_WORK_TREE` darauf exportieren (`iter.sh` macht `cd "$VM_ROOT"`, ein `cd` im Test reicht nicht; der Weg ist in der Spec verifiziert). Zwei neue Fälle: `AH_HEAD` ist gleich `git rev-parse HEAD` des Wegwerf-Repos; mit `GIT_DIR` auf einem Pfad ohne Repo kommt keine Evidenz, `rc=0`, und der Befehl endet auf `run.sh quick --strict`. Die bestehenden `ok`/`bad`-Zeilen bleiben wörtlich. Gegenprobe, vor und nach dem Fix: (a) `AH_SCHEMATHESIS_EXAMPLES=100` exportiert; (b) eine Kopie von `scripts/` in einem Temp-Verzeichnis mit `.git` = `gitdir: /nonexistent`, dort den Test starten. Vorher je 2 rot (Spec F1), nachher 0.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test)

### T2 — `/data/` bleibt beim Box-Sync außen vor (R-0086)  [x]
Komponente: scripts · Dateien: scripts/vm/rsync-exclude.txt, scripts/vm/tests/test_vm.py
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped @56804f32 2026-09-25T13:21:24+02:00
Review: approve (sonnet); Gegenprobe: Test ohne /data/ rot, mit gruen; Lane-Box: Sync --delete ueber root-eigenes data/frp-config ohne Code 23
Änderung: `/data/` **mit führendem `/`** in `rsync-exclude.txt`, mit einem Kommentar im Stil der Datei (gitignored Laufzeitverzeichnis des Compose-Stacks, als root angelegt, `--delete` scheitert sonst mit Code 23). In `test_the_exclude_list_never_hides_tracked_source` ein Muster mit führendem `/` als am Root verankert behandeln (Anker abstreifen, Präfixvergleich), ohne `assert`-Zeilen zu ändern. Ein neuer Test fährt echtes `rsync -a --delete --exclude-from vm.RSYNC_EXCLUDE` zwischen zwei `tmp_path`-Verzeichnissen und prüft den Zustand danach: `data/…` nur im Ziel bleibt, `data/…` nur in der Quelle reist nicht, `apps/x/data/…` nur im Ziel wird gelöscht. Kein `pytest.skip` bei fehlendem rsync. Gegenprobe: ohne die neue Zeile ist der neue Test rot. Fehlt rsync im CI-Job `ops-scripts` (nicht verifiziert), ist der Job rot; dann `[?]` setzen und eine Installzeile in `ci.yml` vorschlagen, nicht still skippen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (der Kommentar in `rsync-exclude.txt` ist die Doku)

### T3 — SSE-Stream verlässt den Fuzz-Lauf, mit gemessenem Grund (R-0085)  [x]
Komponente: server · Dateien: apps/server/tests/schemathesis_exclude.toml, apps/server/tests/test_schemathesis.py
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @76c38e82 2026-09-25T13:54:41+02:00
Review: approve (sonnet, 2. Runde: reason um die drei Kontexte ohne Bearer ergaenzt); Gegenprobe Box-Bedingung vorher OperationalError, nachher 288 deselected; Lane-Box schemathesis 288 passed
Änderung: Ein `[[exclude]]` für `notification_stream_api_notifications_stream_get` mit `raises = true`, `# GET /api/notifications/stream`, `reason` aus Spec F3 (Kette `stream.py:70` → `auth.py:86` → Fallback `config.py:56`; Box 500, Dev/CI 401 aus dem falschen Grund, gebunden `ReadTimeout` nach 10 s; Messdatum 2026-09-25; wo der Rest abgedeckt ist: `test_stream.py::TestStreamAuth`/`TestStreamReauth`, `sse_push_e2e`, `desktop_e2e_sse_push`) und `until`. Den Satz im Dateikopf, jeder `raises`-Eintrag sei ein echter Produktfehler, so korrigieren, dass er die Fixture-Fälle (Proxy, Stream) einschließt. Nachweis: Der Server-Schemathesis-Schritt sammelt 288 statt 292 Fälle und ist grün. Gegenprobe unter Box-Bedingung mit dem Plugin aus Spec F3 (vorher der Fehler, nachher `-k "stream and admin_jwt"` ohne Treffer), Ergebnis in die Review-Notiz.
Verify: bash scripts/dev/verify.sh server --strict
Doku: keine (die Ausschlussdatei ist ihre eigene Doku)

### T4 — Monitoring: Offset am Kalenderrand ist 422, nicht 500 (R-0089)  [x]
Komponente: monitoring · Dateien: apps/monitoring/app/schemas.py, apps/monitoring/tests/test_maintenance_router.py, CHANGELOG.md
Evidenz: run.sh[quick]: 4 passed, 0 failed, 13 skipped @a81a2ecc 2026-09-25T14:01:15+02:00
Review: approve (sonnet); Gegenprobe: vorher 4 failed (OverflowError), nachher gruen; CI-aequivalent 495 passed; Lane-Box monitoring 485 + schemathesis 114 passed
Änderung: Test zuerst: `0001-01-01T00:00:00+00:01` und `9999-12-31T23:59:59-00:01`, je auf `starts_at` und `ends_at`, über `POST /maintenance` und `PUT /maintenance/{id}` → 422, `loc` endet auf dem Feld. Dazu: naives `0001-01-01T00:00:00` bleibt gültig. Vor dem Fix rot (Exception bzw. 500). Dann in `_naive_utc` den `OverflowError` aus `astimezone` in einen `ValueError` mit klarer Meldung umwandeln. Der OpenAPI-Snapshot bleibt unverändert (`test_openapi_snapshot.py` grün).
Verify: bash scripts/dev/verify.sh monitoring --strict
Doku: CHANGELOG.md `[Unreleased]` → `Fixed` (Monitoring antwortet auf ein Datum mit Offset am Kalenderrand mit 422 statt 500)

### T5 — `restore.sh` und `sse_push_e2e.sh` warten über TCP (F5, ohne Roadmap-Zeile)  [x]
Komponente: scripts · Dateien: scripts/restore.sh, scripts/tests/sse_push_e2e.sh, scripts/tests/restore_guard_test.sh, CHANGELOG.md
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped @53cd46db 2026-09-25T14:12:41+02:00
Review: approve (sonnet, mit Mutationsprobe); Gegenprobe: vorher rc=2 / 4 passed 2 failed, nachher 6 passed lokal und auf der Lane-Box
Änderung: Test zuerst, in `restore_guard_test.sh` (der Kopfkommentar wird auf „hermetische Tests für restore.sh" erweitert): ein `docker`-Stub im `PATH` bildet den Socket-only-Init-Server nach. `pg_isready` ohne `-h` antwortet sofort 0, mit `-h 127.0.0.1` ab dem dritten Aufruf; `sh -c …psql…` davor endet ≠ 0, alles andere endet mit 0 und wird protokolliert. Das Archiv enthält `adminhelper.dump`, Aufruf mit `--yes`. Erwartung: Exit 0, und im Protokoll steht ein erfolgreiches TCP-`pg_isready` vor dem ersten `psql`. Vor dem Fix rot. Dann `restore.sh:114` und `sse_push_e2e.sh:65` auf `pg_isready -h 127.0.0.1 -U adminhelper`, mit einem Satz Kommentar zum Warum (Init-Server nur auf dem Socket, Beleg in der Spec). `sse_push_e2e.sh` braucht Docker; sein Beweis ist der Heavy-Lauf.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: CHANGELOG.md `[Unreleased]` → `Fixed` (`restore.sh` auf einem frischen Host: Warten auf Postgres über TCP statt über den Socket)

### T6 — `heavy.sh` klassifiziert jeden roten Schritt, nicht nur den ersten (R-0092)  [x]
Komponente: scripts · Dateien: scripts/tests/heavy.sh, scripts/tests/heavy_test.sh
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped @36ccbb96 2026-09-25T14:25:45+02:00
Review: approve (opus, Harness-Pfad; eigene Gegenprobe 166/4 -> 170/0; 2 nits eingearbeitet); Lane-Box heavy_test 170 passed
Änderung: **Harness-Pfad** (`heavy.sh`): Kevins Freigabe gilt über das Gate. In der interaktiven Session warnt `harness-guard.sh` nur; ein Runner mit `AH_AUTONOMOUS=1` braucht `bash scripts/dev/harness.sh off` (Kevins Handgriff). Test zuerst, in `heavy_test.sh`: ein Fall mit **zwei** roten Schritten (Artefakt mit zwei `fail`), die beide über die Retries in die Zweit-VM laufen. Die ssh-gestützten Fixture-Shims `$FIX/scripts/vm/warm.sh` und `iter.sh` leeren stdin wie ssh, nur bei gesetztem Schalter (z. B. `SHIM_DRAIN_STDIN=1`), und der Fall ruft `heavy.sh … </dev/null` auf. Erwartung: beide Schritte mit Urteil in `history.csv` und in der Tabelle von `report.md`, Summenzeile `2 step(s) red after retries`. Vor dem Fix sieht der Fall nur den ersten (Gegenprobe, Ergebnis in die Review-Notiz). Dann in `heavy.sh` beide Leseschleifen über `steps-all.tsv` (Z. 356-364 und 369-382) auf einen eigenen Deskriptor umstellen (`read -r … <&3`, `done 3< "$OUT/steps-all.tsv"`), den Kommentar an `rerun_step` (Z. 437-439) auf den neuen Grund umschreiben, die bestehenden `</dev/null` stehen lassen. Ursache und Nachstellung: Spec F6.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; der Kommentar an der Schleife ist die Doku)

### T7 — hooks_test.sh: `git check-attr` auf einer Box aus einem Worktree (Fund aus T1)  [x]
Komponente: scripts · Dateien: scripts/tests/hooks_test.sh
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped @2a8dd0ae 2026-09-25T14:54:07+02:00
Review: approve (opus, Harness-Pfad; nit git init ohne geerbte GIT_* eingearbeitet); Gegenprobe Box-Kopie 170/1 -> 171/0, Mutation rot; Lane-Box scripts (hermetic) gruen
Änderung: **Fund beim Bau von T1, nicht in der Spec.** Der `scripts`-Block von `run.sh` bricht beim ersten roten Test ab; im Wochenlauf war das `iter_flags_test`, deshalb lief `hooks_test` dort nie. Nach T1 auf der Lane-Box (aus diesem Worktree gesynct, 2026-09-25): `hooks_test: 170 passed, 1 failed`, rot ist genau `git does not see the union attribute` (`git -C "$REPO_ROOT" check-attr merge -- CHANGELOG.md` braucht ein Repo, auf der Box ist `.git` ein toter Zeiger, Spec N2). Die 17 Tests danach laufen dort einzeln alle grün (u. a. `heavy_test: 166 passed`, `lane_test: 59 passed`). Ohne Lösung bleibt `scripts (hermetic)` im Wochenlauf aus einem Worktree rot. `hooks_test.sh` ist ein Harness-Pfad und außerhalb des freigegebenen Scopes.
Entscheidung: Kevin, 2026-09-25, übermittelt durch die Aufsichts-Session adminhelper-ac: Option (a) auf die Frage „Wie soll hooks_test auf einer Worktree-Box die union-Attribut-Pruefung fahren? (a) wie T1 gegen ein Wegwerf-Repo mit Kopie der .gitattributes (Harness-Test, deine Freigabe noetig), (b) N2 an der Wurzel (vm.py sync ersetzt den Worktree-Zeiger), (c) Wochenlauf nur aus dem Haupt-Checkout“. Umsetzung: ein Wegwerf-`GIT_DIR` über **genau diesem** Arbeitsbaum (`GIT_WORK_TREE=$REPO_ROOT`), exportiert nur um die unveränderte Prüfzeile herum. Abweichung von „Kopie der .gitattributes“: so bleibt die bestehende Assertion wörtlich stehen (Regel oben), und geprüft wird die echte Datei statt einer Kopie. Gegenprobe: eine Box-Kopie (rsync mit `rsync-exclude.txt`, `.git` = `gitdir: /nonexistent`) zeigt vorher `170 passed, 1 failed`, nachher 0 rot.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test)

### T8 — Nacharbeit aus dem Branch-Review: `GIT_*` des Aufrufers in iter_flags_test, rc im Zwei-Schritt-Fall  [x]
Komponente: scripts · Dateien: scripts/tests/iter_flags_test.sh, scripts/tests/heavy_test.sh
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped @50dbca51 2026-09-25T14:42:05+02:00
Review: approve (sonnet; nit GIT_OBJECT_DIRECTORY bewusst nicht, kein realistischer Aufrufer); Gegenprobe: Aufrufer-Index vorher mit seed, nachher sauber
Änderung: Zwei Funde aus `/code-review` über den Branch-Diff, beide im neuen Code dieses Vorhabens. (1) `iter_flags_test.sh` legt das Wegwerf-Repo mit geerbten `GIT_DIR`/`GIT_WORK_TREE`/`GIT_INDEX_FILE` an; aus einem Kontext, der sie exportiert (etwa ein Git-Hook mit `GIT_INDEX_FILE`), schreibt `git add seed` in den Index des Aufrufers. Die drei kommen in die `unset`-Zeile. Gegenprobe: ein Aufrufer-Repo mit exportiertem `GIT_INDEX_FILE`, vorher steht `seed` in dessen Index, nachher nicht. (2) Der Zwei-Schritt-Fall in `heavy_test.sh` (T6) liest `rc`, prüft ihn aber nicht; zwei unbestätigte Kandidaten sind Exit 1 wie im Nachbarfall `candidate_case`.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (Test)

## Abschluss (Heavy, auf Kevins Freigabe)

Wochenlauf-Wiederholung `bash scripts/tests/heavy.sh weekly` als überwachter Hintergrund-Lauf
(tmux plus Wächter, `.claude/skills/test/SKILL.md`), **nicht** von selbst gestartet. Aus diesem
Worktree geht das nach T1; das frpc-Sidecar und `.claude/settings.local.json` müssen wie
bisher verlinkt sein, sonst endet der Lauf UNVERIFIED. Erwartet: `schemathesis`,
`scripts (hermetic)` und `backup_restore` grün, und ein zweiter Sync auf dieselbe Box geht durch
(Beweis für T2). `backup_restore` hängt am Timing: Ein grüner Lauf allein beweist T5 nicht, den
deterministischen Beweis liefert der Stub-Test. Ist ein Schritt rot, nennt `report.md` jetzt
jeden (Beweis für T6). Nach dem Lauf `python3 scripts/vm/vm.py list`.

**Kapazität, außerhalb des Codes:** Der Capstone passte am 2026-09-25 nicht auf den Knoten
(−7061 MiB, ohne Box 3000 noch −5348 MiB; Spec „Offene Fragen"). Ohne freien Speicher bleibt
die Kopfzeile UNVERIFIED, auch wenn `all` grün ist. Das entscheidet Kevin vor dem Lauf.

**Ergebnis (2026-09-25-1529, gestartet von adminhelper-ac auf Kevins Wort, aus diesem Worktree nach
dem Merge von `origin/main`, Commit `62e7ac16`):** Kopfzeile `UNVERIFIED (multibox.sh exited 74
(infrastructure))`. Wörtlich:

    run.sh[all]: 34 passed, 0 failed, 0 skipped, 19 test-skips, 0 reruns
    multibox: 0 ok, 1 failed, 0 skipped  (doctor refused the scenario, exit 74)

Die Ebene `all` ist unter `--strict` vollständig grün, darunter `schemathesis`, `scripts (hermetic)`,
`backup_restore`, `sse_push_e2e` und alle Desktop-E2E. Die warme Box 3000 mit dem root-eigenen `data/`
wurde wiederverwendet, der Sync ging durch (Beweis für T2). Kein Schritt war rot, T6 wurde also
nicht live ausgeübt (sein Beweis ist `heavy_test`). Der Capstone scheiterte vor dem ersten Klon an der
Kapazität (−7086 MiB), nicht am Code. Danach `vm.py list`: 0 eigene Boxen, Box 3000 per `reap.sh`
abgebaut. Frischer Opus-Review über `origin/main...HEAD`: approve (ein nit: Wegwerf-Repos lesen weiter
die globale Git-Konfiguration).
