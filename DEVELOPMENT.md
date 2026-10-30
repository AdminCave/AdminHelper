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

SPDX-Header neuer Quelldateien schreibt `reuse annotate` (CLAUDE.md §10). Ohne sudo (das Debian-Paket
`reuse` braeuchte es) ein eigenes venv mit Link in den `PATH`, wie bei `pip-audit` unten:

```bash
python3 -m venv ~/.local/share/ah-tools/reuse-venv
~/.local/share/ah-tools/reuse-venv/bin/pip install -q reuse==6.2.0
mkdir -p ~/.local/bin && ln -sfn ~/.local/share/ah-tools/reuse-venv/bin/reuse ~/.local/bin/reuse
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
(kein Boden); `scripts/dev/toolchain-lockstep.sh` prueft die Gleichheit. Ein anderes
ruff im `AH_VENV` zieht der Schritt `server-pytest` beim naechsten Lauf auf diese
Version zurueck. `ruff.toml` verlangt sie zusaetzlich per `required-version`: jedes
andere ruff bricht in diesem Baum mit Exit 2 ab, statt still andere Regeln anzuwenden —
auch im Format-Hook `scripts/dev/format-file.sh`, der dann still gar nicht formatiert
(sein Exit bleibt 0). Ohne ruff im `PATH` formatiert er ebenfalls nichts, und ein nacktes
`ruff check` scheitert auch nach `source .devenv.sh`, das nur cargo und go in den `PATH` legt.
Ein Link auf das ruff im `AH_VENV` folgt dem Pin, denn `server-pytest` zieht es auf ihn:

```bash
mkdir -p ~/.local/bin && ln -s ~/.cache/ah-venv/bin/ruff ~/.local/bin/ruff
```

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
  -c "CREATE ROLE adminhelper LOGIN CREATEDB;" \
  -c "CREATE DATABASE adminhelper_test OWNER adminhelper;"
# Passwort setzen: am Prompt \password adminhelper eingeben, danach \q
sudo -u postgres psql

# DATABASE_URL NUR für die server-Suite setzen — global gesetzt würde es
# monitorings Alembic-Smoke fälschlich gegen das falsche Schema aktivieren:
DATABASE_URL="postgresql+psycopg://adminhelper:<passwort>@localhost:5432/adminhelper_test" \
  apps/server/.venv/bin/python -m pytest -q
```

Das Passwort steht nicht im Befehl: `\password` fragt es ab, verschlüsselt es und schickt es als
`ALTER ROLE` an den Server, ohne Klartext in der History oder im Server-Log (psql-Doku). Als Wert
eignet sich `openssl rand -hex 16`; Hex braucht in der URL keine Prozent-Kodierung. Dieselbe URL
setzt die `.devenv.sh` des Haupt-Checkouts als
`export AH_TEST_DB="postgresql+psycopg://adminhelper:<passwort>@localhost:5432/adminhelper_test"`.

**Umstellen.** Eine Einrichtung nach der älteren Anleitung hat als Passwort den Rollennamen. Die
Rolle setzt ihr neues Passwort selbst, ohne sudo (PostgreSQL-Doku zu `ALTER ROLE`: „Ordinary roles
can only change their own password.“): `psql "postgresql://adminhelper@localhost:5432/adminhelper_test"`
fragt das alte Passwort ab, am Prompt `\password` eingeben, danach `\q`. Dann die Zeile `AH_TEST_DB`
der `.devenv.sh` des Haupt-Checkouts auf das neue Passwort ändern. Die Worktrees folgen von selbst:
Ihre `.devenv.sh` sourct die des Haupt-Checkouts und ersetzt nur den Datenbanknamen. Umstellen nur,
solange kein lokaler Server-Lauf läuft, die Sperre aus „Die schweren Python-Schritte laufen
nacheinander“ (unten) also frei ist: Ein laufender Lauf öffnet neue Verbindungen mit der alten URL.

**Ein Worktree hat seine eigene Test-DB.** `bash scripts/dev/worktree-setup.sh <pfad> <slug>` legt
auf demselben Server `adminhelper_test_<slug>` an (Bindestriche werden zu `_`) und schreibt dem
Worktree eine eigene `.devenv.sh`: Sie sourct die des Haupt-Checkouts und biegt danach `AH_TEST_DB`
auf diese DB und `AH_VENV` auf `~/.cache/ah-venv-<slug>` um. `worktree-teardown.sh <pfad> <slug>`
löscht beides wieder. Die Rolle braucht dafür `CREATEDB`, die sie oben ohnehin hat. Steht das
Passwort als `Benutzer:Passwort@` in der URL, reist es in `PGPASSWORD`, nicht in einem Argument von
`createdb`/`dropdb` (`scripts/dev/pg-url.sh`); kann das Skript es dort nicht herauslösen, legt es
keine DB an. Ein Passwort oder ein anderes Geheimnis in der Query (`password`, `sslpassword`,
`oauth_client_secret`, `scram_client_key`, `scram_server_key`, in jeder Schreibweise) lehnt es ebenso
ab, auch einen prozentkodierten Schlüssel der Query (libpq dekodiert auch Schlüssel). Eine andere Form
als eine URL `postgresql://` oder `postgresql+<treiber>://`, etwa die Keyword-Form von libpq
(`host=… dbname=…`), nimmt es nicht an. Ist das Passwort der Benutzername (beide dekodiert, wie
SQLAlchemy sie liest; Groß- und Kleinschreibung zählen), endet `worktree-setup.sh` mit 1 und legt keine
DB an: Die maskierte Form der URL in Testberichten (`benutzer:***@`) nennt den Benutzer und damit das
Passwort. Abhilfe ist der Absatz „Umstellen“ oben; `worktree-teardown.sh` baut einen Worktree auch mit
einer solchen URL ab. Eine Besitzmarke gibt es nicht (Kevin, 2026-10-14): der
Teardown löscht die DB und das Venv, die zum Slug gehören.

**Die schweren Python-Schritte laufen nacheinander.** `server-pytest` und `schemathesis` holen
in `run.sh` vor dem Start eine Sperre (`flock`), gleich aus welchem Checkout: zwei Server-Suiten
auf einer Box haben einander die Tabellen und den Speicher genommen, bis zum OOM-Killer. Die
Sperrdatei wählt `run.sh` in dieser Reihenfolge: `AH_PY_LOCK_FILE`, wenn gesetzt; sonst die
**geteilte** Datei `/var/lib/adminhelper-dev/py.lock` (Pfad über `AH_PY_LOCK_SHARED`), sobald
ihr Verzeichnis existiert; sonst je Nutzer `~/.cache/adminhelper-py.lock`. Verzeichnis und Datei
gibt es nur, wo sie jemand per sudo angelegt hat: über sie warten die Läufe mehrerer Unix-Nutzer
aufeinander. Ohne das Verzeichnis gilt die Sperre nur **je Unix-Nutzer**, über alle seine
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
bash scripts/dev/verify.sh <komponente> [<komponente> …] [--strict] [--full] [--tree <pfad>] [-- <args>]

