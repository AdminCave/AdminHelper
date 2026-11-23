# ops-15 — Task-Ledger
Status: aktiv · Branch: feature/ops-15 · Review: pro Task
Spec: docs/features/ops-15.md (Roadmap R-1684, R-0592)
Heavy: linux-full — scripts/install.sh und scripts/update.sh (upgrade_path_test: letztes Release → Checkout); der Pin-Job in release.yml ist erst mit dem nächsten Tag real beweisbar
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1684: image-pins.sh nennt einen kaputten Digest nur nach Form  [x]
Komponente: scripts · Dateien: scripts/release/image-pins.sh, scripts/tests/image_pins_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ced9afcd9 2026-11-23T09:46:48+01:00
Review: approve (.ah-out/review/ops-15/T1.verdict.json)
Änderung: Die Meldung in `image-pins.sh:51` nennt Image, Version und die Länge des Wertes statt des Wertes selbst. Test 4 in `image_pins_test.sh` prüft zusätzlich, dass der Wert nicht in der Ausgabe steht.
Verify: bash scripts/dev/verify.sh scripts --strict -- image_pins_test
Doku: keine (Fehlermeldung des Release-Laufs)

### T2 — R-1684: release.yml löst die Image-Pins in einem eigenen Job auf  [ ]
Komponente: server · Dateien: .github/workflows/release.yml, apps/server/tests/test_release_images.py
Änderung: Neuer Job `image-pins` (`permissions: contents: read`, ohne Secrets) installiert buildx und cosign, ruft `image-pins.sh` und lädt `IMAGES` als Artefakt hoch; der Job `release` hängt von ihm ab, lädt das Artefakt nach `stage/IMAGES` und installiert weder buildx noch cosign für den Pin. `test_release_images.py` prüft die Struktur (eigener Job, keine `secrets.`, Artefakt-Übergabe, `needs`).
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_release_images.py
Doku: → T5

### T3 — R-1684: update.sh liest die Pins vor jeder Änderung, IMAGES bleibt nicht im Installationsverzeichnis  [ ]
Komponente: scripts · Dateien: scripts/update.sh, scripts/install.sh, scripts/tests/update_test.sh, scripts/tests/install_test.sh, scripts/tests/upgrade_path_test.sh
Änderung: `update.sh` liest `TARGET_IMAGES` einmal direkt nach `fetch_bundle`/der Übergabe, vor Backup und Tausch; der späte Aufruf bei `pin_images` fällt weg. `swap_runtime_files` tauscht `IMAGES` nicht ins Installationsverzeichnis, `install.sh` entfernt es wie `VERSION`; eine liegengebliebene Kopie aus ops-14 räumt `update.sh` weg. `upgrade_path_test` entscheidet die Digest-Pflicht am Inhalt des Bundles von `PREV`, nicht an der Kopie im Installationsverzeichnis. Tests: kaputte `IMAGES` bricht ab, bevor etwas geändert ist; nach Install und Update liegt kein `IMAGES` im Verzeichnis.
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test update_test
Doku: → T5

### T4 — R-0592: Arbeitskopien der .env mit zufälligem Namen und Aufräumen beim Abbruch  [ ]
Komponente: scripts · Dateien: scripts/update.sh, scripts/install.sh, scripts/tests/update_test.sh, scripts/tests/install_test.sh
Änderung: `upsert_env` (`update.sh:392`, `install.sh:641`) und die Rollbacks (`update.sh:891`, `:1057`) legen ihre Arbeitskopie per `mktemp .env.ah-XXXXXX` an und tragen sie in eine Aufräumliste ein, die der bestehende EXIT-Trap (`install.sh:48`, `update.sh:776`) mit abräumt; der feste Name `.env.ah-new` entfällt. Test 40 „append“ (`update_test.sh:1408-1417`) prüft Exit, Fehlermeldung und Rollback-Text einzeln, `bad` nennt die fehlende Bedingung (R-0592 d). Der rote Lauf bei parallelen Läufen (R-0592 c) wird mit zwei gleichzeitigen `update_test`-Läufen nachgestellt; der Befund steht unter `## Entscheidungen`, ein reproduzierbarer Fehler wird eine eigene Roadmap-Zeile.
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test update_test
Doku: keine (internes Verhalten der Skripte)

### T5 — R-1684, R-0592: Doku, Kopfkommentar uninstall.sh und CHANGELOG  [ ]
Komponente: scripts · Dateien: scripts/uninstall.sh, docs/admin/installation.html, docs/en/admin/installation.html, docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ops-15.md
Änderung: Kopfkommentar `uninstall.sh:11` und die Beispiel-Kommentare `installation.html:256`/`:260` (EN `:204`/`:208`) nennen `./repo`; der Satz zur Kopie von `IMAGES` (`installation.html:223`, EN `:176`) sagt, dass sie nicht mehr im Verzeichnis liegt; `cicd.html:590` DE+EN nennt den eigenen Pin-Job; Fragment `changelog.d/ops-15.md` (umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test uninstall_test
Doku: diese Task

## Entscheidungen
