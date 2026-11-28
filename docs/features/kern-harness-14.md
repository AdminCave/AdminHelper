<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-harness-14 — Box-Bootstrap mit Pins, OPNsense-Vorlage, Ledger-Feld

Roadmap: R-1364, R-1824, R-1803, R-1796, R-1800 (alle REF, Harness-Pfade auf Kevins Wort 2026-11-25/27).

## Problem
- **R-1800:** `scripts/vm/bootstrap_linux.sh` holt den Docker-Apt-Schlüssel, das nodesource-Setup-Skript und
  `sh.rustup.rs` nur über TLS. Go, Python, oasdiff und frpc sind per sha256 gepinnt, diese drei nicht: ein
  verändertes Skript oder ein fremder Schlüssel liefe ungeprüft als root bzw. als Box-Nutzer.
- **R-1796:** Python-, oasdiff-, Go- und frpc-Archiv landen unter festen Namen in `/tmp` statt in `mktemp`.
- **R-1803:** vier Nits aus kern-netretry-1: der Kommentar zu oasdiff (bootstrap_linux.sh) nennt den Bake-Warmlauf als
  Grund, den `WARMUP_EXCLUDE` inzwischen ausnimmt; der Kommentar an `WARMUP_EXCLUDE` (vm.py) verschweigt, dass die
  Vorlage nun ohne Python-Venv-Cache bleibt; `pip_install` schläft auch nach dem letzten Versuch; die Entscheidung im
  Ledger kern-netretry-1 nennt `apps/gateway/Dockerfile` nicht.
- **R-1824:** das Ledger-Feld `Assertion-Änderung:` hat seit dem Wegfall von diff-scan keinen Leser mehr; `ledger.sh
  lint` prüft es trotzdem, `tasks/README.md` beschreibt es nicht.
- **R-1364:** der shellcheck-Schritt in `scripts/tests/run.sh` erfasst `scripts/vm/opnsense/*.sh` nicht;
  `OPNSENSE_CHECK` (vm.py) ruft `sshd -T` über `PATH` und prüft so das Basis-sshd statt `/usr/local/sbin/sshd`;
  die Vorlage base-opnsense trägt die rc.conf-Zeilen aus base-freebsd weiter.

## Ziel & Nicht-Ziele
Ziel: jeder Download des Box-Bootstraps ist an einen Hash oder Schlüssel-Fingerprint gebunden und liegt in einer
eigenen Temp-Datei; die Nits sind behoben; das tote Feld ist weg; OPNsense-Check und -Vorlage prüfen bzw. tragen,
was sie sollen. Nicht-Ziel: andere Bezugsquellen für Docker oder Node, Änderungen an den Dockerfiles.

## Betroffene Komponenten & Dateien
`scripts/vm/bootstrap_linux.sh`, `scripts/vm/vm.py`, `scripts/vm/tests/test_vm.py`,
`scripts/tests/harness_consistency_test.sh`, `scripts/tests/run.sh`, `scripts/dev/ledger.sh`,
`scripts/tests/ledger_test.sh`, `DEVELOPMENT.md`, `changelog.d/kern-harness-14.md`.

## Externe Integrationen
- Docker: https://docs.docker.com/engine/install/ubuntu/ (Schlüssel `download.docker.com/linux/ubuntu/gpg`). Die Seite
  nennt keinen Fingerprint mehr; der Schlüssel trägt am 2026-11-27 `9DC858229FC7DD38854AE2D88D81803C0EBFCD88`.
- nodesource: `setup_26.x` legt `deb.nodesource.com/gpgkey/nodesource-repo.gpg.key` als Keyring ab und schreibt eine
  deb822-Quelle `https://deb.nodesource.com/node_26.x nodistro main` mit Apt-Pin auf den Ursprung (aus dem Skript
  gelesen, die README auf GitHub war nicht erreichbar). Schlüssel-Fingerprint am 2026-11-27
  `6F71F525282841EEDAF851B42F59B5F99B1BE0B4`.
- rustup: https://rust-lang.github.io/rustup/installation/other.html — `static.rust-lang.org/rustup/archive/<version>/
  <target>/rustup-init` mit `.sha256` daneben; aktuell 1.29.3.

## Trade-offs
- nodesource: (a) Setup-Skript per sha256 pinnen — bricht bei jeder Skript-Änderung den Bake; (b) Repo von Hand wie
  das Skript, Schlüssel per Fingerprint geprüft — gleiche Form wie Docker, Pakete bleiben apt-signiert; (c) Node-Tarball
  von nodejs.org mit gepinnter Version — wie Go, aber eine neue Patch-Pflege. Empfehlung (b); Kevins Wort am Gate.
- rustup-init als gepinntes Binary statt Skript: das Skript lädt selbst nur rustup-init, der Pin trifft also dasselbe.

## Risiken & Rollback
Ein falscher Pin lässt den Bootstrap hart scheitern (gewollt). Beweis vor dem Merge: eine frische Box aus der Vorlage
bootstrappt mit dem Stand (`warm.sh desktop`), dazu ein Bake von base-opnsense und eine Lease daraus (Kevin
2026-11-27). Rollback: Revert.

## Doku-Impact
`DEVELOPMENT.md` (Box-Bootstrap: Pins); keine Seite unter `docs/` beschreibt den Bootstrap. Changelog-Fragment.
