<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CI-Gates: Image-Tests im Server-Job, Skip-Gate, Keyring in ops-scripts, Playwright-Install

Stand des Codes: `origin/main@b25c65a6`. Alle `datei:zeile` beziehen sich auf diesen Stand. Ledger:
`tasks/ci-gates.md`. Roadmap R-0808 (T1), R-0475 (T2, T3), R-0500 (T4), R-0588 (T5).

**Jede Task ändert `.github/workflows/ci.yml`: den PR merged Kevin (CLAUDE.md §2), nicht die Session.**
`ci.yml` steht als Risikopfad in `scripts/dev/review-risk.txt` (Abschnitt „CI, release and install“), ist aber kein
Harness-Pfad; jede Task bekommt zusätzlich `security`. Keine Task berührt einen Harness-Pfad (`CLAUDE.md`,
`.claude/`, `scripts/dev/`, `scripts/tests/run.sh`, `scripts/tests/heavy.sh`, `scripts/vm/`).

## Problem / Motivation

1. **Der Playwright-Job hängt im Install-Schritt, bis der Job nach 30 min abbricht (R-0808).** Lauf 39767066088
   (PR #262), Job 119785048681: „Install Playwright browsers“ lief von 10:59:30 bis 11:29:36 UTC und wurde mit dem
   Job abgebrochen (`ci.yml:493` `timeout-minutes: 30`). Das Log zeigt, wo er hing: nicht beim Browser-Download,
   sondern bei den Systempaketen. `npx playwright install --with-deps` (`ci.yml:504-506`) installierte per apt
   „8 upgraded, 181 newly installed … Need to get 119 MB“; der Spiegel `azure.archive.ubuntu.com` lieferte im
   30-s-Takt „Ign:“ (26 Zeilen) und nach 30 min stand apt bei „Get:85 … libavfilter9“. Der Browser-Download begann
   nie. Der Re-Run brauchte 47 s; elf CI-Läufe vom 2026-10-22 brauchten 44–125 s für den Schritt.
   Ohne Browser-Argument installiert der Befehl die Abhängigkeiten **aller** Standard-Browser. playwright-core 1.60.0
   (`apps/web/package.json:22` `^1.60.0`) führt für `ubuntu24.04-x64` 12 Pakete „tools“, 21 für chromium, 25 für
   firefox und 52 für webkit (gstreamer, libavcodec, daher `libavfilter9`, `libva2`, `libcodec2` im Log). Die Suite
   braucht nur Chromium: `apps/web/playwright.config.ts` kennt die Projekte `chromium`, `chromium-build` und `live`,
   alle mit `devices['Desktop Chrome']`; `scripts/tests/run.sh:928` und `scripts/tests/web_live.sh:42`
   installieren schon nur `chromium`.
2. **Der server-Job überspringt Image-Tests still (R-0475).** Der Job (`ci.yml:30-94`) zieht unter 3.13 nur das
   Basis-Image von `apps/frps/Dockerfile` (`ci.yml:86-88`) und fährt `pytest -q -m "not schemathesis" --cov=app
   --cov-report=term` (`ci.yml:94`) ohne `-rs` und ohne Skip-Prüfung. Lauf 39768448078 auf `main`: 3.12
   „1909 passed, 21 skipped“, 3.13 „1926 passed, 4 skipped“. Lese-Probe (`pytest --co`): 21 = die 17 frps-Image-Tests
   plus die 4 Container-Tests von `apps/server/tests/test_images_exec_only.py` (`:231`, `:245`, `:261`, `:292`); die 4
   in 3.13 sind genau diese Container-Tests. Ihre Fixture `box` (`:204-228`) überspringt, wenn das Basis-Image
   `python:3.12-slim@sha256:…` (`_base()`, `:142-147`, die letzte Stufe von `Dockerfile`,
   `apps/ca-issuer/Dockerfile` und `apps/monitoring/Dockerfile`) lokal fehlt, und kein Job zieht es: **diese vier
   Tests liefen in CI nie.** Dasselbe trifft die Docker-Tests von `apps/server/tests/test_gateway_container.py`, die
   `feature/compose-hardening` gerade baut (Fixture `gateway_setup` überspringt ohne das nginx-Basis-Image aus
   `apps/gateway/Dockerfile:1`). Lokal laufen alle grün; in der PR-CI überspringen sie, und niemand merkt es.
3. **Der Kommentar im Job agent-windows zählt falsch (R-0500).** `ci.yml:410-415`: „Seven files are windows-tagged
   … and exactly one of them has a test“. Heute gibt es 9 `*_windows.go` und 8 `*_windows_test.go` unter
   `apps/agent/`. Eine Zahl im Kommentar veraltet mit jeder neuen Datei wieder.
4. **Die Keyring-Fälle von `lib_e2e_stack_test.sh` laufen in CI nur als innerer SKIP (R-0588).** Der ops-scripts-Job
   (`ci.yml:833-874`) installiert minisign (`:849-850`), pytest (`:856-857`) und oasdiff, aber kein gnome-keyring.
   `scripts/tests/lib_e2e_stack_test.sh:797-809` meldet ohne die Werkzeuge sechs `skip "keyring …"`, und das Ende
   (`:885-886`) gibt bei `FAIL=0` Exit 0. Lauf 39768448078, ops-scripts: „lib_e2e_stack_test: 82 passed, 0 failed,
   6 skipped“, sechs Zeilen „SKIP keyring …: not available: gnome-keyring-daemon“. `run.sh --strict` sieht einen
   grünen Test; geprüft werden die Fälle nur auf der Dev-Box und den Boxen (`scripts/vm/bootstrap_linux.sh:120`
   installiert `dbus-x11 gnome-keyring`).

## Ziel & Nicht-Ziele

Ziel:
- Der Playwright-Job installiert nur Chromium samt dessen Abhängigkeiten, und der Install-Schritt hat eine eigene Frist
  von 10 min: ein hängender Spiegel kostet 10 statt 30 min, und es hängen weniger Pakete an ihm (T1).
- Die 3.13-Leg des server-Jobs zieht die Basis-Images aller Image-Tests (frps, nginx des Gateways, python:3.12-slim),
  und ein übersprungener Test macht sie rot (T2, T3).
- Der Kommentar im Job agent-windows sagt, was der Job tut, ohne Zahl (T4).
- ops-scripts installiert gnome-keyring; `lib_e2e_stack_test.sh` endet ohne Keyring-Werkzeuge mit 75 statt mit einem
  inneren SKIP bei Exit 0 (T5).

Nicht-Ziele:
- **Kein Browser-Cache.** Die Playwright-Doku rät ab: „Caching browser binaries is not recommended, since the amount of
  time it takes to restore the cache is comparable to the time it takes to download the binaries. Especially under
  Linux, operating system dependencies need to be installed, which are not cacheable.“
  (https://playwright.dev/docs/ci). Der Hänger lag in apt, also genau im nicht cachebaren Teil.
- **Kein Retry-Loop um den Install-Schritt.** GitHub Actions kennt keinen Step-Retry (Workflow-Syntax: nur
  `continue-on-error` und `timeout-minutes`). Eine Schleife mit `timeout` würde `sudo apt-get` mitten im Lauf
  abbrechen, im ungünstigen Fall während dpkg auspackt; der nächste Versuch fände eine gesperrte oder halb
  konfigurierte Paketdatenbank. Der Weg nach einem Abbruch bleibt der Re-Run (CLAUDE.md §2: flaky heißt Rerun plus
  Roadmap-Zeile). Siehe Offene Fragen.
- **Kein Skip-Gate für die 3.12-Leg und den Lock-Job** (`python-lock-server`, `ci.yml:188-238`): beide ziehen keine
  Images und überspringen die Image-Tests mit Absicht; das Gate gilt dort, wo alle Voraussetzungen da sind.
- **Keine Ausnahmeliste im Skip-Gate.** Heute überspringt die 3.13-Leg nach T2 nichts mehr. Braucht später ein Test
  einen gewollten Skip in CI, ist das eine eigene Entscheidung, keine Vorsorge-Abstraktion jetzt.
- **Die 7-s-Grenze von Fall (b) bleibt** (`lib_e2e_stack_test.sh:739`, gemessen 5–6 s auf der Dev-Box). Der erste
  PR-CI-Lauf nach T5 liefert die erste Messung auf dem Runner; wird der Fall dort flaky, gilt §2.
- **Nachtrag (T6, R-0820):** Die Jobs CA-Issuer und `python-lock-ca-issuer` hatten keinen Postgres-Service; Lauf
  39768448078: „106 passed, 6 skipped“, die sechs sind die `pg_engine`-Tests in
  `apps/ca-issuer/tests/test_db_token_store.py` (Fixture `pg_engine`, `:104-108`). Kevin hat die Zeile angenommen und
  diesem Vorhaben zugeordnet; T6 gibt beiden Jobs einen Postgres-Service und `AH_TEST_DB`. Ein Skip-Gate bekommen sie
  nicht (wie die 3.12-Leg).
- `scripts/tests/run.sh` (Harness) bleibt unberührt: die Liste in `test_skip_is_required` braucht keine
  Image-Tests, weil das Gate in CI am JUnit-XML hängt.

## Betroffene Komponenten & Dateien

| Datei | Tasks |
|---|---|
| `.github/workflows/ci.yml` | T1 (`frontend-e2e`, `:490-517`), T2 (server-Job `:33`, `:86-88`), T3 (`:89-94` + neuer Schritt), T4 (`:410-415`), T5 (ops-scripts, neben `:849-850`) |
| `apps/server/tests/test_release_images.py` | T1, T2, T3 (Struktur-Tests über `_workflow`, `_step`, `_run_step`, `:101-133`) |
| `scripts/tests/lib_e2e_stack_test.sh` | T5 (`:797-809`, `:885-886`) |
| `docs/developer/cicd.html`, `docs/en/developer/cicd.html` | T1, T2, T3 (`:40` beide), T5 (DE `:82`, EN `:83`) |
| `DEVELOPMENT.md` | T5 (neben dem oasdiff-Absatz `:321-325`) |

Komponente für `verify.sh`: `server` (T1–T4, die Struktur-Tests liegen in `apps/server/tests/`), `scripts` (T5).

## Datenmodell / API / Migrationen

Keine. Kein Schema, keine Route, keine Migration, kein Vertrag zwischen Server, Web, Desktop und Agent.

## Externe Integrationen

- **GitHub Actions** (https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax):
  `jobs.<job_id>.steps[*].timeout-minutes` — „The maximum number of minutes to run the step before killing the
  process.“, positive ganze Zahl. Einen Step-Retry gibt es nicht.
- **Playwright** (https://playwright.dev/docs/browsers): „Running the command without arguments will install the
  default browsers.“; nur Chromium mit Abhängigkeiten: `npx playwright install --with-deps chromium`. CI-Seite
  (https://playwright.dev/docs/ci): kein Browser-Cache (Zitat oben). Die Paketlisten je Browser stehen in
  `node_modules/playwright-core/lib/coreBundle.js` (1.60.0): `installDeps` nimmt die Gruppen der gewählten Browser
  plus `tools` und ruft `apt-get install -y --no-install-recommends` ohne eigene Timeout- oder Retry-Optionen.
- **pytest JUnit-XML:** ein übersprungener Test ist `<testcase classname=… name=…><skipped message=…/>`; Vorbild für
  die Auswertung ist `scripts/tests/stack_pytest.sh` (prüft `skipped="0"`).

## Trade-offs & Alternativen

- **R-0808, Playwright-Install.** Empfehlung: nur Chromium plus Schritt-Frist 10 min (T1). Das trifft die Ursache
  (der Job verlangt 110 statt 33 direkte Pakete, vor dem Entdoppeln, darunter die ganze gstreamer/ffmpeg-Kette, an der der Lauf hing)
  und begrenzt den Schaden, wenn der Spiegel trotzdem hängt (die `tools`-Schriften standen ebenfalls unter den
  „Ign:“-Zeilen). 10 min ist rund das Fünffache des längsten gemessenen Laufs (125 s).
  Alternativen: (a) Browser-Cache per `actions/cache` — verworfen, deckt apt nicht ab (Doku-Zitat oben). (b) Retry —
  verworfen (Nicht-Ziele). (c) Job im Container `mcr.microsoft.com/playwright:v<version>-noble` (Abhängigkeiten
  vorinstalliert, kein apt im Job) — löst den Spiegel-Teil ganz, kostet aber einen zweiten Pin, der mit
  `@playwright/test` im Lock gleichlaufen muss, und einen Image-Pull aus einer weiteren Registry; als Nachfolger
  sinnvoll, falls der Hänger trotz T1 wiederkommt.
- **R-0475, Pull.** Empfehlung: ein Schritt, der die drei Basis-Images zieht, abgeleitet aus den `FROM`-Zeilen der
  Dockerfiles, damit ein Digest-Bump keinen zweiten Ort braucht. Die python-Basis aus `apps/ca-issuer/Dockerfile`
  (eine `FROM`-Zeile); das Wurzel-`Dockerfile` hat zwei (node und python). Die 3.13-Leg braucht heute 12:21–12:34
  von 15 min; die Pulls und die neuen Container-Tests kosten Zeit, daher `timeout-minutes: 20` für den Job.
- **R-0475, Gate.** Empfehlung: JUnit-XML der 3.13-Leg auswerten (ein Schritt nach „Run pytest“, Python-stdlib), weil
  das die Test-ID und den Grund jedes Skips nennt. Alternative `pytest -rs` plus grep auf „SKIPPED“ hängt an der
  Textausgabe von pytest; Alternative `run.sh --strict` im CI wäre eine Harness-Änderung (Liste in
  `test_skip_is_required`) und würde nur Pflicht-Tests prüfen.
- **R-0588.** Empfehlung wie die Zeile: gnome-keyring installieren und 75 statt innerem SKIP. Der Exit 75 hält die
  Regel aus `docs/developer/cicd.html:82` („Exit 75 heisst SKIP“) ein, die minisign und oasdiff schon nutzen.

## Risiken & Rollback

- **Ein Image-Test ist auf dem Runner rot.** Die vier Container-Tests von `test_images_exec_only.py` liefen in CI nie.
  Nach T2 dispatcht die Session `ci.yml` auf `feature/ci-gates` (`gh workflow run ci.yml --ref feature/ci-gates`) und
  erwartet in der 3.13-Leg „0 skipped“ und grün. Ist ein Test rot, behebt eine eigene Task (Plan-Nachtrag) die
  Ursache vor T3; das Gate wird nicht geschwächt und kein Test abgeschaltet.
- **Kopplung mit `feature/compose-hardening`.** Keine gemeinsame Datei, aber nach T2 laufen dessen
  Gateway-Docker-Tests (`test_gateway_container.py`) in der PR-CI der 3.13-Leg, nach T3 ist ihr Skip rot. Wird
  ci-gates zuerst gemergt, beweist compose-hardening seine Tests in der eigenen PR-CI; umgekehrt laufen sie erst mit
  ci-gates und müssen dort grün sein.
- **Die Job-Frist der 3.13-Leg.** 20 min ist geschätzt; die PR-CI nach T2 liefert die Messung.
- **Fall (b) von `lib_e2e_stack_test.sh` auf dem Runner** (7-s-Grenze): erste Messung in der PR-CI nach T5.
- **Ubuntu 26.** `ubuntu-latest` wechselt auf Ubuntu 26; playwright-core 1.60.0 hat Paketlisten nur für Ubuntu 20.04,
  22.04 und 24.04. Was `--with-deps` auf 26.04 tut, ist nicht verifiziert; das betrifft T1 nicht mehr als heute.
- **Rollback:** jede Task ist ein Commit; Revert stellt den alten Schritt her.

## Doku-Impact

`docs/developer/cicd.html` + `docs/en/developer/cicd.html` (Tabellenzeile `ci.yml`, `:40`): Playwright nur mit
Chromium und Frist (T1), die drei Basis-Images (T2), das Skip-Gate (T3); neben „Exit 75 heisst SKIP“ der Keyring-Fall
(T5). `DEVELOPMENT.md` (nur Deutsch): ein Absatz neben oasdiff, dass der Pflicht-Schritt `scripts` gnome-keyring
braucht (T5). Kein CHANGELOG: CI-intern, für Nutzer nicht sichtbar.

## Offene Fragen

1. **R-0808, Restrisiko:** Hängt der apt-Spiegel trotz T1, scheitert der Job nach 10 min und braucht einen Re-Run.
   Empfehlung: hinnehmen und den Container-Weg (Alternative c) erst als neue Zeile, wenn es wieder passiert.
   Keine Task hängt an der Frage.
2. **Merge-Reihenfolge mit compose-hardening:** Empfehlung ci-gates zuerst (siehe Risiken). Keine Task hängt daran.
