# CI: Archiv-Cache aufräumen, tauri-cli-Pins vollständig prüfen (ci-8)

Roadmap: R-1276, R-1277. Zurückgestellt in ci-9: R-1275 und R-1257 (Fragen an Kevin, siehe unten).

## Problem / Motivation

- **R-1276:** `.github/scripts/apt_archives_verify.sh` prüft nur die `*.deb` im Archiv-Cache. Alles andere, was ein
  wiederhergestellter Cache mitbringt, bleibt liegen: der Inhalt von `partial/`, Symlinks, Verzeichnisse, fremde
  Dateien. apt liest danach aus diesem Verzeichnis.
- **R-1277:** Der Lockstep-Schritt in `ci.yml` liest je Datei nur den ersten `cargo install tauri-cli` (`grep -m1`).
  `ci.yml` pinnt aber zweimal (tauri-build-smoke, rdp-embedded), `release.yml` zweimal; der Pin von rdp-embedded
  und der zweite in `release.yml` sind ungeprüft.

## Ziel & Nicht-Ziele

- Ziel: Das Archiv-Verzeichnis enthält vor `apt-get` nur noch reguläre `.deb`, deren SHA256 der signierte Index
  nennt, und ein leeres `partial/`. Jeder tauri-cli-Pin in `ci.yml` und `release.yml` nennt dieselbe Version, und
  jede Zeile mit `cargo install tauri-cli` nennt überhaupt eine.
- Nicht-Ziel: die Prüfung anderer Caches (R-1275, ci-9).

## Betroffene Komponenten & Dateien

- `.github/scripts/apt_archives_verify.sh`, `.github/scripts/apt_archives_verify_test.sh` (R-1276).
- `.github/workflows/ci.yml` Schritt mit dem tauri-cli-Lockstep (R-1277).
- Doku `docs/developer/cicd.html`, `docs/en/developer/cicd.html`; `changelog.d/ci-8.md`.

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

apt (`Dir::Cache::Archives`, `partial/` für laufende Downloads): unverändert genutzt.

## Trade-offs & Alternativen

- R-1276: `partial/` bleibt als leeres Verzeichnis stehen, weil apt es erwartet (`mkdir -p` im Workflow legt es
  ohnehin an). Ein Symlink namens `partial` wird gelöscht und als Verzeichnis neu angelegt.

## Risiken & Rollback

Ein zu gründliches Aufräumen kostet nur einen Download. Rollback: Revert.
Den Merge macht Kevin (`.github/workflows/`).

## Doku-Impact

`docs/developer/cicd.html` DE+EN: der Satz zu `apt_archives_verify.sh` und der zum tauri-cli-Pin. CHANGELOG über
`changelog.d/ci-8.md`.

## Offene Fragen (am Gate, Zeilen in ci-9)

- **R-1275 (Kevin):** Wie viel Laufzeit und Restrisiko darf die Prüfung anderer Caches kosten?
  - rust-cache kennt `cache-bin: "false"` (README v2.9.3). Dann baut `cargo install tauri-cli` in zwei Jobs je Lauf
    neu, das kostet Minuten.
  - Der Playwright-Cache ließe sich nur streichen, dann lädt jeder Lauf Chromium neu.
  - Das `target/` des rust-cache bliebe auch so ungeprüft.
- **R-1257 (Kevin):** Die Ursache liegt bei GitHub, nicht im Sammeljob. Empfehlung: die Zeile schließen.
  - In Lauf 42672778781 fehlt in Versuch 1 der Job „Server (pytest, image lock, shard 1/2)“ in der Jobliste: Er
    wurde nie angelegt.
  - Der Sammeljob wurde deshalb zu Recht rot. Versuch 2 startete den Shard, danach war der Lauf grün.
