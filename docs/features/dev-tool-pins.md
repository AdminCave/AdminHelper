<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Werkzeug-Pins: npm-Lockfiles ohne Audit-Befund, ein ruff überall

Roadmap: R-0038, R-0074 · Ledger: `tasks/dev-tool-pins.md` · Branch: `harness/dev-tool-pins`
Geplant 2026-09-30 von der Aufsicht (adminhelper-ac) auf Kevins Wort; Entscheidungen am selben Tag (Runde B).

## Problem / Motivation

**npm (R-0038).** vitest steht in `apps/web` und `apps/desktop/ui` auf 4.1.8 (beide Lockfiles), betroffen von
GHSA-82fw-gwwq-j7x9 (moderate, `<4.1.11`). Seit dem grünen Audit-Lauf vom 2026-09-29 (36558264507) sind neue
Advisories dazugekommen: `npm audit --json` meldet heute in `apps/web` 4 moderate + 2 high, in `apps/desktop/ui`
5 moderate + 2 high, in `apps/desktop/e2e` 1 moderate + 2 high. High sind brace-expansion 5.0.9
(GHSA-qhr7-859c-m2p7, GHSA-6j4f-fj2g-mc7p) und undici 7.29.0 (GHSA-rfgv-xxqx-mfg5, GHSA-w293-vg96-wgc3);
moderate dazu devalue 5.8.1 (GHSA-9rgm-9g3h-6x36), in e2e ip-address 10.7.0 (GHSA-j6r3-76f7-8jcv,
GHSA-h3mg-xc3c-68pw). Alle betroffenen Pakete sind `dev: true`, alle Fixes liegen in den vorhandenen Ranges. Der
Audit-Job gated mit `npm audit --audit-level=high` (`.github/workflows/audit.yml:94–106`, alle drei Verzeichnisse);
er fällt damit beim nächsten Cron (Montag 2026-10-05, 06:17 UTC) rot — Schluss aus dem lokalen rc 1, kein
beobachteter Lauf.

Das Anheben scheitert an der Toolchain der Box: npm 10.9.8 bricht bei
`npm install --package-lock-only vitest@4.1.11 @vitest/coverage-v8@4.1.11` (ebenso `npm audit fix`) in arborist
ab (`Cannot read properties of null (reading 'edgesOut')`, `build-ideal-tree.js` `#loadPeerSet`); Auslöser ist,
dass vitest 4.1.8 `@vitest/coverage-v8` als `peerOptional "4.1.8"` exakt pinnt. `npx -y npm@11` (11.20.0) löst
es; die damit geschriebenen Lockfiles laufen unter npm 10.9.8 mit `npm ci` fehlerfrei (Probe der Aufsicht
2026-09-30, Wegwerf-Kopie unter `~/.cache`).

**ruff (R-0074).** `apps/server/requirements-dev.txt:18` verlangt `ruff>=0.15`, CI pinnt 0.15.20
(`.github/workflows/ci.yml:101`), `scripts/vm/bootstrap_linux.sh:31` ebenso. `scripts/dev/toolchain-lockstep.sh`
(Prüfung 2, `:95–128`) prüft CI-Pin == Bootstrap-Default und nur, dass der Boden nicht darüber liegt. `run.sh`
installiert `requirements-dev.txt` ins `AH_VENV`; mit `>=0.15` bleibt ein vorhandenes 0.16.x liegen
(`~/.cache/ah-venv`, `-8b`, `-fable`: 0.16.8). Auf der Box aktiviert `iter.sh` das Venv vor dem Verify, dann
liegt dessen ruff im `PATH`, und `run.sh:497–503` nimmt das erste `ruff` im `PATH`. Mit 0.16.8 meldet
`ruff check --no-cache` über die vier Pfade 841 Treffer (B008 191, UP031 172, UP045 148, …), mit 0.15.20 keinen
— ein lokales Gate kann rot sein, wo CI grün ist, und umgekehrt.

## Ziel und Nicht-Ziele

Ziel:
- `npm audit --audit-level=moderate` ist in `apps/web`, `apps/desktop/ui` und `apps/desktop/e2e` ohne Befund;
  vitest und alle `@vitest/*` stehen auf 4.1.11, die Ranges in `package.json` auf `^4.1.11`.
- Es gibt genau ein ruff: `requirements-dev.txt` pinnt `ruff==0.15.20`, `ruff.toml` verlangt
  `required-version = "==0.15.20"`, und der Lockstep prüft alle vier Stellen (ci.yml, bootstrap, requirements-dev,
  ruff.toml) auf Gleichheit.

