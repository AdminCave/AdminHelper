---
paths:
  - "apps/desktop/src-tauri/tauri.conf.json"
  - "apps/desktop/src-tauri/Cargo.toml"
  - "apps/desktop/src-tauri/Cargo.lock"
  - ".github/workflows/release.yml"
  - ".github/workflows/docker.yml"
  - ".github/workflows/ci.yml"
  - "docker-compose.yml"
  - "scripts/install.sh"
  - "scripts/update.sh"
---

# Release-Regeln

<!-- Stufe 0 · Quelle: Memory version_locations (rekonstruiert 2026-07-13), release-process, release-testing-depth -->

**Kevin taggt, pusht und publiziert.** Claude bereitet vor, prüft und nennt die Befehle.

## Vor dem Tag: drei Ebenen real grün

`bash scripts/tests/run.sh quick` auf der Dev-Box · `run.sh all` auf einer VM · Multibox-Capstone
(`scripts/tests/multibox.sh --capstone --strict`; `--strict` verlangt den vollen Flag-Satz, den `--capstone` setzt).
Rot oder übersprungen heißt: nicht taggen. Seit Stufe 3 melden die sechs bedingten Guards (debian:9,
Agent-Repo/CA-Flip ohne `REPO_FP`, Desktop-Lease, moncheck-Lease, `--enforce`, Monitoring-Hop) über
`skipped()`; **`0 failed, 0 skipped`** heißt damit „jede angeforderte Prüfung lief". Ein fehlgeschlagenes Lease
(Agent, Tunnel, Visitor, RPM, moncheck) lässt seine Folgeprüfungen weiterhin ohne SKIP ausfallen — dort ist der
begleitende FAIL die Evidenz. `--capstone` schließt `--enforce` ein.
**T7a (umgesetzt, aber unverifiziert):** weil `--capstone` das Gateway auf `ssl_verify_client on` stellt,
enrollt die Desktop-Etappe seit Stufe 3 vor jedem Spec eine Geräte-Identität über die certlose Ebene :8444.
Die Einmal-Tokens mintet der Orchestrator kurz vor der Etappe, eines je Spec. Ob das trägt, zeigt erst der
erste echte Capstone-Lauf.
Die Evidenz liefert `/test weekly`.

## Bump-Commit `chore(release): bump version to X.Y.Z` — synchron ändern

**Vor dem Tag prüfen, nicht durchzählen:** `bash scripts/release/check-versions.sh X.Y.Z` druckt je Stelle
`ok`/`MISSING` und endet mit 1, wenn eine fehlt. `release.yml` ruft dasselbe Skript auf dem Tag auf — was hier
rot ist, bricht dort den Draft ab.

1. `apps/desktop/src-tauri/tauri.conf.json` `"version"` — Release-Gate: muss exakt dem Tag entsprechen, sonst bricht
   `release.yml` ab.
2. `apps/desktop/src-tauri/Cargo.toml` `version`.
3. `apps/desktop/src-tauri/Cargo.lock` — nach dem Bump `cargo check -q` laufen lassen, sonst wird `--locked` im CI rot.
4. `CHANGELOG.md` — zuerst `python3 scripts/release/changelog-assemble.py` (faltet `changelog.d/*.md` in
   `## [Unreleased]` und löscht die Fragmente; `check-versions.sh` meldet ein übrig gebliebenes), dann wird
   `## [Unreleased]` zum neuen Abschnitt `## [X.Y.Z] - YYYY-MM-DD` und darüber ein leeres `## [Unreleased]`.
5. Doku-Sidebar-Footer (**38** HTML-Dateien, DE + EN) — auf die Klasse filtern, nicht auf das
   einzeilige Markup: `docs/index.html` und `docs/en/index.html` schreiben den Footer über zwei
   Zeilen und hingen deshalb von 0.43.2 bis 0.45.0 fest:
   `grep -rl 'class="sidebar-footer"' docs --include='*.html' | xargs sed -i 's|<span>vALT</span>|<span>vNEU</span>|'`
