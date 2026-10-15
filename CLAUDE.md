# CLAUDE.md

## 1. Projekt
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

Alles zusammen: `bash scripts/tests/run.sh quick --strict` (lint + unit, dep-gated). Externe Wire-Formate — FRP
(TOML, STCP, eigene PKI), VictoriaMetrics (Line-Protocol), Tauri-IPC, Proxmox-API — vor Änderungen in der offiziellen
Doku nachlesen. Die Dev-Box hat Docker, aber kein Display; schwere Suiten laufen auf Proxmox-VMs (`/test`).

## 2. Betriebsmodell
Kevin startet jede Session und entscheidet: Reihenfolge und Inhalt der Roadmap, Freigabe eines Plans, sichtbares
Verhalten, API-Verträge und Datenmigrationen, hingenommenes Restrisiko, Geld- und Zeitdeckel, Release, Tag,
Ruleset, Repo-Einstellungen, sudo, Tokens, Passwörter. Alles andere innerhalb eines freigegebenen Vorhabens
entscheidet die Session und berichtet danach; Fragen an Kevin gesammelt und mit Empfehlung.
Eine Session arbeitet ein Vorhaben Task für Task ab: ein Bauer-Sub-Agent baut die Task im Worktree des Vorhabens,
ein Reviewer-Sub-Agent prüft, `scripts/dev/task-close.sh` fährt das `Verify:`, den Token-Scan und committet Code und
Ledger. Zwei freigegebene, disjunkte Vorhaben baut die Session parallel (Deckel `aktiv` 2 in `roadmap.py`), je in
eigenem Worktree (Kriterien `/feature-plan` §4); innerhalb eines Vorhabens bauen die Tasks nacheinander. Produkt-PRs
merged die Session, wenn die CI im ersten Anlauf grün ist, einen je CI-Zyklus, und nur, wenn der Branch `origin/main`
enthält (`git fetch`, `merge-base --is-ancestor`; sonst mergen, pushen, neue CI): Das Ruleset prüft die Kombination
nicht, die PR-CI testet dann genau `main` + PR (Kevin, 2026-10-15). PRs, die
`CLAUDE.md`, `.claude/`, `scripts/` oder `.github/` ändern, merged Kevin. Ist `main` rot, wird der letzte Merge
revertiert, und bis `main` grün ist, wird nichts weiter gemergt; flaky heißt Rerun plus Roadmap-Zeile. Lange
Läufe (`/test`, Wochenlauf, Multibox, Suiten über zehn Minuten) laufen in einem tmux-Fenster ohne Modell mit
`( . ./.devenv.sh; … ) > log; echo $? > rc`; die Session wartet mit einem Hintergrund-Wächter auf die `rc`-Datei
und liest das Log, nie durch `tail` gepipt.

## 3. Vor jeder Arbeit
Der SessionStart-Hook druckt `AH-STATUS` (Checkout, Tag, Roadmap, Ledger, PRs, VMs). Fehlt er: `git status --short
--branch`, `git tag --sort=-v:refname | head -1`, „Als Nächstes“ in `tasks/private/ROADMAP.md`, `Status:` des
Ledgers. Nach `compact` oder `resume` dasselbe; offene `[ ]` aus der Ledger-Datei lesen, nicht aus der Erinnerung.
Eine `Warnung:`-Zeile, einmal, vor der Arbeit, genau dann: (1) ein Vorhaben soll starten, dessen `Hängt ab von`
nicht gemergt ist, oder eine `freigegeben`-Zeile höherer Klasse würde übersprungen; (2) ein Commit, Push, Tag oder
Merge direkt auf `main` steht bevor, oder ein Release ohne grünen Wochenlauf; (3) ein Feature-Branch würde
Harness-Pfade mitändern; (4) Kevin will planen, mergen oder rebasen, und der Haupt-Checkout ist nicht auf `main`
oder nicht sauber. Sonst keine Warnung und keine Bestätigungsfrage für Routine.