bash scripts/dev/verify.sh monitoring --strict           # eine Komponente
bash scripts/dev/verify.sh web desktop-e2e --strict      # mehrere, in einem Lauf
bash scripts/dev/verify.sh server -- tests/test_auth.py  # gezielt eine Datei
bash scripts/dev/verify.sh all --strict                  # der ganze quick-Layer
bash scripts/dev/verify.sh web --tree ../lane-b          # ein anderer Worktree
```

Komponenten: `server monitoring ca-issuer agent desktop desktop-rs desktop-ui
desktop-e2e web scripts` und `all` (nur allein). Mehrere Komponenten werden ein Lauf
`run.sh quick --only <a> <b>`; Argumente nach `--` gibt es nur fuer eine Komponente, sonst
Exit 2. Bei `scripts` sind es Namen von Script-Tests, etwa
`verify.sh scripts --strict -- ledger_test`: nur diese laufen, ein Name, der nicht in
der Liste steht, ist Exit 2. Ein gezielter Lauf (`-- <args>`) laesst den Schritt
`schemathesis` aus (`SKIP … (AH_ARGS)`, auch unter `--strict` kein Fehler): er kostete jede
Task-Verify gut fuenf Minuten, voll laeuft er in der PR-CI. Ein Lauf, der die Suite erreicht, hinterlaesst
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

**Log und Digest.** Die volle Ausgabe der Suite landet in
`.ah-out/logs/verify-<zeit>-<pid>.log` (die neuesten 30 bleiben; `last-verify.json` nennt
den Pfad unter `log`). Auf stdout steht der Digest von `scripts/dev/log-digest.sh`: eine Zeile je
Schritt (die per `--only` oder `--` ausgelassenen nur als Zahl), je rotem oder selbst
uebersprungenem Schritt seine Fehlerzeilen (hoechstens 60) und die letzten 20 Zeilen seines
Abschnitts mit Zeilennummern, dann der Schlussblock von `run.sh` (Summary, `strict-failed`- und
`failed`-Liste), Exit-Code und Logpfad; steht kein Schlussblock am Ende des Logs, die letzten 40
Zeilen. Gibt ein roter Test eingefangene `run.sh`-Ausgabe aus, setzt sie keine Grenzen: je Schritt
gilt das schlechteste Ergebnis, widerspruechliche Zeilen werden genannt, und ein Auszug zeigt im
Zweifel mehr. Keine Schritt-Zeile wird gekuerzt. Mehr liest man
gezielt (`sed -n <a>,<b>p <log>`). Auf einem Terminal oder mit `--full` laeuft die volle Ausgabe
zusaetzlich mit. Jedes andere `run.sh`-Log fasst `bash scripts/dev/log-digest.sh <log> [<exit>]`
genauso zusammen.

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

`oasdiff` braucht der Pflicht-Schritt `scripts` von `run.sh`: `scripts/tests/openapi_breaking_test.sh`
prueft die Ausnahme-Datei `scripts/dev/oasdiff-err-ignore.txt` gegen das echte oasdiff und endet
ohne Binary mit Exit 75 — unter `--strict` also rot. CI (Jobs `openapi-compat` und `ops-scripts`)
und die Test-Boxen (`scripts/vm/bootstrap_linux.sh`) installieren es; auf der Dev-Box einmal das
fertige Release-Binary holen:

```bash
# Stand 2026-10-17. Massgeblich ist .github/workflows/ci.yml (Schritt "Install oasdiff"
# im Job openapi-compat, OASDIFF_VERSION und OASDIFF_SHA256_LINUX_AMD64);
# scripts/dev/toolchain-lockstep.sh haelt scripts/vm/bootstrap_linux.sh gleich. Von dort
# uebernehmen, damit Dev-Box, CI und Boxen dieselbe Fassung messen.
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
ihrer go.mod, und die Workflows bauen mit `GOTOOLCHAIN=local` — aus der Quelle bricht der Bau,
sobald oasdiff die `go-version` der Workflows ueberholt, genauso wie seinerzeit `govulncheck`
(PR #14). Ein Tarball braucht gar keine Toolchain, und die Pruefsumme macht ein ausgetauschtes
Asset zum Fehler statt zur Ueberraschung.

Lokal gegen den Basis-Branch pruefen (braucht `oasdiff` im PATH, sonst Exit 75 = SKIP):

```bash
bash scripts/dev/openapi-breaking.sh server --base origin/main
bash scripts/dev/openapi-breaking.sh monitoring --base origin/main
```

Auch `gnome-keyring` braucht der Pflicht-Schritt `scripts`: `scripts/tests/lib_e2e_stack_test.sh`
startet fuer seine Keyring-Faelle einen echten `gnome-keyring-daemon` in einer eigenen
D-Bus-Session und endet ohne `gnome-keyring-daemon`, `dbus-run-session` oder `dbus-send` mit
Exit 75 — unter `--strict` also rot. CI (Job `ops-scripts`) und die Test-Boxen
(`scripts/vm/bootstrap_linux.sh`) installieren es; auf der Dev-Box (Debian/Ubuntu):
`sudo apt-get install --no-install-recommends gnome-keyring dbus`.

### Geteilte API-Typen (sync-from-web.sh --check)

`apps/web/src/lib/api/types.ts` und `apps/desktop/ui/src/lib/api/types.ts` sind
**keine** gemeinsame Datei mehr: das Web beschreibt die Admin-Panel-API (25
Exporte), das Desktop die Client-API (58). Gemeinsam sind drei Symbole —
`FrpConfig`, `FrpStatus`, `FrpStatusProxy`.

```bash
bash apps/desktop/ui/scripts/sync-from-web.sh --check   # Gate (CI: desktop-ui)
```

Geprueft wird die Schnittmenge, und zwar als **Teilmenge**: jede Zeile des
Web-Blocks muss im Desktop-Block stehen, das Desktop darf mehr fuehren. Das ist
kein Kompromiss, sondern die richtige Invariante — bis R-0723 trug das gemeinsame
`Server` im Desktop zusaetzlich `connections?: Connection[]`, das nur das
Admin-Panel ignorierte (seitdem kennt das Web nur `ServerSummary`). Der reale
Drift, den die Regel faengt: das Web zieht ein neues Feld nach, das Desktop nicht.

Quell-Exporte ohne Gegenstueck im Ziel werden nur berichtet, nicht bemaengelt.
Die drei erwarteten gemeinsamen Symbole stehen namentlich im Skript
(`CHECK_SHARED`): verschwindet eines von einer Seite, ist das ein Fehler, keine
kleinere gruene Menge. Ein blosser Zaehl-Boden haette erst bei zwei gleichzeitigen
Verlusten gegriffen — der realistische Fall ist der einzelne Refactor.

**Wo der Guard blind ist:** die Loeschrichtung. Entfernt das Web ein Feld, bleibt
die Teilmenge erfuellt — das Desktop behaelt die Leiche, und niemand meldet es.
Das ist die einzige der sechs Drift-Formen, die die Regel nicht faengt
(umbenannt, Typ geaendert, im Ziel entfernt: alle rot).

**Gegen den Server** prueft jede Seite ihr eigener Vertragstest
(`apps/web/src/lib/api/types.contract.test.ts`, `apps/desktop/ui/src/lib/api/types.contract.test.ts`):
jedes zugeordnete Interface gegen sein Schema im OpenAPI-Snapshot, das Desktop auch gegen
den des Monitoring-Dienstes. Eine geaenderte Antwort zieht deshalb Modell, Snapshot und
beide `types.ts` im selben Commit nach; ein Feld, das der Server nicht mehr sendet, meldet
dort jede Seite.

**`--apply` ist fuer diese Datei tot** und der bestehende Ueberschreib-Schutz
haelt es so: er bricht ab, sobald das Ziel Exporte hat, die die Quelle nicht
kennt — und das sind 54.

### Doku-Smoke (doc-smoke.py)

`scripts/dev/doc-smoke.py` prueft, ob die Dokumentation den Baum noch beschreibt:
jedes `<code>`-Fragment in `docs/**/*.html`, das mit `apps/`, `scripts/`, `docs/`,
`.github/` oder `.claude/` beginnt, muss eine existierende Datei benennen (`--paths`), und
ein `<code>`, das ganz aus einem Namen in Grossbuchstaben besteht, muss ausserhalb der Doku
im Repo vorkommen (`--env`: die drei `config.py`, `.env.example` oder eine getrackte Datei
ausserhalb von `docs/`, `CHANGELOG.md`, `tasks/` und Markdown, R-0044, R-0215).

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
Naechstes" (je die erste Zeile) und darunter die WIP-Zeile aus `roadmap.py show --wip`, dann
aktive Ledger, offene PRs, das Urteil des letzten Wochenlaufs und warme Boxen. Je Workflow mit `schedule:` folgt eine Zeile
`Geplant: <name> <Tag> (<n> d): <conclusion>` fuer den neuesten abgeschlossenen Lauf auf
`main`, Cron oder `workflow_dispatch` — ein per Dispatch bestaetigter Fix schliesst einen roten
Cron wie in `heavy.sh`; `WARN:` bei `failure`, `timed_out` oder `startup_failure` (mit
`gh run view <id> --log-failed`) und bei einem Lauf aelter als 8 Tage, wobei ein toter Cron erst
8 Tage nach dem letzten Dispatch auffaellt. Ohne `gh` steht dort `?`, ohne `WARN:`. Er ist rein lesend,
endet immer mit 0 und warnt nur bei den Triggern aus `CLAUDE.md` §3 und bei einem roten oder
veralteten geplanten Workflow — kein Trigger, keine `WARN:`-Zeile. Manuell:
`bash scripts/dev/hooks/session-status.sh`.

### Task schliessen: `ledger.sh` und `task-close.sh`

Kein Modell setzt selbst einen Haken oder macht einen Task-Commit. Der Weg einer Task, im Worktree des
Vorhabens (Ablauf: `.claude/skills/feature-build/SKILL.md`):

```bash
bash scripts/dev/ledger.sh start tasks/<slug>.md T7      # .vm/active-task: Komponente + Dateien
# ... die Session baut, reviewer prueft (Urteil in .ah-out/review/<slug>/T7.verdict.json) ...
bash scripts/dev/task-close.sh tasks/<slug>.md T7 --stage -m "feat(...): ..."
```

`task-close.sh` laeuft ausserhalb der Modell-Session, ist wiederholbar und geht in dieser Reihenfolge vor:

1. **Eingabe:** das Ledger liegt unter `tasks/*.md` (nicht README oder Vorlage, kein Symlink), die Task
   existiert, der Branch ist nicht `main`/`master` (sonst Exit 2).
2. **Handarbeit:** eine Task mit `Komponente: —` ist Exit 74; sie wird von Hand geschlossen.
3. **Staging:** `--stage` stagt genau die Pfade aus `Dateien:` (nie `git add -A`; Verzeichnisse werden
   abgelehnt, Loeschungen mitgenommen). Eine halb gestagte Datei bricht ab (Exit 2, mit Hinweis auf
   `ledger.sh set-files`). Der Index wird mit `git write-tree` festgehalten.
4. **Geloeschte Testdatei** (unter `tests/` oder `test/`, oder `*_test.*`, `test_*`, `*.test.*`, `*.spec.*`,
   `*.e2e.*`, `*.live.*`; eine Umbenennung zaehlt als Loeschung): nur mit einer committeten
   `Test-Löschung:`-Zeile dieser Task (sonst Exit 3; Format in `tasks/README.md`).
5. **`review.sh sec --staged`:** was nie in dieses oeffentliche Repo darf (Exit 4).
6. **Verify:** die `Verify:`-Zeile der Task, wie sie dasteht (`verify.sh <komp> --strict [-- <args>]`
   oder `run.sh <layer> --strict --only <komp>`; nennt sie die `Komponente:` der Task nicht, Exit 2),
   immer mit `--strict`: rot ist Exit 3, nicht lauffaehig Exit 74. Die Summary-Zeile wird die Evidenz.
7. **Urteil:** `.ah-out/review/<slug>/<id>.verdict.json` des `reviewer`, juenger als jede gestagte
   Datei, mit `verdict` = `approve` (sonst Exit 3). Entfaellt bei `Review: am Ende` im Ledger-Kopf.
8. **Index unveraendert** seit Schritt 3 (sonst Exit 2).
9. **Haken:** `ledger.sh mark-done` mit der Summary-Zeile als `Evidenz:`; war es die letzte offene Task,
   geht der Kopf von `aktiv` auf `bereit`.
10. **Commit** mit Code und Ledger; die Git-Hooks fahren `sec` noch einmal. Aendert der Commit eine
    `Test-Löschung:`-Zeile, nimmt `task-close.sh` ihn zurueck (`git reset --soft HEAD^`, Exit 4).

Exit-Codes: `0` committet · `2` Eingabe, Staging oder Index · `3` Suite rot, Urteil fehlt, Testdatei
ohne Ankuendigung · `4` private Datei oder Token im Diff, geaenderte Ankuendigung · `74` Suite nicht
lauffaehig oder Handarbeits-Task. Nach einem Fehler in Schritt 9 oder 10 setzt ein zweiter Lauf
dieselbe Zeile neu.

`ledger.sh` ist die einzige Stelle, die Task-Status, Haken und Kopf eines Ledgers schreibt (`start`,
`mark-done`, `mark-skip`, `mark-question`, `set-files`, `status`, `lint`); Plan und `## Entscheidungen` schreibt
die Session von Hand. Details in [`tasks/README.md`](tasks/README.md).
**`--evidence` ist ein Feld, kein Beweis:** `mark-done` nimmt jede Zeichenkette; wahr macht die Zeile
nur, dass `task-close.sh` sie aus dem eigenen Lauf erzeugt. Deshalb steht `ledger.sh mark-done` in
`.claude/settings.json` unter `ask`.

**Abschluss eines Vorhabens: `review.sh final`.** Vor dem PR prueft
`bash scripts/dev/review.sh final tasks/<slug>.md` das Branch-Urteil des `reviewer`
(`.ah-out/review/<slug>/branch.verdict.json` des Worktrees, in dem das Ledger liegt): keine Task mehr `[ ]`
oder `[?]`, `approve` gesamt, fuer den Code- und fuer den Testteil, beide mit Evidenz, eine Abdeckungsliste,
hoechstens drei Gegenproben (`red`, `green`, `not-runnable`), kein `blocker` neben einem `approve`, und seit
dem geprueften Commit (`head`) auf der eigenen Linie des Branches nur Commits, die allein das Ledger aendern, und
Merges ohne eigene Aenderungen (ein aufgeloester Konflikt zaehlt als neue Aenderung; `CHANGELOG.md` mit seinem
`merge=union` ausgenommen). Exit 0 druckt den PR-Abschnitt (Adressen und Hostnamen entfernt wie bei `pr-body`), Exit 3 jeden
Grund, Exit 2 einen Aufruffehler.

**`.gitattributes`: `CHANGELOG.md merge=union`.** Zwei Lanes, die beide unter
`## [Unreleased]` etwas anhaengen, bekommen damit keinen Konflikt — union nimmt **beide**
Seiten. Das dedupliziert aber nichts: legen beide dieselbe Versions-Ueberschrift an, steht
sie hinterher doppelt im File, ohne Konflikt-Marker. Vor einem Release lohnt der Blick in
den `Unreleased`-Block (`.claude/rules/release.md`).

### Entwicklung mit Claude Code

Gearbeitet wird in einer interaktiven Claude-Code-Session in tmux, die Kevin im Haupt-Checkout auf
`main` startet. Die Regeln stehen in `CLAUDE.md` (§2 wer entscheidet und baut, §4 Lebenslauf eines
Vorhabens, §5 Tests, §6 Rollen, Pruefer und Modelle, §7 Commit, §8 Roadmap und Worktrees, §13
Uebergabe), die Ablaeufe in den Skills unter `.claude/skills/`; hier steht, welche Teile es dafuer gibt.

- **Modelle:** `.claude/settings.json` startet die Session mit `model: opus` und `effortLevel: high`
  (vor den Benutzer-Settings); `claude --model sonnet` fuer klar begrenzte Arbeit, `claude --effort xhigh`
  fuer ein Architektur-Vorhaben oder `/model` und `/effort` ueberschreiben das fuer eine Session. Die
  Sub-Agenten tragen Modell und Effort im Frontmatter.
- **Sub-Agenten** in `.claude/agents/`: `reviewer` (eine Task vor dem Commit, oder der Branch vor dem PR
  ueber Code und Tests), `security` (Risikopfade), `advisor` (nur lesend, gezielte Hilfe bei
  schwierigen Fragen). Gebaut wird in der Session selbst. Die Session ruft sie ueber das Agent-Werkzeug
  mit `subagent_type`. Sie laufen im Arbeitsverzeichnis der Session, nicht im Worktree des Vorhabens:
  jeder Aufruf nennt den absoluten Worktree-Pfad, die Agenten arbeiten mit `git -C <wt>` und
  `bash <wt>/scripts/…`. Eine neue Agent-Datei sieht eine laufende Session nur, wenn
  `.claude/agents/` bei ihrem Start schon existierte und der Haupt-Checkout sie traegt.
- **Worktrees:** Jedes Vorhaben baut in `../AdminHelper-<slug>` auf `feature/<slug>`.
  `bash scripts/dev/worktree-setup.sh <pfad> <slug>` richtet ihn ein (eigene Test-DB, eigenes Venv,
  `node_modules` als Hardlink-Kopie, frpc-Sidecar, Venv-Links, `.vm/lane`);
  `bash scripts/dev/worktree-teardown.sh <pfad> <slug>` reapt zuerst die VMs der Lane und raeumt dann
  Worktree, Test-DB und Venv weg.
- **Commit einer Task** nur ueber `task-close.sh` (Abschnitt „Task schliessen“).
- **Token-Hooks:** `git config core.hooksPath scripts/dev/hooks`, einmal im Haupt-Checkout; Worktrees
  erben es. `pre-commit`, `prepare-commit-msg`, `pre-merge-commit` und `pre-applypatch` fahren
  `review.sh sec --staged`, `commit-msg` prueft die Nachricht, `pre-push` jeden Commit, den ein Push
  nach draussen bringt. Gemeldet werden Pfad oder Datei:Zeile, nie der Inhalt. Was an den Hooks
  vorbeigeht, faengt der CI-Job „Public repo guard (review.sh sec)“. Der PreToolUse-Hook
  `scripts/dev/hooks/harness-guard.sh` verweigert `git commit --no-verify` und Loeschen per Glob in
  geteilten Temp-Verzeichnissen.
- **AH-STATUS** druckt `scripts/dev/hooks/session-status.sh` beim Start (Abschnitt „Session-Status-Hook“).
- **Roadmap:** `tasks/private/ROADMAP.md` liegt in einem eigenen privaten Repo (Sicherheitsfunde,
  Homelab-Details) und wird nur ueber `roadmap.py` geschrieben (Abschnitt „Die Roadmap als Skript“).
- **Lange Laeufe** (Suiten ueber zehn Minuten, `/test`, Wochenlauf) laufen in einem tmux-Fenster ohne
  Modell, Ausgabe und Exit-Code in Dateien:
  `tmux new-window -d -n ah-quick "( . ./.devenv.sh; bash scripts/tests/run.sh quick --strict ) > <log> 2>&1; echo \$? > <rc>"`.
  Die Session wartet auf die `rc`-Datei und liest danach `bash scripts/dev/log-digest.sh <log> <rc>`.
- **Python-Sperre:** `server-pytest` und `schemathesis` warten ueber `/var/lib/adminhelper-dev/py.lock`
  (ohne das Verzeichnis `~/.cache/adminhelper-py.lock`) aufeinander, ueber alle Worktrees (Abschnitt
  „Python-Tests lokal“).
- **Sessions und Zuege (2026-10-29, CLAUDE.md §2):** `bash scripts/dev/start-session.sh kern|klein`
  startet die Kern-Session (Opus, medium) bzw. die Klein-Session (Sonnet, medium) mit
  `--autocompact 200k` und einem `/goal`, `start-session.sh arch R-nnnn` eine Architektur-Session
  (Opus, xhigh); `--dry-run` zeigt nur den Befehl. Welche Zeilen zusammen fahren, zeigt
  `roadmap.py zuege`; `bash scripts/dev/overlap.sh [--except <branch>] <pfad>...` nennt die offenen
  `feature/*`-Branches, die dieselben Dateien aendern (Exit 1 bei Ueberschneidung). CHANGELOG-Eintraege
  schreibt jeder Branch nach `changelog.d/<slug>.md`; der Release faltet sie mit
  `python3 scripts/release/changelog-assemble.py` in `CHANGELOG.md` (`changelog.d/README.md`).
- **Was es bewusst nicht gibt (2026-10-14):** keinen Worker-Loop, keinen Runner-Nutzer, kein
  Builder-Profil, keine Sandbox und keinen unbeaufsichtigten Betrieb. Jede Session startet Kevin.

### Die Roadmap als Skript: `roadmap.py`

`tasks/private/ROADMAP.md` (privates Repo) bleibt Markdown, das Kevin lesen und von Hand
aendern kann. `scripts/dev/roadmap.py` (nur Python-Stdlib) liest den Kopf (`Stand: … · WIP: …`)
und die Tabellenzeilen mit ihren zehn Spalten; alles andere, also Prosa und Leerzeilen, reicht
es byte-gleich durch. Den Abschnitt „Als Naechstes" schreibt es bei jedem Schreiben neu aus den
Zeilen, niemand pflegt ihn von Hand: was in Arbeit ist (`aktiv`, `bereit`, `pr` mit PR), je
Stufe der naechste wartende Zug (Reihenfolge wie `zuege`), die offenen REL-Zeilen und die
`blockiert`-Zeilen als „Wartet auf Kevin"; Handarbeit fuer Kevin ist darum eine `blockiert`-Zeile. Zeilen legen Kevin und die Skripte an (`heavy.sh`, spaeter die Finder); `/roadmap`
zeigt und triagiert sie (`.claude/skills/roadmap/SKILL.md`).

```bash
python3 scripts/dev/roadmap.py lint                      # tasks/private/ROADMAP.md
python3 scripts/dev/roadmap.py --file /tmp/x.md lint     # eine andere Datei
python3 scripts/dev/roadmap.py show [R-nnnn] [--wip]
python3 scripts/dev/roadmap.py next [--status freigegeben] [--exclude-components server web] [--stufe klein|kern]
python3 scripts/dev/roadmap.py zuege [--stufe klein|kern]
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
- `show` liest nur: ohne Argument „Als Naechstes", wie das letzte Schreiben ihn hinterliess, die WIP-Zaehler aus den Zeilen,
  die offenen Abschnitte mit ihren Zeilen und die Historie als Anzahl; mit einer ID die Zeile
  Feld fuer Feld; mit `--wip` nur die Zaehler (die liest der Status-Hook).
- `next` nennt die naechste Zeile zum Bauen: Klasse vor Reihenfolge (SEC > REG > REL > BUG >
  FEAT > REF > IDEE), wartet, solange „Haengt ab von" eine Zeile nennt, die nicht
  `abgeschlossen` ist, und ueberspringt Zeilen, die eine ausgeschlossene Komponente
  beruehren (`Komponente:` ihres Ledgers, die Komponente eines vollen Dedup-Keys
  `<klasse>:<komponente>:<datei>:<symbol>`; ein kurzer wie `reg:<schritt>` nennt keine).
  Das Ledger liest `next` aus dem Arbeitsbaum und von jedem lokalen und Remote-Branch, der
  den Pfad traegt, und vereinigt die Komponenten: ein geplantes Ledger liegt bis zum Merge
  nur auf seinem Branch (R-0065). `next` fetcht nicht — wer auf `origin/*` angewiesen ist,
  fuehrt vorher `git fetch --prune` aus; eine veraltete Kopie auf
  einem alten Branch schliesst hoechstens zu viel aus. Mit `--exclude-components` gilt
  fail-closed: nennt die Spalte `Ledger` einen Pfad `tasks/….md`, den weder der Baum noch
  ein Branch traegt, wird die Zeile uebersprungen, und stderr sagt es
  (`next: R-nnnn skipped — ledger <pfad> not found in the tree or on any branch (git fetch?)`).
  Ohne Ausschlussliste, bei `—`, einem Slug oder einem Pfad ausserhalb des Repos bleibt die
  Zeile im Rennen.
  Nichts bereit: Exit 1. `--stufe klein` nimmt nur Zeilen eines `klein-`-Ledgers, `--stufe arch`
  die eines `arch-`-Ledgers, `--stufe kern` alle anderen (auch Zeilen ohne Ledger).
- `zuege` zeigt die Zuege (CLAUDE.md §2): die offenen Zeilen (`geplant` bis `pr`), gruppiert nach
  ihrer Spalte `Ledger`, je Zug eine Zeile mit Stufe (`klein` fuer `klein-…`, `arch` fuer `arch-…`,
  sonst `kern`),
  `wartet` oder `unterwegs` und den IDs. Wartende zuerst, nach der hoechsten Klasse, dann nach
  Groesse; ein Zug unterwegs nimmt keine Zeile mehr auf. Kein Zug: Exit 1.
- `add` haengt eine `neu`-Zeile an „Neu" an und druckt ihre ID: die hoechste `R-nnnn` plus
  eins, gezaehlt ueber die Datei und ueber alle IDs, die das Skript je vergeben hat. So kommt
  eine ID, die ein Hand-Edit wieder entfernt hat, nicht ein zweites Mal. `--proof` und
  `Dedup-Key: <key>` stehen mit in „Quelle / Beweis"; `Ablauf` folgt der Klasse (IDEE 60
  Tage, REF 90 Tage, sonst `nie`). Wie viele Zeilen schon `neu` sind, haelt `add` nicht auf:
  `neu N/20` im WIP-Kopf ist Anzeige wie `aktiv N/2`. Traegt eine offene Zeile den Dedup-Key
  schon, ist das Exit 4 mit ihrer ID, und ein leerer Commit `roadmap: dedup <key> -> R-nnnn`
  haelt die Weigerung fuer `stats` fest.
- `status` setzt den Status und verschiebt die Zeile in den Abschnitt, der zu ihm gehoert.
  Erlaubt sind nur die Uebergaenge der Tabelle `TRANSITIONS` im Skript (sonst Exit 2);
  derselbe Status erneut sortiert eine falsch abgelegte Zeile ein und macht aus einem Alias
  das Wort. Ein geschlossener Status (`abgeschlossen`, `abgelehnt`) traegt den Tag; mehr
  als 7 Tage danach faellt die Zeile beim naechsten Schreiben aus der Datei (die Historie
  haelt das private git, `git log -S R-nnnn`). Nennt eine offene Zeile sie unter „Haengt ab
  von", bleibt sie und wandert oben ins „Archiv": `next` zaehlt eine Abhaengigkeit nur, solange
  ihre Zeile `abgeschlossen` in der Datei steht.
  `--ledger` schreibt die Spalte `Ledger` wie `add --ledger`, auch ohne Statuswechsel — so
  bekommt eine aeltere Zeile ihr Ledger nachgetragen; `next` und die Parallel-Pruefung am
  Gate lesen es dort, nicht aus der Notiz. Ebenso schreibt `--pr "#<n>"` die Spalte `PR`,
  die `sync` liest; eine Nummer in der Notiz sieht `sync` nicht, und ein Wert ohne `#<n>`
  ist Exit 2.
- `approve` ist `geplant` -> `freigegeben`, die Freigabe, die die Session nach dem Plan-Commit von `/feature-plan`
  setzt (CLAUDE.md §4); `--revoke` nimmt sie zurueck. Beide lassen die Notiz der Zeile stehen, anders als `status`
  ohne `--note`.
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

### Go Toolchain (Agent)

```bash
# Go 1.27.2 oder neuer installieren (https://go.dev/dl/). go.mod verlangt nur 1.25, CI und
# Release bauen aber mit dem neuesten 1.27.x: ein aelterer Patch traegt stdlib-Luecken, die
# erst der neueste schliesst, und 1.26 faellt mit Go 1.28 aus dem Support. Das Debian-Paket
# golang-go ist dafuer zu alt (trixie: 1.24), also manuell (Version von https://go.dev/dl/
# einsetzen):
# wget https://go.dev/dl/go1.27.x.linux-amd64.tar.gz
# sudo rm -rf /usr/local/go && sudo tar -C /usr/local -xzf go1.27.x.linux-amd64.tar.gz
```

Liegt Go ohne sudo unter `~/sdk/go`, legt `.devenv.sh` es in den `PATH`; damit ein nacktes `go` oder
`gofmt` (auch im Format-Hook) es ohne gesourctes `.devenv.sh` findet, zusaetzlich Links:

```bash
mkdir -p ~/.local/bin && ln -s ~/sdk/go/bin/go ~/sdk/go/bin/gofmt ~/.local/bin/
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
GOTOOLCHAIN=local go install golang.org/x/vuln/cmd/govulncheck@v1.9.0

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

`govulncheck` meldet auch stdlib-Funde und bewertet sie im Quelltext-Modus gegen
die Version des `go` im PATH. Die Dev-Box muss deshalb dieselbe Minor fahren wie
`go-version` in den Workflows (heute `1.27`), und zwar wie CI mit `check-latest`
den neuesten Patch (1.27.2 oder neuer), sonst weicht der lokale Befund von CI ab.
Gewechselt wird per Tarball-Swap unter `~/sdk/go` — `.devenv.sh` legt
`~/sdk/go/bin` vor das System-Go. Dass der govulncheck-Pin ueberhaupt noch zur
`go-version` passt, prueft `bash scripts/dev/toolchain-lockstep.sh` (in CI ein
Step im Job `frp-consistency`): x/vuln v1.8.0 verlangt `go 1.26.0` und liesse
sich unter `GOTOOLCHAIN=local` auf 1.25 nicht mehr bauen — ein Job, der schon
beim Installieren scheitert, sagt nichts ueber unsere Dependencies aus. Dieselbe
Pruefung verlangt neben jeder `go-version` im selben `with:`-Block
`check-latest: true`: sonst nimmt setup-go den Patch aus dem Toolcache des
Runner-Images, und der Release liefert womoeglich einen anderen stdlib-Stand aus,
als der Audit prueft. Ebenso muss der Default von `GO_VERSION` in
`scripts/vm/bootstrap_linux.sh`, das Go der Test-Boxen, dieselbe Minor haben wie
`go-version`; der Patch ist frei, die SHA-256 zieht beim Heben mit.

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

Umgebungsvariablen koennen ueber eine `.env`-Datei im Projektroot gesetzt werden (siehe `.env.example`); uvicorn liest sie nur mit `--env-file ../../.env`, der Server selbst liest keine `.env`.

**Datenbank:** Ohne `DATABASE_URL` meldet sich der Server mit dem Dev-Fallback `adminhelper:adminhelper@localhost:5432/adminhelper` an (`apps/server/app/core/config.py`). Hat die Rolle `adminhelper` ein eigenes Passwort (Abschnitt „Python-Tests lokal (ohne Docker)“), scheitert diese Anmeldung; dann gehoert `DATABASE_URL` mit dem Passwort in die `.env`.

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

**Datenbank:** Ohne `DATABASE_URL` meldet sich der Monitoring-Dienst mit dem Dev-Fallback `adminhelper:adminhelper@localhost:5432/adminhelper_monitor` an (`apps/monitoring/app/core/config.py`). Hat die Rolle `adminhelper` ein eigenes Passwort (Abschnitt „Python-Tests lokal (ohne Docker)“), scheitert diese Anmeldung; dann `DATABASE_URL` mit dem Passwort setzen. Die Datenbank `adminhelper_monitor` legt lokal niemand an, das tut nur der Entrypoint des Containers (`apps/monitoring/docker-entrypoint.sh`).

**Hinweis:** Fuer den vollen Monitoring-Stack wird VictoriaMetrics benoetigt, die per `docker compose up` automatisch mitgestartet wird.

---

## Client-Workspaces testen

Der Desktop-Client startet als Launcher mit dem Picker; jeder Workspace hat eine feste Art (Lokal, Sync oder Server)
und laeuft in einem eigenen Prozess (`adminhelper --workspace <id>`). Ohne Altdaten legt der erste Start den Workspace
„Standard“ (Lokal) an, weitere legt man im Picker unter „Neuer Workspace“ an. Daten und Logs liegen je Workspace
getrennt (`workspaces/<id>/` im App-Datenordner, `adminhelper-<id>.log`); Details in `docs/developer/desktop.html`.

### Lokal

Standard. Connections liegen in `workspaces/<id>/connections.local.json` im App-Datenordner. Kein Server noetig.

### Sync

Client laedt Connections per HTTPS-URL + API-Key. Im Picker einen Sync-Workspace mit der URL anlegen.

### Server (JWT + Tunnel)

Vollstaendige Integration mit dem AdminHelper-Server:

1. **Server + frps starten** (siehe oben)
2. Im Picker einen Server-Workspace mit der Server-URL `https://localhost` anlegen und oeffnen
3. Login mit dem beim Setup angelegten Admin — lokal am schnellsten via `ADMIN_PASSWORD=dev` in der `.env` (→ `admin` / `dev`, siehe Erstanmeldung oben); es gibt **keinen** `admin`/`admin`-Default
4. Connections werden per JWT-API geladen
5. frpc-Visitor startet automatisch im Hintergrund (wenn frpc-Binary vorhanden)

**Tunnel testen:**
- Im Server-Web-Interface: Server + Tunnel + Visitor anlegen
- Der Desktop-Client holt die Visitor-Config automatisch und startet frpc
- Verbindungen mit Tunnel zeigen ein gruenes "via Tunnel"-Badge
- SSH/RDP-Verbindungen werden automatisch ueber `127.0.0.1:<lokaler Port>` aufgeloest (der Visitor-Port oder, ist er belegt, ein freier aus 23000–23999)

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

# Desktop-Live-E2E: zwei Installationen nebeneinander in zwei Workspaces
# (zwei Stacks, zwei PKIs, derselbe Visitor-Port; jedes SSH-Ziel sieht genau
# den SSH-Client seines Fensters; zuletzt loescht der Launcher "Kunde B", und
# Stack b fuehrt dessen Geraet als von sich selbst widerrufen)
bash scripts/tests/desktop_e2e_workspaces.sh

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
# die Postgres-Tests von test_db_token_store (ca-issuer: Einloesen, Register, Identitaets-Sperre).
# Startet nur postgres + redis; ein Skip ist hier ein Fehler.
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
schreibt. Im Haupt-Checkout ausfuehren und danach in jedem Worktree (`../AdminHelper-<slug>`), der
noch eine Kopie der settings-Datei traegt: `worktree-setup.sh` legt sie nur an, solange `pve.env`
fehlt; dort steht das Token dann schon in `pve.env`, und der Befehl nimmt nur die Kopie heraus.

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
| `clone --profile p --role r [--lane l] [--scenario id] [--ttl 8h] [--memory MB] [--cores N] [--name n]` | Klont das Profil-Template, taggt die Lease, injiziert den Schluessel und startet die VM. Druckt `VMID NAME`. Der Klon bootet ohne Paket-Upgrade (`ciupgrade=0`): eine Lease laeuft mit dem Paketstand ihres Templates. |
| `wait <vm> [--timeout 900]` | Wartet auf Guest-Agent, IPv4 und ssh — alle drei an **einer** Frist. Druckt die Adresse. Danach bleibt ssh erreichbar: eine Lease spielt beim ersten Boot kein Paket-Upgrade ein, das sshd neu startet. |
| `ssh <vm> [-- cmd]` | Ohne Kommando eine interaktive Sitzung im Checkout, sonst der Exit-Code des Kommandos — roh, ohne Login-Shell (siehe `run`). |
| `sync <vm> [--no-delete]` | `rsync` des Checkouts auf die Box (Ausschlussliste: `scripts/vm/rsync-exclude.txt`). Nur auf eine VM der eigenen Lane, am frischen Zustand geprueft; eine andere mit `AH_LANE=<lane>`. |
| `run <vm> [--sync] [--timeout S] [--out DIR] [--extend <dauer>] -- <cmd>` | Fuehrt das Kommando in einer **Login-Shell** im Checkout aus und reicht dessen Exit-Code **unveraendert** zurueck. `--out` holt `<remote>/.ah-out/`, `--extend 4h` versetzt vorher den `ttl-`Tag. Wie `sync` nur auf eine VM der eigenen Lane. |
| `pull <vm> <glob> <dir>` | Holt Dateien von der Box. |
| `snap <vm> <name> [--ram]` · `rollback <vm> <name> [--start]` · `delsnap <vm> <name>` | Snapshot, Ruecksetzen, Loeschen. `snap` und `rollback` je ~1–3 s auf LVM-thin; `delsnap` direkt nach einem `rollback --start` wartet, bis der Start das Config-Lock wieder freigibt (gemessen 35 s). |
| `destroy <vm>… \| --scenario id \| --lane l \| --role r` | Stoppt und loescht mit Platte. Genannte VMs zusammen mit `--scenario`/`--lane`/`--role`: jede muss zu jedem Filter passen, sonst Abbruch (Exit 2) vor der ersten Zerstoerung; die Filter fuegen dann keine VMs hinzu. |
| `reap [--all] [--dry-run]` | Raeumt abgelaufene Leases weg — ohne `--all` nur die eigene Lane. |
| `list [--json] [--lane l]` | Zeigt alle eigenen VMs mit Rolle, Lane, Szenario, Adresse, Status und Rest-Lease. |
| `bake --profile linux-full\|linux-server [--from <tag>]` | Baut aus dem Basis-Image ein neues Template (~25–45 min). Nur dieser Klon bootet mit Paket-Upgrade (`ciupgrade=1`); `bake` wartet vor dem `sync` auf `cloud-init status --wait` (Exit 0 oder 2 = fertig) und bringt so den Paketstand der Leases auf den neuesten Stand. |

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
sonst aus `AH_LANE`, sonst aus `.vm/lane` — `worktree-setup.sh` schreibt sie als Erstes —, sonst ist sie
`main` — der Hauptcheckout. Ein von Hand angelegter Worktree (`git worktree add`, etwa die
`harness/`-Worktrees unter `~/.cache`) mit eigenem `.vm`, ohne `.vm/lane` und ohne `AH_LANE`
wird abgewiesen, sobald ein Verb die Lane braucht (Exit 2, „this worktree has no .vm/lane“):
`clone` nimmt dafuer auch `--lane`, bei `list` filtert `--lane` nur. Er liefe sonst still auf
der Lane des Hauptcheckouts, samt dessen Reap und Sweeps. Ein Lauf aus so einem Worktree,
Multibox, `warm.sh`, `iter.sh`, `reap.sh` und auch `vm.py list`, braucht deshalb `AH_LANE=main`,
wenn er auf main laufen soll, wie bei go-toolchain-126. `heavy.sh` fragt die Lane im Pre-flight
zuerst und endet ohne sie UNVERIFIED mit genau diesem Grund („this worktree has no .vm/lane —
set AH_LANE=…“), bevor es den Hypervisor fragt. Fuer `vm.py` selbst nennt `--as-lane <lane>` vor
dem Verb die Lane (`python3 scripts/vm/vm.py --as-lane main list`); das trifft die Allow-Regel
fuer `vm.py`, ein vorangestelltes `AH_LANE=…` trifft keine. Ein Worktree aus `worktree-setup.sh`
braucht das nicht: er hat seine `.vm/lane`.
`vm.py` und `scripts/vm/lib.sh` normalisieren sie identisch;
`scripts/tests/lib_vm_test.sh` vergleicht beide Seiten zeichenweise, weil eine Uneinigkeit
darueber, wessen VM eine VM ist, genau eine Lane zu viel abraeumen wuerde. Den Zustand im eigenen
`.vm` (Lane-Datei, `warm.env`) lesen `vm.py` und `lib.sh` (und mit ihnen `reap.sh`, `warm.sh`,
`iter.sh`) nur ungetrackt, mit oder ohne `--lane`/`AH_LANE`: trackt der Checkout Pfade unter
`.vm` oder antwortet git nicht, lehnen sie mit Exit 2 ab; ohne lesbares git braucht es ein
`AH_VM_STATE_DIR`, das nicht das eigene `.vm` ist. Jedes andere Verzeichnis als das eigene `.vm`
liest ohne diese Pruefung.

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
[--only <keys…>] [--step <name>] [--part gui|rest]` (schwere Layer verlangen `AH_ALLOW_REAL=1`;
`--only server web` begrenzt lint/unit auf die genannten Komponenten — gefilterte
Steps melden SKIP; `--part gui` faehrt nur die Desktop-GUI-Suiten samt Smoke-Test,
`--part rest` alle anderen Schritte, ohne SKIP fuer den anderen Teil).
`scripts/vm/iter.sh` reicht die Flags an die Box weiter.

- **Schneller Loop (warm once → iterieren → reapen).** Eine hydrierte Box ist teuer
  zu bauen (~18 min Bootstrap + ~20 min Tauri-Build), aber billig zu halten:
  `bash scripts/vm/warm.sh <desktop|gui|server|pond>` hydriert **einmal** und merkt die
  VMID und den Namen aus `clone` (`.vm/warm.env`); `gui` ist eine zweite volle Box derselben
  Lane mit eigenem Slot fuer den GUI-Teil des Sammellaufs. Wieder genommen wird der Slot
  nur, solange `vm.py list` auf der VMID eine laufende Box der eigenen Lane mit seiner
  Rolle, ohne Szenario und unter diesem Namen zeigt; einen Slot ohne Namen uebernimmt
  `warm.sh` einmal. Danach ist jede Iteration inkrementell (`target/` +
  `node_modules/` bleiben vom Sync ausgenommen) und dauert Minuten statt ~40:
  `bash scripts/vm/iter.sh <layer>` bzw. `iter.sh --desktop`; `iter.sh
  --cmd '<befehl>'` faehrt einen beliebigen Einzel-Befehl (z. B. ein Task-`Verify:`)
  auf der warmen Box. Ein vorangestelltes `--slot gui` (Layer-Form und `--cmd`) faehrt auf
  der Box des Slots `gui` statt `desktop`, mit deren Namen und Frist; mit `--desktop` gibt
  es kein `--slot`. `bash scripts/vm/reap.sh` raeumt die Warm-Boxen auf, mit
  `--role <desktop|server|gui>` nur diesen einen Slot samt seinen Eintraegen in `warm.env`
  (beim Server auch die Zugangsdaten); die anderen Slots bleiben stehen. Bei Fehler
  bleibt die Box stehen (`python3 scripts/vm/vm.py ssh <vmid>`) und Screenshots/Logs
  landen automatisch lokal unter `.ah-out/`.
- **Parallele Lanes.** Jedes Vorhaben baut in einem eigenen Git-Worktree
  `../AdminHelper-<slug>` (`git worktree add`, dann `bash scripts/dev/worktree-setup.sh
  <pfad> <slug>`: eigene Test-DB und `.devenv.sh`, Sidecar und Venv-Links,
  `node_modules` als Hardlinks, `.claude/settings.local.json` als **Kopie**, solange
  `~/.config/adminhelper/pve.env` fehlt). Jede Lane bekommt ihre **eigene Lane-Kennung**:
  das Setup schreibt den Slug nach `.vm/lane`, jede VM traegt den Tag `lane-<slug>`, und
  `reap`, der Auto-Sweep am Ende jedes Verbs und die Leak-Pruefung in `list` arbeiten
  auf der eigenen Lane — Reap einer Lane laesst die anderen stehen. `destroy` filtert
  ueber `--lane/--scenario/--role`; eine ausdruecklich genannte VMID wird zerstoert,
  geschuetzt ist dort nur, was kein `ah`-Tag traegt. Steht neben ihr ein Filter, muss sie
  zu ihm passen: `reap.sh` nennt die Warm-Slots mit `--lane` der eigenen Lane, ihrer Rolle
  (`--role`), `--no-scenario` und, wo `warm.sh` ihn gemerkt hat, mit `--expect-name` ihrem Namen,
  und `vm.py` lehnt einen Slot ab, dessen VM eine andere Lane oder Rolle oder ein Szenario traegt
  oder frisch (`status/current`) einen anderen Namen: `free_vmid` gibt eine freigewordene VMID
  dem naechsten Klon, ein Szenario least seinen Server zuerst. Klone werden seriell abgeschickt (ein
  Linked Clone dauert ~2 s). Aus einem Worktree reist `.git` nur als Zeiger mit, der
  auf der Box ins Leere zeigt. Die Box braucht kein Repo (Entscheidung Kevin,
  2026-09-25): Kopf und Tree-Hash gibt `iter.sh` vom Client mit, und diese Werte gehen
  vor dem `git` der Box, auch wenn der Sync aus dem Haupt-Checkout ein Repo mitbringt.
  Ein Test, der auf der Box `git` voraussetzt, gehoert deshalb nicht auf die Box.
  `worktree-teardown.sh <pfad> <slug>`
  zerstoert die VMs der Lane und raeumt Worktree, Test-DB, Venv und den gemergten Branch ab —
  auch dann, wenn der Worktree schon von Hand entfernt wurde.
  Ablauf eines Vorhabens im eigenen Worktree: `CLAUDE.md` §8.
- **Verteilt (Multi-Host).** `bash scripts/tests/multibox.sh --agents N [--desktop]`
  klont Server- + Agent-Box(en); mit `--desktop` zusaetzlich eine Box, die die
  echte Tauri-GUI headless gegen den **entfernten** Server faehrt (Login/CRUD/
  Monitoring) — Cross-Host-mTLS, echtes `.deb`, Monitoring ueber den Netz-Hop.
  `--capstone` ist die Release-Kombination (alle Szenarien plus `--enforce`).
  Unter der Summary nennt der Lauf die Go-Version, mit der die Server-Box das Agent-Binary
  der Pakete gebaut hat (`go version (agent .deb, server box): …`, aus dem Binary gelesen).
  Die Frist der Warm-Box kommt aus `AH_WARM_TTL` (Default 8h); `iter.sh` verlaengert bei
  jedem Lauf um genau diese Frist (warm.sh merkt sie je Slot als `desktop_ttl` bzw.
  `gui_ttl` in `.vm/warm.env`), eine bewusst kurze Box bleibt also kurz.

### Wochenlauf (heavy.sh)

Der schwere Tier laeuft nicht mehr „wenn man daran denkt", sondern als ein Lauf mit
Report und Historie. Kevin startet ihn von Hand in `tmux` oder mit `/test weekly`; die Ebene
`all` startet die Claude-Session ausserdem selbst als faelligen Sammellauf ueber `main`
(`/feature-build` §5, seit 2026-10-15). Die Session startet denselben tmux-Lauf, ueberwacht
ihn bis zum Report und meldet das Ergebnis samt VM-Liste (Regeln im `/test`-Skill):

```bash
tmux new -d -s ah-weekly 'bash scripts/tests/heavy.sh weekly'
```

```
bash scripts/tests/heavy.sh all|capstone|weekly [--base <sha>] [--no-second-vm] [--notify]
```

- `all` = `run.sh all --strict` auf **zwei Boxen gleichzeitig**: Teil `rest`
  (`--part rest`) auf der warmen Box des Slots `desktop`, Teil `gui` (`--part gui`, die
  Desktop-GUI-E2E samt Smoke-Test) auf einer zweiten Box derselben Lane (`warm.sh gui`,
  `iter.sh --slot gui`), die geleast wird, waehrend `rest` schon laeuft. `PASS` nur mit zwei
  gruenen Teilen: ein Teil, der nicht lief oder keinen Beleg brachte (weder Summary-Zeile noch
  Artefakt, oder ein Artefakt des anderen Teils), macht den Lauf UNVERIFIED, sonst macht ihn ein
  roter Teil FAIL; der Grund nennt den Teil (`… (gui)`) und einen roten anderen Teil
  (`FAIL in part rest`). Ein Abbruch von `heavy.sh` (INT/TERM/HUP) beendet beide Teile.
  Ist die zweite Box auch im zweiten Versuch nicht zu bekommen, laeuft Teil `gui` nach Teil
  `rest` seriell auf der Box des Slots `desktop` (`iter.sh all --strict --part gui`): ein
  laengerer Lauf statt eines verlorenen. Die Notizen sagen es mit der letzten Zeile aus
  `warm-gui.log`, die Ebenen-Zeile nennt zweimal dieselbe Box, eine GUI-Box gibt es nicht
  freizugeben, und das Urteil bleibt `PASS` nur mit zwei gruenen Teilen. Verweigert `warm.sh gui`
  (Exit 2), laeuft nichts seriell, der Lauf ist UNVERIFIED.
  Nach dem Lauf gibt `heavy.sh` die GUI-Box frei (`reap.sh --role gui`), wenn Teil `gui` gruen
  ist (ein `flaky` Schritt zaehlt nicht als rot); ist er rot oder `infra`, bleibt sie zur Sichtung
  stehen, bis ihre Frist ablaeuft, und die Notizen nennen `python3 scripts/vm/vm.py ssh <vmid>` —
  sofern sie nicht schon vor einer Zweit-VM oder dem Capstone ging (siehe Klassifikation).
  `capstone` = `multibox.sh --capstone --strict`; `weekly` = beides seriell, der Capstone
  bekommt die Box des Slots `desktop`. Der Capstone entfaellt **nur**, wenn die `all`-Ebene
  UNVERIFIED endete (sieben VMs brennen sonst in eine kaputte Umgebung) — ein reines FAIL
  stoppt ihn nicht.
- **Vorab:** `vm.py doctor --roles <was der Modus klont>` — bei `all` nur der Slot `desktop`,
  wenn seine Box nicht schon laeuft (sonst ein leeres `--roles`); ob die GUI-Box passt,
  entscheidet die Kapazitaetspruefung von `vm.py clone` —, und
  `vm.py list --json` darf keine
  Box einer fremden Lane und nichts Geleaktes auf der eigenen zeigen — sonst ist die
  Kapazitaet nicht da und der Lauf bricht ab, bevor er eine VM verbraucht.
- **Report:** `.ah-out/weekly/<jjjj-mm-tt-hhmm>/report.md`. Erste Zeile ist das Urteil
  (`PASS` | `FAIL` | `UNVERIFIED (<grund>)`), dann die Summary-Zeilen der Wrapper
  **woertlich** (bei `all` je Teil mit Etikett: `[rest] run.sh[all]: …`, `[gui] …`), die
  Schritt-Tabelle (alle Schritte beider Teile mit Sekunden und Box, dazu **eine** Ebenen-Zeile
  mit Wandzeit, `<box-rest>+<box-gui>` und `rest <s> s, gui <s> s`), „Kevin sichtet", die
  Notizen, die `audit.yml`-Zeile und die VM-Liste danach. Jeder Teil hat sein Log
  (`all-rest.log`, `all-gui.log`) und sein Zieh-Verzeichnis (`rest/`, `gui/`: Artefakt,
  Screenshots, Logs der Box); `steps-all.tsv` fuehrt die Schritte beider Teile, den Teil in der
  vierten Spalte. Nie eine Bewertung, nur Fakten. Dieselbe erste Zeile steht beim
  Session-Start in Zeile 4 des `AH-STATUS`-Blocks. Die `audit.yml`-Zeile erzeugt bei rot genau
  **eine** REL-Zeile je roter Phase: der Eintrag bleibt in `seen.md` offen (`deps-audit · open`),
  bis ein Lauf mit `success` ihn schliesst (`resolved`) — abgebrochene oder uebersprungene Laeufe
  aendern nichts. Eine neue Zeile gibt es erst beim naechsten roten Lauf nach einem gruenen, und
  auch dann nur, wenn die alte REL-Zeile nicht mehr offen ist: ihr Dedup-Key `rel:deps-audit`
  haelt die neue sonst zurueck. Roadmap-Zeilen legt `heavy.sh` ueber `roadmap.py add` an; ist
  die Zeile schon offen oder scheitert `add`, steht das laut in den Notizen des Reports.
- **JUnit:** Die pytest-Schritte von `run.sh` schreiben `.ah-out/junit/<schritt-id>.xml`
  (`monitoring-pytest`, `ca-issuer-pytest`, `server-pytest`, fuer Schemathesis eine Datei je
  Dienst: `schemathesis-server` usw.), `stack-pytest` je Test `stack-<name>.xml`, Playwright
  `web-playwright.xml` bzw. `web-live.xml` (nur mit gesetztem `AH_OUT_DIR`, sonst schriebe der
  Reporter auf stdout) und die Desktop-E2E je `wdio run` eine `desktop-e2e-<ms>-<cid>.xml`
  (`@wdio/junit-reporter`). Jeder `run.sh`-Lauf verwirft vorher die XMLs des
  letzten, und `heavy.sh` leert das `junit/` im Zieh-Verzeichnis jedes Teils vor dem Lauf: der
  Pull von der Box loescht nichts, eine alte Datei zaehlte sonst als heutige. `heavy.sh` kopiert
  das gezogene `junit/` beider Teile nach `.ah-out/weekly/<jjjj-mm-tt-hhmm>/junit/`; die
  Report-Zeile `JUnit:` nennt, wie viele XMLs dort liegen.
- **Historie:** `tasks/private/history.csv`
  (`datum,commit,tree_hash,ebene,schritt,ergebnis,sekunden,vm`). `heavy.sh` uebernimmt das
  Ergebnis eines Schritts woertlich aus `last-all.json` und klassifiziert nur die roten, es
  steht also auch `skip` in der Spalte — eine Zeile je Schritt (Spalte `vm` = Box seines
  Teils) plus eine Ebenen-Zeile (bei `all` mit `vm` = `<box-rest>+<box-gui>`),
  committet im privaten Repo, **nie** gepusht; Felder mit Komma oder Anfuehrungszeichen
  sind RFC-4180-gequotet. Auf der Box sind alle Schritte der schweren
  Layer Pflicht (Box-Regel, siehe „AH_REQUIRED"): ein `skip` wird dort unter `--strict` zum
  `strict-failed`, und die Ebene endet UNVERIFIED — `ergebnis` ∈
  `pass|skip|fail|flaky|infra|unbestaetigt|extern|reg` (`skip` nur ohne `--strict`).
- **Klassifikation.** `infra` gilt fuer die **ganze Ebene** (bei `all` fuer den ganzen Teil),
  nicht fuer einen Schritt: keine
  warme Box, Warm-Pond nicht bereit, fehlgeschlagenes Server-Lease, `vm.py: capacity` oder
  `privilege` (und auf der Ein-Box-Ebene zusaetzlich `vm.py: no ip|no ssh|timeout|sync failed|
  clone … failed`), `strict-failed: no step ran` oder Wrapper-Exit 74 beenden die Ebene bzw. den
  Teil sofort — er hat dann bewusst keine Zeilen in der
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
  bis zu drei Wiederholungen desselben Schritts auf derselben Box (`AH_NO_SYNC=1`; im Teil
  `gui` mit `iter.sh --slot gui`, nach einem seriellen Lauf auf der Box `desktop`) — ein
  gruener Lauf ⇒ `flaky`
  (Quarantaene in `tasks/private/seen.md`); dreimal identisch rot ⇒ eine frische zweite VM
  (Worktree `.ah-worktrees/w2`, Lane `w2`): dort gruen ⇒ `unbestaetigt`,
  dort rot ⇒ Gegenprobe auf dem letzten PASS-Commit — Basis gruen ⇒ `reg` (Roadmap-Zeile
  Klasse REG mit Dedup-Key `reg:<schritt>` plus `tasks/reg-<datum>-<schritt>.md`; `seen.md`
  sperrt denselben Fund 30 Tage, der Dedup-Key, solange seine Zeile offen ist), Basis ebenfalls
  rot ⇒ `extern`.
  Dreimal rot mit **unterschiedlichen** Markern ⇒ `fail` (reproduzierbar kaputt, aber ohne die
  stabile Signatur, die eine Regressions-Behauptung braucht — keine Zweit-VM).
  `--no-second-vm` ueberspringt die Zweit-VM, `--base <sha>` setzt den Vergleichs-Commit.
  Vor der ersten Zweit-VM und vor dem Capstone (`weekly`) gibt `heavy.sh` die GUI-Box seines
  Laufs frei (`reap.sh --role gui`, einmal je Lauf, die Notizen nennen es), weil neben ihr und
  der Box des Slots `desktop` die `w2`-Box bzw. die Capstone-Rollen nicht passen; die
  Zweit-VM-Pruefungen laufen deshalb erst, wenn beide Teile alle Wiederholungen hinter sich haben.
- **Exit-Codes:** `0` = PASS, `1` = FAIL, `74` = UNVERIFIED (Infrastruktur — der Lauf konnte
  nicht stattfinden, ueber den Code ist damit nichts bekannt), `2` = Usage. Als Infrastruktur
  zaehlen auch die Faelle, in denen die Wrapper nur `1` liefern: keine warme Box, Warm-Pond
  nicht bereit, fehlgeschlagenes Server-Lease, `strict-failed: no step ran`.
- **`--notify`** postet die Urteilszeile und den Report-Pfad an `AH_NOTIFY_URL` (aus
  `.devenv.sh`, gitignored); Default aus, ein fehlgeschlagener POST ist kein Fehler des Laufs.

**Keine offenen Vorbehalte mehr** (Stufe 3): **T7a** — `--capstone`
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
│  │  │  └─ modules/             # users, connections, servers, frp, hooks, api_keys, ansible,
│  │  │                          #   monitoring_proxy, audit, enrollment, notifications, provisioning
│  │  ├─ alembic/               # DB-Migrationen
│  │  └─ requirements.txt
│  ├─ monitoring/            # eigenständiger FastAPI-Microservice (eigene DB)
│  │  ├─ app/
│  │  │  ├─ checkers/            # agent, smart, http, ping, tcp, plugins, forecast
│  │  │  ├─ routers/             # admin, agent, alerts, checks, maintenance, templates
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
│  │  │  ├─ lib/api/             # client + Domain-Wrapper + types
│  │  │  ├─ lib/stores/          # Svelte-Stores
│  │  │  ├─ lib/i18n/            # DE/EN-Dictionaries
│  │  │  ├─ pages/               # Produktiv-Pages + Login + Placeholder
│  │  │  └─ modals/              # Modal-Komponenten
│  │  └─ tests/e2e/              # Playwright-E2E-Specs (*.spec.ts)
│  └─ desktop/               # Tauri Desktop-Client (Backend + UI zusammen)
│     ├─ src-tauri/          # Rust/Tauri-Backend
│     │  ├─ src/
│     │  │  ├─ main.rs            # invoke_handler mit allen Tauri-Commands
│     │  │  ├─ commands.rs        # IPC-Schnittstelle
│     │  │  ├─ auth.rs            # JWT-Login und -Abmeldung
│     │  │  ├─ session.rs         # Session im Speicher, ein Erneuerungsweg
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
│        │  ├─ lib/bridge/       # typisierte Tauri-IPC-Wrapper
│        │  ├─ lib/stores/       # Svelte-Stores
│        │  ├─ lib/models/       # connection, settings, ansible, monitoring (typisiert)
│        │  ├─ components/       # Svelte-Components
│        │  └─ pages/            # 5 Pages (Dashboard, Connections, Infrastructure, Ansible, Monitoring)
│        └─ vitest.setup.ts      # Vitest-Setup; die Unit-Tests liegen neben dem Code (src/**/*.test.ts)
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