6. News-Callouts in `docs/index.html` + `docs/en/index.html` („Was ist neu in X.Y.Z?" / "What's new in X.Y.Z?").

**Aus dem Tag abgeleitet, nicht anfassen:** Agent (`release.yml` `VERSION=${GITHUB_REF_NAME#v}`; `build-deb.sh` /
`build-rpm.sh` brechen ohne `VERSION` ab), Server/Monitoring/Gateway/CA-Issuer (Docker-Build-Arg).
**Bewusst versionsunabhängig:** Install-Snippets in `README.md` und `docs/*/admin/installation.html` zeigen auf
`main/scripts/install.sh` (löst `releases/latest` selbst auf, minisign-verifiziert, fail-closed); `apps/desktop/ui/package.json`
bleibt auf 0.38.0.
**Separat gepinnt:** `FRP_VERSION` an vier Stellen (`ci.yml`, `release.yml`, `docker-compose.yml`,
`scripts/vm/bootstrap_linux.sh`) — der CI-Job `frp-consistency` prüft Gleichstand.

## Signatur

Docker-Images schlüssellos via cosign (GitHub-OIDC). `SHA256SUMS` via minisign: das Secret `MINISIGN_SECRET_KEY` ist die
**base64-Form** des Key-Files (`base64 -w0 minisign.key`); ein roher, mehrzeiliger Key wird verstümmelt
(`base64 conversion failed`). Der Public Key steht als `MINISIGN_PUBKEY` in `scripts/install.sh` **und**
`scripts/update.sh` — synchron halten, beide verifizieren fail-closed. Anleitung inkl. `cosign verify`:
`docs/developer/cicd.html` „Release-Signatur".

## Ablauf und Kanäle

Bump-Commit → Kevin: `git push origin main` → annotierter Tag `vX.Y.Z` → Tag pushen → alle Workflows per `gh run watch`
bis grün begleiten → Draft prüfen → Kevin publiziert als Beta. Drafts sind Konvention.
Kanäle (Kevin 2026-10-20): `beta` ist der Tag `vX.Y.Z` ohne Suffix, fortlaufend nach grünem Wochenlauf, veröffentlicht
als „Pre-release“ (`gh release edit vX.Y.Z --draft=false --prerelease`). `stable` ist kein eigener Schnitt und kein RC
mehr, sondern dasselbe Release auf „Latest“ (`gh release edit vX.Y.Z --prerelease=false --latest`), ohne neuen Tag. Den
Wechsel entscheidet Kevin, frühestens 7 Tage nach der Veröffentlichung als Pre-release ohne Fix und ohne Rückmeldung;
ein Fix ist ein neues Patch-Release, `hotfix` der einzige Bypass. Tags tragen kein Suffix (`-beta.N`, `-rc.N`), weil die
Pipeline solche Tags heute nicht richtig baut: tauri lehnt fürs MSI eine nicht numerische Prerelease-Kennung ab, eine
RPM-Version darf kein `-` tragen, und `dpkg` sortiert `0.46.0-beta.1` über `0.46.0`. `release.yml` legt den Draft als
Pre-release an, „Publish“ in der Web-Oberfläche macht ein Beta also nie zu „Latest“. `docker.yml` taggt beim Tag-Push
`:X.Y.Z` und `:sha-…`, aber kein `:latest`: das kommt erst mit Stable, wenn das Release von Pre-release auf Release
wechselt oder direkt als Release erscheint (Event `release`, Typ `released`). Dann taggt der Job `latest` das schon
gebaute `:X.Y.Z` um, ohne neu zu bauen und ohne neu zu signieren (die Signatur des Tag-Pushs hängt am Digest), aber
nur, wenn dieses Release `releases/latest` ist und `cosign verify` an jedem Image die Signatur seines Tag-Pushs
findet; scheitert er nach dem ersten Umtaggen, den Job erneut ausführen. Er läuft aus dem `docker.yml` des getaggten
Commits. `:latest` ist damit Stable, wie `releases/latest`, das `install.sh` ohne lokalen Checkout und `update.sh`
lesen. Ein halb geschnittenes Release (Bump ohne Tag, Tag ohne Publish, `main` vor `origin`) ist ein Warn-Trigger, kein
Normalzustand.
