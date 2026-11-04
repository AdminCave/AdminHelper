<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-harness-2 — npm-Stempel per Lock-Hash, Node 26 im VM-Bootstrap

Roadmap: R-1106 (BUG), R-1087 (REF); beide Kevin 2026-11-03 als Harness-Änderung angenommen. Stand
`origin/main@4e0d5f7e`.

## Problem / Motivation

- **R-1106:** `npm_ci_if_stale` (`scripts/tests/run.sh:572`) installiert nur, wenn `node_modules` fehlt oder
  `package-lock.json` jünger ist. Auf einer warmen Box überlebt `node_modules` den Sync (die Sync-Liste schließt es
  aus). Stammt es aus einem anderen Baum und ist jünger als der Lock, läuft kein `npm ci`. Im Sammellauf
  2026-11-02-2310 fand `svelte-check` deshalb `@lucide/svelte` nicht (31 Fehler), weil der Lock älter war als das
  `node_modules` eines anderen Worktrees. Die mtime sagt nichts darüber, zu welchem Lock ein Baum gehört.
- **R-1087:** `scripts/vm/bootstrap_linux.sh:23` setzt `NODE_MAJOR` auf 22, CI und Images bauen seit kern-laufzeit-1
  mit Node 26 (`.github/workflows/ci.yml` `node-version: "26"`). Die Boxen testen also mit einem anderen Node als CI.

## Ziel & Nicht-Ziele

**Ziel:**
- `npm_ci_if_stale` vergleicht einen Stempel `node_modules/.ah-lock-sha256` (sha256 des `package-lock.json`, den
  es nach einem erfolgreichen `npm ci` schreibt) mit dem aktuellen Lock. Fehlt der Stempel oder weicht er ab, läuft
  `npm ci`. Ein `node_modules` ohne Stempel (Altbestand) wird einmal neu installiert.
- Den Stempel schreibt es über eine temporäre Datei plus `mv`: eine per `cp -al` verlinkte Kopie
  (`worktree-setup.sh`) darf den Stempel der Hauptkopie nie über denselben Inode ändern.
- `worktree-setup.sh` braucht das `touch` nicht mehr, mit dem es heute die mtime-Regel bedient: die verlinkte Kopie
  trägt den Stempel der Hauptkopie und ist frisch, solange die Locks gleich sind. Ändert der Branch seinen Lock,
  passt der Stempel nicht, und `run.sh` installiert.
- `NODE_MAJOR` steht auf 26 (gleich `ci.yml`). Ein Test in `harness_consistency_test.sh` hält beide Werte
  gleich, damit die Abweichung nicht wieder still entsteht.

**Nicht-Ziele:** keine Änderung an `.github/workflows/` (das merged Kevin). Der Re-Bake der Vorlagen ist nicht Teil
des Codes: `warm.sh` fährt den Bootstrap auf jeder Box, und der hebt Node an, wenn die Major-Version abweicht
(`bootstrap_linux.sh:196`). Der Re-Bake spart danach nur Zeit und ist im Pool `adminhelper-ci` erlaubt.

## Betroffene Komponenten & Dateien

`scripts/tests/run.sh` (`npm_ci_if_stale`), `scripts/tests/run_flags_test.sh` (Smoke-Block ab :884),
`scripts/dev/worktree-setup.sh:133-150`, `scripts/tests/worktree_setup_test.sh` (Fixture :89-93, Prüfungen :187-194
und :350-359), `scripts/vm/bootstrap_linux.sh:23`, `scripts/tests/harness_consistency_test.sh`.

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

NodeSource-Setup-Skript `https://deb.nodesource.com/setup_26.x`, am 2026-11-03 abgerufen: HTTP 200.

## Trade-offs & Alternativen

- npms eigene `node_modules/.package-lock.json` vergleichen: Das Format ist nicht der Lock selbst, und Felder
  unterscheiden sich je nach npm-Version. Ein eigener Stempel ist eindeutig. **Empfehlung: eigener Stempel.**
- mtime als Rückfall bei fehlendem Stempel: Damit bliebe der Fehler für jede warme Box bestehen. Abgelehnt.

## Risiken & Rollback

Ein einmaliges `npm ci` je `node_modules` ohne Stempel (Dev-Box, Worktrees, warme Boxen) kostet einmal Zeit. Der
Rollback ist der Revert des Merges.

## Doku-Impact

Keine. Die Änderung ist intern im Test-Harness; `DEVELOPMENT.md` nennt weder die mtime-Regel noch die Node-Version
der Boxen.

## Offene Fragen

Keine.
