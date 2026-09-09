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

<!-- Stufe 0 · Quelle: Memory version_locations (rekonstruiert 2026-07-13), release-process, release-testing-depth · Roadmap Stufe 13 -->

**Kevin taggt, pusht und publiziert.** Claude bereitet vor, prüft und nennt die Befehle.

## Vor dem Tag: drei Ebenen real grün

`bash scripts/tests/run.sh quick` auf der Dev-Box · `run.sh all` auf einer VM · Multibox-Capstone
(`crabbox_multibox.sh --agents 2 --desktop`). Rot oder übersprungen heißt: nicht taggen. Ab Stufe 3 liefert
`/test weekly` die Evidenz, ab Stufe 13 prüft `release.sh check` sie mechanisch.

## Bump-Commit `chore(release): bump version to X.Y.Z` — synchron ändern

1. `apps/desktop/src-tauri/tauri.conf.json` `"version"` — Release-Gate: muss exakt dem Tag entsprechen, sonst bricht
   `release.yml` ab.
2. `apps/desktop/src-tauri/Cargo.toml` `version`.
3. `apps/desktop/src-tauri/Cargo.lock` — nach dem Bump `cargo check -q` laufen lassen, sonst wird `--locked` im CI rot.
4. `CHANGELOG.md` — neuer Abschnitt `## [X.Y.Z] - YYYY-MM-DD`.
5. Doku-Sidebar-Footer (36 HTML-Dateien, DE + EN):
   `grep -rl '<div class="sidebar-footer"><span>v' docs --include='*.html' | xargs sed -i 's|<span>vALT</span>|<span>vNEU</span>|'`
6. News-Callouts in `docs/index.html` + `docs/en/index.html` („Was ist neu in X.Y.Z?" / "What's new in X.Y.Z?").

**Aus dem Tag abgeleitet, nicht anfassen:** Agent (`release.yml` `VERSION=${GITHUB_REF_NAME#v}`; `build-deb.sh` /
`build-rpm.sh` brechen ohne `VERSION` ab), Server/Monitoring/Gateway/CA-Issuer (Docker-Build-Arg).
**Bewusst versionsunabhängig:** Install-Snippets in `README.md` und `docs/*/admin/installation.html` zeigen auf
`main/scripts/install.sh` (löst `releases/latest` selbst auf, minisign-verifiziert, fail-closed); `apps/desktop/ui/package.json`
bleibt auf 0.38.0.
**Separat gepinnt:** `FRP_VERSION` an vier Stellen (`ci.yml`, `release.yml`, `docker-compose.yml`,
`scripts/tests/crabbox_bootstrap.sh`) — der CI-Job `frp-consistency` prüft Gleichstand.

## Signatur

Docker-Images schlüssellos via cosign (GitHub-OIDC). `SHA256SUMS` via minisign: das Secret `MINISIGN_SECRET_KEY` ist die
**base64-Form** des Key-Files (`base64 -w0 minisign.key`); ein roher, mehrzeiliger Key wird verstümmelt
(`base64 conversion failed`). Der Public Key steht als `MINISIGN_PUBKEY` in `scripts/install.sh` **und**
`scripts/update.sh` — synchron halten, beide verifizieren fail-closed. Anleitung inkl. `cosign verify`:
`docs/developer/cicd.html` „Release-Signatur".

## Ablauf und Kanäle

Bump-Commit → Kevin: `git push origin main` → annotierter Tag `vX.Y.Z` → Tag pushen → alle Workflows per `gh run watch`
bis grün begleiten → Draft prüfen → Kevin publiziert (`gh release edit vX.Y.Z --draft=false`). Drafts sind Konvention.
Kanäle: `beta` (`vX.Y.Z-beta.N`, fortlaufend nach grünem Wochenlauf) → `rc` (`vX.Y.Z-rc.N`, Kevin entscheidet) →
`stable` (frühestens 7 Tage nach dem RC ohne Fix und ohne Rückmeldung); `hotfix` ist der einzige Bypass. Prerelease-Tags
landen nie auf `latest` (`docker.yml`) und nie in `releases/latest` (`install.sh`/`update.sh`). Ein halb geschnittenes
Release (Bump ohne Tag, Tag ohne Publish, `main` vor `origin`) ist ein Warn-Trigger, kein Normalzustand.
