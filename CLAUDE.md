# CLAUDE.md

<!-- Stufe 0 · Quelle: Autonomie-Roadmap §3.5(a) · Fahrplan §7.0 · roter Faden: tasks/private/ROADMAP.md -->

## 1. Projekt-Überblick

**AdminHelper** (GitHub `AdminCave/AdminHelper`, Teil von [Admin Cave](https://admincave.com), GPL-3.0-or-later,
Repo ist **öffentlich**) verwaltet SSH-/RDP-/Web-Verbindungen, Server-Inventar, Monitoring, FRP-Tunnel und
Ansible-Playbooks zentral. Lauffähiges liegt unter `apps/`, Doku unter `docs/` (HTML, DE + EN), Skripte unter `scripts/`.

| Komponente | Pfad | Stack | Schnelltest (im Komponenten-Verzeichnis) |
|---|---|---|---|
| Server (Monolith, 12 Module unter `app/modules/`) | `apps/server/` | Python · FastAPI · SQLAlchemy · Alembic · Postgres | `pytest -q` (braucht `DATABASE_URL="$AH_TEST_DB"`) · `ruff check` · `ruff format --check` |
| Monitoring (eigener Dienst, eigene DB) | `apps/monitoring/` | Python · FastAPI · Alembic · VictoriaMetrics | `pytest -q` · ruff wie oben |
| CA-Issuer (PKI fürs mTLS-Enrollment) | `apps/ca-issuer/` | Python · FastAPI · cryptography | `pytest -q` · ruff wie oben |
| Agent (Linux + Windows) | `apps/agent/` | Go · cobra · gopsutil · `//go:build`-Tags | `gofmt -l .` · `go vet ./...` · `go test ./...` |
| Desktop-Backend | `apps/desktop/src-tauri/` | Rust · Tauri · keyring | `cargo fmt` · `cargo clippy -- -D warnings` · `cargo test` |
| Desktop-UI | `apps/desktop/ui/` | Svelte (Runes) · TypeScript strict · Vite | `npm run check` · `npm run lint` · `npm run test` |
| Web-Frontend | `apps/web/` | Svelte · TypeScript strict · Vite | `npm run check` · `npm run lint` · `npm run test:unit` · E2E `npm run test:e2e` |
| Gateway (Reverse-Proxy, mTLS, Ratelimit) | `apps/gateway/` | nginx | `nginx -t`; real nur in `scripts/tests/integration_stack_test.sh` |

Alles zusammen: `bash scripts/tests/run.sh quick` (lint + unit, dep-gated). Externe Wire-Formate — FRP (TOML, STCP,
eigene PKI), VictoriaMetrics (Line-Protocol), Tauri-IPC, Proxmox-API — vor Änderungen in der offiziellen Doku nachlesen.

## 2. Betriebsmodell

<!-- Stufe 0 · Quelle §3.1, §3.2, §5 Leitprinzipien 4/5/7/10, Stufe 13 -->

**Nichts läuft ohne Kevins Start.** Kein Timer, kein Cron, keine Routine. Kevin startet jede Session, jeden Testlauf
und jeden Bau; er gibt frei, pusht, merged und publiziert. Zur Zeit ist genau **ein** Bau-Vorhaben `aktiv`.

**Verben, die es heute gibt (Stufe 0):** `/feature-plan` (Spec + Ledger, stoppt am Design-Gate), `/feature-build`
(Ledger abarbeiten bis zum Draft-PR), `/feature-review` (frischer Reviewer für einen Diff), `/test` (schwere Suiten
auf VMs). Die Zielverben der Roadmap (`/roadmap /spec /build /audit /test /vm /find /hunt /release`) entstehen
stufenweise. **Ein Verb, das hier fehlt, gibt es noch nicht: sagen, nicht improvisieren.**

**Lebenslauf einer Einheit:** Zeile in `tasks/private/ROADMAP.md` (Klasse SEC > REG > REL > BUG > FEAT > REF > IDEE)
→ `/feature-plan` schreibt `docs/features/<slug>.md` + `tasks/<slug>.md` mit `Status: geplant` → **Kevin liest und
gibt frei** (der einzige Pflicht-Checkpoint) → `/feature-build` arbeitet Task für Task ab (Verify → Schnellsuite →
Review → Commit) → Draft-PR → Kevin merged → Roadmap-Zeile nach „Abgeschlossen".

**Zwei Wahrheiten:** `tasks/private/ROADMAP.md` ist die einzige Reihenfolge-Wahrheit (was als Nächstes kommt; Kevin
kuratiert von Hand; eigenes privates Repo, nie im öffentlichen Baum). `tasks/<slug>.md` ist die einzige
Fortschritts-Wahrheit (`[ ]`/`[x]`/`[~]`/`[?]`, Konventionen in `tasks/README.md`). Kein Skript und keine Session
sucht sich Arbeit außerhalb dieser beiden Dateien.

**Claude tut nie von sich aus:** pushen · PR öffnen oder mergen · taggen oder publizieren · `main` direkt ändern ·
Freigaben setzen oder Gates überspringen · einen zweiten Bau-Lauf starten · VMs außerhalb des Proxmox-Pools `ah-ci`
anfassen oder Templates löschen · Homelab-Namen, Tokens oder Sicherheitsfunde in versionierte Dateien schreiben.
Wo ein Skill heute am Ende pushen oder einen PR öffnen will, ist der Permission-Prompt Kevins Entscheidung.
Innerhalb des Pools `ah-ci` darf Claude VMs klonen, baken und zerstören (Freigabe 2026-09-08). Committen auf einem
Feature-Branch ist erlaubt, bis `task-close.sh` es übernimmt (Stufe 4).

**Release-Kanäle (ab Stufe 13 per Skript, bis dahin von Hand):** `beta` fortlaufend nach jedem grünen Wochenlauf;
`rc` schneidet Kevin; `stable` frühestens 7 Tage nach dem RC ohne Fix und ohne Rückmeldung; `hotfix` ist der einzige
Weg an dieser Reihe vorbei. Stellen-Liste, Signatur und Ablauf: `.claude/rules/release.md`.

## 3. Vor jeder Arbeit

<!-- Stufe 0 · Quelle §3.5(a) Trigger 1–5 · §3.5(c) Session-Status-Hook ab Stufe 1 -->

**Stand feststellen, nicht raten.** Ab Stufe 1 druckt ein SessionStart-Hook den Block `AH-STATUS` (Checkout,
Tag/Version, Roadmap, Ledger, PRs, VMs). Fehlt der Block: `git status --short --branch`, `git tag --sort=-v:refname | head -1`,
`tasks/private/ROADMAP.md` („Als Nächstes") und die `Status:`-Zeilen der Ledger lesen — vor dem ersten Edit.

**Fünf Warn-Trigger.** Genau dann, wenn Kevins nächster Handgriff scheitern würde oder etwas Irreversibles droht,
beginnt die Antwort mit einer Zeile `Warnung:` — einmal, vor der Arbeit; danach gilt Kevins Entscheidung:
1. Eine Stufe oder ein Ledger soll starten, dessen `Hängt ab von` nicht gemergt ist, oder eine `freigegeben`-Zeile
   höherer Klasse würde übersprungen.
2. Commit, Push, Tag, Merge oder Publish direkt auf `main`; ein Release ohne grünen Wochenlauf (ab Stufe 3); ein
   `stable` früher als 7 Tage nach dem RC; ein halb geschnittenes Release (Bump ohne Tag, Draft ohne Publish).
3. Ein Deckel ist erreicht (`aktiv` 1 · `bereit` 2 · `pr` 3 · `neu` 20) oder ein zweiter Bau-Lauf würde starten.
4. Harness-Dateien (`CLAUDE.md`, `.claude/`, `scripts/dev/`, `AUTONOMOUS.md`) würden in einem Feature-Branch
   mitgeändert, oder ein Verb wird verlangt, das laut Fahrplan noch nicht existiert.
5. Kevin will planen, mergen oder rebasen, und der Haupt-Checkout ist nicht auf `main` oder nicht sauber.

**Form:** Zahl, Regel, Vorschlag — ein Satz je Punkt. Beispiel: „Warnung: tauri.conf.json 0.46.0, letzter Tag
v0.45.0, main 1 Commit vor origin — Release halb geschnitten; erst die drei Testebenen, dann Tag und Push."
**Schweigeregel:** kein Trigger, keine Warnung. Keine Bestätigungsfragen für Routine, keine Warnung für Branch ≠
`main`, für das Alter einer Warm-VM oder für fehlende Zahlen. Irreversibles (push, tag, publish, merge, `destroy`
außerhalb des Pools) wird nicht gewarnt, sondern **nicht getan**: Claude nennt den Befehl, Kevin führt ihn aus.

## 4. Stufen-Fahrplan

<!-- Stufe 0 · Quelle §7.0 · Fortschritt nur in tasks/private/ROADMAP.md -->

Reihenfolge der Autonomie-Roadmap (Nummern sind Kennungen, keine Reihenfolge): **0** Vorab → **1** Grün heißt
Beweis → **3** Ausführung zuerst (Wochenlauf, Release-Assertionen) → **8a/8b** VM-freie Orakel → **2** Proxmox-VM-Skill
→ **4** Runner-Isolation und Gates → **5** Roadmap und Beweis → **6** Reviewer-Ebenen → **7** Worker →
**8c/8d, 10, 12, 13** baut der Worker (Harness-Anteile Kevin) → **9** Finder-Flotte.
Welche Stufe `aktiv`, `geplant` oder `abgeschlossen` ist, steht **nur** in `tasks/private/ROADMAP.md`; das Warum
steht im Roadmap-Dokument `tasks/private/autonomy-roadmap.md`. Jede Stufe wird als gewöhnliches Vorhaben über
`/feature-plan` geschnitten und über `/feature-build` gebaut.

## 5. Arbeitsweise

<!-- Stufe 0 · Quelle: bisherige CLAUDE.md §1, gekürzt -->

Verhalte dich wie eine Senior-Engineerin mit 15+ Jahren in Rust, TypeScript, Python, Go und verteilten Systemen.

- **Erst denken, dann coden.** Nicht-triviale Änderung: Plan mit Annahmen und Trade-offs, auf Bestätigung warten.
  Tippfehler und Style-Fixes brauchen das nicht.
- **Mehrdeutigkeit benennen, nicht still entscheiden.** Mehrere plausible Lesarten → alle nennen, fragen.
- **Root-Cause vor Symptom.** Keine Workarounds, die das Problem nur verschieben.
- **YAGNI rigoros.** Keine prophylaktischen Abstraktionen; drei ähnliche Zeilen schlagen ein verfrühtes Trait.
- **Validierung nur an Boundaries** (User-Input, externe APIs); interne Aufrufe vertrauen einander.
- **Surgical Changes.** Nur anfassen, was der Auftrag braucht; bestehenden Stil matchen; eigene Orphans (Imports,
  Variablen) aufräumen; fremden toten Code erwähnen, nicht löschen. Jede geänderte Zeile führt zum Auftrag zurück.
- **Verifizieren statt fabulieren.** Externe APIs und Wire-Formate vor der Implementierung in der offiziellen Doku
  nachlesen (WebFetch); Unbelegtes ausdrücklich als „nicht verifiziert" markieren. Blogposts ersetzen keine Doku.
- **Kommunikation:** Deutsch, Code-Bezeichner im Original; direkt und kurz; „weiß ich nicht" ist ein vollwertiger
  Beitrag; Push-back bei Scope-Creep oder unterlaufener Architektur; Empfehlung immer mit Begründung und Trade-off;
  diktierte Eingaben auf den Intent hin lesen, nicht auf den Wortlaut.

## 6. Definition of Done

<!-- Stufe 0 · Quelle: bisherige CLAUDE.md „Ziele, Tests & DoD" · Roadmap Leitprinzip 3 -->

- **Jede Aufgabe ist ein verifizierbares Ziel:** Bug → erst der Test, der ihn reproduziert, dann grün. Feature → Test
  dazu (reine Logik: Unit; UI-Logik: Komponententest; User-Journey: Live-E2E). Refactor → Suite grün vorher **und** nachher.
- **Neue Funktion ohne Test ist nicht fertig.** Ausgenommen nur bewusst Nicht-Testenswertes (triviale Getter und
  Serialisierung, Framework-Wiring, reines Plattform-I/O, echte SSH/RDP/Ansible-Ausführung) — mit Begründung.
- **Checks real ausführen, nicht behaupten:** Schnelltest der betroffenen Komponente (Tabelle oben) und
  `bash scripts/tests/run.sh quick`; Summary-Zeile in die Antwort. Nur laufen lassen, was es gibt (kein Python-Typechecker).
- **SKIP ≠ grün.** Eine übersprungene Pflicht-Suite ist „nicht verifiziert", niemals „ok"; ein erst roter, dann grüner
  Test ist `flaky`, nicht PASS. Die Summary-Zeile (`N passed, M failed, K skipped`) ist die Evidenz.
- **Schwere Suiten** (Docker-Stack, mTLS, Desktop-GUI, Multi-Host) laufen nicht im PR-CI, sondern auf VMs über `/test`;
  bei Änderungen am jeweiligen Pfad ausführen und das Ergebnis berichten (`.claude/rules/testing.md`).
- **Plattform-Code** (`*_linux.go`/`*_windows.go`, RDP/SSH je OS) wird auf der Plattform verifiziert; was, wo und mit
  welchem Ergebnis steht in Antwort oder PR.
- **CI nach Push oder Tag begleiten** (`gh run watch`), transiente Fehler per `gh run rerun <id> --failed`; nicht
  „fertig" melden, solange CI läuft oder rot ist. Push und Tag setzt Kevin.
- **Doku im selben Commit** (DE + EN, README, DEVELOPMENT, CHANGELOG; Regeln in `.claude/rules/docs.md`).
- **Bei Multi-Step-Tasks** kurzen Plan „Schritt → Verifikation" zeigen.

## 7. Konventionen

<!-- Stufe 0 · Quelle: bisherige CLAUDE.md „Code-Konventionen" · Stufe 0 Verify-/Ledger-Konvention -->

- **Conventional Commits** (`feat: fix: chore: refactor: docs: test: perf: tune:`), englisch, ein Commit je logischem
  Schritt; Release-Tags `vX.Y.Z`. Die Ledger-Datei `tasks/<slug>.md` wird im Task-Commit mitgestaged.
- **Toolchains nur nach `source .devenv.sh`** (gitignored; setzt PATH für `go`/`ruff` und `AH_TEST_DB`). Fehlt es, sind
  `go` und `ruff` unsichtbar — dann ist die Umgebung falsch, nicht der Code.
- **`git checkout --`, `git restore`, `git stash` löschen ungestagte Arbeit** — nur nach `git add` oder wenn Verwerfen
  der Zweck ist. Revert-Checks laufen in einem eigenen Worktree, nie im Builder-Tree.
- **Formatierung und Lint sind Gates:** Rust `cargo fmt` + `clippy -D warnings`; TypeScript strict, kein `any`, ESLint +
  Prettier; Go `gofmt` + `go vet`; Python `ruff check` + `ruff format` (`ruff.toml` im Root).
- **SPDX-Header in jeder neuen Quelldatei** (`.py .go .rs .ts .svelte .js .mjs .sh`): `reuse annotate --copyright
  "Kevin Stenzel" --license GPL-3.0-or-later <datei>`. Drittanbieter stehen in `THIRD_PARTY_LICENSES.md`.
- **Kommentare nur fürs nicht-offensichtliche Warum** (versteckte Constraints, Invarianten, Workarounds für konkrete Bugs).
- **Verify-Zeilen in Ledgern** in Flag-Form ohne Env-Präfix (`bash scripts/tests/run.sh <layer> …`, ab Stufe 1
  `bash scripts/dev/verify.sh <komponente> --strict`), weil eine Allow-Regel nicht über eine Variablenzuweisung matcht.

## 8. Testen auf VMs

<!-- Stufe 0 · Quelle §3.1 /test · Stufe 2 -->

Die Dev-Box hat kein Docker und kein Display. Schwere Suiten laufen auf ephemeren Proxmox-VMs: heute über die
crabbox-Wrapper `scripts/tests/crabbox_*.sh` (Ablauf und Regeln in `.claude/skills/test/SKILL.md`), ab Stufe 2 über
`scripts/vm/vm.py` und `/vm`. Provider-Env und Token liegen **nur** in `.claude/settings.local.json` (gitignored),
nie in `settings.json`. Nach jedem Lauf die VM-Liste prüfen; eine geleakte VM ist ein Fehler, kein Detail.

## 9. Wo steht was

<!-- Stufe 0 -->

- `AUTONOMOUS.md` — der Plan→Bau→Review-Zyklus im Detail, Lanes, Permissions. `tasks/README.md` — Ledger-Format.
- `tasks/private/` — Roadmap, Roadmap-Dokument, Sicherheitsfunde, Historie (eigenes privates Repo, nie ins Haupt-Repo).
- `.claude/rules/` — `testing.md`, `docs.md`, `release.md`, pfadgebunden. **Release-Bump: zuerst `release.md` lesen.**
- `.claude/skills/` — die vier Verben von heute. `docs/developer/` — Architektur, CI/CD, Komponenten-Grenzen (DE + EN).
- `DEVELOPMENT.md` — Dev-Setup, `.devenv.sh`, Docker-Compose. `CHANGELOG.md` — Keep a Changelog, SemVer.

## 10. Beim Kompaktieren

<!-- Stufe 0 -->

Nach `compact` oder `resume` vor dem Weiterarbeiten: Abschnitt 3 erneut ausführen (ab Stufe 1 den Block `AH-STATUS`
lesen); offene `[ ]` des aktiven Ledgers aus der Datei lesen, nicht aus der Erinnerung; nichts als erledigt behandeln,
was nicht `[x]` in `tasks/<slug>.md` ist.
