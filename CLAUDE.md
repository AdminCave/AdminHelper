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
Kevin startet jede Session und entscheidet: Reihenfolge und Inhalt der Roadmap, sichtbares Verhalten,
API-Verträge und Datenmigrationen, hingenommenes Restrisiko, Geld- und Zeitdeckel, Release, Tag, Ruleset,
Repo-Einstellungen, sudo, Tokens, Passwörter. Den Plan eines Vorhabens gibt die Session selbst frei (§4). Alles andere
innerhalb eines freigegebenen Vorhabens entscheidet die Session und berichtet danach; Fragen an Kevin gesammelt (ein
Block je Zug) und mit Empfehlung.

**Wer baut:** die Session selbst, Task für Task (`/feature-build`); Prüfer und gezielte Unterstützung sind Sub-Agenten
(§6). Zwei feste Sessions, gestartet mit `bash scripts/dev/start-session.sh kern|klein` (Kevin 2026-10-29): die
**Kern-Session** (Opus) baut SEC, REG, BUG mit Datenpfad, FEAT, Install/Update/Restore und Release; die
**Klein-Session** (Sonnet) baut die `klein-`-Züge (Doku-Drift, Kommentare, Test-Lücken, kleine REF und UI-Fehler).
Ein Architektur-Vorhaben über Komponenten startet Kevin als eigene Session (`start-session.sh arch R-nnnn`, Ledger
`arch-<…>`).
**Gebaut wird in Zügen:** ein Ledger nimmt alle Zeilen auf, die die Triage ihm zuordnet (Spalte `Ledger`, `roadmap.py
zuege`); einzeln fahren nur REG, ein BUG mit Nutzerwirkung und Architektur. Je Ledger und Worktree baut ein Akteur.
Jede Session nimmt nur Züge ihrer Stufe (`--stufe`), wechselt zwischen ihren Vorhaben, während Prüfer, CI oder VMs
laufen (Kriterien `/feature-plan` §4), und lässt Zeilen aus, deren Dateien ein offener Branch der anderen ändert
(`scripts/dev/overlap.sh`). Seriell bleibt, was sich Contract-Dateien, eine Test-DB oder eine Abhängigkeit teilt:
Parallelität darf keine Prüfung kosten.

**Merge:** Eigene PRs merged die Session selbst, auch zu `CLAUDE.md`, `.claude/`, `scripts/` (Kevin 2026-10-17), sobald
die Bedingungen aus `/feature-build` §4.7 erfüllt sind. Kevin merged fremde PRs und PRs, die
`.github/workflows/`, `scripts/install.sh`, `scripts/agent-install.sh` oder `scripts/update.sh` ändern (sie wirken
ohne Release auf Nutzer oder Secrets). Ist `main` rot, wird der letzte Merge revertiert, und bis `main` grün ist, wird
nichts gemergt; flaky heißt Rerun plus Roadmap-Zeile.

## 3. Vor jeder Arbeit
Der SessionStart-Hook druckt `AH-STATUS` (Checkout, Tag, Roadmap, Ledger, PRs, VMs). Fehlt er: `git status --short
--branch`, `git tag --sort=-v:refname | head -1`, „Als Nächstes“ in `tasks/private/ROADMAP.md`, `Status:` des
Ledgers. Eine `Warnung:`-Zeile, einmal, vor der Arbeit, genau dann: (1) ein Vorhaben soll starten, dessen `Hängt ab
von` nicht gemergt ist, oder eine `freigegeben`-Zeile höherer Klasse würde übersprungen; (2) ein Commit, Push, Tag
oder Merge direkt auf `main` steht bevor, oder ein Release ohne grünen Wochenlauf; (3) ein Feature-Branch würde
Harness-Pfade mitändern; (4) Kevin will planen, mergen oder rebasen, und der Haupt-Checkout ist nicht auf `main`
oder nicht sauber. Sonst keine Warnung und keine Bestätigungsfrage für Routine. Dazu: ist der Sammellauf fällig
(`/feature-build` §5)?

