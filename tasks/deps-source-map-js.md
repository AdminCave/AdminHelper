<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# source-map-js 1.2.1 → 1.2.2 in web und desktop-ui (R-0199) — Task-Ledger
Status: erledigt · Branch: feature/deps-source-map-js · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-06 (Kevin hat R-0199 am 2026-10-06 angenommen und den Bau durch Worker A gewählt; Lockfile-Fund nach seiner Regel vom selben Tag, Delegation Kevin 2026-10-05)
Spec: Roadmap R-0199 (Kurz-Ledger ohne Spec)
Heavy: none — nur die Lockfiles zweier Svelte-Projekte; `source-map-js` hängt dort ausschließlich an Dev-Werkzeug (`@vitest/coverage-v8` → `magicast`, `eslint-plugin-svelte` → `postcss`, `jsdom` → `css-tree`), nicht am Vite-Build und nicht im ausgelieferten Bundle. Kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, ESLint und Prettier sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-06 von der Aufsicht (adminhelper-ac). Nach #83 lief der Dependency-Audit von Hand erneut und war nur
noch in den Schritten „Audit web lockfile“ und „Audit desktop-ui lockfile“ rot: je 1 high, `source-map-js` 1.2.1
(GHSA-68fv-2mgg-jv7q, behoben in 1.2.2). Der Fix ist semver-kompatibel, alle drei Abnehmer erlauben 1.2.2: ein reiner
Lockfile-Bump ohne Override, nach Kevins Regel vom 2026-10-06 ein Fall für die Aufsicht. Vorbild für den Lock-Weg:
`0ecdc3ca` (npm 10.9.8, `--package-lock-only --ignore-scripts`).

### T1 — `source-map-js` im Web-Lockfile auf 1.2.2 (R-0199)  [x]
Komponente: web · Dateien: apps/web/package-lock.json, CHANGELOG.md
Evidenz: run.sh[quick] web: 1 passed, 0 failed, 17 skipped · contracts: 1 ok @3d518292 2026-10-06T03:26:43+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: In `apps/web` den Lock mit `npm update source-map-js --package-lock-only --ignore-scripts` (oder `npm audit
fix --package-lock-only --ignore-scripts`, falls `update` nicht greift) auf 1.2.2 heben; `package.json` bleibt
unverändert, im Lock-Diff bewegt sich nur `source-map-js` (bewegt npm mehr: im Commit-Body nennen und begründen).
CHANGELOG unter `[Unreleased]` → `### Security` ein Eintrag für beide Projekte (T2 ergänzt ihn), in der Form der
übrigen Audit-Einträge. Im Commit-Body: `npm audit --audit-level=high` in `apps/web` vorher (1 high) und nachher (0),
`npm ci` rc 0.
Beweis: `gh run view 37398587325 --log-failed` (audit.yml, workflow_dispatch 2026-10-06 auf main@01caf2e1, Schritt
„Audit web lockfile“) ⇒ `source-map-js … Severity: high … GHSA-68fv-2mgg-jv7q`, `1 high severity vulnerability`.
Dedup-Key: rel:web+desktop-ui:package-lock.json:source-map-js
HEAD: 01caf2e1
Semantik: DEVELOPMENT.md „Audit-Tools lokal“: „`audit.yml` faehrt den woechentlichen CVE-Sweep in CI.“
Verify: bash scripts/dev/verify.sh web --strict
Doku: CHANGELOG.md

### T2 — `source-map-js` im Desktop-UI-Lockfile auf 1.2.2 (R-0199)  [x]
Komponente: desktop-ui · Dateien: apps/desktop/ui/package-lock.json, CHANGELOG.md
Evidenz: run.sh[quick] desktop-ui: 1 passed, 0 failed, 17 skipped · contracts: 1 ok @4ec56ad6 2026-10-06T03:28:43+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Wie T1 in `apps/desktop/ui`; der CHANGELOG-Eintrag aus T1 nennt danach beide Projekte. Im Commit-Body
`npm audit --audit-level=high` in `apps/desktop/ui` vorher (1 high) und nachher (0), dazu `apps/web` und
`apps/desktop/e2e` ohne Fund.
Beweis: derselbe Lauf, Schritt „Audit desktop-ui lockfile“ ⇒ `source-map-js … GHSA-68fv-2mgg-jv7q`, `1 high severity
vulnerability`.
Dedup-Key: rel:web+desktop-ui:package-lock.json:source-map-js
HEAD: 01caf2e1
Semantik: wie T1.
Verify: bash scripts/dev/verify.sh desktop-ui --strict
Doku: CHANGELOG.md