## 4. Lebenslauf eines Vorhabens
Zeile in `tasks/private/ROADMAP.md` (Klasse SEC > REG > REL > BUG > FEAT > REF > IDEE) → `/feature-plan` schreibt
`docs/features/<slug>.md` und `tasks/<slug>.md` (`Status: geplant`) als ersten Commit auf `feature/<slug>` → Kevin
gibt frei: er tippt `! python3 scripts/dev/roadmap.py approve R-nnnn`; die Freigabe ist dieser Roadmap-Status →
`/feature-build` setzt beim Start im Worktree den Ledger-Kopf von `geplant` auf `aktiv` (`chore(ledger)`, nur wenn
die Roadmap-Zeile `freigegeben` ist) und baut Task für Task → Abschluss (§5, §6) → PR → Merge → `roadmap.py sync`.
Die Roadmap ist die einzige Reihenfolge-Wahrheit, das Ledger die einzige Fortschritts-Wahrheit
(`[ ]`/`[x]`/`[~]`/`[?]`, Format `tasks/README.md`). Keine Session sucht sich Arbeit außerhalb dieser zwei Dateien.
Harness-Pfade ändert eine Session nur auf Kevins Wort oder bei belegtem Produktschaden (roter Produkttest, falscher
Merge, Datenverlust, Leak), als eigene Task, nie nebenbei. Funde an der Harness aus Reviews werden Roadmap-Zeilen
`zurückgestellt`, keine Ledger.

## 5. Tests sind Beweis
- Je Task nur das `Verify:` der Task mit gezieltem Testpfad (`bash scripts/dev/verify.sh <komp> --strict -- <test>`;
  `verify.sh` sourct `.devenv.sh` selbst, `run.sh` nicht). Die Komponenten-Suiten fährt nur die PR-CI;
  `bash scripts/tests/run.sh quick --strict` lokal vor einem Release. Verify-Zeilen in Flag-Form ohne Env-Präfix.
- Die Summary-Zeile (`N passed, M failed, K skipped`) ist die Evidenz und steht neben jedem `[x]`. Ein SKIP, ein
  fehlendes Werkzeug, ein abgebrochener Lauf oder ein Befehl ohne Ausgabe ist rot. Erst rot, dann grün ist `flaky`.
- Ein Server-Lauf zur Zeit je Test-DB; jeder Worktree hat seine eigene (§8). Revert-Proben nie im Bau-Worktree,
  sondern in einem eigenen.
- Berührt der Branch-Diff `apps/server`-API, Gateway, CA-Issuer, Agent, Desktop-Tunnel/Enrollment, Compose,
  Install/Update, FRP oder PKI: `linux-full` im Sammellauf über `main` (`/test all`; ob er fällig ist, prüft die
  Session beim Start und nach jedem Merge und startet ihn selbst, `/feature-build` §5, Kevin 2026-10-15), `scenario`
  und `windows` vor dem Merge, Multibox nur nach Kevins Ja. VM-Läufe dürfen parallel laufen, je Vorhaben in seiner
  Lane; `vm.py` prüft vor jedem Klon den RAM des Hosts. Im Pool `adminhelper-ci` darf die Session VMs klonen, baken
  und zerstören (Kevin, 2026-09-08); danach `python3 scripts/vm/vm.py list`; eine geleakte VM ist ein Fehler.
  Proxmox-Zugang: Umgebung > `~/.config/adminhelper/pve.env` (0600, gelesen, nie gesourct) > `settings.local.json`.
- Neue Funktion ohne Test ist nicht fertig: Bug → erst der rote Test, dann grün; Feature → Test dazu; Refactor →
  Suite grün vorher und nachher. Ausnahmen mit Begründung: triviale Getter, Framework-Wiring, reines Plattform-I/O,
  echte SSH/RDP/Ansible-Ausführung. Plattform-Code wird auf der Plattform verifiziert und das Ergebnis genannt.
- CI nach Push begleiten (`gh pr checks <n> --watch --fail-fast`), nach einem Merge den `ci.yml`-Lauf des
  Merge-Commits auf `main` (`gh run watch <id> --exit-status`); nicht „fertig“ melden, solange CI läuft oder rot ist.

