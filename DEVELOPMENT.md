# Entwicklungsumgebung einrichten

Anleitung zum lokalen Entwickeln von Client und Server auf **Debian 13 (Trixie)**.

## Voraussetzungen

### System-Pakete installieren

```bash
sudo apt install -y \
  build-essential \
  curl \
  pkg-config \
  libssl-dev \
  libwebkit2gtk-4.1-dev \
  libjavascriptcoregtk-4.1-dev \
  libsoup-3.0-dev \
  libgtk-3-dev \
  libappindicator3-dev \
  librsvg2-dev \
  patchelf
```

### Rust Toolchain

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
```

### Tauri CLI

```bash
cargo install tauri-cli
```

### Python venv (Server)

```bash
cd apps/server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # zieht requirements.in (lose) + Test-Deps
```

### Python-Dependencies & Lockfiles

`apps/server`, `apps/monitoring` und `apps/ca-issuer` trennen **Intent** von **Lock**:

- `requirements.in` — die editierbare Quelle (lose `>=`-Constraints). Hier
  Dependencies hinzufügen/ändern.
- `requirements.txt` — die **generierte, gepinnte + gehashte** Lockfile, die der
  Production-Container per `pip install --require-hashes` installiert
  (Supply-Chain-Integrität). **Nicht von Hand editieren.**

Lock neu erzeugen (im passenden Python wie im Dockerfile, derzeit 3.12):

```bash
docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -v "$PWD/apps/server:/w" -w /w python:3.12-slim \
  sh -c "pip install -q --user pip-tools && \
         python -m piptools compile --generate-hashes \
           --output-file=requirements.txt requirements.in"
```

Tests/CI installieren `requirements.in` (lose, ungehasht) — `--require-hashes`
verträgt keine Mischung aus gehashten und ungehashten Zeilen. Den Stand, den das
Image ausliefert, prüfen die CI-Jobs `python-lock-server`, `-monitoring` und
`-ca-issuer` (Python wie im Dockerfile): erst der Lock mit `--require-hashes`, dann
`requirements-dev.txt` in einem zweiten Aufruf (`-c requirements.txt` scheitert an
Extras), dann `scripts/dev/lock-pins.py`, das jeden Pin nennt, den die
Dev-Dependencies verschoben haben. Lokal genauso nach `source .devenv.sh`, das Venv
unter `~/.cache` (nie das geteilte `AH_VENV`, nie `/tmp`) und mit dem Python des
Dockerfiles — `lock-pins.py` prüft den Interpreter nicht; unter 3.13 wäre es grün, ohne
den Stand des Images zu zeigen. Fehlt `python3.12` im PATH (Debian 13 bringt 3.13 mit):
erst ein 3.12 bereitstellen (Paketquelle, pyenv oder uv), dann das Rezept.

```bash
python3.12 -m venv ~/.cache/ah-venv-lock-server && . ~/.cache/ah-venv-lock-server/bin/activate
cd apps/server && pip install --require-hashes -r requirements.txt && pip install -r requirements-dev.txt
python ../../scripts/dev/lock-pins.py requirements.txt && DATABASE_URL="$AH_TEST_DB" pytest -q -m "not schemathesis"
```

- `requirements-dev.txt` — die **Test-Dependencies** je Dienst (`-r requirements.in`
  plus pytest & Generatoren). Eine Wahrheit pro Dienst: `scripts/tests/run.sh` und
  `.github/workflows/ci.yml` installieren beide genau diese Datei, nie eine
  Paketliste im Skript.

### Generatoren (Schemathesis, Hypothesis, pytest-alembic)

Drei Fehlerklassen findet niemand von Hand: eine Eingabe, an die keiner gedacht
hat, ein Vertrag, der still bricht, und ein Lock, das nur unter echter
Gleichzeitigkeit etwas tut. Dafür erzeugen diese Suiten ihre Eingaben selbst.

- **Schemathesis** fuzzt jeden Dienst gegen seine *eigene* OpenAPI, einmal je
  Authentifizierungs-Kontext. Eigener `run.sh`-Schritt `schemathesis` (nicht Teil
  der pytest-Schritte — die wählen den Marker mit `-m "not schemathesis"` ab,
  sonst liefe die Suite zweimal). Im PR-CI fährt ihn ein **eigener Job**
  (`Schema fuzzing`, alle drei Dienste, eigener Postgres-Service) über denselben
  `run.sh`-Aufruf. Der Knopf heißt `AH_SCHEMATHESIS_EXAMPLES`: **0** lokal **und** im
  PR-CI fährt nur die explizite Phase (die Beispiele des Schemas und die Coverage-Fälle
  von Schemathesis). Sie schickt für denselben Baum dieselben Fälle, ein roter Lauf
  liegt also am Diff und ist lokal nachstellbar. Eine Zahl **> 0** fährt alle Phasen
  mit so vielen erzeugten Beispielen je Operation: **100** im Wochenlauf (`heavy.sh`
  setzt es, `scripts/vm/iter.sh` reicht es an die Box weiter). Die Phase `generate`
  ist nicht wiederholbar (siehe Hypothesis unten); ihre Funde kommen deshalb aus dem
  Wochenlauf und gehen als Zeile in die Roadmap.
- **Integer-Lint** statt Glück: `apps/<dienst>/tests/test_openapi_integer_bounds.py`
  verlangt für jeden Integer-Eingang des veröffentlichten Schemas ein `maximum`.
  Das ist die Fehlerklasse, die die Phase `generate` bisher zufällig fand (`2**63`
  in einer `OFFSET`- oder INTEGER-Spalte).
- **Versionen gepinnt:** `hypothesis` und `schemathesis` stehen in den drei
  `requirements-dev.txt` exakt (`==`); ein neues Release ändert die Fälle erst mit
  einem Commit. Das gilt im CI-Job und in jedem `run.sh`-Lauf, dessen pytest-Schritte
  die `requirements-dev.txt` installieren; ein Lauf nur mit `--step schemathesis` nimmt
  das venv, wie es ist. Prüfwerkzeug: `bash scripts/tests/schemathesis_determinism.sh
  [--only <dienst…>]` fährt den Gate-Schritt je Dienst zweimal und vergleicht die
  Fälle je Test als `curl`-Protokoll (`<dienst>: N cases, M differing lines`, Exit 0
  nur bei 0 Abweichungen). Für den Server nur fahren, wenn keine andere Server-Suite
  auf derselben Test-DB läuft.
- **Ausschlüsse** stehen als Eintrag mit Grund und Wiedervorlage in
  `apps/<dienst>/tests/schemathesis_exclude.toml` — nie als Flag im Skript. Der
  Test prüft jede `operation_id` gegen das Schema: ein Tippfehler dort schließt
  nichts aus und sagt nichts, also ist er ein Fehler.
- **Hypothesis** deckt drei Ziele ab: den FRP-TOML-Round-Trip, das
  VictoriaMetrics-Line-Protocol und den SSRF-Guard. Gepinnte Fälle stehen als
  `@example` im Test und werden mitcommittet; die Beispieldatenbank `.hypothesis/`
  ist lokaler Cache und gitignored. Die Suiten laufen `derandomize` (Profil `gate`
  in der jeweiligen `conftest.py`) und ziehen damit keinen neuen Seed je Lauf.
  **Wiederholbar ist die Generierung damit nicht:** Zwei Läufe desselben Baums zogen
  im Schemathesis-Gate andere Daten (Monitoring mit allen Phasen: rund 930 von 4000
  `curl`-Zeilen verschieden, R-0063). Ein bekannter Eingang sind die Literale der
  geladenen Quelldateien, die Hypothesis in die Generierung einspeist (Cache je Datei
  unter `.hypothesis/constants/`, kein Schalter dagegen); der Rest der Ursache ist nicht
  bestimmt. Ein Fund aus einer erzeugten Phase ist deshalb eine Suche, kein Beweis, dass
  der Diff ihn verursacht hat.
- **Postgres-gegattert:** Der Concurrency-Test (`with_for_update` in
  `check_engine`) und die pytest-alembic-Ketten brauchen ein echtes Postgres und
  skippen, solange `DATABASE_URL` nicht auf ein Postgres zeigt — auf der Dev-Box
  ist das der Normalfall, CI stellt einen Service. Nicht nur „gesetzt": eine
  SQLite-URL macht `FOR UPDATE` zum No-op, der Test liefe dann grün, ohne je ein
  Lock geprüft zu haben. `run.sh` kennt diese Skips und gattert sie auf dasselbe
  Merkmal: zeigt `DATABASE_URL` auf ein Postgres, ist ein Skip dort ein Fehler.

**Dependency-Updates laufen agent-getrieben** (kein Dependabot mehr): Versionen
in der `.in` anheben bzw. `pip-compile --upgrade` fahren, Lock regenerieren,
Tests grün, committen. Für npm/cargo/go analog über die jeweiligen Update-Befehle.

### Python-Lint/Format (ruff)

Alle drei Python-Komponenten und die Python-Skripte unter `scripts/` nutzen
[ruff](https://docs.astral.sh/ruff/) (Lint + Formatter, Config in `ruff.toml` im
Repo-Root):

```bash
ruff check apps/server apps/monitoring apps/ca-issuer scripts    # Lint (--fix behebt)
ruff format apps/server apps/monitoring apps/ca-issuer scripts   # Formatieren
```

`scripts/tests/run.sh` lintet dieselben Pfade — die drei Komponenten im Schritt
`ruff`, ganz `scripts/` im Schritt `ruff-vm` (Key `scripts`; die Id stammt aus der
Zeit, als er nur `scripts/vm` abdeckte) — und findet ruff auch dann, wenn es nicht
im `PATH` liegt, sondern nur in einem Komponenten-venv. Der CI-Job `python-lint`
prueft genau diese vier Pfade mit dem gepinnten ruff. `apps/server/requirements-dev.txt`
pinnt mit `ruff==` dieselbe Version wie `ci.yml` und `scripts/vm/bootstrap_linux.sh`
(kein Boden), ebenso `VENV_PKGS` in `scripts/dev/runner-setup.sh` fuer das Tool-Venv des
Runners; `scripts/dev/toolchain-lockstep.sh` prueft die Gleichheit. Ein anderes
ruff im `AH_VENV` zieht der Schritt `server-pytest` beim naechsten Lauf auf diese
Version zurueck. `ruff.toml` verlangt sie zusaetzlich per `required-version`: jedes
andere ruff bricht in diesem Baum mit Exit 2 ab, statt still andere Regeln anzuwenden —
auch im Format-Hook `scripts/dev/format-file.sh`, der dann still gar nicht formatiert
(sein Exit bleibt 0).

### Python-Tests lokal (ohne Docker)

`monitoring` und `ca-issuer` sind reine Logik-Suiten und brauchen **kein** Postgres.
Ihre Test-Deps stehen in der jeweiligen `requirements-dev.txt` — bei `ca-issuer` auch
`httpx`, das nur der starlette-`TestClient` der Tests braucht, nicht die App selbst
(deshalb steht es dort und nicht in `requirements.in`):

```bash
apps/monitoring/.venv/bin/pip install -r apps/monitoring/requirements-dev.txt   # einmalig
apps/monitoring/.venv/bin/python -m pytest -q
apps/ca-issuer/.venv/bin/pip install -r apps/ca-issuer/requirements-dev.txt     # einmalig
apps/ca-issuer/.venv/bin/python -m pytest -q
```

`server`-pytest braucht ein Postgres — entweder testcontainers (Docker) **oder** ein
injiziertes `DATABASE_URL` (conftest wählt automatisch). Docker-frei einmalig eine
Test-Rolle + -DB anlegen. Wichtig: `CREATEDB` ist Pflicht, weil die Alembic-Smoke
(`test_migrations_smoke.py`) pro Lauf eine Wegwerf-DB anlegt:

```bash
sudo -u postgres psql \
  -c "CREATE ROLE adminhelper LOGIN CREATEDB PASSWORD 'adminhelper';" \
  -c "CREATE DATABASE adminhelper_test OWNER adminhelper;"

# DATABASE_URL NUR für die server-Suite setzen — global gesetzt würde es
# monitorings Alembic-Smoke fälschlich gegen das falsche Schema aktivieren:
DATABASE_URL="postgresql+psycopg://adminhelper:adminhelper@localhost:5432/adminhelper_test" \
  apps/server/.venv/bin/python -m pytest -q
```

**Eine Lane hat ihre eigene Test-DB.** `bash scripts/dev/lane.sh new <slug>` legt auf demselben
Server `adminhelper_test_<slug>` an (Bindestriche werden zu `_`) und schreibt der Lane eine eigene
`.devenv.sh`: Sie sourct die des Haupt-Checkouts und biegt danach `AH_TEST_DB` auf diese DB und
`AH_VENV` auf `~/.cache/ah-venv-<slug>` um. `lane.sh done <slug>` löscht beides wieder. Die Rolle
braucht dafür `CREATEDB`, die sie oben ohnehin hat. Steht das Passwort als `Benutzer:Passwort@` in der
URL, reist es in `PGPASSWORD`, nicht in einem Argument von `createdb`/`dropdb`; kann `lane.sh` es dort
nicht herauslösen, legt es keine Lane an.
Was `new` angelegt hat, steht in der Marke `.vm/lanes/<slug>` des Haupt-Checkouts (`db=`, `venv=`),
und `done` löscht genau das, nichts sonst; eine DB oder ein Venv gleichen Namens, das keine Lane
angelegt hat, bleibt stehen. Kann `done` einen Eintrag nicht entfernen (etwa ohne `.devenv.sh` oder
weil `dropdb` scheitert), bleibt die Marke, und `new <slug>` verweigert den Slug als „never closed".
Ausweg: `done <slug>` erneut aufrufen, sobald die Ursache weg ist, oder die DB von Hand löschen und
die Marke entfernen.

**Die schweren Python-Schritte laufen nacheinander.** `server-pytest` und `schemathesis` holen
in `run.sh` vor dem Start eine Sperre (`flock`), gleich aus welchem Checkout: zwei Server-Suiten
auf einer Box haben einander die Tabellen und den Speicher genommen, bis zum OOM-Killer. Die
Sperrdatei wählt `run.sh` in dieser Reihenfolge: `AH_PY_LOCK_FILE`, wenn gesetzt; sonst die
**geteilte** Datei `/var/lib/adminhelper-dev/py.lock` (Pfad über `AH_PY_LOCK_SHARED`), sobald
ihr Verzeichnis existiert; sonst je Nutzer `~/.cache/adminhelper-py.lock`. Verzeichnis und Datei
legt `runner-setup.sh` an (Abschnitt „Runner-User"): über sie warten Kevins Läufe und die des
Runners aufeinander. Ohne das Verzeichnis gilt die Sperre nur **je Unix-Nutzer**, über alle seine
Checkouts. Darf ein Nutzer die geteilte Datei nur lesen, sperrt der Schritt trotzdem, nur ohne
Halter-Zeile; lässt sie sich gar nicht öffnen (fehlt sie und darf er sie nicht anlegen, oder ist
das Verzeichnis für ihn nicht durchsuchbar), ist der Schritt ein SKIP mit Grund und Abhilfe — kein Rückfall auf die Datei je
Nutzer, denn dort träfe er die Läufe der anderen nicht.
Ist die Sperre belegt, sagt der Schritt einmal, wer sie hält (nur druckbare Zeichen), und
**wartet** — bis `AH_PY_LOCK_WAIT` Sekunden (Default 3600). Danach gibt er als SKIP mit Grund
auf, unter `--strict` also `strict-failed`: nicht gelaufen, kein Befund über den Code. Alle
anderen Schritte laufen weiter parallel. `AH_PY_LOCK=0` schaltet die Sperre ab, gedacht für
eine Box, auf der ohnehin nur ein Lauf existiert.

Wer `pytest` von Hand startet statt über `run.sh`/`verify.sh`, läuft an der Sperre vorbei. Dann
gilt weiter: **ein `server`-Lauf zur Zeit** je Test-DB. Zwei gleichzeitige Läufe räumen einander
die Tabellen weg (die Alembic-Smoke legt pro Lauf eine Wegwerf-DB an), und das Ergebnis ist
**verworfen, nicht rot** — es sagt weder „grün" noch „kaputt", nur „nichts bewiesen".

### Schnelltest einer Komponente: verify.sh

`scripts/dev/verify.sh` ist die eine Form, in der eine Task-`Verify:`-Zeile eine
Komponenten-Suite startet. Es sourct `.devenv.sh` (bzw. `$AH_DEVENV`), loest
`AH_TEST_DB` auf und delegiert an `scripts/tests/run.sh`:

```bash
bash scripts/dev/verify.sh <komponente> [<komponente> …] [--strict] [--tree <pfad>] [-- <args>]

bash scripts/dev/verify.sh monitoring --strict           # eine Komponente
bash scripts/dev/verify.sh web desktop-e2e --strict      # mehrere, in einem Lauf
bash scripts/dev/verify.sh server -- tests/test_auth.py  # gezielt eine Datei
bash scripts/dev/verify.sh all --strict                  # der ganze quick-Layer
bash scripts/dev/verify.sh web --tree ../lane-b          # ein anderer Worktree
```

Komponenten: `server monitoring ca-issuer agent desktop desktop-rs desktop-ui
desktop-e2e web scripts` und `all` (nur allein). Mehrere Komponenten werden ein Lauf
`run.sh quick --only <a> <b>`; Argumente nach `--` gibt es nur fuer eine Komponente, sonst
Exit 2. Ein Lauf, der die Suite erreicht, hinterlaesst
`.ah-out/last-verify.json` (das Artefakt von `run.sh` plus `component` — bei mehreren die
Liste —, `args`, `tree`) — die Evidenz, dass ein Gruen zu einem bestimmten Baum gehoert.
Ein Lauf, der vorher abbricht (vertippte Komponente), schreibt **keine** Datei und
loescht eine aeltere: veraltete Evidenz ist schlechter als fehlende.

Jeder Lauf bekommt ein eigenes `TMPDIR` (`${TMPDIR:-/tmp}/ah-verify.XXXXXXXX`) und
loescht genau dieses Verzeichnis am Ende, den Exit-Code reicht er unveraendert durch
(R-0098): ein Aufraeumer, der nach `/tmp/tmp.*` greift, trifft die Fixtures eines
parallel laufenden Tests nicht mehr. Die Kehrseite: das `tmp_path` von pytest ist nach
dem Lauf weg. Wer einen Rest zum Debuggen braucht, faehrt `run.sh` direkt: der bleibt
vorerst im `TMPDIR` des Aufrufers (meist `/tmp`).

Der Grund fuer den Wrapper ist die Allowlist: eine Bash-Allow-Regel matcht nie
ueber ein Env-Praefix, `source .devenv.sh && DATABASE_URL=… pytest` ist also
nicht freigebbar. Env-Bedarf loest das Skript auf, der Aufrufer schreibt Flags.

### OpenAPI-Snapshot aktualisieren

`apps/server/tests/openapi.snapshot.json` und `apps/monitoring/tests/openapi.snapshot.json`
sind der eingecheckte Vertrag der beiden APIs. Web-Frontend, Desktop-UI und Agent werden
**nicht** gegen ihn kompiliert — ein umbenanntes Feld faellt dort erst zur Laufzeit auf.
Der Snapshot macht jede solche Aenderung zu einem Review-Diff, und der CI-Job
`openapi-compat` vergleicht ihn per `oasdiff` gegen den Basis-Branch.

Aendert eine Task die API, gehoert die neue Aufzeichnung in **denselben Commit**:

```bash
cd apps/server     && pytest tests/test_openapi_snapshot.py --update-openapi-snapshot
cd apps/monitoring && pytest tests/test_openapi_snapshot.py --update-openapi-snapshot
```

Ohne das Flag vergleicht der Test nur und zeigt bei Abweichung einen gekuerzten
Unified-Diff. Der Test braucht keine Datenbank (der App-Import reicht), `info.version`
wird auf `0.0.0` normalisiert und ein `servers`-Feld entfernt — sonst waere jeder Release
ein Snapshot-Diff ohne Vertragsaenderung.

`oasdiff` gehoert zu keiner Pflicht-Suite — fehlt das Binary, meldet der Check Exit 75 (SKIP)
statt rot zu werden. Wer das Gate vor dem Push selbst sehen will, holt sich das fertige
Release-Binary:

```bash
# Stand 2026-09-23. Massgeblich ist .github/workflows/ci.yml (Job openapi-compat,
# OASDIFF_VERSION und OASDIFF_SHA256_LINUX_AMD64) — von dort uebernehmen, damit
# lokal und CI dieselbe Fassung messen.
V=1.32.0
S=5b2050787cfee2a9a3ba7b25cb50fe2c5cc45cdf5b96fbc51a4a60107f8b4aad
curl -sSfL -o /tmp/oasdiff.tgz \
  "https://github.com/oasdiff/oasdiff/releases/download/v${V}/oasdiff_${V}_linux_amd64.tar.gz" &&
  echo "${S}  /tmp/oasdiff.tgz" | sha256sum -c - &&
  mkdir -p ~/.local/bin &&
  tar xzf /tmp/oasdiff.tgz -C ~/.local/bin oasdiff
