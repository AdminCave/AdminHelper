<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ci-3 — Shard-Abgleich, ci-2-Nits, Actions und Runner aktuell

Zug `tasks/ci-3.md` mit R-1019, R-1020, R-1042 und R-1085. Kein offener Branch ändert die Workflows,
`apps/server/tests/conftest.py` oder `docs/developer/cicd.html` (`overlap.sh`, 2026-11-03). Den PR merged Kevin,
denn er ändert `.github/workflows/` (CLAUDE.md §2).

## Problem / Motivation

- **R-1019 (REF):** Die Server-Suite läuft je Python-Leg in zwei Shards (`--shard K/N`,
  `apps/server/tests/conftest.py:527`). Jeder Shard sammelt die ganze Suite und behält seinen Teil. Ob beide Shards
  einer Leg dieselbe Sammlung gesehen haben, prüft niemand. Ein Unterschied wäre etwa ein Importfehler nur auf einer
  Seite oder eine Sammlung, die von der Umgebung abhängt. Dann fiele eine Testdatei in keinen Shard, und beide
  Shards wären trotzdem grün.
- **R-1020 (REF):** Drei Nits aus dem Branch-Review von ci-2:
  - Der Job `server-result` (`.github/workflows/ci.yml:133`) ist eine Matrix ohne `fail-fast: false`. Ist eine Leg
    rot, bricht GitHub die andere ab, und sie zeigt `cancelled` statt `failure`.
  - Kein Test prüft, dass `--shard` erst nach `-m`/`-k` teilt (`trylast`, `conftest.py:527`).
  - In `docs/en/developer/cicd.html:40` stehen zwei Klammern hintereinander („… image lock</code>) (jobs …“).
- **R-1042 (REF, Kevin 2026-11-02: alles auf aktuelle LTS/Stable):** Die Workflows pinnen ältere Majors, jeweils
  per SHA. Stand der GitHub-Releases am 2026-11-03 (`gh api repos/<r>/releases/latest`, SHA über
  `repos/<r>/commits/<tag>`):

  | Action | heute | aktuell |
  |---|---|---|
  | actions/checkout | v6 | v7.0.1 |
  | actions/setup-go | v6 | v7.0.0 |
  | actions/setup-node | v6 | v7.1.0 |
  | actions/setup-python | v6 | v7.1.0 |
  | actions/upload-artifact | v7 | v7.0.2 |
  | actions/download-artifact | v8 | v8.0.2 |
  | docker/build-push-action | v7.2.0 | v7.4.0 |
  | docker/login-action | v4.2.0 | v4.7.0 |
  | docker/metadata-action | v6.1.0 | v6.2.0 |
  | docker/setup-buildx-action | v4.1.0 | v4.4.1 |
  | sigstore/cosign-installer | v3.9.2 | v4.1.2 (cosign 3) |
  | softprops/action-gh-release | v3.0.0 | v3.0.3 |
  | Swatinem/rust-cache | v2 (SHA e18b4977) | v2.9.3 |

  `dtolnay/rust-toolchain@…# stable` bleibt: der Pin ist ein Branch-Stand, kein Release. Alle Jobs laufen auf
  `ubuntu-latest`, das heute noch 24.04 ist; `ubuntu-26.04` gibt es als Runner-Label (actions/runner-images
  README, 2026-11-03).
- **R-1085 (REF):** `cargo install tauri-cli --version "2.11.2"` (`ci.yml:734`, `release.yml:59`,
  `release.yml:261`) hängt eine Minor hinter der tauri-Crate (`Cargo.lock`: 2.12.5). Aktuell ist tauri-cli 2.12.4
  (crates.io, 2026-11-03).

## Ziel & Nicht-Ziele

Ziel:
- Jeder Shard schreibt eine Kennung seiner Sammlung, und der Ergebnis-Job einer Leg ist rot, wenn die Kennungen
  der Shards abweichen.
- Die drei Nits sind behoben.
- Alle Actions laufen auf dem aktuellen Release, per SHA gepinnt, mit Versionskommentar.
- CI läuft auf `ubuntu-26.04`.
- tauri-cli steht in CI und Release auf 2.12.4.

Nicht-Ziele:
- `windows-latest` bleibt (nicht Teil der Zeile).
- Den Pin `TAURI_CLI_VERSION` in `scripts/vm/bootstrap_linux.sh:24` (2.11.2) ändert ci-3 nicht. Er ist ein
  Harness-Pfad (CLAUDE.md §4) und wird eine eigene Roadmap-Zeile, Status `zurückgestellt`.
- Python-, npm- und ruff-Updates gehören zu kern-deps-2 und kern-deps-3.

## Betroffene Komponenten & Dateien

- `apps/server/tests/conftest.py`
- `apps/server/tests/test_shard.py`
- `apps/server/tests/test_ci_shards.py`
- `.github/workflows/ci.yml`, `release.yml`, `docker.yml`, `audit.yml`
- `docs/developer/cicd.html` und `docs/en/developer/cicd.html`
- `changelog.d/ci-3.md`

## Datenmodell / API / Migrationen