## 6. Prüfer: Sub-Agenten mit festem Auftrag (`.claude/agents/`)
Aufruf immer über das Agent-Werkzeug mit `subagent_type` (`builder`, `reviewer`, `tester`, `security`), nie über
automatische Wahl; Kevin tippt `@agent-<name>`. Jeder Aufruf nennt den **absoluten Worktree-Pfad**; Sub-Agenten
laufen im Arbeitsverzeichnis der Session und müssen `git -C <wt>` und `bash <wt>/scripts/…` nutzen.
- Bauen: `builder` je Task mit Worktree-Pfad, Ledger, Task-ID, Spec-Stelle. Er baut, fährt das `Verify:`,
  hinterlässt die Commit-Nachricht und committet nicht. Fragen beendet er mit `[?]` im Ledger; die Session fragt
  Kevin und setzt ihn mit der Antwort fort (SendMessage an denselben Agenten).
- Vor jedem Commit: `reviewer` (Opus) mit Diff-Pfaden, Slug, Task-ID, Summary-Zeile, eigenem Scratch-Verzeichnis.
  Die Session schreibt keinen Prüfprompt; der Auftrag ist die Agent-Datei. `approve` → `task-close.sh`.
  `request_changes` mit `blocker` oder belegtem `wichtig` → `builder` mit den Funden einmal, Tests erneut, einmal
  re-reviewen; danach Commit oder `[?]`. Nits blockieren nie. Zwei Runden sind das Maximum.
- Berührt der Diff einen Risikopfad (`scripts/dev/review-risk.txt`: Auth, Enrollment, PKI, FRP, Gateway, Alembic,
  Release-Dateien, Harness-Pfade): zusätzlich `security`.
- Vor dem Abschluss: `tester` über den Branch (Tests da, echt, rot ohne den Fix?) und `reviewer` über
  `git -C <wt> diff main...`. Beide Urteile stehen im PR-Text.
- Sub-Agenten haben keine Uhr, `maxTurns` ist Notbremse. Turn-Limit → einmal fortsetzen („Ergebnis jetzt“); erneut
  oder 20 min ohne Wachstum der `output_file` (`stat -L -c %Y`, nie lesen) → stoppen, einmal enger neu starten (tester:
  Probe-Worktree vorher weg), dann prüft die Session selbst (Commit-Body), beim builder `[~]`. Keine vollen Suiten.

## 7. Commit
Nur `bash <wt>/scripts/dev/task-close.sh <ledger> <id> --stage -m "<msg>"` (im Worktree) committet eine Task: es
fährt das `Verify:`, prüft das Reviewer-Urteil und den Token-Scan, stagt genau die `Dateien:` der Task, setzt den
Haken mit der Summary-Zeile und committet Code und Ledger in einem Commit. Exit 2: nicht (voll) gestagt oder
Eingabe kaputt; 3: Suite rot, Urteil fehlt oder Testdatei ohne `Test-Löschung:` gelöscht; 4: Token im Diff oder
Deklarationszeile im Commit geändert; 74: Suite konnte nicht laufen, STOPP. Plan- und Ledger-Commits
(`chore(plan)`, `chore(ledger)`) macht die Session selbst. Conventional Commits auf Englisch, ein Commit je Task.
Die Git-Hooks fahren den Token-Scan; `--no-verify` gibt es nicht. Nie einen roten Stand committen: ein Fix, der in
zwei Versuchen nicht grün wird, wird zurückgenommen (`git -C <wt> restore --source=HEAD --staged --worktree --
<datei>`) und die Task `[~] verworfen: <Grund>`. `git checkout --`, `git restore` und `git stash` löschen ungestagte
Arbeit: nur nach `git add` oder wenn Verwerfen der Zweck ist.

## 8. Roadmap, Ledger, Worktrees
`tasks/private/` ist ein eigenes privates Repo (Sicherheitsfunde, Homelab-Namen): nie im öffentlichen Baum. Die
Roadmap schreibt nur `python3 scripts/dev/roadmap.py` (`add`, `status`, `approve`, `sync`, `lint`), nie ein Edit; „Als
Nächstes“ pflegt Kevin von Hand. Statuswechsel: neu → geplant → freigegeben (nur Kevin) → aktiv → bereit → pr →
abgeschlossen (`sync`); `zurückgestellt`/`blockiert` mit `--note` und Datum.
Jedes Vorhaben baut in einem eigenen Worktree: `git worktree add ../AdminHelper-<slug> feature/<slug>` und
`bash scripts/dev/worktree-setup.sh ../AdminHelper-<slug> <slug>` (eigene Test-DB, Venv, `node_modules`, Sidecar,
`.vm/lane`); erst danach den Ledger-Kopf im Worktree ändern (das Ledger liegt nur auf dem Branch). Nach dem Merge
`bash scripts/dev/worktree-teardown.sh ../AdminHelper-<slug> <slug>` (reapt zuerst die VMs der Lane). Nie zwei
Bauer auf demselben Ledger. Temp-Verzeichnisse nur `mktemp -d -p <eigenes Verzeichnis>`, gelöscht nur mit vollem
Pfad, nie per Glob. Nach jedem Vorhaben `git worktree list` und `vm.py list` sauber.

