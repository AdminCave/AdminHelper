<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# basic-ftp im e2e-Lockfile auf 6.2.x (R-0198) — Task-Ledger
Status: aktiv · Branch: feature/deps-basic-ftp · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
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

### T1 — `basic-ftp` per Override auf `^6.2.1` (R-0198)  [ ]
Komponente: desktop-e2e · Dateien: apps/desktop/e2e/package.json, apps/desktop/e2e/package-lock.json, CHANGELOG.md
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
