# cosign 3 für die Image-Signaturen — Task-Ledger
Status: bereit · Branch: feature/ci-4 · Review: am Ende
Spec: docs/features/ci-4.md (Roadmap R-1119)
Heavy: none — nur `docker.yml` und Doku; der Workflow läuft erst nach dem Merge auf `main` (ein Branch-Lauf würde Images veröffentlichen), die Session beobachtet ihn (Spec, Risiken)
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — docker.yml: cosign-installer v4.1.3 und Verify nach dem Signieren (R-1119)  [x]
Komponente: scripts · Dateien: .github/workflows/docker.yml
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @c649b87aa 2026-11-06T18:31:43+01:00
Review: am Ende (Branch-Review)
Änderung: Beide Schritte „Install cosign“ (Jobs `build` und `latest`) auf `sigstore/cosign-installer@756fe2d284c7292c4e9b62c8a28f1e5629c59532 # v4.1.3` (cosign v3.1.4). Im Job `build` prüft nach „Sign the image (keyless)“ ein `cosign verify` die frische Signatur gegen die Identität dieses Laufs (`https://github.com/${GITHUB_REPOSITORY}/.github/workflows/docker.yml@${GITHUB_REF}`, Issuer GitHub-OIDC); der Kommentar über dem Signieren nennt das Bundle-Format.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: → T2

### T2 — Doku und Changelog: cosign 3 zum Prüfen der Images (R-1119)  [x]
Komponente: scripts · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html, changelog.d/ci-4.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @e36435f22 2026-11-06T18:41:28+01:00
Review: am Ende (Branch-Review)
Änderung: Im Abschnitt Signaturen DE+EN die Mindestversion (cosign 3, oder 2.6 mit `--new-bundle-format`) und, nach einer lokalen Probe mit cosign v3.1.4 gegen ein veröffentlichtes Image bis v0.46.0, ob alte Images mit cosign 3 prüfbar bleiben; `changelog.d/ci-4.md` (`### Changed`, umlautfrei).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html DE+EN · changelog.d/ci-4.md
Task-Review: am Ende
Abhängt von: T1

### T3 — Test: der Sign-Schritt prüft die frische Signatur (R-1119, Abschlussprüfung)  [x]
Komponente: server · Dateien: apps/server/tests/test_release_images.py, .github/workflows/docker.yml
Evidenz: run.sh[quick] server: 3 passed, 0 failed, 15 skipped @577be4a30 2026-11-06T18:49:45+01:00
Review: am Ende (Branch-Review)
Änderung: `test_release_images.py` fährt den Schritt „Sign the image (keyless)“ des Jobs `build` mit dem cosign-Stub (jetzt auch `sign`) für den Push eines Tags: `verify` folgt auf `sign` mit demselben Digest, der Identität `_signer(tag)` (aus `GITHUB_WORKFLOW_REF`, dieselbe, die der Job `latest` prüft) und dem GitHub-Issuer; scheitert `verify`, wird der Schritt rot. Der Kommentar in `docker.yml` sagt „fails the run“ statt „fails the push“.
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_release_images.py
Doku: keine (Test und Kommentar)
