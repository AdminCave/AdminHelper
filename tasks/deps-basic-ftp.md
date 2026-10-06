<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# basic-ftp im e2e-Lockfile auf 6.2.x (R-0198) — Task-Ledger
Status: bereit · Branch: feature/deps-basic-ftp · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-06 (Kevin hat R-0198 am 2026-10-06 angenommen und den Bau durch Worker A gewählt; Ein-Task-Paket, Delegation Kevin 2026-10-05)
Spec: Roadmap R-0198 (Kurz-Ledger ohne Spec)
Heavy: linux-full — nur der Desktop-E2E-Smoke (`run.sh e2e`, Schritt `desktop-e2e-smoke`) auf einer Pool-VM, weil ein Major-Override im WebdriverIO-Baum den Start von wdio brechen kann; die Aufsicht fährt ihn am Gate. Kein Stack-, Gateway-, PKI- oder Install-Pfad, nichts davon wird ausgeliefert.
DoD je Task: CLAUDE.md (Tests grün, ESLint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-06 von der Aufsicht (adminhelper-ac). Nach dem pyjwt-Bump (#82) ist der Dependency-Audit nur noch im
Schritt „Audit e2e lockfile“ rot. `basic-ftp` 5.3.1 hängt transitiv an `@wdio/utils` → `@puppeteer/browsers` →
`proxy-agent` → `pac-proxy-agent` → `get-uri`; `get-uri` verlangt `^5.3.1`, die gepatchte Version gibt es erst ab 6.2.1.
`npm audit fix --force` würde `@wdio/mocha-framework` auf 10 heben (Bruch). Vorbild ist der gezielte Override in
`f8d4376f` und der Lockfile-Weg in `0ecdc3ca`.

### T1 — `basic-ftp` per Override auf `^6.2.1` (R-0198)  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/package.json, apps/desktop/e2e/package-lock.json, CHANGELOG.md
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped · contracts: 1 ok @44c6d637 2026-10-06T02:43:22+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: In `apps/desktop/e2e/package.json` unter `overrides` `"basic-ftp": "^6.2.1"` ergänzen und den Lock mit
`npm install --package-lock-only --ignore-scripts` nachziehen (npm wie in `0ecdc3ca` beschrieben); im Lock-Diff
bewegt sich nur `basic-ftp` (falls npm mehr bewegt: im Commit-Body nennen und begründen). Vorher das Changelog von
basic-ftp 5.3.1 → 6.2.x lesen (Repo `patrickjuchli/basic-ftp`) und prüfen, dass die API, die `get-uri` nutzt
(`Client`, `FileInfo`, die Methoden in `get-uri`s `ftp`-Modul), in 6 erhalten ist. Load-Smoke im e2e-Verzeichnis
nach `npm ci`: `get-uri` aus dem wdio-Baum importiert ohne Fehler, und `npx wdio --version` startet. CHANGELOG unter
`[Unreleased]` → `### Security` in der Form der übrigen Audit-Einträge. Im Commit-Body: `npm audit --audit-level=high`
in `apps/desktop/e2e` vorher (18 high) und nachher (0), dazu `apps/web` und `apps/desktop/ui` unverändert ohne Fund.
Beweis: `gh run view 37394634899 --log-failed` (audit.yml, workflow_dispatch 2026-10-06 auf main@36287f79, Schritt
„Audit e2e lockfile“) ⇒ `basic-ftp <=6.2.0 Severity: high … GHSA-c475-qrg2-pj4r`, `18 high severity
vulnerabilities`; derselbe Schritt war schon am 2026-10-05 rot (Lauf 37325402429).
Dedup-Key: rel:desktop-e2e:package-lock.json:basic-ftp
HEAD: 36287f79
Semantik: `.github/workflows/audit.yml`, Schritt „Audit e2e lockfile“: „The e2e lockfile (wdio + deps) was unscanned —
this audit found serialize-javascript there; the sweep must cover it too (7.2/7.8).“ und DEVELOPMENT.md „Audit-Tools
lokal“: „`audit.yml` faehrt den woechentlichen CVE-Sweep in CI.“
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: CHANGELOG.md

### T2 — braces aus dem e2e-Baum: mochas chokidar per Override auf ^4 (R-0198)  [x]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/package.json, apps/desktop/e2e/package-lock.json, CHANGELOG.md
Evidenz: run.sh[quick] desktop-e2e: 1 passed, 0 failed, 17 skipped · contracts: 1 ok @fb275d88 2026-10-06T02:45:21+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Ergänzt 2026-10-06 auf Entscheidung der Aufsicht (Variante B): der zweite High-Fund im selben Audit-Schritt.
In `overrides` verschachtelt `"mocha": { "chokidar": "^4.0.3" }`, Lock wie in T1 (`npm install --package-lock-only
--ignore-scripts`, npm 10.9.8). Im Lock-Diff fällt `node_modules/mocha/node_modules/chokidar` 3.6.0 samt `braces` und den
Paketen weg, die nur chokidar 3 braucht; mocha nimmt das vorhandene chokidar 4.0.3. Grenze: Der Watch-Modus der
mocha-CLI (`lib/cli/watch-run.js`) verliert mit chokidar 4 die Glob-Unterstützung; e2e nutzt ihn nicht (wdio ruft mocha
programmatisch). Load-Smoke nach `npm ci`: `require('mocha')` und `@wdio/mocha-framework` laden, mochas
`lib/cli/watch-run.js` lädt mit chokidar 4 (CJS), `npx wdio --version` startet. CHANGELOG: der Eintrag aus T1 fasst
beide Advisories zusammen. Im Commit-Body: `npm audit --audit-level=high` in `apps/desktop/e2e` vorher (4 high, nach T1)
und nachher (0), `apps/web` und `apps/desktop/ui` unverändert 0, dazu die Grenze.
Beweis: `npm audit --audit-level=high` in `apps/desktop/e2e` auf feature/deps-basic-ftp@2e9259a4 ⇒ `braces *`,
Severity high, GHSA-vfj7-8cjw-p6xm (CVE-2026-93687, CVSS 8.7; betroffen ≤ 3.0.3, keine gepatchte Version), Pfad
braces 3.0.3 → chokidar 3.6.0 (`node_modules/mocha/node_modules/chokidar`) → mocha 10.8.2 → @wdio/mocha-framework
9.29.0 (verlangt mocha ^10), `4 high severity vulnerabilities`.
Dedup-Key: rel:desktop-e2e:package-lock.json:braces
HEAD: 2e9259a4
Verify: bash scripts/dev/verify.sh desktop-e2e --strict
Doku: CHANGELOG.md (der Eintrag aus T1, erweitert)