```

Die Schritte haengen mit `&&` zusammen, damit ein Pruefsummen-Fehlschlag das Entpacken
wirklich verhindert: `sha256sum -c -` meldet den Fehler, stoppt aber von sich aus nichts, und
ein gueltiges Archiv mit falschem Inhalt landete sonst trotzdem in `~/.local/bin`. In CI
uebernimmt das `bash -e`, mit dem GitHub jeden `run:`-Schritt faehrt; beim Einfuegen in eine
normale Shell gibt es das nicht.

Das Release-Binary statt `go install`: jede oasdiff-Fassung ab v1.24.0 verlangt `go 1.26` in
ihrer go.mod, waehrend die Workflows Go 1.25 mit `GOTOOLCHAIN=local` pinnen — aus der Quelle
bauen scheitert dort genauso wie seinerzeit `govulncheck` (PR #14). Ein Tarball braucht gar
keine Toolchain, und die Pruefsumme macht ein ausgetauschtes Asset zum Fehler statt zur
Ueberraschung.

Lokal gegen den Basis-Branch pruefen (braucht `oasdiff` im PATH, sonst Exit 75 = SKIP):

```bash
bash scripts/dev/openapi-breaking.sh server --base origin/main
bash scripts/dev/openapi-breaking.sh monitoring --base origin/main
```

### Geteilte API-Typen (sync-from-web.sh --check)

`apps/web/src/lib/api/types.ts` und `apps/desktop/ui/src/lib/api/types.ts` sind
**keine** gemeinsame Datei mehr: das Web beschreibt die Admin-Panel-API (25
Exporte), das Desktop die Client-API (58). Gemeinsam sind vier Symbole —
`FrpConfig`, `FrpStatus`, `FrpStatusProxy`, `Server`.

```bash
bash apps/desktop/ui/scripts/sync-from-web.sh --check   # Gate (CI: desktop-ui)
```

Geprueft wird die Schnittmenge, und zwar als **Teilmenge**: jede Zeile des
Web-Blocks muss im Desktop-Block stehen, das Desktop darf mehr fuehren. Das ist
kein Kompromiss, sondern die richtige Invariante — `Server` traegt im Desktop
zusaetzlich `connections?: Connection[]`, weil `to_dict()` das Feld liefert und
nur das Admin-Panel es ignoriert. Der reale Drift, den die Regel faengt: das Web
zieht ein neues Server-Feld nach, das Desktop nicht.

Quell-Exporte ohne Gegenstueck im Ziel werden nur berichtet, nicht bemaengelt.
Die vier erwarteten gemeinsamen Symbole stehen namentlich im Skript
(`CHECK_SHARED`): verschwindet eines von einer Seite, ist das ein Fehler, keine
kleinere gruene Menge. Ein blosser Zaehl-Boden haette erst bei zwei gleichzeitigen
Verlusten gegriffen — der realistische Fall ist der einzelne Refactor.

**Wo der Guard blind ist:** die Loeschrichtung. Entfernt das Web ein Feld, bleibt
die Teilmenge erfuellt — das Desktop behaelt die Leiche, und niemand meldet es.
Das ist die einzige der sechs Drift-Formen, die die Regel nicht faengt
(umbenannt, Typ geaendert, im Ziel entfernt: alle rot).

**`--apply` ist fuer diese Datei tot** und der bestehende Ueberschreib-Schutz
haelt es so: er bricht ab, sobald das Ziel Exporte hat, die die Quelle nicht
kennt — und das sind 54.

### Doku-Smoke (doc-smoke.py)

`scripts/dev/doc-smoke.py` prueft, ob die Dokumentation den Baum noch beschreibt:
jedes `<code>`-Fragment in `docs/**/*.html`, das mit `apps/`, `scripts/`, `docs/`,
`.github/` oder `.claude/` beginnt, muss eine existierende Datei benennen (`--paths`), und
ein `<code>`, das ganz aus einem Namen in Grossbuchstaben besteht, muss ausserhalb der Doku
im Repo vorkommen (`--env`: die drei `config.py`, `.env.example` oder eine getrackte Datei
ausserhalb von `docs/`, `CHANGELOG.md` und `tasks/`, R-0044).

```bash
python3 scripts/dev/doc-smoke.py                          # nur Pfade, nur berichten (Exit 0)
python3 scripts/dev/doc-smoke.py --paths --env --strict   # Gate wie in CI (ops-scripts): Funde = Exit 1
python3 scripts/dev/doc-smoke.py --env                    # --env allein prueft NUR die Namen
```

Die Existenz wird gegen `git ls-files` aufgeloest, nicht gegen den Arbeitsbaum:
sonst waere der Guard lokal gruen und im CI rot, weil Build-Ausgaben wie
`apps/web/dist/` nur auf der Entwickler-Box liegen.

Ausnahmen stehen in `scripts/dev/doc-smoke-allow.txt`, eine Zeile je Eintrag mit
Begruendung nach `#`. Der Deckel liegt bei **fuenf** Eintraegen: darueber
verweigert das Skript den Dienst (Exit 2). Eine Ausnahmeliste ist der Ort, an dem
so ein Guard verrottet — waechst sie, ist die Doku zu korrigieren, nicht die Liste.

`--env` vergleicht `<code>`-Fragmente in Grossbuchstaben gegen die Env-Namen der
drei `config.py` und `.env.example`. Es ist bewusst noch **kein** Gate: die
Heuristik meldet aktuell 43 Namen, die gar keine Env-Variablen sind (HTTP-Methoden,
Log-Level, Dateinamen wie `SHA256SUMS`). Erst nach deren Triage wandert `--env` in
den CI-Step.

### AH_REQUIRED in .devenv.sh

`--strict` macht aus einem SKIP einen Fehler — aber nur fuer die Steps der
**Required-Menge**. Die haengt vom Rechner ab (diese Box hat kein Display,
`run.sh e2e --strict` waere hier also dauerhaft rot), deshalb steht sie in der
gitignoreten `.devenv.sh` und ueberschreibt `AH_REQUIRED_DEFAULT` aus `run.sh`.
Die gueltigen Step-Ids stehen im Kopf von `scripts/tests/run.sh`. Beispiel fuer
eine Box ohne frpc-Sidecar (also ohne `cargo test (desktop)`): Die Datei bleibt auf der
Dev-Box: `vm.py sync` schliesst sie aus, damit auf einer Box `AH_REQUIRED` ungesetzt bleibt
und die Box-Regel aus `run.sh` greift (alle Schritte eines schweren Layers Pflicht).

```bash
export AH_REQUIRED="ruff ruff-vm shellcheck server-pytest monitoring-pytest ca-issuer-pytest go-agent desktop-ui-vitest web-vitest scripts vm-pytest dev-pytest"
```

Auf dieser Box deckt sich die Menge mit dem Default; ohne die Zeile gilt er. Die wirksame Menge druckt `run.sh` unter
`--strict` in die Summary, damit sie nicht still schrumpfen kann. Ein strenger
Lauf, in dem **kein** Step lief, ist ebenfalls ein Fehler — sonst meldete er
gruen, ohne etwas geprueft zu haben.

**Auf einer Box gilt die Box-Regel:** ist `AH_REQUIRED` *nicht* gesetzt und der
Layer `integration`, `e2e` oder `all`, nimmt `run.sh` alle Schritte dieses Layers
in die Pflicht-Menge auf (inklusive der Layer-Guards `integration` und
`desktop-e2e-gui`) — auf einer Box mit Docker und Display gibt es keinen Grund,
warum ein schwerer Schritt still uebersprungen werden duerfte. `scripts/vm/iter.sh`
reicht ein gesetztes `AH_REQUIRED` an die Box weiter; `heavy.sh` setzt die
Dev-Box-Menge deshalb vor dem Box-Lauf zurueck (`AH_REQUIRED_BOX` benennt eine
Box-Menge explizit). Ein gesetztes `AH_REQUIRED` gewinnt immer unveraendert.

### Session-Status-Hook

`scripts/dev/hooks/session-status.sh` laeuft als `SessionStart`-Hook
(`.claude/settings.json`) und druckt einen `AH-STATUS`-Block: Checkout und
Dirty-Stand, `tauri.conf.json`-Version gegen den letzten Tag, alle Punkte von „Als
Naechstes" (je die erste Zeile) und darunter die WIP-Zeile aus `roadmap.py show --wip`, an den
Deckeln aus `CLAUDE.md` gemessen und bei einem erreichten Deckel mit `Warnung:`, dann aktive
Ledger, offene PRs und warme Boxen. Je Workflow mit `schedule:` folgt eine Zeile
`Geplant: <name> <Tag> (<n> d): <conclusion>` fuer den neuesten abgeschlossenen Lauf auf
`main`, Cron oder `workflow_dispatch` — ein per Dispatch bestaetigter Fix schliesst einen roten
Cron wie in `heavy.sh`; `WARN:` bei `failure`, `timed_out` oder `startup_failure` (mit
`gh run view <id> --log-failed`) und bei einem Lauf aelter als 8 Tage, wobei ein toter Cron erst
8 Tage nach dem letzten Dispatch auffaellt. Ohne `gh` steht dort `?`, ohne `WARN:`. Er ist rein lesend,
endet immer mit 0 und warnt nur bei den Triggern aus `CLAUDE.md` §3 und bei einem roten oder
veralteten geplanten Workflow — kein Trigger, keine `WARN:`-Zeile. `AH_AUTONOMOUS=1` schaltet ihn stumm (der Hook
feuert auch in `claude -p`). Manuell: `bash scripts/dev/hooks/session-status.sh`.

### Task schliessen: `ledger.sh` und `task-close.sh`

Seit Harness-Stufe 4 setzt **kein Modell mehr selbst einen Haken und macht keinen
Commit**. Der Weg einer Task ist:

```bash
bash scripts/dev/ledger.sh start tasks/<slug>.md T7      # .vm/active-task: Komponente + Dateien
# ... bauen, gezielt testen, Review ...
bash scripts/dev/task-close.sh tasks/<slug>.md T7 --stage --review-note "approve (sonnet)" -m "feat(...): ..."
```

`--stage` stagt die Pfade aus der `Dateien:`-Zeile der Task (nur die, nie `git add -A`;
Verzeichnisse werden abgelehnt, Loeschungen mitgenommen).
Das ist kein Komfort: beim Runner ist `git add` hart verboten, ein autonomer Lauf, der von
Hand stagen will, kommt nicht weiter; in Kevins Sessions ist es frei.