## 4. Lebenslauf eines Vorhabens
Roadmap-Zeile (Klasse SEC > REG > REL > BUG > FEAT > REF > IDEE; Status neu → geplant → freigegeben → aktiv → bereit →
pr → abgeschlossen) → `/feature-plan` (ein Zug: `--zug tasks/<slug>.md`) committet `docs/features/<slug>.md` und
`tasks/<slug>.md` (`Status: geplant`) als ersten Commit auf `feature/<slug>` → die Session gibt sofort selbst frei, wenn
Kevin die Zeile angenommen (`/roadmap triage`) oder das Vorhaben diktiert hat: `python3 scripts/dev/roadmap.py approve
R-nnnn` (Kevin 2026-10-21) → `/feature-build` (Kopf `aktiv`, Task für Task, Abschluss, PR, Merge) → `roadmap.py sync`.
Eine Entscheidung aus Kevins Bereich (§2), die weder die Roadmap-Zeile noch Kevins Wort (in der Session oder in der
Notiz der Zeile) trifft, stellt das Gate als Frage mit Empfehlung; ihre Task steht auf `[?]`, die übrigen baut die
Session; hängt jede Task an einer Frage, bleibt die Zeile `geplant`. Die Roadmap ist die einzige Reihenfolge-Wahrheit,
das Ledger die einzige Fortschritts-Wahrheit (Format `tasks/README.md`); keine Session sucht sich Arbeit außerhalb.
Harness-Pfade ändert eine Session nur auf Kevins Wort oder bei belegtem Produktschaden (roter Produkttest, falscher
Merge, Datenverlust, Leak), als eigene Task, nie nebenbei; Harness-Funde aus Reviews werden Roadmap-Zeilen
`zurückgestellt`.

## 5. Tests sind Beweis
Vor dem ersten Lauf eines Vorhabens `.claude/rules/testing.md` lesen (Ebenen, SKIP, VMs, Form der `Verify:`-Zeile).
- Je Task nur ihr `Verify:` mit gezieltem Testpfad (`bash scripts/dev/verify.sh <komp> --strict -- <test>`; es sourct
  `.devenv.sh` selbst, `run.sh` nicht). Komponenten-Suiten fährt die PR-CI, `run.sh quick --strict` lokal vor einem
  Release.
- Die Summary-Zeile (`N passed, M failed, K skipped`) ist die Evidenz und steht neben jedem `[x]`. Ein SKIP, ein
  fehlendes Werkzeug, ein abgebrochener Lauf oder ein Befehl ohne Ausgabe ist rot; erst rot, dann grün ist `flaky`.
- **Ausgaben:** `verify.sh` legt die volle Ausgabe unter `.ah-out/logs/` ab und zeigt den Digest (jeder Schritt, rote
  und übersprungene mit Auszug und Zeilenbereich, Summary, Exit, Logpfad); mehr nur gezielt (`sed -n <a>,<b>p`).
  Andere lange Ausgaben erst in eine Datei, dann `bash scripts/dev/log-digest.sh <log> <rc>` oder `grep`; nie durch
  `tail` gepipt, nie ein ganzes Log ins Modell.
- **Lange Läufe** (`/test`, Wochenlauf, Multibox, über zehn Minuten) in tmux ohne Modell:
  `( . ./.devenv.sh; … ) > log; echo $? > rc`; ein Hintergrund-Wächter wartet auf `rc`, keine Modellaufrufe zum Warten.
- Ein Server-Lauf zur Zeit je Test-DB (jeder Worktree hat seine, §8); Gegenproben nur in einem Probe-Worktree.
- **Heavy:** `Heavy:` im Ledger-Kopf (Zuordnung `/feature-plan` §3): `linux-full` im Sammellauf über `main`, den
  die Session selbst startet (`/feature-build` §5, Kevin 2026-10-15); `scenario` und `windows` vor dem Merge;
  Multibox nur nach Kevins Ja. VMs nur im Pool `adminhelper-ci` (klonen, baken, zerstören erlaubt, Kevin 2026-09-08),
  je Vorhaben in seiner Lane (`/vm`); danach `python3 scripts/vm/vm.py list`, eine geleakte VM ist ein Fehler.
