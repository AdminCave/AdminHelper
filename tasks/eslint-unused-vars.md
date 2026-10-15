<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# ESLint meldet tote `_`-Stores wieder — Task-Ledger
Status: aktiv · Branch: feature/eslint-unused-vars · Review: am Ende
Spec: Roadmap R-0028
Heavy: none — nur Lint-Konfiguration beider Frontends; kein Laufzeitcode, kein Stack-, Gateway-, PKI- oder Install-Pfad
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Baut nach R-0240 und R-0383 (beide `desktop-ui`).

### T1 — `varsIgnorePattern '^_'` aus beiden ESLint-Konfigurationen  [ ]
Komponente: web · Dateien: apps/web/eslint.config.js, apps/desktop/ui/eslint.config.js
Änderung: In `@typescript-eslint/no-unused-vars` fällt `varsIgnorePattern: '^_'` weg (`apps/web/eslint.config.js:46`, `apps/desktop/ui/eslint.config.js:46`); `argsIgnorePattern: '^_'` bleibt. Beide Frontends benennen modul-private Stores mit `_` (`_auth`, `_users`, `_hooks` …), das Muster blendete damit jeden toten Store aus. Der Kommentar darüber (`:40-43`), der genau das als bekannte Lücke beschreibt, wird auf den neuen Stand gezogen. Auf `main` meldet die Regel ohne das Muster in beiden Frontends 0 Funde; es ist kein Code anzupassen.
Verify: bash scripts/dev/verify.sh web desktop-ui --strict
Doku: keine (intern, Lint-Regel)
Beweis: main@c18098a4 · `printf "import { writable } from 'svelte/store';\nconst _dead = writable(0);\nexport const used = 2;\n" | npx eslint --stdin --stdin-filename src/lib/stores/zz_probe.ts` in apps/web → mit der heutigen Konfiguration keine Meldung zu `_dead`; mit `--rule '{"@typescript-eslint/no-unused-vars": ["error", {"argsIgnorePattern": "^_"}]}'` → „'_dead' is assigned a value but never used.“
Orakel: metric — unbenutzte Variablen ohne das Muster, je Frontend über `eslint --format json`
Metrik: ESLint (node_modules von main, 2026-10-15), `no-unused-vars` ohne `varsIgnorePattern` auf apps/web und apps/desktop/ui: 0 → 0 Funde (keine toten `_`-Variablen heute)
Dedup-Key: ref:web:eslint.config.js:vars-ignore-pattern
HEAD: c18098a4
Semantik: apps/web/eslint.config.js:42-43 — „modul-private Stores heissen hier ebenfalls so, ein toter _store faellt der Regel also nicht auf“; keine Stelle in docs/ — gesucht: eslint, no-unused-vars, varsIgnorePattern in docs/**