## 9. Arbeitsweise
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

## 10. Konventionen
- **Conventional Commits** (`feat: fix: chore: refactor: docs: test: perf: tune:`), englisch, ein Commit je logischem
  Schritt; Release-Tags `vX.Y.Z`. Die Ledger-Datei `tasks/<slug>.md` wird im Task-Commit mitgestaged.
- **Toolchains nur nach `source .devenv.sh`** (gitignored; setzt PATH für `go`/`ruff` und `AH_TEST_DB`). Fehlt es, sind
  `go` und `ruff` unsichtbar — dann ist die Umgebung falsch, nicht der Code.
- **Formatierung und Lint sind Gates:** Rust `cargo fmt` + `clippy -D warnings`; TypeScript strict, kein `any`, ESLint +
  Prettier; Go `gofmt` + `go vet`; Python `ruff check` + `ruff format` (`ruff.toml` im Root).
- **SPDX-Header in jeder neuen Quelldatei** (`.py .go .rs .ts .svelte .js .mjs .sh`): `reuse annotate --copyright
  "Kevin Stenzel" --license GPL-3.0-or-later <datei>`. Drittanbieter stehen in `THIRD_PARTY_LICENSES.md`.
- **Kommentare nur fürs nicht-offensichtliche Warum** (versteckte Constraints, Invarianten, Workarounds für konkrete Bugs).
- **Doku im selben Commit** (DE + EN, README, DEVELOPMENT, CHANGELOG; Regeln in `.claude/rules/docs.md`).
- **Release-Kanäle** (von Hand): `beta` nach jedem grünen Wochenlauf, `rc` schneidet Kevin, `stable` frühestens 7 Tage
  nach dem RC ohne Fix und ohne Rückmeldung, `hotfix` als einziger Weg daran vorbei. Release-Bump: zuerst
  `.claude/rules/release.md` lesen.

## 11. Claude tut nie
Pushen auf `main` des öffentlichen Repos, taggen, publizieren, Ruleset oder Repo-Einstellungen ändern (das private
Roadmap-Repo pusht die Session nach jeder Änderung) · einen Harness-Pfad nebenbei ändern · eine Freigabe setzen ·
einen Haken ohne Summary-Zeile · einen Test abschalten oder schwächen, um grün zu werden · VMs außerhalb des Pools
`adminhelper-ci` anfassen oder Templates löschen · Homelab-Namen, Tokens oder Sicherheitsfunde in versionierte
Dateien schreiben · `env` ausgeben · in geteilten Temp-Verzeichnissen per Glob löschen · einen zweiten Bauer auf
dasselbe Ledger setzen.

## 12. Wo steht was
`.claude/agents/` die vier Prüfer · `.claude/skills/` `/feature-plan`, `/feature-build`, `/test`, `/vm`, `/roadmap` ·
`.claude/rules/` `testing.md`, `docs.md`, `release.md` (pfadgebunden) · `scripts/dev/` `task-close.sh`,
`worktree-setup.sh`, `roadmap.py`, `ledger.sh`, `review.sh sec`, Hooks · `docs/developer/` Architektur, CI/CD (DE+EN) ·
`DEVELOPMENT.md` Dev-Setup · `tasks/README.md` Ledger-Format · `tasks/private/` Roadmap und Funde · `CHANGELOG.md`.

## 13. Beim Kompaktieren
Nach `compact` oder `resume`: §3 erneut; offene `[ ]` des aktiven Ledgers aus der Datei; laufende Sub-Agenten und
tmux-Läufe anhand ihrer Dateien (`.ah-out/review/`, `rc`-Dateien) prüfen; nichts als erledigt behandeln, was nicht
`[x]` im Ledger ist.
