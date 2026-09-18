---
paths:
  - "apps/**"
  - "scripts/tests/**"
---

# Testregeln

<!-- Stufe 0 · Quelle: bisherige CLAUDE.md „Testen auf VMs" · Roadmap Leitprinzip 3 · Stufe 1 -->

## Drei Ebenen

1. **Schnell (überall, PR-CI):** Lint + Unit je Komponente (Tabelle in `CLAUDE.md`). Sammelbefehl
   `bash scripts/tests/run.sh [lint|unit|quick|integration|e2e|all] [--strict] [--only <keys…>] [--step <name>]`,
   Default `quick`; dep-gated, Exit 75 = SKIP, am Ende
   `N passed, M failed, K skipped, J test-skips, R reruns` (Exit ≠ 0 bei Fail). Unter `--strict` ist ein
   übersprungener Pflicht-Schritt ein Fehler, ebenso ein strenger Lauf, in dem gar nichts lief; jeder Lauf
   schreibt `.ah-out/last-<layer>.json` mit Tree-Hash als Evidenz.
2. **Schwer (VM, manuell):** `integration`/`e2e`/`all` fahren den echten docker-compose-Stack, mTLS-Enrollment,
   Redis-SSE-Fan-out, Agent-Monitoring, apt/rpm-Repo-Bau und die Desktop-GUI-E2E (`apps/desktop/e2e/*.live.js` über
   `scripts/tests/desktop_e2e_*.sh`). Sie verweigern ohne `AH_ALLOW_REAL=1` und laufen nur auf einer VM (`/test`).
3. **Multi-Host (Capstone):** `bash scripts/tests/multibox.sh --capstone --strict` — echtes `.deb` über
   einen Netz-Hop, Cross-Host-mTLS, die echte Tauri-GUI gegen den entfernten Server, der 3-Host-Tunnel, der
   Mail-Alert und der `MTLS_ENFORCE`-Guard. Teilläufe (`--agents N [--desktop]` …) laufen **ohne** `--strict`:
   ein Lauf ohne `--enforce` meldet den MTLS_ENFORCE-Guard als SKIP, und unter `--strict` ist ein SKIP ein
   Fehler — `--strict` verlangt deshalb den vollen Flag-Satz, den `--capstone` setzt. `heavy.sh capstone` fährt
   genau diese Kombination.
   Seit T7a enrollt die Desktop-Etappe vor jedem Spec eine Geräte-Identität (ein Einmal-Token je Spec,
   kurz vorher gemintet), damit sie das cert-gated :443 überhaupt erreicht — bewiesen erst im Capstone-Lauf.

Vor jedem Release sind alle drei Ebenen real grün; eine rote oder übersprungene Ebene heißt: nicht taggen.

## Regeln

- **SKIP ≠ grün.** Exit 75 heißt „nicht verifiziert". Ein Live-Skript, das mangels Toolchain mit `exit 0` endet, ist
  ein Bug — seit Stufe 1 enden alle mit 75. Auch ein pytest-interner Skip zählt: unter `--strict` ist er ein Fehler,
  sobald seine Vorbedingung erfüllt ist. Ein erst roter, dann grüner Test ist `flaky`, kein PASS.
- **Nie grün melden ohne bestandene Suite.** Die Summary-Zeile ist die Evidenz und wird zitiert.
- **Lange Läufe überwacht.** `/test weekly|all|capstone` startet `heavy.sh` in tmux und wacht bis zum Report
  (Wächter im Hintergrund, kein Hand-Polling); Verdict-Zeile wörtlich, danach VM-Liste, Historie und Roadmap-Zeilen
  im privaten Repo committen. Start nur auf Kevins Zuruf, Abbruch nur auf Kevins Zuruf.
- **Verify-Zeilen in Ledgern** nur in Flag-Form: `bash scripts/dev/verify.sh <komponente> [--strict] [-- <args>]`
  oder `bash scripts/tests/run.sh <layer> --strict --only <keys…>`. Nie `FOO=bar cmd` — die Allow-Regel matcht nicht
  über die Zuweisung. Gilt für neue und aktive Ledger; abgeschlossene bleiben Historie und werden nur
  dort nachgezogen, wo eine Zeile sonst etwas Falsches behauptet. Schwere Läufe stehen als eigene Zeile `Heavy:`. Env-Bedarf löst das Skript auf, nicht der Aufrufer.
- **Server-pytest** braucht ein Postgres; `verify.sh` löst `AH_TEST_DB` aus `.devenv.sh` selbst auf, der Aufrufer
  setzt nichts.
- **Neue oder geänderte User-Journey ⇒ Live-E2E** auf der passenden Ebene (Web: Playwright; Desktop: `*.live.js`).
  Nicht-Testenswertes (triviale Getter, Framework-Wiring, Plattform-I/O, echte SSH/RDP/Ansible-Ausführung) bleibt
  ohne Test — mit einem Satz Begründung.
- **Plattform-Code** wird auf der Plattform verifiziert: Linux auf der VM; für Windows läuft seit Stufe 1 die
  **Go**-Suite nativ (CI-Job `agent-windows`: `go test -v ./...`, Build und `version`-Smoke der `.exe`), Rust per
  `rust-windows` (`cargo test --locked`). Alles andere unter Windows — Desktop-GUI, Dienst-Installation,
  Enrollment-Journey — bleibt bis Stufe 12 ausdrücklich „nicht verifiziert".
- **Desktop-GUI headless:** `LANG=C` lässt die Webview an `Intl.NumberFormat` scheitern (leeres `#app`). VMs brauchen
  `en_US.UTF-8`; der Bootstrap generiert es, die Desktop-Box setzt es.
- **Warm-Loop, nicht stop-after-run:** eine hydrierte VM ist teuer zu bauen (~40 min), billig zu halten. Einmal warm
  machen (`scripts/vm/warm.sh`), iterieren (`scripts/vm/iter.sh`), am Ende reapen (`scripts/vm/reap.sh`). Bei Fehler
  bleibt die VM stehen; Debug-Artefakte mit `AH_CAPTURE=1` nach `.ah-out/`, gitignored.
- **Nach jedem Lauf VM-Liste prüfen** (`python3 scripts/vm/vm.py list` — Exit 74, wenn auf dieser Lane etwas läuft,
  das niemand beansprucht); geleakte VMs sind ein Fehler. Provisionieren (`bake`, neue Templates) nur im Pool
  `adminhelper-ci`, und nur auf Zuruf.
