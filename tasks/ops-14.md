# ops-14 — Task-Ledger
Status: aktiv · Branch: feature/ops-14 · Review: am Ende
Spec: docs/features/ops-14.md (Roadmap R-0460)
Heavy: linux-full — scripts/install.sh und scripts/update.sh (upgrade_path_test: letztes Release → Checkout); der Digest-Pfad selbst ist erst mit dem nächsten Release-Bundle real beweisbar
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-0460: Release-Lauf schreibt die signierten Image-Digests ins Runtime-Bundle  [ ]
Komponente: scripts · Dateien: scripts/release/image-pins.sh, scripts/tests/image_pins_test.sh, .github/workflows/release.yml
Änderung: Neues `scripts/release/image-pins.sh <tag> <out>` (SPDX-Header): je Image wartet es auf `:X.Y.Z` auf ghcr, löst den Digest auf, prüft die cosign-Signatur (Identität `docker.yml@refs/tags/<tag>`) und schreibt `IMAGES` mit fünf Zeilen `KEY=ghcr.io/admincave/adminhelper/<image>:X.Y.Z@sha256:<hex>`. In `release.yml` ersetzt es den Schritt „Assert the tag images exist on ghcr“ und läuft vor „Build runtime bundle“ (cosign-Installer davor); `MANIFEST.sha256` nimmt `IMAGES` auf. Test mit gestubbtem `docker`/`cosign`: gültiger Lauf, fehlende Signatur, fehlendes Image, kaputter Digest → Exit ≠ 0 ohne `IMAGES`.
Verify: bash scripts/dev/verify.sh scripts --strict -- image_pins_test
Doku: → T3

### T2 — R-0460: install.sh und update.sh pinnen den Digest aus dem Bundle  [ ]
Komponente: scripts · Dateien: scripts/install.sh, scripts/update.sh, scripts/tests/install_test.sh, scripts/tests/update_test.sh
Änderung: Liegt `IMAGES` im geprüften Bundle, pinnen `install.sh --ref` (Pin-Block, `fetch_bundle_into`) und `update.sh` (`TARGET_IMAGES`) die fünf Zeilen daraus; ohne `IMAGES` wie bisher den Tag. Eine `IMAGES`, die nicht genau die fünf Schlüssel mit `ghcr.io/admincave/adminhelper/<image>:<Zielversion>@sha256:<64 hex>` trägt, bricht ab, bevor etwas geändert ist. `installed_version`/`installed_label` lesen `:X.Y.Z@sha256:…`. Tests für beide Skripte: Bundle mit und ohne `IMAGES`, kaputte `IMAGES`, Versionserkennung mit Digest-Pin; erst rot.
Verify: bash scripts/dev/verify.sh scripts --strict -- install_test update_test
Doku: → T3

### T3 — R-0460: Doku und CHANGELOG  [ ]
Komponente: scripts · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html, docs/admin/installation.html, docs/en/admin/installation.html, changelog.d/ops-14.md
Änderung: `cicd.html` DE+EN: `IMAGES` im Runtime-Bundle, Digest nur mit passender cosign-Signatur. `installation.html` DE+EN: Install und Update pinnen `:X.Y.Z@sha256:…` aus dem signierten Bundle, ältere Releases den Tag. Changelog-Fragment umlautfrei.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: diese Task
Task-Review: am Ende

## Entscheidungen
- 2026-11-21: Image-Zeilen wie heute fest auf ghcr überschrieben, jetzt mit Digest; keine Mirror-Funktion (Kevin).
- 2026-11-21: Kaputte `IMAGES` in einem signierten Bundle bricht ab (fail closed), fehlende `IMAGES` fällt auf den Tag zurück (ältere Releases).