Keine. Neu ist nur eine pytest-Option, `--shard-manifest <pfad>`. Sie wirkt nur zusammen mit `--shard`. In die
Datei schreibt pytest:
- die Zahl der Tests nach `-m`/`-k` und vor der Teilung,
- den SHA-256 ihrer sortierten Node-IDs,
- K/N.

## Externe Integrationen

- GitHub-Actions-Releases über `gh api` (Tabelle oben). Bei den Majors haben die Release-Notes keinen Bruch für
  unsere Eingaben gezeigt:
  - checkout v7, setup-go v7: Abhängigkeits-Updates.
  - setup-node v7: ESM, und der Dummy-Export von `NODE_AUTH_TOKEN` entfällt (wir nutzen ihn nicht).
  - setup-python v7: Eingabe `pip-install` entfernt (wir nutzen sie nicht), EOL-Pythons entfernt.
- Python 3.14 und 3.15 gibt es für `ubuntu-26.04` (actions/python-versions `versions-manifest.json`:
  3.15.2 für 22.04, 24.04 und 26.04).
- cosign-installer v4.0.0, Release-Notes: v4 ist nötig für cosign 3. Unter cosign 3 braucht `sign-blob` den Schalter
  `--bundle`. Das Sigstore-Blog (blog.sigstore.dev/cosign-3-0-available) sagt dazu: `--new-bundle-format`,
  `--trusted-root` und `--use-signing-config` sind ab v3 Standard und lassen sich abschalten. Wir rufen
  `cosign sign` auf ein Image (`docker.yml:115`) und `cosign verify` (`docker.yml:172`) auf; `sign-blob` nicht.
  **Nicht verifiziert:**
  - wo cosign 3 die Signatur eines Images im neuen Format ablegt,
  - ob ein Nutzer mit cosign 2.x sie mit der dokumentierten Zeile prüfen kann (`docs/developer/cicd.html`, Abschnitt
    Signaturen: `cosign verify ghcr.io/admincave/adminhelper/server --certificate-identity-regexp …`).

## Trade-offs & Alternativen

- **Shard-Abgleich.** Gewählt: eine Manifest-Datei je Shard als Artefakt. Der Ergebnis-Job der Leg lädt beide
  Dateien und vergleicht Zahl und Hash.
  - Alternative 1: `--collect-only` in einem eigenen Job zählen. Das kostet einen dritten Postgres-Lauf und
    vergleicht trotzdem nicht die Sammlung der Shards selbst.
  - Alternative 2: Job-Outputs. Bei Matrix-Jobs überschreibt die letzte Leg die Outputs der anderen.
- **Runner für Release-Builds.** Ein Desktop-Binary, das auf 26.04 gebaut ist, verlangt die glibc von 26.04 und
  liefe auf 24.04 oder Debian 12 nicht mehr. Empfehlung: `release.yml` Job `desktop-linux` ausdrücklich auf
  `ubuntu-24.04` setzen, statt ihn mit `ubuntu-latest` still wandern zu lassen. Damit bleibt das sichtbare Verhalten
  gleich. Alle übrigen Jobs gehen auf `ubuntu-26.04`. Der Agent ist statisch gebaut (`CGO_ENABLED=0`) und daher
  unabhängig.
- **cosign 3 oder 2.x.** Dazu die offene Frage unten. Die Task T5 wartet auf `[?]`, der Zug fährt ohne sie.

## Risiken & Rollback

- `release.yml` läuft nur auf einem Tag, `docker.yml` signiert bei jedem Push auf `main` und verifiziert nur bei
  `released`. Ein Bruch dort zeigt sich erst beim Merge oder beim nächsten Release. Abhilfe:
  - die Release-Jobs vor dem Tag einmal per `workflow_dispatch` auf dem Branch starten (Kevins Wort, die Jobs fragen
    `startsWith(github.ref, 'refs/tags/')`, und Teile laufen dann nicht),
  - beim Merge den `docker.yml`-Lauf auf `main` beobachten.
- Ein 26.04-Runner kann andere apt-Paketnamen tragen (Tauri-Systempakete). Die PR-CI zeigt das sofort.
- Rollback: jede Task ist ein eigener Commit, Revert genügt.

## Doku-Impact

`docs/developer/cicd.html` DE+EN: den Shard-Abgleich beschreiben, den Runner nennen, und die EN-Klammern
beheben. Bei cosign 3 kommt der Abschnitt Signaturen dazu. Dazu ein Eintrag in `changelog.d/ci-3.md`
(`### Changed`).

## Offene Fragen

1. **cosign 3 (T5):** cosign-installer v4 mit cosign 3 (neues Bundle-Format, die Doku nennt die nötige cosign-Version
   zum Prüfen) oder v4 mit `cosign-release: v2.6.x` (Format wie heute)?
   - Empfehlung: cosign 3. Kevin hat „aktuell“ diktiert, und der Job `latest` prüft jede Signatur vor dem Umsetzen
     von `:latest` mit derselben Version.
   - Trade-off: Nutzer mit cosign 2.x prüfen künftig womöglich nicht mehr mit der dokumentierten Zeile (nicht
     verifiziert).
