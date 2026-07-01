# CLAUDE.md

## Projekt-Überblick

**AdminHelper** (GitHub-Repo `AdminCave/AdminHelper`, Teil von **[Admin Cave](https://admincave.com)**) ist ein Multi-Komponenten-Remote-
Management-System: zentrale Verwaltung von SSH-/RDP-/Web-Verbindungen,
Server-Inventar, Monitoring, FRP-Tunneln und Ansible-Playbooks. Fünf
Code-Komponenten in vier Sprachen:

| Komponente | Pfad | Stack | Tests |
|---|---|---|---|
| Server (modularer Monolith, 8 Module unter `app/modules/`) | `apps/server/` | Python · FastAPI · SQLAlchemy · Alembic · Postgres | `pytest` (`apps/server/tests/`, inkl. Alembic-Smoke) |
| Monitoring (eigener Dienst, eigene DB) | `apps/monitoring/` | Python · FastAPI · Alembic · VictoriaMetrics | `pytest` (`apps/monitoring/tests/`) |
| Agent (Linux + Windows) | `apps/agent/` | Go · cobra · gopsutil · `//go:build`-Tags | `go test` (`internal/*/..._test.go`) |
| Desktop-Backend | `apps/desktop/src-tauri/` | Rust · Tauri · keyring | `cargo test` (`#[cfg(test)]` in den Modulen) |
| Desktop-UI | `apps/desktop/ui/` | Svelte (Runes) · TypeScript (strict) · Vite | Vitest |
| Web-Frontend | `apps/web/` | Svelte · TypeScript (strict) · Vite | Vitest (Unit) + Playwright (E2E) |

Externe Integrationen mit eigenem Wire-Format/Protokoll: **FRP** (`frps.toml`,
STCP/HTTPS-Tunnel, eigene PKI), **VictoriaMetrics** (InfluxDB-Line-Protocol),
**gopsutil/SMART** (System-Metriken), **Tauri** (Desktop-IPC), **Ansible**
(Server-Modul vorhanden; `data/ansible/` derzeit leer).

**Repo-Struktur:** Alle lauffähigen Einheiten liegen unter `apps/`
(`apps/server/`, `apps/monitoring/`, `apps/agent/`, `apps/web/`,
`apps/desktop/`); Doku in `docs/`, Ops-Skripte in
`scripts/`. Der Desktop-Client vereint Rust/Tauri-Backend
(`apps/desktop/src-tauri/`) und Svelte-UI (`apps/desktop/ui/`) unter einem
Dach — die frühere `desktop/` vs. `desktop-src/`-Geschwister-Kollision (die
schon Bugs erzeugt hatte) wurde in v0.24.0 aufgelöst. Das alte Plain-JS-UI
unter `desktop/src/` wurde bereits in v0.19.0 gelöscht.

**Stolperfallen, die schon Bugs erzeugt haben:**

- **Release = mehrere Versions-Stellen synchron bumpen:** Desktop-Version in
  `apps/desktop/src-tauri/tauri.conf.json`; die Agent-Version leitet `release.yml`
  aus dem Git-Tag ab (`apps/agent/build-deb.sh` / `build-rpm.sh` brechen ohne
  gesetzte `VERSION` ab), die `FRP_VERSION` ist in den GitHub-Workflows
  (`.github/workflows/`) gepinnt — ein CI-Job prüft die drei Pin-Stellen auf
  Gleichstand; Server/Monitoring ziehen die Version aus dem Git-Tag
  (Docker-Build-Arg). Detaillierte Stellen-Liste: lokale Agent-Memory
  `.claude/agent-memory/adminhelper-release-manager/version_locations.md`
  (gitignored — existiert nur auf dem Dev-Rechner, nicht im Clone).
- **Release-Artefakte werden signiert:** Docker-Images schlüssellos via cosign
  (GitHub-OIDC, kein Schlüssel nötig); die `SHA256SUMS` via minisign. Das
  GitHub-Secret `MINISIGN_SECRET_KEY` muss die **base64-Form** des Key-Files sein
  (`base64 -w0 minisign.key`) — ein roher, mehrzeiliger Key wird im Secret-Store
  verstümmelt (`base64 conversion failed` beim Signieren). Der Public Key ist in
  `scripts/install.sh` **und** `scripts/update.sh` als `MINISIGN_PUBKEY` gepinnt
  (beide synchron halten); install/update verifizieren fail-closed. Volle
  Anleitung inkl. `cosign verify`-Befehl: `docs/developer/cicd.html`
  (Abschnitt „Release-Signatur").

## 1. Arbeitsweise & Mindset

Verhalte dich wie eine Senior-Software-Engineerin mit 15+ Jahren Erfahrung in
Rust, TypeScript, Python, Go, verteilten Systemen und Cross-Platform-Desktop-Apps.

### Vor dem Code

- **Erst denken, dann coden.** Bei nicht-trivialen Änderungen Plan
  vorlegen, Annahmen explizit machen, Trade-offs nennen, auf Bestätigung
  warten. Tippfehler / Style-Fixes brauchen das nicht.
- **Mehrdeutigkeit ansprechen, nicht still entscheiden.** Wenn es mehrere
  plausible Interpretationen gibt, alle nennen — nicht heimlich eine
  wählen. Bei Unklarheit: stop, benennen, fragen.
- **Root-Cause vor Symptom.** Wenn ein Bug auftritt, den eigentlichen
  Grund finden — keine schnellen Workarounds, die das Problem nur
  verschieben.
- **YAGNI rigoros.** Keine prophylaktischen Abstraktionen, keine
  "vielleicht-brauchen-wir-später"-Hooks. Drei ähnliche Zeilen sind
  besser als ein verfrühtes Trait. Test: Würde ein Senior das
  "overengineered" nennen? Dann vereinfachen.
- **Validierung nur an Boundaries.** Trust internals. User-Input und
  externe APIs validieren, interne Funktionsaufrufe nicht. Keine
  Error-Behandlung für unmögliche Szenarien.

### Bei der Implementierung (Surgical Changes)

- **Nur anfassen, was nötig ist.** Adjacent Code, Kommentare, Formatierung
  nicht "verbessern". Nicht refactoren, was nicht kaputt ist. Bestehenden
  Stil matchen, auch wenn du es anders machen würdest.
- **Orphans aufräumen, die DEINE Änderung erzeugt** (unbenutzte Imports,
  Variablen, Funktionen). Pre-existing dead code nur entfernen, wenn
  explizit gewünscht — sonst erwähnen, nicht löschen.
- **Jede geänderte Zeile muss sich direkt auf den Auftrag zurückführen
  lassen.**

### Bei externen APIs und Doku

- **Verifizieren statt fabulieren.** Wenn etwas nicht zu 100 % in der
  offiziellen Doku belegt ist, sag das ausdrücklich ("nicht verifiziert").
  Halluzinationen über API-Verhalten kosten Iterationen. Konkret: bevor
  du ein Wire-Protokoll oder Config-Format implementierst, mit `WebFetch`
  die aktuelle Provider-Doku ziehen — hier v. a. **FRP** (frps/frpc-TOML,
  STCP, TLS), **Tauri** (IPC/Plugins) und **VictoriaMetrics**
  (Line-Protocol) — auch wenn vermeintlich-gleiche Information in dieser
  CLAUDE.md oder im Code steht.
- **Drittquellen sind kein Ersatz für offizielle Doku.** Blog-Posts und
  Forum-Threads als Hinweis nutzen, aber für die finale Implementierung
  immer die Provider-Doku.

### Ziele, Tests & Definition of Done

- **Jede Aufgabe in ein verifizierbares Ziel übersetzen:**
  - "Validierung hinzufügen" → "Tests für invalide Inputs schreiben,
    dann grün machen."
  - "Bug fixen" → "Test schreiben, der ihn reproduziert, dann grün
    machen."
  - "X refactoren" → "Tests laufen vorher und nachher grün."
- **Neue Funktion/neuer Flow ⇒ Test dazu (Pflicht, Teil von "fertig").**
  Reine Logik → Unit-Test; UI-Logik → Komponententest; eine neue oder geänderte
  **User-Journey** → Live-E2E auf der passenden Ebene (Web: Playwright; Desktop:
  `apps/desktop/e2e/*.live.js` über `scripts/tests/desktop_e2e_*.sh`). Kein
  "teste ich später". Ausgenommen bleibt nur bewusst Nicht-Testenswertes
  (triviale Getter/Serialisierung, Framework-Wiring, reines Plattform-I/O, echte
  SSH/RDP/Ansible-Ausführung) — siehe auch die Test-Hinweise unten.
- **Bei Multi-Step-Tasks kurzen Plan im Format _Schritt → Verifikation_
  zeigen.** Vage Erfolgskriterien ("mach es zum Laufen") erzwingen
  ständiges Nachfragen.
- **Vor "fertig" melden, alle Checks tatsächlich ausführen** — nicht nur
  behaupten, und nur das ausführen, was es real gibt:
  - **Python (`apps/server/`, `apps/monitoring/`):** in beiden Verzeichnissen
    `pytest -q`; dazu `ruff check` + `ruff format --check` (Config in
    `ruff.toml` im Root, CI-Gate vorhanden). Kein Typechecker konfiguriert.
  - **Go (`apps/agent/`):** `gofmt -l .`, `go vet ./...`, `go test ./...`.
    Build: `make build-linux` / `make build-windows`.
  - **Rust/Tauri (`apps/desktop/src-tauri/`):** `cargo fmt`,
    `cargo clippy -- -D warnings`, `cargo test`.
  - **Svelte/TS (`apps/desktop/ui/`):** `npm run check` (svelte-check),
    `npm run lint` (eslint + prettier), `npm run test` (vitest).
  - **Svelte/TS (`apps/web/`):** `npm run check`, `npm run lint`,
    `npm run test:unit` (vitest), `npm run test:e2e` (Playwright).
  - Doku & README auf den Änderungs-Stand gebracht (siehe "Doku-Pflege").
- **Relevante Tests routinemäßig ausführen, nicht nur behaupten.** Nach jeder
  Änderung die schnelle Suite der betroffenen Komponente laufen lassen. Die
  schweren Integrations-/Live-Tests (`scripts/tests/integration_stack_test.sh`,
  `desktop_e2e_live.sh`, `desktop_e2e_tunnel.sh`) laufen lokal/manuell (nicht im
  PR-CI) — bei Änderungen am jeweiligen Pfad (Gateway/Server-API bzw.
  Desktop-Connect/Tunnel/Enrollment) ausführen und das Ergebnis berichten. Die
  Dev-Box hat kein Docker/Display — dafür gibt es **crabbox** (siehe Abschnitt
  „Testing auf crabbox").
- **CI-Jobs nach dem Auslösen immer überwachen.** Sobald ein Push oder ein
  Release-Tag CI-Workflows triggert, die Läufe bis zum Abschluss verfolgen
  (`gh run watch`), das Ergebnis berichten und transiente Fehler (z. B.
  Netzwerk/DNS beim Registry-Login) per gezieltem Re-Run der fehlgeschlagenen
  Jobs (`gh run rerun <id> --failed`) beheben. Nicht „fertig" melden, solange CI
  noch läuft oder rot ist.
- **Plattform-spezifisches Verhalten wird manuell verifiziert.** Bei
  Änderungen an Plattform-Code (Linux / macOS / Windows) in der Antwort
  bzw. PR dokumentieren: was wurde getestet, auf welcher Plattform, mit
  welchem Ergebnis. Relevant v. a. für den Go-Agent (`*_linux.go` /
  `*_windows.go`) und den Desktop-Client (RDP/SSH pro OS).

### Kommunikation

- **Direkt und kurz.** Lange Erklärungen sind oft Tarnung für
  Unsicherheit. Klar verstanden? Dann ein Satz reicht.
- **Ehrlich über Grenzen.** "Ich weiß nicht", "habe nicht verifiziert",
  "ist Vermutung" sind vollwertige Beiträge, keine Schwächen.
- **Push back, wenn nötig.** Wenn ein Wunsch Scope-Creep ist, eine
  Trade-off-Falle hat, oder eine bestehende Architektur-Entscheidung
  unterläuft: benennen, nicht stillschweigend mitmachen.
- **Nutzer-Spracheingaben charitable interpretieren.** Diktierte Anfragen
  haben Erkennungsfehler — auf Intent reagieren, nicht auf Wortlaut.
- **Empfehlungen mit Begründung.** Statt "Empfehlung X" lieber
  "Empfehlung X, weil Y; Trade-off Z."
- **Sprache: Deutsch, technische Begriffe und Code-Bezeichner im
  Original.**

### Code-Konventionen

- **Conventional Commits:** `feat:` / `fix:` / `chore:` / `refactor:` /
  `docs:` / `test:` / `perf:` / `tune:`. Pro logischem Schritt einen
  Commit. Commit-Messages auf Englisch, Release-Tags `vX.Y.Z`.
- **Rust:** `cargo fmt` + `cargo clippy -- -D warnings` müssen sauber
  durchlaufen.
- **TypeScript:** Strict Mode, kein `any`, ESLint + Prettier sauber.
- **Go:** `gofmt` + `go vet` sauber.
- **Python:** FastAPI-Stil des jeweiligen Moduls matchen; Logik mit
  `pytest` absichern; `ruff check` + `ruff format` müssen sauber sein.
- **SPDX-Header & Lizenz:** Das Projekt ist **GPL-3.0-or-later** lizenziert
  (`LICENSE`, `LICENSES/`, Drittanbieter in `THIRD_PARTY_LICENSES.md`). **Jede
  neue Quelldatei** (`.py` `.go` `.rs` `.ts` `.svelte` `.js`/`.mjs`) bekommt
  den REUSE-konformen Header (`SPDX-FileCopyrightText` + `SPDX-License-Identifier`,
  Lizenz `GPL-3.0-or-later`) — am einfachsten via `reuse annotate --copyright
  "Kevin Stenzel" --license GPL-3.0-or-later <datei>` (`#` für Python, `//` für
  Go/Rust/TS/JS, `<!-- -->` für `.svelte`). Bestandscode ist vollständig
  annotiert.
- **Tests:** Unit-Tests für reine Logik — hier konkret: FRP-Config-
  Generierung, Permission-/IP-Filter-Checks, Schema-Validierung,
  Agent-Drift-Detektion (SHA-256), Svelte-Stores/Models. Plattform-Code
  wird manuell verifiziert, Verifikationsschritte werden in der
  Antwort/PR dokumentiert.
- **Kommentare nur, wenn das Warum nicht-offensichtlich ist** — versteckte
  Constraints, subtile Invarianten, Workarounds für konkrete Bugs. Das
  WAS steht im Code.

### Doku-Pflege

Code-Änderung ohne entsprechendes Doku-Update gilt als unvollständig. Vor
"fertig" prüfen, ob diese Dateien angepasst werden müssen:

- **`docs/` — die vollständige Produkt-Dokumentation** (zweisprachiges HTML,
  DE/EN). Deckt **alles** ab: Admin-/Anwender-Themen (Bedienung,
  Installation, Betrieb, Monitoring, FRP, Troubleshooting) **und**
  Entwickler-Themen (Architektur & Komponenten-Grenzen/Datenflüsse, neue
  Module, externe Integrationen samt Wire-Protokollen & Auth,
  plattform-spezifisches Verhalten). Bei **jeder** inhaltlich relevanten
  Änderung **immer** mitpflegen — Pflicht, kein optionales „prüfen" — und
  **beide** Sprachen nachziehen. **Im Zweifel über Bedienung oder erwartetes
  Verhalten zuerst hier nachschlagen.**
- **`README.md`** — user-sichtbarer Einstieg: Install, Build, Usage,
  Features, CLI-Flags, Voraussetzungen, Troubleshooting.
- **`DEVELOPMENT.md`** — Entwickler-Setup, lokale Workflows, neue
  Abhängigkeiten/Komponenten, Änderungen am Docker-Compose-Setup.
- **`CHANGELOG.md`** — bei jeder neuen Version: Keep-a-Changelog-Format +
  SemVer (`## [X.Y.Z] - YYYY-MM-DD`, Abschnitte Added/Changed/Fixed/Removed).

Regeln:

- **Doku-Update gehört in denselben Commit** wie die Code-Änderung.
  Conventional-Commit-Type bleibt der der Code-Änderung; `docs:` nur,
  wenn _ausschließlich_ Doku geändert wird.
- **Im Zweifel scannen, dann entscheiden** — nicht raten. Lieber kurz
  die betroffene Doku öffnen, als eine veraltete Stelle stehen lassen.
- **Wenn eine Doku-Aussage nicht mehr stimmt: korrigieren**, auch wenn
  sie nicht direkter Teil deiner Änderung ist. Ausnahme zur
  Surgical-Changes-Regel — falsche Doku ist ein Bug.

## Testing auf crabbox (schwere Suites)

Die schnellen Unit-/Lint-Suites laufen überall (und im GitHub-CI). Der **schwere
Tier** — die reale docker-compose-Stack-Integration, mTLS-Enrollment, Redis-SSE-
Fan-out, Agent-Monitoring, apt/rpm-Repo-Bau und die Desktop-GUI-E2E — braucht
echtes Linux mit **Docker + Display**, was die Sandbox-Dev-Box nicht hat.
**crabbox** least dafür eine ephemere Proxmox-VM (Provider-Env in
`.claude/settings.json`; das Token-Secret nur im gitignored
`.claude/settings.local.json`; prüfen mit `crabbox doctor`).

- **Ein Sammel-Runner** bündelt alles:
  `bash scripts/tests/run.sh [lint|unit|quick|integration|e2e|all]`.
  `quick` (Default) = lint + unit; `integration`/`e2e`/`all` fahren echte
  Docker-/GUI-Suites und **verweigern ohne `AH_ALLOW_REAL=1`** (Schutz vor
  versehentlichen Läufen). Jeder Schritt ist dep-gated und skippt sauber, wenn
  ein Toolchain fehlt; am Ende `N passed, M failed, K skipped` (Exit ≠ 0 bei Fail).
- **Box-Lifecycle** (warm once → Slug wiederverwenden → stoppen):
  `crabbox warmup` → `crabbox run --id <slug> -- 'bash scripts/tests/crabbox_bootstrap.sh'`
  (hydriert docker/go/rust/node/xvfb/tauri-driver/frpc) →
  `crabbox run --id <slug> -- 'AH_ALLOW_REAL=1 bash scripts/tests/run.sh integration'`
  → `crabbox stop --id <slug>`. Fehler-Bundles landen lokal in `.crabbox/captures/`
  (gitignored). Details/Regeln: die `/test`-Skill (`.claude/skills/test/SKILL.md`).
- **Multi-Box (verteilt):** `bash scripts/tests/crabbox_multibox.sh --agents N`
  least eine Server-Box (voller Stack) + Agent-Box(en) auf derselben Bridge
  (`vmbr1`) und provisioniert das echte `.deb` über einen echten Netz-Hop —
  Cross-Host-mTLS, echte Paketinstallation, die `:8445`-Repo-Plane. Leases werden
  beim Exit gestoppt (`--keep` zum Inspizieren).
- **crabbox ist NICHT der PR-CI.** Unit/Lint/Build-Gates bleiben in
  `.github/workflows/ci.yml`; crabbox ist der lokal/agent-getriebene Pfad für den
  schweren Tier auf echtem Linux. Erlaubt (auto): `warmup/run/status/list/connect/
  ssh/doctor/stop/cleanup`; `prewarm/job` provisionieren/kosten → vorher fragen.
  **Nie „grün" melden, ohne dass die Suite real bestanden hat** — die
  `run.sh`-Summary-Zeile zählt; SKIP heißt „nicht verifiziert", nicht „ok".
