---
paths:
  - "apps/**"
  - "scripts/tests/**"
---

# Testregeln

Pfadgebunden: für Dateien in einem Worktree lädt diese Datei nicht von selbst; `/feature-build`, `/feature-plan` und
`reviewer` lesen sie ausdrücklich. Die Grundregeln (Summary-Zeile als Evidenz, Ausgaben, lange Läufe, Heavy) stehen
in CLAUDE.md §5; hier die Einzelheiten.

## Drei Ebenen

1. **Schnell (überall, PR-CI):** Lint + Unit je Komponente (Tabelle in `CLAUDE.md`). Sammelbefehl
   `bash scripts/tests/run.sh [lint|unit|quick|integration|e2e|all] [--strict] [--only <keys…>] [--step <name>] [--part gui|rest]`,
   Default `quick`; dep-gated, Exit 75 = SKIP, am Ende
   `N passed, M failed, K skipped, J test-skips, R reruns` (Exit ≠ 0 bei Fail). Unter `--strict` ist ein
   übersprungener Pflicht-Schritt ein Fehler, ebenso ein strenger Lauf, in dem gar nichts lief; jeder Lauf
   schreibt `.ah-out/last-<layer>.json` mit Tree-Hash als Evidenz. Eine Task fährt die Ebene über
   `verify.sh` (volles Log unter `.ah-out/logs/`, Digest auf stdout, `--full` streamt alles).
2. **Schwer (VM, manuell):** `integration`/`e2e`/`all` fahren den echten docker-compose-Stack, mTLS-Enrollment,
   Redis-SSE-Fan-out, Agent-Monitoring, apt/rpm-Repo-Bau und die Desktop-GUI-E2E (`apps/desktop/e2e/*.live.js` über
   `scripts/tests/desktop_e2e_*.sh`). Sie verweigern ohne `AH_ALLOW_REAL=1` und laufen nur auf einer VM (`/test`).
3. **Multi-Host (Capstone):** `bash scripts/tests/multibox.sh --capstone --strict` — echtes `.deb` über
   einen Netz-Hop, Cross-Host-mTLS, die echte Tauri-GUI gegen den entfernten Server, der 3-Host-Tunnel, das
   Docker-Monitoring mit echtem Docker auf der Agent-Box, der Mail-Alert und der `MTLS_ENFORCE`-Guard.
   Teilläufe (`--agents N [--desktop]` …) laufen **ohne** `--strict`: ein Lauf ohne `--enforce` meldet den
   MTLS_ENFORCE-Guard als SKIP, und unter `--strict` ist ein SKIP ein Fehler — `--strict` verlangt den vollen
   Flag-Satz, den `--capstone` setzt. `heavy.sh capstone` fährt genau diese Kombination. Die Desktop-Etappe enrollt
   vor jedem Spec eine Geräte-Identität (ein Einmal-Token je Spec), damit sie das cert-gated :443 erreicht.

Vor jedem Release sind alle drei Ebenen real grün; eine rote oder übersprungene Ebene heißt: nicht taggen.

## Regeln

- **SKIP ≠ grün.** Exit 75 heißt „nicht verifiziert". Ein Live-Skript, das mangels Toolchain mit `exit 0` endet, ist
  ein Bug; alle enden mit 75. Auch ein pytest-interner Skip zählt: unter `--strict` ist er ein Fehler, sobald seine
  Vorbedingung erfüllt ist.
- **Verify-Zeilen in Ledgern** nur in Flag-Form: `bash scripts/dev/verify.sh <komponente> [--strict] [-- <args>]`
  oder `bash scripts/tests/run.sh <layer> --strict --only <keys…>`. Nie `FOO=bar cmd` — die Allow-Regel matcht nicht
  über die Zuweisung. Gilt für neue und aktive Ledger; abgeschlossene bleiben Historie und werden nur dort
  nachgezogen, wo eine Zeile sonst etwas Falsches behauptet. Schwere Läufe stehen als eigene Zeile `Heavy:`.
  Env-Bedarf löst das Skript auf, nicht der Aufrufer; Server-pytest bekommt `AH_TEST_DB` über `verify.sh`.
- **Lange Läufe:** `/test weekly|all|capstone` startet `heavy.sh` in tmux und wacht bis zum Report (Ablauf im
  `/test`-Skill); Start auf Kevins Zuruf, `all` auch als fälliger Sammellauf (`/feature-build` §5); Abbruch nur auf
  Kevins Zuruf.
- **Neue oder geänderte User-Journey ⇒ Live-E2E** auf der passenden Ebene (Web: Playwright; Desktop: `*.live.js`).
- **Plattform-Code** wird auf der Plattform verifiziert: Linux auf der VM; für Windows läuft die **Go**-Suite nativ
  (CI-Job `agent-windows`: `go test -v ./...`, Build und `version`-Smoke der `.exe`), Rust per `rust-windows`
  (`cargo test --locked`). Alles andere unter Windows — Desktop-GUI, Dienst-Installation, Enrollment-Journey —
  bleibt ausdrücklich „nicht verifiziert".
- **Desktop-GUI headless:** `LANG=C` lässt die Webview an `Intl.NumberFormat` scheitern (leeres `#app`). VMs brauchen
  `en_US.UTF-8`; der Bootstrap generiert es, die Desktop-Box setzt es.
- **Warm-Loop, nicht stop-after-run:** eine hydrierte VM ist teuer zu bauen (~40 min), billig zu halten. Einmal warm
  machen (`scripts/vm/warm.sh`), iterieren (`scripts/vm/iter.sh`), am Ende reapen (`scripts/vm/reap.sh`). Bei Fehler
  bleibt die VM stehen; Debug-Artefakte mit `AH_CAPTURE=1` nach `.ah-out/`, gitignored.
- **Nach jedem Lauf VM-Liste prüfen** (`python3 scripts/vm/vm.py list` — Exit 74, wenn auf dieser Lane etwas läuft,
  das niemand beansprucht); geleakte VMs sind ein Fehler. Provisionieren (`bake`, neue Templates) nur im Pool
  `adminhelper-ci`, und nur auf Zuruf.