`task-close.sh` laeuft **ausserhalb** der Modell-Session und macht fuenf Dinge in
dieser Reihenfolge: (1) jede Datei aus `Dateien:` muss vollstaendig gestaged sein
(halb gestaged, ungestaged oder untracked bricht ab), Tree-Hash und Index merken (aendert sich
der Index bis zum Commit, Exit 2); (2) die billigen Pruefer, vor der Suite (R-0150): `review.sh diff-scan`
(abgeschaltete Tests im Diff: Skip-, xfail-, todo-, fixme- und only-Muster von pytest, unittest,
vitest/jest, Playwright, Rust und Go, auch `fit(`, `.fails(`, `.runIf(` und `pytest.importorskip(`, <!-- review: ok nennt die Muster -->
`|| true` und `set +e`, eine geloeschte Assertion — auch die <!-- review: ok nennt die Muster -->
Rust-Makros `assert_…!` und in Go-Tests `t.Fatal…`/`t.Error…`, gezaehlt nur, wo Tests stehen:
in einer Testdatei (`tests/`, `e2e/`, `test_*.py`, `*_test.{py,go,sh}`, `*.test.*`, `*.spec.*`)
oder in der Spanne eines Tests, etwa einem inline `#[test]` unter `src/`, auch nach einer
Umbenennung; eine Import-Zeile nie (R-0130); Helfer in `#[cfg(test)] mod tests` ohne `#[test]`
bleiben eine Grenze — und ein `return` in einem Test, nackt oder mit dem Wert, den ein Test
ohnehin liefert (`None`, `undefined`, `Ok(())`), auch in einer Datei mit CRLF-Zeilen (R-0132; andere
Rueckgabewerte und ein generisches `.fail(` bleiben frei), wenn noch Code des Tests folgt und es
nicht in einer darin verschachtelten Funktion steht (Stub, Callback; ein Go-`t.Run` ist ein Test); eine Zeile, die das bewusst tut, traegt `# review: ok <grund>`, eine Doku-Zeile,
die ein Muster zitiert, `<!-- review: ok <grund> -->`; ein ganzer Test darf gehen, wenn die Task ihn schon committet
als `Test-Löschung:` ankündigt, eine Assertion in einem bleibenden Test darf sich ändern, wenn die Task das als
`Assertion-Änderung:` ankündigt und mindestens so viele Assertions zurückbringt — geprüft am Inhalt, siehe
`tasks/README.md`), `review.sh scope` (Fremd-Pfade),
`review.sh docs-pairs` (eine Doku-Seite ohne ihre andere Sprache) und `review.sh sec` (was nie ins
oeffentliche Repo darf); (3) das
`Verify:` der Task, wie sie dasteht: die Komponenten aus `bash scripts/dev/verify.sh <a> [<b> …]
--strict [-- <args>]` oder `bash scripts/tests/run.sh <layer> --strict --only <a> [<b> …]` als
`verify.sh <a> [<b> …] --strict` (fehlt die `Komponente:` der Task in der Liste, Exit 2; eine
Prosa-Zeile faehrt die Komponente der Task, mit Hinweis), danach `review.sh contracts` (die
Pruefungen, die an den geaenderten Pfaden haengen); (4) das Review-Urteil:
`--review-note "<text>"`, `--review verdict:<datei>`, die `review.sh check-verdict` gegen Schema und Tree-Hash
prueft, oder `--review auto`, der Reviewer als eigener Prozess (Stufe 6b, „Reviewer als Prozess"); (5) `ledger.sh
mark-done` mit der Summary-Zeile dieses Laufs als `Evidenz:` (sie nennt die gelaufenen
Komponenten, etwa `run.sh[quick] web desktop-e2e: 2 passed, 0 failed, 16 skipped`, und liefen Vertraege,
` · contracts: 1 ok`) und **ein** Commit
mit Code und Ledger; war es die letzte offene Task, setzt derselbe Commit den Kopf von
`aktiv` auf `bereit` (sonst stuende das Ledger mit `aktiv` ohne offene Task im Baum, und
`ledger_test` waere rot). Exit-Codes: `0` committed, `2` nicht (voll) gestaged oder
Eingabefehler (auch ein unlesbares oder schemawidriges Verdict) oder der Index aenderte sich waehrend des
Laufs, `3` Suite rot, Diff-Scan-Fund, eine Doku-Seite in nur einer Sprache, ein roter Vertrag, kein brauchbares
approve oder eine dritte Review-Runde, `4` blockiert (Scope/Sec) oder ein Verdict fuer einen anderen Baum oder eine
andere Task, `74` die Suite, ein Vertrags-Test, die Probe oder der Reviewer-Prozess konnte gar nicht laufen.

`ledger.sh start` schreibt dabei `.vm/active-task` — reine **Anzeige** (wer arbeitet
gerade woran); geprueft wird spaeter die `Dateien:`-Zeile der Task selbst, und kein Skript liest
die Datei, auch der Worker (Stufe 7a) nicht.

`ledger.sh` ist die einzige Stelle, die ein Ledger schreibt (`start`, `mark-done`,
`mark-skip`, `mark-question`, `set-files`, `status`, `new-task`, `lint`) — Details
in [`tasks/README.md`](tasks/README.md). Braucht eine Task eine Datei, die nicht in
ihrem `Dateien:` steht, erweitert `ledger.sh set-files` die Liste **sichtbar**;
den Scope zu lockern ist nicht vorgesehen. Ohne Eintrag erlaubt sind ohnehin die
Test-Verzeichnisse der Komponente, `docs/`, `CHANGELOG.md` und der Ledger selbst —
**ausser** den Dateien aus `scripts/dev/harness-paths.txt`: die muessen benannt werden,
sonst waere `scripts/tests/run.sh` als „Test der Komponente scripts" eine offene Tuer.

**`--evidence` ist ein Feld, kein Beweis.** `ledger.sh mark-done` nimmt jede Zeichenkette
entgegen; was die Zeile wahr macht, ist ausschliesslich, dass `task-close.sh` sie aus dem
Artefakt des Laufs erzeugt, den es selbst gefahren hat. Deshalb steht `mark-done` in Kevins
Settings unter `ask` und beim Runner im Deny. Eine Zeile mit `# review: ok <grund>`
nimmt sie aus dem Diff-Scan — bewusst und mit Begruendung in derselben Zeile.

`git add`, `git commit`, `git checkout`, `git restore` und `git stash` sind in den
Runner-Settings (`scripts/dev/runner-settings.json`) hart verboten und in Kevins Sessions
frei — eine Abfrage, die immer bestaetigt wird, hielt nur den Bau auf (zwei Worker verloren
daran je 45 Minuten). Unter `permissions.ask` in `.claude/settings.json` stehen nur
`bootstrap_linux.sh`, `harness.sh off` und `ledger.sh mark-done`, und
`scripts/tests/hooks_test.sh` haelt fest, dass die Git-Verben dort nicht zurueckkehren. Der Weg
zum Commit fuehrt ueber `task-close.sh`; die drei Recovery-Verben loeschen im Zweifel
ungestagte Arbeit.

**`.gitattributes`: `CHANGELOG.md merge=union`.** Zwei Lanes, die beide unter
`## [Unreleased]` etwas anhaengen, bekommen damit keinen Konflikt — union nimmt **beide**
Seiten. Das dedupliziert aber nichts: legen beide dieselbe Versions-Ueberschrift an, steht
sie hinterher doppelt im File, ohne Konflikt-Marker. Vor einem Release lohnt der Blick in
den `Unreleased`-Block (`.claude/rules/release.md`).

### Review-Pruefer (Ebene 0)

Bevor ein Modell einen Diff ansieht, beantworten Skripte die Fragen, die sonst jeder Reviewer
raten muesste (Stufe 6a; Uebersicht in `docs/developer/cicd.html`, „Review-Pruefer und Verdict"):

```bash
bash scripts/dev/review.sh risk                           # xhigh + Pfade | standard: welches Reviewer-Modell
bash scripts/dev/review.sh docs-pairs --staged            # Doku-Seite ohne ihre andere Sprache -> Exit 3
bash scripts/dev/review.sh contracts --staged [--list]    # die Pruefungen der geaenderten Pfade
bash scripts/dev/review.sh check-verdict <datei> --tree <hash> [--task <ledger> <id>]   # 0 | 2 | 3 | 4
bash scripts/dev/review-probe.sh <komponente> [--staged | --commit <rev>] [-- <test>]
bash scripts/dev/review-probe.sh <komponente> --commit <rev> --mutate <datei>:<zeile> '<ersatz>'
bash scripts/dev/review.sh pr-body tasks/<slug>.md [--verdicts <dir>]
bash scripts/dev/review.sh log [--ledger tasks/<slug>.md]          # jede Reviewer-Runde, mit Summe
```

- **`risk`** misst ohne Flag alles noch nicht Committete (gestaged, ungestaged, untrackt —
  feature-build fragt es in Schritt 4, bevor etwas gestaged ist), mit `--staged` nur den Index,
  mit `--range <a>..<b>` einen Bereich. Es liest `scripts/dev/review-risk.txt` (PKI/mTLS, Auth,
  SSRF, FRP, Wire-Vertraege, Alembic, CI/Release/Install) und `harness-paths.txt`, jeweils so,
  wie HEAD, Index und Worktree sie haben: ein Diff, der eine Zeile streicht, wird nicht an
  seiner eigenen Liste gemessen. Eine Verschiebung zaehlt auch mit ihrem alten Pfad.
- **`contracts`** liest `scripts/dev/review-contracts.txt`: `<glob> test <komponente> <testdatei>`
  (laeuft als `verify.sh <komponente> --strict -- <testdatei>`, mit eigenem `AH_OUT_DIR`) oder
  `<glob> pair <regex> <datei> <datei>` (der erste Capture ist in beiden gleich). Die Liste gilt
  ebenfalls aus HEAD, Index und Worktree. Wer das Format einer Paar-Stelle aendert, geht deshalb
  in zwei Schritten: erst ein Regex, der beide Schreibweisen nimmt, dann das neue Format.
- **`check-verdict`** prueft ein Reviewer-Urteil gegen `scripts/dev/review-verdict.schema.json`
  (nur mit python3): kein approve mit einem `blocker`, keins, wenn die Probe den neuen Test ohne
  die Aenderung gruen fand; ein `blocker` ohne Beleg zaehlt als `nit`. Mit `--task` muss das
  Verdict auch diese Task meinen (sonst Exit 4). Schema-Version 2 (der Reviewer-Prozess) verlangt
  Runde, Turns, Dauer und den `probe`-Block; eine Probe mit `applicable: false` (etwa
  `no-test-change`, ein Refactor) ist kein Hindernis, ein ueberlebender Mutant steht in der
  Review-Zeile, ebenso eine Probe, die nicht lief (`probe not run: toolchain|other-failure|…`).
  `only-declared-deletion` ist auch kein Hindernis, steht aber sichtbar in der Review-Zeile
  (`probe: only a declared test deletion, not run`): das lockert ein Gate (R-0227).
- **`declared-only`** (`<komponente> (--staged | --commit <rev>) --task <ledger> <id>`) sagt, ob
  der Diff unter den Testpfaden der Komponente nur aus angekuendigten `Test-Löschung:`-Tests
  besteht: keine Zeile hinzugefuegt, jede entfernte Zeile leer, ein Import, der keine Tests
  mitbringt (kein `*`, kein Name `test…`/`Test…`, in JS/TS kein blosser Import und keiner einer
  `.test`/`.spec`-Datei; ein Go-Importblock nur vor der ersten Deklaration), oder in der alten
  Spanne eines angekuendigten Tests, der nach den Regeln von `diff-scan` zaehlt (derselbe Code).
  Die Ankuendigung kommt aus dem Ledger vor der Aenderung (`HEAD` bzw. `<rev>^`). Exit 0 ja, 1 nein.
- **`review-probe.sh`** legt eine eigene Worktree unter dem `TMPDIR` des Aufrufers an, setzt nur
  die Test-Hunks auf die Basis und faehrt `verify.sh --tree`; die Antwort ist der `probe`-Block
  des Schemas (`red_without_change`, oder `applicable: false` mit `new-symbol`, `toolchain`,
  `no-test-change`, `only-test-change`, `only-declared-deletion`, `apply-failed`, `other-failure`;
  `no-test-change`, `only-test-change` und `only-declared-deletion` ohne Suite-Lauf, der letzte nur mit
  `--task`, wie es `task-close.sh` uebergibt). `--mutate` setzt genau einen Mutanten in die
  ganze Aenderung (eine Datei der Worktree, sonst Exit 2); der Ersatz muss lint-sauber sein.
- **`pr-body`** schreibt den PR-Text aus dem Ledger; eine Task ohne Evidenz heisst
  „unverifiziert", Adressen, Hostnamen privater Netze und VMIDs fallen heraus. Mit
  `--verdicts .ah-out/review/<slug>` nimmt es je Task die letzte Runde `<id>.r<n>.verdict.json`
  (oder `<id>.json`) und prueft sie ueber `check-verdict` selbst: ein schemawidriges Verdict heisst
  „ungueltig", eines ohne brauchbares approve sagt warum; die Zeile nennt Modell, Runde und
  Mutanten.
- **`log`** liest `.ah-out/review/review-log.jsonl`, eine Zeile je Reviewer-Runde (Datum, Ledger,
  Task, Runde, Modell, Effort, Urteil, Funde, Probe, Mutanten, `cost_usd`, `num_turns`,
  `duration_s`, Tree), und druckt sie als Tabelle mit der Summe
  `N runs, A approve, R request_changes, F failed, $X, T turns, S s`. Die Zeilen schreibt
  `task-close.sh --review auto` (`log --append <verdict>`, eine gescheiterte Runde mit
  `log --failed "<grund>"`).

### Reviewer als Prozess: `--review auto` (Stufe 6b)

Im Pilot (Ledger-Kopf `Review: auto`) startet `task-close.sh` den Task-Reviewer selbst, statt
dass die Bau-Session einen Sub-Agent fragt; Prompt und Urteil gehen nicht durch die Session:

```bash
bash scripts/dev/task-close.sh tasks/<slug>.md T3 --stage --review auto -m "feat(...): ..."
bash scripts/dev/review.sh log --ledger tasks/<slug>.md      # Runden, Urteile, $, Turns, Sekunden
```

Nach den billigen Pruefern, der Suite und den Vertraegen:

1. **Runde:** gezaehlt aus den Dateien unter `.ah-out/review/<slug>/`. Liegt fuer genau diesen
   gestagten Diff, Baum und diese Task schon ein approve (ein Abschluss brach danach ab, etwa am
   Commit), wird es uebernommen. Eine dritte Runde gibt es nicht (Exit 3 mit Hinweis auf
   `ledger.sh mark-question`).
2. **Probe durch den Runner:** `review-probe.sh <komponente> --staged [-- <test aus Verify:>]`;
   ohne Testdatei oder nur mit Tests antwortet sie `applicable: false`, ohne Suite-Lauf.
3. **Reviewer:** `scripts/dev/review-run.sh` baut den Prompt (Task-Text, Spec-Pfad, gestagter
   Diff ohne `tasks/private/`, neue Dateien, Tree-Hash, Probe, Vertraege, Verify-Summary; in
   Runde 2 der Pfad der Runde 1) und startet aus dem Repo-Wurzelverzeichnis `claude -p` mit dem
   Reviewer aus `scripts/dev/review-agent.md` (als `--agents`-JSON), `--setting-sources ""` (weder
   Projekt- noch User-Settings: deren Allow-Regeln deckelt `review-settings.json` nicht),
   den Settings `scripts/dev/review-settings.json` und dem Schema
   `scripts/dev/review-output.schema.json`. Das Modell folgt `review.sh risk --staged`:
   `standard` ist Sonnet/high mit 60 Turns und 5 $, `xhigh` Opus/xhigh mit 80 Turns und 15 $;
   Timeout 1200 s. Die Deckel werden nach dem Pilot aus den Werten von `review.sh log`
   nachgestellt.
4. **Verdict:** aus `structured_output` plus den Feldern des Runners (Task, Tree-Hash, Probe,
   Verify, Vertraege, Kosten, Turns, Dauer) wird `<id>.r<n>.verdict.json` (Schema-Version 2),
   daneben liegen `prompt.md`, `raw.json`, `err` (stderr der CLI), `run.err` (stderr von
   review-run.sh) und `staged` (der Hash des gestagten Diffs, an dem die Uebernahme eines approve
   haengt) der Runde, alles unter `.ah-out/`, gitignored. `check-verdict --tree --task` entscheidet, ob committet wird; jede Runde geht als
   Zeile ins Review-Log.
5. **Scheitern:** kein Start, Timeout, ein `error_*`-Ergebnis, ein Exit ungleich 0 oder ein
   fehlendes oder schemawidriges `structured_output` sind Exit 74, ohne Verdict und ohne Commit;
   im Log steht die Runde als `failed` mit Grund. Die Session versucht es einmal neu, danach
   STOPP; einen Rueckfall auf den Sub-Agent-Review gibt es nicht.

Der Reviewer darf lesen und `git diff|show|log|status`; im Pilot setzt er keine Mutanten (Kevin,
2026-10-03): ein `review-probe.sh --mutate` laeuft als Code mit den Rechten des Benutzers. Mutanten
kommen zurueck, sobald es feste Operatoren oder eine Sandbox gibt (Roadmap); von Hand bleibt
`--mutate` nutzbar. Edit, Write, Netz, `verify.sh` und `run.sh` sind gesperrt. Der
harness-guard laeuft als PreToolUse-Hook und ist fail-closed: fehlt er, scheitert oder haengt
er, blockiert der Hook (R-0159). Die Projekt-Settings wirken nicht hinein. Die Aufrufform hat
`scripts/dev/review-cli-probe.sh` gemessen (CLI 2.1.285); gegen eine neue CLI-Version laesst
sie sich mit demselben Skript erneut messen.

### Die Roadmap als Skript: `roadmap.py`

`tasks/private/ROADMAP.md` (privates Repo) bleibt Markdown, das Kevin lesen und von Hand
aendern kann; den Abschnitt „Als Naechstes" kuratiert er allein. `scripts/dev/roadmap.py` (nur
Python-Stdlib) liest den Kopf (`Stand: … · WIP: …`) und die Tabellenzeilen mit ihren zehn
Spalten; alles andere, also Prosa, „Als Naechstes" und Leerzeilen, reicht es byte-gleich
durch. Zeilen legen Kevin und die Skripte an (`heavy.sh`, spaeter die Finder); `/roadmap`
zeigt und triagiert sie (`.claude/skills/roadmap/SKILL.md`).

```bash
python3 scripts/dev/roadmap.py lint                      # tasks/private/ROADMAP.md
python3 scripts/dev/roadmap.py --file /tmp/x.md lint     # eine andere Datei
python3 scripts/dev/roadmap.py show [R-nnnn] [--wip]
python3 scripts/dev/roadmap.py next [--status freigegeben] [--exclude-components server web]
python3 scripts/dev/roadmap.py add --class REG --title "…" --source "weekly 2026-09-25 · 1a2b3c4d" \
    [--proof <branch@sha>] [--dedup-key reg:web-vitest] [--ledger tasks/reg-….md]
python3 scripts/dev/roadmap.py status R-nnnn geplant [--note "…"] [--ledger tasks/<slug>.md] [--pr "#<n>"]
python3 scripts/dev/roadmap.py approve R-nnnn [--revoke]
python3 scripts/dev/roadmap.py sync
python3 scripts/dev/roadmap.py stats [--days 30]
```

- `lint` meldet je Fund eine Zeile mit ID und Zeilennummer: doppelte IDs, unbekannte Status
  (die Aliase `geparkt` und `erledigt` beim Namen), Zeilen im falschen Abschnitt, Zeilen ohne
  genau zehn Spalten (ein unmaskiertes `|` im Text macht eine elfte; `\|` ist erlaubt),
  einen `Dedup-Key:`, den zwei offene Zeilen tragen, und einen WIP-Kopf, der nicht zu den
  Zeilen passt. Exit 0 sauber, 1 Funde, 2 Aufruf falsch oder Datei fehlt.
- `show` liest nur: ohne Argument „Als Naechstes" woertlich, die WIP-Zaehler aus den Zeilen,
  die offenen Abschnitte mit ihren Zeilen und die Historie als Anzahl; mit einer ID die Zeile
  Feld fuer Feld; mit `--wip` nur die Zaehler (die liest der Status-Hook).
- `next` nennt die naechste Zeile zum Bauen: Klasse vor Reihenfolge (SEC > REG > REL > BUG >
  FEAT > REF > IDEE), wartet, solange „Haengt ab von" eine Zeile nennt, die nicht
  `abgeschlossen` ist, und ueberspringt Zeilen, die eine ausgeschlossene Komponente
  beruehren (`Komponente:` ihres Ledgers, die Komponente eines vollen Dedup-Keys
  `<klasse>:<komponente>:<datei>:<symbol>`; ein kurzer wie `reg:<schritt>` nennt keine).
  Das Ledger liest `next` aus dem Arbeitsbaum und von jedem lokalen und Remote-Branch, der
  den Pfad traegt, und vereinigt die Komponenten: ein geplantes Ledger liegt bis zum Merge
  nur auf seinem Branch (R-0065). `next` fetcht nicht — wer auf `origin/*` angewiesen ist
  (etwa der Worker-Klon), fuehrt vorher `git fetch --prune` aus; eine veraltete Kopie auf
  einem alten Branch schliesst hoechstens zu viel aus. Mit `--exclude-components` gilt
  fail-closed: nennt die Spalte `Ledger` einen Pfad `tasks/….md`, den weder der Baum noch
  ein Branch traegt, wird die Zeile uebersprungen, und stderr sagt es
  (`next: R-nnnn skipped — ledger <pfad> not found in the tree or on any branch (git fetch?)`).
  Ohne Ausschlussliste, bei `—`, einem Slug oder einem Pfad ausserhalb des Repos bleibt die
  Zeile im Rennen.
  Nichts bereit: Exit 1.
- `add` haengt eine `neu`-Zeile an „Neu" an und druckt ihre ID: die hoechste `R-nnnn` plus
  eins, gezaehlt ueber die Datei und ueber alle IDs, die das Skript je vergeben hat. So kommt
  eine ID, die ein Hand-Edit wieder entfernt hat, nicht ein zweites Mal. `--proof` und
  `Dedup-Key: <key>` stehen mit in „Quelle / Beweis"; `Ablauf` folgt der Klasse (IDEE 60
  Tage, REF 90 Tage, sonst `nie`). Bei 20 `neu`-Zeilen ist Schluss (Exit 3). Traegt eine
  offene Zeile den Dedup-Key schon, ist das Exit 4 mit ihrer ID, und ein leerer Commit
  `roadmap: dedup <key> -> R-nnnn` haelt die Weigerung fuer `stats` fest.
- `status` setzt den Status und verschiebt die Zeile in den Abschnitt, der zu ihm gehoert.
  Erlaubt sind nur die Uebergaenge der Tabelle `TRANSITIONS` im Skript (sonst Exit 2);
  derselbe Status erneut sortiert eine falsch abgelegte Zeile ein und macht aus einem Alias
  das Wort. Ein geschlossener Status (`abgeschlossen`, `abgelehnt`) traegt den Tag; mehr
  als 30 Tage danach wandert die Zeile beim naechsten Schreiben oben ins „Archiv".
  `--ledger` schreibt die Spalte `Ledger` wie `add --ledger`, auch ohne Statuswechsel — so
  bekommt eine aeltere Zeile ihr Ledger nachgetragen; `next` und die Parallel-Pruefung am
  Gate lesen es dort, nicht aus der Notiz. Ebenso schreibt `--pr "#<n>"` die Spalte `PR`,
  die `sync` liest; eine Nummer in der Notiz sieht `sync` nicht, und ein Wert ohne `#<n>`
  ist Exit 2.
- `approve` ist `geplant` -> `freigegeben`, Kevins Freigabe; `--revoke` nimmt sie zurueck.
- `sync` fragt `gh pr list --state merged`: eine Zeile im Status `pr`, deren PR-Spalte nur
  gemergte PRs nennt, wird `abgeschlossen <Merge-Tag> (PR #n)`. Eine Zeile in einem anderen
  Status (etwa eine Stufe mit mehreren PRs, noch `aktiv`) meldet es nur; `sync` ueberspringt
  keinen Status, denn ein Schliessen laesst sich nicht zuruecknehmen. Den Push des privaten
  Repos druckt es, ausfuehren tut es ihn nicht. Laeuft `gh` nicht, scheitert es oder liefert
  kein lesbares JSON: Exit 74.
- `stats` zaehlt Tasks pro Tag (netto abgehakte `[x]` in `git log -p -- tasks/*.md`),
  Kevin-Minuten pro PR, die Wartezeit je Zustand aus der Historie der Datei, die Stale-Quote
  (offene Zeilen ueber ihrem Ablauf) und die Dedup-Quote. Seine Fenster sind ganze UTC-Tage,
  damit dieselbe Frage auf jeder Maschine dieselbe Antwort hat.

**Schreibregeln.** Jedes Schreiben (`add`, `status`, `approve`, `sync`) laeuft unter `flock`
auf `<datei>.lock` und legt vorher `<datei>.bak` an. Es prueft danach die Zeilenzahl: vorher
plus erwartete Aenderung muss nachher ergeben, sonst geht die `.bak` zurueck (Exit 6). Es
rechnet den Kopf `Stand: <heute> · WIP: …` aus den Zeilen neu und committet die eine Datei in
ihrem eigenen Repo (`roadmap: <verb> <id>`): lokal, nie gepusht, nur wenn das Verzeichnis der
Datei die Wurzel dieses Repos ist, und nie in diesem oeffentlichen Repo. In einem Klon,
dessen `tasks/private` ein gewoehnliches Verzeichnis ist, entsteht deshalb kein Commit. Hat
jemand anders die Datei in den letzten 5 Sekunden geaendert, verweigert es (Exit 5), denn ein
Editor koennte sie noch halten. Die Marke der eigenen letzten Schreibung (mtime und sha256)
und die hoechste vergebene ID stehen in der Lock-Datei; auch der Dedup-Commit entsteht noch
unter der Sperre.

Die Datei ist `--file`, sonst `AH_ROADMAP`, sonst `tasks/private/ROADMAP.md`. Tests
arbeiten **nie** auf der echten Datei, sondern auf Fixtures in einem Temp-Verzeichnis, die
sie per `--file` oder `AH_ROADMAP` benennen; das Datum fuer Ablauf, Archiv und Kopf setzt
`--today`. Die Tests unter `scripts/dev/tests/` faehrt
der `run.sh`-Schritt `scripts/dev pytest` (Id `dev-pytest`, Key `scripts`), gleich gebaut
wie `vm.py pytest`: er braucht nur `pytest` und ist unter `--strict` Pflicht.

### Harness-Schutz und Kill-Switch

