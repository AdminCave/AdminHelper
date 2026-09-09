---
paths:
  - "apps/**"
  - "scripts/tests/**"
---

# Testregeln

<!-- Stufe 0 · Quelle: bisherige CLAUDE.md „Testing auf crabbox" · Roadmap Leitprinzip 3 · Stufe 1 -->

## Drei Ebenen

1. **Schnell (überall, PR-CI):** Lint + Unit je Komponente (Tabelle in `CLAUDE.md`). Sammelbefehl
   `bash scripts/tests/run.sh [lint|unit|quick|integration|e2e|all] [--strict] [--only <keys…>] [--step <name>]`,
   Default `quick`; dep-gated, Exit 75 = SKIP, am Ende
   `N passed, M failed, K skipped, J test-skips, R reruns` (Exit ≠ 0 bei Fail). Unter `--strict` ist ein
   übersprungener Pflicht-Schritt ein Fehler, ebenso ein strenger Lauf, in dem gar nichts lief; jeder Lauf
   schreibt `.crabbox-out/last-<layer>.json` mit Tree-Hash als Evidenz.
2. **Schwer (VM, manuell):** `integration`/`e2e`/`all` fahren den echten docker-compose-Stack, mTLS-Enrollment,
   Redis-SSE-Fan-out, Agent-Monitoring, apt/rpm-Repo-Bau und die Desktop-GUI-E2E (`apps/desktop/e2e/*.live.js` über
   `scripts/tests/desktop_e2e_*.sh`). Sie verweigern ohne `AH_ALLOW_REAL=1` und laufen nur auf einer VM (`/test`).
3. **Multi-Host (Capstone):** `bash scripts/tests/crabbox_multibox.sh --agents N [--desktop] [--strict]` — echtes `.deb` über
   einen Netz-Hop, Cross-Host-mTLS, optional die echte Tauri-GUI gegen den entfernten Server.

Vor jedem Release sind alle drei Ebenen real grün; eine rote oder übersprungene Ebene heißt: nicht taggen.

## Regeln

- **SKIP ≠ grün.** Exit 75 heißt „nicht verifiziert". Ein Live-Skript, das mangels Toolchain mit `exit 0` endet, ist
  ein Bug — seit Stufe 1 enden alle mit 75. Auch ein pytest-interner Skip zählt: unter `--strict` ist er ein Fehler,
  sobald seine Vorbedingung erfüllt ist. Ein erst roter, dann grüner Test ist `flaky`, kein PASS.
- **Nie grün melden ohne bestandene Suite.** Die Summary-Zeile ist die Evidenz und wird zitiert.
- **Verify-Zeilen in Ledgern** nur in Flag-Form: `bash scripts/dev/verify.sh <komponente> [--strict] [-- <args>]`
  oder `bash scripts/tests/run.sh <layer> --strict --only <keys…>`. Nie `FOO=bar cmd` — die Allow-Regel matcht nicht
  über die Zuweisung. Schwere Läufe stehen als eigene Zeile `Heavy:`. Env-Bedarf löst das Skript auf, nicht der Aufrufer.
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
  machen, iterieren, am Ende reapen. Bei Fehler bleibt die VM stehen; Debug-Artefakte mit `AH_CAPTURE=1` nach
  `.crabbox-out/` (ab Stufe 2 `.ah-out/`), gitignored.
- **Nach jedem Lauf VM-Liste prüfen** (`crabbox list`, ab Stufe 2 `python3 scripts/vm/vm.py list`); geleakte VMs sind
  ein Fehler. Provisionieren (`bake`, `image`, neue Templates) nur im Pool `ah-ci`.
