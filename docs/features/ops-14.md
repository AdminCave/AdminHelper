# ops-14 — Eigen-Images per Digest aus dem signierten Bundle pinnen

Roadmap: R-0460.

## Problem / Motivation
`install.sh` (Zeilen 649–653) und `update.sh` (`TARGET_IMAGES`, Zeilen 1056–1059) pinnen die fünf eigenen Images
`server`, `gateway`, `ca-issuer`, `monitoring` und `frps` auf den Tag `ghcr.io/admincave/adminhelper/<image>:X.Y.Z`.
Ein Tag ist veränderbar: Wer in die Registry schreiben kann, kann unter demselben Tag ein anderes Image ablegen. Ein
Host zieht dann beim nächsten `docker compose pull` etwas anderes als das, was der Release-Lauf gebaut und mit cosign
signiert hat. Die Release-Dateien selbst sind seit Langem minisign-signiert (`SHA256SUMS.minisig`). Was der Host an
Images zieht, hängt aber bisher nicht an dieser Signatur. Fremd-Images wie postgres, redis und victoria-metrics sind
in `docker-compose.yml` schon per Digest gebunden.

## Ziel & Nicht-Ziele
- **Ziel:** Der Release-Lauf schreibt die Digests der fünf Images in das Runtime-Bundle, als Datei `IMAGES`, die in
  `MANIFEST.sha256` steht und damit unter der minisign-Signatur liegt. Den Digest übernimmt er nur, wenn die
  cosign-Signatur aus `docker.yml` für diesen Tag darauf passt. `install.sh --ref vX.Y.Z` und `update.sh` pinnen
  dann `ghcr.io/admincave/adminhelper/<image>:X.Y.Z@sha256:<digest>`.
- **Fallback:** Ein Bundle ohne `IMAGES` (Releases vor diesem Vorhaben, etwa beim Update auf eine alte Version) pinnt
  wie bisher den Tag. Ein Bundle mit kaputter `IMAGES` (falscher Schlüssel, fremdes Repo, Version passt nicht, kein
  Digest der Form `sha256:<64 hex>`) bricht ab, bevor etwas geändert wird: Ist die Datei da, gilt sie.
- **Image-Zeilen:** wie heute fest auf `ghcr.io/admincave/adminhelper/...` überschrieben (Kevin 2026-11-21). Eine
  eigene Registry oder ein Mirror wird nicht unterstützt (YAGNI).
- **Versionserkennung:** `installed_version`/`installed_label` in `update.sh` lesen die Version auch aus
  `…:X.Y.Z@sha256:…`.
- **Nicht-Ziele:** keine Änderung an `docker.yml`, an der cosign-Signatur, am `latest`-Tag oder an den Compose-Defaults
  (`:latest` bleibt der Fallback für ein nacktes `docker compose up`); kein Checkout-Modus mit Digests (ohne Bundle
  gibt es keine signierte Quelle).

## Betroffene Komponenten & Dateien
- `scripts/release/image-pins.sh` (neu): löst je Image den Digest von `:X.Y.Z` auf, prüft die cosign-Signatur mit der
  Identität `…/.github/workflows/docker.yml@refs/tags/vX.Y.Z` und schreibt `IMAGES`. Test
  `scripts/tests/image_pins_test.sh` mit gestubbtem `docker` und `cosign`.
- `.github/workflows/release.yml`: Der Schritt „Assert the tag images exist on ghcr“ (Zeile 599) wartet heute erst
  nach Bundle und Signatur auf die Images. Das Warten rückt vor „Build runtime bundle“ (Zeile 415), cosign wird
  installiert, `image-pins.sh` schreibt `stage/IMAGES`, und `MANIFEST.sha256` nimmt die Datei auf.
- `scripts/install.sh`: `fetch_bundle_into` (Zeile ~150) hebt `IMAGES` auf; der Pin-Block (Zeilen 641–654) nimmt sie.
- `scripts/update.sh`: `TARGET_IMAGES` aus `${EXTRACT}/IMAGES`; `installed_version`/`installed_label` (Zeilen
  399–421); die Log-Zeile von `pin_images`.
- Tests `scripts/tests/install_test.sh`, `scripts/tests/update_test.sh`.
- Doku: `docs/developer/cicd.html` + `docs/en/developer/cicd.html` (Signatur-Abschnitt), `docs/admin/installation.html` +
  `docs/en/admin/installation.html` (Pins von Install und Update), `changelog.d/ops-14.md`.

## Datenmodell / API / Migrationen
Keine Migration. Neu ist das Bundle-Format: die Datei `IMAGES` mit genau fünf Zeilen `KEY=ghcr.io/admincave/adminhelper/
<image>:X.Y.Z@sha256:<64 hex>` (KEY ∈ `SERVER_IMAGE GATEWAY_IMAGE FRPS_IMAGE CA_ISSUER_IMAGE MONITORING_IMAGE`). Alte
Skripte ignorieren sie (sie liest niemand), neue Skripte kommen mit alten Bundles aus (Fallback).

## Externe Integrationen
- Docker-Referenzen `name:tag@digest`: Docker und Compose nehmen Tag und Digest zusammen und ziehen per Digest
  (Docker-Doku „docker image pull“, Abschnitt „Pull an image by digest“). Vor dem Bau lokal mit `docker pull` geprüft.
- cosign 3 `verify` mit `--certificate-identity` und `--certificate-oidc-issuer`, wie schon in `docker.yml`.

## Trade-offs & Alternativen
- **Digest im Release-Lauf auflösen** statt auf dem Host: Nur so liegt er unter der minisign-Signatur. Auf dem Host
  aufgelöst, hinge er wieder am veränderbaren Tag.
- **Eigenes Skript statt Inline-YAML:** testbar ohne Release-Lauf; `release.yml` ruft es nur auf.
- **cosign-Prüfung vor dem Schreiben:** Der Digest könnte zwischen Push und Release-Lauf getauscht werden; mit der
  Prüfung landet nur ein Digest im Bundle, den `docker.yml` für diesen Tag signiert hat.

## Risiken & Rollback
- **Release-Lauf:** Ein Fehler in `image-pins.sh` macht `release.yml` rot, es entsteht kein Draft. Der Lauf ist erst
  mit dem nächsten Tag real bewiesen; bis dahin nur die Tests mit Stubs.
- **Update:** Das `update.sh` der alten Installation holt das Bundle des Ziels und übergibt (`AH_UPDATE_REEXECED`) an
  das `update.sh` daraus; dieses prüft das Bundle erneut und pinnt schon beim ersten Lauf den Digest. Das neue
  `update.sh` muss alte und neue Bundles lesen (Fallback).
- **Versionserkennung:** Ein falsch gelesener Pin hieße „unknown“ und damit jedes Update als Downgrade-Frage; Tests
  decken `:X.Y.Z@sha256:` ab.
- **Rollback:** Revert des PR; Hosts mit Digest-Pins laufen weiter (die Referenz ist gültig), ein späteres altes
  `update.sh` überschreibt sie mit dem Tag.

## Doku-Impact
`cicd.html` DE+EN (Signatur und Release-Assets: `IMAGES` im Bundle, cosign-Prüfung im Release-Lauf), `installation.html` DE+EN
(Install und Update pinnen mit Digest), CHANGELOG-Fragment.

## Offene Fragen
Keine. Kevin 2026-11-21: Zug ops-14, Kevin merged; Image-Zeilen wie heute fest auf ghcr, mit Digest.
