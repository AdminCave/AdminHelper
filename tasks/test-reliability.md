<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Test-Zuverlässigkeit: install_test-Stub liest stdin, Desktop-E2E hält node_modules frisch (R-0131, R-0142) — Task-Ledger
Status: freigegeben · Branch: harness/test-reliability · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Kevin, 2026-10-02 (Design-Gate, „Test-Zuverlässigkeit“ freigegeben), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: Roadmap R-0131, R-0142
Heavy: linux-full — `run.sh e2e --strict --step desktop_e2e_crud` auf frischer Template-Box ohne händisches `npm ci` (erwartet: `npm ci` im Log, 6 Specs grün). Vorher die Template-Tags gegen die Lockfile-Änderungen prüfen (junit-Reporter 7bc9f6d0 vom 2026-09-27, letzte Lockfile-Änderung heute 0ecdc3ca vom 2026-09-30): ist das Template jünger, beweist der Lauf nur „keine Regression“, den Fix beweist dann der hermetische Test aus T2.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, keine Doku, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-02 von der Aufsicht (adminhelper-ac) auf Kevins Wort (Paket „Test-Zuverlässigkeit“ für Worker A).
Entscheidungen am Plan: mtime-Regel wie `run.sh` (kein Hash-Marker), alle acht Desktop-Suiten, Fix für R-0142 im
Test-Stub (install.sh bleibt), R-0142 gilt als BUG (latent seit 2026-07-06), Review mit Sonnet in einer Runde
(keine Datei steht in `scripts/dev/harness-paths.txt`). `run.sh` und `AH_SCRIPT_TESTS_DEFAULT` bleiben unberührt:
die neuen Prüfungen gehen in schon eingetragene Tests (`run.sh:557–562`).

### T1 — install_test: der Docker-Stub liest bei create-admin stdin  [ ]
Komponente: scripts · Dateien: scripts/tests/install_test.sh
Roadmap: R-0142
Befund: `scripts/install.sh:287` reicht das Admin-Passwort per `printf '%s\n' "$ADMIN_PASSWORD" | docker compose exec
-T server … create-admin --password-stdin` weiter, unter `set -euo pipefail` (`:28`). Der Docker-Stub in
`scripts/tests/install_test.sh:41–48` fällt für create-admin in `*) exit 0` (`:47`) und liest stdin nie. Endet der
Stub, bevor die `printf`-Subshell schreibt, stirbt `printf` an SIGPIPE, pipefail und `set -e` machen daraus Exit 141
von install.sh, und Fall 1 (`:97`) meldet `bootstrap exit 141`. Die übrigen Pipes nach `:259` scheiden aus: die
`until`-Bedingung ist mit dem Stub sofort grün (`logs | grep -q` läuft nie), hinter `mint-enroll-token` (`:289`)
liest `tr` bis zum Ende. Das echte `docker compose exec -T` reicht stdin weiter und startet viel langsamer als
`printf`; install.sh bleibt unverändert.
Änderung: Im Stub vor `*) exit 0` einen Zweig `*create-admin*) cat > "$WORK/admin.stdin"; exit 0 ;;` (nur dieser
Zweig liest stdin: im Default würde `cat` bei geerbtem stdin hängen, etwa bei `logs` ohne `</dev/null`). Nach Fall 1
eine Prüfung, dass `$WORK/admin.stdin` genau `sikrit123` enthält („admin password reached create-admin on stdin“).
Ohne den Stub-Zweig ist sie deterministisch rot (Datei fehlt).
Beweis: origin/main@9fa298ed, die Pipe aus `install.sh:287` isoliert in einem Skript unter `set -euo pipefail`, der
Stub aus `install_test.sh:41–48` auf PATH, je 1000 Läufe ohne künstliche Last: Exit 141 in 16 von 1000 (zweiter
Durchgang 2 von 1000); mit einem Stub, der bei `*create-admin*` erst `cat >/dev/null` macht, 0 von 1000 (Probe der
Aufsicht, 2026-10-02). Erstbefund: Gate fuzz-gate 2026-10-02, `verify.sh scripts --strict` @ec08a26b: install_test
6 passed, 1 failed (`bootstrap exit 141`), danach 10× grün. Latent seit 2026-07-06 (Pipe 5fc2cee7, Stub ba8bd713).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Dedup-Key: reg:scripts:install_test.sh:bootstrap-sigpipe · HEAD: 9fa298ed
Semantik: `docs/admin/troubleshooting.html:60`: „Sicherer (Passwort nicht im Prozess-<code>argv</code>):
<code>--password-stdin</code> statt <code>--password</code> und das Passwort auf stdin.“ — das Passwort über stdin
ist gewollt, der Stub muss es abnehmen. Dazu `.claude/rules/testing.md:37`: „Ein erst roter, dann grüner Test ist
`flaky`, kein PASS.“

