# Netz-Aussetzer und Haenger in Bake, Bootstrap und Images (kern-netretry-1)

Roadmap: R-1794, R-1795, R-1797, R-1798 · Kevin 2026-11-26 („Zwei Zuege, jetzt bauen“, „Nur bauen, keine Tests“)

## Problem / Motivation
- **R-1794:** `vm.py bake` waermt die Vorlage mit `run.sh unit` unter `WARMUP_LIMIT` (1800 s). Die Suite ist
  gewachsen; beide Bakes vom 2026-11-25 liefen mitten in der Server-Pytest-Suite in die Grenze. Weil die
  Python-Suiten vor Go, Cargo und npm laufen, blieben genau die teuren Caches (Rust-`target/`, `node_modules`)
  kalt.
- **R-1795, R-1797:** Downloads ohne Wiederholung: `pip3 install` (ruff, pytest), `apt-get`, rustup, das
  Docker-GPG und `cargo install` in `scripts/vm/bootstrap_linux.sh`; `apt-get`, `pip install` und `npm ci`
  in den Dockerfiles. Ein PyPI-Lese-Timeout brach am 2026-11-25 ein Bake ab, ein fehlender Index einen
  Docker-Build. Die Netzprobe vom 2026-11-26 zeigte den Netzweg der Boxen gleichauf mit der Dev-Box (MTU
  1492 auf beiden, 10/10 grosse Downloads vollstaendig): es sind seltene Aussetzer der Gegenseite, die
  Wiederholung ist der Ursachenfix.
- **R-1798:** Haenger statt Fehler: `rsync` in `vm.py` hat keine I/O-Grenze, die Bootstrap-curls keine
  Verbindungs- oder Stall-Grenze. Ein haengender Transfer blockiert den Sammellauf bis zur aeusseren Grenze.

## Ziel & Nicht-Ziele
- Ziel: ein einzelner Netz-Aussetzer bricht weder Bake, Lease, Bootstrap noch Image-Build ab; ein stehender
  Transfer endet nach Minuten mit Fehler statt zu haengen; das Aufwaermen baut die Caches statt Tests zu fahren.
- Nicht-Ziel: pauschales Anheben von Grenzen (die Inventur vom 2026-11-26 fand ausser `WARMUP_LIMIT` keine
  gerissene); Workflows (`release.yml`, `audit.yml`, `docker.yml`) — die faehrt Zug `ci-22` (R-1799).

## Betroffene Komponenten & Dateien
- `scripts/vm/vm.py` — Warm-Schritt in `bake_linux` (`run.sh unit --exclude` der reinen Testschritte),
  `rsync()` mit `--timeout`; Tests `scripts/vm/tests/test_vm.py`.
- `scripts/vm/bootstrap_linux.sh` — apt-Wiederholung als Konfigurationsdatei, pip-Wiederholung und -Timeout,
  curl mit `--retry-all-errors`, `--connect-timeout` und Stall-Grenze, `CARGO_NET_RETRY`.
- `Dockerfile`, `apps/ca-issuer/Dockerfile`, `apps/monitoring/Dockerfile`, `scripts/tests/xrdp-gfx/Dockerfile` —
  apt `Acquire::Retries`, pip `--retries`/`--timeout`, npm `--fetch-retries`.
- `scripts/tests/harness_consistency_test.sh` — Pruefung, dass jede curl im Bootstrap wiederholt und begrenzt ist
  und die Dockerfiles die Wiederholungs-Optionen tragen.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen (Doku gelesen 2026-11-26)
- pip General Options (pip.pypa.io/en/stable/cli/pip/): `--retries` „Maximum attempts to establish a new HTTP
  connection (default 5)“, `--timeout` Socket-Timeout (default 15 s), Env `PIP_RETRIES`, `PIP_DEFAULT_TIMEOUT`.
  `--retries` gilt dem Verbindungsaufbau, nicht einem Abbruch mitten im Download; dafuer bekommen die zwei
  Bootstrap-Installs eine aeussere Wiederholung. `--resume-retries` ist auf pip 24.0 der Boxen nicht verifiziert
  und wird nicht genutzt.
- npm config (docs.npmjs.com/cli/v10/using-npm/config): `fetch-retries` (default 2), `fetch-retry-maxtimeout`
  (default 60000); gesetzt in der dokumentierten Form `--fetch-retries 5`.
- apt.conf(5) bookworm: `Acquire::Retries` „retry failed files the given number of times“;
  apt-transport-http(1): `Acquire::http::Timeout` gilt Verbindung und Daten.
- rsync(1): `--timeout=SECONDS` „If no data is transferred for the specified time then rsync will exit“.
- curl(1): `--speed-limit`/`--speed-time` brechen einen stehenden Transfer ab; ob `--retry` diesen Abbruch
  (Exit 28) wiederholt, sagt die Seite nicht — daher `--retry-all-errors`, lokal mit einer Gegenprobe gezeigt.
- cargo config: `net.retry` (default 3), Env `CARGO_NET_RETRY`.

## Trade-offs & Alternativen
- Aufwaermen: `--exclude` der reinen Testschritte (`monitoring-pytest`, `ca-issuer-pytest`, `server-pytest`,
  `schemathesis`, `scripts`, `vm-pytest`, `dev-pytest`) statt eines eigenen Bau-Skripts. Die verbleibenden
  Schritte (Go, Cargo, desktop-ui, desktop-e2e, web) sind die, deren Kosten Kompilieren und `npm ci` sind; ein
  eigenes Skript wuerde die Bau-Befehle von `run.sh` doppeln und auseinanderlaufen. `run.sh` lehnt eine
  unbekannte Step-ID ab, ein umbenannter Schritt faellt also sofort auf. Die Python-Abhaengigkeiten der
  Services installiert der erste Lease (rund eine Minute). `WARMUP_LIMIT` bleibt 1800 s.
- curl-Stall-Grenze statt `--max-time`: eine Gesamtgrenze bricht langsame, aber laufende Downloads ab; die
  Stall-Grenze (unter 1 KiB/s fuer 60 s) nur stehende.

## Risiken & Rollback
- Dockerfiles sind Produkt: nur zusaetzliche Optionen, kein anderer Paketstand (`--require-hashes` bleibt).
- Revert je Task-Commit.

## Doku-Impact
DEVELOPMENT.md: die `bake`-Zeile der vm.py-Tabelle nennt das Aufwaermen ohne Testschritte; `changelog.d/kern-netretry-1.md`.

## Offene Fragen
Keine.