- Neue Funktion ohne Test ist nicht fertig: Bug → erst der rote Test; Feature → Test dazu; Refactor → Suite grün
  vorher und nachher. Ausnahmen mit Begründung: triviale Getter, Framework-Wiring, reines Plattform-I/O, echte
  SSH/RDP/Ansible-Ausführung. Plattform-Code wird auf der Plattform verifiziert und das Ergebnis genannt.
- Nicht „fertig“ melden, solange CI läuft oder rot ist (PR und Merge-Commit, `/feature-build` §4.7–§4.8).

## 6. Rollen, Prüfer, Modelle (`.claude/agents/`)
| Rolle | Modell | Aufgabe |
|---|---|---|
| Kern-Session | Opus, medium (`start-session.sh kern`) | plant, implementiert, korrigiert, schließt Tasks, Doku, Übersetzung |
| Klein-Session | Sonnet, medium (`start-session.sh klein`) | dasselbe für die `klein-`-Züge |
| `reviewer` | Opus, high; Task-Prüfer der Klein-Session Sonnet (`model: "sonnet"`) | `task`: jede Task vor ihrem Commit (nicht bei `Review: am Ende`); `branch`: Abschlussprüfung von Code und Tests |
| `security` | Opus, high | dazu bei Risikopfad (`scripts/dev/review-risk.txt`, `review.sh risk`) |
| `advisor` | Opus, high; per Aufruf `xhigh` | schwierige Architektur, festgefahrene Fehlersuche, Sicherheitsfragen; implementiert nicht |

- Aufruf über das Agent-Werkzeug mit `subagent_type` und dem **absoluten Worktree-Pfad** (Sub-Agenten laufen im
  Arbeitsverzeichnis der Session: `git -C <wt>`, `bash <wt>/scripts/…`); Kevin tippt `@agent-<name>`. Den Auftrag
  trägt die Agent-Datei; die Session gibt nur Eingaben (Einsatzart, Slug, Task-ID, Diff-Pfade, Summary-Zeile,
  Scratch-Verzeichnis), keine Bewertung.
- **Ein Task-Prüfer je Zug** (Kevin 2026-10-29): die erste Task startet ihn, jede weitere setzt ihn fort (SendMessage,
  neue Task-ID), nach fünf Tasks oder einer eigenen Kompaktierung startet ein frischer. Eine reine Doku-Task
  (`Task-Review: am Ende`; `task-close.sh` lässt das nur für Doku-Dateien gelten) prüft erst die Abschlussprüfung.
  `security`, die Abschlussprüfung und `advisor` laufen in jeder Session auf Opus.
- **Mehr Effort nur gezielt:** Nach zwei ähnlichen Versuchen ohne Fortschritt fragt die Session den `advisor`, statt
  weiter zu probieren; `xhigh` nur für die schwersten Fragen, `max` nur mit Begründung in `## Entscheidungen`.
  Fehlende Infrastruktur (Werkzeug, VM, Netz, Rechte) ist kein Grund für mehr Modell oder Effort, sondern STOPP und
  Bericht. Modell und Effort der eigenen Session schaltet die Session nicht um; welche Session was baut, legt
  `start-session.sh` fest, ein Architektur-Vorhaben empfiehlt sie Kevin als `start-session.sh arch` (Kevin 2026-10-29).
- **Urteile:** `<wt>/.ah-out/review/<slug>/<id>.verdict.json` bzw. `branch.verdict.json` (Form in
  `.claude/agents/reviewer.md`). Kann ein Prüfer nicht schreiben, schreibt die Session das gemeldete JSON wörtlich
  (Kevin 2026-10-21).