### T2 — lib_e2e_stack: e2e_npm_ready installiert, wenn node_modules fehlt oder älter ist als das Lockfile  [ ]
Komponente: scripts · Dateien: scripts/tests/lib_e2e_stack.sh, scripts/tests/lib_e2e_stack_test.sh
Roadmap: R-0131
Befund: `desktop_e2e_crud.sh:33–34` und `desktop_e2e_misc.sh:61–62` prüfen nur `[ -d node_modules ] || npm ci`; auf
einer Box mit node_modules aus dem Template fehlt danach jedes später ins Lockfile gekommene Paket. Frisch hält
node_modules heute nur der Schritt `desktop-e2e-smoke` über `npm_ci_if_stale` (`run.sh:473–478`), und ein Lauf mit
`--step` überspringt genau diesen Schritt. Die mtime-Regel greift auf der Box, weil `vm.py:1116` mit `rsync -az`
synct (mtime des Lockfiles vom Dev-Rechner bleibt erhalten).
Änderung: In `lib_e2e_stack.sh` neben `e2e_require` (`:50`) eine Funktion `e2e_npm_ready <dir>…`: je Verzeichnis
`npm ci --no-audit --no-fund`, wenn `node_modules` fehlt oder `package-lock.json` neuer ist (dieselbe Regel wie
`npm_ci_if_stale`, ein Satz Kommentar mit Verweis auf 5.26), in einer Subshell mit `cd`; ein Fehlschlag von `npm ci`
gibt einen Exit ≠ 0 zurück. Die Kopfzeilen-Übersicht der Lib (`:4–10`) nennt die Funktion. In
`lib_e2e_stack_test.sh` (heute 129 Zeilen) drei Fälle mit einem npm-Stub auf PATH, der seine Aufrufe protokolliert,
und Fixture-Verzeichnissen mit gesetzten mtimes (`touch -d`): node_modules fehlt → `npm ci`; Lockfile neuer → `npm ci`;
node_modules neuer → kein Aufruf. Dazu: scheitert `npm ci`, ist der Exit ≠ 0.
Beweis: Der Fall „Lockfile neuer“ ist mit dem heutigen Ausdruck `[ -d node_modules ] || npm ci` deterministisch rot
(kein Aufruf), mit `e2e_npm_ready` grün. Erstbefund: FRP-Heavy-Lauf 1 der Aufsicht, 2026-09-30, @5dd4e196, auf
einer Template-Box (Bake 20260918): desktop_e2e_crud 3 passed, 3 failed, Spec Files 0 passed, 6 failed, wdio
„Couldn't find plugin junit reporter“ (der Reporter kam mit 7bc9f6d0 ins Lockfile). Lauf 2, ein `run.sh e2e` mit
dem einen Schritt desktop_e2e_crud, nach händischem `npm ci` 6 passed (`.ah-out/frp-desktop-crud.log:171`,
`:189`, `:3759`; das Log von Lauf 1 ist überschrieben).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Dedup-Key: bug:scripts:desktop_e2e_crud.sh:stale-node-modules · HEAD: 9fa298ed
Semantik: keine Stelle in docs/ — gesucht nach `node_modules` und `npm ci` in docs/ (nur Setup-Anleitungen,
`docs/developer/index.html:92–95`). Die Absicht steht in `scripts/tests/run.sh:473–475`: „Install only when the
lockfile is newer or node_modules is missing — deterministic when it matters, fast otherwise (5.26).“

### T3 — alle acht Desktop-Suiten rufen e2e_npm_ready für ui und e2e  [ ]
Komponente: scripts · Dateien: scripts/tests/desktop_e2e_{connect,connect_tunnel,crud,live,misc,monitoring,sse_push,tunnel}.sh, scripts/tests/lib_e2e_stack_test.sh
Roadmap: R-0131
Abhängt von: T2
Änderung: Jede der acht Suiten ruft direkt nach ihrer tauri-cli-Prüfung (`|| { echo "SKIP: tauri-cli …"; exit 75; }`,
heute connect `:54`, connect_tunnel `:57`, crud `:27`, live `:34`, misc `:56`, monitoring `:28`, sse_push `:29`,
tunnel `:36`) `e2e_npm_ready "$E2E_REPO_ROOT/apps/desktop/ui" "$E2E_DIR" || exit 1`. In crud (`:33–34`) und misc
(`:61–62`) ersetzt der Aufruf die beiden `[ -d node_modules ] || npm ci`-Zeilen; ihr Kommentar darüber bleibt
sinngemäß. Nach der tauri-cli-Prüfung, damit `desktop_e2e_skip_test.sh` (endet dort mit 75) weiter ohne npm läuft.
In `lib_e2e_stack_test.sh` eine statische Prüfung: jede `scripts/tests/desktop_e2e_*.sh` außer
`desktop_e2e_skip_test.sh` enthält einen Aufruf von `e2e_npm_ready`, keine enthält mehr `[ -d node_modules ]`.
Beweis: Die statische Prüfung ist auf origin/main@9fa298ed rot (acht Suiten ohne Aufruf, zwei mit dem alten
Ausdruck), nach T3 grün.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Dedup-Key: bug:scripts:desktop_e2e_crud.sh:stale-node-modules · HEAD: 9fa298ed
Semantik: wie T2 (`scripts/tests/run.sh:473–475`); keine Stelle in docs/.
