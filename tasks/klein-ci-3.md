<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ci-3 — Task-Ledger
Status: bereit · Branch: feature/klein-ci-3 · Review: am Ende
Spec: docs/features/klein-ci-3.md (Roadmap R-1385, R-1386)
Heavy: none — Wächter-Skript unter .github/scripts und Doku, kein Stack-Pfad
DoD je Task: CLAUDE.md (Tests grün, Lint sauber, SPDX bei neuen Dateien; Doku in der Task oder ihrer Doku-Task).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

### T1 — R-1385: Cache-Wächter erkennt weitere Formen eines Image-Builds in run:  [x]
Komponente: scripts · Dateien: .github/scripts/cache_settings.sh, .github/scripts/cache_settings_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @daf3a5a4e 2026-11-12T17:54:10+01:00
Review: am Ende (Branch-Review)
Beweis: ci-13 Branch-Review 2026-11-12 · feature/ci-13@d375ce5a2 .github/scripts/cache_settings.sh:60 · Dedup-Key: REF:scripts:cache_settings.sh:dockerbuild
Änderung: Das Muster `dockerbuild` erlaubt einen Pfad vor `docker` (`/usr/bin/docker`), beliebigen Leerraum (Tab) als Trenner und die Unterbefehle `compose`, `image`, `builder` (neben `buildx`) vor `build`/`bake`. Test: je eine rote Probe für `/usr/bin/docker build`, Tab, `docker compose build`, `docker image build`, `docker builder build`, grüne für `docker compose up`, `docker image ls`, `docker builder prune`, `imagetools`; das echte `ci.yml`/`release.yml`/`docker.yml` bleibt grün.
Verify: bash scripts/dev/verify.sh scripts --strict -- .github/scripts/cache_settings_test
Doku: keine (Beschreibung in cicd.html nennt die Formen nicht einzeln)

### T2 — R-1386: Doku Image-Signatur: nur --certificate-identity bindet die Version  [x]
Komponente: scripts · Dateien: docs/developer/cicd.html, docs/en/developer/cicd.html
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @6415e36e4 2026-11-12T17:56:41+01:00
Review: am Ende (Branch-Review)
Beweis: ci-13 security nit 2026-11-12 · feature/ci-13@d375ce5a2 docs/developer/cicd.html:569 · Dedup-Key: REF:docs:cicd.html:cosign-regex-version
Änderung: Der Absatz zur verankerten Regex sagt, dass nur `--certificate-identity` die Version bindet und die Regex jedes Release-Tag annimmt (ein Skript, das eine Version erzwingen soll, nimmt die feste Identität). DE+EN.
Verify: bash scripts/dev/verify.sh scripts --strict -- doc_smoke_test
Doku: die Änderung selbst
Task-Review: am Ende