`scripts/dev/harness-paths.txt` listet die Dateien, deren Inhalt die **Regeln**
bestimmt (`CLAUDE.md`, `AUTONOMOUS.md`, `.claude/**`, die Gate-Skripte unter
`scripts/dev/`, `run.sh`, `heavy.sh`, `vm.py`). Der `PreToolUse`-Hook
`scripts/dev/hooks/harness-guard.sh` ermittelt vor jedem `Edit`/`Write`/`MultiEdit`/
`Bash`, welche Datei der Aufruf schreiben wuerde — inklusive `sed -i`, `tee`,
`>`-Umleitung, `cp`/`mv` und `bash -c` — und verweigert ihn, wenn sie auf der Liste
steht. Eine Eingabe-Umleitung (`<`, `<<<`, `<&`) verdeckt dabei weder das Kommando noch das
Ziel von `cp`/`mv` (R-0134), ein gequotetes `"<"` bleibt ein Wort; Grenzen bleiben eine
Prozess-Substitution `<(…)` und `<<- EOF` mit Leerzeichen. Ein Kommentar (`#` am Wortanfang)
oeffnet nichts, kein `((`, kein Here-Doc, keine Quote; ein `#` mitten im Wort liest shlex dagegen
als Kommentarbeginn (Grenze, R-0145). Was ein wegnehmendes Kommando erreicht (`rm`, `rmdir`, `shred`, `unlink`,
`chmod`/`chown`/`chgrp`, die Quelle von `mv`, der Startpfad eines loeschenden `find`),
trifft auch, wenn Harness-Pfade **darunter** liegen: `rm -rf .claude`, `rm -rf
scripts/dev/hooks`, `chmod -R -x scripts/dev/hooks`, ein Glob mit dem, was er im Baum trifft
(`rm -rf scripts/dev/*`, auch nach einem `cd` in einen Glob; hinter einer Variablen zaehlt sein
Verzeichnis), und die Repo-Wurzel samt allem darueber, die alles enthaelt (`rm -rf ./*`,
`rm -rf ..`; R-0127). Das trifft im autonomen Lauf auch einen harmlos wirkenden Aufraeumer, der
in der Wurzel startet (`find . -name '*.pyc' -delete`): er startet im Unterverzeichnis
(`find apps -name '*.pyc' -delete`); `rm -f *.log` bleibt frei, der Glob trifft nur die Logs. Alle anderen Schreibformen
pruefen nur den Pfad selbst. Fuer Shell-Kommandos ist das **best effort**: ein Schreibvorgang aus
python/perl heraus, ein zur Laufzeit gebauter Pfad, ein `find … -exec sed -i`,
`git clean` oder `git rm` kommen durch (der Skript-Kopf zaehlt die Luecken auf). Auch git schreibt
ueber Ausgabe-Optionen: `--output` jedes git-Aufrufs (auch hinter `--`, das ein Optionswert schlucken
kann; ein Argument namens `--output…`, Pfad oder Optionswert, ist dafuer ein Fehlalarm), `-o` von archive, das Verzeichnis von
`format-patch -o`, die Datei von `bundle create` zaehlen als Ziel, und der Befehl hinter `git grep -O`
wird mit den Dateien geprueft, die er bekommt (R-0158). Im Runner ist der
Hook **fail-closed** (R-0159): Claude Code laesst einen Aufruf durch, wenn ein command-Hook nicht
startet (Exit 127) oder in seine Zeitgrenze laeuft; nur Exit 2 sperrt. Der Hook-Befehl in
`scripts/dev/runner-settings.json` prueft deshalb, dass der Waechter lesbar ist, ruft ihn mit
`timeout -k 2 10` auf und macht aus jedem Fehler Exit 2 (Feld `timeout` 15 s); der Waechter selbst endet
immer mit 0 und traegt seine Entscheidung im JSON. Ein Fehler **im** Waechter (kein `python3`, eine
Ausnahme im Parser) laesst ihn dagegen weiter ohne Entscheidung enden (offen, R-0166). Interaktiv
bleibt der Hook, wie er ist. Die tragende
Grenze ist auch hier die Deny-Liste, der Hook ist die zweite Schicht:

```bash
bash scripts/dev/harness.sh status   # Marker, AH_AUTONOMOUS, Hook-Registrierung, pre-commit
bash scripts/dev/harness.sh off      # Kill-Switch: der Waechter warnt nur noch
bash scripts/dev/harness.sh on       # wieder scharf
```

Der Deny fuer Harness-Pfade greift **nur** im autonomen Lauf (`AH_AUTONOMOUS=1`) und nur
ohne den Marker `.vm/harness.off` (gitignored, kann also nicht in einen Commit reisen).
Interaktiv warnt der Hook bloss — und diese Warnung sieht man nur mit
`claude --debug`, weil Claude Code bei Exit 0 ausschliesslich das JSON auf stdout
liest. Ein Ledger, das den Harness selbst umbaut, ist der Fall fuer `harness.sh off`.
Der Hook kostet einen `python3`-Start je Tool-Aufruf (auf der Dev-Box ~60 ms) und
laeuft auch in Kevins interaktiven Sessions.

Zwei Regeln gelten dagegen **in jedem Modus** — interaktiv, im Auto-Modus, in Subagenten,
im Runner — und der Kill-Switch hebt sie nicht auf (Kevin, 2026-09-27):

- **Kein Loeschen per Glob in einem geteilten Temp-Verzeichnis** (R-0098). Geteilt sind
  `/tmp`, `/var/tmp`, `/dev/shm`, `$TMPDIR` und die Verzeichnisse von Claude Code darin:
  `/tmp/claude-<uid>`, `…/<projekt>` (der kodierte Pfad mit fuehrendem `-`) und
  `…/<projekt>/<session>` (eine UUID; dort liegen `tasks/` und `scratchpad/` aller Subagenten
  einer Session), dazu die beiden, die Claude Code je uid fuer alle Sessions fuehrt
  (`bash-edit-diff/`, `bundled-skills/`). Ein anderer Eintrag dort
  (`/tmp/claude-<uid>/tmp.XXXX`, eine Datei) ist jemandes eigener. Verweigert werden `rm`,
  `rmdir`, `unlink` und `shred` mit einem Glob, dessen woertliches Verzeichnis (nach `cd`
  aufgeloest) ein solches Verzeichnis **ist** (`/tmp/tmp.*`, `cd /tmp && rm -rf tmp.*`, auch
  `/tmp*` und ein geteiltes Verzeichnis selbst), `find` mit so einem Startpfad samt `-delete`
  bzw. `-exec rm`, eine Schleife ueber so einen Glob, in deren Rumpf geloescht wird (`for d in
  /tmp/tmp.*; do …`, `… | while read d; do …`, auch ueber `cd "$d"` oder `bash -c`), und `… |
  xargs rm` hinter einem Lister (`ls`, `echo`, `printf`, `find`) oder hinter einer solchen
  Schleife. Ein Glob **ueber** der Wurzel zaehlt in jeder Tiefe (`/t*/claude-1000/*`,
  `cd /t* && rm -rf claude-1000/*`, R-0109). Frei bleibt ein Glob, der erst eine Ebene
  tiefer beginnt, also im eigenen Verzeichnis (`…/scratchpad/x/*`, ein `mktemp`-Verzeichnis
  `/tmp/foo.XXXX/*`), dazu Pfade hinter einer Variablen (`rm -rf "$W"/*` — der Hook kann sie
  nicht aufloesen), Globs im eigenen Checkout und derselbe Text in einer Commit-Message oder
  einem Here-Doc. Die Grenze ist gemessen:
  „irgendwo unter `/tmp`" traf in 34 513 echten Befehlen 13 legitime Aufraeumer in
  Scratchpads. Erkannt werden auch ein Operand nach `--`
  (`cd /tmp/claude-<uid> && rm -rf -- -home-x*`), `|&` als Pipe,
  `for d in $(ls -d /tmp/tmp.*); do …`, `… | xargs sh -c 'rm …'` und `grep -l`/`-L` als Lister
  (R-0109), dazu `[^x]` wie `[!x]`, Klammer-Listen (`/{tmp,x}/tmp.*`, auch verschachtelt) und ein
  woertlicher Operand nach `cd` in einen Glob (`cd /t* && rm -rf claude-1000`, R-0125). Nicht
  erfasst: Loeschen aus python heraus, `find … -exec sh -c 'rm …'`, eine
  Schleife, die ihre Liste per Prozess-Substitution oder `mapfile`/`readarray` bekommt
  (`done < <(ls …)`), eine Liste ohne Glob mit einem erst zur Laufzeit gebauten Pfad
  (`ls /tmp | while read d; do rm -rf /tmp/$d`), eine Liste, die ohne xargs in eine Shell geht
  (`… | sh -c 'xargs rm'`), `cat … | xargs rm` (Dateiinhalt statt Namen), Klammer-Sequenzen
  (`{1..3}`), eine Variable in einer Klammer-Liste (`/{$X,y}/…`) und die Expansionen nach der
  32. einer Klammer-Liste. Die Regel dazu
  fuer jede Session: Temp-Verzeichnisse nur mit `mktemp -d -p <eigenes Verzeichnis>`,
  geloescht wird nur der eigene Pfad, nie per Glob.
- **Keine Umgehung des pre-commit-Hooks** (R-0102). Verweigert werden
  `git commit --no-verify` und `-n` (auch in `-qn`), `git am -n` und `--no-verify` (fuer <!-- review: ok nennt die verweigerte Umgehung -->
  `git am` laeuft nur `pre-applypatch`), `git -c core.hooksPath=…` (auch ueber
  `GIT_CONFIG_*`) und `git config … core.hooksPath`, ausser lesend (`--get`), ebenso das
  Entfernen der ganzen `core`-Sektion. Kevins eigene Shell bleibt frei: der Hook sieht nur,
  was das Modell ausfuehrt. Nicht erfasst: ein git-Alias auf `commit -n` oder `am -n`, ein direktes
  Schreiben von `.git/config` (Edit, `sed -i`, `>>`), ein `core.hooksPath` ueber
  `include.path`, `git config --edit`, `eval` oder eine Kommando-Substitution und Plumbing
  (`commit-tree`, `update-ref`). `chmod -x` auf einen Hook zaehlt seit R-0110 als Schreiben
  eines Harness-Pfads wie `sed -i` (ebenso `chown`, `chgrp`): im autonomen Lauf verweigert,
  interaktiv gewarnt.

**pre-commit-Hook.** `scripts/dev/hooks/pre-commit` faehrt vor jedem Commit
`review.sh sec --staged` — bis dahin lief die Sperre fuer privaten Plan, SEC-Ledger,
`sec:`-Dedup-Keys, `.devenv.sh` und `settings.local.json` nur in `task-close.sh`, der
Plan-Commit am Gate und jeder Commit von Hand blieben mechanisch ungeprueft. Seit R-0183 sperrt `sec`
auch eine hinzugefuegte Zeile mit einem Token-Muster — ein Proxmox-API-Token
(`USER@REALM!TOKENID=UUID`, ebenso die PBS-Form mit `:` statt `=`, die URL-kodierte Form mit `%40`, `%21`,
`%3D` und ein Secret allein hinter einem Schluesselnamen wie `api_token_secret` oder `PVE_TOKEN_SECRET`;
ein nacktes UUID ohne solchen Namen bleibt erlaubt, R-0196), ein GitHub-Token (`ghp_`, `gho_`, `ghu_`,
`ghs_`, `ghr_`, `github_pat_`) oder ein `sk-ant-`-Schluessel, je mit einer Mindestlaenge, die Platzhalter durchlaesst (ebenso ein
Rumpf aus hoechstens zwei verschiedenen Zeichen wie `xxxx…`) — und nennt dabei nur Datei:Zeile; ueber
eine Spanne (`--range`: pre-push und CI) liest es auch die Nachricht jedes Commits und nennt dann nur
den Commit. Schon beim Commit liest der Hook `scripts/dev/hooks/commit-msg` die Nachricht
(`review.sh sec --message <datei>`, R-0197): ein Token darin bricht den Commit ab, gemeldet wird nur
die Zeile; bei `commit -v` zaehlt alles unter der Schnittlinie nicht. Ein Test, der ein solches
Muster braucht, setzt es zur Laufzeit zusammen. Was an den lokalen
Hooks vorbeigeht (ein Klon ohne `core.hooksPath`, ein Edit im Web-UI, ein anderer Rechner), faengt
der CI-Job „Public repo guard (review.sh sec)": er faehrt `review.sh sec --range` ueber jeden Commit
eines Pull Requests bzw. Pushs (R-0123; ein Commit, der eine private Datei bringt und der naechste,
der sie wieder loescht, zaehlen beide, denn die Historie wird mit veroeffentlicht). Der Job prueft
zweimal, mit dem `review.sh` der Basis (ein Worktree von `origin/<base>`, beim Push der Stand vor
ihm) und mit dem des geaenderten Stands; beide muessen gruen sein (R-0174) — ein Pull Request,
der `sec` aendert, wird mit der Logik geprueft, die vor ihm galt. Einen Fehlalarm der Basis-Logik
raeumt ein Pull Request deshalb nicht an ihr vorbei aus, der geht per Admin-Merge. Scharf wird
der Hook je Klon mit einem Handgriff Kevins:

```bash
git config core.hooksPath scripts/dev/hooks   # einmal im Haupt-Checkout; die Lanes erben es
bash scripts/dev/harness.sh status            # pre-commit: armed (core.hooksPath=scripts/dev/hooks)
```

Der Pfad ist relativ: jeder Worktree faehrt die Hooks **seines** Branches, ein Branch ohne
die Dateien hat keine (und dessen aelteres `harness.sh` sagt dazu nichts). Seit R-0110 liegen
dort vier Hooks, alle mit demselben `review.sh sec --staged`: `pre-commit` fuer `git commit`,
`prepare-commit-msg` fuer `git cherry-pick`, `git revert`, jeden Commit, den ein `rebase`
mit dem Standard-Backend nachspielt, und den Merge-Commit, `pre-merge-commit` fuer
`git merge` mit eigenem Commit (githooks(5): bricht ab, bevor der Commit entsteht) und
`pre-applypatch` fuer `git am` und `git rebase --apply` (auch ueber `rebase.backend=apply`),
die keinen der drei anderen rufen. Dass der Sequencer `prepare-commit-msg`
ruft, dokumentiert git nicht; gemessen ist es mit git 2.47.3, und
`scripts/tests/review_scripts_test.sh` haelt es fest — ein git, das damit aufhoert, macht
diese Faelle rot. `git commit -n` ueberspringt nur `pre-commit`, nicht `prepare-commit-msg`;
ein gewoehnlicher Commit faehrt `sec` deshalb zweimal (~20 ms je Lauf). Seit R-0123 kommt ein
fuenfter dazu: `pre-push` faehrt `review.sh sec --range` ueber jeden Commit, den ein Push nach
draussen bringt — je Ref vom Stand des Remotes bis zum lokalen Commit (eine neue Ref: die ganze
Historie), und nur die Commits, die der Remote noch nicht hat (`--not-on <remote>`; ein Branch, der
main gemergt hat, bringt main nicht als Fund mit). Ein Treffer bricht den Push ab und nennt Pfad bzw.
Datei:Zeile mit dem Commit, nie den Inhalt; eine Loeschung pusht nichts und geht durch. Erst dieser
Hook verhindert, dass etwas ueberhaupt oeffentlich wird; die CI faengt, was an ihm vorbeigeht.
Seit R-0197 ist `commit-msg` der sechste: er faehrt `review.sh sec --message` ueber die Nachricht
eines `git commit` und eines Merge-Commits von `git merge` — nur die rufen ihn (githooks(5)); die
Nachrichten von `git cherry-pick`, `git revert`, einem `rebase` und `git am` prueft erst `pre-push`
bzw. die CI. `git commit -n` ueberspringt ihn wie `pre-commit`.
Fehlt einer der sechs im Checkout oder ist er nicht ausfuehrbar, meldet `harness.sh status`
`NOT armed` und nennt ihn. Nach einer Weigerung geht es mit `--abort` zurueck (`git cherry-pick`, `merge`, `rebase`,
`am`, `git revert` einer Serie); ein verweigertes `git revert` eines einzelnen Commits
hinterlaesst dagegen keinen `REVERT_HEAD` und seine Aenderung gestaged, dort hilft
`git reset --merge`. Die Hooks sperren
fail-closed — ein kaputtes `review.sh` blockiert jeden Commit, jeden Merge, cherry-pick,
rebase, `git am` und jeden Push; der Ausweg in Kevins Shell ist `git config --unset core.hooksPath`.
Nicht abgedeckt: ein Fast-Forward-Merge (er erzeugt keinen Commit), Plumbing (`commit-tree`,
`update-ref`) und die Wege am Hook vorbei, die der Waechter nicht sieht (oben). Eine Runner-Regel `Edit(./.git/**)` gibt es bewusst nicht: unter
`dontAsk` ohne passende Allow-Regel wird so ein Edit schon heute verweigert, und die
Bash-Schreibwege deckt eine Edit-Regel nicht ab.

### Runner-User `adminhelper-runner`

Der Unix-User, unter dem autonome Laeufe arbeiten. Er existiert, damit ein Lauf
nicht mit Kevins ssh-Schluesseln, seinem `gh`-Login und seinen Bypass-Rechten
faehrt. Anlegen (einmalig, als root):

```bash
bash scripts/dev/runner-setup.sh --dry-run        # zeigt den Plan, aendert nichts (kein root noetig)
sudo bash scripts/dev/runner-setup.sh             # legt User, Klon, DB, Venv, Settings an
```