- **Grenzen:** `request_changes` mit `blocker` oder belegtem `wichtig` → korrigieren, denselben Prüfer fortsetzen;
  höchstens zwei Runden, Nits blockieren nie. Turn-Limit → einmal fortsetzen („Ergebnis jetzt“); erneut oder 20 min
  ohne Wachstum der `output_file` (`stat -L -c %Y`, nie lesen) → stoppen, einmal enger neu starten (Probe-Worktree
  vorher weg), dann prüft die Session selbst: Ersatzprüfung im Commit-Body, kein `approve`.

## 7. Commit
Eine Task committet nur `bash <wt>/scripts/dev/task-close.sh <ledger> <id> --stage -m "<msg>"`: es fährt das
`Verify:`, prüft Reviewer-Urteil (vorhanden, jünger als jede gestagte Datei, `approve`) und Token-Scan, stagt genau die
`Dateien:`, setzt den Haken mit der Summary-Zeile, ein Commit für Code und Ledger (Exit-Codes im Skriptkopf, Reaktion
in `/feature-build` §3). `chore(plan)`- und `chore(ledger)`-Commits macht die Session selbst. Conventional Commits
englisch, einer je Task; die Git-Hooks fahren den Token-Scan, `--no-verify` gibt es nicht. Nie einen roten Stand
committen: ein Fix, der in zwei Versuchen nicht grün wird, wird zurückgenommen (`git -C <wt> restore --source=HEAD
--staged --worktree -- <datei>`), die Task `[~] verworfen: <Grund>`. `git checkout --`, `git restore` und `git stash`
löschen ungestagte Arbeit: nur nach `git add` oder wenn Verwerfen der Zweck ist.

## 8. Roadmap, Ledger, Worktrees
`tasks/private/` ist ein eigenes privates Repo (Sicherheitsfunde, Homelab-Namen), nie im öffentlichen Baum. Die Roadmap
schreibt nur `python3 scripts/dev/roadmap.py` (`add`, `status`, `approve`, `sync`, `lint`), nie ein Edit; „Als Nächstes“
erzeugt es bei jedem Schreiben aus den Zeilen (Kevin 2026-10-30), Handarbeit für Kevin ist eine `blockiert`-Zeile;
`zurückgestellt`/`blockiert` mit `--note` und Datum. Die Triage ordnet jede angenommene Zeile einem Zug zu
(`status R-nnnn geplant --ledger tasks/<zug>.md`, `klein-` für die Klein-Session; `/roadmap`). Jedes Vorhaben baut in
`git worktree add ../AdminHelper-<slug> feature/<slug>` plus `bash scripts/dev/worktree-setup.sh ../AdminHelper-<slug>
<slug>` (eigene Test-DB, Venv, `node_modules`, Sidecar, `.vm/lane`); erst danach den Ledger-Kopf im Worktree ändern (das
Ledger liegt nur auf dem Branch). Nach dem Merge `bash scripts/dev/worktree-teardown.sh ../AdminHelper-<slug> <slug>`
(reapt zuerst die VMs der Lane), dann `git worktree list` und `vm.py list` sauber. Temp-Verzeichnisse nur `mktemp -d -p
<eigenes Verzeichnis>`, gelöscht nur mit vollem Pfad, nie per Glob.

## 9. Arbeitsweise
Verhalte dich wie eine Senior-Engineerin mit 15+ Jahren in Rust, TypeScript, Python, Go und verteilten Systemen.

- **Erst denken, dann coden.** Nicht-triviale Änderung außerhalb eines Vorhabens: Plan mit Annahmen und Trade-offs,
  auf Bestätigung warten; den Plan eines Vorhabens gibt die Session nach dem Gate selbst frei (§4).
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
- **Toolchains nur nach `source .devenv.sh`** (gitignored; setzt PATH für `go` und `AH_TEST_DB`; `ruff`, `go` und
  `reuse` liegen zusätzlich als Links in `~/.local/bin`, DEVELOPMENT.md). Fehlt eins davon, ist die Umgebung falsch,
  nicht der Code.