Nicht-Ziele:
- vitest 5 (Major, eigener Schritt).
- npm der Dev-Box dauerhaft anheben; `npx -y npm@11` schreibt die Lockfiles einmalig, CI bleibt bei npm 10.
- ruff auf 0.16 anheben (841 Treffer, eigenes Vorhaben).
- ruff in monitoring/ca-issuer-requirements eintragen (sie führen es nicht; jede weitere Stelle wäre eine
  weitere Drift-Quelle).
- Die fastapi/starlette-Drift im `AH_VENV` (lose `.in` gegen Lock) — deckt seit #57 der CI-Job
  `python-lock-*` ab.
- Warnungen von `cargo audit` (unmaintained/unsound) — sie machen `audit.yml` nicht rot.

## Betroffene Komponenten und Dateien

- web: `apps/web/package.json` (`:28`, `:40`), `apps/web/package-lock.json`
- desktop-ui: `apps/desktop/ui/package.json` (`:25`, `:26`, `:39`), `apps/desktop/ui/package-lock.json`
- desktop/e2e: `apps/desktop/e2e/package-lock.json` (package.json unverändert)
- scripts: `scripts/dev/toolchain-lockstep.sh`, `scripts/tests/toolchain_lockstep_test.sh`, `ruff.toml`,
  `apps/server/requirements-dev.txt`, Kommentare in `.github/workflows/ci.yml:98–100` und
  `scripts/vm/bootstrap_linux.sh:24–30`
- Doku: `docs/developer/cicd.html:40` + `docs/en/developer/cicd.html:40`, `DEVELOPMENT.md` „Python-Lint/Format
  (ruff)“ (`:129–144`), `CHANGELOG.md` [Unreleased]

## Datenmodell / API / Migrationen

Keine. Kein API-, Schema- oder DB-Vertrag ändert sich; die npm-Pakete sind reine Test-/Build-Abhängigkeiten.

## Externe Integrationen

- npm-Advisories (GitHub Advisory Database, IDs oben), gelesen mit `npm audit --json`.
- ruff `required-version` (Top-Level-Einstellung, PEP-440-Specifier; bei Abweichung beendet sich ruff mit
  Fehler): https://docs.astral.sh/ruff/settings/#required-version — per Probe bestätigt: 0.16.8 mit
  `==0.15.20` → Exit 2 „Required version `==0.15.20` does not match the running version“, 0.15.20 → Exit 0.

## Trade-offs und Alternativen

- **npm@11 per npx statt Box-npm anheben:** Einmalig beim Schreiben der Lockfiles, CI und Box bleiben bei npm 10;
  `npm ci` unter npm 10 ist geprüft. Alternative (Box-npm dauerhaft auf 11) ändert die Toolchain für alle Bauten.
- **Alle Funde statt nur vitest:** gleicher Handgriff, gleiche Dateien; nur vitest ließe den Audit am Montag rot.
- **required-version zusätzlich zum Pin:** Der Pin heilt nur neu installierte Venvs, die Ursache ist die Wahl
  „erstes ruff im PATH“. required-version macht ein falsches ruff laut (Exit 2) statt still anders. Preis: ein
  Bump braucht vier Stellen — der Lockstep prüft alle vier, also fällt eine vergessene Stelle offline auf.

## Risiken und Rollback

- Ein Lockfile-Update zieht mehr als erwartet: erwartet sind 12 Pakete (web, desktop-ui) bzw. 7 (e2e); der Bau
  vergleicht `git diff --stat` und die Paketliste mit dieser Erwartung, mehr ist ein STOPP mit Bericht.
- devalue landet evtl. im Web-Bundle: der Playwright-Job der PR-CI (`ci.yml`, web e2e) deckt das ab.
- Ein Venv mit ruff 0.16.x bricht nach T4 mit Exit 2 ab: gewollt; `run.sh` installiert beim nächsten Lauf
  0.15.20 ins `AH_VENV` zurück. `format-file.sh:27` formatiert mit falschem ruff dann still nicht (Exit 0 bleibt).
- Rollback: je Task ein Commit, `git revert` genügt; die Lockfiles gehen auf den alten Stand zurück.

## Doku-Impact

CHANGELOG [Unreleased]: Security (npm-Funde, T1/T2) und Changed (ruff gepinnt, T3/T4). `cicd.html` DE+EN: der
Lockstep-Satz sagt „gleiche Version“ statt „Boden nicht darüber“. `DEVELOPMENT.md`: ein Satz zu Pin und
required-version.

## Offene Fragen

Keine. Entschieden am 2026-09-30 (Kevin): alle npm-Funde mit `npx -y npm@11`, vitest 4.1.11 (nicht 5),
`ruff==0.15.20` mit Gleichheit im Lockstep, dazu `required-version` in `ruff.toml`.
