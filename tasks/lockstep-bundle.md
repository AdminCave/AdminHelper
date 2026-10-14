<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Paket lockstep-bundle: der Toolchain-Lockstep liest Kommentare, die Test-Box-Go und jede wahre Schreibweise von check-latest (R-0355, R-0356, R-0354) — Task-Ledger
Status: erledigt · Branch: harness/lockstep-bundle · Commit-Granularität: pro Task · Review: am Ende (Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-13 (kleines Fund-Paket, Triage Kevin 2026-10-13; Bau nach der Uebergabe von status-robust; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0355, R-0356, R-0354 (Kurz-Ledger ohne Spec)
Heavy: none — toolchain-lockstep.sh mit toolchain_lockstep_test (Fixture-Bäume, Fake-curl); kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku DE+EN im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker A für den Chef (adminhelper-ac). Kevin hat das Bündel am 2026-10-13 angenommen.
Zeilenangaben origin/main@073a487e; beim Bau an Symbolen orientieren.

Vorab geprüft:
- Prüfung 1 (toolchain-lockstep.sh :72–103) liest `go-version:` mit einem sed, der nach dem Wert nur Leerraum bis zum
  Zeilenende zulässt (:93). Eine Zeile `go-version: "1.25"  # kommentar` fällt heraus: Sie zählt nicht und kann keine
  Drift melden. Prüfung 1b liest dieselbe Zeile (awk, `^[ ]*go-version:`).
- `GO_VERSION` in scripts/vm/bootstrap_linux.sh (:19, `"${AH_GO_VERSION:-1.26.9}"`) steht in keiner Prüfung. Den
  ruff-Pin derselben Datei liest Prüfung 2 schon (:151).
- Prüfung 1b nimmt nur das wörtliche `check-latest: true` (:117). setup-go liest das Input mit `core.getBooleanInput`.
  Das nimmt `true`, `True` und `TRUE`; Anführungszeichen ändern am String nichts
  (https://github.com/actions/toolkit/blob/main/packages/core/src/core.ts, `getBooleanInput`).
- Die Fixture `fixture()` in toolchain_lockstep_test (:50–70) schreibt bootstrap_linux.sh ohne `GO_VERSION`.

### T1 — Prüfung 1 liest go-version auch mit einem Kommentar dahinter (R-0355)  [x]
Komponente: scripts · Dateien: scripts/dev/toolchain-lockstep.sh, scripts/tests/toolchain_lockstep_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @97ffb09e 2026-10-13T20:15:25+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- Der sed in Prüfung 1 (:93) lässt nach dem Wert einen Kommentar zu: `[[:space:]]*\(#.*\)\{0,1\}$`. Der Wert selbst bleibt
  wörtlich und wird geprüft wie heute.
- Fälle in toolchain_lockstep_test, am Dateiende:
  - nur die zweite `go-version`-Zeile in ci.yml wird `"1.26"  # plchold` → Exit 1, „go-version drift“;
  - alle drei mit `"1.25"  # plchold` → Exit 0, `ok (go 1.25 <= 1.25)`.
Rot vorher: Auf main geht der erste Fall mit Exit 0 durch; die Zeile mit Kommentar zählt nicht.
Beweis: origin/main@073a487e, toolchain-lockstep.sh :93. Fund: Review go-toolchain-126 (Worker A), 2026-10-13.
Dedup-Key: bug:scripts:toolchain-lockstep.sh:go-version-trailing-comment
HEAD: 073a487e
Semantik: docs/developer/cicd.html:40 „jede <code>go-version</code>-Stelle in <code>ci.yml</code>/<code>release.yml</code>/<code>audit.yml</code> muss dieselbe sein“ (HTML-Quelle).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T2 — Der Lockstep hält GO_VERSION der Test-Boxen auf der Minor der Workflows (R-0356)  [x]
Komponente: scripts · Dateien: scripts/dev/toolchain-lockstep.sh, scripts/tests/toolchain_lockstep_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html, DEVELOPMENT.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @51c2a014 2026-10-13T20:29:02+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- Neue Offline-Prüfung 1c nach 1b: Der Default von `GO_VERSION="${AH_GO_VERSION:-X.Y.Z}"` in bootstrap_linux.sh muss
  dieselbe MAJOR.MINOR haben wie `go-version`. Der Patch ist frei.
  - Sonst kommt eine `::error::`-Zeile, die beide Werte nennt und sagt, dass `GO_VERSION` und seine SHA-256 zusammen mit
    `go-version` gehoben werden. Exit 1.
  - Fehlt der Default oder ist er kein `X.Y.Z` aus Ziffern, kommt ebenfalls Exit 1 mit eigener Meldung.
  - Der Kopfkommentar nennt die Prüfung.
- toolchain_lockstep_test:
  - `fixture()` schreibt in bootstrap_linux.sh eine Zeile `GO_VERSION="${AH_GO_VERSION:-<ci>.0}"`. Sie hängt an einem
    neuen optionalen neunten Argument, Default `<ci>.0`. Kein bestehender Fall ändert seinen Sollwert.
  - Neue Fälle am Dateiende:
    - `GO_VERSION` 1.24.0 bei go-version 1.25 → Exit 1, die Meldung nennt bootstrap_linux.sh;
    - ein anderer Patch (1.25.9) → Exit 0;
    - ohne `GO_VERSION`-Zeile → Exit 1;
    - auch bei unerreichbarem Proxy Exit 1, nicht 75.
  - Der bestehende Fall über den echten Baum prüft damit 1.26.9 gegen 1.26.
- cicd.html:40 DE+EN und DEVELOPMENT.md (Lockstep-Absatz, :1356ff.): je ein Satz zu `GO_VERSION`.
Rot vorher: Auf main geht ein Baum mit `GO_VERSION` 1.24.0 und go-version 1.25 mit Exit 0 durch.
Beweis: origin/main@073a487e, bootstrap_linux.sh :19; toolchain-lockstep.sh liest `GO_VERSION` nirgends. Fund: Review
go-toolchain-126 (Worker A), 2026-10-13.
Dedup-Key: ref:scripts:toolchain-lockstep.sh:bootstrap-go-version
HEAD: 073a487e
Semantik: DEVELOPMENT.md Lockstep-Absatz und docs/developer/cicd.html:40 (Toolchain-Lockstep); bootstrap_linux.sh :20–21
„Pin the Go tarball checksum like the frpc one“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html, DEVELOPMENT.md
Abhängt von: T1

### T3 — 1b nimmt jede wahre Schreibweise von check-latest, und der Nachbar-Step zählt nicht (R-0354)  [x]
Komponente: scripts · Dateien: scripts/dev/toolchain-lockstep.sh, scripts/tests/toolchain_lockstep_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @044cb5fd 2026-10-13T20:42:32+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung:
- Prüfung 1b (:117) nimmt `true`, `True` und `TRUE`, auch in einfachen oder doppelten Anführungszeichen. Das ist die
  Menge von `getBooleanInput`.
  - Das einfache Anführungszeichen kommt über `awk -v`, weil das awk-Programm in einfachen Anführungszeichen steht.
- Fälle in toolchain_lockstep_test, am Dateiende:
  - `check-latest: "true"`, `check-latest: True` und `check-latest: 'TRUE'` → Exit 0;
  - `check-latest: yes` → Exit 1, die bekannte Meldung (setup-go wirft dort einen Fehler);
  - der Regressionsfall: release.yml mit `go-version` ohne `check-latest` im setup-go-Step und einem
    `check-latest: true` im nächsten Step auf Step-Ebene → Exit 1, die Meldung nennt release.yml:7.
Rot vorher: Auf main sind die drei Schreibweisen rot („without check-latest: true“).
Beweis: origin/main@073a487e, toolchain-lockstep.sh :117 `check-latest:[ ]*true[ ]*`. Fund: Review go-toolchain-126
(Worker A), 2026-10-13.
Dedup-Key: ref:scripts:toolchain-lockstep.sh:check-latest-followups
HEAD: 073a487e
Semantik: `getBooleanInput` in @actions/core (Link oben).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Abhängt von: T2

### T4 — Nachbesserung aus dem Review am Ende: # ohne Leerzeichen davor gehört zum Wert  [x]
Komponente: scripts · Dateien: scripts/dev/toolchain-lockstep.sh, scripts/tests/toolchain_lockstep_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @4c852e4f 2026-10-13T21:29:23+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Angelegt 2026-10-13 aus dem Review am Ende (Opus, `request_changes`: ein belegter Fund, drei nits).
- T1 schloss `#` aus dem Wert aus und verlangte vor dem Kommentar kein Leerzeichen. YAML liest `#` aber nur nach einem
  Leerzeichen als Kommentar.
  - Folge: `go-version: 1.25#x` las Prüfung 1 als `1.25`, auf main war die Zeile laut („cannot compare go-version
    '1.25#x'“).
  - Neu: Der Wert nimmt `#` wieder auf, der Kommentar verlangt davor Leerraum.
  - Fälle: `go-version: 1.25#x` und `go-version: "1.25#x"` → Exit 1, „cannot compare go-version '1.25#x'“. Die Fälle aus
    T1 bleiben grün.
- nit: Der Zweig „Default von GO_VERSION ist kein X.Y.Z“ in 1c hatte keinen Fall. Neu: `GO_VERSION` 1.25 → Exit 1,
  „no plain GO_VERSION“.
- Die nits zu gemischten Anführungszeichen bei check-latest und zu `"1.25 # x"` bleiben liegen: In beiden Fällen
  scheitert der Workflow schon selbst.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)
Abhängt von: T3