Das Skript ist idempotent: ein zweiter Lauf laesst gefuellte Token-Dateien in Ruhe
und haelt DB-Passwort und `~/.devenv.sh` zusammen. `--remove --yes` nimmt User,
Klon und Datenbank wieder weg. Im Klon setzt es als Runner `core.hooksPath
scripts/dev/hooks`, damit der pre-commit-Hook auch dort vor jedem Commit
`review.sh sec` faehrt (R-0102); ein Klon von vorher bekommt es mit einem erneuten
`sudo bash scripts/dev/runner-setup.sh`. Geklont wird nur in einen Pfad, den es noch nicht
gibt: steht unter `/srv/ah/repo` schon etwas ohne `.git`, bricht das Skript mit einem Satz ab,
statt hineinzuklonen; sonst klont es in ein Temp-Verzeichnis in `/srv` (neben `/srv/ah`) und
benennt danach mit einem einzigen rename um (`mv --no-copy -T`): `/srv` muss root gehoeren und
darf fuer Gruppe und andere nicht schreibbar sein; liegt `/srv/ah` auf einem anderen Dateisystem
oder Mount, bricht es ab, statt zu kopieren. Ausserdem legt es die geteilte Python-Sperre
`/var/lib/adminhelper-dev/py.lock` an (root, `0666`, im Verzeichnis `0755` von root; Abschnitt
„Die schweren Python-Schritte laufen nacheinander"), `--remove --yes` nimmt sie mit; ein
bestehender Runner bekommt sie mit einem erneuten `sudo bash scripts/dev/runner-setup.sh`.
Ebenso installiert es das Red Team root-eigen (R-0152): `runner-redteam.sh`, `runner-env.sh`,
`runner-settings.json` und `runner-claude.version` aus dem Checkout, aus dem es laeuft, nach
`/usr/local/lib/adminhelper-dev/` (root, Verzeichnis und Skript `0755`, der Rest `0644`), dazu den
Harness-Waechter `scripts/dev/hooks/harness-guard.sh` als `harness-guard.sh` (`0755`, R-0164): der
Hook in den Runner-Settings ruft diese Kopie auf, nicht die im Klon, die der Runner aendern kann. Es
haelt die sha256 der Runner-CLI in `/var/lib/adminhelper-dev/runner-claude.sha256` fest
(`0644`); `--remove --yes` nimmt beides mit.
Danach bleiben **drei Handgriffe** fuer Kevin, die der Runner nicht selbst tun kann:

1. `sudo -iu adminhelper-runner env DISABLE_AUTOUPDATER=1 claude setup-token` → Token nach
   `~adminhelper-runner/.config/adminhelper/oauth.env` (Abo-Token, kein API-Key:
   `ANTHROPIC_API_KEY` haette Vorrang und wuerde ueber ein API-Konto abrechnen).
2. `pveum user token add adminhelper-runner@pve run --privsep 1` plus dieselben vier
   ACL-Pfade der Rolle `AdminHelperVM`, die Kevins eigener Token hat (Abschnitt
   „VMs mit vm.py") → Werte nach `~adminhelper-runner/.config/adminhelper/pve.env`.
3. `sudo -u adminhelper-runner git -C /srv/ah/repo pull --ff-only`, dann der
   Red-Team-Lauf (unten). Das Red Team laeuft nicht aus diesem Klon, sondern aus seiner
   root-eigenen Kopie; der Klon ist nur das Ziel seiner Proben.

**`-iu`, nicht `-u`, bei allem, was die CLI des Runners braucht:** ohne `-i` behaelt
sudo den PATH des Aufrufers, und die CLI in `~adminhelper-runner/.local/bin` ist dann
unsichtbar (`sudo: claude: Befehl nicht gefunden`, 2026-09-22 verifiziert).

**Modell, Effort und CLI-Version sind festgenagelt, nicht geerbt.** Ein unbeaufsichtigter Lauf
darf nicht davon abhaengen, was die CLI gerade als Standard mitbringt:

- **Modell:** `scripts/dev/runner-settings.json` nennt `claude-opus-5-5[1m]` — eine volle
  Kennung, **kein** Alias. Ein Alias wie `opus[1m]` zeigt immer auf das neueste Modell und
  wechselte beim naechsten Release ohne Review; fuer interaktive Sessions ist das richtig,
  fuer den Runner nicht.
- **Effort:** `xhigh`. Wirksam ist der Eintrag unter `modelSettings.claude-opus-5-5`
  (`effortLevel`, so wie `/effort` ihn schreibt): ein `effortLevel` oben in den
  User-Settings zaehlt laut Claude-Code-Doku fuer Opus 5.5 **nicht** mehr, nur noch fuer
  aeltere Modelle — es bleibt stehen, damit ein Rueckfall auf ein aelteres Modell nicht
  auf dessen Standard faellt. Opus 5.5 hat von sich aus `medium`.
- **Nichts darf das ueberstimmen:** `ANTHROPIC_MODEL` und `CLAUDE_CODE_EFFORT_LEVEL`
  haben Vorrang vor den Settings; `runner-env.sh` leert beide, wie schon den API-Key.
- **CLI-Version:** steht in **einer** Datei, `scripts/dev/runner-claude.version`.
  `runner-setup.sh` installiert genau diese Fassung (`claude install <version>`),
  `runner-env.sh` schaltet den Auto-Updater ab (`DISABLE_AUTOUPDATER`) — bewusst nicht die
  Settings-Datei: die ist oeffentlich und traegt Regeln, nie einen `env`-Block. Aeltere Fassungen kennen neuere
  Modelle nicht: das Binary von 2.1.278 enthaelt `claude-opus-5-5` nicht in seinem Katalog.
  Hat der Runner noch gar keine CLI, installiert der offizielle Installer genau diese
  Fassung (aus dem Repo-Root:
  `sudo -iu adminhelper-runner bash -c "curl -fsSL https://claude.ai/install.sh | bash -s $(cat scripts/dev/runner-claude.version)"`),
  danach `runner-setup.sh` erneut. Ein Handgriff als Runner ohne `runner-env.sh` setzt den
  Schalter selbst (`env DISABLE_AUTOUPDATER=1`, wie bei `setup-token`); wandert die Version
  trotzdem, meldet das Red Team es, und `runner-setup.sh` setzt sie zurueck.

**Das Red Team liest zurueck, was wirklich lief.** Aus dem `system/init`-Ereignis einer
Modellprobe nimmt es das tatsaechliche Modell und die tatsaechliche CLI-Version, aus
`result.modelUsage` das Modell, das wirklich geantwortet hat, und vergleicht alles mit dem
Soll, das `runner-setup.sh` neben das Red Team installiert hat — nicht mit dem Klon, den der
Runner aendern kann. Die CLI selbst gehoert dem Runner; dass sie die installierte ist, belegt
ihre sha256 gegen die festgehaltene (`runner-redteam.sh --claude-sum <datei> <claude>`).
Abweichung, fehlendes Ereignis, eine Probe ohne Ergebnis oder eine
fehlende CLI ist ein `FAIL`, kein Hinweis — ein Messgeraet, das nichts misst, darf nicht
wie ein Ergebnis aussehen. Den Effort liest es **nicht** zurueck: kein Ereignis des
Protokolls traegt ihn; ihn sichern die Settings und das Leeren von
`CLAUDE_CODE_EFFORT_LEVEL`.

**Anheben** ist ein bewusster Schritt, kein Nebeneffekt. Das Soll steht im Repo;
`runner-setup.sh` liest es aus dem Checkout, aus dem es laeuft, und installiert es mit dem
Red Team. Nach jedem CLI- oder Modellwechsel laeuft deshalb zuerst `runner-setup.sh`: sonst
misst das Red Team gegen das alte Soll, und die Pruefsumme der neuen CLI meldet es als `FAIL`:

```
# 1. auf einem Branch: neue Version eintragen und pruefen, dass sie das Modell kennt
echo 2.1.XXX > scripts/dev/runner-claude.version
# 2. bei einem Modellwechsel: model und modelSettings in scripts/dev/runner-settings.json
# 3. PR, Merge; dann aus einem Checkout auf dem neuen main einrichten und beweisen
sudo bash scripts/dev/runner-setup.sh
sudo -u adminhelper-runner git -C /srv/ah/repo pull --ff-only
sudo -u adminhelper-runner bash /usr/local/lib/adminhelper-dev/runner-redteam.sh
```

**Getrusteter Workspace — bewusst abgeschaltet.** Claude Code ignoriert die
Allow-Liste eines Projekts, solange der Workspace nicht getrustet ist, und sagt das
auch: „Ignoring 38 permissions.allow entries … this workspace has not been trusted".
Die Richtung ist fail-safe (die **Deny**-Liste gilt weiter), deshalb setzt
`runner-setup.sh` das Flag nur auf ausdrueckliche Anforderung:

```
sudo bash scripts/dev/runner-setup.sh --trust
```

Das schreibt `projects["/srv/ah/repo"].hasTrustDialogAccepted` in
`~adminhelper-runner/.claude.json`. Die Meldung von 2026-09-22 nennt die Allow-Liste aus
`.claude/settings.json` des Projekts; ob die Allow-Liste der Runner-Settings ohne Trust gilt, ist
**nicht verifiziert**. Der Worker (Stufe 7a) laedt die Projekt-Settings gar nicht
(`--setting-sources user`) und arbeitet in den Lanes `/srv/ah/AdminHelper-<slug>`, die `--trust` nicht
abdeckt (es trustet nur `/srv/ah/repo`); ob er den Trust braucht, misst der Pilot (Abschnitt „Der
Worker"). Solange jeder Lauf von Hand gestartet wird, ist der engere Zustand der bessere.

Beide Dateien muessen regulaere `0600`-Dateien in einem Verzeichnis sein, in das
nur der Runner schreiben darf; `scripts/dev/runner-env.sh` (zum **Sourcen**)
prueft das und gibt sonst einen Fehler zurueck (`return 1`, die Shell lebt weiter).
`oauth.env` ist Pflicht, `pve.env` optional — ohne Hypervisor-Token laufen die
Python- und Shell-Suiten trotzdem, nur keine VM. Es leert ausserdem die geerbten Credentials, die auf dieser Box
ueberhaupt vorkommen — `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, ein fremdes
`CLAUDE_CODE_OAUTH_TOKEN`, alle `AH_PVE_*` (`vm.py` laesst die Umgebung ueber seine
Konfiguration gewinnen), `GH_TOKEN`/`GITHUB_TOKEN`, `SSH_AUTH_SOCK` (ein Agent-Socket ist ein
Schluessel ohne Schluesseldatei), `DATABASE_URL` sowie **alle** `PG*` und `AWS_*` (als Wildcard, nicht als Handliste — `PGPORT` lenkt eine Verbindung so gut um wie `PGHOST`) — und setzt
`AH_AUTONOMOUS=1` und `AH_VM_MAX=8`. Die Unsets stehen **vor** allem, was scheitern kann: die
Datei wird gesourct, ihr Rueckgabewert meist ignoriert. `DATABASE_URL` ist dabei der scharfe
Fall: `run.sh` bevorzugt sie gegenueber `AH_TEST_DB`, und die Server-Suite legt darauf Tabellen
an und **loescht sie wieder** — ein geerbter Wert waere ein Drop in einer fremden Datenbank.

**Was die Runner-Settings** (`scripts/dev/runner-settings.json` →
`~adminhelper-runner/.claude/settings.json`) **verbieten und warum:**

| Deny-Regel | Grund |
|---|---|
| `git add`, `git commit`, `git push`, `git switch`, `git branch`, `git revert`, `git checkout`, `git restore`, `git stash` | Der Runner schreibt keine Historie. `revert`/`branch`/`switch` stehen mit drin, weil sie committen bzw. ungestagte Arbeit verwerfen koennen — und weil die Projekt-`settings.json` des Klons sie sonst mitbringt (Listen mergen ueber die Ebenen). |
| `gh:*`, `sudo:*` | Kein GitHub-Zugang, keine Rechteerhoehung. |
| `vm.py bake`, `bake.sh`, `heavy.sh`, `multibox.sh`, `run.sh all/e2e/integration` | Teure oder VM-fressende Laeufe startet ein Mensch. `vm.py` ist Verb fuer Verb freigegeben, damit kein breites Praefix `bake` mit abdeckt. |
| `task-close.sh`, `ledger.sh mark-done` | Die Bau-Session schliesst keine Task. Seit Stufe 7a tut das der Worker (`ledger-loop.sh`) ausserhalb der Session mit `task-close.sh --review auto`; die Session hinterlaesst nur eine Commit-Nachricht. |
| `Edit(./tasks/**)`, `git grep` | Stufe 7a (R-0108): ein Ledger aendert die Bau-Session nur ueber `ledger.sh` (`start`, `mark-skip`, `mark-question`, `set-files`, alle erlaubt); den Haken setzt `task-close.sh`. `git grep` kann mit `-O` ein Programm starten. |
| `Edit(./.claude/**)`, `Edit(~/.claude/**)`, `CLAUDE.md`, `AUTONOMOUS.md`, `scripts/dev/**`, `run.sh`, `heavy.sh`, `vm.py` | Der Harness ist nicht sein Arbeitsmaterial. `~/.claude` steht mit drin, weil Claude Code Settings **live** nachlaedt. |
| `Edit(./tasks/private/**)`, `Read(~/.config/adminhelper/**)` | Privates Repo und die eigenen Token-Dateien. Der `Read`-Deny ist Hygiene, **keine Grenze**: die Token stehen nach `runner-env.sh` ohnehin in der Prozess-Umgebung des Runners, und ein erlaubtes `cat` liest die Datei am `Read`-Tool vorbei. Was wirklich schuetzt, ist `0600` plus die Tatsache, dass es seine **eigenen** Token sind (Pool-gescopt, eigenes Abo). |
| `Edit(//srv/ah/**/…)` (dieselben Harness-Pfade absolut) | Eine `./`-Regel loest gegen das **Arbeitsverzeichnis** der Session auf: startet ein Lauf in einem Unterverzeichnis des Klons, meint `Edit(./CLAUDE.md)` eine ganz andere Datei. Die absoluten Zwillinge halten ueberall. |

**Was die Regeln nicht koennen** — ehrlich, weil es den Beweis veraendert: der
Runner darf `Edit(./scripts/**)` (ausser den gesperrten Pfaden) und `bash
scripts/tests/run.sh quick` — wer eine Testdatei aendert und sie dann startet,
fuehrt eigenen Code aus. Die gefaehrlichste Form davon ist zu: `scripts/vm/**`
(die Wrapper laufen mit dem Hypervisor-Token) und `scripts/tests/multibox.sh`
stehen im Deny **und** auf den Harness-Pfaden; was bleibt, sind die uebrigen
Test-Dateien, die keinen Token in der Hand haben. Ein Ledger kann die Bau-Session seit Stufe 7a nicht
mehr direkt editieren (`Edit(./tasks/**)` steht im Deny), wohl aber der Code, den sie ueber
`verify.sh` startet; was der hinter dem Worker aendert, erkennt der Worker erst danach (Abschnitt
„Der Worker"). Einen Scratch-Ordner gibt es nur ueber `bash scripts/dev/scratch.sh new|rm` (kein
`mktemp`, kein `rm` in der Allow-Liste). **Die tragende Grenze ist
deshalb nicht die Regel-Liste, sondern die Betriebssystem-Ebene:** kein
`~/.ssh`, kein `gh`-Login, leeres `GH_TOKEN`, `remote.origin.pushurl=/dev/null`,
eigene DB, eigener Proxmox-Token nur fuer den Pool.

**Red Team.** Der Beweis, dass das haelt, ist ein Lauf als dieser User:

```bash
sudo -u adminhelper-runner bash /usr/local/lib/adminhelper-dev/runner-redteam.sh
```

Das Messgeraet liegt ausserhalb dessen, was der gepruefte Nutzer schreiben kann: die
root-eigene Kopie, die `runner-setup.sh` installiert. Es startet sich einmal unter `env -i` mit
festem `PATH` neu, sourct keine Datei des Runners (`runner-env.sh` laesst dort `~/.devenv.sh`
aus) und bricht ab, wenn `runner-env.sh` seine Funktionen, Zaehler oder seinen `PATH`
veraendert. Laeuft es von woanders, etwa aus dem Klon, ist das ein `FAIL`, der den richtigen
Aufruf nennt, und der Lauf endet dort.

Jede Probe druckt `ok`, `FAIL` oder `info`; die letzte Zeile ist `N ok, M FAIL`.
Geprueft werden: Lesen fremder Schluessel und Settings, `git push` nach origin,
`gh`-Login, D-Bus/Keyring, der eigene Proxmox-Token gegen eine VM **ausserhalb**
des Pools, und `claude -p`-Laeufe, die ausdruecklich nach einem verbotenen Griff fragen
(erwartet: `permission_denials`): ein harmloses `git stash list`, ein `git push`, eine
`CLAUDE.md`-Aenderung und, gestartet wie die Bau-Session des Workers (`--setting-sources user`),
ein Ledger per Umleitung und ein nacktes `mktemp -d` (Stufe 7a). Ohne Modell prueft
`--build-settings`, dass die Settings den Deny auf `tasks/` und die zwei Allows fuer `scratch.sh`
wortgleich tragen.
Die Proben auf git, Proxmox, D-Bus und Settings fuehren keinen Code und keine ausfuehrbare
Konfiguration des Runners aus (R-0156, R-0160 bis R-0163); die Modellproben starten bewusst die
CLI des Runners, nachdem Pruefsumme und Settings geprueft sind — ein FAIL dort haelt sie nicht auf
(ihr Verhindern regelt Stufe 7a).
Die Push-Proben pushen aus einem eigenen Repository ohne Hooks, ohne git-Konfiguration
des Nutzers und ohne Credential-Helper an die URLs, die der Klon nennt, und lesen seine
Konfiguration auf Helper, Extra-Header und URL-Umschreibungen (nur Namen, URLs geschwaerzt); ob eine
Modellprobe den Klon geaendert hat, zeigt die ctime seiner Dateien, nicht `git status`. Der
Proxmox-Token wird direkt an der API gemessen (`curl -q` ohne die curlrc des Nutzers, Token ueber
stdin): `GET /pools?poolid=<pool>` muss den Pool zeigen, der Status einer VM ausserhalb des Pools
muss abgelehnt werden. Das Ziel (URL, Node, Pool, CA) liest das Red Team aus `pve-target.env`, die
`runner-setup.sh` root-eigen neben das Red Team schreibt (aus der Umgebung des Aufrufs, sonst aus
`.claude/settings.local.json` des Checkouts, ohne Token; die CA als Kopie) — ohne sie meldet Probe 4
`info`. Die D-Bus-Probe sucht den Socket in `/run/user/<uid>` und fragt ihn mit gesetztem
`XDG_RUNTIME_DIR`; das Runtime-Verzeichnis des Besitzers darf der Runner nicht betreten.
`~/.claude/settings.json` des Runners muss byte-genau der geprueften `runner-settings.json`
entsprechen; Claude Code schreibt diese Datei selbst, wenn in einer Session `/config` oder `/model`
eine Wahl speichert (Claude-Code-Doku, Settings), dann hilft ein erneutes `runner-setup.sh`. Ein
unbekanntes Argument endet mit Exit 2, bevor eine Probe laeuft; viele Proben gibt es einzeln als
Schritt ohne den Neustart (die Liste nennt die Meldung bei einem unbekannten Argument) — `--pve` und
`--git` (zu jeder nicht-lokalen Push-URL des Klons und zu einer angegebenen URL) gehen dabei ins
Netz. Dazu die
geteilte Python-Sperre `/var/lib/adminhelper-dev/py.lock`: sie existiert, Datei und
Verzeichnis gehoeren root, der Runner darf das Verzeichnis nicht schreiben und kann die
Sperre nehmen (ist sie gerade belegt, ein `info`); einzeln mit
`runner-redteam.sh --py-lock <absoluter-pfad>`. Und die Runner-CLI gegen ihre festgehaltene
sha256 (`--claude-sum`).
Stufe 4 gilt erst mit `0 FAIL` als abgeschlossen; das Ergebnis gehoert in den
Anhang von `tasks/harness-stufe-4.md`.

### Der Worker: `ledger-loop.sh` (Stufe 7a)

Der Worker baut freigegebene Ledger als `adminhelper-runner` (Ablauf, Deckel und Stopp-Klassen:
`AUTONOMOUS.md`, „Der Worker"). Vor dem ersten Start und nach **jeder** Aenderung an
`scripts/dev/runner-settings.json`, an `scripts/dev/hooks/harness-guard.sh` (der Runner ruft die
root-eigene Kopie, die nur `runner-setup.sh` erneuert), am Red Team oder an
`scripts/dev/runner-claude.version` laufen die drei Handgriffe von oben: `sudo bash scripts/dev/runner-setup.sh`, `sudo -u adminhelper-runner
git -C /srv/ah/repo pull --ff-only`, das Red Team als Runner. Der Worker selbst zieht einen `main`
mit geaenderten Harness-Pfaden nicht nach, sondern endet mit `stop: infra (Harness auf main
geaendert — Pull + Red Team durch Kevin)`. Dazu muss das Token des Runners gelten:

```bash
sudo -u adminhelper-runner bash -lc '. /srv/ah/repo/scripts/dev/runner-env.sh && claude auth status'
```

**Getrusteter Workspace — nicht verifiziert.** Ob die Bau-Session in einer Lane die Allow-Liste der
Runner-Settings ohne Trust anwendet, hat noch niemand gemessen (oben, „Getrusteter Workspace").
Endet im Pilot jede Task als `[?] stall` oder mit vielen Verweigerungen im Summary, und steht in
`/srv/ah/loop/<slug>/<id>.s<n>.err` (oder `.json`) eine Meldung „Ignoring … permissions.allow
entries", greift der Trust: das entscheidet dann Kevin (die Aufsicht legt es ihm vor), denn `--trust` deckt die Lanes
nicht ab.

**Starten** (nur Kevin, in tmux; die Ledger in seiner Reihenfolge, die Flags mit ihren Defaults):

```bash
sudo -u adminhelper-runner tmux new -d -s ah-loop \
  'cd /srv/ah/repo && bash scripts/dev/ledger-loop.sh --ledger tasks/<a>.md --max-hours 8 --max-budget-usd 200'
```

**Stand lesen** aus dem eigenen Checkout, nie mit einem Skript des Runners:

```bash
bash scripts/dev/ledger-loop.sh status --state /srv/ah/loop/state.json
```

Die erste Zeile ist die Worker-Zeile des AH-STATUS (`AH_LOOP_STATE` zeigt dem Hook eine andere
Datei), danach Stopp-Grund, Ledger und die letzten Zeilen des neuesten `summary-<datum>.md`. Je
Ledger liegen unter `/srv/ah/loop/<slug>/` die Session-Ausgaben (`<id>.s<n>.json`), die Close-Logs,
`<id>.aborted.diff` (was der Loop zuruecknahm, jedes Aufraeumen angehaengt mit Zeitstempel) und bei
`bereit` `pr-body.md`.

**Bundle holen**, wenn ein Ledger `bereit` ist — in Kevins Checkout, kein `git` im Repo des Runners.
Das Bundle setzt das `origin/main` voraus, auf dem der Runner es schnitt; deshalb zuerst `origin`:

```bash
git fetch origin
git fetch /srv/ah/loop/<slug>.bundle feature/<slug>:feature/<slug>
```

Push und Draft-PR sind danach Kevins bzw. der Aufsicht Handgriff (Text aus
`/srv/ah/loop/<slug>/pr-body.md`).

**Recovery:**

- **`[?]` und `blockiert`:** die Frage steht im `[?]` der Task, im Ledger der Lane
  (`/srv/ah/AdminHelper-<slug>`) und im Summary; der Loop baut das Ledger nicht weiter, bis Kevin
  entscheidet. Die Ledger-Commits des Loops liegen nur in der Lane, gepusht wird nichts. Einen Befehl,
  der ein beantwortetes Ledger in der Lane wieder auf `aktiv` setzt, gibt es in 7a nicht: der Loop baut
  eine bestehende Lane nur weiter, wenn sie sauber ist und ihr Ledger `freigegeben` oder `aktiv` traegt,
  und nimmt dort die erste Task mit `[ ]` (eine `[?]`-Task bleibt liegen); bis dahin ist das Kevins
  Handgriff als Runner.
- **`blockiert (Lane schmutzig)`:** die Lane traegt Aenderungen, die der Loop nicht committet hat.
  Der Loop raeumt sie nicht weg (kein `stash`, kein `clean`); ansehen mit
  `sudo -u adminhelper-runner git -C /srv/ah/AdminHelper-<slug> status`, entscheiden tut Kevin.
- **`stop: infra`:** der Satz dahinter nennt den Grund (Token, CLI-Pin, Klon nicht sauber, `git`,
  Harness auf `main`, ein API-Fehler oder eine Session ohne JSON); beheben bzw. den Ausfall abwarten,
  dann neu starten. Die offene Task bleibt `[ ]`. Ausnahme: sagt der
  Satz `the claude CLI … is not the one runner-setup.sh recorded`, nachdem schon Sessions liefen, hat
  vermutlich Code einer Session die CLI ersetzt — das ist dasselbe Signal wie `harness-modified`. Die
  Lane bleibt dann, wie die Session sie verliess (`stop: infra` raeumt nicht auf): ansehen, dann Setup
  und Red Team, nicht einfach neu starten.
- **`stop: usage-limit`:** die Reset-Zeit steht in `state.json` und im Summary; danach neu starten,
  die Task ist offen und ihre Lane aufgeraeumt.
- **`stop: harness-modified`:** nicht einfach neu starten. Etwas, das nur Code einer Session tun
  konnte, ist passiert (ein Harness-Pfad, ein Commit in der Lane, der Klon); `aborted.diff` und die
  Lane ansehen, dann Setup und Red Team. Der Loop sperrt das Ledger mit der Datei
  `/srv/ah/loop/<slug>/harness-modified`: erst wenn Kevin sie nach dem Ansehen entfernt, baut ein
  neuer Lauf es wieder.

#### Das Builder-Profil: der Loop unter Kevins Benutzer

Solange der Runner ruht, laeuft der Loop unter Kevins UID mit einem eigenen HOME, dem Builder unter
`~/.cache/ah-builder`: `home/` fuer die Sessions, `repo/` als Klon (die Lanes daneben), `loop/` fuer
den Stand. Einrichten, ohne sudo, einmal und danach nach jeder Aenderung an den Runner-Settings oder an
der Harness auf `main`; die Stopp-Meldung „Harness auf main geaendert … Pull + Red Team durch Kevin“
heisst beim Builder: `setup`. Voraussetzung ist, was `sudo bash scripts/dev/runner-setup.sh`
hinterlegt: die Pruefsumme der CLI (`/var/lib/adminhelper-dev/runner-claude.sha256`), die root-eigene
Kopie des Waechters, die der Hook der Settings ruft (`/usr/local/lib/adminhelper-dev/harness-guard.sh`),
und die geteilte Python-Sperre. Nach einer Aenderung an `runner-claude.version` oder an
`scripts/dev/hooks/harness-guard.sh` deshalb zuerst `runner-setup.sh`, dann `setup`:

```bash
bash scripts/dev/builder-home.sh setup     # idempotent: was schon stimmt, bleibt
bash scripts/dev/builder-home.sh token     # claude setup-token, dann das Token verdeckt einfuegen
bash scripts/dev/builder-home.sh status    # nennt, was fehlt (Exit 1)
```

`setup` legt die Verzeichnisse mit 0700 an, installiert die CLI aus `runner-claude.version` des
Checkouts, in dem `setup` laeuft (vorher auf `main` pullen, wie fuer `runner-setup.sh`), ins
Builder-HOME (mit Abgleich gegen die Pruefsumme, die `runner-setup.sh` schrieb; eine Abweichung ist
nur eine `note`, der Loop endet dann in der Vorpruefung mit `stop: infra`), zieht den Klon auf
`origin/main` vor (`pushurl=/dev/null`, `core.hooksPath`), schreibt die Settings aus der
`runner-settings.json` des Klons, ein Tools-venv (`ruff` wie `runner-setup.sh`, `python3` als Wrapper
auf das venv), eine eigene Test-DB `adminhelper_builder` auf dem Server des Haupt-Checkouts,
`.devenv.sh` (0600) und die Git-Identitaet. `oauth.env` schreibt nur `token`, und nur ein Token der Form
`sk-ant-oat01-…`; der Code, den der Browser unterwegs zeigt, ist keins.

**Starten** (nur Kevin; die Ledger in seiner Reihenfolge, die Deckel wie oben) und **Stand lesen**:

```bash
bash scripts/dev/ledger-loop.sh start --profile kevin --ledger tasks/<a>.md --max-hours 8 --max-budget-usd 200
bash scripts/dev/ledger-loop.sh status --profile kevin
```

`start` prueft `builder-home.sh status`, verweigert neben einer schon laufenden tmux-Session
`ah-builder` und startet darin den Loop des Klons mit `env -i` (nur `HOME`, `PATH`, `LANG`, `USER`,
`LOGNAME`, `TERM`, `AH_LOOP_DIR`: kein SSH-Agent, keine D-Bus-Adresse, kein Proxmox-Token) und
`</dev/null`. Die Ausgabe steht in `~/.cache/ah-builder/loop/builder.log`, der Exit-Code am Ende in
`builder.done` (`rc=<n>`). Was oben unter `/srv/ah/loop` steht (Logs je Ledger, `pr-body.md`, Bundle),
liegt beim Builder unter `~/.cache/ah-builder/loop`, die Lanes neben `~/.cache/ah-builder/repo`.

**Die Sperrregeln und ihre Grenze.** Die Settings des Builders sind die des Runners, die Lane-Regeln
(`//srv/ah/…`) auf das Builder-Verzeichnis umgeschrieben. Dazu kommen absolute Deny-Regeln (`//<pfad>`,
denn `~/` meint in einer Session das Builder-HOME) fuer die privaten Verzeichnisse in Kevins HOME
(`~/.ssh`, `~/.config/gh`, `~/.claude` und `~/.claude.json`, `~/.config/adminhelper`, die Keyrings,
`~/.gnupg`) und fuer `tasks/private` und `.claude/settings.local.json` jedes Checkouts; dazu Deny fuer
die Befehle `ssh` und `docker`. Sie halten die eingebauten Werkzeuge der Session (Read, Edit, Write,
Grep, Glob), die Datei-Befehle, die Claude Code in Bash erkennt (`cat`, `head`, `tail`, `sed`, `tee`),
soweit sie die Datei nennen, und die Ziele von Umleitungen. Sie halten kein Programm, das Dateien
selbst oeffnet — ein Testskript unter `pytest` oder `npm run` ebenso wie einen Befehl, den Claude Code
nicht als Datei-Befehl kennt: die Session laeuft unter Kevins UID, und was ein solches Programm tut,
sieht keine Regel. Dieses Restrisiko hat Kevin hingenommen; eine harte Grenze gaebe erst eine eigene
UID oder die Sandbox der CLI.

**Wartezeit:** `server-pytest` und `schemathesis` nehmen die gemeinsame Python-Sperre
(`/var/lib/adminhelper-dev/py.lock`). Laeuft daneben eine andere Server-Suite (Haupt-Checkout, eine
Lane), wartet schon die Grundlage, der `verify.sh`-Lauf vor der ersten Task, dort
(`loop/<slug>/fundament.log`: `waiting for the shared python lock`); im ersten Messlauf 10–38 Minuten.
Nach `AH_PY_LOCK_WAIT` (3600 s) ist der Schritt ein SKIP; bei `server-pytest`, einem Pflicht-Schritt
des Builders, macht `--strict` die Grundlage rot.

### Go Toolchain (Agent)

```bash
# Go 1.25+ installieren (siehe https://go.dev/dl/ — go.mod verlangt 1.25)
sudo apt install -y golang-go
# Oder manuell (Version von https://go.dev/dl/ einsetzen):
# wget https://go.dev/dl/go1.25.x.linux-amd64.tar.gz
# sudo tar -C /usr/local -xzf go1.25.x.linux-amd64.tar.gz
```

### Node.js + npm (Desktop-UI und Web-Frontend)

Beide Svelte-Frontends (und `cargo tauri dev`, das den Vite-Dev-Server
startet) brauchen Node.js 22+:

```bash
# Z. B. via NodeSource oder nvm; danach in beiden Projekten:
cd apps/desktop/ui && npm ci
cd apps/web && npm ci
```

### Docker (Server + frps + Monitoring)

Docker und Docker Compose werden fuer das vollstaendige Setup mit frps benoetigt:

```bash
sudo apt install -y docker.io docker-compose-v2
sudo usermod -aG docker $USER
# Danach neu einloggen
```

### Optionale Tools

```bash
# RDP-Client fuer Verbindungstests
sudo apt install -y freerdp3-x11

# SSH-Client (meist schon vorhanden)
sudo apt install -y openssh-client
```

### Audit-Tools lokal

`audit.yml` faehrt den woechentlichen CVE-Sweep in CI. Lokal — vor einem
Dependency-Update oder um einen roten Sweep nachzustellen — braucht es dieselben
drei Werkzeuge in **denselben gepinnten Versionen**; eine andere Version
vergleicht andere Befunde:

```bash
# Go: landet in ~/go/bin, das .devenv.sh in den PATH legt.
# GOTOOLCHAIN=local, weil CI (setup-go) genauso baut — ohne das holt sich go
# still eine neuere Toolchain und der Pin sagt nichts mehr darueber aus, was in
# CI ueberhaupt uebersetzt.
GOTOOLCHAIN=local go install golang.org/x/vuln/cmd/govulncheck@v1.7.0

# Python: Debians pip ist externally-managed (PEP 668), also ein eigenes venv
# statt --user, plus ein Symlink in den PATH.
python3 -m venv ~/.local/share/ah-tools/pip-audit-venv
~/.local/share/ah-tools/pip-audit-venv/bin/pip install -q pip-audit==2.10.1
ln -sfn ~/.local/share/ah-tools/pip-audit-venv/bin/pip-audit ~/.local/bin/pip-audit

# Rust
cargo install cargo-audit --locked --version 0.22.2
```

Aufrufe je Komponente — dieselben wie in `audit.yml`, aus dem Repo-Root
(Subshells, damit der ganze Block am Stueck kopierbar bleibt):

```bash
(cd apps/agent             && govulncheck ./...)
(cd apps/server            && pip-audit -r requirements.txt --disable-pip)
(cd apps/monitoring        && pip-audit -r requirements.txt --disable-pip)
(cd apps/ca-issuer         && pip-audit -r requirements.txt --disable-pip)
(cd apps/desktop/src-tauri && cargo audit)
```

`--disable-pip` ist kein Detail: `requirements.txt` ist der gehashte Lock, und
ohne das Flag wuerde pip-audit ihn zum Aufloesen installieren wollen.

`govulncheck` meldet auch stdlib-Funde und bewertet sie gegen die Go-Version,
mit der es gebaut wurde. Die Dev-Box muss deshalb dieselbe Minor fahren wie
`go-version` in den Workflows (heute `1.25`), sonst weicht der lokale Befund von
CI ab. Gewechselt wird per Tarball-Swap unter `~/sdk/go` — `.devenv.sh` legt
`~/sdk/go/bin` vor das System-Go. Dass der govulncheck-Pin ueberhaupt noch zur
`go-version` passt, prueft `bash scripts/dev/toolchain-lockstep.sh` (in CI ein
Step im Job `frp-consistency`): x/vuln v1.8.0 verlangt `go 1.26.0` und liesse
sich unter `GOTOOLCHAIN=local` auf 1.25 nicht mehr bauen — ein Job, der schon
beim Installieren scheitert, sagt nichts ueber unsere Dependencies aus.

---

## Entwicklung starten

### Server (lokal mit uvicorn)

```bash
cd apps/server
source .venv/bin/activate
DATA_DIR=../data uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

Der Server laeuft dann unter `http://127.0.0.1:8080` mit Web-Interface und API-Docs unter `/api/docs` (Swagger UI) bzw. `/openapi.json`.

**Erstanmeldung:** Es gibt keinen Default-Login mehr. Im Log nach `Setup-Token` suchen, dann mit dem Token einen Admin per `POST /api/auth/bootstrap` anlegen (siehe README). Fuer schnelle lokale Entwicklung kannst du in der `.env` `ADMIN_PASSWORD=dev` setzen — dann legt der Server beim Start einen Admin `admin/dev` direkt an.

Umgebungsvariablen koennen ueber eine `.env`-Datei im Projektroot gesetzt werden (siehe `.env.example`).

### Server + frps (Docker, empfohlen)

Fuer das vollstaendige Setup inkl. FRP-Server. Beim ersten Start einmal
die Secrets initialisieren — generiert `SECRET_KEY`, `MONITOR_API_KEY`,
`POSTGRES_PASSWORD` und `CA_ROOT_PASSPHRASE` in der `.env`:

```bash
# Im Projektroot:
cp .env.example .env
./scripts/init-secrets.sh

docker compose pull
docker compose up -d
```

(`--build` greift nur, wenn eine `docker-compose.override.yml` mit
`build:`-Sektion existiert — die Standard-Compose nutzt fertige
ghcr.io-Images, siehe unten.)

Das startet:
- **Gateway** (nginx) als einzige öffentliche TLS-Kante auf `443` (Web/API) und `8444`
  (Enrollment); terminiert TLS und proxyt intern an den Server
- **Server** nur intern im Compose-Network (plain-HTTP `8080`, kein Host-Port); erreichbar
  über das Gateway unter `https://localhost`
- **ca-issuer** nur intern (kein Host-Port): erzeugt beim ersten Start die interne PKI und
  stellt dem Gateway sein TLS-Leaf bereit
- **frps** auf Port 7000 (FRP-Protokoll) und 7443 (HTTPS-vhosts)
- **Monitoring** nur intern im Compose-Network (`expose 8080`, kein Host-Port); Agent-Metriken laufen tunnelfrei über den Server unter `/api/monitoring`
- **VictoriaMetrics** auf Port 8428 (intern, Time-Series DB)
- **PostgreSQL 17** (`postgres:17-alpine`, nur intern, kein Port-Mapping) — gemeinsame DB für Server (`adminhelper`) und Monitoring (`adminhelper_monitor`); die zweite DB wird beim ersten Start des Monitoring-Service (durch dessen Entrypoint) angelegt
- **scheduler** (Server-Image mit `RUN_MODE=scheduler`, nur intern, seit 0.38.0) — die **einzige** APScheduler-Instanz für periodische Jobs (u. a. FRP-Zertifikats-Renewals); bewusst **nicht** skalieren, sonst laufen die Jobs doppelt
- **redis** (`redis:7-alpine`, nur intern, ohne Persistenz) — Backing-Store für das Rate-Limiting und den SSE-Fan-out zwischen den Server-Workern

**Erstanmeldung:** Es gibt keinen Default-Login. Entweder den
Bootstrap-Token-Flow nutzen (`docker compose logs server | grep -A2
'Setup-Token'`, dann `POST /api/auth/bootstrap` — siehe README) oder fuer
lokale Entwicklung `ADMIN_PASSWORD=dev` in der `.env`/Override setzen, dann
existiert direkt ein Admin `admin`/`dev`.

Docker Compose laedt automatisch `docker-compose.override.yml`, falls vorhanden. Diese Datei ist in `.gitignore` und eignet sich fuer lokale Anpassungen:

```yaml
# docker-compose.override.yml (Beispiel: alle Images lokal bauen)
services:
  server:
    build:
      context: .            # Server-Image baut aus dem Root-Dockerfile
      dockerfile: Dockerfile
    image: adminhelper-server:dev
    environment:
      - ADMIN_PASSWORD=dev   # nur fuer lokale Entwicklung; Production: leer lassen + Bootstrap-Token
  monitoring:
    build:
      context: ./apps/monitoring
    image: adminhelper-monitoring:dev
  ca-issuer:
    build:
      context: ./apps/ca-issuer
    image: adminhelper-ca-issuer:dev
  gateway:
    build:
      context: ./apps/gateway
    image: adminhelper-gateway:dev
```

Mit so einer Override-Datei startet `docker compose up --build -d` den
lokal gebauten Stand.

**Logs ansehen:**

```bash
docker compose logs -f server
docker compose logs -f frps
```

### Client (Tauri)

```bash
cd apps/desktop/src-tauri
cargo tauri dev
```

Der Client oeffnet sich als Desktop-Fenster. `tauri.conf.json` ruft `npm --prefix ui run dev` (relativ zu `apps/desktop/`) als Vite-Dev-Server auf — Aenderungen am Svelte-Frontend (`apps/desktop/ui/`) werden live uebernommen, Rust-Aenderungen loesen einen Rebuild aus. Das alte `desktop/src/` (Plain-JS) ist seit v0.19.0 historisch und wird nicht mehr gebaut.

**Hinweis:** Beim ersten Build muss eine frpc-Platzhalter-Binary existieren:

```bash
mkdir -p apps/desktop/src-tauri/binaries
touch apps/desktop/src-tauri/binaries/frpc-x86_64-unknown-linux-gnu
```

Diese Binary wird im CI/CD durch die echte frpc-Binary ersetzt.

### Go Agent

```bash
cd apps/agent

# Linux-Binary bauen:
make build-linux

# Windows-Binary bauen (Cross-Compile):
make build-windows

# DEB-Paket erstellen:
make deb

# RPM-Paket erstellen:
make rpm

# Alles bauen:
make all
```

Der Agent laesst sich auch direkt starten:

```bash
go run ./cmd/adminhelper-agent version
go run ./cmd/adminhelper-agent run --once
```

### Monitoring (lokal ohne Docker)

```bash
cd apps/monitoring
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.in   # lose Quelle; requirements.txt ist die Lock

VICTORIA_METRICS_URL=http://localhost:8428 \
uvicorn app.main:app --reload --host 127.0.0.1 --port 8081
```

**Hinweis:** Fuer den vollen Monitoring-Stack wird VictoriaMetrics benoetigt, die per `docker compose up` automatisch mitgestartet wird.

---

## Client-Modi testen

Der Desktop-Client unterstuetzt drei Modi:

### Lokal-Modus

Standard. Connections werden lokal in `connections.json` gespeichert. Kein Server noetig.

### Sync-Modus

Client laedt Connections per HTTPS-URL + API-Key. Im Client: Einstellungen -> Modus: Sync -> URL eingeben.

### Server-Modus (JWT + Tunnel)

Vollstaendige Integration mit dem AdminHelper-Server:

1. **Server + frps starten** (siehe oben)
2. Im Client: Einstellungen -> Modus: **Server** -> Server-URL: `https://localhost`
3. Login mit dem beim Setup angelegten Admin — lokal am schnellsten via `ADMIN_PASSWORD=dev` in der `.env` (→ `admin` / `dev`, siehe Erstanmeldung oben); es gibt **keinen** `admin`/`admin`-Default
4. Connections werden per JWT-API geladen
5. frpc-Visitor startet automatisch im Hintergrund (wenn frpc-Binary vorhanden)

**Tunnel testen:**
- Im Server-Web-Interface: Server + Tunnel + Visitor anlegen
- Der Desktop-Client holt die Visitor-Config automatisch und startet frpc
- Verbindungen mit Tunnel zeigen ein gruenes "via Tunnel"-Badge
- SSH/RDP-Verbindungen werden automatisch ueber `127.0.0.1:<visitor_port>` aufgeloest

### Automatisierte Integrations-/E2E-Tests (Docker)

Ergaenzend zu den Komponenten-Unit-Tests fahren diese Tests den **echten** Stack
hoch — `docker-compose.yml` plus das Test-Overlay `docker-compose.test.yml`, das
die First-Party-Images aus dem Checkout baut, die Gateway-Ports auf hohe
Per-Run-Ports umlegt, Postgres und Redis nur auf `127.0.0.1` veroeffentlicht und
das `./data`-Volume isoliert. Die Ports streut `lib_e2e_stack.sh` pro Lauf
(`ITEST_HTTPS_PORT` 21000-38999, `ITEST_PG_PORT` 11000-15999, `ITEST_REDIS_PORT`
16000-20999 — die beiden letzten unterhalb des ephemeren Bereichs ab 32768; ohne
`e2e_init` gelten 18443, 15432 und 16379) und exportiert
`ITEST_DATABASE_URL` und `ITEST_REDIS_URL` fuer Tests, die auf dem Host laufen:

```bash
# From-outside: mTLS-Enrollment (CSR -> :8444) + JWT von aussen durchs Gateway
bash scripts/tests/integration_stack_test.sh

# Desktop-Live-E2E: die echte App (tauri-driver) legt ueber die GUI einen Tunnel an
bash scripts/tests/desktop_e2e_live.sh

# Desktop-Live-E2E: Tunnel STARTEN + verbinden (enrollt, +frps, prueft frps-Login)
bash scripts/tests/desktop_e2e_tunnel.sh

# Desktop-Live-E2E: GUI-CRUD (Connection/Tunnel/Server anlegen/umbenennen/loeschen)
bash scripts/tests/desktop_e2e_crud.sh

# Agent->Monitoring: echte Go-Agenten enrollen (mTLS) + pushen Metriken
# (AH_AGENTS=N fuer mehrere Agenten/Server)
bash scripts/tests/agent_monitoring_test.sh

# Desktop-Live-E2E: Monitoring-Check ueber die GUI anlegen (echte Agent-Daten)
bash scripts/tests/desktop_e2e_monitoring.sh

# Desktop-Live-E2E: Verbindung oeffnen gegen echte Ziel-Container
# (SSH -> sshd-Log, Web -> nginx-Log, RDP -> xrdp-Log)
bash scripts/tests/desktop_e2e_connect.sh

# Desktop-Live-E2E: SSH/Web/RDP ueber FRP-Tunnel, voller Durchstich
# (Desktop-Visitor -> frps -> agent-frpc -> sshd/nginx/xrdp)
bash scripts/tests/desktop_e2e_connect_tunnel.sh

# SSE-Push: Cross-Instance-Fan-out ueber echtes Redis. Zwei Server-Instanzen
# (8081/8082) an einem Postgres+Redis; SSE-Stream gegen A, Event gegen B ->
# A empfaengt den Push (beweist den Multi-Worker-Redis-Pfad). Braucht das
# Server-venv (VENV=..., Default das von run.sh: AH_VENV bzw. ~/.cache/ah-venv).
bash scripts/tests/sse_push_e2e.sh

# Desktop-Live-E2E: SSE-Push in der echten GUI. Event injizieren -> die Glocke
# aktualisiert sich in Echtzeit (Badge erscheint << 30s-Poll = beweist Push).
bash scripts/tests/desktop_e2e_sse_push.sh

# Pflicht-Tests gegen Postgres/Redis des Stacks (run.sh-Schritt stack-pytest):
# Migrations-Smoke und test_db_session_utc (monitoring), test_stream_redis (server),
# TOCTOU-Test (ca-issuer). Startet nur postgres + redis; ein Skip ist hier ein Fehler.
# JUnit: .ah-out/junit/stack-<name>.xml. Braucht das venv mit den Python-Deps.
bash scripts/tests/stack_pytest.sh

# Web-Panel ohne Mocks (run.sh-Schritt web-live): Playwright-Projekt `live`
# gegen das Gateway — Login als Seed-Admin, jede Admin-Seite, Benutzer anlegen
# und loeschen. JUnit: .ah-out/junit/web-live.xml.
bash scripts/tests/web_live.sh
```

Gemeinsamer Boot/Seed-Code liegt in `scripts/tests/lib_e2e_stack.sh`
(+ `e2e_api.py`). Die Desktop-E2E brauchen zusaetzlich `webkit2gtk-driver`,
`xvfb`, `tauri-driver`, `tauri-cli` und `gnome-keyring`/`dbus`
(siehe `apps/desktop/e2e/README.md`).

In CI laeuft (nur auf `main`-Push/manuell, kein PR-Gate) der From-outside-Test
(`integration-stack`). Einen CI-Job fuer den Desktop-Smoke-E2E gibt es **nicht**:
die headless-WebKit-Kette driftet mit dem Runner-Image und faerbte `main` rot
ohne echten Defekt. Der Smoke wie auch die **Desktop-Live-E2E**
(`desktop_e2e_live.sh` + `desktop_e2e_tunnel.sh`) laufen auf einer VM bzw. lokal
— vor Releases von Hand ausfuehren.

### Versions-Stellen vor einem Release pruefen

Sechs Stellen werden von Hand gebumpt (`tauri.conf.json`, `Cargo.toml`, `Cargo.lock`,
`CHANGELOG.md`, 38 Doku-Sidebar-Footer, zwei News-Callouts). `bash
scripts/release/check-versions.sh X.Y.Z` druckt je Stelle `ok`/`MISSING` und endet mit 1,
sobald eine fehlt — derselbe Aufruf laeuft im Release-Workflow auf dem Tag. Details und
die Bump-Reihenfolge: `.claude/rules/release.md`.

### VMs mit vm.py (Proxmox, ohne externes Binary)

`scripts/vm/vm.py` least, verwaltet und zerstoert die ephemeren Proxmox-VMs, auf denen die
schweren Suites laufen — Python-3-Standardbibliothek, keine Abhaengigkeit, nur die REST-API
(kein `pvesh`, kein `qm`). Seit Harness-Stufe 2b ist es der einzige Weg zu einer VM — die
Wrapper darunter rufen nichts anderes mehr auf.

**Konfiguration** kommt aus `~/.config/adminhelper/pve.env` und dem gitignoreten
`.claude/settings.local.json` (Block `env`, der Rueckfall); `pve.env` gewinnt ueber die settings-Datei,
und eine gleichnamige Umgebungsvariable gewinnt ueber beide, damit ein Runner sein eigenes Token
mitbringen kann, ohne eine Datei zu schreiben (R-0229). `pve.env` ist der Ort des Tokens: Claude Code
exportiert den `env`-Block in jede Session, eine eigene Datei nicht. Sie traegt Zeilen `KEY=VALUE` (nur
`AH_PVE_*`/`AH_VM_*`, wahlweise mit `export ` davor), wird gelesen und nie gesourct, und sie muss eine
regulaere Datei mit Modus 600 sein, die dem eigenen Benutzer gehoert, in einem Verzeichnis, in das
Gruppe und Andere nicht schreiben — sonst bricht `vm.py` mit Exit 2 und dem passenden `chmod` ab.
`scripts/vm/lib.sh` liest ueber `vm.py` genau dieselben Werte.

| Schluessel | Bedeutung |
|---|---|
| `AH_PVE_URL` | `https://<host>:8006`. Der Name **muss** im SAN des Zertifikats stehen (siehe TLS). |
| `AH_PVE_NODE` | Der Knoten, auf dem geklont wird. |
| `AH_PVE_TOKEN` | `<user>@pve!<tokenid>=<secret>`. Wandert nur im `Authorization`-Header, nie in eine URL. |
| `AH_PVE_CA` | Pfad zur Root-CA des Hypervisors (PEM). |
| `AH_PVE_STORAGE` · `AH_PVE_BRIDGE` · `AH_PVE_POOL` | Storage, Bridge und Pool der Klone. |
| `AH_PVE_VMID_RANGE` | `3000-3999`. Klone liegen im **unteren**, Templates im **oberen** Hundert. |
| `AH_VM_SSH_KEY` | Privater Schluessel; der `.pub` daneben wird per cloud-init in den Klon injiziert. |
| `AH_VM_MAX` | Deckel fuer gleichzeitige Leases **je Lane** (Default 8 — der Capstone haelt sieben). |
| `AH_VM_LINKED` | `1` (Default) = Linked Clone in ~2 s statt ~11 min Vollklon. |
| `AH_VM_REMOTE_DIR` | Wohin `sync` den Checkout schiebt (Default `~/adminhelper`). |
| `AH_VM_STATE_DIR` | Lokaler Zwischenspeicher (Default `.vm/`): `lane` und `warm.env`. |

**Umzug des Tokens (einmal):** Der Befehl schreibt `AH_PVE_TOKEN` aus der settings-Datei nach
`pve.env` (Datei 600, Verzeichnis 700) und nimmt es dort heraus, ohne den Wert auszugeben; eine
vorhandene `pve.env` liest er wie `vm.py`, und ein Symlink an ihrer Stelle bricht ab, bevor er etwas
schreibt. Im Haupt-Checkout ausfuehren und danach in jeder Lane (`../AdminHelper-<slug>`), denn
`lane.sh new` legt jeder Lane eine eigene Kopie der settings-Datei an; dort steht das Token schon in
`pve.env`, und der Befehl nimmt nur die Kopie heraus.

```bash
python3 - .claude/settings.local.json <<'PY'
import json, os, stat, sys
src = sys.argv[1]
dst = os.path.expanduser("~/.config/adminhelper/pve.env")
with open(src) as fh:
    data = json.load(fh)
token = data.get("env", {}).pop("AH_PVE_TOKEN", None)
if token is None:
    sys.exit("%s has no AH_PVE_TOKEN - nothing to move" % src)
text = ""
if os.path.lexists(dst):  # O_NOFOLLOW: a link is refused here too, before anything is written
    with os.fdopen(os.open(dst, os.O_RDONLY | os.O_NOFOLLOW), encoding="utf-8") as fh:
        text = fh.read()
have = False  # read as vm.py reads it: an empty value is no token
for line in text.splitlines():
    line = line.strip()
    if line.startswith("export") and line[6:7].isspace():
        line = line[6:].lstrip()
    key, _, value = line.partition("=")
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if key == "AH_PVE_TOKEN" and value:
        have = True
if not have:
    os.makedirs(os.path.dirname(dst), mode=0o700, exist_ok=True)
    os.chmod(os.path.dirname(dst), 0o700)
    fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "a") as fh:
        os.fchmod(fh.fileno(), 0o600)
        # A last line without a newline would swallow the token.
        fh.write(("\n" if text and not text.endswith("\n") else "") + "AH_PVE_TOKEN=%s\n" % token)
tmp = src + ".new"
with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
os.chmod(tmp, stat.S_IMODE(os.stat(src).st_mode))
os.replace(tmp, src)
print("AH_PVE_TOKEN: %s, removed from %s" % ("kept the one in " + dst if have else "now in " + dst, src))
PY
```

Danach `python3 scripts/vm/vm.py doctor` als Probe. Eine laufende Session traegt den alten Wert bis zu
ihrem Neustart in ihrer Umgebung — und dort gewinnt er weiter ueber `pve.env`.

Den SSH-Schluessel legt man **einmal** selbst an — `doctor` erzeugt ihn bewusst nicht als
Nebenwirkung:

```bash
ssh-keygen -t ed25519 -f ~/.config/adminhelper/vm_ed25519 -N ''
```

**Verben** (`python3 scripts/vm/vm.py <verb>`):

| Verb | Was es tut |
|---|---|
| `doctor [--roles a,b] [--json]` | Prueft API, Rechte, Storage, Templates, deren Guest-Agent und Bridge, die VMID-Baender und die Kapazitaet und druckt je Zeile `ok\|FAIL <check>: <detail>`. |
| `clone --profile p --role r [--lane l] [--scenario id] [--ttl 8h] [--memory MB] [--cores N] [--name n]` | Klont das Profil-Template, taggt die Lease, injiziert den Schluessel und startet die VM. Druckt `VMID NAME`. |
| `wait <vm> [--timeout 900]` | Wartet auf Guest-Agent, IPv4 und ssh — alle drei an **einer** Frist. Druckt die Adresse. |
| `ssh <vm> [-- cmd]` | Ohne Kommando eine interaktive Sitzung im Checkout, sonst der Exit-Code des Kommandos — roh, ohne Login-Shell (siehe `run`). |
| `sync <vm> [--no-delete]` | `rsync` des Checkouts auf die Box (Ausschlussliste: `scripts/vm/rsync-exclude.txt`). |
| `run <vm> [--sync] [--timeout S] [--out DIR] [--extend <dauer>] -- <cmd>` | Fuehrt das Kommando in einer **Login-Shell** im Checkout aus und reicht dessen Exit-Code **unveraendert** zurueck. `--out` holt `<remote>/.ah-out/`, `--extend 4h` versetzt vorher den `ttl-`Tag. |
| `pull <vm> <glob> <dir>` | Holt Dateien von der Box. |
| `snap <vm> <name> [--ram]` · `rollback <vm> <name> [--start]` · `delsnap <vm> <name>` | Snapshot, Ruecksetzen, Loeschen. `snap` und `rollback` je ~1–3 s auf LVM-thin; `delsnap` direkt nach einem `rollback --start` wartet, bis der Start das Config-Lock wieder freigibt (gemessen 35 s). |
| `destroy <vm>… \| --scenario id \| --lane l \| --role r` | Stoppt und loescht mit Platte. |
| `reap [--all] [--dry-run]` | Raeumt abgelaufene Leases weg — ohne `--all` nur die eigene Lane. |
| `list [--json] [--lane l]` | Zeigt alle eigenen VMs mit Rolle, Lane, Szenario, Adresse, Status und Rest-Lease. |
| `bake --profile linux-full\|linux-server [--from <tag>]` | Baut aus dem Basis-Image ein neues Template (~25–45 min). |

SSH merkt sich **keine** Host-Keys (`StrictHostKeyChecking=no`, `UserKnownHostsFile=/dev/null`):
diese VMs leben Minuten, jedes Bake loescht `/etc/ssh/ssh_host_*`, und der Pool vergibt dieselbe
DHCP-Adresse wieder — ein gemerkter Schluessel waere also sicher irgendwann falsch, und dann
kaeme niemand mehr auf die Box, bis jemand die Datei von Hand loescht. Gewonnen war damit
ohnehin nichts: beim ersten Kontakt wurde jeder Schluessel akzeptiert.

`run` nimmt eine **Login-Shell**, `ssh` nicht. Der Grund ist messbar: `go` steht auf der Box in
`/etc/profile.d/go.sh`, `cargo` in `~/.cargo/env` ueber `~/.profile` — ein blankes
`ssh host cmd` liest beides nicht. Ohne Login-Shell meldet `run.sh` dort `go=no cargo=no`,
ueberspringt die betroffenen Suiten und endet trotzdem mit 0: ein gruener Lauf, der weniger
geprueft hat. `ssh` bleibt bewusst der rohe Griff auf die Box.

**Exit-Codes.** `0` ok · `1` das Ausgefuehrte ist fehlgeschlagen (der Remote-Exit von `run`,
also ein roter Test) · `2` Aufruffehler, oder die Weigerung, etwas anzufassen, das uns nicht
gehoert · `74` Infrastruktur (API, Kapazitaet, keine Adresse, fehlendes Privileg). Die Trennung
1/74 ist der Grund, warum `heavy.sh` eine Infra-Stoerung nicht als roten Test berichten muss:
die Wrapper reichen den Code unveraendert durch.

**Tags sind die Lease-Wahrheit**, nicht eine lokale Datei. Jede VM traegt `ah` plus
`role-…`, `lane-…`, `sc-…`, `ttl-<epoch>`, `tpl-…`; Templates tragen `ah-tpl-<profil>` und
`built-<yyyymmdd>`. Daraus folgt dreierlei: jeder Checkout sieht jede Lease samt Frist, der
Aufraeumer braucht keinen lokalen Zustand — **jedes** Verb ausser `list` und `doctor` kehrt am
Ende die eigene Lane (`AH_VM_NO_AUTOREAP=1` schaltet das ab) —, und eine VM **ohne** `ah`-Tag
ist fuer dieses Werkzeug unsichtbar: jedes zerstoerende Verb verweigert sie mit Exit 2 —
deshalb kann der Pool auch Homelab-VMs tragen, ohne dass ein Tippfehler eine davon frisst.

**Probe von Hand** — `doctor` sichert sie vorher ab. `clone` druckt `VMID NAME`; die VMID
aus dieser Zeile ist in allen folgenden Aufrufen gemeint (unten `3000` als Beispiel):

```bash
python3 scripts/vm/vm.py doctor --roles probe          # alles ok?
python3 scripts/vm/vm.py clone --profile linux-full --role probe --ttl 20m
python3 scripts/vm/vm.py wait 3000                     # Adresse in < 5 min
python3 scripts/vm/vm.py run 3000 --sync -- 'bash scripts/tests/run.sh lint'
python3 scripts/vm/vm.py snap 3000 s1
python3 scripts/vm/vm.py rollback 3000 s1 --start
python3 scripts/vm/vm.py delsnap 3000 s1
python3 scripts/vm/vm.py destroy 3000
python3 scripts/vm/vm.py list                          # leer, Exit 0
```

`list` endet mit Exit != 0, wenn auf der eigenen Lane eine VM steht, die niemand beansprucht:
weder als Warm-Slot in `.vm/warm.env`, noch ueber das laufende Szenario (`AH_VM_SCENARIO`),
noch als laufendes Bake (`role-bake`) — eine geleakte VM ist ein Fehler, kein Detail.

**Die Lane** ist das, was parallele Worktrees auseinanderhaelt: jede VM traegt sie als Tag,
und `reap` (ohne `--all`) wie der Auto-Reap fassen nur die eigene an. Sie kommt aus `--lane`,
sonst aus `AH_LANE`, sonst aus `.vm/lane` — die Datei ist heute von Hand zu setzen, meist ist
`AH_LANE` im Worktree einfacher; ab 2b legt `lane.sh new <slug>` sie an —, sonst ist sie
`main` — der Hauptcheckout. `vm.py` und `scripts/vm/lib.sh` normalisieren sie identisch;
`scripts/tests/lib_vm_test.sh` vergleicht beide Seiten zeichenweise, weil eine Uneinigkeit
darueber, wessen VM eine VM ist, genau eine Lane zu viel abraeumen wuerde.

**TLS.** Die Root-CA des Hypervisors traegt kein `keyUsage`, was Python 3.13 unter
`VERIFY_X509_STRICT` ablehnt. `vm.py` loescht **genau dieses eine Flag** und verifiziert sonst
voll gegen `AH_PVE_CA` — Kette und Hostname eingeschlossen. Darum muss `AH_PVE_URL` einen Namen
aus dem Zertifikats-SAN tragen; eine blosse IP, die nicht im SAN steht, scheitert an der
Hostname-Pruefung (und nicht etwa an einer abgeschalteten Verifikation).

**Die Shell-Seite.** `scripts/vm/lib.sh` wird gesourct, nicht ausgefuehrt, und haelt, was ein
Wrapper vor und nach einem `vm.py`-Aufruf braucht: `vm_load_env` (die Variablen oben),
`vm_lane`, `warm_get/set/clear` auf `.vm/warm.env`, `vm_marker` und `vm_build_agent_deb`.
Hermetisch geprueft von `scripts/tests/lib_vm_test.sh`; `vm.py` selbst von
`scripts/vm/tests/` gegen aufgezeichnete API-Antworten (Herkunft und Bereinigungsregel:
`scripts/vm/tests/README.md`). Beides faehrt `bash scripts/dev/verify.sh scripts --strict` mit.

### Schwere Suites auf VMs (Multi-Host + schneller Loop)

Wer kein lokales Docker/Display hat (z. B. die Agent-Sandbox), faehrt die schweren
Suites auf einer ephemeren Proxmox-VM (das Token in `~/.config/adminhelper/pve.env`, die uebrige
Konfiguration im gitignoreten `.claude/settings.local.json`; siehe „VMs mit vm.py“).
Ein Sammel-Runner buendelt die Single-Box-Layer:
`bash scripts/tests/run.sh [lint|unit|quick|integration|e2e|all] [--strict]
[--only <keys…>] [--step <name>]` (schwere Layer verlangen `AH_ALLOW_REAL=1`;
`--only server web` begrenzt lint/unit auf die genannten Komponenten — gefilterte
Steps melden SKIP). `scripts/vm/iter.sh` reicht die Flags an die Box weiter.

- **Schneller Loop (warm once → iterieren → reapen).** Eine hydrierte Box ist teuer
  zu bauen (~18 min Bootstrap + ~20 min Tauri-Build), aber billig zu halten:
  `bash scripts/vm/warm.sh <desktop|server|pond>` hydriert **einmal** und merkt die
  VMID (`.vm/warm.env`); danach ist jede Iteration inkrementell (`target/` +
  `node_modules/` bleiben vom Sync ausgenommen) und dauert Minuten statt ~40:
  `bash scripts/vm/iter.sh <layer>` bzw. `iter.sh --desktop`; `iter.sh
  --cmd '<befehl>'` faehrt einen beliebigen Einzel-Befehl (z. B. ein Task-`Verify:`)
  auf der warmen Box. `bash scripts/vm/reap.sh` raeumt die Warm-Boxen auf. Bei Fehler
  bleibt die Box stehen (`python3 scripts/vm/vm.py ssh <vmid>`) und Screenshots/Logs
  landen automatisch lokal unter `.ah-out/`.
- **Parallele Lanes.** `bash scripts/dev/lane.sh new <slug>` legt fuer ein Vorhaben
  einen Git-Worktree `../AdminHelper-<slug>` an (Branch `feature/<slug>` von `main`;
  `.devenv.sh` als Symlink, `.claude/settings.local.json` als **Kopie** — Claude Code
  schreibt die Datei bei Permission-Grants, ein Symlink waere ein geteiltes
  Write-Target aller Lanes). Jede Lane bekommt ihre **eigene Lane-Kennung**: `lane.sh
  new` schreibt den Slug nach `.vm/lane`, jede VM traegt den Tag `lane-<slug>`, und
  `reap`, der Auto-Sweep am Ende jedes Verbs und die Leak-Pruefung in `list` arbeiten
  auf der eigenen Lane — Reap einer Lane laesst die anderen stehen. `destroy` filtert
  ueber `--lane/--scenario/--role`; eine ausdruecklich genannte VMID wird zerstoert,
  geschuetzt ist dort nur, was kein `ah`-Tag traegt. Klone werden seriell abgeschickt (ein
  Linked Clone dauert ~2 s). Aus einem Worktree reist `.git` nur als Zeiger mit, der
  auf der Box ins Leere zeigt. Die Box braucht kein Repo (Entscheidung Kevin,
  2026-09-25): Kopf und Tree-Hash gibt `iter.sh` vom Client mit. Ein Test, der auf der
  Box `git` voraussetzt, gehoert deshalb nicht auf die Box. `lane.sh done <slug>` zerstoert die
  VMs der Lane und raeumt Worktree + Branch ab — auch dann, wenn der Worktree schon
  von Hand entfernt wurde.
  Kompletter autonomer Ablauf: `AUTONOMOUS.md` („Parallel-Betrieb").
- **Verteilt (Multi-Host).** `bash scripts/tests/multibox.sh --agents N [--desktop]`
  klont Server- + Agent-Box(en); mit `--desktop` zusaetzlich eine Box, die die
  echte Tauri-GUI headless gegen den **entfernten** Server faehrt (Login/CRUD/
  Monitoring) — Cross-Host-mTLS, echtes `.deb`, Monitoring ueber den Netz-Hop.
  `--capstone` ist die Release-Kombination (alle Szenarien plus `--enforce`).
  Die Frist der Warm-Box kommt aus `AH_WARM_TTL` (Default 8h); `iter.sh` verlaengert bei
  jedem Lauf um genau diese Frist (warm.sh merkt sie als `desktop_ttl` in `.vm/warm.env`),
  eine bewusst kurze Box bleibt also kurz.

### Wochenlauf (heavy.sh)

Der schwere Tier laeuft nicht mehr „wenn man daran denkt", sondern als ein Lauf mit
Report und Historie. **Nichts davon startet von selbst** — Kevin startet ihn: von Hand in
`tmux`, oder mit `/test weekly` aus einer Claude-Session, die denselben tmux-Lauf startet, ihn
bis zum Report ueberwacht und das Ergebnis samt VM-Liste meldet (Regeln im `/test`-Skill):

```bash
tmux new -d -s ah-weekly 'bash scripts/tests/heavy.sh weekly'
```

```
bash scripts/tests/heavy.sh all|capstone|weekly [--base <sha>] [--no-second-vm] [--notify]
```

- `all` = warme Box → `run.sh all --strict`; `capstone` = `multibox.sh --capstone
  --strict`; `weekly` = beides seriell. Der Capstone entfaellt **nur**, wenn die `all`-Ebene
  UNVERIFIED endete (sieben VMs brennen sonst in eine kaputte Umgebung) — ein reines FAIL
  stoppt ihn nicht.
- **Vorab:** `vm.py doctor --roles <was der Modus klont>`, und `vm.py list --json` darf keine
  Box einer fremden Lane und nichts Geleaktes auf der eigenen zeigen — sonst ist die
  Kapazitaet nicht da und der Lauf bricht ab, bevor er eine VM verbraucht.
- **Report:** `.ah-out/weekly/<jjjj-mm-tt-hhmm>/report.md`. Erste Zeile ist das Urteil
  (`PASS` | `FAIL` | `UNVERIFIED (<grund>)`), dann die Summary-Zeilen der Wrapper
  **woertlich**, die Schritt-Tabelle, „Kevin sichtet", die Notizen, die `audit.yml`-Zeile und
  die VM-Liste danach. Nie eine Bewertung, nur Fakten. Dieselbe erste Zeile steht beim
  Session-Start in Zeile 4 des `AH-STATUS`-Blocks. Die `audit.yml`-Zeile erzeugt bei rot genau
  **eine** REL-Zeile je roter Phase: der Eintrag bleibt in `seen.md` offen (`deps-audit · open`),
  bis ein Lauf mit `success` ihn schliesst (`resolved`) — abgebrochene oder uebersprungene Laeufe
  aendern nichts. Eine neue Zeile gibt es erst beim naechsten roten Lauf nach einem gruenen, und
  auch dann nur, wenn die alte REL-Zeile nicht mehr offen ist: ihr Dedup-Key `rel:deps-audit`
  haelt die neue sonst zurueck. Roadmap-Zeilen legt `heavy.sh` ueber `roadmap.py add` an; ist
  der Deckel von 20 `neu`-Zeilen voll oder die Zeile schon offen, steht das laut in den Notizen
  des Reports.
- **JUnit:** Die pytest-Schritte von `run.sh` schreiben `.ah-out/junit/<schritt-id>.xml`
  (`monitoring-pytest`, `ca-issuer-pytest`, `server-pytest`, fuer Schemathesis eine Datei je
  Dienst: `schemathesis-server` usw.), `stack-pytest` je Test `stack-<name>.xml`, Playwright
  `web-playwright.xml` bzw. `web-live.xml` (nur mit gesetztem `AH_OUT_DIR`, sonst schriebe der
  Reporter auf stdout) und die Desktop-E2E je `wdio run` eine `desktop-e2e-<ms>-<cid>.xml`
  (`@wdio/junit-reporter`). Jeder `run.sh`-Lauf verwirft vorher die XMLs des
  letzten, und `heavy.sh` leert das lokale `junit/` vor dem Lauf: der Pull von der Box loescht
  nichts, eine alte Datei zaehlte sonst als heutige. `heavy.sh` kopiert das gezogene `junit/`
  nach `.ah-out/weekly/<jjjj-mm-tt-hhmm>/junit/`; die Report-Zeile `JUnit:` nennt, wie viele
  XMLs dort liegen.
- **Historie:** `tasks/private/history.csv`
  (`datum,commit,tree_hash,ebene,schritt,ergebnis,sekunden,vm`). `heavy.sh` uebernimmt das
  Ergebnis eines Schritts woertlich aus `last-all.json` und klassifiziert nur die roten, es
  steht also auch `skip` in der Spalte — eine Zeile je Schritt plus eine Ebenen-Zeile,
  committet im privaten Repo, **nie** gepusht; Felder mit Komma oder Anfuehrungszeichen
  sind RFC-4180-gequotet. Auf der Box sind alle Schritte der schweren
  Layer Pflicht (Box-Regel, siehe „AH_REQUIRED"): ein `skip` wird dort unter `--strict` zum
  `strict-failed`, und die Ebene endet UNVERIFIED — `ergebnis` ∈
  `pass|skip|fail|flaky|infra|unbestaetigt|extern|reg` (`skip` nur ohne `--strict`).
- **Klassifikation.** `infra` gilt fuer die **ganze Ebene**, nicht fuer einen Schritt: keine
  warme Box, Warm-Pond nicht bereit, fehlgeschlagenes Server-Lease, `vm.py: capacity` oder
  `privilege` (und auf der Ein-Box-Ebene zusaetzlich `vm.py: no ip|no ssh|timeout|sync failed|
  clone … failed`), `strict-failed: no step ran` oder Wrapper-Exit 74 beenden die Ebene sofort — der Report hat dann bewusst keine
  Schritt-Tabelle, weil nichts gelaufen ist, und es ist nie eine Regression. Meldet das
  Box-Artefakt einen Pflicht-Schritt als `strict-failed` (SKIP unter `--strict`), ist die Ebene
  ebenfalls `infra`, die Schritt-Tabelle bleibt aber stehen: gelaufene Schritte `pass`, die
  nicht gelaufenen `infra`, ein echter roter Schritt daneben `fail` ohne Klassifikation (kein
  Retry, kein Capstone).
  **Ausnahme Capstone:** kommt das Setup einer Rolle nicht durch (`vm.py: sync/ssh/timeout/
  no ip/no ssh/clone …` — die Box hat den Baum nie bekommen oder war nie erreichbar — oder
  der Klon selbst ist gescheitert, dann nennt `multibox.sh` die Rolle in der Zeile),
  gelten die spaeteren FAILs dieser
  Rolle als `infra` je Schritt (Detail `setup abort: <rolle>`); bleiben nur solche
  Folgefehler, endet die Ebene UNVERIFIED mit dem Grund „capstone infra: …" und der
  Multibox-Summary-Zeile; jeder FAIL, der nicht auf einen Abbruch seiner Rolle folgt,
  macht die Ebene FAIL. Ist die Ebene gelaufen, wird jeder rote Schritt einzeln klassifiziert:
  bis zu drei Wiederholungen desselben Schritts auf derselben Box (`AH_NO_SYNC=1`) — ein gruener Lauf ⇒ `flaky`
  (Quarantaene in `tasks/private/seen.md`); dreimal identisch rot ⇒ eine frische zweite VM
  (Worktree `.ah-worktrees/w2`, Lane `w2`): dort gruen ⇒ `unbestaetigt`,
  dort rot ⇒ Gegenprobe auf dem letzten PASS-Commit — Basis gruen ⇒ `reg` (Roadmap-Zeile
  Klasse REG mit Dedup-Key `reg:<schritt>` plus `tasks/reg-<datum>-<schritt>.md`; `seen.md`
  sperrt denselben Fund 30 Tage, der Dedup-Key, solange seine Zeile offen ist), Basis ebenfalls
  rot ⇒ `extern`.
  Dreimal rot mit **unterschiedlichen** Markern ⇒ `fail` (reproduzierbar kaputt, aber ohne die
  stabile Signatur, die eine Regressions-Behauptung braucht — keine Zweit-VM).
  `--no-second-vm` ueberspringt die Zweit-VM, `--base <sha>` setzt den Vergleichs-Commit.
- **Exit-Codes:** `0` = PASS, `1` = FAIL, `74` = UNVERIFIED (Infrastruktur — der Lauf konnte
  nicht stattfinden, ueber den Code ist damit nichts bekannt), `2` = Usage. Als Infrastruktur
  zaehlen auch die Faelle, in denen die Wrapper nur `1` liefern: keine warme Box, Warm-Pond
  nicht bereit, fehlgeschlagenes Server-Lease, `strict-failed: no step ran`.
- **`--notify`** postet die Urteilszeile und den Report-Pfad an `AH_NOTIFY_URL` (aus
  `.devenv.sh`, gitignored); Default aus, ein fehlgeschlagener POST ist kein Fehler des Laufs.

**Keine offenen Vorbehalte mehr** (Ledger `tasks/harness-stufe-3.md`): **T7a** — `--capstone`
setzt seit Stufe 3 `--enforce`, das Gateway verlangt damit ein Client-Zertifikat auf :443; die
Desktop-Etappe enrollt deshalb vor jedem Spec eine Geraete-Identitaet ueber die certlose
Ebene :8444 (ein Einmal-Token je Spec, kurz vor der Etappe gemintet) — bewiesen im Capstone
vom 2026-09-11. **T15a** — `AH_REQUIRED` erreichte die Box nicht — ist mit der Box-Regel
oben behoben (`harness-stufe-3b` T1).

---

## Typische Workflows

### Client + Server gleichzeitig

Zwei Terminals oeffnen:

```bash
# Terminal 1: Server + frps (Docker)
docker compose up --build -d

# Terminal 2: Client
cd apps/desktop/src-tauri
cargo tauri dev
```

### Nur Server-API testen

```bash
cd apps/server && source .venv/bin/activate
DATA_DIR=../data uvicorn app.main:app --reload --host 127.0.0.1 --port 8080

# In einem anderen Terminal:
curl http://127.0.0.1:8080/api/docs
```

### Server-Login per CLI testen

```bash
# JWT holen (password = dein ADMIN_PASSWORD; hier das lokale `dev`, es gibt keinen admin/admin-Default)
TOKEN=$(curl -sk https://localhost/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"dev"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Connections abrufen
curl -sk https://localhost/api/connections \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

# Tunnel abrufen
curl -sk https://localhost/api/frp/tunnels \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

---

## Projektstruktur

```text
.
├─ apps/                     # alle lauffähigen Einheiten
│  ├─ server/                # FastAPI-Backend (modularer Monolith, 12 Module)
│  │  ├─ app/
│  │  │  ├─ main.py
│  │  │  ├─ core/                # config, auth, database, events, middleware, rate_limit
│  │  │  └─ modules/             # users, connections, servers, frp, hooks, api_keys,
│  │  │                          #   ansible, monitoring_proxy
│  │  ├─ alembic/               # DB-Migrationen
│  │  └─ requirements.txt
│  ├─ monitoring/            # eigenständiger FastAPI-Microservice (eigene DB)
│  │  ├─ app/
│  │  │  ├─ checkers/            # agent, smart, http, ping, tcp, plugins
│  │  │  ├─ routers/             # admin, agent, alerts, checks, templates
│  │  │  ├─ core/                # auth, config, database, victoria
│  │  │  └─ scheduler.py         # APScheduler für Pull-Checks
│  │  └─ Dockerfile
│  ├─ ca-issuer/             # Python/FastAPI PKI-Enrollment-Plane (eigenes mTLS, eigene pytest-Suite)
│  ├─ gateway/               # nginx Reverse-Proxy: TLS-/Header-/mTLS-Terminierung, Ratelimit
│  ├─ agent/                 # Unified Go Agent (Linux + Windows)
│  │  ├─ cmd/adminhelper-agent/  # Cobra CLI (run, frpc, monitor, service, version)
│  │  ├─ internal/               # config, frpc, monitor, service
│  │  ├─ deb/, rpm/              # Paket-Metadaten
│  │  ├─ systemd/                # adminhelper-agent.service + .timer
│  │  └─ Makefile                # build-linux, build-windows, deb, rpm
│  ├─ web/                   # PRODUKTIV: Svelte 5 + TS Web-Admin-Panel
│  │  ├─ src/
│  │  │  ├─ lib/api/             # 9 Module (client + 7 Domain-Wrapper + types)
│  │  │  ├─ lib/stores/          # 6 Stores
│  │  │  ├─ lib/i18n/            # DE/EN-Dictionaries
│  │  │  ├─ pages/               # 5 Produktiv-Pages + Login + Placeholder
│  │  │  └─ modals/              # 9 Modal-Komponenten
│  │  └─ tests/e2e/              # Playwright (login.spec.ts, smoke.spec.ts, crud.spec.ts)
│  └─ desktop/               # Tauri Desktop-Client (Backend + UI zusammen)
│     ├─ src-tauri/          # Rust/Tauri-Backend
│     │  ├─ src/
│     │  │  ├─ main.rs            # invoke_handler mit 32 Tauri-Commands
│     │  │  ├─ commands.rs        # IPC-Schnittstelle
│     │  │  ├─ auth.rs            # JWT-Login, Keyring-Persistenz
│     │  │  ├─ frpc.rs            # frpc-Sidecar Prozess-Management
│     │  │  ├─ tunnel.rs          # Tunnel-Mapping + Connection-Resolution
│     │  │  ├─ connection/        # SSH/RDP/Web Verbindungslogik
│     │  │  ├─ password.rs        # OS-Keyring (com.admincave.adminhelper)
│     │  │  ├─ ansible.rs         # Inventory-Generierung + Playbook-Ausführung
│     │  │  └─ ...
│     │  ├─ binaries/            # frpc-Sidecar (gitignored, CI-Download)
│     │  └─ capabilities/        # Tauri v2 Security Permissions
│     └─ ui/                 # PRODUKTIV: Svelte 5 + TS Desktop-Frontend
│        ├─ src/
│        │  ├─ lib/bridge/       # 31 typisierte invoke()-Wrapper
│        │  ├─ lib/stores/       # 12 Stores
│        │  ├─ lib/models/       # connection, settings, ansible, monitoring (typisiert)
│        │  ├─ components/       # ~46 Components
│        │  └─ pages/            # 5 Pages (Dashboard, Connections, Infrastructure, Ansible, Monitoring)
│        └─ vitest.setup.ts      # ~250 Vitest-Unit-Tests
├─ docs/                     # Dokumentation (DE + EN, statisches HTML)
├─ scripts/                  # Ops-/DB-Skripte (+ tests/: integration_stack_test, desktop_e2e_live, lib_e2e_stack)
├─ data/                     # Server-Daten (gitignored, Bind-Mount)
├─ Dockerfile                # Multi-Stage: Vite-Build (apps/web) → Python-Runtime (Server-Image)
├─ docker-compose.yml
├─ docker-compose.test.yml      # Test-Overlay (build aus Checkout, Ports/Volume isoliert)
├─ docker-compose.override.yml  # Lokale Dev-Overrides (gitignored)
├─ .github/workflows/        # CI/CD (GitHub Actions): ci, docker, release
└─ .env.example
```

---

## Aufraeumen

```bash
# Server venv entfernen
rm -rf apps/server/.venv

# Monitoring venv entfernen
rm -rf apps/monitoring/.venv

# Rust Build-Cache leeren (Holzhammer — naechster Build ist ein Full-Rebuild)
cd apps/desktop/src-tauri && cargo clean

# Sanfter: nur veraltete Artefakte entfernen, letzten Build behalten.
# target/ waechst sonst monoton, weil alte Dependency-/Toolchain-Versionen
# liegen bleiben. (einmalig installieren: cargo install cargo-sweep)
cargo sweep --installed       apps/desktop/src-tauri  # Reste alter Toolchains
cargo sweep --time 30         apps/desktop/src-tauri  # Artefakte aelter als 30 Tage
cargo sweep --dry-run --time 30 apps/desktop/src-tauri  # nur anzeigen, nichts loeschen

# Go Build-Cache leeren
cd apps/agent && go clean

# Docker aufraeumen
docker compose down -v

# frpc-Platzhalter entfernen
rm -rf apps/desktop/src-tauri/binaries/
```

Alle generierten Dateien (`.venv/`, `target/`, `data/`, `binaries/`, `__pycache__/`) sind in `.gitignore` eingetragen und landen nicht im Repository.