- **Formatierung und Lint sind Gates** (Befehle in der Tabelle §1; TypeScript strict ohne `any`, ESLint + Prettier;
  `ruff.toml` im Root).
- **SPDX-Header in jeder neuen Quelldatei** (`.py .go .rs .ts .svelte .js .mjs .sh`): `reuse annotate --copyright
  "Kevin Stenzel" --license GPL-3.0-or-later <datei>`. Drittanbieter stehen in `THIRD_PARTY_LICENSES.md`.
- **Kommentare nur fürs nicht-offensichtliche Warum** (versteckte Constraints, Invarianten, Workarounds für konkrete Bugs).
- **Doku** (DE + EN, README, DEVELOPMENT, CHANGELOG über `changelog.d/<slug>.md`): in der Task oder gebündelt in einer
  Doku-Task desselben Ledgers, vor der Abschlussprüfung vollständig; Regeln in `.claude/rules/docs.md` (vor Plan,
  Doku-Task und Abschluss lesen).
- **Release** (Bump, Kanäle `beta`/`stable`/`hotfix`, Signatur): zuerst `.claude/rules/release.md` lesen.

## 11. Claude tut nie
Pushen auf `main` des öffentlichen Repos, taggen, publizieren, Ruleset oder Repo-Einstellungen ändern (das private
Roadmap-Repo pusht die Session nach jeder Änderung) · einen Harness-Pfad nebenbei ändern · eine Zeile freigeben, die
Kevin nicht angenommen oder diktiert hat oder die keinen committeten Plan hat · einen Haken ohne Summary-Zeile · ein
Prüfurteil erfinden oder umschreiben · einen Test abschalten oder schwächen, um grün zu werden · VMs außerhalb des
Pools `adminhelper-ci` anfassen oder Templates löschen · Homelab-Namen, Tokens oder Sicherheitsfunde in versionierte
Dateien schreiben · `env` ausgeben · in geteilten Temp-Verzeichnissen per Glob löschen · einen zweiten Akteur auf
dasselbe Ledger oder denselben Worktree setzen.

## 12. Wo steht was
`.claude/agents/` (`reviewer`, `security`, `advisor`) · `.claude/skills/` (`/feature-plan`, `/feature-build`, `/test`,
`/vm`, `/roadmap`) · `.claude/rules/` (`testing.md`, `docs.md`, `release.md`; pfadgebunden, für Worktree-Pfade
ausdrücklich lesen) · `.claude/settings.json` (Modell, Effort, Rechte, Hooks) · `scripts/dev/` (`task-close.sh`,
`verify.sh`, `log-digest.sh`, `review.sh sec|risk|pr-body|final`, `ledger.sh`, `roadmap.py`, `overlap.sh`,
`start-session.sh`, Worktree-Skripte, Hooks) · `changelog.d/` · `docs/developer/` (Architektur, CI/CD, DE+EN) ·
`DEVELOPMENT.md` · `tasks/README.md` (Ledger-Format) · `tasks/private/` · `CHANGELOG.md`.

## 13. Unterbrechung, Kompaktieren, Übergabe
Nach `compact`, `resume` oder in einer neuen Session: §3 erneut; offene `[ ]`/`[?]` und `## Entscheidungen` aus der
Ledger-Datei, nicht aus der Erinnerung; `git -C <wt> status` und `log`; laufende Sub-Agenten und tmux-Läufe anhand
ihrer Dateien (`.ah-out/review/`, `rc`-Dateien); erledigt ist nur, was `[x]` im Ledger ist. Zusammenhängende Tasks
baut eine Session am Stück. Vor einem fachlichen Wechsel oder bei vollem Kontext übergibt sie: laufende Task
committet oder zurückgenommen, Entscheidungen in `## Entscheidungen`, Fragen als `[?]`, dann höchstens fünf Zeilen
Übergabe mit Belegen (Vorhaben, Worktree, letzter Commit, nächste Task, laufende Läufe mit `rc`-Pfad) und der
Vorschlag an Kevin für `/compact` oder eine neue Session.
