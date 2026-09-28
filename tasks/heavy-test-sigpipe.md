<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# heavy_test ohne SIGPIPE-Flake (R-0103) — Task-Ledger
Status: bereit · Branch: harness/heavy-test-sigpipe · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Kevin, 2026-09-27 („alle freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: Roadmap R-0103
Heavy: none — hermetische Testskripte und ein Listeneintrag im scripts-Block von run.sh; kein Stack-, Gateway-, PKI- oder Install-Pfad, heavy.sh bleibt unverändert.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Hängt ab von: harness-stufe-5c — 5c T1 ändert heavy_test.sh, T2 hier run.sh

Geplant 2026-09-27 von der Aufsicht (adminhelper-ac) auf Kevins Wort. Kevins Entscheidung: seriell nach 5c,
Fix plus Wächter. Branch `harness/`, weil T2 `scripts/tests/run.sh` ändert (Harness-Pfad): Bau interaktiv.
Zeilen nach dem 5c-Merge frisch greppen (4i-d rückt auf etwa :585, Fall 10 auf etwa :1143).

Ursache, belegt: git flusht in eine Pipe nach jedem Datensatz (`man git`, GIT_FLUSH: „Git will choose
buffered or record-oriented flushing based on whether stdout appears to be redirected to a file or not"),
`grep -q` endet beim Treffer in der mittleren Zeile, git bekommt beim nächsten Schreiben SIGPIPE (141), und
`set -uo pipefail` (heavy_test.sh:18) macht aus dem Treffer ein Rot. Häufigkeit rund 3 % je Lauf (2 von 70
erhaltenen Läufen), nicht „1 von 3". Falle beim Nachstellen: In der Tool-Shell von Claude Code ist `grep` eine
Shell-Funktion, die das Lese-Ende offen hält; nachstellen nur in `bash --noprofile --norc -c` oder einem Skript.

### T1 — 4i-d und Fall 10: das git-Log erst in eine Variable  [x]
Komponente: scripts · Dateien: scripts/tests/heavy_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @b240a732 2026-09-28T14:49:38+02:00
Review: am Ende (Kurz-Ledger)
Änderung: heavy_test.sh:581–582 (4i-d) wird `log=$(git -C "$AH_PRIVATE_DIR" log --format=%s)` und danach
`grep -qx 'roadmap: add R-0018' <<<"$log" && ok … || bad "log: $log"`; :1110–1111 (Fall 10) in derselben Form.
Ein Kommentar nennt SIGPIPE, pipefail und R-0103. Kein `|| true`, kein `GIT_FLUSH=0` (hilft nur, solange die
Ausgabe kleiner ist als der Puffer). Die Assertion bleibt inhaltlich dieselbe.
Beweis: harness/stufe-5b@5e75985e · `bash scripts/tests/heavy_test.sh` → 2 von 70 Läufen `heavy_test: 178 passed, 1 failed` mit `FAIL log: weekly 2026-09-25 / roadmap: add R-0018 / seed`; deterministisch auf origin/main@70e91718 in `bash --noprofile --norc -c`: `GIT_EXTERNAL_DIFF='sleep 0.15; :' git log --no-merges -3 --format=%s -p --ext-diff 70e91718 | grep -qx 'fix(deps): install sqlalchemy with the asyncio extra'` → `PIPESTATUS=141 0`, 3 von 3; Treffer in der letzten Zeile oder Ausgabe erst in eine Variable → grün
Semantik: .claude/rules/testing.md:37 — „Ein erst roter, dann grüner Test ist `flaky`, kein PASS." · docs/features/harness-stufe-5.md:41–42 — „jede Schreiboperation unter `flock`, mit `.bak`, geprüfter Zeilenzahl und einem lokalen Commit" (das prüft 4i-d, das Verhalten stimmt; falsch ist die Prüfung)
Dedup-Key: bug:scripts:heavy_test.sh:4i-d-roadmap-log
HEAD: 70e91718
Kosten: rund 10 000 Pipe-Läufe, etwa 3 min, keine VM
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T2 — Wächter: kein git-Erzeuger mit mehreren Datensätzen vor einem frühen Lese-Ende  [x]
Komponente: scripts · Dateien: scripts/tests/pipe_guard_test.sh, scripts/tests/run.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @b33a7d01 2026-09-28T15:02:55+02:00
Review: am Ende (Kurz-Ledger)
Änderung: Neue Datei `scripts/tests/pipe_guard_test.sh` (SPDX-Kopf `GPL-3.0-or-later`, nach dem Vorbild von
`box_scripts_guard_test.sh`), eingetragen in `AH_SCRIPT_TESTS_DEFAULT` (run.sh:537–541). Sie scannt die
Nicht-Kommentarzeilen aller `scripts/tests/*_test.sh` nach `git … (log|rev-list|reflog|shortlog|check-attr|check-ignore)`
ohne `-1`/`-n 1`/`--max-count=1`, das in `grep -q`/`-m`/`-l`, `head` oder `sed …q` läuft, und meldet jede
Stelle mit Datei:Zeile. Nicht-Leer-Prüfung: Die Zahl der gescannten Dateien muss größer null sein. Selbsttest
mit Fixtures: die alte 4i-d-Zeile wird gemeldet, `git log -1 … | grep -q` und `x=$(git log …)` nicht. Optional
nimmt der Wächter Dateiargumente an. Gegenprobe für den Review: `bash scripts/tests/pipe_guard_test.sh <(git show 70e91718:scripts/tests/heavy_test.sh)` meldet genau die Stellen 4i-d und Fall 10.
Orakel: analyzer — statischer Musterscan, deterministisch; die Gegenprobe gegen den alten Stand ist dreimal identisch rot
HEAD: 70e91718
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Abhängt von: T1

### T3 — pipe_guard_test: die drei nits aus dem Gesamt-Review  [x]
Komponente: scripts · Dateien: scripts/tests/pipe_guard_test.sh
Evidenz: run.sh[quick]: 6 passed, 0 failed, 12 skipped @55da6b66 2026-09-28T15:31:32+02:00
Review: approve (opus, Re-Review der Gesamt-Review-nits)
Änderung: Aus dem Opus-Gesamt-Review (approve mit drei nits, Kevin 2026-09-28: „T3 nachziehen"). (1) Der
Leser-Teil des letzten Pipe-Segments endet dort, wo `mask()` den Zeilenend-Kommentar abgeschnitten hat
(`orig[cnt] = substr(s, k, n - k + 1)`); dazu eine clean-Fixture `git log | grep -c x  # grep -q y`, vorher ein
Fehlalarm. (2) Die Fixture „a pipe inside quotes" trifft die Maskierung wirklich (Zeilen, in denen `git` ein
eigenes Wort ist), eine weitere Fixture mit einem escapten Quote deckt den Backslash-Zweig; beide werden rot,
wenn Maskierung bzw. Backslash-Zweig fehlen. (3) Der Kopfkommentar nennt die Grenzen: eine Pipe am Zeilenende
ohne `\` und `|&` sieht der Scan nicht.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Abhängt von: T2
