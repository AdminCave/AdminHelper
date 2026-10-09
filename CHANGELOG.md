# Changelog

Alle nennenswerten Aenderungen an diesem Projekt werden hier dokumentiert.

Format orientiert sich an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/),
Versionierung nach [Semantic Versioning](https://semver.org/lang/de/).

## [Unreleased]

### Added

- **`Assertion-Aenderung:` im Ledger (R-0206):** eine Task kann eine absichtlich geaenderte
  Assertion in einem bleibenden Test oder Test-Helfer ankuendigen (`<datei>::<test> — <Grund>`).
  `review.sh diff-scan` laesst dann genau diese Aenderung durch, wenn der Test mindestens so viele
  Assertions hinzubekommt, wie er verliert; `task-close.sh` sperrt eine Ankuendigung, die erst mit
  der Task selbst kommt, und `ledger.sh lint` prueft die Form. Als Ledger gelten nur noch
  `tasks/*.md` ohne `tasks/README.md` und `tasks/templates/` — das schliesst auch einen aelteren
  Weg an `Test-Loeschung:` vorbei.

- **commit-msg-Hook (R-0197):** `scripts/dev/hooks/commit-msg` faehrt `review.sh sec --message`
  und sperrt einen Token in der Commit-Nachricht schon beim Commit. Dazu meldet `sec` die Zeile
  nach „\ No newline at end of file“ richtig und erkennt weitere Formen eines Proxmox-Tokens
  (PBS mit Doppelpunkt, URL-kodiert, Secret hinter einem Schluesselnamen; R-0194, R-0196), und
  `ledger.sh lint` meldet auch Huelle und Ausgabe eines Werkzeugaufrufs als Rest (R-0195).

- **`review.sh sec` erkennt Token-Muster (R-0183):** eine hinzugefuegte Zeile mit einem
  Proxmox-API-Token (`USER@REALM!TOKENID=UUID`), einem GitHub-Token (`ghp_`, `gho_`, `ghu_`,
  `ghs_`, `ghr_`, `github_pat_`) oder einem `sk-ant-`-Schluessel sperrt den Commit, den Push und
  den CI-Job „Public repo guard"; genannt wird nur Datei:Zeile, nie der Inhalt. Ueber eine
  Spanne (pre-push, CI) prueft es auch die Commit-Nachrichten und nennt dann nur den Commit.
  Eine Mindestlaenge und ein Rumpf aus hoechstens zwei verschiedenen Zeichen (`xxxx…`) lassen
  die Platzhalter in Code, Doku und Tests durch.

- **`ledger.sh lint` meldet Werkzeug-Reste (R-0165):** Reste eines Werkzeugaufrufs, die ein
  planender Agent in Ledger oder Spec hinterliess, sind ein Lint-Fehler mit Datei:Zeile.

- **Der Worker (Stufe 7a, R-0010, R-0108, R-0164, R-0167, R-0170):** `scripts/dev/ledger-loop.sh`
  baut freigegebene Ledger Task fuer Task als `adminhelper-runner` in dessen Klon, jedes Ledger in
  seiner Lane; Kevin startet ihn in tmux mit einer expliziten Ledger-Liste. Je Task eine frische
  Bau-Session (`claude -p` mit dem Text von `/build-task`, nur die Runner-Settings, `dontAsk`,
  Deckel fuer Zeit, Turns und Budget); geschlossen wird ausserhalb der Session mit
  `task-close.sh --review auto --round <n>`. Der Loop zaehlt die Runden selbst, raeumt nach einem
  Abbruch auf (`aborted.diff`, restore, neue Dateien einzeln), setzt `[?]` mit dem Grund und das
  Ledger auf `blockiert`, haelt an Lauf-Deckeln (`--max-hours`, `--max-tasks`, `--max-budget-usd`
  samt Reviewer-Kosten, `--max-ready`) und am Nutzungslimit an und endet mit einer Stopp-Klasse
  und `summary-<datum>.md`. Ein fertiges Ledger uebergibt er als PR-Text (`review.sh pr-body`) und
  Git-Bundle; Push und PR bleiben Kevins. Neu sind `/build-task`
  (`.claude/skills/build-task/SKILL.md`) und `scripts/dev/scratch.sh`; die Runner-Settings
  verbieten Edits unter `tasks/` und erlauben einen Scratch-Ordner nur ueber `scratch.sh`;
  `task-close.sh` nimmt im autonomen Lauf weder ein eigenes Verdict noch ein frueheres approve an
  und druckt die Kosten des Reviewers; das Red Team prueft die Grenzen der Bau-Session;
  `ledger-loop.sh status` und die Worker-Zeile im AH-STATUS zeigen den Stand. Anleitung:
  `AUTONOMOUS.md`, „Der Worker", und `DEVELOPMENT.md`, „Der Worker".
- **CI-Sperre fuer Privates (R-0123):** Der neue CI-Job „Public repo guard (review.sh sec)" faehrt
  `scripts/dev/review.sh sec --range` ueber jeden Commit eines Pull Requests bzw. Pushs auf `main` —
  dieselbe Sperre wie die lokalen Commit-Hooks (privater Plan, SEC-Ledger, Dedup-Key eines
  Sicherheitsfunds, `.devenv.sh`, `settings.local.json`), fuer alles, was an ihnen vorbeigeht. `sec`
  liest eine Spanne Commit fuer Commit (eine Datei, die kommt und wieder geht, zaehlt), einen Merge nur
  nach dem, was er selbst bringt; der Job braucht kein Secret und nennt nur Pfad bzw. Datei:Zeile.
  Lokal faehrt der neue Hook `scripts/dev/hooks/pre-push` dieselbe Pruefung ueber jeden Commit, den
  ein Push nach draussen bringt, und bricht den Push bei einem Treffer ab. Kevins Handgriff: den
  Check im Ruleset fuer `main` als Pflicht eintragen. Anleitung: `docs/developer/cicd.html`,
  `DEVELOPMENT.md` „pre-commit-Hook".

- **Der Reviewer als eigener Prozess (Stufe 6b, R-0155, R-0147, R-0150):**
  `task-close.sh --review auto` startet den Task-Reviewer selbst: der Runner faehrt die Probe
  (`review-probe.sh`), `scripts/dev/review-run.sh` startet `claude -p` mit dem Reviewer aus
  `scripts/dev/review-agent.md`, ohne Projekt- und Benutzer-Settings, nur mit eigenen Settings
  (`scripts/dev/review-settings.json`: lesend, im Pilot ohne Mutanten, der harness-guard als
  Hook, fail-closed) und dem Schema `scripts/dev/review-output.schema.json`,
  Modell und Deckel nach `review.sh risk`. Das Verdict (Schema-Version 2) liegt unter
  `.ah-out/review/<slug>/` und wird ueber `check-verdict --task` an Task und Tree gebunden;
  hoechstens zwei Runden, ein Prozess ohne Verdict ist Exit 74 ohne Rueckfall. Neu sind
  `review.sh log` (jede Runde mit Kosten, Turns und Dauer, als Tabelle mit Summe) und
  `scripts/dev/review-cli-probe.sh` (misst die Aufrufform gegen die CLI). Opt-in fuer den Pilot
  per Ledger-Kopf `Review: auto`; Anleitung: `DEVELOPMENT.md`, „Reviewer als Prozess".

- **Review-Pruefer ohne Modell (Stufe 6a, R-0009):** `scripts/dev/review.sh` kann jetzt
  `risk` (Risikopfad im Diff nach `scripts/dev/review-risk.txt`, daraus das Reviewer-Modell),
  `docs-pairs` (eine Doku-Seite ohne ihre andere Sprache), `contracts` (Pruefungen je
  geaendertem Pfad nach `scripts/dev/review-contracts.txt`: ein Komponenten-Test oder ein
  Wertpaar wie die FRP-Pins), `check-verdict` (ein Reviewer-Urteil gegen
  `scripts/dev/review-verdict.schema.json` und den Tree-Hash) und `pr-body` (der PR-Text als
  Checkliste aus dem Ledger). Neu ist `scripts/dev/review-probe.sh`: in einer eigenen Worktree
  prueft es, ob der neue Test ohne die Aenderung rot waere, und mit `--mutate`, ob ein Mutant die
  Tests uebersteht. `task-close.sh` faehrt `docs-pairs` und `contracts` bei jedem Abschluss und
  prueft ein Verdict ueber `check-verdict`. Anleitung: `DEVELOPMENT.md`, „Review-Pruefer
  (Ebene 0)".

- **AH-STATUS nennt die geplanten Workflows (R-0120):** Der SessionStart-Hook
  `scripts/dev/hooks/session-status.sh` druckt je Workflow mit `schedule:` eine Zeile
  `Geplant: <name> <Tag> (<n> d): <conclusion>` fuer den neuesten abgeschlossenen Lauf auf `main`
  und warnt bei einem roten Lauf (mit `gh run view <id> --log-failed`) oder einem Lauf aelter als
  8 Tage. Bisher sah zwischen zwei Wochenlaeufen keine Session, dass der Dependency Audit rot war.
  Ohne `gh` steht dort `?`, ohne Warnung. Anleitung: `DEVELOPMENT.md` „Session-Status-Hook".
- **CI prueft den Lock-Stand der Images (R-0115):** Die Test-Jobs installieren das lose
  `requirements.in`, die Images den gehashten Lock — der lose Stand laeuft dem Lock voraus, und
  ein Bruch wie der von fastapi 0.138 im Auth-Gate-Test zeigte sich nur dort. Neu fahren die Jobs
  `python-lock-server`, `python-lock-monitoring` und `python-lock-ca-issuer` die Suiten auf dem
  Python der Images gegen den Lock (`--require-hashes`, danach die Dev-Dependencies), und
  `scripts/dev/lock-pins.py` macht den Job rot, sobald ein Pin nicht in der Lock-Version
  installiert ist. Ein Lockstep-Test haelt die Python-Version jedes Jobs beim `FROM` seines
  Dockerfiles. Anleitung: `DEVELOPMENT.md` „Python-Dependencies & Lockfiles".
- **Harness-Schutz fuer /tmp und Commits (R-0098, R-0102):** Der PreToolUse-Waechter
  `scripts/dev/hooks/harness-guard.sh` verweigert in jedem Modus, auch mit gesetztem Kill-Switch,
  das Loeschen per Glob in einem geteilten Temp-Verzeichnis (`/tmp`, `/var/tmp`, `/dev/shm`,
  `$TMPDIR` und die Session-Verzeichnisse von Claude Code darin; auch ueber `find … -delete`,
  Schleifen und Pipes) — ein Reviewer hatte mit `rm -rf /tmp/tmp.*` die Fixtures aller
  Sessions geloescht. Neu ist `scripts/dev/hooks/pre-commit`: er faehrt `review.sh sec --staged`
  vor jedem Commit, nicht mehr nur in `task-close.sh`; scharf wird er je Klon mit
  `git config core.hooksPath scripts/dev/hooks`, `harness.sh status` zeigt den Stand,
  `runner-setup.sh` setzt ihn im Runner-Klon, und der Waechter verweigert seine Umgehung.
  Shell-Schluesselwoerter wie `do` und `then` verdecken vor dem Waechter keinen Befehl mehr.
  `verify.sh` gibt jedem Lauf ein eigenes `TMPDIR`, Reviewer arbeiten in einem eigenen
  Verzeichnis. Anleitung: `DEVELOPMENT.md` „Harness-Schutz und Kill-Switch".
- **Lane-Isolation (Harness):** eine Lane (`scripts/dev/lane.sh new <slug>`) hat jetzt, was sie
  zum Bauen braucht, und teilt mit dem Haupt-Checkout nichts mehr, woran zwei Laeufe einander
  stoeren: eine eigene `.devenv.sh` mit eigener Test-Datenbank `adminhelper_test_<slug>` und
  eigenem Venv `~/.cache/ah-venv-<slug>`, Links auf das frpc-Sidecar und auf die
  Komponenten-Venvs mit dem CI-`ruff`. `new` bricht ab, wenn der Plan nicht committet ist (auf
  `feature/<slug>`, sonst auf `main`). In `scripts/tests/run.sh` stehen `server-pytest` und
  `schemathesis` je Nutzer ueber alle seine Checkouts Schlange (`flock` auf
  `~/.cache/adminhelper-py.lock`; `AH_PY_LOCK_WAIT`, Default 3600 s, danach SKIP mit Grund;
  `AH_PY_LOCK=0` schaltet ab) — zwei Server-Suiten auf einer Box hatten einander Tabellen und
  Speicher genommen, bis zum OOM-Killer. `lane.sh done` loescht Datenbank und Venv mit und
  verweigert, solange noch ein Prozess in der Lane arbeitet. Hermetisch getestet in
  `scripts/tests/lane_test.sh`. Anleitung: `AUTONOMOUS.md` „Parallel-Betrieb",
  `DEVELOPMENT.md` „Python-Tests lokal".
- **Runner-Isolation und deterministische Gates (Harness Stufe 4):** Ein `[x]` und ein Commit
  entstehen nur noch in `scripts/dev/task-close.sh` — ausserhalb der Modell-Session: es verlangt,
  dass jede Datei der Task vollstaendig gestaged ist, faehrt das `Verify:` der Task als
  `verify.sh <komponente> --strict`, prueft mit `scripts/dev/review.sh` den Diff auf
  stummgeschaltete Tests (`diff-scan`), auf Pfade ausserhalb der Task (`scope`) und auf das, was
  nie ins oeffentliche Repo darf (`sec`), und schreibt die Summary-Zeile des Laufs als `Evidenz:`
  in den Ledger. Geschrieben wird der Ledger von `scripts/dev/ledger.sh` (`start`, `mark-done`,
  `mark-skip`, `mark-question`, `set-files`, `status`, `new-task`, `lint`) aus einer Vorlage
  `tasks/templates/task.md`. Dazu der Harness-Schutz: `scripts/dev/harness-paths.txt` nennt die
  Dateien, die die Regeln bestimmen, ein PreToolUse-Hook verweigert im autonomen Lauf jede
  Aenderung daran (auch ueber `sed -i`, `tee`, Umleitung, `cp`/`mv`, `bash -c`), und
  `scripts/dev/harness.sh off|on|status` ist der Kill-Switch. Neu ausserdem der Unix-User
  `adminhelper-runner` (`scripts/dev/runner-setup.sh`, `runner-env.sh`, `runner-settings.json`,
  `runner-redteam.sh`): eigener Klon ohne Push-Recht, eigene Test-Datenbank, eigenes Abo- und
  Proxmox-Token, `dontAsk` mit Deny-Liste — und ein Red-Team-Skript, das das beweist. Anleitung:
  `DEVELOPMENT.md`, Abschnitte „Task schliessen: `ledger.sh` und `task-close.sh`",
  „Harness-Schutz und Kill-Switch" und
  „Runner-User `adminhelper-runner`".
- **Generatoren statt Beispiele in den Testsuiten (Harness Stufe 8b):** Jeder Python-Dienst
  wird gegen seine eigene OpenAPI gefuzzt (Schemathesis, eigener `run.sh`-Schritt
  `schemathesis` und einem eigenen CI-Job ueber alle drei Dienste, Beispielzahl
  5 lokal und im PR-CI, 100 im Wochenlauf ueber `AH_SCHEMATHESIS_EXAMPLES`),
  einmal je Authentifizierungs-Kontext. Dazu drei
  Hypothesis-Ziele — FRP-TOML-Round-Trip, VictoriaMetrics-Line-Protocol und der
  SSRF-Guard gegen ein Orakel aus dem `ipaddress`-Modul —, ein Postgres-Concurrency-
  Test fuer `execute_check` (der `with_for_update` ist auf SQLite ein No-op und war
  damit nie ausgefuehrt) und pytest-alembic fuer beide Migrationsketten, je mit einem
  Seed-Test, der die Daten-Migration mit Daten prueft statt auf einer leeren Tabelle.
  Ausschluesse stehen mit Grund und Wiedervorlage in `schemathesis_exclude.toml`, und
  eine `operation_id`, die das Schema nicht kennt, ist ein Fehler statt eines stillen
  No-ops. Neu: `requirements-dev.txt` je Dienst als einzige Wahrheit fuer Test-Deps.
- **Ephemere Proxmox-VMs ohne externes Binary (Harness Stufe 2a):** `scripts/vm/vm.py` least,
  verwaltet und zerstoert die VMs, auf denen die schweren Suites laufen — Python-3-Standard-
  bibliothek, keine Abhaengigkeit, nur die REST-API. Verben: `doctor clone wait ssh sync run
  pull snap rollback delsnap destroy reap list bake`. Linked Clones kosten ~2 s statt ~11 min
  Vollklon, Snapshot und Rollback je ein bis drei Sekunden. Der Zustand liegt als **Tag** auf
  dem Hypervisor (`ah`, `role-`, `lane-`, `sc-`, `ttl-`, `tpl-`), nicht in einer lokalen Datei:
  jeder Checkout sieht jede Lease samt Frist, jedes Verb ausser `list`/`doctor` raeumt am Ende
  die abgelaufenen VMs der eigenen Lane weg (kein Timer, kein Cron), und bei einer VM **ohne**
  `ah`-Tag verweigert `vm.py` jedes zerstoerende Verb, damit ein Tippfehler keine Homelab-VM
  frisst. Exit-Codes trennen „der Test ist rot" (1) von „die
  Infrastruktur hat nein gesagt" (74). `bake` baut aus dem Basis-Cloud-Image ein neues
  Template. Dazu `scripts/vm/lib.sh` als Shell-Seite und zwei hermetische Suiten: `vm.py`
  gegen aufgezeichnete Proxmox-Antworten (`scripts/vm/tests/`), `lib.sh` gegen einen
  Temp-Zustand (`scripts/tests/lib_vm_test.sh`); beide haengen an `verify.sh scripts --strict`
  und an CI. Anleitung: `DEVELOPMENT.md`, Abschnitt „VMs mit vm.py".

- **Paritaets- und Contract-Gates (Harness Stufe 8a):** Die APIs von Server und Monitoring
  haben jetzt einen eingecheckten OpenAPI-Snapshot (`apps/<dienst>/tests/openapi.snapshot.json`),
  den ein Test bei jeder Aenderung einfordert — neu aufgezeichnet wird er mit
  `pytest tests/test_openapi_snapshot.py --update-openapi-snapshot`, im selben Commit wie die
  API-Aenderung. Der neue CI-Job `openapi-compat` vergleicht den Snapshot des Basis-Branch per
  `oasdiff breaking --fail-on ERR` mit dem des PR: neue Pfade und Felder sind gruen, ein
  entfernter Pfad, ein entferntes Response-Feld oder ein neu verpflichtendes Request-Feld
  sind rot. `oasdiff` kommt als gepinnter Release-Tarball (v1.32.0, SHA-256 im Workflow), nicht
  per `go install` — jede Version ab v1.24.0 verlangt `go 1.26`, die Workflows pinnen aber Go
  1.25 mit `GOTOOLCHAIN=local`. Dazu Guards, die zwei getrennt gepflegte Wahrheiten aneinander
  pinnen: Proxy-Allowlist gegen die Monitoring-Routen, die mTLS-Identity-Header ueber Gateway,
  Server und CA-Issuer, der Enrollment-Token-Hash zwischen Server und CA-Issuer, und die
  Gleichheit der beiden SSRF-Guards. Dazu `scripts/dev/doc-smoke.py` (CI-Step im Job `ops-scripts`): jedes `<code>`-Fragment in
  `docs/**/*.html`, das einen Repo-Pfad nennt, muss eine existierende Datei benennen — zwei
  veraltete Pfade in der Entwickler-Doku sind damit schon aufgefallen und korrigiert.
  Und `sync-from-web.sh --check` (CI-Step im Job `desktop-ui`) haelt die vier API-Typen zusammen,
  die Web- und Desktop-Frontend doppelt fuehren.
  Details: `docs/developer/cicd.html` (DE + EN), Abschnitt „Paritaets- und Contract-Gates".

### Security

- **Server-gebundene API-Keys schreiben nur fuer ihren Server (Server):** `POST /api/connections` und
  `PUT /api/connections/{id}` nehmen von einem an einen Server gebundenen API-Key nur eine `serverId`
  gleich diesem Server an; eine andere oder eine leere `serverId` ergibt `403` „Kein Zugriff auf diesen
  Server". Ein solcher Key darf Verbindungen also nur fuer seinen eigenen Server anlegen oder dorthin
  verschieben. Ungebundene Keys und Benutzer sind nicht betroffen. Eine Test-Matrix
  (`tests/test_api_key_server_binding.py`) haelt fest, was jede Key-Art auf jeder Route darf, die einen
  API-Key annimmt.

- **npm-Abhaengigkeiten (dev) ohne Audit-Befund (R-0038):** `vitest` und die `@vitest/*`-Pakete
  stehen in `apps/web` und `apps/desktop/ui` auf 4.1.11 (GHSA-82fw-gwwq-j7x9; Ranges `^4.1.11`).
  Die Lockfiles dort und in `apps/desktop/e2e` heben `brace-expansion` (GHSA-qhr7-859c-m2p7,
  GHSA-6j4f-fj2g-mc7p; high), `undici` (GHSA-rfgv-xxqx-mfg5, GHSA-w293-vg96-wgc3; high),
  `devalue` (GHSA-9rgm-9g3h-6x36) und in e2e `ip-address` (GHSA-j6r3-76f7-8jcv,
  GHSA-h3mg-xc3c-68pw) auf gefixte Versionen, alles `dev`-Abhaengigkeiten. Vorher meldete
  `npm audit --audit-level=high`, mit dem der woechentliche Dependency Audit gated, in allen drei
  Verzeichnissen zwei high-Funde; jetzt ist `--audit-level=moderate` ueberall ohne Befund. Die
  Lockfiles von web und desktop-ui schreibt einmalig `npx -y npm@11 … --package-lock-only`, weil
  npm 10.9.8 dabei in arborist abbricht; `npm ci` laeuft mit npm 10 unveraendert.

- **SSRF-Guard (Server und Monitoring):** Die DNS-Aufloesung des Guards lief ueber einen
  geteilten Vier-Worker-Pool. Vier haengende Aufloesungen belegten ihn vollstaendig, jeder
  weitere `is_private_url`-Aufruf lief in seine 5-Sekunden-Frist und meldete fail-closed
  „privat". Durch den Guard laufen nur HTTP-Checks und Alert-Webhooks — im Monitoring hiess
  das also: ein toter Nameserver, und keiner von beiden erreichte mehr ein Ziel. Aufgeloest
  wird jetzt je Aufruf in einem eigenen Daemon-Thread mit derselben Frist, gedeckelt auf 64
  gleichzeitige Aufloesungen; ueber dem Deckel wird sofort fail-closed abgelehnt und
  hoechstens einmal pro Minute gewarnt. Eine leere Adressliste gilt jetzt ebenfalls als
  „privat". Nach aussen aendert sich nichts, ausser dass haengende Aufloesungen einander
  nicht mehr blockieren und der Dienst trotz haengender Aufloesung beendet werden kann.

- **Desktop-Backend:** `rustls` 0.23.40 → 0.23.45 (RUSTSEC-2026-0285, TLS-1.3-Handshake-
  Nachrichten wurden ueber Encryption-Level-Grenzen hinweg akzeptiert; medium) samt
  `rustls-webpki` 0.103.13 → 0.103.15 — nur der Lockfile-Stand, keine Verhaltensaenderung.
  Gefunden vom gepinnten `cargo audit` des Audit-Sweeps. Cargo 1.96 haengt beim Update
  zusaetzlich fuenf `windows-sys`-Kanten (errno, os_pipe, rustix, tempfile, winapi-util)
  auf bereits gelockte Versionen um — Windows-only, vom CI-Job `rust-windows` gebaut.

- **anyio 4.13.0 → 4.14.2** in server, monitoring und ca-issuer (gehashte Locks neu generiert):
  behebt CVE-2026-63374 und CVE-2026-64847. Vom woechentlichen Dependency-Audit (`pip-audit`)
  erkannt. Die Locks von server und monitoring ziehen dabei `sqlalchemy[asyncio]` nach, faellig
  seit der `.in`-Aenderung (gleiche Version, gleiche Hashes). `pytest` gegen die exakten neuen
  Locks unter Python 3.12 gruen — server 968, monitoring 599, ca-issuer 74 —, `pip-audit` ohne Befund.

- **pyjwt 2.13.0 → 2.14.0** im Server (gehashte Lock neu generiert, Untergrenze in `requirements.in`
  auf `>=2.14.0`): behebt CVE-2026-101917, CVE-2026-102265 bis -102269 und CVE-2026-102271 bis -102274.
  Vom Dependency-Audit (`pip-audit`) erkannt. Der Changelog 2.13.0 → 2.14.0 enthaelt keine inkompatible Aenderung; `pytest`
  gegen den exakten neuen Lock unter Python 3.12 gruen (server 682), `pip-audit` ohne Befund.

- **pyjwt 2.14.0 → 2.15.1** im Server (gehashte Lock neu generiert, Untergrenze in `requirements.in`
  auf `>=2.15.0`, R-0193): behebt PYSEC-2026-4141 (behoben ab 2.15.0). Vom Dependency-Audit (`pip-audit`)
  erkannt. Der Changelog 2.14.0 → 2.15.1 enthaelt keine inkompatible Aenderung fuer `jwt.encode`/`jwt.decode`
  mit HS256: 2.15.0 meldet zu tief verschachtelte Payloads als `DecodeError` (der Server faengt
  `InvalidTokenError`), 2.15.1 nimmt ein angehaengtes `=`-Padding in JWS-Segmenten an (gesperrte Tokens
  erkennt der Server an der `jti`, nicht am Token-String). `pytest` gegen den exakten neuen Lock unter
  Python 3.12 gruen (server 824), `pip-audit` ohne Befund.

- **e2e-Lockfile: `basic-ftp` 5.3.1 → 6.2.2, `braces` entfernt (R-0198):** zwei `overrides` in
  `apps/desktop/e2e/package.json`, beide unter WebdriverIO und vom Dependency-Audit (`npm audit`, Schritt „Audit e2e
  lockfile") erkannt; nur `dev`-Abhaengigkeiten, nichts davon wird ausgeliefert.
  - `basic-ftp` auf `^6.2.1` (transitiv ueber `@wdio/utils` → `@puppeteer/browsers` → `proxy-agent` →
    `pac-proxy-agent` → `get-uri`, das `^5.3.1` verlangt): behebt GHSA-c475-qrg2-pj4r (high, CPU-Last beim Parsen von
    Verzeichnislisten), 6.2.2 zusaetzlich GHSA-5rfr-xx34-2xxv. Der Changelog 5.3.1 → 6.2.2 aendert keine API, die
    `get-uri` nutzt; der Bruch in 6.0.0 (kein getrennter Transfer-Host ohne `allowSeparateTransferHost`) betrifft nur
    FTP-Downloads, die der Testbaum nicht macht.
  - `chokidar` unter `mocha` auf `^4.0.3`: fuer `braces` (GHSA-vfj7-8cjw-p6xm, high, bis 3.0.3, ohne gepatchte
    Version) gibt es keinen Fix, es hing nur an mochas `chokidar` 3.6.0. Mit chokidar 4, das schon im Baum liegt, faellt
    es samt elf weiteren Paketen weg. Grenze: Der Watch-Modus der mocha-CLI verliert die Glob-Unterstuetzung; die
    E2E-Tests nutzen ihn nicht, WebdriverIO ruft mocha programmatisch.
  - `npm audit --audit-level=high` in `apps/desktop/e2e` vorher 18 high, nachher 0; `apps/web` und `apps/desktop/ui`
    unveraendert ohne Befund.

- **`source-map-js` 1.2.1 → 1.2.2 in den Lockfiles von `apps/web` und `apps/desktop/ui` (R-0199):** behebt GHSA-68fv-2mgg-jv7q
  (CVE-2026-93749, high, Event-Loop-Blockade durch indizierte Source-Map-Abschnitte). Vom Dependency-Audit (`npm audit`)
  erkannt. Reiner Lockfile-Bump (`npm update source-map-js --package-lock-only`), `package.json` unveraendert: alle
  Abnehmer (`postcss`, `css-tree`, `magicast`) erlauben `^1.2.1`. Der Changelog 1.2.1 → 1.2.2 enthaelt nur diesen Fix
  und einen CSP-Fix fuer den Browser. Nur Dev-Werkzeug, nicht im ausgelieferten Bundle; `npm audit --audit-level=high`
  vorher je 1 high, nachher 0 in beiden Projekten und in `apps/desktop/e2e`.

### Fixed

- **Desktop: Passwort fuer den Browser-Export (R-0219):** Die Einstellungen liessen ein Passwort ab 8
  Zeichen zu, der Export selbst verlangt 12; ein Passwort mit 8 bis 11 Zeichen endete in der
  allgemeinen Meldung „angemeldet und Server erreichbar?“. Die Einstellungen verlangen jetzt die
  dokumentierten 12 Zeichen, gezaehlt wie im Backend, und sagen das.
- **SSRF-Guard nennt den Grund (R-0045):** Der HTTP-Check und der Alert-Webhook des Monitorings sowie die
  Hook-Funktionen `http_get`/`http_post` des Servers melden ein Ziel, dessen Host nicht aufloest
  (DNS-Fehler oder Zeitlimit), jetzt als solches (`could not be resolved … rejected by the SSRF guard`)
  statt als private/reservierte Adresse. Abgelehnt wird es weiter, ohne Request; die Meldung fuer
  private Ziele bleibt unveraendert.
- **Server-Datenbank-Sessions in UTC (R-0209):** Jede Verbindung des Servers setzt ihre Session
  auf `UTC`, unabhaengig von der Zeitzone des Postgres-Clusters (der Stack startet ihn mit
  `TZ=Europe/Berlin`) und von einem `PGTZ` in der Umgebung. Postgres rechnete einen Zeitwert mit
  Offset bisher in die Session-Zeitzone um, bevor er in eine Spalte ohne Zeitzone ging; diese Spalten
  halten aber UTC. Bereits gespeicherte Werte bleiben, wie sie sind (keine Migration), die
  API-Ausgabe auch.
- **Desktop: Tunnel-Hinweis ohne Identitaet (R-0203):** Startet ein Tunnel ohne mTLS-Zertifikat,
  verweist die Meldung jetzt auf die Registrierung des Geraets mit einem Einmal-Token vom Admin
  statt auf eine Anmeldung am Server — seit ADR 0003 enrollt der Login nicht.
- **Zeitstempel der Server-API in UTC mit `Z` (R-0064):** Die Antworten schreiben ihre Zeitstempel
  als RFC 3339 in UTC mit `Z`. Bisher trugen die meisten keinen Offset — auch die vier Felder, fuer
  die das OpenAPI `format: date-time` verspricht (`created_at` der API-Keys, `created_at`, `last_run`
  und `next_run` der Hooks; die uebrigen sind `string` oder untypisiert) —, und Audit und
  Notifications den Offset der Datenbank-Session; Web und Desktop lasen Werte ohne Offset als
  lokale Zeit und zeigten sie um den Abstand zu UTC verschoben. Das OpenAPI bleibt unveraendert,
  die Datenbank auch (keine Migration); die
  Schemathesis-Ausnahmen der API-Key-Routen sind gefallen. **Hinweis fuer Hook-Skripte:** `last_run`
  und `triggered_at` im Kontext eines Hook-Skripts tragen jetzt beide `Z` (`last_run` etwa
  `2026-10-05T12:00:00Z` statt `2026-10-05T12:00:00`, `triggered_at` `…Z` statt `…+00:00`); ein
  Skript, das die Werte als String vergleicht oder selbst zerlegt, muss das `Z` erwarten.
  `datetime.fromisoformat` liest alle drei Formen. Doku: API-Referenz, „Zeitstempel",
  und Hooks.
- **Server: Zeitstempel in den tz-naiven Spalten durchgehend als naive UTC (Konvention F7):** Vier Schreibstellen
  (`enrollment/service.py`, zweimal `provisioning/router.py`, `core/auth.py`) gaben zeitzonenbehaftete Werte an
  `DateTime`-Spalten ohne Zeitzone; Postgres legte sie dann in der Zeitzone der Datenbank-Session ab statt in UTC wie
  die uebrigen tz-naiven Spalten. Sie schreiben jetzt ueber `utcnow_naive()` aus `app/core/time.py`, und der Abgleich
  in `cleanup_expired_blacklist` liest mit derselben Konvention, mit 12 h Spielraum fuer Zeilen aus der Zeit davor (sie
  tragen die Ortszeit der Session). Ein neuer Test prueft die Spalten unter einer Session-Zeitzone ungleich UTC.

- **Red Team und Waechter unabhaengig vom geprueften Nutzer (R-0156, R-0158 bis R-0163):**
  Die Proben von `scripts/dev/runner-redteam.sh` auf git, Proxmox, D-Bus und Settings fuehren
  keinen Code und keine ausfuehrbare Konfiguration des Runners mehr aus (die Modellproben starten
  bewusst seine CLI, nach Pruefsumme und Settings, die sie bei einem FAIL nicht aufhalten). Die Push-Proben pushen aus einem eigenen Repository ohne Hooks und ohne
  git-Konfiguration des Nutzers an die URLs des Klons und lesen seine Konfiguration auf
  Credential-Helper, Extra-Header und URL-Umschreibungen; Aenderungen am Klon zeigt die ctime statt
  `git status`. Probe 4 misst den Proxmox-Token direkt an der API (`curl -q`, Token ueber stdin)
  gegen ein Ziel, das `runner-setup.sh` root-eigen als `pve-target.env` ablegt, statt `vm.py` aus dem
  Klon zu starten. Die D-Bus-Probe prueft den Socket statt ein `busctl` ohne `XDG_RUNTIME_DIR`, die
  Runner-Settings werden byte-genau mit der geprueften Kopie verglichen, und ein unbekanntes
  Argument endet mit Exit 2 statt im vollen Lauf. `scripts/dev/hooks/harness-guard.sh` zaehlt die
  Ausgabe-Optionen von git als Schreibziel (`--output` jedes Aufrufs, `archive -o`,
  `format-patch -o`, `bundle create`, `grep -O`), und der Runner-Hook ist fail-closed: fehlt der
  Waechter oder haengt er, sperrt der Hook mit Exit 2. Anleitung: `DEVELOPMENT.md` „Runner-User" (Red Team) und
  „Harness-Schutz und Kill-Switch".

- **FRP: Generate-Routen nur mit nutzbaren Tunneln (Server, R-0128):** `visitor-toml`, `visitor-bundle` und
  `frpc-toml` lassen STCP-Tunnel ohne Secret weg, bevor sie pruefen, ob ein Tunnel da ist. Bleibt keiner uebrig,
  antworten sie mit demselben `404` wie ohne Tunnel, und `bulk-zip` schreibt fuer einen solchen Nutzer keine
  `visitors/<user>.toml`. Das `auth.token` von frps steht damit nur in einer Datei, die auch einen Tunnel
  enthaelt. Doku: `docs/developer/api-reference.html`.
- **FRP: Secret und Visitor-Port nur an STCP-Tunneln (Server, R-0129):** Ein HTTPS-Tunnel speichert weder
  `secret_key` noch `visitor_port`; `POST` verwirft mitgeschickte Werte, und der Wechsel per `PUT` auf HTTPS
  loescht beide. Der Wechsel zurueck auf STCP erzeugt ein neues Secret und vergibt einen freien Port, wenn der
  gespeicherte inzwischen einem anderen Tunnel gehoert. Das heilt auch aeltere Zeilen ohne Datenmigration;
  bisher endete dieser Rueckwechsel mit `409`. Doku: `docs/developer/api-reference.html`,
  `docs/admin/frp-tunnel.html`.
- **FRP: bulk-zip nur mit nutzbaren Tunneln (Server, R-0148):** `bulk-zip` laesst STCP-Tunnel ohne Secret
  einmal vorab weg. Ein Server ohne nutzbaren Tunnel bekommt keine `clients/<server>/frpc.toml` mehr (bisher eine
  mit `auth.token` und ohne Proxy), ohne nutzbaren STCP-Tunnel gibt es keine `visitor.toml`; im Extremfall
  enthaelt der ZIP nur `frps.toml`. Das ist dieselbe Regel wie der `404` der Einzelrouten. Je Tunnel ohne Secret
  steht eine Warnung im Log statt einer je Server, Nutzer und Generator-Aufruf. Doku:
  `docs/developer/api-reference.html`.
- **SSE: ein Worker verpasste kurz nach dem Start ein Refresh-Signal (Server, R-0149):** `subscribe()` schickt
  das Abo an Redis nur ab; ein `publish` vor der Bestaetigung ging verloren, Pub/Sub puffert nicht.
  `stream_hub.start()` liest jetzt die Bestaetigung (hoechstens 5 s), bevor es den Reader startet und
  „subscribed" meldet. Bleibt sie aus, warnt es und startet den Reader trotzdem; die Clients fallen wie bisher
  auf Polling zurueck. Das behebt auch den sporadisch roten `test_redis_fanout_only_to_targeted_user`.
- **Verbindungen: nur bekannte Felder gehen in Spalten (Server, R-0136):** Beim Anlegen, Aendern und
  Importieren uebernimmt der Server nur die Felder der API (`name`, `kind`, `host`, …, in camelCase) in
  die Spalten einer Verbindung. Alles andere bleibt Zusatzinformation in `extra_data`, auch ein
  Schluessel, der wie eine Spalte heisst (`extra_data`, `created_at`). Beim Lesen gewinnen die bekannten
  Felder gegen Eintraege aus `extra_data`; ein `extra_data`, das kein JSON-Objekt ist (aeltere Zeilen),
  wird mit einer Warnung im Log ausgelassen, statt die Liste mit `500` abzubrechen.
- **OpenAPI: exakte BIGINT-Grenze (Server):** Das veroeffentlichte Schema (`/openapi.json`) traegt die
  Obergrenze der BIGINT-Felder im Request-Body als Ganzzahl `9223372036854775807`. FastAPI tippt
  `maximum` als Float, dort stand bisher `9.223372036854776e+18`, 193 ueber der echten Grenze. Die
  Pruefung zur Laufzeit war davon nicht betroffen. `app/core/openapi.py` schreibt die Grenze in das
  erzeugte Schema zurueck; der Snapshot aendert genau diese Zahl, oasdiff meldet keine Aenderung.
- **FRP: U+007F in Konfigurationswerten (Server):** Die Felder, die der Server in die erzeugten
  FRP-TOML-Dateien schreibt (FRP-Server-Config, Tunnel, Servername), lehnen neben den anderen
  Steuerzeichen jetzt auch U+007F (DEL) mit 422 ab. TOML verbietet das Zeichen in einem
  String; eine `frps.toml` damit konnte frps nicht lesen.
- **Web-Panel: F5 waehrend eine Liste laedt (R-0107):** `apps/web/src/lib/api/client.ts` gibt
  bei einem 2xx, dessen Body sich nicht lesen laesst (Reload bricht die Uebertragung ab, oder
  kein JSON), nicht mehr still `null` zurueck, sondern wirft `ApiError(status, 'Invalid response
  body')`. Die Seiten Benutzer, API-Keys, Hooks und Audit lasen `.length` auf dem `null` und
  endeten im `pageerror` „Cannot read properties of null (reading 'length')", den der Live-Smoke
  fand; jetzt zeigen sie ihren Fehler-Toast. 204 und ein gueltiges JSON-`null` bleiben `null`.
  `docs/developer/webui.html` (DE+EN) sagt dazu, dass der Access-Token nur im Speicher liegt.
- **Wartungsfenster mit Offset am Kalenderrand (Monitoring):** `POST /maintenance` und
  `PUT /maintenance/{id}` antworten auf ein `starts_at`/`ends_at` mit Zeitzonen-Offset, das in
  UTC umgerechnet vor dem Jahr 1 oder nach dem Jahr 9999 laege (etwa
  `0001-01-01T00:00:00+00:01`), mit 422 und Feldbezug statt mit 500. Die Umrechnung lief als
  ungefangener `OverflowError` durch. Ein naives Datum im Jahr 1 bleibt gueltig.
- **`restore.sh` auf einem frischen Host:** das Skript wartet jetzt ueber TCP auf Postgres
  (`pg_isready -h 127.0.0.1`), ueber denselben Weg, den der DB-Restore danach nimmt. Auf einem
  neuen Volume lauscht der Init-Server des offiziellen Images nur auf dem Unix-Socket; die
  Socket-Probe meldete ihn bereit, und `psql`/`createdb` scheiterten dann mit
  `Connection refused` — je nach Timing brach die Wiederherstellung mittendrin ab. Dieselbe
  Warteschleife in `scripts/tests/sse_push_e2e.sh` ist mit korrigiert.
- **422 statt 500 an den Raendern der API (Server und Monitoring):** Eingaben, die erst in der
  Datenbankschicht scheiterten, werden jetzt am Rand geprueft. Betroffen waren alle drei
  Eingangswege: die int-Pfad- und Query-Parameter (`user_id`, `key_id`, `offset`), die
  Integer-Felder und die Id-Liste im Request-Body (FRP-Ports, `ids` von
  `POST /api/notifications/read`) und Textfelder, in denen ein NUL-Byte stand
  (`POST /api/enrollment/token/for`, die Filter von `GET /api/audit`, die Skript- und
  Namensfelder von `/api/hooks`, `server_ids` von `POST /api/users`, die Textfelder von
  `POST /api/internal/events`, der Name von `POST /api/api-keys`) — jeder davon lief bis
  hierher als ungefangener
  `NumericValueOutOfRange` bzw. `DataError` durch und kam als HTTP 500 zurueck. Die Schranken
  stehen als `minimum`/`maximum` im OpenAPI-Schema und stammen je Feld aus dem Spaltentyp des
  Modells; fuer Clients, die gueltige Werte senden, aendert sich nichts.
- **Tag-Validator und Fremdschluessel am Rand (Server):** ein `tags`-Wert vom falschen Typ
  (dict, int, bool, Liste mit Nicht-Strings) ergibt eine Validierungsmeldung statt
  `AttributeError` bzw. `TypeError` — das betraf sechs Routen. Ein nackter String wird dabei
  jetzt abgelehnt: `tags: "ops"` ergab bisher still die drei Ein-Zeichen-Tags `o`, `p`, `s`
  und ergibt nun 422. Und eine unbekannte `serverId` beim Anlegen, Aendern oder Importieren
  einer Verbindung ergibt 422 mit Feldbezug statt einer durchlaufenden `ForeignKeyViolation`.
- **Schemathesis-Ausschluesse, Bilanz (Server 27 -> 29, Monitoring 4 -> 1):** im Server sind
  zwei Eintraege hinfaellig und entfernt, acht gelten nur noch fuer einen einzelnen Check statt
  fuer die ganze Route — dort laeuft die 500er-Pruefung wieder mit, genau die Pruefung, die
  diese Klasse gefunden hat. Einer (`GET /api/frp/tunnels`) ist umgekehrt verbreitert worden,
  weil dort ein NUL-Pfad zum bestehenden Grund dazukam (im naechsten Punkt wieder verengt).
  Vier sind neu, alle vier fuer die Catch-all-Routen des Monitoring-Proxys, und das ist kein
  Produktfehler, sondern eine Eigenschaft der Testfixture. Im Monitoring fallen die drei
  `offset`-Eintraege weg.
  Die NUL-Klasse, die dieser Lauf nur dort behoben hatte, wo er sie zeigte, ist inzwischen
  flaechig geschlossen (naechster Punkt).
- **NUL-Byte am Rand, flaechig (Server und Monitoring):** ein NUL-Byte (`U+0000`) in einer Eingabe
  ergibt jetzt 422 mit Feldbezug statt HTTP 500 — gleich auf welchem Weg es kommt. Im Pfad und im
  Query-String prueft eine Middleware vor dem Routing (`loc` `["path"]` bzw. `["query", <name>]`),
  in einem Request-Body jedes Request-Schema ueber eine gemeinsame Basisklasse bis in
  verschachtelte Listen und Objekte (`loc` ist der Weg bis zum Wert), und im Monitoring ebenso
  der Agent-Report, dessen Body kein Modell ist. Postgres speichert kein `0x00` in einem Textwert;
  bisher starb jede solche Eingabe im Treiber, ausser an den Feldern, die ein Fuzz-Lauf gezeigt
  hatte. Die Regel ist bewusst flaechig: auch dort, wo ein NUL nie eine Textspalte erreichte —
  Passwoerter, Tokens, Tags und Zusatzfelder einer Verbindung, unbekannte Felder und Query-Namen —
  antwortet die API jetzt 422 statt 200, 201 oder 401. Das OpenAPI-Schema aendert sich nicht.
  Schemathesis-Ausschluesse, gegen den vorigen Stand ausgezaehlt: Server 29 -> 23 — sechs
  NUL-Ausschluesse entfernt, zwei von der ganzen Route auf einen Check verengt
  (`GET /api/frp/tunnels`, dessen Verbreiterung aus dem vorigen Punkt damit zurueckgenommen ist,
  und `POST /api/connections`); Monitoring unveraendert 1.

- **Capstone, Visitor-Rolle:** der frpc-Visitor startete mit `sudo sh -c … &` und hielt damit stdout/stderr
  der ssh-Sitzung — `vm.py run` (ohne pty) sah nie EOF und lief 50 Minuten in den Timeout, obwohl die
  Pruefung acht Sekunden braucht. Jetzt per `setsid` mit `</dev/null` gestartet und am Ende beendet; ein
  hermetischer Guard (`box_scripts_guard_test.sh`) verbietet solche Hintergrundstarts in allen Box-Skripten.

- **VM-Hygiene (R-0048/R-0049):** `.devenv.sh` reist nicht mehr per `vm.py sync` auf die Box
  und damit auch nicht mehr in ein Template — auf der Box bleibt `AH_REQUIRED` ungesetzt und die
  Box-Regel macht alle Schritte eines schweren Layers zur Pflicht. `iter.sh` verlaengert die
  Warm-Box mit der Frist, mit der sie gewaermt wurde (`desktop_ttl` in `.vm/warm.env`), statt
  mit dem eigenen 8h-Default: eine 20-Minuten-Box wurde bisher beim ersten Lauf still zur Nacht-Box.

- **Konfigurations-Stellhebel, die nichts bewirkt haben (Harness Stufe 8a, T6):** `DB_POOL_SIZE` und
  `DB_MAX_OVERFLOW` waren in `.env.example` samt Rechenregel dokumentiert, wurden aber von keinem
  Compose-Dienst durchgereicht — wer sie setzte, aenderte nichts. Sie gehen jetzt an `server` und
  `scheduler`. `CA_FRPS_EXTRA_SANS` (eigene SANs fuers frps-Leaf) war umgekehrt im Compose vorhanden,
  aber nirgends dokumentiert. Entfernt wurden drei tote Keys: `DOMAIN` und `EXTRA_SANS` beim Dienst
  `server` (nichts in `apps/server` liest sie; sie gehoeren dem ca-issuer und dem Gateway) sowie
  `PGPASSWORD` bei `server` und `scheduler` (deren Entrypoints rufen nur `pg_isready`, das sich nicht
  authentifiziert — nur das Monitoring nutzt `psql`). Ein neuer Test haelt die drei Beschreibungen
  ab jetzt zusammen.

- **Wochenlauf (Harness Stufe 3b):** Auf der Box sind unter `--strict` alle Schritte der
  schweren Layer Pflicht (`AH_REQUIRED` ungesetzt ⇒ Layer-Menge; `crabbox_iter.sh` reicht ein
  gesetztes `AH_REQUIRED` durch, `heavy.sh` setzt die Dev-Box-Menge zurueck) — ein Self-SKIP
  von `upgrade-path` oder einer GUI-Suite ist kein gruener Lauf mehr, sondern UNVERIFIED. Der
  Capstone-Report nennt die Ursache, wenn crabbox das Setup einer Rolle abgebrochen hat
  (Folgefehler `infra` je Rolle statt Produktfehler); die Rollen-Setups upgraden die Fat-Box
  nicht mehr (`--no-upgrade`, Zeitgrenzen 3000 s). Ein roter `audit.yml` erzeugt eine
  Roadmap-Zeile je roter Phase statt je Lauf; `history.csv` ist RFC-4180-gequotet; der
  Migrations-Smoke-Teardown droppt ohne `WITH (FORCE)`.

### Removed

- **crabbox (Harness Stufe 2b):** Das externe Binary und alles, was nur fuer es da war —
  `.crabbox.yaml`, der Workflow `crabbox.yml`, die Agent-Skill `.agents/skills/crabbox/`,
  `scripts/tests/crabbox_lib.sh` und die Wrapper `crabbox_warm|iter|reap|bake|multibox.sh`.
  Die beiden lokalen Verzeichnisse `.crabbox/` und `.crabbox-out/` bleiben vorerst
  gitignoriert und vom Sync ausgenommen: `.crabbox/captures` enthaelt unredigierte
  Fehler-Bundles, und dieses Repo ist oeffentlich. Loeschen — dann koennen die zwei
  Eintraege mit.

- **Desktop: Tauri-Command `enroll_device` (R-0040):** das Enrollment ueber die Login-Session hatte keinen
  Aufrufer in der UI; die App enrollt seit ADR 0003 mit einem Einmal-Token (`enroll_with_token`). Entfernt sind
  der Command, `enrollment::enroll` und der Zweig in `mint_token`, der nur dafuer ein Access-Token anforderte; der
  Browser-Export (`export_browser_p12`) nach dem Login bleibt. Der IPC-Inventar-Test fuehrt keinen Command ohne
  UI-Aufrufer mehr. `docs/developer` (DE+EN) nennt fuer den Desktop jetzt den Einmal-Token statt „nach Login".

### Changed

- **Doku-Smoke prueft auch die Namen in Grossbuchstaben als Gate (R-0044):** `scripts/dev/doc-smoke.py --env`
  zaehlt einen Namen, den die Doku als `<code>` nennt, als bekannt, wenn ihn ausser den drei `config.py` und
  `.env.example` irgendeine getrackte Datei ausserhalb von `docs/`, `CHANGELOG.md` und `tasks/` traegt — Agent-
  Einstellungen, CI-Secrets, Zustaende und HTTP-Methoden sind also kein Fund mehr (vorher 138 Funde ueber 48
  Namen). Der einzige echte Fund, `FRP_DOMAIN` in `docs/en/admin/frp-tunnel.html`, ist korrigiert: gemeint ist der
  Subdomain-Host der FRP-Server-Konfiguration. Der CI-Job `ops-scripts` faehrt jetzt
  `doc-smoke.py --paths --env --strict`.

- **Der Public repo guard prueft auch mit der Logik der Basis (R-0174):** Der CI-Job
  „Public repo guard (review.sh sec)" faehrt `review.sh sec --range` zuerst mit dem `review.sh` der
  Basis (ein Worktree von `origin/<base>`, beim Push der Stand vor ihm), dann mit dem des geaenderten
  Stands; beide muessen gruen sein. Ein Pull Request, der `sec` aendert, wird so mit der Logik
  geprueft, die vor ihm galt; eine Basis ohne `sec --range` macht den Job rot. Einen Fehlalarm der
  Basis-Logik nimmt ein Admin-Merge. Anleitung: `docs/developer/cicd.html`, `DEVELOPMENT.md`.
- **CI-Laeufe auf Pushes nach `main` laufen zu Ende (R-0174):** Die `concurrency` von `ci.yml` gibt
  jedem Push eine eigene Gruppe je Commit und bricht nur noch Pull-Request-Laeufe ab; ein spaeterer
  Push bricht den Lauf davor weder ab noch verdraengt er ihn, solange er wartet. Nur dieser Lauf liest
  die Commits eines Pushs (`before..sha`). Anleitung: `docs/developer/cicd.html`.
- **`review.sh sec --range` sagt, wenn die Spanne leer ist (R-0174):** Ohne einen Commit in der
  Spanne meldet `sec` jetzt `sec: empty span (<range>) — nothing read` statt „sec: clean" (Exit
  weiter 0, ein Push ohne neue Commits ist keine Verweigerung). Der CI-Job „Public repo guard" macht
  daraus einen Hinweis, etwa bei einem `workflow_dispatch` auf `main`.
- **`task-close.sh` prueft billig zuerst (Stufe 6b, R-0150):** `diff-scan`, `scope`,
  `docs-pairs` und `sec` laufen vor der Suite, `contracts` danach; ein einseitiger Doku-Abschluss
  kostet keinen Suite-Lauf mehr. Aendert sich der Index waehrend des Laufs, bricht der Abschluss
  mit Exit 2 ab. `pr-body` prueft Verdict-Dateien ueber `check-verdict` (schemawidrig heisst
  „ungueltig").
- **Red Team root-eigen, in fester Umgebung (R-0152):** `scripts/dev/runner-setup.sh` installiert
  `runner-redteam.sh` mit `runner-env.sh`, `runner-settings.json` und `runner-claude.version` nach
  `/usr/local/lib/adminhelper-dev/` (root) und haelt die sha256 der Runner-CLI in
  `/var/lib/adminhelper-dev/runner-claude.sha256` fest; `--remove` nimmt beides mit. Das Red Team
  laeuft von dort (`sudo -u adminhelper-runner bash /usr/local/lib/adminhelper-dev/runner-redteam.sh`),
  startet sich unter `env -i` mit festem `PATH` neu, sourct keine Datei des Runners
  (`AH_RUNNER_ENV_NO_DEVENV=1` in `runner-env.sh`), nimmt das Soll des Pin-Checks aus seinem eigenen
  Verzeichnis und meldet `FAIL`, wenn es von woanders laeuft, wenn `runner-env.sh` es veraendert
  oder wenn die CLI nicht die festgehaltene ist. Nach einem CLI-Wechsel braucht es deshalb erneut
  `sudo bash scripts/dev/runner-setup.sh`. Anleitung: `DEVELOPMENT.md` „Runner-User".

- **Python-Sperre ueber Nutzergrenzen, Runner-Setup klont nur neu (R-0080, R-0077):**
  `scripts/tests/run.sh` nimmt fuer `server-pytest` und `schemathesis` die geteilte Sperre
  `/var/lib/adminhelper-dev/py.lock`, sobald ihr Verzeichnis existiert (`AH_PY_LOCK_FILE` geht
  vor, der Pfad ist ueber `AH_PY_LOCK_SHARED` aenderbar); ohne es bleibt es bei
  `~/.cache/adminhelper-py.lock` je Nutzer. So warten Kevins Laeufe und die des Runners
  aufeinander. Eine nur lesbare Sperrdatei sperrt weiter, eine fehlende oder nicht oeffenbare ist
  ein SKIP mit Grund (unter `--strict` rot), und die Halter-Zeile erscheint nur mit druckbaren
  Zeichen. `scripts/dev/runner-setup.sh` legt die Datei
  an (`--remove` nimmt sie mit) und klont nur noch in einen Pfad, den es nicht gibt: ein
  vorhandenes Verzeichnis ohne `.git` bricht mit einem Satz ab, der Klon entsteht in einem
  Temp-Verzeichnis in `/srv` und wird danach umbenannt. Ein bestehender Runner bekommt die Sperre mit einem erneuten
  `sudo bash scripts/dev/runner-setup.sh`. Das Red Team prueft die Sperre mit
  (`runner-redteam.sh --py-lock <pfad>`: vorhanden, root gehoerend, Verzeichnis fuer den Runner
  nicht schreibbar, nehmbar) und meldet `FAIL`, solange das Setup nicht erneut lief. Anleitung:
  `DEVELOPMENT.md` „Runner-User".

- **diff-scan: weitere Skip-Muster und Rueckgaben mit Wert (R-0132):** `review.sh diff-scan`
  meldet jetzt auch `fit(`, `fdescribe(`, `.runIf(`, `.fails(`, `test.fail(`, `.fixme(` (also <!-- review: ok nennt die Muster -->
  `test.describe.fixme(`), `self.skipTest(` und `pytest.importorskip(` in einer hinzugefuegten Zeile <!-- review: ok nennt die Muster -->
  sowie `return None`, `return undefined;` und `return Ok(());` in einem Test — bisher nur ein
  nacktes `return`, und in einer Datei mit CRLF-Zeilen nicht einmal das. `assert.fail(`,
  `sys.exit(` und `profit(` bleiben frei, ebenso ein `return` in einer im Test verschachtelten
  Funktion (Stub, Callback) und eines, nach dem kein Code des Tests mehr folgt; die Meldung heisst
  `early return in a test`.

- **diff-scan: entfernte Assertions zaehlen nur, wo Tests stehen (R-0130):** Eine geloeschte Zeile
  mit `assert`, `assert_…!`, `expect(` oder Go-`t.Fatal…` ist nur noch ein Fund in einer
  Testdatei (`tests/`, `e2e/`, `test_*.py`, `*_test.{py,go,sh}`, `*.test.*`, `*.spec.*`) oder in
  der Spanne eines Tests (inline `#[test]` unter `src/`); eine Import-Zeile nie. Bisher meldete
  diff-scan auch ein entferntes `.expect("…")` im Rust-Produktivcode, einen entfernten Import
  `use pretty_assertions::assert_eq;` und `review.sh` selbst, ohne Ausweg (eine geloeschte Zeile
  kann kein `review: ok` tragen).

- **Waechter: wer ein Verzeichnis mit Harness-Pfaden wegnimmt, nimmt sie mit (R-0127):**
  `scripts/dev/hooks/harness-guard.sh` verweigert im autonomen Lauf auch `rm -rf .claude`,
  `rm -rf scripts/dev/hooks`, `chmod -R -x scripts/dev/hooks`, `mv scripts/dev /tmp/x`, einen
  Glob, der Harness-Pfade im Baum trifft (`rm -rf scripts/dev/*`; `rm -f *.log` bleibt frei), die
  Repo-Wurzel (`rm -rf ./*`) und ein
  loeschendes `find` von dort aus — bisher zaehlte nur der Harness-Pfad selbst. Die Regel gilt
  nur fuer wegnehmende Kommandos (`rm`, `rmdir`, `shred`, `unlink`, `chmod`/`chown`/`chgrp`,
  `mv`-Quelle, `find … -delete`); interaktiv bleibt es eine Warnung. Dazu erkennt der Waechter
  `[^x]`, Klammer-Listen (`/{tmp,x}/…`) und `cd` in einen Glob mit woertlichem Operand
  (R-0125), und ein Kommentar verdeckt keine Folgezeilen mehr (`# … <<X`, ein Apostroph im
  Kommentar; R-0139). Anleitung: `DEVELOPMENT.md` „Harness-Schutz und Kill-Switch".

- **Schema-Fuzzing im PR deterministisch (R-0063):** Der Schritt `schemathesis` (lokal `run.sh` und der
  CI-Job „Schema fuzzing") faehrt mit `AH_SCHEMATHESIS_EXAMPLES=0` nur noch die explizite Phase
  (Schema-Beispiele und Coverage-Faelle): fuer denselben Baum dieselben Faelle, ein roter Lauf ist
  lokal nachstellbar. Der Wochenlauf behaelt alle Phasen mit 100 Beispielen. `hypothesis==6.168.3`
  und `schemathesis==4.29.0` sind exakt gepinnt. `scripts/tests/schemathesis_determinism.sh` prueft,
  ob zwei Laeufe je Test dieselben Faelle schicken. Die Server-Suite ersetzt den Proxy-Client zum
  Monitoring durch einen Stub; die fuenf Ausschluesse der Proxy-Routen sind entfallen. Doku:
  `DEVELOPMENT.md` „Generatoren", `docs/developer/cicd.html`.
- **Monitoring: Obergrenzen fuer ganzzahlige Eingaben (R-0063):** `cooldown_minutes` (Alert-Regeln und
  Vorlagen) und `consecutive_fails` (Checks und Vorlagen) enden bei der INTEGER-Grenze `2147483647`;
  `duration_minutes` (1–1440) und `weekdays` (0–6) der Wartungsfenster tragen ihre Grenzen jetzt auch
  im Schema, bisher galten sie nur im Validator (ein `once`-Fenster, das `duration_minutes` bisher
  ignorierte, darf damit keinen Wert ausserhalb 1–1440 mehr senden). Groessere Werte beantwortet der
  Dienst mit `422`, statt sie an die Datenbank zu geben. Je Dienst prueft ein Test, dass
  jeder Integer-Eingang des veroeffentlichten Schemas ein `maximum` hat.
- **Import-422 in der deklarierten Form (Server):** `POST /api/connections/import` meldet abgelehnte
  Eintraege jetzt wie jede andere 422 der API: `detail` ist eine Liste mit einem Eintrag je Fehler,
  `loc` = `["body", "connections", <index>, <feld>]`, in Import-Reihenfolge. Bisher stand dort
  `detail.message` und `detail.rejected[]` mit `index`, `name` und `errors`; Skripte, die das lesen,
  muessen auf `detail[]` umstellen. Alles oder nichts bleibt. Auch ein Eintrag mit snake_case-Feld
  (etwa `server_id`) wird so gemeldet. Der Schemathesis-Ausschluss fuer die Route faellt. Doku:
  `docs/developer/api-reference.html`.
- **Verbindungen nur in camelCase (Server):** `POST` und `PUT /api/connections` lehnen die
  snake_case-Schreibweisen `server_id`, `key_path`, `trust_cert` und `last_used` mit `422` ab (je
  Feld ein Eintrag in `detail`, Hinweis auf den camelCase-Namen). Jede dieser Spalten wird damit nur
  ueber ihren API-Namen geschrieben und durchlaeuft dessen Pruefungen. Alle Clients im Repo senden
  camelCase; andere Zusatzfelder bleiben erlaubt.
- **Verify-Zeile, wie sie dasteht (R-0104):** `scripts/dev/verify.sh` nimmt mehrere Komponenten
  und faehrt sie als einen Lauf `run.sh quick --only <a> <b>` (Argumente nach `--` nur fuer eine
  Komponente, `all` nur allein). `scripts/dev/task-close.sh` liest die Komponenten aus einer
  `Verify:`-Zeile in der Form `verify.sh <a> [<b> …] --strict` oder `run.sh <layer> --strict
  --only <a> [<b> …]` und faehrt genau diese — bisher lief fuer `--only web desktop-e2e` nur
  `web`. Fehlt die `Komponente:` der Task in der Liste, ist das Exit 2. Die `Evidenz:`-Zeile nennt
  die gelaufenen Komponenten (`run.sh[quick] web desktop-e2e: …`).

- **diff-scan erkennt mehr stummgeschaltete Tests (R-0082):** `scripts/dev/review.sh diff-scan`
  wertet jetzt auch geloeschte Rust-Makros `assert_…!` und in Go-Tests `t.Fatal…`/`t.Error…`
  als entfernte Assertion (ausserhalb einer `*_test.go` bleibt `err.Error()` frei), kennt die
  Skip-, xfail-, todo- und only-Muster von vitest/jest, Playwright, pytest, Rust (auch
  `#[ignore = "…"]`) und Go (`t.SkipNow()`), und meldet ein hinzugefuegtes nacktes `return` <!-- review: ok nennt die Muster -->
  innerhalb eines Tests (Python, Go, Rust, TS/JS). Der Ausweg bleibt `review: ok <grund>` auf
  der Zeile. Anleitung: `DEVELOPMENT.md` „Task schliessen".

- **Commit-Hooks auch bei merge, cherry-pick, revert, rebase und git am (R-0110):** Neben
  `scripts/dev/hooks/pre-commit` fahren jetzt `prepare-commit-msg` (cherry-pick, revert, jeder
  Commit eines rebase mit dem Standard-Backend, Merge-Commit), `pre-merge-commit` (vor einem
  Merge-Commit) und `pre-applypatch` (`git am`, `git rebase --apply`)
  `review.sh sec --staged` — bisher kam eine private Datei aus einem anderen Branch ueber diese
  Wege ungeprueft in den Verlauf. Dass der Sequencer `prepare-commit-msg` ruft, ist nicht
  dokumentiert, aber mit git 2.47.3 gemessen und im Test festgehalten. `harness.sh status`
  prueft alle vier Hooks und nennt einen fehlenden; der Waechter verweigert `git am -n` wie
  `git commit -n`; `chmod`, `chown` und `chgrp` auf einen
  Harness-Pfad zaehlen fuer den Waechter als Schreiben. Wirksam je Worktree mit dem Branch,
  der die Hooks traegt. Anleitung: `DEVELOPMENT.md` „Harness-Schutz und Kill-Switch".

- **Temp-Waechter erkennt mehr Formen (R-0109):** `scripts/dev/hooks/harness-guard.sh`
  verweigert jetzt auch einen Glob **ueber** einer Temp-Wurzel in jeder Tiefe
  (`/t*/claude-1000/*`, `cd /t* && rm -rf claude-1000/*`) — bisher zaehlte nur ein Treffer auf
  der Wurzel oder direkt darin, so dass ein solcher Glob die Verzeichnisse aller Sessions
  erreichte. Dazu erkennt der Parser einen Operanden nach `--`, `|&` als Pipe, `);` als zwei
  Operatoren (`for d in $(ls -d /tmp/tmp.*); do rm …`), `xargs sh -c 'rm …'` wie `xargs rm`
  und `grep -l`/`-L` als Lister. Frei bleiben die Aufraeumer im eigenen Verzeichnis; die
  verbleibenden Grenzen (Prozess-Substitution, `mapfile`, Laufzeit-Pfade ohne Glob,
  `cat … | xargs rm`) stehen in `DEVELOPMENT.md` „Harness-Schutz und Kill-Switch".
- **Audit: Logout nur, wenn eine Sitzung endet (Server, R-0105):** `POST /api/auth/logout` schreibt
  `auth.logout` nur noch, wenn der Aufruf einen Token gesperrt hat (Bearer oder Refresh-Token aus Body
  oder Cookie). Ein Logout ohne Token, mit ungueltigem oder abgelaufenem Token oder mit denselben
  Tokens ein zweites Mal hinterlaesst keinen Eintrag; Antwort (`200`) und Cookie-Loeschung bleiben
  gleich. Ein Logout nur mit Cookie traegt jetzt den Benutzernamen. Doku:
  `docs/developer/api-reference.html`, `docs/admin/betrieb.html`.
- **FRP: leere STCP-Secrets werden gefuellt (Server):** Eine Datenmigration gibt jedem
  stcp-Tunnel, dessen Secret leer ist, ein eigenes zufaelliges Secret; der Generator laesst
  einen stcp-Tunnel ohne Secret aus der frpc- und Visitor-Konfiguration weg. Der Agent holt die
  neue Konfiguration von selbst (Provision-Hash); ein laufender Desktop-Visitor eines solchen
  Tunnels braucht einen Tunnel-Neustart.
- **FRP: Tunnel-Antworten ohne Secret (Server):** Die JSON-Antworten von `/api/frp/tunnels`,
  `/api/frp/status`, `/api/frp/server-config/{id}` und `/api/servers` liefern `secretKey` als
  `null`; das Feld bleibt, das Schema aendert sich nicht. Das Secret steht nur noch in den
  erzeugten TOML-Dateien und im Provisioning. Ein `PUT /api/frp/tunnels/{id}` mit `secret_key`
  `null` oder `""` laesst das gespeicherte Secret unveraendert; wird ein Tunnel per `PUT` zu STCP
  und hat kein Secret, erzeugt der Server eins. Doku: `docs/developer/api-reference.html`.
- **Ein ruff ueberall (R-0074):** `apps/server/requirements-dev.txt` pinnt `ruff==0.15.20`
  statt des Bodens `ruff>=0.15`, und `scripts/dev/toolchain-lockstep.sh` verlangt Gleichheit
  mit `ci.yml` und `scripts/vm/bootstrap_linux.sh` statt nur „nicht darueber". Mit dem Boden
  blieb ein vorhandenes ruff 0.16.x im `AH_VENV` liegen und meldete ueber die vier Lint-Pfade
  841 Treffer, die CI mit 0.15.20 nie sah. Der Schritt `server-pytest` zieht das `AH_VENV`
  beim naechsten Lauf auf 0.15.20 zurueck. Dazu verlangt `ruff.toml` per
  `required-version = "==0.15.20"` genau diese Version, und der Lockstep prueft auch diese
  Stelle: ein anderes ruff im `PATH` bricht mit Exit 2 ab, statt still andere Regeln
  anzuwenden (der Format-Hook `scripts/dev/format-file.sh` formatiert dann still nicht).
  Auch das Tool-Venv des Runners (`VENV_PKGS` in `scripts/dev/runner-setup.sh`, das erste
  ruff in seinem `PATH`) installiert `ruff==0.15.20`, als fuenfte Stelle im Lockstep; auf
  einem bestehenden Runner wirkt das nach erneutem `sudo bash scripts/dev/runner-setup.sh`.

- **API-Schema: `X-API-Key` und `X-Internal-Key` als Security-Schemes (Server):** Das
  OpenAPI-Schema deklariert neben `HTTPBearer` jetzt `ApiKey` (Header `X-API-Key`, an allen
  Routen, die API-Key oder JWT annehmen) und `InternalKey` (Header `X-Internal-Key`, der
  Dienst-zu-Dienst-Ingress); die Swagger UI bietet beide unter „Authorize" an. Dafuer entfaellt
  der optionale Header-Parameter `x-internal-key` der zwei Internal-Routen, deren Verhalten
  gleich bleibt (Anfragen mit zwei Anmeldungen: siehe naechsten Punkt). Der Schemathesis-Check
  `ignored_auth` laeuft damit in allen vier Auth-Kontexten statt nur mit JWT. Doku:
  `docs/developer/api-reference.html`.
- **Verhaltensaenderung: jede mitgesendete Anmeldung muss gelten (Server):** An den Routen, die
  API-Key oder JWT annehmen (`/api/connections`, `/api/frp/provision`), prueft der Server jetzt
  alle mitgesendeten Anmeldungen, bevor er entscheidet. Ein gueltiger `X-API-Key` neben einem
  ungueltigen oder abgelaufenen Bearer-Token — oder ein gueltiger Bearer neben einem
  unbekannten Key, auch als `?api_key=` — ergibt `401` statt `200`; ebenso ein
  `X-API-Key` neben einem ungueltigen `?api_key=` (bisher wurde die Query dann ignoriert). Nur
  `Authorization: Basic` (von einem Proxy oder aus `user:pass@` einer Sync-URL) wird ignoriert;
  jeder andere `Authorization`-Header muss ein gueltiger Bearer sein — ein fremdes Schema, ein
  leerer oder unlesbarer Wert ergibt `401`. Sind beide
  gueltig, entscheidet wie bisher der Key; mit nur einer Anmeldung bleibt alles wie es war.
  Kein Client sendet zwei (Web und Desktop den Bearer, der Desktop-Sync nur `?api_key=`,
  der Agent nur `X-API-Key`, das Monitoring nur `X-Internal-Key`). Doku:
  `docs/developer/api-reference.html`.
- **API-Schema: typisierte Antworten fuer users und frp (Server):** `GET`/`POST /api/users` und
  `PUT /api/users/{id}` deklarieren `UserResponse`, die FRP-Server-Config-Routen
  `FrpServerConfigOut` (Detail: `FrpServerConfigDetail` mit den Tunneln als `FrpTunnelOut`) und
  `GET /api/frp/status` `FrpStatus` — statt eines leeren Schemas im OpenAPI. Die Antwort-Bytes
  bleiben gleich (je Route ein Differential-Test gegen den bisherigen Builder); Zeitstempel
  bleiben Strings aus `isoformat()`, das `tunnel`-Objekt im FRP-Status bleibt offen. Die Doku
  nannte fuer die Config-Detail-Route ein `?include_tunnels=true`, das es nicht gibt: die Tunnel
  kommen immer mit. Doku: `docs/developer/api-reference.html`.
- **Test-Ausgaben und Pflicht-Tests gegen den Stack (Harness Stufe 5c, Entwickler-Werkzeuge):**
  Die pytest-Schritte von `scripts/tests/run.sh` schreiben JUnit-XML nach
  `.ah-out/junit/<schritt-id>.xml` (Schemathesis eine Datei je Dienst), Playwright mit gesetztem
  `AH_OUT_DIR` nach `junit/web-playwright.xml`, die Desktop-E2E ueber `@wdio/junit-reporter` eine
  Datei je `wdio run`; jeder Lauf verwirft die XMLs des letzten, `heavy.sh` kopiert `junit/` in
  das Laufverzeichnis und nennt im Report ihre Zahl. Das Test-Overlay `docker-compose.test.yml`
  veroeffentlicht Postgres und Redis nur auf `127.0.0.1` (`ITEST_PG_PORT`, `ITEST_REDIS_PORT`, pro
  Lauf gestreut), `lib_e2e_stack.sh` exportiert `ITEST_DATABASE_URL` und `ITEST_REDIS_URL`. Zwei
  neue Pflicht-Schritte im `integration`-Layer: `stack-pytest` (`scripts/tests/stack_pytest.sh`)
  faehrt den Migrations-Smoke des Monitorings, `test_stream_redis` und den TOCTOU-Test des
  ca-issuers gegen diese Dienste, ein Skip ist dort ein Fehler; `web-live`
  (`scripts/tests/web_live.sh`) faehrt das Playwright-Projekt `live` ohne Mocks (Login als
  Seed-Admin, jede Admin-Seite, Benutzer anlegen und loeschen). `test_stream_redis` liest die
  Redis-URL aus `AH_TEST_REDIS_URL`. Anleitung: `DEVELOPMENT.md` („Automatisierte
  Integrations-/E2E-Tests", „Wochenlauf") und `docs/developer/cicd.html`.
- **Planen und Beweis (Harness Stufe 5b, Entwickler-Werkzeuge):** Ledger haben die Status-Folge
  `geplant` -> `freigegeben` -> `aktiv` -> `bereit` -> `erledigt` und das Kopf-Feld `Heavy:`
  (`none | linux-full | scenario <flags> | windows`) statt `Fast-Suite:`/`Warm-Profil:`;
  `ledger.sh lint` prueft `Heavy:` und die Zeilen der Beweis-Konvention A-D (`Orakel:`,
  `Dedup-Key:`, `HEAD:`). `/feature-plan` committet den Plan am Gate als ersten Commit auf
  `feature/<slug>`, kennt `--kurz R-nnnn` (Kurz-Ledger aus einer belegten Roadmap-Zeile, mit
  Pflichtzeile `Semantik:`, ohne SEC) und `--bundle <komponente>` (REF-Zeilen einer Komponente)
  und fuehrt die Roadmap-Schritte am Gate aus; `/feature-build` folgt der Status-Folge, liest
  `Heavy:` und zieht die Roadmap mit. `roadmap.py status` bekommt `--ledger` und `--pr`, die
  Spalten, die `next` und `sync` lesen. Neu ist `scripts/tests/skill_consistency_test.sh`, der
  die Skill-Texte gegeneinander prueft. Anleitung: `tasks/README.md` und
  `docs/developer/cicd.html` („Beweis-Konvention").
- **Die Roadmap als Skript (Harness Stufe 5a, Entwickler-Werkzeuge):** `scripts/dev/roadmap.py`
  (Python-Stdlib) liest, lintet und schreibt die private Roadmap `tasks/private/ROADMAP.md`
  mit `lint`, `show`, `next`, `add`, `status`, `approve`, `sync` und `stats`. Jedes Schreiben
  laeuft unter `flock`, mit `.bak`, Zeilenzahl-Pruefung, einer 5-Sekunden-Regel gegen einen
  offenen Editor und einem lokalen Commit im privaten Repo. Der Abschnitt einer Zeile folgt
  ihrem Status, der WIP-Kopf wird neu gerechnet, `neu` ist bei 20 Zeilen gedeckelt, und ein
  Dedup-Key haelt Dubletten zurueck. `heavy.sh` legt REG- und REL-Zeilen nur noch ueber
  `roadmap.py add` an. Der Status-Hook zeigt alle Punkte von „Als Naechstes" und die
  WIP-Deckel, bei einem erreichten mit `Warnung:`. Neu sind der Skill `/roadmap` (Ueberblick
  und `triage`) und der `run.sh`-Schritt `scripts/dev pytest` (Id `dev-pytest`, Pflicht).
  Anleitung: `DEVELOPMENT.md`, „Die Roadmap als Skript: `roadmap.py`".
- **VM-Rollen bekommen mehr vCPUs:** `scripts/vm/profiles.json` gibt der Desktop-Rolle und dem Bake
  6 statt 4 bzw. 2 Kerne und der Server-Rolle 4 statt 2 — der Host lief waehrend eines Capstones
  bei 10 % CPU, waehrend Tauri-, npm- und Go-Builds in den VMs auf 2 Kernen warteten (Bake
  `linux-full` 56 min). Agent-, Tunnel-, Visitor-, Moncheck-, RPM- und Probe-Rolle bleiben bei 2.

- **Die schweren Suites laufen ohne externes Binary (Harness Stufe 2b):** Alle Wrapper rufen
  jetzt `scripts/vm/vm.py` statt des externen `crabbox` auf, bei unveraenderter Aufruf-Semantik.
  Neu: `scripts/vm/warm.sh`, `iter.sh`, `reap.sh`, `bake.sh` und `scripts/vm/bootstrap_linux.sh`;
  `scripts/tests/multibox.sh` und die sieben Rollen-Skripte heissen `box_*.sh`. Die
  Ausgabe-Artefakte liegen unter `.ah-out/`, der Warm-Zustand unter `.vm/warm.env`, die
  Lane-Kennung explizit in `.vm/lane`. Eine Multi-Host-Szenerie traegt ein gemeinsames
  `sc-`-Tag: der Teardown ist ein `vm.py destroy --scenario` und erwischt auch die Box, deren
  Klon zwar kam, aber nie hochfuhr. Vor dem ersten Klon prueft `vm.py doctor --roles` die
  Kapazitaet fuer die ganze Szenerie — was nicht passt, kostet nichts statt vier gebooteter
  Boxen. `heavy.sh` trennt jetzt Ganz-Lauf-Abbrueche von Rollen-Abbruechen: ein einzelner
  verlorener Klon im Capstone wird der Rolle zugeordnet, statt den Lauf als UNVERIFIED zu
  verwerfen. Die Lease-Wiederholung entfaellt mit dem Rennen, das sie umging.
  Anleitung: `/vm` (die VMs) und `/test` (die Suiten), Details in `DEVELOPMENT.md`.

- **Bau- und Review-Tempo (Harness):** Der Frischer-Kontext-Reviewer laeuft jetzt auf Sonnet
  statt Opus (Opus nur bei einem Risikopfad im Diff: PKI/mTLS, Auth, SSRF, Migrationen,
  Release-Workflows), hat ein Zeitbudget von zehn Minuten und faehrt die Suiten nicht mehr
  selbst nach. Ein Kurz-Ledger mit hoechstens drei Tasks bekommt `Review: am Ende` — ein
  Review ueber den ganzen Branch-Diff statt einem je Task, ohne den abschliessenden
  `/code-review`. Und pro Task laeuft nur noch das gezielte `Verify:`, die volle
  Komponenten-Suite einmal vor dem Commit — nie zwei Testlaeufe gleichzeitig, weil die
  `server`-Suite sich eine Postgres-Test-DB teilt (`DEVELOPMENT.md`, „Python-Tests lokal").

- **Lange Laeufe ueberwacht:** `/test weekly|all|capstone` startet `heavy.sh` jetzt selbst in
  `tmux` und wacht mit einem Hintergrund-Waechter bis zum Report, statt Kevin die tmux-Zeile
  zurueckzugeben; Verdict-Zeile, Summary-Zeilen, VM-Liste und die Roadmap-Zeilen des Laufs
  kommen als Meldung. Start und Abbruch bleiben Kevins Zuruf, nichts startet von selbst.

- **Audit-Hygiene:** `audit.yml` installiert `pip-audit` und `cargo-audit` jetzt gepinnt
  (2.10.1 bzw. 0.22.2, wie `govulncheck@v1.7.0` seit dem letzten Update-Lauf) — ein Job
  darf nicht rot werden, weil ein Werkzeug ueber das Wochenende seine Exit-Codes oder
  seine Advisory-Quelle geaendert hat. Neu prueft `scripts/dev/toolchain-lockstep.sh`
  (CI-Step im Job `frp-consistency`), dass alle `go-version`-Stellen in
  `ci.yml`/`release.yml`/`audit.yml` uebereinstimmen und die `go`-Direktive des gepinnten
  `x/vuln`-Release nicht darueber liegt — sonst scheitert der Audit-Job unter
  `GOTOOLCHAIN=local` schon am Installieren von `govulncheck` und meldet nichts ueber
  unsere Dependencies. Ist der Modul-Proxy nicht erreichbar, endet der Check mit 75
  (SKIP) und faerbt den Job rot, statt eine Pruefung durchzuwinken, die nie lief. `DEVELOPMENT.md` beschreibt die drei Werkzeuge jetzt auch lokal,
  in denselben Versionen wie CI.

- **Ausfuehrung zuerst (Autonomie-Roadmap, Stufe 3):** Der Release-Workflow prueft jetzt
  das Ergebnis statt des Rezepts — das Agent-Binary muss statisch sein und darf kein
  `GLIBC_`-Symbol importieren, das ausgelieferte `.deb` darf keine zstd-Member tragen,
  die frische `SHA256SUMS.minisig` wird gegen den in `scripts/update.sh` gepinnten
  Public Key verifiziert, die Windows-`.exe` wird einmal ausgefuehrt und muss die
  Tag-Version drucken (neuer harter Job `agent-windows-smoke`), und das MSI wird
  installiert, geprueft und wieder deinstalliert (weiter `continue-on-error`).
  `scripts/release/check-versions.sh <X.Y.Z>` prueft alle sechs handgepflegten
  Versions-Stellen statt nur `tauri.conf.json` — dabei kam heraus, dass die
  Sidebar-Footer der beiden Landing-Pages seit 0.43.2 hingen (mehrzeiliges Markup, vom
  alten Muster nie erfasst); sie sind mitgezogen. Die Go-Suite laeuft in CI unter `-race`, in
  `run.sh` dort, wo ein C-Compiler mit cgo vorhanden ist (sonst sagt der Lauf, dass der
  Detektor aus war).
  Neu ist der **Wochenlauf** `bash scripts/tests/heavy.sh all|capstone|weekly`: ein
  Wrapper um die vorhandenen crabbox-Skripte, der einen Report mit den woertlichen
  Summary-Zeilen schreibt, jeden roten Schritt mechanisch als `infra`, `flaky`,
  `unbestaetigt`, `extern` oder `reg` klassifiziert (Wiederholung auf derselben Box,
  dann eine frische zweite VM, dann eine Gegenprobe gegen den letzten PASS-Commit) und
  aus einer bestaetigten Regression eine Roadmap-Zeile plus Kurz-Ledger macht. Er
  startet nie von selbst. Zusaetzlich abgedeckt: der Upgrade-Pfad vom letzten
  veroeffentlichten Release auf den aktuellen Stand (`upgrade_path_test.sh`, inkl.
  `update.sh` real) und die fuenf Desktop-Specs, die bisher von keinem Skript gefahren
  wurden (`desktop_e2e_misc.sh`). Der Multibox-Capstone schliesst `--enforce` ein und
  meldet jede bedingte Pruefung, die nicht lief, als SKIP statt sie zu verschweigen.

- **Test-Infrastruktur (Autonomie-Roadmap, Stufe 1 — „Gruen heisst Beweis"):** Der
  Test-Aggregator `scripts/tests/run.sh` kennt `--strict`, `--only <keys>` und
  `--step <name>`; unter `--strict` ist ein uebersprungener Pflicht-Schritt ein
  Fehler statt eines PASS, ebenso ein strenger Lauf, in dem ueberhaupt nichts lief.
  Die pytest-internen Skips sind jetzt sichtbar (`N passed, M failed, K skipped,
  J test-skips, R reruns`) und fuer Tests mit erfuellter Vorbedingung ein Fehler.
  Jeder Lauf schreibt `last-<layer>.json` mit Tree-Hash als Evidenz. Neu:
  `scripts/dev/verify.sh <komponente>` als einzige Verify-Form (Flags statt
  Env-Praefix, `last-verify.json`), `scripts/dev/tree-hash.sh` und ein
  Session-Status-Hook, der jede Session mit einem `AH-STATUS`-Block eroeffnet.
  Elf Stellen, die mangels Toolchain still `exit 0` meldeten (die sieben
  Desktop-GUI-Suiten und vier in `agent_install_test.sh`), enden jetzt mit
  `exit 75` = SKIP; die beiden minisign-Weichen in `install_test.sh`/
  `update_test.sh` melden ebenfalls SKIP, statt den Signaturpfad zu
  neutralisieren und PASS zu melden. Der
  crabbox-Bootstrap bricht ab, statt eine halb hydrierte Box zu hinterlassen.
  CI bekommt den Job `agent-windows`, der die Go-Suite erstmals nativ unter
  Windows ausfuehrt. `@typescript-eslint/no-unused-vars` ist in Web-Panel und
  Desktop-UI von `warn` auf `error` gestellt — ein verwaister Import laesst einen
  PR jetzt durchfallen, statt nur zu warnen.

- **Entwickler-Harness (Autonomie-Roadmap, Stufe 0):** `CLAUDE.md` auf 179 Zeilen neu
  geschnitten (Betriebsmodell, Warn-Trigger, Stufen-Fahrplan, Definition of Done); die
  Release- und Test-Stolperfallen leben jetzt als pfadgebundene Regeln unter
  `.claude/rules/` (`testing.md`, `docs.md`, `release.md`). `.gitignore` gibt
  `.claude/rules/` und `.claude/agents/` frei und haelt `.ah-out/`, `.vm/` und
  `tasks/private/` lokal. Die Autonomie-Roadmap liegt im privaten Repo statt unter
  `docs/features/`.

## [0.45.0] - 2026-09-08

### Fixed

- **Agent-Installation scheitert nicht mehr am apt-Lock:** Auf einer frischen
  Debian-/Ubuntu-Maschine laeuft `unattended-upgrades` direkt nach dem Boot, und
  `agent-install.sh` lief mit seinem ersten `apt-get update` genau da hinein. Der
  Abbruch meldete „repo unreachable or TLS/GPG problem" — eine Fehldiagnose, die
  in die voellig falsche Richtung schickt. Jeder apt-Aufruf laeuft jetzt mit
  `DPkg::Lock::Timeout` (apt wartet damit selbst auf die Sperre, ohne Zusatz-
  Werkzeug, deckt aber nur die dpkg-Sperren ab) und wird zusaetzlich von einer
  Warteschleife ueber alle vier apt/dpkg-Sperren gedeckt. Der Listen-Lock von
  `apt-get update` — der tatsaechliche Ausloeser — kennt keinen apt-Timeout und
  ist jetzt zusaetzlich durch drei Wiederholversuche abgesichert; der Fehlertext
  nennt die Sperre als moegliche Ursache.

- **„Jetzt pruefen" meldet keinen Erfolg mehr, wo nichts passiert:** Der Endpunkt
  `POST /api/monitoring/checks/{id}/run` rief `execute_check` auch fuer
  push-ausgewertete Check-Typen (`agent_resources`, `service_process`,
  `proxmox_backup`, `zfs_health`, `docker_health`, `smart_health` — 6 von 11)
  und fuer deaktivierte Checks auf. Beide steigen dort still aus; der Endpunkt
  antwortete trotzdem mit HTTP 200 und unveraendertem Zustand, was von
  „geprueft, unveraendert" nicht zu unterscheiden war. Jetzt kommt in beiden
  Faellen ein `409` mit Klartext-Begruendung. Der Desktop-Client bietet die tote
  Aktion gar nicht mehr an: Der „Jetzt pruefen"-Knopf ist fuer diese Checks
  ausgegraut und nennt im Tooltip den Grund. `agent_ping` bleibt ausloesbar — er
  misst das Ausbleiben eines Pushes und wird vom Scheduler ausgewertet.

- **Hook-Ausfuehrung bleibt nach einem fehlgeschlagenen Prozess-Start nutzbar:**
  Das Semaphore-Permit wurde vor `subprocess.Popen` geholt, das freigebende
  `try`/`finally` begann aber erst nach dem Start der Lese-Threads. Schlug
  dazwischen etwas fehl — `Popen` bei Speicherdruck, `Thread.start` bei
  erschoepftem Thread-Kontingent —, war das Permit dauerhaft verloren. Nach acht
  solchen Fehlschlaegen meldete **jeder** Hook bis zum Neustart „Server
  ausgelastet", obwohl gar keiner mehr lief.
- **Deaktivierte Schaltflaechen sehen im Desktop-Client jetzt auch deaktiviert
  aus:** Das Stylesheet hatte keine einzige `:disabled`-Regel — ein gesperrter
  Knopf war optisch nicht von einem funktionierenden zu unterscheiden und
  leuchtete beim Ueberfahren weiter auf. Betrifft ueber die Monitoring-Knoepfe
  hinaus alle `.btn`-Schaltflaechen, etwa Speichern-Knoepfe waehrend eines
  laufenden Vorgangs.

- **Kein Heartbeat-Sturm mehr bei Uhr-Spruengen des Monitoring-Hosts:** Die
  agent_ping-Staleness
  misst auf der Wanduhr (nur die ist ueber Prozessgrenzen persistierbar) — ein
  NTP-Vorwaertssprung groesser als `stale_minutes` liess dadurch schlagartig
  ALLE Agents als "nicht erreichbar" gelten und schaltete ueber die
  Host-down-Unterdrueckung zugleich alle anderen Alerts dieser Server stumm.
  Ein monotoner Zweit-Zeitstempel entlarvt den Sprung jetzt (Divergenz > 60 s);
  der Checker rechnet ihn heraus und bewertet auf der echten Stillstandszeit
  weiter — ein frischer Agent bleibt ok, ein wirklich toter bleibt critical.

### Security

- **cryptography auf 50.0.1 angehoben (Server + CA-Issuer):** Die gepinnte
  Version 48.0.1 war von PYSEC-2026-3552, -3553 und -3554 betroffen
  (PKCS#7-Entschluesselung bzw. X.509-Verifier; behoben ab 50.0.0). **Diese
  Pfade nutzt der Code nicht** — gebaut und signiert wird ueber
  `CertificateBuilder`/`CertificateSigningRequestBuilder`, PKCS#7 und
  `x509.verification` kommen nirgends vor. Angehoben wird trotzdem, weil
  cryptography ausgeliefert in der eigenen PKI (CA-Issuer) und im mTLS-Pfad des
  Servers steckt. Die Untergrenze in beiden `requirements.in` steht jetzt auf
  `>=50.0.0`, damit ein spaeterer Resolver nicht hinter die Sicherheitsschwelle
  zurueckfaellt; die gehashten Lockfiles wurden neu erzeugt.
- **npm-Lockfiles von Web und Desktop-UI bereinigt:** `npm audit fix` (ohne
  `--force`, also rein semver-kompatibel) hebt `brace-expansion`, `nanoid`,
  `postcss`, `postcss-selector-parser` und `undici` an, im Web zusaetzlich
  `@humanfs/core` und `@humanfs/node` — durchweg Build- und Test-Werkzeug, das
  nicht ausgeliefert wird. Beide Projekte melden jetzt `found 0
  vulnerabilities`. Fuer `apps/desktop/e2e` reichte das nicht: der
  WebdriverIO-Stack hing an `extract-zip`, fuer das es **keine** gepatchte
  Version gibt (GHSA-jmr9-qjv8-65gv). Zwei `overrides` loesen das ohne
  Unterdrueckung — `deepmerge-ts ^8.0.0` und `@puppeteer/browsers ^3.2.1`, das
  den Entpack-Pfad von `extract-zip` auf `modern-tar` umstellt. Danach greift
  auch dort `npm audit fix`, und alle drei Projekte melden
  `found 0 vulnerabilities`.
- **Rust-Abhaengigkeiten des Desktop-Clients entschaerft:** `quick-xml` steht
  jetzt auf 0.41.0 statt 0.37.5/0.38.4 (RUSTSEC-2026-0194 und -0195, ueber
  `plist` 1.10.0; `tauri-winrt-notification` 0.7.3 streicht seine
  quick-xml-Abhaengigkeit ganz), und mit
  `tauri-plugin-log` 2.9.1 faellt der Teilbaum `byte-unit` → `rust_decimal` →
  `rkyv` samt RUSTSEC-2026-0235 ganz aus dem Baum. `cargo audit` meldet keine
  Vulnerabilities mehr. Bewusst als gezielte `-p`-Bumps (26 Pakete) statt eines
  vollen `cargo update` (246 Zeilen inkl. tokio, hyper, rustls und einem
  signal-hook-Major) — vor einem Release nur so viel Flaeche wie noetig.

## [0.44.0] - 2026-07-28

### Added

- **Monitoring: Standard-Templates + Seeding:** Fuenf Built-in-Templates (Linux
  Server, Windows Server, Proxmox Host, Docker Host, ZFS Storage) mit
  recherchierten Schwellwerten (Zabbix/Netdata/Checkmk/Backblaze) werden beim
  Start des Monitoring-Dienstes einmalig geseedet (Tombstone in
  `monitor_seed_state` — User-Edits und -Deletes ueberleben jeden Neustart).
- **Tag-basierte Template-Zuweisung:** Ein Template laesst sich an einen
  Server-Tag binden; der Sync materialisiert Zuweisungen sofort bei
  Server-Aenderungen und alle 15 Minuten (`GET /api/internal/servers`,
  `POST /templates/tag-sync`). Manuelle Zuweisungen bleiben unangetastet.
- **Template-Zuweisung in der UI:** Template-Modal mit Server-Mehrfachauswahl
  (Bulk), Opt-in-Template-Dropdown im Server-Anlege-Dialog, Zuweisungs-Sektion
  im Server-Monitoring-Tab und Uebersichts-Banner "N Server ohne Monitoring"
  mit Bulk-Zuweisungs-Dialog.
- **Maintenance-Fenster (pro Server oder global):** einmalig oder woechentlich (Wochentage +
  Zeitfenster in IANA-Zeitzone, DST-korrekt), collect-but-mute — Checks und
  Metriken laufen weiter, Alerts und Hub-Benachrichtigungen sind unterdrueckt.
- **Disk-Full-Prognose (`disk_forecast`):** Least-Squares-Fuellrate aus der
  VictoriaMetrics-Historie pro Mountpoint — warnt bei "voll in <= 24 h",
  kritisch bei "<= 8 h", deutlich vor den statischen Disk-Schwellen.
- **Kachel-Grid + Heartbeat:** Die Monitoring-Uebersicht bekommt eine
  umschaltbare Kachel-Ansicht (Worst-State-Farbe pro Server) und einen
  24-h-Verfuegbarkeits-Balken aus der `agent_ping`-Timeline; Loading-/Empty-/
  Error-States mit Retry.
- **Default-Subscription fuer neue Admins:** Jeder Admin-Create-Pfad (API, CLI
  `create-admin`, `ADMIN_PASSWORD`-Env, Bootstrap-Endpoint) legt automatisch
  eine Benachrichtigungs-Regel "Alle Server / warning / Glocke" an — auf
  Frisch-Installationen erreicht damit jeder Alert mindestens die Admins.
- **`alert.triggered`-Event-Hook:** Kritische Monitoring-Transitionen feuern
  den bisher nur dokumentierten Hook jetzt wirklich (Payload `server_id`,
  `severity`, `title`, `message`).
- **Retention konfigurierbar:** `ALERT_LOG_RETENTION_DAYS` (Alert-Log, Default
  90 Tage) und `VM_RETENTION` (VictoriaMetrics, Default 90d) als Env-Variablen.

### Changed

- **Alerter mit Sent-State (Level-Semantik):** Der Alerter merkt sich pro Check
  den zuletzt real gemeldeten Status (`monitor_states.notified_status`, Migration
  mit Backfill) und meldet Diskrepanzen nach, sobald keine Unterdrueckung mehr
  greift: Ein Problem, das waehrend eines Host-Ausfalls entstand und danach
  bestehen bleibt, wird nach der Agent-Recovery nachgemeldet; Recoveries fuer
  vor einem Maintenance-Fenster gesendete Alerts und Probleme, die das Fenster
  ueberdauern, werden nach Fenster-Ende nachgeholt; `unknown -> ok` erzeugt nur
  noch dann eine Recovery, wenn zuvor real ein Problem gemeldet wurde (kein
  Recovery-Spam durch ok/unknown-Flapping). Transitionen vollstaendig innerhalb
  eines Fensters bleiben weiterhin stumm.
- **unknown-Policy:** Uebergaenge nach `unknown` benachrichtigen nie mehr
  (vorher eskalierte `unknown` wie ein Failure); `unknown -> ok` meldet nur
  noch nach einem real gemeldeten Problem eine Recovery (siehe Sent-State-
  Eintrag oben).
- **Alert-Daempfung:** `agent_resources` arbeitet pro Metrik mit Hysterese
  (Release = Entry - 10 pp, konfigurierbar via `hysteresis_pp`); steht der
  `agent_ping` eines Servers auf critical, sind alle anderen Checks des
  Servers unterdrueckt (Host-down-Inhibition).
- **Agent-Liveness persistiert:** Der letzte Push-Zeitpunkt liegt jetzt in
  `monitor_agent_liveness` und wird beim Start hydratisiert — kein
  False-Alert-Sturm nach einem Monitoring-Restart; `stale_minutes`-Default 15.
- **Check-Konfiguration strikt validiert:** Pro Check-Typ ein striktes
  Pydantic-Modell — Tippfehler in Config-Keys und Werte ausserhalb der Grenzen
  geben 422 statt stumm `unknown`.
- **Monitoring-Modals vereinheitlicht:** Gemeinsame UI-Primitives (Modal,
  ConfirmDialog, EmptyState) im AdminCave-Design ersetzen die duplizierten
  Editor-Overlays; Check-CRUD direkt auf der Monitoring-Seite.

### Fixed

- **`restore.sh` stellt `./data` wieder her, statt daran zu scheitern:**
  `backup.sh` sichert das Verzeichnis im Container (als root), der Restore
  raeumte und entpackte es aber mit dem Host-`tar` als aufrufender Nutzer — die
  Bereinigung schlug still fehl und das Entpacken starb an `Cannot utime` /
  `Cannot mkdir`. Disaster Recovery scheiterte damit genau dann, wenn man sie
  braucht, mit irrefuehrender Meldung. Wipe und Extraktion laufen jetzt als
  Container-Root (wie `restore_volume`), der Tar-Escape-Guard bleibt davor.
- **Ping-/TCP-Checks erreichen wieder interne Ziele:** Der SSRF-Schutz lehnte in
  `ping` und `tcp` auch private/reservierte Adressen ab (10.x, 192.168.x,
  localhost) — damit war der Hauptanwendungsfall, interne Server zu ueberwachen,
  nicht moeglich; die Checks blieben dauerhaft auf `unknown`. Beide pruefen jetzt
  beliebige Ziele (Anlegen bleibt Admin-only, das Signal ist reine
  Erreichbarkeit). `http`-Checks und Alert-Webhooks bleiben bewusst geschuetzt:
  Sie liefern bzw. verschicken Antwort-Inhalte (Cloud-Metadaten).
- **Web-Panel: Hook-Editor bietet alle Events an:** Die Event-Auswahl im
  Hook-Dialog fuehrte eine eigene, veraltete Liste — `playbook.*` und das neue
  `alert.triggered` fehlten und waren nur per API abonnierbar. Die Liste ist
  ergaenzt (inkl. Labels DE+EN) und ein Guard-Test pinnt sie jetzt gegen die
  Server-Whitelist `VALID_EVENTS`.
- **Admin-Doku Monitoring (DE+EN):** Das dokumentierte
  `warn_threshold`/`crit_threshold`-Modell existierte nicht — ersetzt durch
  die echten per-Typ-Config-Keys samt Defaults; der `alert.triggered`-Abschnitt
  beschreibt jetzt den implementierten Hook.

## [0.43.2] - 2026-07-14

### Fixed

- **Agent-Binary laeuft wieder auf aelterer glibc (Debian Stretch, RHEL 8,
  UniFi-/Appliance-Firmware):** Der Release-Build baute den Agent mit einem
  nackten `go build`, das die Runner-Default `CGO_ENABLED=1` erbt und dadurch
  **dynamisch** gegen die glibc des Build-Hosts (2.39) linkt — das ausgelieferte
  Binary brach mit `GLIBC_2.34 not found`. Der Release baut den Agent jetzt
  **ueber den Makefile** (`CGO_ENABLED=0`, vollstatisch), sodass es genau das
  getestete Binary ist. Zusammen mit dem xz-Fix aus 0.43.1 installiert **und**
  laeuft das Paket damit auf dem gesamten unterstuetzten Feld.
- **Regressions-Guard:** Der Multibox-Test installiert das frische `.deb` jetzt
  in einem `debian:9`-Container (dpkg 1.18 + glibc 2.24) **und fuehrt das Binary
  aus** — faengt kuenftig beide Klassen (Kompression und glibc-Linkage), die die
  reine Modern-Ubuntu-Testflotte durchrutschen liess.

## [0.43.1] - 2026-07-14

### Fixed

- **Agent-`.deb` installiert wieder auf aelterem Debian / Appliance-Hosts:** Das
  Paket wurde auf modernen Build-Hosts mit **zstd**-Kompression gebaut, die ein
  aelteres `dpkg` (Debian Stretch/Buster, UniFi- und aehnliche Debian-basierte
  Firmware) nicht lesen kann (`unknown compression for member 'control.tar.zst'`).
  `build-deb.sh` erzwingt jetzt **xz** (verstaendlich fuer jedes `dpkg` seit
  Debian 6), plus ein Build-Guard, der einen zstd-Rueckfall hart failt. Das
  Agent-Binary selbst war nie betroffen (statisch, `CGO_ENABLED=0`).
- **`agent-install.sh` haengt nicht mehr an einem nicht erreichbaren Port:** die
  Repo-/Release-Fetches bekommen `--connect-timeout 10`, brechen also mit klarer
  Meldung ab, statt am TCP-SYN eines gefilterten `:8445` stillzustehen.

## [0.43.0] - 2026-07-13

### Added

- **Ein-Befehl-Agent-Rollout (`scripts/agent-install.sh`):** richtet auf
  Debian/Ubuntu (apt) und Rocky/Alma/RHEL (dnf) das server-eigene Paket-Repo
  ein (Repo-Schluessel von `:8445` mit **erzwungenem** GPG-Fingerprint-Vergleich
  gegen den gepinnten Projekt-Schluessel), installiert den Agent und
  provisioniert ihn direkt mit. Nach erfolgreichem mTLS-Enrollment stellt das
  Skript die Repo-Quelle automatisch auf CA-Pinning um (apt `CAInfo` /
  dnf `sslcacert`). Token optional per `/dev/tty`-Abfrage;
  `--from-github`-Fallback (minisign-verifiziert, apt). Liegt auch im
  Runtime-Bundle (`/opt/adminhelper/scripts/agent-install.sh`).
- **Verifizierter Erstkontakt (`adminhelper-agent provision --ca-fp`):** Der
  Agent prueft im TLS-Handshake, dass die praesentierte Kette die interne CA
  mit genau diesem SHA-256-Fingerprint enthaelt und das Server-Leaf
  kryptografisch daran haengt — der Einmal-Token verlaesst den Host erst nach
  bestandener Pruefung (ersetzt blindes Trust-on-first-use).
- **Provisionierungs-Tab als Vertrauensanker-Kurier:** generiert den
  Install-Einzeiler und den `provision`-Befehl inklusive `--ca-fp` (der
  Desktop kennt die interne CA aus seinem eigenen Enrollment) und zeigt den
  CA-Fingerprint fuer den Out-of-band-Vergleich an; ohne enrollte Identitaet
  sichtbarer Hinweis auf den unverifizierten TOFU-Erstkontakt.

### Changed

- **Multibox-Suite testet den echten User-Pfad:** Server-Box baut und signiert
  ein Test-Repo auf `:8445`, Agent-Box installiert ueber das reale
  `agent-install.sh` mit `--gpg-fp`/`--ca-fp` und asserted Repo-Quelle und
  CA-Pinning-Endzustand.

### Fixed

- **Multibox: .deb-Pfad-Capture repariert** — `cbx_build_agent_deb` leakte
  make-/dpkg-Ausgaben in den per Command-Substitution zurueckgegebenen Pfad
  (betraf alle vier Rollen-Boxen der Suite).
- **Doku:** toter Verweis auf eine Ansible-Beispiel-Role
  (`apps/agent/ansible/`) ersetzt; veraltete Versionsbeispiele im
  Agent-Install-Abschnitt (README, EN-Doku) bereinigt.

## [0.42.0] - 2026-07-13

### Added

- **Trust-Dialog beim Erstkontakt (Desktop):** Praesentiert der Server ein nicht
  oeffentlich vertrauenswuerdiges Zertifikat (Standard-Installation mit
  AdminHelper-eigener PKI), fragt der Login-Screen bei Anmeldung und
  Token-Enrollment per Dialog, ob dem Server dennoch vertraut werden soll —
  Bestaetigen aktiviert dauerhaft "Selbstsignierte Zertifikate erlauben"
  (TOFU-Pin) und wiederholt die unterbrochene Aktion automatisch. Neuer
  stabiler Fehlercode `ERR_TLS_UNKNOWN_ISSUER` ersetzt die rohe rustls-Meldung.

### Fixed

- **"invalid peer certificate: UnknownIssuer" beim Bootstrap:** Der allererste
  Login-/Enrollment-Versuch mit Default-Einstellungen lief gegen die
  Standard-PKI in eine Sackgasse (roher TLS-Fehler ohne Handlungs-Hinweis) —
  jetzt Trust-Dialog bzw. verstaendliche Meldung mit Verweis auf die
  Einstellung.
- **"Selbstsignierte Zertifikate erlauben" war im Server-Modus unsichtbar**
  (die Checkbox wurde nur im Sync-Modus gerendert, obwohl Login/Enrollment sie
  auch im Server-Modus auswerten) — liegt jetzt im gemeinsamen Bereich beider
  Remote-Modi.
- **desktop_e2e_crud.sh laeuft standalone auf frischen Boxen:** fehlende
  node_modules werden selbst installiert (vorher zog `npx wdio` das falsche
  Wizard-Paket aus der Registry und der Tauri-Build scheiterte an fehlendem
  svelte-check).

## [0.41.0] - 2026-07-13

### Added

- **AdminCave-Design-System-Retheme (Web + Desktop):** beide Svelte-Frontends auf die
  visuelle Sprache des AdminCave-Design-Systems umgestellt — monochrom, True-Black
  dark-first, gebuendelte Geist-Schrift (offline-/CSP-fest, kein CDN), Pill-Radien,
  monochrome Primary-Buttons, Hairline-Borders und der AdminCave-Brand-Mark
  (currentColor, keine Verlaeufe mehr). DOM-Struktur und Layout bleiben unangetastet.
- **Light-Mode mit Umschalter:** gleichwertiger Light-Mode neben dem Default-Dark;
  Icon-Umschalter im Sidebar-Footer (Web neben EN/DE, Desktop neben Einstellungen),
  FOUC-frei via Inline-Script im `<head>`, Praeferenz in `localStorage['ah-theme']`
  (nicht im persistierten Settings-Contract, keine Migration). Monitoring-Charts (uPlot)
  und Status-Timeline sind theme-adaptiv.

## [0.40.0] - 2026-07-11

Umfassendes Security- und Qualitaets-Audit ueber alle Komponenten (Server,
Monitoring, Agent, Desktop, CA-Issuer, Gateway, Web): 590 Funde behoben,
CI (inkl. Windows) und die vollen Test-Suiten gruen.

### Fixed

- **Sicherheit:** Netz-Segmentierung des CA-Issuers (nur ueber die interne
  PKI-Plane erreichbar), Rate-Limit auf der CA-Renew-Plane, Secrets nur noch
  ueber stdin statt argv, Zip-Bomb-Schutz beim Report-Ingest, IPv6-taugliche
  Enroll-Endpunkte, gehaertete Header-/mTLS-Terminierung am Gateway.
- **Korrektheit:** deterministische FRP-Config-/Tunnel-Generierung, explizite
  UTC-Defaults in der Datenbank (Zeitzonen-Bug), Entfernung doppelt
  geschriebener Monitoring-Metriken, robustere System-Metrik-Parser (systemd,
  Docker/ZFS, SMART).
- **Desktop:** Windows-.rdp-Launch-Dateien (Host/Benutzername) werden beim
  naechsten Start zuverlaessig aufgeraeumt, Enrollment respektiert die
  Self-Signed-Einstellung, stabilere RDP-/SSH-/Tunnel-Verbindungsfluesse.

### Changed

- **Architektur:** Import-Zyklen aufgebrochen, Client-/Factory-Logik
  extrahiert, ConnectionKind-Vertrag auf ssh/rdp/web vereinheitlicht,
  Validierung konsequent an den Boundaries.
- **Betrieb:** Healthchecks und Startup-Reihenfolge im docker-compose-Stack
  gehaertet, FRP-bindPort-Kopplung entschaerft, Doku (DE/EN) durchgaengig
  nachgezogen.

### Added

- Umfangreiche Test-Abdeckung: neue Live-E2E-Specs (Enrollment-Formular,
  Tunnel-Erstellung/-Start/-Connect, SSH-/Web-/RDP-Connect), Windows-gated
  Unit-Tests, deterministische Alembic-Smoke- und Integrations-Suiten.

## [0.39.0] - 2026-07-04

### Changed

- **Projekt in die Admin-Cave-Organisation umgezogen.** Repo, Container-Registry
  (`ghcr.io/admincave/*`), Projekt-URLs und die Homepage (`admincave.com`) verweisen jetzt
  auf die Organisation; die Release-Signaturschlüssel (minisign + GPG) wurden neu erzeugt.

### Fixed

- **Agent: statisch gelinktes Linux-Binary (`CGO_ENABLED=0`).** Das `.deb`/`.rpm` lief
  bisher nur auf Systemen mit mindestens der glibc des Build-Hosts; auf älteren Distros
  (RHEL/Rocky/Alma 8, glibc 2.28) brach der Agent mit `GLIBC_2.34 not found` ab. Der Agent
  ist reines Go (gopsutil liest `/proc`), daher erzeugt `CGO_ENABLED=0` ein voll statisches
  Binary, das auf jeder glibc läuft.
- **Agenten-Provisionierung unter erzwungenem mTLS (`MTLS_ENFORCE=true`).** Ein frisch
  installierter Agent konnte sich nicht gegen einen bereits mTLS-erzwungenen Server
  provisionieren — sein `provision/activate`-Aufruf traf die zertifikatspflichtige
  Data-Plane (:443), bevor er ein Client-Zertifikat besaß. Die token-gesicherte
  Bootstrap-Route wird jetzt (wie `/enroll`) zertifikatslos auf der Enrollment-Plane (:8444)
  bedient; die Data-Plane (:443) bleibt unverändert zertifikatspflichtig.

### Added

- **Verteilte Multi-Host-Integrationstests via crabbox** (Entwickler-Tooling): der schwere
  Test-Tier (echter Stack, Cross-Host-mTLS, `.deb`/`.rpm`-Installation, 3-Host-FRP-Tunnel,
  Monitoring-Closed-Loop, Desktop-GUI-E2E) läuft auf ephemeren Proxmox-VMs, mit einem
  schnellen Warm-Reuse-Loop + Auto-Debug bei Fehlern. Siehe `DEVELOPMENT.md`.

## [0.38.0] - 2026-06-23

### Added

- **Server: Multi-Worker-Tauglichkeit (Skalierungs-Fundament).** Der Server kann nun
  mit mehreren Uvicorn-Workern laufen (`WEB_CONCURRENCY`, Default 1 = unverändert).
  Damit die periodischen Jobs (E-Mail-Outbox, Aufbewahrungs-Cleanups, Scheduled
  Hooks) genau einmal laufen, ist der **APScheduler in einen dedizierten
  `scheduler`-Dienst** ausgelagert (im Compose enthalten, genau eine Instanz,
  `RUN_MODE=scheduler`); die Web-Worker führen nur noch `uvicorn` aus. Scheduled
  Hooks werden vom Scheduler-Prozess periodisch aus der DB rekonziliert statt direkt
  von den Routern registriert. Das Rate-Limit warnt bei Multi-Worker ohne Redis; der
  DB-Pool ist pro Worker konfigurierbar (`DB_POOL_SIZE`/`DB_MAX_OVERFLOW`).
- **Server: SSE-Push für die Benachrichtigungs-Glocke (Push statt Polling).** Neuer
  Stream-Endpoint `GET /api/notifications/stream` (Server-Sent Events): sobald ein
  Nutzer eine neue Benachrichtigung bekommt, pusht der Server ein leichtes
  „Refresh"-Signal, woraufhin die Glocke sofort lädt — statt bis zu 30&nbsp;s zu
  warten. Worker-übergreifend via Redis Pub/Sub (`stream_hub`, eine Subscription pro
  Web-Worker); der Handler ist async und DB-frei und hält keine DB-Connection über
  die Stream-Dauer. Das Gateway (nginx) proxyt den Stream ungepuffert mit langem
  Read-Timeout. Polling bleibt als Fallback.
- **Server: Fundament für ein Benachrichtigungssystem (Phase A).** Der Server wird
  zum Notification-Hub. Neue Tabellen: `notification_subscription` (pro-User-Regeln
  — Scope *alle Server* / *Tag* / *einzelner Server*, Mindest-Severity, optionaler
  Kategorie-Filter, externe Kanäle E-Mail/Telegram), `notification` (Glocken-Feed
  mit gelesen/ungelesen) und `notification_outbox` (Versand-Queue für externe
  Kanäle, mit Retry-Feldern), plus `email`/`telegram_chat_id` am User. Ein
  Recipient-Resolver fächert Events least-privilege auf — ein Nutzer wird nur über
  Server benachrichtigt, die er sehen darf (Admin oder via `user_servers`
  zugeordnet). Neue Endpoints: `POST /api/internal/events` (Event-Ingress vom
  Monitoring-Dienst, `X-Internal-Key`), `GET /api/notifications` (+ `/unread-count`,
  `/read`) als eigener Feed, und `GET`/`PUT /api/users/me/notification-prefs`
  (Self-Service-Einstellungen). Das Monitoring bleibt reine Event-Quelle; die
  Empfänger-Auflösung liegt nur im Server, wo die User↔Server-Zuordnung existiert.
  Noch ohne UI und ohne tatsächlichen Versand (folgt in späteren Phasen).
- **Monitoring speist den Hub (Phase B1).** Jeder Check-Statuswechsel wird
  zusätzlich zum regelbasierten Webhook-/E-Mail-Versand an `POST
  /api/internal/events` des Servers gepusht (`SERVER_HUB_URL`, Auth via
  `MONITOR_API_KEY` als `X-Internal-Key`, best-effort). Die Event-Severity ist der
  schlimmere der beiden Zustände, damit eine Entwarnung (`warning→ok`) auch
  Abonnenten mit Schwelle „warning" erreicht.
- **Server-interne Events speisen den Hub (Phase B2).** Der In-Process-Event-Bus
  (`fire_event`) bridged eine kuratierte Auswahl in den Hub: neuer Admin-Benutzer
  (`security`), Server entfernt und FRP-Tunnel angelegt (`lifecycle`). Reine
  CRUD-Events, die der Auslöser selbst verursacht, werden bewusst nicht gespiegelt
  (kein Noise).
- **Desktop: Benachrichtigungs-Glocke, Desktop-Notifications und Self-Service-
  Einstellungen (Phase C).** Eine Glocke mit Ungelesen-Badge im Header öffnet ein
  Panel mit dem Benachrichtigungs-Feed (app-weites Polling, solange eine
  Server-Session aktiv ist). Neue Feed-Einträge erscheinen optional als native
  **OS-Benachrichtigungen** (`tauri-plugin-notification`, opt-in mit
  Permission-Abfrage; ein „Priming"-Schritt verhindert eine Flut beim Start). In
  den Einstellungen kann jeder Nutzer seine **Kontakt-E-Mail** und beliebig viele
  **Regeln** verwalten — Geltungsbereich (alle Server / Tag / einzelner Server),
  Mindest-Schweregrad und Kanal (Glocke immer, E-Mail optional). Telegram ist im
  Datenmodell vorgesehen, aber noch nicht in der Oberfläche.
- **E-Mail-Versand der Benachrichtigungen (Phase D).** Ein APScheduler-System-Job
  (Muster wie der Audit-Retention-Job) leert die `notification_outbox` minütlich
  aus dem Request-Pfad heraus und stellt E-Mails über einen externen SMTP-Relay
  zu (`SMTP_HOST`/`PORT`/`USER`/`PASSWORD`/`FROM`, 587 STARTTLS oder 465 SMTPS).
  Fehlversuche werden mit linearem Backoff bis `NOTIFICATION_MAX_ATTEMPTS` (Default
  5) wiederholt und danach als fehlgeschlagen markiert. Damit ist der MVP-Umfang
  (Glocke + Desktop-Notification + E-Mail) vollständig.
- **Agent-Paket-Repo (apt/dnf-Update-Kanal).** Der AdminHelper-Server stellt selbst
  ein **GPG-signiertes** apt-/rpm-Repo über eine neue **certless Repo-Plane des
  Gateways** bereit (`REPO_PORT`, Default `8445`), sodass Agent-Hosts neue Versionen
  über `apt upgrade` / `dnf upgrade` beziehen statt per manuellem Download — gedacht
  für laufende Updates auf vielen Servern. `release.yml` baut das Repo
  (`apps/agent/build-repo.sh`: `InRelease`/`Release.gpg`, `rpm --addsign` +
  `repomd.xml.asc`, je ein de-/armored Public-Key) und veröffentlicht es als ein in
  `SHA256SUMS` + minisign abgedecktes Asset `adminhelper-agent-repo-<tag>.tar.gz`.
  `install.sh`/`update.sh` ziehen das Asset best-effort nach `./repo` (in-place, der
  Live-Bind-Mount bleibt gültig). Signatur via neuem Secret `REPO_GPG_PRIVATE_KEY`:
  ohne Schlüssel wird das Asset mit Warnung übersprungen und `/repo` liefert `404` —
  kein Bruch. Onboarding (apt `deb822`/`signed-by` + dnf `.repo`, GPG-Fingerprint als
  Vertrauenswurzel, TLS via CA-Pinning oder `Verify-Peer`) unter *Agent-Deployment*;
  Maintainer-Setup unter *CI/CD & Release*. Test: `scripts/tests/repo_build_test.sh`.

### Changed

- **Server-Auth-Gate-Test robust gegen FastAPI-Versionssprünge.**
  `test_route_auth_gate.py` nahm an, `app.routes` liste eingebundene Router flach
  als `APIRoute`. FastAPI 0.138 kapselt jedes `include_router()` in ein opakes
  `_IncludedRouter` → der Test sammelte 0 Routen (false-positive „route no longer
  exists", und schlimmer: der Guard-Test wäre still leergelaufen). Jetzt rekursiver
  `_collect_api_routes()` für beide Strukturen (≤0.136 flach + ≥0.138 verschachtelt)
  plus Emptiness-Guard. Trat nur in CI auf, weil der Test-Job über `requirements.in`
  die *neueste* FastAPI zieht, nicht die gehashte Lock.

### Removed

- **Desktop-E2E (tauri-driver-Smoke) aus der CI entfernt.** Die headless-WebKit-Kette
  (tauri-driver → WebKitWebDriver → WebKit unter xvfb) driftet mit dem GitHub-Runner-
  Image + ungepinnten Upstream-Tools und färbte `main` rot ohne echten Defekt — und
  überdeckte dabei einen realen Bug. Der Smoke-Test läuft jetzt wie die Desktop-
  `*.live.js`-Journeys **lokal/manuell** (`cd apps/desktop/e2e && xvfb-run -a npm test`).

### Security

- **starlette 1.2.1 → 1.3.1** in server + monitoring (gehashte Lock neu generiert):
  behebt CVE-2026-54282 und CVE-2026-54283. Vom wöchentlichen Dependency-Audit
  (`pip-audit`) erkannt; `fastapi` zieht dabei auf `0.138.0` mit (der Auth-Gate-Test
  ist bereits dafür robust, siehe Changed). `pytest` server (291) + monitoring (138)
  grün gegen die neuen Versionen, `pip-audit` ohne Befund.
- **undici 7.27.1 → 7.28.0** in `apps/desktop/ui` (transitiv über `jsdom`, eine
  Dev/Test-Abhängigkeit — nicht im Production-Bundle): behebt eine high-severity
  Sammel-Lücke (TLS-Bypass, Cache-Disclosure, Header-Injection, DoS u.a.). Nicht-
  breaking via `npm audit fix`; `npm audit --audit-level=high` ohne Befund, vitest
  (200 Tests) grün.
- **quinn-proto 0.11.14 → 0.11.15** im Desktop-Backend (transitiv über `quinn`):
  behebt RUSTSEC-2026-0185 (Remote Memory Exhaustion durch unbegrenztes
  Out-of-order-Stream-Reassembly). Patch-Bump via `cargo update -p quinn-proto`
  (nur diese Crate); `cargo check` grün, vollständige fmt/clippy/test-Prüfung im
  CI-Rust-Job.

## [0.37.2] - 2026-06-20

### Added

- **Desktop: Live-E2E für den Settings-Moduswechsel** (`settings-mode.live.js`,
  läuft mit im `desktop_e2e_crud.sh`-Boot). Wechsel server→local in den
  Einstellungen beendet die Server-Session und lädt in den Local-Mode; verifiziert
  wird der beobachtbare Seiteneffekt: das Modus-Badge wechselt und die server-only
  Navigation (Infrastruktur) verschwindet.
- **Desktop: Live-E2E für „SSH/Web/RDP über FRP-Tunnel" (voller End-to-End-
  Durchstich)** (`desktop_e2e_connect_tunnel.sh`, `tunnel-connect.live.js`). Die App
  enrollt, die Tunnel connecten, und das Öffnen der per `connection_id` verknüpften
  Connections schickt `ssh`/Browser/`xfreerdp3` über die **ganze FRP-Strecke**:
  Desktop-frpc-Visitor → frps → **ein agent-frpc mit drei STCP-Proxies** → echte
  `sshd`-/`nginx`-/`xrdp`-Container (zielseitig verifiziert). Der STCP-Server ist
  ein echter Agent, der via Provisioning seine `frpc.toml` + enrollte mTLS-Identität
  bekommt und mit `snowdreamtech/frpc` läuft. Die getunnelten Connections nutzen
  **tote Platzhalter-Ziele**, damit nur der Tunnel-Pfad (nicht ein Direkt-Treffer)
  grün sein kann.
- **Desktop: Live-E2E für „Verbindung öffnen" gegen echte Ziel-Container**
  (`desktop_e2e_connect.sh`). Die App öffnet über die GUI eine **SSH**-Verbindung
  (`openssh-server`), eine **Web**-Verbindung (`nginx`) und eine **RDP**-Verbindung
  (`xrdp`; inkl. des Passwort-Prompts, den der Desktop auf Linux für RDP zeigt). Da
  der Desktop `ssh`/Browser/`xfreerdp3` als externe Prozesse startet, wird
  zielseitig verifiziert: **sshd-Log** (eingehende Verbindung), **nginx-Access-Log**
  (Web-Fetch via `xdg-open`-Shim) bzw. **xrdp-Log** (RDP-Handshake) — analog zur
  frps-Log-Prüfung des Tunnel-Tests.
- **Desktop: Live-E2E für die Monitoring-Check-Journey** (`monitoring-check.live.js`,
  `desktop_e2e_monitoring.sh`) gegen **echte Agent-Daten**: ein echter Agent pusht
  Metriken, dann legt die App über die GUI einen `agent_resources`-Check an, der
  nach dem Reload aus dem Monitoring-Dienst (GUI → `api_proxy` → Gateway → Server →
  Monitoring) erscheint.
- **Integrations-E2E: echter Agent → Monitoring-Pipeline**
  (`scripts/tests/agent_monitoring_test.sh`). Mehrere echte Go-Agenten (in
  Wegwerf-Containern) provisionieren gegen den Test-Stack, **enrollen ein
  mTLS-Client-Zertifikat** und pushen Metriken; verifiziert beidseitig (Agent-Log
  „Report gesendet" + `POST /agent/{id}/report 200` im Monitoring-/Server-Log).
  Deckt die bisher nur unit-getestete Provision→Enroll→Push-Kette real ab. Das
  Test-Overlay baut den Monitoring-Dienst jetzt ebenfalls lokal.
- **Desktop: Live-E2E für die Provisioning-Journey** (`provisioning.live.js`).
  Die echte App fordert über die GUI einen Agent-Enrollment-Token an; der Server
  stellt ihn aus, die GUI listet ihn (Round-Trip). Läuft im selben
  `desktop_e2e_crud.sh`-Boot wie die GUI-CRUD-Journeys.
- **Web: Playwright-CRUD für API-Keys, Hooks, FRP-Config und Audit** (gegen die
  stateful Mocks). API-Keys: anlegen → Secret **genau einmal** im Reveal → Liste →
  löschen. Hooks: Webhook anlegen → Einmal-Token → löschen. FRP-Config: anlegen →
  bearbeiten mit **leerem Token** (der gespeicherte Secret bleibt, da das Modal
  `auth_token` weglässt). Audit: Einträge anzeigen + nach Aktion filtern. Der
  `mocks.ts`-In-Memory-Store deckt dafür `/api/api-keys`, `/api/hooks`,
  `/api/frp/server-config` und `/api/audit` ab.
- **Web: Unit-Tests für die Stores `users`, `hooks`, `frpConfig`** (analog
  `apikeys`). Der fehleranfällige Kern: optimistische Listen-Updates **per ID**
  (nicht per Index), `hooks.toggle` als Partial-Merge nur auf den passenden Hook,
  und `frpConfig.save`, das je nach vorhandener Config auf create vs. update routet.
- **Monitoring: Alert-Korrektheit** — die Schwellwert-Logik der Checker
  (`AgentResourcesChecker`/`SmartHealthChecker` `evaluate`: ok→warning→critical-
  Eskalation, `>=`-Grenze, Pseudo-FS-Filter, Temp-Overrides bzw. Disk-Typ-Temp,
  smartctl-Exit-Bitflags, NVMe-Wear (**invertiertes** `available_spare` +
  `percentage_used`/media_errors) und ATA-Wear (reallocated/pending/spin-retry))
  und die bisher ungetesteten Alert-Dispatch-Pfade
  (`_dispatch` fail-closed bei kaputter `channel_config`/unbekanntem Kanal; der
  Email-Kanal mit Empfänger-Parsing und SMTP-Host-Pflicht).

- **Desktop: Live-E2E für die GUI-CRUD-Journeys** (`scripts/tests/desktop_e2e_crud.sh`
  + `*-crud.live.js`). Die echte App legt über die GUI gegen den echten Stack eine
  Verbindung an, benennt sie um und löscht sie; legt einen Tunnel an, benennt ihn um
  und löscht ihn; legt einen Server an und löscht ihn. Jeder Schritt wird durch die
  neu geladene Liste verifiziert (GUI → `api_proxy` → Gateway → Server → Postgres →
  GUI). Geteilte Login-/Navigations-Helfer unter `apps/desktop/e2e/test/lib/`.

- **Test-Abdeckung der bisher ungetesteten Server-Module `ansible` und
  `hooks`.** Ansible (vorher 0 Tests): Admin-Authz, der Dateinamen-Allowlist als
  Path-Traversal-Guard, YAML-Validierung beim Schreiben, und der
  Create→Content-lesen→Update→Delete-Roundtrip (Inhalt auf Disk). Hooks:
  Admin-Authz, die typ-spezifische Create-Validierung (webhook/event/schedule),
  und — bisher ungeprüft — dass der Event-Dispatch (`_run_event`) wirklich nur die
  passenden, aktivierten Event-Hooks auslöst.

- **Erweiterte Unit-Test-Abdeckung an den von CLAUDE.md priorisierten Stellen.**
  Gezielt die echten Lücken geschlossen (vorhandene Abdeckung — FRP-Config-
  Generierung, `require_scope`-Enforcement, Tunnel-Auflösung — blieb unangetastet):
  Server-Authz für das `servers`-Modul (non-admin → 403, ergänzt das Struktur-Gate
  semantisch), die reinen Schema-Validatoren `_validate_server_name`
  (Pfad-/TOML-Injection-Guard) und `_validate_tags`, sowie IP-Filter-Proxy-Header-
  Spoofing (`resolve_client_ip` mit `TRUSTED_PROXIES`). Go-Agent: `round1`/`round2`
  (Metrik-Rundung, betrifft jeden Push) und `baseURL` (mTLS-Origin-Ableitung).
  Desktop-Rust: die RDP-Credential-Cache-Key-Helfer (`rdp_storage_key`,
  case-insensitiv, Port-Default). Monitoring: Ping-RTT-Parsing + Target-Hardening
  (Command-Injection-Guard) und `format_line`-Abweisung nicht-finiter Werte
  (inf/nan würden den Batch vergiften). Web: der `apikeys`-Store (das Einmal-Secret
  aus `create()` wird zurückgegeben, landet aber nie in der sichtbaren Liste).

- **Desktop: Live-E2E „Verbindung mit Tunnel über die GUI anlegen" gegen einen
  echten Stack.** `scripts/tests/desktop_e2e_live.sh` fährt den realen Backend-
  Stack permissiv hoch, seedet Admin + Server + FRP-Config per Admin-API, und
  treibt die **echte** Desktop-App (WebdriverIO + tauri-driver): Login durch das
  nginx-Gateway (TOFU, self-signed vertraut), dann im Infrastruktur-Hub einen
  Tunnel anlegen. Damit ist erstmals der volle Pfad GUI → `api_proxy` → Gateway →
  Server → Postgres abgedeckt (vorher endeten die Tests an der IPC-Grenze). Doppelt
  verifiziert: der Tunnel erscheint in der GUI **und** wird unabhängig per
  Server-API gegengeprüft. Der App-Keyring wird über eine frische
  D-Bus-Session + leeres `gnome-keyring` isoliert (sonst bricht eine real
  enrollte Identität den Login).

- **Desktop: Live-E2E „Tunnel testen" (starten + verbinden) gegen echtes frps.**
  `scripts/tests/desktop_e2e_tunnel.sh` fährt zusätzlich `frps` hoch, seedet einen
  STCP-Tunnel und mintet einen Enrollment-Token; die App enrollt ein Geräte-Cert,
  loggt sich ein, und der Infrastruktur-Hub startet den Tunnel automatisch.
  Verifiziert wird der **volle PKI-Tunnel-Pfad**: der GUI-Tunnel-Indicator
  erreicht „connected" **und** das frps-Container-Log bestätigt unabhängig, dass
  sich der Desktop-`frpc` per mTLS verbunden hat (ca-issuer-provisioniertes
  frps-Cert, Access-Intermediate-Trust). Damit ist „Verbindung mit Tunnel anlegen
  **und** testen" über die echte GUI vollständig abgedeckt.

- **Desktop: echtes End-to-End-Test-Harness (WebdriverIO + tauri-driver).** Neu
  unter `apps/desktop/e2e/`: treibt die gebaute Tauri-App über eine echte
  WebDriver-Session (auf Linux via `tauri-driver` → `WebKitWebDriver`). Erster
  Test ist ein Smoke-Test (App startet, Fenster „AdminHelper", Svelte-UI mountet)
  — die billigste sinnvolle E2E-Stufe, ohne Backend. Als eigener CI-Job
  (`desktop-e2e`, unter `xvfb`) auf `main`-Pushes + manuell, kein PR-Gate. Der
  Live-„Verbindung-mit-Tunnel-anlegen-und-testen"-Flow (braucht den echten Stack
  aus dem From-outside-Test plus `frpc`) baut auf diesem Harness auf und ist der
  nächste Schritt.

- **Desktop: Komponententests für den „Verbindung-mit-Tunnel-anlegen"-Flow.**
  `TunnelModal` und `ServerConnectionModal` werden jetzt als echte Komponenten
  gemountet (`@testing-library/svelte`), das Formular ausgefüllt und abgesendet,
  und das an den Server gehende API-Payload sowie die bedingten Felder geprüft
  (STCP↔HTTPS bzw. SSH↔Web — inkl. Validierungs-Abbruch). Der IPC-/Server-Rand
  ist gemockt, also ohne Tauri-Runtime/Server/frpc lauffähig im bestehenden
  `desktop-ui`-Job. Deckt die „anlegen"-Logik ab; das tatsächliche Öffnen/
  Verbinden bleibt plattformspezifisch (manuell verifiziert) bzw. ist über die
  Rust-Tunnel-Auflösungs-Tests und den From-outside-Integrationstest abgedeckt.

- **From-outside-Integrationstest gegen das echte Gateway.** Bisher fuhr kein
  Test den echten Multi-Container-Stack hoch — CI baute nur Images und prüfte
  Komponenten isoliert (gemockt bzw. mit DB-Override). Neu schließt
  `scripts/tests/integration_stack_test.sh` genau diese Lücke mit **einem**
  Pfad: Er startet den realen Stack (Postgres, Redis, Server, ca-issuer,
  nginx-Gateway) mit erzwungenem mTLS (`MTLS_ENFORCE=true`) und redet
  ausschließlich von außen durch das Gateway — mintet einen Enrollment-Token
  in-container, enrollt von außen per CSR über die certless Enroll-Plane (:8444)
  ein Client-Cert, und prüft den ganzen Pfad: certless → vom Gateway abgewiesen
  (400), Cert ohne JWT → 401, Cert + Login → JWT, Cert + JWT → 200. Hermetisch
  (Wegwerf-Secrets, lokal gebaute Images, isolierte Ports/Volumes, `down -v`).
  Als eigener CI-Job auf `main`-Pushes + manuell (bewusst noch kein PR-Gate, da
  Image-Build + 5-Container-Boot).

- **Struktur-Gate gegen „neuer Router ohne Auth".** Ein neuer pytest-Test
  (`apps/server/tests/test_route_auth_gate.py`) introspiziert beim Lauf alle
  gemounteten `/api`-Routen und schlägt fehl, sobald eine Route weder eine
  Auth-Dependency (`require_scope` / `get_current_user` / `get_current_admin` /
  `ApiKeyOrUser`) im Dependency-Baum trägt noch in einer kurzen, begründeten
  Allowlist bewusst öffentlicher Routen steht. Damit kann ein Modul-Router, der
  in `app.main` ohne Scope-Guard eingebunden wird, nicht mehr unbemerkt
  ungeschützt durchrutschen — der Fehler fällt im bestehenden Server-`pytest`-Job
  auf (in-process, keine DB, ~0,2 s) statt erst im Betrieb auf. Strukturell, nicht
  semantisch: geprüft wird, *ob* ein Guard verdrahtet ist, nicht *ob* er greift —
  Letzteres deckt der Integrationstest gegen das Gateway ab.

### Fixed

- **Desktop: Tunnel- und Verbindungs-Formular im Infrastruktur-Hub waren unbedienbar.**
  Beim Öffnen von „Tunnel anlegen" bzw. „Verbindung anlegen" (Server-Detail) lief der
  Initialisierungs-`$effect` in eine Endlosschleife (`effect_update_depth_exceeded`): Er
  wies `form` ein frisches Objekt zu und las direkt danach `form.tags` — wodurch der Effect
  von dem State abhing, den er selbst schreibt, und sich bei jedem Lauf neu triggerte.
  Svelte brach nach 10 Durchläufen ab und zerstörte dabei die Reaktivität des Modals:
  Eingabefelder *und* alle Buttons (inklusive „Abbrechen"/„×") waren tot. `tagsInput` wird
  jetzt aus dem lokalen, frisch erzeugten Objekt abgeleitet statt aus dem `form`-State.
  (Das Server-Anlegen war nicht betroffen — `ServerModal` leitete schon aus der lokalen
  Quelle ab.) Abgesichert durch erste mountende Komponenten-Tests (`@testing-library/svelte`),
  die den Crash reproduzieren — bislang wurde keine Svelte-Komponente in Tests gemountet.

## [0.37.1] - 2026-06-16

### Fixed

- **Desktop: Zertifikat-/Identitäts-Reset jetzt direkt am Login-Screen.** Ein TOFU- bzw.
  CA-Pin-Mismatch (z. B. nach einer Server-Neuinstallation) trat genau dort auf, wo die
  Reset-Aktionen *nicht* erreichbar waren: am Login-/Verbinden-Screen — die Einstellungen
  (und damit beide Reset-Buttons) gibt es erst nach erfolgreichem Login. Der Login-Screen
  zeigt jetzt bei einem Pin-/Identitäts-Fehler einen passenden Reset-Button direkt unter
  der Fehlermeldung („Gepinntes Server-Zertifikat zurücksetzen" bzw. — bei registriertem
  Gerät — „Geräte-Registrierung zurücksetzen"); danach neu verbinden.
- **Release-Signatur funktionsfähig (Key-Rotation).** Der minisign-Signing-Key wurde durch
  einen **passwortlosen** Key ersetzt — der bisherige war passwortgeschützt, was den CI-Schritt
  `Sign SHA256SUMS` scheitern ließ (kein interaktives Passwort möglich; 0.36.0/0.37.0 blieben
  daher unsigniert/ohne Release). Der gepinnte `MINISIGN_PUBKEY` in `scripts/install.sh` und
  `scripts/update.sh` wurde entsprechend rotiert. Der vollständige Signier-Pfad (base64-Dekodierung
  → `minisign -S` ohne Prompt → Verify gegen den gepinnten Pubkey) wurde lokal nachgestellt.

## [0.37.0] - 2026-06-16

### Added

- **Desktop: „Geräte-Identität zurücksetzen".** Neuer Einstellungs-Button (Modus
  *Server*, nur sichtbar wenn das Gerät registriert ist) für den Recovery-Fall nach
  einer Server-Neuinstallation / neu erzeugten PKI. Löscht das enrollte mTLS-Geräte-
  Zertifikat **und** den TOFU-Zertifikat-Pin in einem Schritt — danach pinnt/registriert
  sich das Gerät beim nächsten Verbinden neu. Mit Gefahren-Bestätigungsdialog.

### Changed

- **Desktop: eindeutige Fehlermeldung bei CA-Pin-Mismatch.** Präsentiert der Server
  ein Zertifikat, das nicht mehr zur bei der Registrierung gepinnten CA passt (z. B.
  nach einem Reinstall), liefert der mTLS-Client jetzt eine explizite, gefahren-bewusste
  Meldung (mögliche MITM-Attacke + Verweis auf *Geräte-Identität zurücksetzen*) statt des
  rohen rustls-Fehlers — analog zur bestehenden TOFU-Leaf-Pin-Meldung.

### Fixed

- **Release-Signatur: base64-Interpretation des Secrets.** Das `MINISIGN_SECRET_KEY`-Secret
  wird jetzt als base64-kodiertes Key-File interpretiert (`base64 -w0 minisign.key`) — der
  rohe, mehrzeilige Key wurde im Secret-Store verstümmelt. Hinweis: Das Signieren der
  `SHA256SUMS` erfordert zusätzlich einen **passwortlosen** minisign-Key (`minisign -G -W`),
  da der CI-Schritt das Passwort nicht interaktiv liefern kann.

## [0.36.0] - 2026-06-15

Ergebnis eines projektweiten Audits (Bugs, Verbesserungen, Sicherheit) über alle
fünf Code-Komponenten. Alle Punkte sind durch Tests bzw. die jeweilige
Verifikations-Suite (pytest/ruff, go test/vet, cargo clippy/test, svelte-check/vitest)
abgesichert.

### Security

- **FRP-Secrets nicht mehr lesbar zurückgegeben.** `GET /api/frp/server-config`
  maskiert `auth.token` und Dashboard-Passwort; das Web-Modal füllt sie beim
  Bearbeiten nicht mehr vor (leer lassen = unverändert) und zeigt den Auth-Token
  als Passwortfeld.
- **Monitoring-Webhooks SSRF-geprüft.** Alert-Webhook-Ziele werden — wie bereits
  der HTTP-Checker — gegen private/reservierte Adressen geprüft und ohne Redirects
  gesendet. SMTP-Port 465 nutzt jetzt implizites TLS (`SMTP_SSL`) statt eines
  Klartext-Logins.
- **Desktop: Token-Ziel-Pinning gehärtet.** `api_proxy`/`authenticated_get` pinnen
  die *finale* Ziel-URL an den angemeldeten Server und weisen Pfade ab, die die
  URL-Authority umschreiben (führendes `@`, `\`, `://`) — verhindert JWT-Leak an
  fremde Hosts. TOFU-Pinning ist jetzt race-frei (atomares `load_or_store`); rohe
  Server-Fehler-Bodies werden vor Anzeige/Log redigiert und gekürzt.
- **Web: Access-Token nur noch im Speicher** (nicht mehr in `localStorage`) — eine
  XSS-Lücke kann ihn nicht mehr aus persistentem Storage exfiltrieren; nach einem
  Reload wird die Session aus dem HttpOnly-Refresh-Cookie wiederhergestellt.
- **`restore.sh` weist manipulierte Backups ab** (absolute/`../`-Pfade, Sym-/
  Hardlink-Member) und entpackt mit `--no-same-owner` — schließt eine
  Path-Traversal-Lücke beim Wiederherstellen eines untergeschobenen Backups.
- **Docker-Base-Images per Digest gepinnt.** `postgres`, `redis`, `nginx`,
  `python`, `node`, das internet-facing `snowdreamtech/frps` und
  `victoria-metrics` sind in `docker-compose.yml` und den Dockerfiles zusätzlich
  zum Tag per `@sha256:`-Index-Digest fixiert — ein neu gepushter Tag kann nicht
  mehr still ein anderes Image unterschieben (reproduzierbare Builds). Der
  CI-FRP-Pin-Check ist digest-robust gemacht.
- **Signierte Releases (Supply-Chain).** Docker-Images werden schlüssellos mit
  cosign (GitHub-OIDC) signiert und tragen SLSA-Provenance + SBOM. Die
  Release-`SHA256SUMS` werden mit minisign signiert (`SHA256SUMS.minisig`);
  `install.sh`/`update.sh` prüfen die Signatur gegen einen im Skript gepinnten
  Public Key, bevor sie den Checksummen vertrauen — die `curl|bash`-Kette belegt
  jetzt Authentizität, nicht nur Transport-Integrität. Scharf geschaltet (Public
  Key gepinnt, Signing-Secret hinterlegt); greift ab dem nächsten Release. Der
  hermetische Update-Sandbox-Test verifiziert den signierten Pfad end-to-end.

### Fixed

- **Migrations-Sicherheit (Server).** `alembic/env.py` importiert jetzt die
  Module `audit`, `enrollment` und `provisioning`; ein künftiges
  `--autogenerate` schlägt sonst `drop_table` für `audit_log`,
  `enrollment_tokens` und `revoked_identities` vor (Datenverlust).
- **Monitoring `agent_ping` korrekt.** Wird nicht mehr zusätzlich im Push-Endpoint
  ausgewertet (dort war die Staleness immer ~0 → fälschlich „ok"); der Scheduler
  ist die einzige Quelle.
- **Monitoring-Robustheit.** Ein einzelner Check mit defekter `config` bricht nicht
  mehr die Auswertung aller Checks eines Servers ab; `process_alert` committet die
  geteilte Session nicht mehr vorzeitig (sauberes Rollback im Fehlerfall).
- **Alert-Versand blockiert den Agent-Push nicht mehr.** Webhook/SMTP-Benachrichtigungen
  werden im Agent-Push-Pfad erst *nach* der Antwort als Hintergrund-Task versendet
  (eigene DB-Session); ein langsamer/hängender Webhook- oder SMTP-Server kann den
  Push-Request — und damit bei 250–500 Agents den Worker-Pool — nicht mehr blockieren.
- **Doppelte Port-/Namensvergabe verhindert (Server).** DB-Constraints für STCP-
  `visitor_port` und Tunnel-/Benutzernamen schließen ein TOCTOU-Fenster; Konflikte
  werden als 409 statt als 500 gemeldet.
- **Connection-Import validiert.** Jeder Eintrag wird gegen `ConnectionCreate`
  geprüft (422 mit Fehlerliste) statt ungültige Werte zu persistieren oder mitten
  im Lauf 500 zu werfen; ein `replace`-Import mit fehlerhaftem Input löscht nichts.
- **Agent.** Kritische NVMe-SMART-Nullwerte (z. B. „Spare aufgebraucht") fallen
  nicht mehr aus dem Report; der Windows-Dienst reagiert beim Stop sofort
  (Push-Retry-Backoff per Context abbrechbar); der Windows-FRP-Sync bricht nicht
  mehr bei jeder Config-Änderung an einem nicht registrierten Dienst ab;
  PKI-Dateien werden mit geprüftem Close + `fsync` geschrieben; Proxmox-Backup-
  Index nutzt den echten Node-Namen statt `localhost`; OS-Info im Diagnose-Bericht
  funktioniert auch unter Windows.
- **Desktop-UI.** Beim schnellen Serverwechsel zeigen die Tabs keine Daten des
  falschen Servers mehr (Out-of-order-Fetches); die Monitoring-Sparkline lädt bei
  Zeitraum-/Check-Wechsel neu; ein RDP-Kindprozess wird bei fehlgeschlagenem
  Passwort-Stdin sauber beendet; die „vor X min"-Anzeige auf dem Dashboard wechselt
  jetzt sofort die Sprache (reaktiver Übersetzer statt Snapshot).
- **Web.** `ConfirmDialog` hängt nicht mehr bei überlappenden Aufrufen; Audit- und
  FRP-Status-Listen zeigen bei schnellem Filtern keine veralteten Antworten mehr;
  der Login zeigt bei falschen Zugangsdaten die Server-Meldung statt „Sitzung
  abgelaufen".
- **Diverse Robustheit.** inf/nan-Metrikwerte werden vor dem Line-Protocol verworfen;
  die Pagination spart die `COUNT(*)`-Query, wenn ohne Limit/Offset gelistet wird;
  Hook- und Tunnel-Updates re-validieren ihre Eingaben (kein 500 bei ungültigem
  Cron/`tunnel_type`); ein N+1 im FRP-Bulk-ZIP ist behoben; der Redis-Increment im
  Agent-Ingest-Proxy blockiert den Event-Loop nicht mehr.

## [0.35.0] - 2026-06-15

### Changed

- **Einheitliches, lesbares Logging in Server und Monitoring.** Beide Dienste
  konfigurieren das Logging jetzt zentral mit Zeitstempel, Level und Logger-Name
  (`2026-06-15 11:25:53 INFO     adminhelper.auth …`) auf stdout — sichtbar via
  `docker compose logs`. Der Server hatte zuvor **gar keine** Logging-Konfiguration:
  alle `INFO`-Meldungen wurden verworfen, Warnungen/Fehler kamen ohne Zeitstempel.
  uvicorn-Zugriffs-/Fehlerlogs laufen über dasselbe Format. Die Ausführlichkeit ist
  über die Env-Variable `LOG_LEVEL` steuerbar (Default `INFO`).
- **Begrenzte Container-Logs (Log-Rotation).** `docker-compose.yml` cappt jeden Service
  über den Docker-`json-file`-Treiber (`max-size: 10m`, `max-file: 5` → max. 50 MB/Service)
  via `x-logging`-Anker — verhindert, dass `docker compose logs` ungebremst die Platte
  füllt. `LOG_LEVEL` ist als `.env`-Knopf in der Compose dokumentiert (Default `INFO`).
- **Agent: strukturiertes Logging mit rotierender Logdatei.** Der Go-Agent nutzt jetzt
  `log/slog` (Level via `LOG_LEVEL`-Env oder `--log-level`) und schreibt zusätzlich zu
  stdout/journal in eine größenrotierte Datei (`/var/log/adminhelper/agent.log` bzw.
  `%ProgramData%\AdminHelper\logs\agent.log`, 10 MB × 5, komprimiert) — eine durchgehende
  Spur für Fehler-Reports. Die zuvor **doppelte** `logMsg`-Implementierung (frpc + monitor)
  entfällt; Logzeilen tragen jetzt Level + Komponente. Neue Abhängigkeit:
  `gopkg.in/natefinch/lumberjack.v2`.

### Added

- **Audit-Trail (wer hat wann was getan).** Neue **append-only** `audit_log`-Tabelle
  protokolliert sicherheits- und änderungsrelevante Aktionen mit Actor (User *oder* API-Key),
  Quell-IP und Zeitstempel: Connections (anlegen/ändern/löschen **und Nutzung** über das
  `/touch`, das der Desktop beim Verbinden aufruft), Server, Benutzer, API-Keys,
  FRP-Configs/Tunnel und Ansible-Playbooks sowie Login (Erfolg/Fehlschlag), Logout und
  Erst-Admin-Bootstrap. Einsehbar über die neue admin-only Web-Ansicht **„Audit-Log"**
  (filterbar nach Actor/Objekt/Aktion) bzw. `GET /api/audit` (paginiert). Das Schreiben ist
  best-effort und kann die auditierte Aktion nie brechen; der Actor wird über `request.state`
  gebunden (nicht contextvars, die in synchronen Endpoints verloren gehen). Ein täglicher
  System-Job löscht Einträge älter als `AUDIT_RETENTION_DAYS` (Default 365, `0` = unbegrenzt) —
  der einzige Löschpfad der append-only Tabelle.
- **Diagnose-Bundle für Bug-Reports (`scripts/diagnostics.sh`).** Erzeugt auf dem Server-Host
  ein **redaktiertes** `tar.gz` (Versionen, OS/Docker, `docker compose ps`, pro-Service-Logs,
  `compose.yml`, sanitisierte `.env`), das der Admin durchsieht und an ein GitHub-Issue hängt.
  Secret-Werte (SECRET_KEY, Passwörter, API-Keys, JWT-/Bearer-Tokens) werden automatisch
  maskiert (Best-effort). Dazu ein GitHub-Issue-Template; das Skript ist im Runtime-Bundle
  enthalten; ein hermetischer Redaction-Test läuft im CI. Ersetzt das in der Doku erwähnte,
  nie implementierte `app.cli support-bundle`. Der Go-Agent bringt analog
  `adminhelper-agent diagnostics` mit (Version, OS, Config ohne Secrets, Log-Auszug; redaktiert).
  Der **Desktop-Client** loggt jetzt in eine rotierende Datei (+ Panic-Hook) und bietet unter
  Einstellungen → Diagnose einen „Diagnose-Bericht" (Version, OS, Log-Auszug; redaktiert).

## [0.34.0] - 2026-06-15

### Changed

- **Release-gebundener Update-Mechanismus (`scripts/update.sh`).** Jedes Release legt
  jetzt ein **verifiziertes Runtime-Bundle** bei (`adminhelper-runtime-vX.Y.Z.tar.gz`:
  `docker-compose.yml`, alle Ops-Skripte, `MANIFEST.sha256`, `VERSION`). `update.sh`
  löst die Zielversion auf, lädt **genau dieses eine Asset**, prüft es gegen die
  `SHA256SUMS` des Release und tauscht die Laufzeit-Dateien **atomar** — so landet jede
  Datei-Änderung eines Release (neue/geänderte/entfernte Skripte, neue Compose)
  zuverlässig auf dem Host; „welche Dateien zu Release X gehören" steht im Release, nicht
  im Skript. Ein nacktes `./scripts/update.sh` geht auf das **neueste veröffentlichte
  Release** (Prereleases ausgenommen) und verweigert einen stillen Downgrade; `--ref
  vX.Y.Z` pinnt gezielt, `--redeploy` zieht nur die gepinnten Images neu, `--check` ist
  ein Trockenlauf. Vor dem Tausch wird gesichert (Daten **und** ein Laufzeit-Snapshot);
  schlägt der Healthcheck fehl, rollt das Skript Laufzeit-Dateien **und** Image-Pins
  automatisch zurück (`--no-rollback` zum Debuggen). Der Updater **aktualisiert sich
  selbst** (Re-exec in die neue `update.sh` aus dem Release). Behebt, dass neu
  hinzukommende Ops-Dateien Alt-Installs früher nie erreichten.
- **`scripts/install.sh` nutzt dasselbe Bundle** und installiert per Default das neueste
  Release (vorher `--ref main`-Default). Release-Tags ohne Bundle (≤ 0.33.0) und
  Branch-Refs fallen auf den Einzeldatei-Download (raw) zurück.

### Added

- **Runtime-Bundle als Release-Asset** samt `MANIFEST.sha256`/`VERSION`; `release.yml`
  baut und hängt es an. Neuer CI-Job `ops-scripts` (shellcheck + hermetischer
  `update.sh`-Sandbox-Test, `scripts/tests/update_test.sh`) und ein Release-Guard, der
  die Desktop-Version in `tauri.conf.json` gegen den Tag prüft.

### Migration

- **Installs vor 0.34.0:** deren altes `update.sh` kennt das Bundle noch nicht. Einmalig
  über den Install-Einzeiler neu holen **oder** ein `./scripts/update.sh --ref v0.34.0`
  fahren — danach ist der Updater self-updating.

## [0.33.0] - 2026-06-14

### Added

- **Deinstallations-Skript `scripts/uninstall.sh`.** Entfernt eine Server-Installation
  restlos: alle Container des Compose-Projekts, das Netzwerk und **alle** Named Volumes
  (inkl. `ca-pki` mit der Root-CA, `postgres-data`, `victoria-data`), dazu die
  Host-Bind-Mounts `./data`/`./certs` und die Secrets-Datei `.env`. Da `./data`/`./certs`
  dem Container-User (`uid 10001`) gehören, löscht das Skript sie als root in einem
  Wegwerf-Container — ohne `sudo` vorauszusetzen. Standardmässig **interaktiv**: das Skript
  fragt für jede Kategorie (Stack, Volumes, `./data`/`./certs`, `.env`, Backups, Images)
  einzeln nach und löscht erst, nachdem alle Fragen beantwortet sind. `./backups/` und die
  Docker-Images bleiben per Default erhalten (`--purge-backups` / `--rmi` entfernen auch sie
  bzw. belegen die jeweilige Frage mit JA vor); `--yes` fährt nicht-interaktiv mit den
  Defaults. Das Skript wird von `install.sh`/`update.sh` mit ausgeliefert, liegt also nach
  der Installation lokal im Install-Verzeichnis.
- **Desktop: lokaler Modus direkt vom Login erreichbar.** Der Login-Screen hat einen
  Knopf „Ohne Server fortfahren (nur lokale Verbindungen)", der in den lokalen Modus
  wechselt (reine Verbindungs-Verwaltung, keine Anmeldung). Bisher war der Login-Screen
  eine Sackgasse, sobald der Client im Server-Modus war — der Modus-Umschalter lebte nur
  in den Einstellungen innerhalb der App, die ohne Anmeldung nicht erreichbar ist.
- **Desktop: Server-URL und Benutzername werden auf dem Login-Screen vorausgewählt.** Nach
  einer erfolgreichen Server-Anmeldung merkt sich der Client die Server-URL und den
  Benutzernamen (neues Feld `lastUsername`; das Passwort wird **nie** gespeichert) und füllt
  beide beim nächsten Start vor — es muss dann nur noch das Passwort eingegeben werden.

### Changed

- **Desktop verlangt jetzt bei jedem Öffnen ein Passwort (Server-Modus).** Der Client stellt
  beim Start keine gespeicherte Session mehr still aus dem Keyring wieder her. So kann an einem
  entsperrten Rechner niemand ohne Passwort Verbindungen aufbauen oder Einstellungen ändern.
  Die laufende Session erneuert ihre Tokens weiterhin automatisch; nur das Wiederherstellen
  über einen Neustart entfällt. Die mTLS-Geräte-Identität bleibt erhalten.

### Fixed

- **Lokale Verbindungen wurden vom Server-/Sync-Abruf überschrieben.** Alle drei Modi teilten
  sich die Datei `connections.json`; ein Server-Login oder ein Sync überschrieb sie mit den
  abgerufenen Daten, sodass lokale Verbindungen bei einem Wechsel Lokal → Server → Lokal verloren
  gingen. Der lokale Modus hat jetzt einen eigenen Speicher (`connections.local.json`), getrennt
  vom Server-/Sync-Cache (`connections.json`); ein Abruf überschreibt ihn nie. Bestehende lokale
  Daten werden beim ersten Start nach dem Update einmalig migriert.
- **Desktop-Logout überschrieb lokale Verbindungen.** Beim Abmelden leerte der Client den
  Verbindungs-Cache via `saveConnections([])` und überschrieb damit die `connections.json` —
  obwohl diese Datei der Speicher des lokalen Modus ist (Server-Verbindungen liegen nur im
  Speicher). Wer lokale Verbindungen angelegt, sich dann an einem Server an- und wieder
  abgemeldet hatte, verlor sie. Logout leert jetzt nur noch den Speicher.
- **Desktop-Modus-Wechsel ließ eine veraltete Session zurück.** Der Wechsel auf den lokalen
  oder Sync-Modus verwarf die aktive Server-Session nicht. Ein späterer Wechsel zurück auf
  einen (geänderten) Server konnte dadurch Daten vom alten Server laden statt eine frische
  Anmeldung zu erzwingen. Beim Verlassen des Server-Modus wird die Session jetzt verworfen;
  zudem nullt der „Abmelden"-Knopf im Einstellungs-Dialog jetzt auch die In-Memory-Session.

## [0.32.1] - 2026-06-13

### Fixed

- **Logout sperrte unter enforced mTLS aus.** Der Desktop-Client löschte beim Logout die
  enrollte mTLS-Identität (Key+Cert+CA). Da das Cert unter erzwungenem mTLS nötig ist, um den
  Login-Endpoint auf `:443` überhaupt zu erreichen, konnte man sich danach nicht mehr anmelden
  (Gateway: „no required SSL certificate was sent") — bis ein Admin ein neues Enrollment-Token
  mintete. Logout verwirft jetzt nur die Session-Tokens; das Geräte-Cert bleibt erhalten.

## [0.32.0] - 2026-06-13

### Added

- **Desktop-Client wird zum Verwaltungs-Cockpit (Infrastruktur-Hub).** Der Desktop ist nicht mehr
  nur Verbindungs-Launcher: Im neuen server-zentrischen „Infrastruktur"-Bereich (nur im
  Server-Modus) verwaltet der Admin sein Server-Inventar und pro Server in Tabs dessen
  Verbindungen, FRP-Tunnel, Monitoring und Provisionierung.
  - **Server-Inventar:** Server anlegen/bearbeiten/löschen.
  - **Provisionierung:** Einmal-Token erzeugen + Agent-`provision`-Befehl pro Server anzeigen.
  - **Verbindungen:** server-seitiges CRUD pro Server (ssh/rdp/vnc/web/custom). Auch der
    Verbindungs-Launcher schreibt im Server-Modus jetzt server-seitig statt nur lokal.
  - **FRP-Tunnel:** Tunnel pro Server anlegen/bearbeiten/löschen (STCP/HTTPS); die
    FRP-Server-Konfiguration wird als Auswahl referenziert (bleibt Web-Admin-Sache).
  - **Monitoring vollständig bearbeitbar:** Checks pro Server (alle Check-Typen mit Konfiguration)
    sowie Alert-Regeln und Templates fleet-weit auf der Monitoring-Seite.
  - **Ansible:** Playbooks im Desktop anlegen/bearbeiten/löschen (zusätzlich zum bestehenden
    Ausführen).

### Changed

- **Web-Admin-Panel ist jetzt reine Instanz-Verwaltung.** Es behält Benutzer-, API-Key-,
  Hook-Verwaltung und die FRP-**Server-Konfiguration**; die operative Fleet-Arbeit ist in den
  Desktop-Client umgezogen. Die Standard-Seite nach dem Login ist jetzt „Benutzer". Die
  User↔Server-Zuweisung bleibt im Web (im Benutzer-Dialog, gespeist aus einer reinen
  Lese-Server-Liste).

### Removed

- **Operative Funktionen aus dem Web-Frontend entfernt** (in den Desktop-Client umgezogen):
  Server-Inventar, Verbindungs-Verwaltung, FRP-**Tunnel**-Verwaltung, Monitoring-Bearbeitung
  (Checks/Alerts/Templates) und Ansible-Playbook-Verwaltung. **Breaking** für reine
  Web-Nutzer: diese Aufgaben erfolgen nun im Desktop-Client.

## [0.31.0] - 2026-06-13

### Added

- **Browser-`.p12`-Export mit Speicherort-Auswahl.** Beim Export des Browser-Zertifikats
  (Desktop → Einstellungen) öffnet der Client jetzt einen nativen Speichern-Dialog
  (`tauri-plugin-dialog`) — der Nutzer wählt, wohin die `.p12` geschrieben wird (Default-Name
  `adminhelper-browser.p12`), statt sie in einem versteckten App-Daten-Verzeichnis suchen zu
  müssen. Abbruch des Dialogs bricht ohne Enrollment ab. (Das `.p12`-Format bleibt unverändert
  — Legacy, aber von allen aktuellen Browsern akzeptiert.)

## [0.30.4] - 2026-06-13

### Fixed

- **Re-Install über ein altes Postgres-Volume scheiterte unverständlich.** Ein
  `postgres-data`-Volume aus einem abgebrochenen Versuch ist mit einem anderen
  `POSTGRES_PASSWORD` initialisiert als eine frisch generierte `.env` (Postgres setzt das
  Passwort nur beim ersten Init) — die DB-Auth scheiterte dauerhaft und die Readiness-Schleife
  lief in einen kryptischen 240-s-Timeout. `install.sh` erkennt jetzt das
  `password authentication failed` und bricht mit klarer Anleitung ab; neues `--reset`-Flag
  räumt vorab `docker compose down -v` weg.

## [0.30.3] - 2026-06-13

### Changed

- **Installs pinnen die Image-Version fest.** `install.sh` schreibt die `*_IMAGE`-Tags in
  `.env` auf die Version, von der installiert wurde (`--ref vX.Y.Z` → `:X.Y.Z`, `main` →
  `:main`), statt am floatenden `:latest` zu bleiben — ein Install ist reproduzierbar und
  springt nie unbemerkt auf eine neue Version bei `docker compose pull`. `update.sh --ref`
  re-pinnt auf die Zielversion; ein nacktes `update.sh` zieht die gepinnte Version neu
  (Upgrade = bewusstes `--ref vNEU`). `:latest` bleibt nur der Compose-Fallback ohne `.env`.

## [0.30.2] - 2026-06-13

### Fixed

- **Einzeiler brach unter `curl | bash` an der ersten Rückfrage ab.** Die interaktiven
  `read`-Prompts (Domain/Passwort/Bestätigung) lasen `stdin` — unter `curl | bash` ist das
  die Script-Pipe, nicht das Terminal, also kam sofort „Abgebrochen" ohne Eingabemöglichkeit.
  Die Prompts kommen jetzt aus `/dev/tty`; ohne Terminal bricht `install.sh` mit einer klaren
  Meldung ab (Hinweis auf `--admin-password … --yes`).

## [0.30.1] - 2026-06-13

### Changed

- **Update-Ablauf dokumentiert.** Die Installations-Doku (DE+EN) beschreibt jetzt den
  `scripts/update.sh`-Ablauf mit seinen zwei Modi — nur Images frischen
  (`./scripts/update.sh`) gegenüber einem Versions-Upgrade mit `--ref` (das die Compose +
  Ops-Skripte für die Zielversion mitzieht) — samt `.env`-Image-Pinning und der
  Selbst-Update-Falle (`update.sh` überschreibt sich nicht selbst).

## [0.30.0] - 2026-06-12

### Added

- **Ein-Befehl-Installer (`curl … install.sh | bash`).** `scripts/install.sh` kennt jetzt einen
  Bootstrap-Modus: per `curl | bash` ohne lokalen Checkout lädt es nur die **Laufzeit-Dateien**
  (die `docker-compose.yml` + ein paar Ops-Skripte, **nicht** den Quellbaum) für einen gepinnten
  Ref herunter und macht dann das Setup. Da mTLS per Default erzwungen ist, gibt es keinen
  Scharfschalt- oder permissiven Schritt — Erst-Admin + Token entstehen über die Container-CLI.
  README + Installations-Doku (DE+EN) führen mit dem Einzeiler.

### Changed

- **`docker-compose.yml` ist jetzt selbstgenügsam** — keine Repo-Datei-Bind-Mounts mehr. Die
  Monitoring-DB (`adminhelper_monitor`) legt der Monitoring-Service in seinem Entrypoint selbst an
  (statt eines gemounteten `postgres-init.sh`). Damit ist die Compose eine **einzelne, eigenständig
  verteilbare Datei** (Images aus ghcr); ein Operator braucht den Quellbaum nicht mehr zum Betrieb.
- **`scripts/update.sh`** kann mit `--ref` die Laufzeit-Dateien (Compose + Skripte) für eine
  Zielversion frischen, bevor es Images zieht + neu startet (Backup-first bleibt).

### Fixed

- **Einzeiler-Robustheit (`curl … | bash`).** `install.sh` zieht die Images jetzt explizit
  (`docker compose pull`), bevor es startet — ein veraltetes lokal gecachtes `:latest` würde sonst
  stillschweigend weiterlaufen. Zusätzlich bekommt jeder `docker compose`-Aufruf `</dev/null`: unter
  `curl | bash` liest bash das Script aus der Pipe, und ein Subprozess, der dieselbe stdin erbt,
  verschluckte sonst den Rest des Scripts (der Stack kam hoch, aber ohne Erst-Admin).

## [0.29.0] - 2026-06-12

### Added

- **One-Shot-Installer `scripts/install.sh`.** Bringt den Stack hoch, legt den Erst-Admin samt
  einmaligem Enrollment-Token **out-of-band** an (über eine neue interne Management-CLI
  `python -m app.cli` mit `create-admin` + `mint-enroll-token`) und schaltet am Ende mTLS scharf.
  Das löst die Henne-Ei-Lage des Erst-Admins unter erzwungenem mTLS: ein brandneuer certloser
  Client kommt nicht durch den `:443`-Handshake zum Login, also mintet das Script (mit internem
  Netz-Zugriff) das erste Token direkt. Der Admin löst es im Desktop unter „Mit Token enrollen" ein
  (Cert entsteht on-device), dann normaler Login.
- **Update-Script `scripts/update.sh`** — Backup-first (inkl. CA-Kronjuwel) → gepinnter
  `docker compose pull` → Recreate → Healthcheck. Version pinnen über die `*_IMAGE`-Tags in `.env`.

### Changed

- **mTLS ist jetzt per Default erzwungen** (`MTLS_ENFORCE=true` in `docker-compose.yml` +
  `.env.example`). **BREAKING:** die Datenebene `:443` verlangt ab Werk ein Client-Cert. Ein
  frischer Install ist via `install.sh` sofort enforced nutzbar; ein manueller Bootstrap ohne Script
  braucht einmalig `MTLS_ENFORCE=false`. Die Token-Mint-Logik wurde in
  `enrollment/service.mint_enrollment_token` extrahiert (von HTTP-API + CLI geteilt).

## [0.28.0] - 2026-06-12

### Added

- **Internes TLS/mTLS-Gateway (`apps/gateway/`, nginx) als einzige öffentliche TLS-Kante**
  auf `:443` (Web/API) und `:8444` (Enrollment, certless + token-gated). Es terminiert TLS und
  reicht die verifizierte Client-Identität als `X-Client-*`-Header an die internen Dienste weiter
  (in dieser Phase **permissiv** — `ssl_verify_client optional`; die mTLS-Pflicht folgt später).
  Ein externer Reverse-Proxy ist nicht mehr nötig (ADR 0001 D11).
- **`ca-issuer`-Dienst in die Produktiv-Compose verdrahtet** (+ ghcr-Publish). Er erzeugt beim
  ersten Start die interne PKI (Root + `tunnel`/`access`/`internal`-Intermediates) und stellt dem
  Gateway dabei dessen TLS-Leaf bereit — **access-signiert**, kettet zur gepinnten Root, sodass
  native Clients es akzeptieren (das Gateway hält keinen Signier-Schlüssel, ADR 0001 D6). Neue
  Volumes `ca-pki` (issuer-privat) und `gateway-certs`.
- **`CA_ROOT_PASSPHRASE`** in `.env.example` + `scripts/init-secrets.sh` — verschlüsselt den
  kalten PKI-Root-Key at-rest (ADR 0001 D7); **getrennt sichern, nicht ins Backup legen**.
- **Full-Stack-Backup/Restore inkl. CA-Kronjuwel** (`scripts/backup.sh` / `scripts/restore.sh`,
  ADR 0001 §5). `backup.sh` bündelt `ca-pki` (Root + Intermediates), `pg_dump` beider DBs,
  `monitoring-data`, optional `victoria-data` und die `.env` **ohne `CA_ROOT_PASSPHRASE`** in ein
  Tarball; `restore.sh` stellt Volumes + DBs wieder her. Die restaurierte Root ist identisch —
  bereits enrollte Clients bleiben vertraut. `gateway-certs`/`frps-certs` werden nicht gesichert
  (der `ca-issuer` regeneriert sie aus `ca-pki`).
- **Server: Per-Route-mTLS-Scope-Schicht** (`app/core/identity.py`, ADR 0001 D8) — der Server
  liest die vom Gateway weitergereichte, verifizierte Client-Identität und prüft pro Route den
  Cert-Scope (`access` = Mensch, `tunnel` = Agent). **In dieser Phase permissiv** (`MTLS_ENFORCE`
  default `false`): ein Mismatch wird nur geloggt, der Request läuft durch — das System bleibt
  nutzbar, bis alle Clients Certs haben. Das Scharfschalten auf `CERT_REQUIRED` folgt später.
- **Desktop: automatisches mTLS-Enrollment (A5a).** Nach dem Login mintet der Desktop ein
  access-scoped Enrollment-Token (`POST /api/enrollment/token`, JWT-gated), erzeugt on-device
  einen ECDSA-Key + CSR (`rcgen`), holt sein Client-Zertifikat vom `ca-issuer` über die
  Enroll-Plane des Gateways und legt Key/Cert/CA in drei Keyring-Einträgen ab. Danach präsentiert
  `build_client` das Cert per mTLS und verifiziert den Server gegen die **gepinnte CA-Kette**
  (CA-Pinning statt Leaf-TOFU — überlebt Gateway-Leaf-Rotation, D2; Hostname bewusst nicht
  erzwungen, damit Enrollment keinen funktionierenden Zugriff bricht). Logout räumt die Identität.
  **Auto-Renew (A5b):** beim App-Start erneuert der Desktop sein Cert automatisch, sobald es ~50 %
  seiner Laufzeit erreicht (über `/ca/renew` mit dem aktuellen Cert als Nachweis).
  **Browser-P12-Export (A5c):** der Desktop kann ein langlebiges Browser-Zertifikat enrollen und
  als passwortgeschützte **PKCS12-Datei** exportieren (zum Import in den Browser-Zertifikatsspeicher).
- **Agent: automatisches mTLS-Enrollment + Auto-Renew.** Beim Provisioning erzeugt der Agent
  on-device einen ECDSA-Key, holt über die Enroll-Plane des Gateways (Port `8444`) ein
  `tunnel`-scoped Client-Zertifikat vom `ca-issuer`, legt es unter `/etc/adminhelper/identity/`
  (Key `0600`) ab und pinnt die interne Root-CA. Danach weist er sich bei allen Server-Pushes
  (Monitor-Report, FRPC-Sync) mit diesem Cert aus (custom-root-only, ADR 0001 D2) und erneuert es
  automatisch bei ~50&nbsp;% Laufzeit via `/ca/renew`. **Best-effort:** ohne erfolgreiches
  Enrollment läuft der Agent vorerst mit dem API-Key weiter. `provision/activate` liefert dafür
  einen einmaligen Enrollment-Token mit.
- **Desktop: Browser-Zertifikat-Export im UI (A6).** Die Einstellungen (Server-Modus, angemeldet)
  haben jetzt einen Knopf **„Browser-Zertifikat exportieren"**: Der Desktop enrollt ein langlebiges
  `access`-Zertifikat, verpackt es als passwortgeschützte `.p12` (auf `0600` gehärtet, im
  App-Datenverzeichnis) und zeigt den Speicherpfad an. Damit lässt sich ein Browser für den späteren
  mTLS-Zwang vorbereiten — Import-Anleitung (Chrome/Edge + Firefox) DE+EN unter „Benutzer &amp;
  Zugriff → Browser-Zugriff". Das Backend-Command bestand seit dem Desktop-Enrollment, war aber nie
  ins UI verdrahtet; die Datei schreibt — mangels FS-/Dialog-Plugin — der Rust-Layer.
- **mTLS-Enforcement-Schalter `MTLS_ENFORCE` (A8).** Eine einzige Variable schaltet die Datenebene
  von permissiv auf erzwungen: das Gateway generiert beim Start sein `ssl_verify_client`-Snippet
  (`optional` per Default, `on` = `CERT_REQUIRED` bei `MTLS_ENFORCE=true`), der Server (seit A3)
  weist geschützte Routen ohne gültigen Cert-Scope mit `403` ab. In `docker-compose.yml` an Gateway
  **und** Server verdrahtet, `.env.example` dokumentiert. **Default `false`** (permissiv) — nichts
  ändert sich, bis ein Operator umlegt; Rollback ist ein Flag zurück + Gateway-Neustart. Beide
  nginx-Modi mit `nginx -t` **und end-to-end am laufenden Stack** verifiziert (permissiv → certlos
  `GET /` = 200; enforced → certlos = 400 „No required SSL certificate" am Handshake, Enroll-Plane
  `:8444` weiter offen; Rollback → 200). Betriebs-Anleitung (Scharfschalten, Rollback,
  Lock-out-Vermeidung, Bootstrap-Fenster) unter „Betrieb &amp; Konfiguration" (DE+EN). Das
  tatsächliche Scharfschalten bleibt eine bewusste Operator-Aktion nach GUI-Hardware-Verifikation.
- **Admin-Enrollment-Token für fremde Identitäten** (`POST /api/enrollment/token/for`, admin-only).
  Ein Admin mintet ein einmaliges `access`-Enrollment-Token für einen existierenden Ziel-User und
  reicht es out-of-band weiter; der neue Nutzer löst es certless an der Enroll-Plane `:8444` ein.
  Erster Baustein der **entkoppelten Enrollment-Tür** (ADR 0003), damit neue Clients auch bei
  erzwungenem mTLS ohne permissives Fenster onboarden können (CN = Ziel-Username, issuer-diktiert).
- **Desktop: „Mit Token enrollen"-Erst-Start-Flow** (ADR 0003, entkoppelte Enrollment-Tür). Der
  Login-Screen hat jetzt einen Umschalter „Erstes Mal? Gerät mit Token einrichten": mit Server-URL +
  einem (vom Admin out-of-band erhaltenen) Enrollment-Token holt der Client sein mTLS-Zertifikat
  **ohne vorigen Login** an der certless Enroll-Plane `:8444` und meldet sich danach normal an. Damit
  lässt sich ein neuer Nutzer auch bei erzwungenem mTLS onboarden, ohne die Datenebene kurzzeitig
  permissiv zu schalten (das bleibt nur für den allerersten Admin nötig).
- **Sofortiger Identitäts-Widerruf (Schnell-Widerruf ohne CRL, ADR 0001 §3.4).** Das Löschen eines
  Benutzers bzw. Servers schreibt jetzt einen `revoked_identities`-Eintrag: der `ca-issuer`
  verweigert dem Cert die Erneuerung (`/renew`) **und** die Datenebene weist es im erzwungenen Modus
  pro Request mit `403` ab (vorher wurde die Liste nie befüllt — der Widerruf war wirkungslos). Das
  Neuanlegen eines gleichnamigen Benutzers räumt einen veralteten Eintrag.
- **Cleanup-Job für `enrollment_tokens`.** Verbrauchte/abgelaufene Enrollment-Token werden periodisch
  gelöscht (analog zur JWT-Blacklist), statt die Tabelle unbegrenzt wachsen zu lassen.
- **Rate-Limit auf der certless Enroll-Plane `:8444`** (`limit_req`, per-IP, 10 r/s, Status 429) gegen
  Token-Brute-Force/Enroll-Flooding (das in ADR 0003 §5 versprochene Limit war nie konfiguriert).

### Changed

- **FRP-Tunnel auf die einheitliche PKI umgestellt** (ADR 0001 D1, Provider-Seite). Das
  frps-Server-Cert und das Agent-Tunnel-Cert kommen jetzt aus der `tunnel`-Intermediate des
  `ca-issuer` (ECDSA P-256) statt aus einer frps-eigenen RSA-CA: der Issuer provisioniert
  `frps.crt`/`frps.key`/`ca.crt` (tunnel-Kette) in ein neues `frps-certs`-Volume, das frps
  read-only unter `/etc/frp-pki` mountet; der Agent nutzt für den frp-Tunnel **dasselbe**
  enrollte Tunnel-Cert wie für seine Server-Pushes. `trustedCaFile` ist beidseitig die
  tunnel-Kette; der Server mintet kein per-Client-frp-Zertifikat mehr. Der **Desktop-Visitor**
  ist inzwischen ebenfalls migriert (siehe „Changed → STCP-Visitor"/„Removed → FRP-CA").
- **Der Server terminiert kein TLS mehr selbst.** Er lauscht plain-HTTP intern auf `:8080` hinter
  dem Gateway und hat **keinen Host-Port** mehr; `server` und `ca-issuer` sind nur noch im
  Compose-Netz erreichbar. Dadurch ist der vom Gateway gesetzte Identitäts-Header von außen
  unfälschbar. Die frühere Self-Signed-Zertifikat-Erzeugung im Server-Entrypoint entfällt
  (das TLS-Zertifikat kommt jetzt vom `ca-issuer`). **frps** bleibt seine eigene TLS-Kante.
- **STCP-Visitor (Desktop) auf die einheitliche PKI migriert.** Der Visitor präsentiert jetzt seine
  **enrollte access-Identität** als frpc-Client-Cert (der Desktop exportiert Key/Cert/CA aus dem
  Keyring in Dateien für den frpc-Sidecar) statt eines server-gemünzten Certs der alten FRP-CA. frps
  vertraut dafür zusätzlich der `access`-Intermediate (der `ca-issuer` trägt sie in frps' `ca.crt`
  ein); die echte Per-Tunnel-Autorisierung bleibt der STCP-`secretKey` + die server-seitige
  Bundle-Filterung. **Real-Roundtrip nur manuell verifizierbar** (kein CI-Schutz).
- **Renew schreibt die Identität crash-sicher** (Agent: Staging + atomarer Rename; Desktop:
  Schlüssel-Wiederverwendung). Ein Absturz mitten im Renew kann keine unbrauchbare Key/Cert-Paarung
  mehr hinterlassen (vorher: stiller Lock-out bis zur Neu-Provisionierung).
- **Gateway-/frps-Leaf wird vor Ablauf erneuert.** Der `ca-issuer` mintet ein bereitgestelltes
  Server-Leaf beim Boot neu, sobald es die Hälfte seiner Laufzeit überschritten hat — ein
  langlaufender Stack verliert `:443`/`:8444` (bzw. frps) nicht mehr durch ein abgelaufenes Cert.

### Removed

- **Browser-Erweiterung (`apps/extension/`) vollständig entfernt.** Die Chrome/Edge-MV3-Extension,
  die gespeicherte Web-Verbindungen als Popup anzeigte, wurde mitsamt Code, CI-Job (`ci.yml`),
  Release-Artefakt (`adminhelper-extension-*.zip` in `release.yml`) und Dokumentation (Admin-/
  Developer-Kapitel, README, `DEVELOPMENT.md`) aus dem Projekt gelöscht. Sie nutzte ausschließlich
  den **geteilten** `GET /api/connections`-Endpunkt mit einem `X-API-Key`-Header — es gab keine
  extension-exklusive Server-Schnittstelle, daher entfällt serverseitig nichts außer einigen
  Kommentar-Verweisen. Menschliche Browser-Nutzung läuft über das vom Desktop exportierte
  PKCS12-Client-Zertifikat (mTLS, A5c). Im PKI/mTLS-Plan (ADR 0001/0002) entfällt damit der
  Extension-Teil von A6.
- **Alte server-eigene FRP-CA vollständig entfernt** (D6 wirklich erfüllt — keine zweite
  Signier-Capability mehr im exponierten Server). Gelöscht: `app/modules/frp/pki.py` +
  `pki_router.py` (die `POST /api/frp/pki/ca|server-cert|client-cert`-Endpunkte), die
  CA-Erzeugung im Server-Start, das `frp-pki`-Volume sowie die **FRP-PKI-Admin-UI** im
  Web-Frontend (Modal, „CA generieren"-Knopf, API-Client, i18n-Strings). Die FRP-TLS-Materialien
  kommen seit der Provider-Migration ausschließlich aus dem `ca-issuer`.

## [0.27.0] - 2026-06-10

### Security

- **Server: Server-Name in die TOML-/Pfad-Boundary aufgenommen** (Audit-Residuum).
  `ServerCreate`/`ServerUpdate.name` lehnt jetzt TOML-Breaker und Pfad-Zeichen
  (`/`, `.`, `..`) ab — der Name fließt als FRP-Identifier (`user`/`serverUser`)
  in generierte Agent-Configs und als Pfad-Komponente ins Bulk-ZIP
  (`clients/{name}/frpc.toml`), war aber als einzige Eingangstür unvalidiert.
- **Server/FRP: `extra_config` lehnt Nicht-Skalar-Werte ab** (Audit-Residuum).
  Listen/Dicts umgingen den String-Breaker-Check und landeten als rohes
  Python-`repr` in der TOML (Injection über innere Strings möglich); Keys
  müssen jetzt TOML-Bare-Keys sein, Werte `str`/`bool`/`int`/`float`.
- **Server: Per-User-Isolation auf `/api/connections` durchgesetzt** (Audit-Fund).
  Non-Admins (und server-gebundene API-Keys) sehen und „touchen" nur noch
  Connections ihrer zugewiesenen Server — vorher lieferte die Liste **jedem**
  Non-Admin Host, Username und FRP-Visitor-Ports **aller** Server (IDOR). Spiegelt
  die bereits bestehende FRP-Visitor-Scoping-Invariante (`frp/generate_router.py`).
- **Server: Der letzte Admin kann nicht mehr per `update_user` herabgestuft
  werden** — verhindert den irreversiblen Self-Lockout aller admin-only-Endpunkte.
- **Server: Webhook-Ausführung blockiert nicht mehr den Event-Loop** (Audit-Fund).
  `run_hook_script` läuft jetzt über `run_in_threadpool` — ein einzelner langsamer
  Hook fror vorher das komplette Single-Worker-Backend (Login/APIs/Health) bis zum
  Timeout ein. Zusätzlich: eine Semaphore begrenzt gleichzeitige Hook-Subprozesse,
  und das Webhook-Trigger-Rate-Limit nutzt jetzt das zentrale `rate_limit`-Backend
  (mit Eviction/TTL) statt eines unbegrenzt wachsenden Per-IP-Dicts (Memory-DoS bei
  gefälschten `X-Forwarded-For`).
- **Server: Refresh-Token-Reuse invalidiert jetzt die ganze Token-Familie** (Audit).
  Bei erkanntem Reuse (Theft-Signal) wird `tokens_valid_after` des Users gesetzt —
  damit stirbt auch die bereits rotierte Angreifer-Kette, nicht nur das einzelne
  Token (vorher blieb sie unbegrenzt gültig).
- **Server: Rate-Limit fällt bei Redis-Ausfall nicht mehr „offen"** (Audit). Statt
  bei Redis-Fehlern still `0` zu liefern (Brute-Force-Schutz aus), **degradiert**
  das Backend auf einen lokalen In-Memory-Zähler — das Limit bleibt durchgesetzt.
- **Server/FRP: TOML-Injection an der Boundary geschlossen** (Audit). Felder, die
  roh in `frps.toml`/`frpc.toml`/Visitor-Config interpoliert werden (Tunnel-/
  Server-Name, `secret_key`, `auth_token`, `custom_domains`, `extra_config` …),
  lehnen jetzt Anführungszeichen/Backslash/Steuerzeichen ab; `secret_key`/
  `auth_token` haben einen Entropie-Floor (≥16 Zeichen). `get_allow_users` fällt
  zudem **fail-closed** (leere Allow-Liste statt `["*"]`).
- **Monitoring: MetricsQL-Label-Injection geschlossen** (Audit). `server_id`/
  `check_id` werden vor der Interpolation in Label-Matcher escaped — ein
  präparierter Wert kann nicht mehr aus dem Matcher ausbrechen und fremde
  Server-Metriken lesen.
- **Server: Agent-Report-Ingest (`/api/monitoring/agent/{id}/report`) ist
  rate-limitiert** (Audit) — der öffentliche, JWT-freie Proxy-Endpunkt cappt jetzt
  pro IP, statt eine unauthentifizierte Flut ungebremst durchzureichen.
- **Agent: Argument-Injection in watched-services geschlossen** (Audit). `--`
  vor dem server-gelieferten Service-Namen verhindert Flag-Confusion in den
  `systemctl`-Aufrufen (kein RCE — exec ohne Shell — aber Flag-Verwechslung).
- **Extension: API-Key wandert von `chrome.storage.sync` nach `chrome.storage.local`**
  (Audit). Der langlebige Key wird nicht mehr über den Browser-Account auf alle
  Geräte synchronisiert; eine einmalige Migration verschiebt bestehende Keys und
  löscht die Cloud-Kopie.
- **Desktop: TLS-Bypass durch TOFU-Zertifikat-Pinning ersetzt** (Audit-Fund,
  der einzige bestätigte MITM-Credential-Theft-Pfad). „Selbstsignierte
  Zertifikate erlauben" schaltete vorher via `danger_accept_invalid_certs(true)`
  die **komplette** TLS-Prüfung ab (Chain **und** Hostname, ohne Pinning) — ein
  On-Path-Angreifer konnte Login-Passwort, JWT-Access/Refresh-Token sowie den
  FRP-Client-Private-Key + `auth.token` aus dem Visitor-Bundle abgreifen. Jetzt
  pinnt der zentrale `auth::build_client` (und damit alle Pfade: Login, Refresh,
  `api_proxy`, Tunnel-, Connection- und Sync-Abrufe) beim ersten Verbinden den
  SHA-256-Fingerprint des Server-Leaf-Zertifikats (SSH-`known_hosts`-Modell,
  custom rustls `ServerCertVerifier`) und akzeptiert danach **nur** noch genau
  dieses Zertifikat; ein Wechsel wird abgelehnt (mögliche MITM). Der Pin liegt
  im OS-Keyring; neue Einstellung **„Gepinntes Zertifikat zurücksetzen"** stellt
  nach legitimer Cert-Rotation den First-Use wieder her. `check_server_cert`
  prüft zusätzlich das URL-Schema (kein Cleartext-Probe). Verifiziert per
  Echt-Handshake-Test (tokio-rustls-Server, Cert-Wechsel → reject).
- **Desktop: drei Defense-in-Depth-Härtungen rund um den gepinnten TLS-Pfad**
  (Audit, Rest des Desktop-Bündels — schließt #6 vollständig). (1) **Token-
  Destination-Pin**: `api_proxy` sendet den Session-JWT nur noch an die
  angemeldete Server-URL (`auth::stored_server_url`), ein abweichendes Ziel wird
  abgelehnt — ein kompromittiertes Frontend kann den Token nicht mehr an einen
  Fremd-Host umleiten. (2) **`ansible`-Pfad-Confinement**: `launch_ansible`
  akzeptiert nur noch Pfade unter dem App-Temp-Verzeichnis mit Präfix
  `adminhelper_ansible` (canonicalisiert, blockt `..`/Symlink-Ausbruch) — ein
  manipuliertes Frontend kann `ansible-playbook` nicht mehr auf ein fremdes YAML
  zeigen (RCE-Schutz). (3) **CSP**: `connect-src` von `'self' https:` auf
  `'self' ipc: http://ipc.localhost` verengt — schließt den XSS-Exfiltrations-
  Kanal; sämtlicher Server-Verkehr läuft ohnehin über den Rust-`api_proxy`, nie
  über Webview-`fetch`. (CSP-Änderung auf Windows manuell zu verifizieren.)
- **Web: Refresh-Token von `localStorage` in ein `HttpOnly`-Cookie verlagert**
  (Audit). Der langlebige Refresh-Token ist damit für JavaScript — und somit für
  XSS — unlesbar. Der Server setzt ihn auf `/login`, `/refresh` und `/bootstrap`
  als `HttpOnly; Secure; SameSite=Strict`-Cookie (Pfad `/api/auth`); `/refresh`
  und `/logout` lesen ihn aus Cookie **oder** Body, sodass Desktop- und CLI-
  Clients unverändert weiterlaufen (`Secure` folgt dem Request-Schema, damit
  localhost-Dev und Tests funktionieren). `SameSite=Strict` auf dem einzigen
  Cookie-lesenden Endpunkt ist der CSRF-Schutz — ein separates CSRF-Token wäre
  hier Over-Engineering. Der Web-Client hält den Refresh-Token nicht mehr und
  räumt Altbestände aus `localStorage`. Verifiziert per pytest (Cookie-Setzen/
  Rotation/Reuse-Detection/Logout-Clear + Body-Backward-Compat) und Playwright-E2E.
- **Server/Monitoring: gehashte Python-Lockfiles** (Audit, Supply-Chain). Die
  Production-Images installieren ihre Dependencies jetzt aus einer gepinnten +
  SHA-256-gehashten `requirements.txt` (generiert via `pip-compile
  --generate-hashes`) mit `pip install --require-hashes` — ein manipuliertes oder
  getauschtes Artefakt vom Index lässt den Build fehlschlagen. `requirements.in`
  ist die lose Intent-Quelle; Tests/CI nutzen sie (ungehasht). Verifiziert per
  realem Docker-Build (`--require-hashes`, exit 0) für beide Dienste.
- **`SECURITY.md`: Trust-Modell + Audit-Residuen dokumentiert** — FRP-`secretKey`
  als eigentliche Authz-Grenze (nicht `allowUsers`), globaler `auth.token` als
  akzeptiertes SPOF mit Rotations-Empfehlung, Single-Worker-Verfügbarkeitsprofil,
  und das Register der bewusst zurückgestellten/akzeptierten Funde
  (frps-Caps, Pagination, Watermark-Subsekunden …) mit Begründung + Plan.

### Changed

- **Agent: Service-Inventar wird nur noch bei Änderung gesendet** (Audit R8,
  Ziel 250–500 Agenten). `all_services` (100–300 weitgehend statische
  systemd-Units) geht nur noch mit, wenn sich der SHA-256-Hash des Inventars
  ändert oder der letzte Full-Send >1 h her ist (State-Datei
  `.inventory-state.json` neben `monitor.conf`, oneshot-fest; Fehler ⇒
  Full-Send, nie Push-Abbruch). Watched-Services und Legacy-Fallback-Keys
  gehen weiterhin bei jedem Push; serverseitig ist „Key fehlt ≠ leeres
  Inventar" jetzt dokumentiert und durch Tests festgenagelt. Windows
  meldet gestoppte Dienste nicht mehr fälschlich als `enabled_inactive`.
- **Agent-Pakete installieren nach `/usr/bin`** (vorher `/usr/local/bin` —
  FHS-untypisch für Paketmanager-Inhalte, `rpmlint`-Fehler). deb und rpm
  teilen sich die Unit-Datei, daher beide umgestellt; dpkg/rpm räumen den
  alten Pfad beim Upgrade ab. Build-Skripte brechen außerdem ab statt still
  ein Dummy-`frpc` zu packen oder eine geratene Default-Version zu bauen;
  rpm deklariert jetzt `Conflicts:` für die alten `srm-*`-Pakete; die
  Install-Hinweise nennen `provision` statt des entfernten `frpc init`.
- **Dependabot entfernt** (`.github/dependabot.yml`) — Dependency-Updates laufen
  künftig agent-getrieben (verträgt sich besser mit den gehashten Python-Locks und
  erlaubt koordinierte, getestete Bumps über alle Ökosysteme). GitHubs separate
  Security-Alerts bleiben als Sicherheitsnetz unberührt. Neuer Workflow in
  `DEVELOPMENT.md` dokumentiert.
- **Web: Monitoring-Seite zerlegt** (Audit F8). `Monitoring.svelte` schrumpft
  von 743 auf 153 Zeilen: Filter-/Gruppierungs-/Summen-Logik lebt jetzt
  testbar in `lib/utils/monitoring.ts`, die Tab-Inhalte in fünf
  Subkomponenten unter `lib/components/monitoring/` (Muster der
  Desktop-Sektionen). Verhalten und Optik unverändert (Screenshot-Tests
  grün); Polling/„zuletzt aktualisiert" bleiben auf Seitenebene.
- **Server: FK-Spalten indiziert** (Audit, Ziel 250–500 Server). Neue Migration
  `a258973bb7fd` legt Indizes auf `connections.server_id`,
  `frp_tunnels.server_id`/`frp_config_id`/`connection_id` und
  `provision_tokens.server_id` an — Postgres indiziert FK-Spalten nicht
  automatisch; Server-Deletes (CASCADE/SET NULL) und server-bezogene Filter
  liefen vorher als Full-Table-Scans.

### Fixed

- **Server: Webhook-Trigger blockiert den Event-Loop nicht mehr** (Audit-Rest).
  Der Redis-Rate-Limit-Increment und die Hook-DB-Query in `trigger_webhook`
  liefen als einzige sync-I/O-Reste direkt im Event-Loop des async-Handlers —
  jetzt via `run_in_threadpool`, konsistent zum bereits ausgelagerten
  Hook-Subprozess.
- **Agent: `service install` erzeugt jetzt dieselbe Unit-Semantik wie deb/rpm**
  (Audit). Die generierte systemd-Unit nutzte `run` (Dauerläufer) unter
  `Type=oneshot` + Timer — `systemctl start` hing bis zum Timeout und der Timer
  feuerte eine zweite, parallele Instanz (doppelte Pushes). Jetzt `run --once`
  + Timer wie im Paket, inkl. `RandomizedDelaySec`.
- **Agent: Metrik-Push mit 1 Retry (10 s Backoff)** — ein transienter
  Server-Neustart reißt kein 5-Minuten-Loch mehr in die Zeitreihen.
- **Agent: Docker-Collection mit Timeout + Batch-Inspect** — `docker info`/
  `ps`/`inspect` laufen mit 10-s-Timeout (hängender Daemon blockierte vorher
  den ganzen Push-Cycle unbegrenzt); Restart-Policies kommen aus EINEM
  Batch-`docker inspect` statt einem Subprozess pro Container.
- **Agent: TLS-HTTP-Client dedupliziert** (`internal/httpclient`) — die
  dreifach kopierte CA-Pinning-Logik (monitor/frpc/provision) hat jetzt eine
  Quelle; Timeout ist der einzige Parameter.
- **Web/Desktop: `types.ts`-Drift aufgelöst, Dictionaries entkoppelt** (Audit,
  Kritisch-Fund). Das Web übernimmt die Desktop-Typnamen (`FrpProvisionToken`,
  `FrpProvisionTokenCreateResult`, + `MonitoringAgentKeyResult`) — beide
  `lib/api/types.ts` sind wieder byte-identisch. `sync-from-web.sh`
  synchronisiert nur noch `types.ts` (die i18n-Dictionaries sind bewusst
  getrennte Produkte, ein `--apply` hätte ~200 Desktop-Keys still gelöscht)
  und bricht ab, wenn das Ziel Exporte enthält, die in der Quelle fehlen.
- **Desktop: TOFU-Pin-Cache übersteht Thread-Panics** — alle vier
  `.lock().unwrap()`-Stellen auf dem Pin-Cache-Mutex nutzen jetzt das
  Poison-tolerante Muster aus `frpc.rs`; vorher hätte ein einzelner Panic
  jede weitere TLS-Verifikation mitgerissen.
- **Desktop: `api_proxy` meldet kaputtes Antwort-JSON als Fehler** statt es
  still auf `null` zu mappen (leerer 2xx-Body bleibt zulässig).
- **Desktop: RDP-Fehlertoast bei extrem schnellen Verbindungen** —
  „verbunden"-Erkennung nutzt jetzt ein eigenes Flag statt des
  `connected_at_ms == 0`-Sentinels (Doppeldeutung bei <1 ms).
- **Produkt-Doku (DE+EN) auf den Code-Stand gebracht** (Audit X3/X5): alle
  Prä-v0.24-Pfade ohne `apps/`-Präfix korrigiert, Agent-Pfade
  (`/usr/bin`, `adminhelper.conf`, `%ProgramData%\AdminHelper`),
  HttpOnly-Cookie-Realität in der API-Referenz; neu dokumentiert:
  Pagination, Push-Retry/Inventar-Drosselung, Web-Auto-Refresh,
  Scheduler-Defaults, Alert-Log-Retention, alle neuen CI-Gates.
  CLAUDE.md-Testspalte korrigiert (alle Komponenten haben Tests; der
  `version_locations`-Verweis ist als lokale, gitignorte Agent-Memory
  gekennzeichnet).
- **Doku-Drift behoben** (Audit X1/X2/X6): README-Quick-Start zeigte auf das
  nicht existierende `http://localhost:8080` (richtig: `https://localhost`,
  Compose published nur 443); DEVELOPMENT.md beschrieb den entfernten
  `admin/admin`-Login, verlangte Go 1.24 (go.mod: 1.25), verschwieg die
  Node.js-Voraussetzung und zeigte ein Override-Beispiel mit totem
  Build-Context; CONTRIBUTING verlangte ein nicht existierendes
  `npm run test` fürs Web.
- **Monitoring: Connection-Leak im Alerter geschlossen** (Audit). Die
  Zweit-Session in `_build_message` wurde nur im Happy-Path geschlossen —
  bei Fehlern blieb die Pool-Verbindung hängen; jetzt Context-Manager.
- **Monitoring/Server: APScheduler-Defaults explizit gesetzt** (Audit, Ziel
  250–500 Server). `misfire_grace_time=30` statt 1 s (verspätete Runs wurden
  still verworfen → Zeitreihen-Lücken), Monitoring-Pool auf 30 Worker für
  I/O-gebundene Checks; `coalesce`/`max_instances` als Entscheidung gepinnt.
- **Monitoring: Push- und Scheduler-Checks nutzen dieselbe Damping-Logik**
  (Audit Q1). Der Agent-Report-Pfad hatte die `consecutive_fails`-Transition
  inline reimplementiert (ungetestete Kopie der getesteten
  `check_engine`-Funktionen, Drift-Gefahr) — jetzt eine Quelle; unterdrückte
  Meldungen tragen auch im Push-Pfad das „(Fehler n/m)"-Suffix.
- **Desktop-UI: Alert-Ladefehler sind sichtbar** (Audit). `loadAlerts`/
  `loadAlertLog` schluckten API-Fehler still — ein toter Monitoring-Service
  sah aus wie „keine Alerts". Jetzt `reportError` wie in `loadMonitoring`
  (Session-Expiry weiterhin ausgenommen).
### Added

- **CI schließt die „grün-aber-kaputt"-Blindspots** (Audit C1–C3): neuer
  Windows-`cargo check`-Job (der `windows`-Crate-Code wurde nie in CI
  kompiliert), ein `cargo tauri build`-Smoke auf Linux (beforeBuildCommand/
  UI-Embedding/deb-Bundling liefen nur auf Tags) und Docker-Builds beider
  Images auf PRs (`push: false`). Dazu ein FRP-Pin-Konsistenz-Check über
  die drei `FRP_VERSION`-Stellen.
- **Wöchentlicher Dependency-Audit-Workflow** (`audit.yml`, Audit D2):
  pip-audit (beide gehashten Locks), cargo audit, govulncheck, npm audit —
  das automatische CVE-Signal zwischen den agent-getriebenen Update-Runden.
- **Coverage-Reporting in CI** (Audit C4, report-only): pytest-cov für
  Server/Monitoring, `go test -cover`, vitest `--coverage` in beiden UIs.
- **ruff für die Python-Komponenten** (Audit C8). Server und Monitoring waren
  als einzige Komponenten ohne Lint-/Format-Gate — jetzt `ruff check`
  (+ Import-Sortierung) und `ruff format` mit CI-Job; einmaliger
  Format-Lauf über den Bestand (96 Auto-Fixes + 77 reformatierte Dateien,
  rein mechanisch, Suiten grün).
- **Release: Extension als versioniertes Zip-Artefakt** (Audit C5) — bisher
  wurde die MV3-Extension getestet, aber nie ausgeliefert („Load unpacked"
  aus dem Clone); jetzt hängt sie als `adminhelper-extension-X.Y.Z.zip` am
  Draft-Release und ist Teil des Release-Gates. `tauri-cli` ist im
  Release-Build exakt gepinnt statt floatendem `^2`.
- **API: optionale Pagination auf den Listen-Endpunkten** (Audit P4, Ziel
  250–500 Server). `limit`/`offset`-Query-Parameter (1–1000) +
  `X-Total-Count`-Header auf `GET /api/servers`, `/api/connections`,
  `/api/hooks` sowie Monitoring-Checks/-Status/-Alert-Regeln — ohne
  Parameter unverändertes Verhalten (volle Liste), Frontends unberührt.
  Pagination läuft in SQL nach dem Per-User-Scoping; der Monitoring-Proxy
  reicht `X-Total-Count` jetzt durch (Whitelist). 21 neue Tests.
- **Web: Monitoring aktualisiert sich automatisch** (Entscheidung nach Audit).
  30-s-Polling wie im Desktop, aber pausiert bei verstecktem Tab
  (`visibilitychange`; beim Sichtbarwerden sofortiger Refresh) — bei
  250–500 Servern pollen Hintergrund-Tabs damit nicht. Dezente „zuletzt
  aktualisiert"-Anzeige im Seitenkopf; Run-now-Button hat jetzt ein
  `aria-label`.
- **Monitoring: Retention-Cleanup für `monitor_alert_log`** (Audit). Täglicher
  System-Job löscht Einträge älter als 90 Tage — flatternde Checks schrieben
  die Tabelle vorher unbegrenzt voll (analog zum Blacklist-Cleanup des
  Servers). Dazu Tests für Trigger-Parsing, Push-Only-Skip und Cleanup.
- **Migrations-Smoke-Tests für Server und Monitoring** (Audit T1 — größter
  Test-Blindspot). Die Suite lief bisher ausschließlich gegen
  `create_all()`-Schemata; die echte Alembic-Kette wurde nie ausgeführt —
  eine kaputte Migration wäre grün durchgerutscht und erst im Deployment
  aufgefallen. Jetzt: `alembic upgrade head` gegen eine frische DB +
  `compare_metadata`-Abgleich (Server zusätzlich: Reentrance). Der
  Monitoring-CI-Job bekommt dafür einen Postgres-Service; lokal skippt der
  Monitoring-Smoke ohne `DATABASE_URL`.
- **Monitoring: Tests für `template_sync` und den Agent-Report-Pfad** (Audit
  T2 — die komplexeste, bisher ungetestete Monitoring-Logik). Variablen-
  Substitution, Create/Update/Delete-Diffing über mehrere Server, Schutz
  manueller Checks, Assignment-Entfernung, Server-Cleanup; dazu
  Endpoint-Verhaltenstests für das `consecutive_fails`-Damping im Push-Pfad.
  Monitoring-Suite 53 → 72 Tests.
- **Web: E2E-CRUD- und Fehler-Flows** (Audit T2). Stateful-Mocks +
  `crud.spec.ts`: Connection-Roundtrip (anlegen → Liste → löschen),
  Server-Anlage, API-500 → Fehler-Toast-Assertion; dazu 17 Unit-Tests für
  die extrahierte Monitoring-Filter-/Gruppierungslogik. Web-Suite 41 → 59
  Unit-Tests, Playwright 18 → 21 Specs.
- **Frontend: Tests für Token-Refresh und i18n-Parität** (Audit T3/T5).
  `client.ts` (401→Refresh→Retry, Refresh-Fehlschlag→Logout, parallele
  Requests teilen einen Refresh, 204→null) war als sicherheitskritischste
  Web-Logik ungetestet; dazu DE≡EN-Schlüssel-Paritäts-Tests in beiden
  Frontends — die heutige 100-%-Parität ist damit gegen Drift geschützt.
- **Agent: Tests für SMART-Parsing, Report-Aufbau und Push-Retry** —
  smartctl-7.x-JSON-Fixtures (ATA + NVMe + Degenerat-Fälle), `BuildReport`-
  Grundstruktur, Retry-Verhalten gegen httptest-Server, `hasPrefix`/`getFloat`.
- **Desktop: RDP-Fehlerklassifizierung testbar extrahiert**
  (`connection/rdp_logic.rs`) — `parse_freerdp_error` als datengetriebene
  Regel-Tabelle (verhaltensgleich), dazu 25 neue Tests (FreeRDP-Fehlerklassen,
  `parse_custom_size`, `hdpi_scale`, `resolve_connection`-Tunnel-Mapping,
  Windows-Cmdline-Quoting); Rust-Suite 24 → 49 Tests.

### Removed

- **Web: 5 verwaiste UI-Komponenten gelöscht** (`StatusPill`, `Badge`, `Tabs`,
  `Spinner`, `Field` — 0 Importe im gesamten `src`, per grep verifiziert).

## [0.26.0] - 2026-06-07

### Changed

- **FRP von 0.61.1 auf 0.69.1 angehoben** — frps-Image (`docker-compose.yml`),
  gebundeltes frpc (CI/Release) und die SHA-256-Pins der frp-Artefakte im
  Gleichschritt. Das Wire-Protokoll bleibt v1 (Default in 0.69), daher
  abwaerts­kompatibel; v2 ist opt-in (`transport.wireProtocol`) und wird nicht
  gesetzt. **Tunnel-getestet:** frps+frpc 0.69.1 mit der vom `config_generator`
  erzeugten Struktur (STCP-Proxy + `allowUsers`, Visitor mit `serverUser`,
  mutual `transport.tls` gegen eine eigene CA) — `verify` akzeptiert die Config
  und Nutzdaten fliessen durch den Tunnel.

## [0.25.0] - 2026-06-06

### Security

- **Desktop: Path-Traversal (Zip-Slip) beim Schreiben server-gelieferter
  PKI-Dateinamen geschlossen.** Ein boesartiger/kompromittierter Server konnte
  ueber den Visitor-Bundle-Dateinamen (`pki_dir.join(filename)`) beliebige Dateien
  auf dem Client schreiben. Dateinamen werden jetzt als einzelne, separator-freie
  Pfad-Komponente validiert.
- **Desktop: TLS auf der authentifizierten Server-URL erzwungen.** Login/Refresh/
  Logout/`authenticated_get` senden Passwort + Tokens nur noch ueber `https://`
  (Ausnahme: Loopback fuer lokale Entwicklung) — kein Klartext mehr ueber das Netz.
- **Monitoring: VictoriaMetrics-Line-Protocol-Injection geschlossen.** Agent-Report-
  Felder werden numerisch erzwungen, Tags/Measurements escaped (Backslash/Newline/
  Control-Chars) — ein Agent-Key kann keine fremden Zeitreihen mehr faelschen.
- **FRP-PKI: CA-Private-Key + alle Client-Keys aus dem internet-zugewandten
  frps-Volume entfernt.** Master-PKI liegt jetzt server-privat (Volume `frp-pki`);
  ins geteilte `frp-config`-Volume wird nur noch die frps-Teilmenge
  (`ca.crt`/`frps.crt`/`frps.key`) publiziert. Bestandsdeployments werden beim
  Startup einmalig migriert (CA bleibt erhalten).
- **Monitoring: Admin-API nicht mehr direkt zum Host exponiert.** Agent-Metriken
  laufen jetzt tunnelfrei ueber den Server-Proxy (`POST /api/monitoring/agent/
  {id}/report` auf 443); der Monitoring-Dienst ist nur noch intern erreichbar.
  `/docs`+`/openapi.json` sind standardmaessig aus (Env `MONITOR_ENABLE_DOCS`),
  der interne/Agent-Key wird konstant-zeitig (`secrets.compare_digest`,
  fail-closed) verglichen.

- **Server: Passwort-Reset widerruft jetzt bestehende JWTs.** Ein Passwort-Wechsel
  setzt `users.tokens_valid_after`; Tokens mit `iat` davor (oder ohne `iat`) werden
  abgelehnt — vorher blieben Access-(8h)/Refresh-(7d)-Tokens nach einem Reset gueltig.
- **Server: Input-Validierung auf User-Endpunkten.** `UserCreate`/`UserUpdate`
  erzwingen Passwort-Mindestlaenge (8) und einen Username-Charset
  (`^[a-zA-Z0-9._-]+$`, 3–64) — der Username fliesst in FRP-TOML und PKI-Dateinamen.

- **Extension: API-Key nicht mehr im URL-Query-String.** `background.js`/`popup.js`/
  `options.js` senden den Key jetzt über den `X-API-Key`-Header statt `?api_key=`
  (vorher landete der langlebige Key in Access-/Proxy-Logs, Referer, History).
  Zusätzlich: überflüssige `tabs`-Permission entfernt, und Verbindungs-URLs werden
  vor dem Öffnen auf `http(s)` geprüft.
- **Agent: `--insecure` persistiert nicht mehr in die Schleife.** Statt `INSECURE=1`
  dauerhaft zu speichern (TLS-Verify dauerhaft aus + API-Key-Leak pro Zyklus),
  erfasst der Agent beim Provisioning das Server-Zertifikat und pinnt es (TOFU) —
  `--insecure` gilt nur noch für den einmaligen Activate-Aufruf. Zusätzlich:
  Secret-Verzeichnisse `0700` (auch bei Raw-Binary-Provisioning), Config-Writer
  lehnt Steuerzeichen ab (verhindert `INSECURE=1`-Injection via Newline),
  PKI-Bundle-Dateien default `0600` (nur `.crt` auf `0644`).
- **Container laufen nicht mehr als root.** Server- und Monitoring-Image starten
  nur kurz als root (chownt die gemounteten Pfade), droppen dann via `gosu` auf
  einen Non-root-User (uid 10001) — uvicorn, Alembic, Cert-Generierung und
  Hook-Subprozesse laufen unprivilegiert. Begrenzt die Auswirkung einer
  App-RCE/Path-Traversal auf einen Non-root-Prozess.
- **`frps.toml` jetzt `0600`.** Die Datei (globaler `auth.token` +
  Dashboard-Passwort) im mit frps geteilten Volume wurde zuvor world-readable
  (`0664`) geschrieben; jetzt umask-robust `0600` (frps liest sie als root).
- **CI/CD-Supply-Chain gehärtet.** Alle third-party GitHub-Actions sind auf den
  vollen Commit-SHA gepinnt (vorher mutable Tags/Branch-Refs wie
  `rust-toolchain@stable` in Jobs mit ghcr-Push + `contents:write`); der
  `frpc`-Download wird vor Nutzung gegen einen gepinnten SHA-256 verifiziert;
  Dependabot (`github-actions` + pip/npm/gomod/cargo) hält die Pins aktuell.
- **Desktop: drei aktive `rustls`-Advisories geschlossen** (`reqwest` 0.11 → 0.12).
  `reqwest` 0.11 war der einzige Konsument des EOL-`rustls` 0.21 →
  `rustls-webpki` 0.101.7 mit zwei Cert-Validation-Bypässen
  (RUSTSEC-2026-0098/-0099: Name-Constraints für URI-/Wildcard-Namen fälschlich
  akzeptiert) und einem DoS-Panic (RUSTSEC-2026-0104, CRL-Parsing). Jetzt
  `rustls` 0.23.40 / `rustls-webpki` 0.103.13 — Krypto-Provider bleibt **`ring`**
  (kein `aws-lc-rs`, also kein neuer NASM-Build-Zwang auf Windows), Roots bleiben
  `webpki-roots` (unveraendertes Trust-Verhalten). Keine Code-Aenderung noetig.

### Changed

- **Provisioning-Antwort `monitorUrl` ist nun ein server-relativer Pfad
  (`/api/monitoring`).** Der Agent setzt ihn an die bereits TLS-vertraute
  Server-URL, gegen die er provisioniert wurde — der Metrik-Push trifft so immer
  denselben Host/Cert, ohne dass der Server seine oeffentliche Adresse kennen muss.
- **Desktop: `keyring`-Crate von 2.3 auf 3.6 angehoben.** Verhalten unveraendert
  (gleiche Backends: Linux `secret-service`/zbus + `crypto-rust`, macOS Keychain,
  Windows Credential Manager). Der Major-Bump zieht ein neueres `zbus` (4.x) nach
  und entfernt damit die als **unmaintained** geflaggte transitive Abhaengigkeit
  `derivative` (RUSTSEC-2024-0388); netto **-12** Crates im Lockfile. Dependabots
  vorgeschlagener Sprung auf `keyring` 4.0 wurde bewusst **nicht** uebernommen: Die
  4.x-Crate ist auf Sample-/CLI-Code umgebaut (re-exportiert `Entry`/`Error` nicht
  mehr → unbaubar) und zieht ueber den unbedingten `db-keystore`-Store eine ganze
  SQL-Engine (Turso) + Volltextsuche (Tantivy) + `bindgen` herein (+160 Crates).
- **Desktop: `windows`-Crate von 0.56 auf 0.61 angehoben.** Der `flags`-Parameter
  von `CredReadW`/`CredDeleteW` ist in 0.61 `Option<u32>` statt `u32` — der
  Windows-Credential-Code (`password.rs`) wurde entsprechend von `0` auf `Some(0)`
  angepasst. Verhalten unveraendert (`0` ≙ keine Flags). Nur subtraktiv im Lockfile
  (-5 Crates: doppelter 0.56-Subtree entfernt, 0.61.3 war via Tauri bereits
  vorhanden). Verifiziert per isoliertem Cross-Compile gegen `x86_64-pc-windows-gnu`,
  da der Linux-CI-Job den `#[cfg(windows)]`-Pfad nicht kompiliert.
- **Desktop-UI: Build-Toolchain modernisiert** — Vite 5→8, TypeScript 5→6,
  ESLint 9→10, `@sveltejs/vite-plugin-svelte` 4→7, `eslint-plugin-svelte` 2→3
  (+ `svelte-eslint-parser`, `globals`, `prettier-plugin-svelte`, `@types/node`).
  `tsconfig.json` auf relative `paths` ohne `baseUrl` umgestellt (TS-7-fest).
  Der strengere `eslint-plugin-svelte@3`-Regelsatz deckte echte Mängel auf, die
  **gefixt** statt unterdrückt wurden: 18 `{#each}`-Blöcke in den Monitoring-Views
  haben jetzt stabile `(key)` (korrekte DOM-Reconciliation beim Umsortieren/Entfernen),
  und `normalizeConnection` dedupliziert Connection-Tags (keine doppelten Tag-Chips,
  kollisionsfreie Keys). Drei Regel-Treffer waren Fehlalarme (uPlot-DOM-Interop,
  transiente `Map` in `$derived.by`, bewusste `$effect`-Dependency-Registrierung)
  und sind mit begründeten `eslint-disable`-Kommentaren versehen.
- **Web-Frontend: Build-Toolchain modernisiert** — Vite 5→8, TypeScript 5→6,
  ESLint 9→10, Vitest 2→4, `@sveltejs/vite-plugin-svelte` 4→7,
  `eslint-plugin-svelte` 2→3, Svelte 5.1→5.56, `typescript-eslint`,
  `@playwright/test`, `svelte-check`, `@types/node`, `globals`,
  `prettier-plugin-svelte`. Fehlendes direktes `@eslint/js` ergänzt (wurde unter
  ESLint 9 nur transitiv aufgelöst, unter 10 nicht mehr). `tsconfig.json` auf
  relative `paths` ohne `baseUrl` umgestellt (TS-7-fest). In `client.ts` eine tote
  `null`-Initialisierung entfernt. Die sieben `prefer-svelte-reactivity`- und der
  eine `no-dom-manipulating`-Treffer waren allesamt Fehlalarme (transiente
  `Map`/`Set` in `$derived.by`, Copy-then-reassign-Pattern, uPlot-DOM-Interop) und
  sind mit begründeten `eslint-disable`-Kommentaren versehen.
- **Ops: schwebende `:latest`-Images in `docker-compose.yml` gepinnt.**
  `snowdreamtech/frps` → `0.61.1` (im Gleichschritt mit der gebundelten frpc-Version
  `FRP_VERSION`, damit Server/Client nicht auseinanderlaufen) und
  `victoriametrics/victoria-metrics` → `v1.144.0` — reproduzierbare Deployments,
  keine ueberraschenden Versionsspruenge mehr. (Ein FRP-Bump auf 0.69.x ist bewusst
  separat zu testen.)
- **Server: totes `requests`-Dependency entfernt** (`apps/server/requirements.txt`);
  der einzige HTTP-Client ist `httpx` (`monitoring_proxy.py`).

### Fixed

- **Desktop:** frpc-Status wird nach Prozess-Ende zurueckgesetzt (Restart war
  zuvor mit „frpc laeuft bereits" blockiert). (#2)
- **Desktop:** Dashboard-Connections-Subscription wird in `onDestroy` aufgeraeumt
  (Subscription-Leak pro Navigation). (#6)
- **Desktop:** Wechsel in den Server-Modus mit gueltiger Session laedt jetzt
  neu und startet den Tunnel (zuvor erst nach Neustart). (#7)
- **Desktop:** re-entrantes `requestPassword` haengt nicht mehr den ersten
  Connect-Flow (in-flight-Prompt wird als „cancelled" aufgeloest). (#8)
- **Windows-Desktop:** Session-Load implementiert (`CredReadW`) — kein
  Re-Login mehr bei jedem Start. (#4)
- **Windows-Agent:** Service ist SCM-aware (`svc.Run`) — `sc start` laeuft nicht
  mehr in Fehler 1053. (#3)
- **Agent:** Watched-Service-Health wird pro Zyklus nur einmal erhoben (#5);
  letzter STOPPED-Service auf Windows korrekt als `enabled_inactive` (#11);
  re-Provisioning ueberschreibt `SERVICES` nicht mehr mit leer (#12).
- **Server:** `GET /api/frp/status` blockiert den Event-Loop nicht mehr
  (sync-Endpoint) (#9); Ansible-Playbook-Schreib/Loeschvorgaenge sind mit der
  DB-Transaktion geordnet (keine verwaisten Dateien/Rows) (#10).
- **Frontend:** englischsprachige Nutzer sehen keine deutschen Strings mehr
  (Tunnel-Status-Labels + ~54 `'Fehler'`-Toast-Fallbacks i18n-isiert) (#13);
  Metrik-Fetches bei schnellem Perioden-Wechsel werden sequenziert
  (kein Stale-Overwrite) (#14).

### Removed

- **Monitoring-Host-Port (`MONITOR_AGENT_PORT`/`8480`) aus `docker-compose.yml`
  entfernt** (nur noch `expose: 8080`).
  **Breaking (Ops):** Nach dem Upgrade muessen bereits provisionierte Agents
  **neu provisioniert** werden — ihre gespeicherte `MONITOR_URL` zeigt sonst auf
  den weggefallenen Port. Wer direkt gegen `:8480` skriptet, stellt auf
  `https://<server>/api/monitoring/agent/{id}/report` um.

## [0.24.0] - 2026-06-04

### Security

- **FRP-PKI-Schluessel jetzt `0600`, PKI-Verzeichnis `0700`.** Private Keys
  (`ca.key`, `frps.key`, Client-Keys) wurden zuvor umask-abhaengig (oft
  world-readable `0644`) geschrieben. `_write_key` erzeugt sie nun atomar mit
  `0600`; bestehende lax-permissionierte Deployments werden bei jedem
  PKI-Zugriff idempotent nachgezogen.
- **IDOR auf `GET /api/frp/provision/{server_id}/config(-hash)` geschlossen.**
  Mit einem beliebigen gueltigen Read-API-Key war zuvor die `frpc.toml`
  (globaler `auth.token` + STCP-Secrets) jedes Servers abrufbar. API-Keys sind
  jetzt an einen `server_id` gebunden; der Endpoint prueft die Server-Scope
  strikt (403) und ist Admin-only.
- **TOCTOU im Provision-Activate behoben.** Der Einmal-Token wird nun atomar
  per bedingtem `UPDATE ... WHERE used_at IS NULL` konsumiert; ein verlorenes
  Rennen liefert `409` und erzeugt fail-closed keinen API-Key.
- **Hook-Ausfuehrung: ehrliche Sicherheits-Posture.** Das wirkungslose
  `exec()`-Pseudo-Sandbox wurde entfernt; die Worker-Umgebung ist auf das
  Noetigste minimiert (entfernt u.a. `ADMIN_PASSWORD`). Hooks bleiben bewusst
  vertrauenswuerdiger Admin-Code mit DB-Zugriff — das ist nun dokumentiert und
  testverankert, statt faelschlich „isoliert" zu suggerieren.

### Added

- **GitHub Actions CI/CD.** `ci.yml` (Lint/Tests aller Komponenten),
  `docker.yml` (Server- + Monitoring-Images nach ghcr.io) und `release.yml`
  (Desktop-DEB/RPM, Agent-Pakete + Binaries, Checksums, Draft-Release).
- **Periodische JWT-Blacklist-Bereinigung.** `cleanup_expired_blacklist` laeuft
  jetzt als System-Job (Intervall 6 h); zuvor wuchs die `token_blacklist`-
  Tabelle unbegrenzt.
- **Server-Bindung fuer API-Keys** (`api_keys.server_id`, inkl.
  Alembic-Migration mit Backfill).

### Changed

- **Docker-Images kommen aus ghcr.io**
  (`ghcr.io/ks98/adminhelper/{server,monitoring}`); `docker-compose.yml` und
  `.env.example` entsprechend vereinheitlicht.
- **Quellcode-Kommentare und README auf Englisch** vereinheitlicht; Doku-Links
  und CI-Beschreibung von GitLab auf GitHub umgestellt. Lokalisierte
  UI-Strings (DE/EN) bleiben unveraendert.

### Removed

- Toter Code: `ScriptSecurityError`, `ScriptTimeoutError`, ungenutzte
  `UserResponse` und die wirkungslose Hook-Sandbox.

### Fixed

- Alembic-`downgrade` Postgres-kompatibel (`sa.DateTime()` / `sa.String()`
  statt `sa.DATETIME()` / `sa.VARCHAR()`).

## [0.23.2] - 2026-05-03

### Fixed

**Desktop-Client: alte Connections nach Server-Wechsel sichtbar**

Beim Wechsel zwischen zwei AdminHelper-Servern (Login zu B nach Login zu A,
oder serverUrl-Aenderung in den Settings) blieben die Verbindungen vom
vorherigen Server im Desktop-Client sichtbar — sowohl im Memory-Store als
auch persistent in `connections.json` (Tauri-AppDataDir). Bei Fehlschlag
des Fetch-Calls zum neuen Server (z.B. falscher Port) blieb der alte Stand
unveraendert.

Drei Code-Pfade hatten den Connection-Reload nicht getriggert:

- `session.ts:login()` aktualisierte nur das Session-Objekt, ohne
  `connections.reloadForMode()` zu rufen → frischer Login zu Server B
  liess die alten Daten von Server A stehen, bis der User manuell die
  Connections-Page wechselte (was ohne Trigger auch nichts neu lud).
- `session.ts:logout()` setzte nur die Session auf `null`, leerte aber
  nicht den Connection-Cache → die Datei blieb voll mit Server-A-Daten
  und tauchte nach dem naechsten App-Start wieder auf.
- `settings.ts:saveSettings()` ignorierte serverUrl-Wechsel mit aktiver
  Session — das alte JWT gehoerte zum alten Server, der neue Server
  haette es abgelehnt, aber der User merkte das nie, weil kein Reload
  triggerte.

Fix: Login triggert nun `reloadForMode(settings, sess)` direkt nach dem
Token-Setzen. Logout leert vor dem Session-Reset den Connection-Cache
(Memory + Datei via `saveAll([])`). Settings erzwingen bei serverUrl-
Wechsel mit aktiver Session ein `serverLogout()`, sodass der User in den
needsLogin-Flow geschickt wird.

## [0.23.1] - 2026-05-03

### Highlights

**Server-zentrisches Provisioning** — bis v0.22.x war der Provision-Flow
fest an FRP gekoppelt; wer keinen Tunnel hatte, konnte den Token-Flow nicht
nutzen und bekam keinen Monitor-Agent-Key. Ab v0.23.x lebt Provisioning im
Server-Modul und liefert je nach Konfiguration optional FRP-Bundle und
Monitor-Key. Ein einziger Agent-Aufruf ersetzt das alte zweistufige Setup.

(v0.23.0 wurde lokal getaggt, aber nie auf origin gepusht — der CI-Job
scheiterte an einer Prettier-Verletzung in `Frp.svelte`. v0.23.1 enthaelt
denselben Funktionsumfang plus den Style-Fix.)

### Fixed

- `prettier --check` failte im CI-Job auf `Frp.svelte`, weil beim Entfernen
  der Provision-Modal-Einbindung eine ueberzaehlige Leerzeile stehengeblieben
  war. Inhaltlich kein Effekt, blockierte aber die Tag-Pipeline.

### Added

- Neues Backend-Modul `app.modules.provisioning` mit Endpoints
  `POST /api/servers/{id}/provision/token`, `GET /tokens` und
  `POST /activate` (Header `X-Provision-Token`). Activate-Antwort:
  `{ serverName, apiKey, monitorApiKey?, monitorUrl?, frp? }` —
  Felder sind `null`, wenn die jeweilige Komponente nicht konfiguriert
  oder nicht erreichbar ist. Resilience-Pattern: ausgefallener
  Monitor-Service blockiert das Provisioning nicht.
- Neuer Agent-Subbefehl `adminhelper-agent provision --url ... --token ... --server-id ...`
  in `internal/provision/`. Orchestriert Activate-Aufruf, dann je nach
  Antwort `monitor.Init` und `frpc.Apply`.
- Frontend: `ServerProvisionModal.svelte` an der Servers-Page (statt
  vorher in der Frp-Page); generiert genau einen `provision`-Befehl
  zum Kopieren.
- Tests: `server/tests/test_provisioning.py` mit pytest-httpx-Mocking
  fuer den Monitor-Service-Aufruf (8 Testfaelle, u.a. minimal/with-monitor/
  monitor-down/wrong-token/used-twice/wrong-server).
- Neue Test-Dependency: `pytest-httpx>=0.30` in `requirements-dev.txt`.

### Changed

- Tabelle `frp_provision_tokens` umbenannt zu `provision_tokens` per
  `op.rename_table` (nicht-destruktive Alembic-Migration
  `0494a8f377ef_rename_frp_provision_tokens_to_provision_tokens`).
  Constraints (PK, UNIQUE auf `hashed_token`, FK auf `servers`) werden
  von Postgres automatisch mit umbenannt.
- `frpc.Init` (HTTP + Datei + Service in einem) wurde zu `frpc.Apply`
  (nur Datei + Service) zerlegt — der HTTP-Activate-Aufruf wandert in
  das neue `internal/provision/` Package.
- `frp/models.py` exportiert `ProvisionToken` weiterhin (Re-Export aus
  `app.modules.provisioning.models`) als Backwards-Compat fuer Test-
  Fixtures, die das alte Symbol importieren.

### Removed (Breaking)

- Alte Endpoints `/api/frp/provision/{id}/token`, `/tokens` und `/activate`
  sind komplett entfernt — Pre-Release, kein Deprecation-Window.
  Das FRP-Modul behaelt nur noch `/api/frp/provision/{id}/config` und
  `/config-hash` fuer den laufenden Sync-Agent.
- Agent-Subbefehl `adminhelper-agent frpc init` ist entfernt — Setup
  laeuft nun ausschliesslich ueber `adminhelper-agent provision`.
- Frontend-API: `createMonitoringAgentKey()` (toter Code, war im alten
  Modal als Fallback gedacht) und der API-Type `MonitoringAgentKeyResult`
  sind weg. Die zugehoerigen Funktionen `listProvisionTokens` /
  `createProvisionToken` sind aus `lib/api/frp.ts` in das neue
  `lib/api/provisioning.ts` umgezogen, Types `FrpProvisionToken[…]`
  heissen jetzt `ProvisionToken[…]`.
- Versions-Bump aller Komponenten auf `v0.23.1` (Server, Monitoring,
  Web-Admin-Panel, Desktop-Client, Browser-Extension, Go-Agent via
  `.gitlab-ci.yml AGENT_VERSION`, 40 Doku-HTML-Footer).

## [0.22.1] - 2026-05-02

### Fixed

- `docker compose pull` scheiterte mit `pull access denied for
  adminhelper-monitoring`, weil das Monitoring-Image nirgends in
  der Registry lebte (es gab nur einen `docker_server`-Job). Neuer
  `docker_monitoring`-Job in `.gitlab-ci.yml` (1:1 analog zu
  `docker_server`) baut + pusht jetzt das Monitoring-Image nach
  `docker.nevondo.com/$CI_PROJECT_PATH/monitoring` mit den Tags
  SHA, `latest`, `dev` (main-Branch) und `$CI_COMMIT_TAG` (bei Tags).
  `MONITORING_IMAGE`-Default in `docker-compose.yml` zeigt jetzt
  auf den Registry-Pfad statt den nicht-pullbaren lokalen Tag.

### Changed

- Versions-Bump aller Komponenten auf `v0.22.1` (Patch-Release).

## [0.22.0] - 2026-05-02

### Changed

- Koordinierter Versions-Bump aller Komponenten auf `v0.22.0`
  (Server, Web-Admin-Panel, Desktop-Client, Browser-Extension,
  Go-Agent via `.gitlab-ci.yml AGENT_VERSION`, Doku-Footer in
  40 HTML-Dateien). Sammel-Release ohne funktionale Aenderungen.

### Fixed

- CI-Job `server_test` scheiterte mit `pytest: command not found`,
  weil `pytest` und `testcontainers` nur lokal im venv installiert
  waren, nicht in `requirements.txt`. Neu: `requirements-dev.txt`
  mit `pytest`, `pytest-asyncio` und `testcontainers[postgres]`;
  CI installiert beide Files. Production-Container (Dockerfile)
  bleibt schlanker, weil testcontainers + pytest nicht mehr in
  jedem Server-Image landen.

## [0.21.0] - 2026-05-02

### Highlights

**Pre-Release-Welle**: drei groesse Stoesse parallel gefahren —
Brand-Umbenennung **SimpleRemoteManager/SRM &rarr; AdminHelper**,
**6 P0-Sicherheits-Fixes** aus dem Pre-Release-Audit, und Migration
der Server-Side-Persistenz von **SQLite auf PostgreSQL 17**
(server + monitoring). Plus 2 P1-Cleanups, Plain-JS-Desktop-Client-
Reste entfernt, Doku komplett aufgeraeumt.

Beide FastAPI-Services teilen sich einen Postgres-Cluster mit zwei
DBs (`adminhelper`, `adminhelper_monitor`). Schema-Anlage uebernimmt
jetzt **Alembic** statt `Base.metadata.create_all()`. Tests laufen
gegen ein echtes Postgres via `testcontainers` (lokal) bzw.
`services: postgres:17-alpine` (CI), nicht mehr gegen SQLite-in-memory.

22 Commits seit v0.20.0.

### Brand

- Vollstaendige Umbenennung des Projekts von "SimpleRemoteManager"
  (intern auch "SRM") auf **"AdminHelper"** &mdash; in Doku, Code,
  Storage-Keys (localStorage `adminhelper_token`, `adminhelper_refresh_token`,
  `adminhelper_language`), Tauri-Keyring-Service (`com.adminhelper.app`),
  Browser-Extension, FRP-Provision-Token-Prefix, Go-Agent-Variablen.
- GitLab-Repo migriert auf <https://git.nevondo.com/ks98/adminhelper>;
  Doku-Verweise und CHANGELOG-Release-Links aktualisiert.
- Bewusst behalten: Legacy-Paketnamen (`srm-frpc-client`, `srm-monitor-agent`,
  `srm-agent`) in DEB-`Replaces`/RPM-`Obsoletes` &mdash; werden gebraucht
  fuer DEB/RPM-Upgrades von Vorgaenger-Installationen.

### Security (Pre-Release-Audit-Fixes)

- **P0-1**: API-Key wird jetzt zusaetzlich als Query-Parameter akzeptiert
  (`?api_key=...`), nicht nur als `X-API-Key`-Header &mdash; Browser-
  Extension funktionierte vorher gar nicht.
- **P0-2**: `MONITOR_API_KEY`-Mismatch zwischen server und monitoring
  geloest; `init-secrets.sh` generiert jetzt einen synchronen Wert.
  Vorher: Default-Setup hatte 401 auf jedem `/api/monitoring/*`-Aufruf.
- **P0-3**: Authorization-Bypass im FRP-Visitor-Bundle behoben &mdash;
  Non-Admin-User ohne Server-Zuweisungen sahen vorher *alle* STCP-Tunnel
  inklusive Secret-Keys (`if server_ids:`-Logik invertiert). Plus
  5 Regression-Tests in `test_frp_permissions.py`.
- **P0-4**: Frontend-Logout invalidiert JWT jetzt auch serverseitig
  via `POST /api/auth/logout`. Vorher: Token blieb 8h gueltig nach "Abmelden".
- **P0-5**: Security-Headers-Middleware hinzugefuegt
  (HSTS, CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy).
  CSP nur fuer SPA-HTML, nicht fuer `/api/docs` (Swagger-UI braucht CDN).
- **P0-6**: Default-Admin `admin/admin` entfernt; ersetzt durch
  Bootstrap-Token-Pattern (Vaultwarden/Gitea-Style). Server schreibt
  Setup-Token in `data/.bootstrap_token`, Admin wird ueber
  `POST /api/auth/bootstrap` angelegt. 6 neue Endpoint-Tests.
- **P1-6 + P1-7**: stale `server/frontend/`-Stub-Verzeichnis entfernt,
  Dead Config `MONITOR_AGENT_API_KEYS` aus `docker-compose.yml` raus.

### Database (SQLite &rarr; PostgreSQL)

- PostgreSQL 17 als neuer `postgres`-Service in `docker-compose.yml`
  mit Healthcheck und `service_healthy`-Dependencies fuer beide Apps.
- `server/alembic/` und `monitoring/alembic/` mit initialen Migrations.
- `monitoring/docker-entrypoint.sh` neu (vorher nur `CMD`).
- Server- und Monitoring-Entrypoint warten via `pg_isready` auf die DB
  und fuehren `alembic upgrade head` vor `uvicorn`-Start aus.
- `scripts/postgres-init.sh` legt beim ersten Postgres-Start die zweite
  DB (`adminhelper_monitor`) idempotent an.
- `scripts/pg-backup.sh` + `scripts/pg-restore.sh` fuer pg_dump-basiertes
  Backup beider DBs (Custom-Format, 7-Tage-Retention).
- Optionaler `pg-backup`-Service in `docker-compose.yml` (auskommentiert
  als Opt-In-Beispiel) &mdash; taegliche Backups nach `./backups/`.
- `init-secrets.sh` erzeugt zusaetzlich `POSTGRES_PASSWORD` (32 Bytes hex).
- `psycopg[binary]>=3.1`, `alembic>=1.13` in beiden requirements.txt.
- `testcontainers[postgres]>=4.7` als dev-dependency im server.
- Server-`pytest`-Job in `.gitlab-ci.yml` (existierte vorher nicht):
  nutzt `services: postgres:17-alpine` als CI-Sidecar.
- `tests/test_alembic_consistency.py`: Drift-Detector zwischen
  `Base.metadata` und Alembic-Migrations, laeuft bei jedem CI-Run.

### Other

- Plain-JS-Desktop-Client (`desktop/src/`, ~6670 Zeilen) komplett
  geloescht &mdash; war seit v0.19.0 nur noch historisch im Repo.
  8 Migrationskontext-Kommentare in `desktop-src/` bereinigt.
- `/api/docs` Swagger-UI-Pfad in der Doku korrigiert (war faelschlich
  als `/docs` dokumentiert; `app/main.py` setzt explizit
  `docs_url='/api/docs'`).
- README + DEVELOPMENT.md auf aktuellen v0.20.0-Stand gebracht
  (Lead-Beschreibung Svelte 5, Project-Tree mit `desktop-src/` +
  `frontend-src/` als produktiven Frontends).

### Changed

- Server-Side-DBs von SQLite auf PostgreSQL umgestellt:
  - `server/app/core/database.py` + `monitoring/app/core/database.py`:
    Engine ohne `check_same_thread`, dafuer Pool (size=10, overflow=20,
    pre-ping, recycle=3600).
  - `server/app/core/config.py` + `monitoring/app/core/config.py`:
    `DATABASE_URL` aus Env mit Postgres-Default-Fallback.
- Beide Dockerfiles installieren `postgresql-client` (fuer `pg_isready`),
  kopieren `alembic/`-Folder in den Container.
- `server/tests/conftest.py` komplett neu: testcontainers-Postgres,
  SAVEPOINT-Pattern fuer Test-Isolation (kein DROP/CREATE pro Test).
- Tests jetzt 78 (77 bestehende + 1 alembic-consistency); Wallclock
  ~17s lokal (12s Container-Boot einmalig), ~8s im Cache-Lauf.

### Removed

- `_migrate_connections_json`, `_migrate_add_columns`,
  `_migrate_visitors_to_users` aus `server/app/main.py` (PRAGMA-basierte
  SQLite-only Migrationen, jetzt durch Alembic ersetzt).
- `_migrate_columns`, `_migrate_agent_keys_to_hash` aus
  `monitoring/app/main.py` (gleiches Pattern).
- `Base.metadata.create_all()` aus beiden Lifespans (Alembic ist neuer
  Schema-Owner).
- `CONNECTIONS_FILE`-Konstante aus `server/app/core/config.py`
  (Konsument war `_migrate_connections_json`).
- `desktop/src/` (Plain-JS-Frontend) und 8 SQLite-Stub-Files unter
  `server/frontend/`.

### Migration

- Bestehende lokale `data/db.sqlite3` und `data/monitor.sqlite3` sind
  obsolete und koennen geloescht werden.
- Pre-Release-Status: keine Production-Datenmigration noetig.
- Beim Update bestehender Setups vor dem ersten Restart:
  `./scripts/init-secrets.sh` ausfuehren, damit `POSTGRES_PASSWORD`
  in der `.env` steht (sonst weigert sich der Postgres-Container).
- `data/`-Verzeichnis bleibt erhalten (Bootstrap-Token, .secret_key,
  FRP-PKI), nur die DB-Datei darin ist obsolete.

### Added

- PostgreSQL 17 als neuer `postgres`-Service in `docker-compose.yml`
  mit Healthcheck und `service_healthy`-Dependencies fuer beide Apps
- `server/alembic/` und `monitoring/alembic/` mit initialen Migrations
- `monitoring/docker-entrypoint.sh` neu (vorher nur `CMD`)
- Server- und Monitoring-Entrypoint warten via `pg_isready` auf die DB
  und fuehren `alembic upgrade head` vor `uvicorn`-Start aus
- `scripts/postgres-init.sh` legt beim ersten Postgres-Start die zweite
  DB (`adminhelper_monitor`) idempotent an
- `scripts/pg-backup.sh` + `scripts/pg-restore.sh` fuer pg_dump-basiertes
  Backup beider DBs (Custom-Format, 7-Tage-Retention)
- Optionaler `pg-backup`-Service in `docker-compose.yml` (auskommentiert
  als Opt-In-Beispiel) — taegliche Backups nach `./backups/`
- `init-secrets.sh` erzeugt zusaetzlich `POSTGRES_PASSWORD` (32 Bytes hex)
- `psycopg[binary]>=3.1` und `alembic>=1.13` in beiden requirements.txt
- `testcontainers[postgres]>=4.7` als dev-dependency im server
- Server-`pytest`-Job in `.gitlab-ci.yml` (existierte vorher nicht):
  nutzt `services: postgres:17-alpine` als CI-Sidecar
- `tests/test_alembic_consistency.py`: Drift-Detector zwischen
  `Base.metadata` und Alembic-Migrations, laeuft bei jedem CI-Run

### Changed

- Server-Side-DBs von SQLite auf PostgreSQL umgestellt:
  - `server/app/core/database.py` + `monitoring/app/core/database.py`:
    Engine ohne `check_same_thread`, dafuer Pool (size=10, overflow=20,
    pre-ping, recycle=3600)
  - `server/app/core/config.py` + `monitoring/app/core/config.py`:
    `DATABASE_URL` aus Env mit Postgres-Default-Fallback
- Beide Dockerfiles installieren `postgresql-client` (fuer `pg_isready`),
  kopieren `alembic/`-Folder in den Container
- `server/tests/conftest.py` komplett neu: testcontainers-Postgres,
  SAVEPOINT-Pattern fuer Test-Isolation (kein DROP/CREATE pro Test)
- Tests jetzt 78 (77 bestehende + 1 alembic-consistency); Wallclock
  ~17s lokal (12s Container-Boot einmalig), ~8s im Cache-Lauf

### Removed

- `_migrate_connections_json`, `_migrate_add_columns`,
  `_migrate_visitors_to_users` aus `server/app/main.py` (PRAGMA-basierte
  SQLite-only Migrationen, jetzt durch Alembic ersetzt)
- `_migrate_columns`, `_migrate_agent_keys_to_hash` aus
  `monitoring/app/main.py` (gleiches Pattern)
- `Base.metadata.create_all()` aus beiden Lifespans (Alembic ist neuer
  Schema-Owner)
- `CONNECTIONS_FILE`-Konstante aus `server/app/core/config.py`
  (Konsument war `_migrate_connections_json`)

### Migration

- Bestehende lokale `data/db.sqlite3` und `data/monitor.sqlite3` sind
  obsolete und koennen geloescht werden.
- Pre-Release-Status: keine Production-Datenmigration noetig.
- Beim Update bestehender Setups vor dem ersten Restart:
  `./scripts/init-secrets.sh` ausfuehren, damit `POSTGRES_PASSWORD`
  in der `.env` steht (sonst weigert sich der Postgres-Container).
- `data/`-Verzeichnis bleibt erhalten (Bootstrap-Token, .secret_key,
  FRP-PKI), nur die DB-Datei darin ist obsolete.

## [0.20.0] - 2026-04-19

### Changed

- Koordinierter Versions-Bump ueber alle Komponenten
  (Desktop-Client, Web-Admin-Panel, Go-Agent, Browser-Extension,
  Docker-Image, CI-Pipeline) auf `v0.20.0` — Sammel-Release ohne
  funktionale Aenderungen, um alle Artefakte wieder auf einen
  gemeinsamen Versions-Stand zu heben

## [0.19.1] - 2026-04-18

### Changed

- Einmalige Prettier-Formatierung ueber `frontend-src/` (rein
  kosmetisch, 31 Dateien)

### Fixed

- CI-Failure bei `npm run lint` im Frontend behoben: ESLint 9
  Flat-Config (`eslint.config.js`) eingefuehrt, `typescript-eslint` +
  `globals` als Dev-Dependencies ergaenzt, `.prettierignore` fuer
  `frontend-src/`

## [0.19.0] - 2026-04-18

### Highlights

Big-Bang-Migration des **Desktop-Clients** von Plain-JavaScript auf
**Svelte 5 + TypeScript + Vite** (11 Phasen). Das alte `desktop/src/`
wurde vollstaendig durch `desktop-src/` ersetzt und baut ueber
`npm --prefix ../desktop-src run build` in den Tauri-Release.
Funktional bleibt der Client unveraendert; intern ist alles typisiert
und reaktiv ueber Stores statt DOM-imperativen Managern.

Zusaetzlich in 0.19.0: mehrere Security-Haertungen (Refresh-Token-
Rotation mit Blacklist/Reuse-Detection, Login-Rate-Limit auf Redis,
Tauri-Capability-Scoping, PKI-Bundle-Zip-Slip-Schutz), ein komplett
ueberarbeitetes Monitoring-Dashboard sowie ein Doku-Komplett-Rewrite
mit getrennten Admin- und Developer-Sektionen (DE + EN).

### Added

- `desktop-src/` als eigenstaendiges Projekt (kein Monorepo) mit
  Svelte 5 Runes, TS strict, Vite-Build, Pfad-Aliassen (`$lib`)
- Typisierte Tauri-Bridge (`src/lib/bridge/`) mit 1:1-Mapping zu allen
  24 `#[tauri::command]` Backend-Funktionen
- Store-Architektur: `sessionStore`, `connectionsStore`, `tunnelStore`,
  `monitoringStore`, `ansibleStore`, `settingsStore`, `connectFlow`,
  `passwordPrompt`, `editorStore`, `statusBarStore`
- Seiten: Dashboard, Connections (mit Live-Suche + Kind/Group-Filter),
  Monitoring (Overview/Alerts/Log mit uPlot-Charts), Ansible
  (3-Stufen-Wizard mit Server/Tag-Auswahl)
- Modals: ConnectionEditor, PasswordPrompt (Promise-Continuation),
  SettingsModal (Sync/Server-Mode, RDP-Optionen, Sprache, Logout)
- Connect-Flow mit RDP-Race-Guard (monotone Connect-ID) und
  Tunnel-Auto-Resolve fuer Server-Modus
- Vitest-Suite: 41 Tests fuer Models (connection, settings, ansible,
  monitoring) und Stores (ansible, connections)
- Monitoring-Detail: Current-Values-Panel und Status-Timeline pro Check
- Grouped-View und Tree-View fuer die Connections-Seite
- Scroll-Beschleunigung als wiederverwendbare Svelte-Action
- Refresh-Token-Rotation mit Token-Blacklist und Reuse-Detection
  (kompromittierte Tokens werden erkannt und alle Sessions der
  betroffenen User-Kette invalidiert)
- Komplette Dokumentation neu aufgesetzt: getrennte Admin- und
  Developer-Sektionen, vollstaendige EN-Spiegelung unter `docs/en/`

### Changed

- `desktop/src-tauri/tauri.conf.json` `beforeBuildCommand` zeigt auf
  `../desktop-src` statt `../src`
- Sidebar-Version-Label auf `v0.19.0`
- Monitoring-Detail auf Sektions-Dashboard umgestellt: pro Server werden
  alle Checks in typ-spezifischen Sektionen (Heartbeat, Live, Network,
  Services, Docker, Backups, ZFS, SMART) gruppiert; jede Zeile klappt
  inline auf zu Perioden-Tabs (1h/6h/24h/7d) mit Graph und Timeline
- Monitoring-Dashboard v2: Card-Layout mit typ-spezifischen Heroes,
  Master-Detail-Layout fuer die Overview, Sektions-basiertes Dashboard
  statt Card-Grid
- Connections-Liste: Card fungiert als Connect-Button, Edit-Icon nur
  noch per Hover eingeblendet, aufgeraeumte Button-Anordnung
- Login-Rate-Limit auf Redis migriert (mit In-Memory-Fallback, wenn
  Redis nicht erreichbar ist) — skaliert ueber mehrere Server-Worker
  hinweg konsistent
- Tauri-Capabilities strikt gescopt (minimale Permissions statt
  Default-Allow-All), RDP-Fenstertitel werden sanitisiert
- i18n fuer Stores, Validatoren und `timeAgo` eingefuehrt, i18n-Leaks
  in AppShell/App/Connections geschlossen
- `metricLabel` als eigenes Modul ausgelagert, toter Alert-Log-Wrapper
  entfernt

### Fixed

- RDP-Race-Condition zwischen aufeinanderfolgenden Connects ueber
  Correlation-IDs geschlossen
- `lastUsed` wird pro Connect-Modus getrennt gefuehrt (statt global)
- `trustCert`-Checkbox logisch zu RDP zugeordnet (war faelschlich
  auch bei Web aktiv)
- Transparente Modals durch fehlende `--bg-panel`- und
  `--bg-input`-CSS-Variablen beseitigt
- PKI-Bundle-Import gegen Zip-Slip und Zip-Bomb geschuetzt, erzeugte
  Secrets landen mit `0600` auf der Platte
- Visuelle Regressionen, Monitoring-TLS-Handling und i18n-Engine
  in der Desktop-UI

### Removed

- Altes Plain-JS-Frontend (`desktop/src/`) wird vom Tauri-Build nicht
  mehr verwendet (bleibt historisch im Repo erhalten, bis alle
  Referenzen entfernt sind)
- Monitoring-Card-Grid, Filter-Bar, View-Switch und Hero-Komponenten
  (`MonCheckPanel/Card/Row`, `MonFilterBar`, `MonDetailPanel`,
  `hero/Hero*.svelte`) — ersetzt durch `MonServerDashboard` +
  `section/Sec*.svelte` mit wiederverwendbarem `MonCheckLine`-Snippet

## [0.17.0] - 2026-04-18

### Highlights

Big-Bang-Migration des Web-Admin-Panels von Plain-JavaScript auf
**Svelte 5 + TypeScript + Vite** (12 Phasen). Das alte `server/frontend/`
wurde vollstaendig durch `frontend-src/` ersetzt und wird im Docker-Image
ueber einen Multi-Stage-Build ausgeliefert.

### Added

- Svelte 5 Frontend in `frontend-src/` mit Hash-Router, Token-Auth,
  i18n (DE/EN), Toast- und ConfirmDialog-Komponenten
- UI-Komponentenbibliothek (`Button`, `Modal`, `TagChip`, `Tabs`,
  `EmptyState`, uvm.) mit einheitlichem Design-System
- Alle 8 Produktiv-Seiten portiert: Connections, Servers, Users,
  API-Keys, Hooks, Ansible, FRP-Tunnels, Monitoring
- Monitoring-Seite mit uPlot-Charts fuer SMART-Temperaturen und
  Resource-Gauges
- Playwright E2E-Tests: Smoke-Tests fuer alle 8 Routen + Login,
  Visual-Diff Screenshots (`frontend-src/tests/e2e/`)
- CI: neue `check`-Stage mit `frontend_check` (svelte-check + lint)
  und `frontend_e2e` (Playwright mit HTML-Report-Artifact)
- Repo-Root `Dockerfile` als Multi-Stage-Build (Vite-Build ->
  Python-Runtime) und `.dockerignore`
- SMART-Health-Monitoring mit Kind-Erkennung (SATA/SAS/NVMe),
  Temperatur-Thresholds und NVMe-Bit-Dekodierung

### Changed

- `docker_server`-CI-Job: Build-Context auf Repo-Root (`-f Dockerfile .`)
- `server/app/main.py`: Static-Mounts auf Vite-Output angepasst
  (`/assets`, `/fonts`), SPA-Fallback prueft erst Datei-Existenz
- Agent-Version auf 0.17.0 synchronisiert (Desktop, Extension,
  Go-Agent-Pakete)

### Fixed

- Strict-MIME-Error auf `/assets/*.js` durch dedizierten Static-Mount
- Unterstrichene Sidebar-Menueeintraege (Browser-Default fuer `<a href>`)
- Fehlende Modal-Body-/Footer-Styles (Buttons klebten aneinander)
- Favicon-Referenz in `index.html` korrigiert (`/logo.svg`)
- Redirect nach Login via `$effect` statt nur in `onMount`

### Removed

- Altes Plain-JS-Frontend (`server/frontend/`) und separates
  `server/Dockerfile` + `server/.dockerignore`

## Vorherige Versionen

Aeltere Releases siehe Git-Tags `v0.7.0` bis `v0.16.0`.

[0.39.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.39.0
[0.38.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.38.0
[0.37.2]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.37.2
[0.37.1]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.37.1
[0.37.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.37.0
[0.36.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.36.0
[0.35.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.35.0
[0.34.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.34.0
[0.33.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.33.0
[0.32.1]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.32.1
[0.32.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.32.0
[0.31.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.31.0
[0.30.4]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.30.4
[0.30.3]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.30.3
[0.30.2]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.30.2
[0.30.1]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.30.1
[0.30.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.30.0
[0.29.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.29.0
[0.28.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.28.0
[0.27.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.27.0
[0.26.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.26.0
[0.25.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.25.0
[0.24.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.24.0
[0.23.2]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.23.2
[0.23.1]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.23.1
[0.22.1]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.22.1
[0.22.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.22.0
[0.21.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.21.0
[0.20.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.20.0
[0.19.1]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.19.1
[0.19.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.19.0
[0.17.0]: https://github.com/AdminCave/AdminHelper/releases/tag/v0.17.0
