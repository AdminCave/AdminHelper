# kern-harness-7 — tauri-cli auf den Test-Boxen im Gleichschritt mit CI und Release

Roadmap: R-1294 (REF, Harness; Kevin 2026-11-11 Triage: Harness-Änderung auf Kevins Wort).

## Problem
- **R-1294**: `scripts/vm/bootstrap_linux.sh:24` setzt `TAURI_CLI_VERSION` auf `2.11.2`, `ci.yml` und `release.yml`
  installieren `tauri-cli` `2.12.4`. `.github/scripts/tauri_cli_pins.sh` hält nur die beiden Workflows zusammen, den
  Bootstrap prüft niemand. Box-Läufe bauen die Desktop-App damit mit einer anderen tauri-cli als CI und Release.
- Dazu installiert der Bootstrap tauri-cli nur, wenn `cargo tauri` ganz fehlt (`bootstrap_linux.sh:219`): eine Box
  mit älterer tauri-cli behielte sie auch nach dem Anheben des Pins.

## Ziel & Nicht-Ziele
- Ziel: der Bootstrap-Standard ist die Version der Workflows, und eine Prüfung, die in CI ohnehin läuft, wird rot,
  sobald beide auseinanderlaufen. Eine Box mit anderer tauri-cli installiert die gepinnte.
- Nicht-Ziel: `ci.yml` ändern (überlappt `feature/ci-9`, #464, und ist Kevins Merge). Deshalb prüft nicht
  `tauri_cli_pins.sh`, sondern `scripts/dev/toolchain-lockstep.sh`, das CI schon fährt und das die ruff-, Go- und
  oasdiff-Pins des Bootstraps bereits gegen `ci.yml` hält. Kein Neu-Backen der Vorlagen (Kevins Wort, `/vm bake`).

## Betroffene Komponenten & Dateien
- `scripts/vm/bootstrap_linux.sh` (Pin `2.12.4`; Installation, wenn `cargo tauri --version` nicht die gepinnte nennt)
- `scripts/dev/toolchain-lockstep.sh` (neue Prüfung 2c: jede `cargo install … tauri-cli … --version X` in `ci.yml`
  gleich dem Bootstrap-Standard)
- `scripts/tests/toolchain_lockstep_test.sh` (Fixture mit tauri-cli-Zeile, grüner Fall, Drift- und Fehlt-Fälle)
- `docs/developer/cicd.html`, `docs/en/developer/cicd.html` (ein Satz zum Lockstep)

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
`cargo tauri --version` gibt `tauri-cli X.Y.Z` aus (tauri-cli 2.x); nicht gegen eine Doku verifiziert, darum
vergleicht der Bootstrap nur auf Gleichheit und installiert bei jeder anderen Ausgabe neu.

## Trade-offs & Alternativen
- `tauri_cli_pins.sh` um den Bootstrap erweitern: braucht einen neuen Aufruf in `ci.yml` oder einen fest
  verdrahteten Pfad im Skript. Verworfen (Überlappung #464, Kevins Merge).
- Empfehlung: `toolchain-lockstep.sh`, das alle Bootstrap-Pins schon an `ci.yml` misst.

## Risiken & Rollback
Ein falsch gelesener Pin macht den CI-Schritt „Toolchain pins in lockstep“ rot (laut, kein stiller Schaden). Die
Neuinstallation kostet auf einer Box mit alter tauri-cli einmalig ~18 min Kompilierzeit. Rollback: Revert.

## Doku-Impact
`docs/developer/cicd.html` DE+EN: ein Halbsatz, dass auch der Bootstrap-Standard mitgeprüft wird. Kein CHANGELOG
(nur Harness, keine Wirkung für Nutzer).

## Offene Fragen
Keine.
