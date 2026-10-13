<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Box-Skripte: jeder Aufruf der Agent-CLI ist gegen die CLI geprüft — Task-Ledger
Status: geplant · Branch: harness/box-cli-check · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Spec: Roadmap R-0333 (Kurz-Ledger ohne Spec)
Heavy: none — ein Test im Paket `cmd/adminhelper-agent`, das Agent-Binary selbst ändert sich nicht; kein Stack-, Gateway-, PKI- oder Install-Pfad, und die Box-Skripte bleiben, wie sie sind.
DoD je Task: CLAUDE.md (Tests grün, gofmt und go vet sauber, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-13 von Worker B im Auftrag der Aufsicht (adminhelper-ac). Kevin hat die Zeile am 2026-10-13
angenommen. Die private Roadmap ist in diesem Worktree nicht lesbar; der Zeileninhalt kommt von der Aufsicht.
Zeilenangaben origin/main@7860cfdd.

Die Multibox-Box-Skripte (`scripts/tests/box_*.sh`) rufen die Agent-CLI auf, und das nur auf einer VM. Lokal
prüft keiner diese Aufrufe, denn `multibox_test.sh` ersetzt `vm.py` und damit jede Box durch eine Attrappe
(`:41-66`). So kam in harness-checks ein `sudo adminhelper-agent sync` durch alle lokalen Tests und Proben; richtig ist
`adminhelper-agent frpc sync` (`apps/agent/cmd/adminhelper-agent/main.go:110-125`). Erst der Review fand es, und der
Multibox-Lauf wäre an einem Fehler des Harness rot geworden.

### T1 — agent: ein Test prüft jeden Aufruf der Agent-CLI in den Box-Skripten mit `--help` (R-0333)  [ ]
Komponente: agent · Dateien: apps/agent/cmd/adminhelper-agent/box_cli_test.go
Änderung: Neue Datei `box_cli_test.go` im Paket `main`, SPDX-Kopf (`reuse annotate --copyright "Kevin Stenzel"
--license GPL-3.0-or-later`). Am Produktionscode ändert sich nichts.
- **Die Aufrufe lesen:**
  - Der Test liest `scripts/tests/box_*.sh`, relativ zum Paket `../../../../scripts/tests`.
  - Erfasst wird jeder Aufruf `adminhelper-agent <unterbefehl…> [--flag …]`, ohne Kommentarzeilen.
  - Unterbefehle sind die Wörter bis zum ersten Flag. Ein Flag ist sein Name ohne Wert. Werte, Variablen und
    Shell-Operatoren (`&&`, `||`, `|`, `;`, `\`, Umleitungen) beenden bzw. überspringt der Parser.
  - Heute sind es sieben Aufrufe: `provision` viermal, `run --once` zweimal, `frpc sync` einmal (`box_agentbox.sh:48`,
    `:53`; `box_agentbox_rpm.sh:36`, `:37`; `box_tunnelbox.sh:30`, `:52`; `box_visitorbox.sh:27`). Findet der Parser
    weniger als einen je Skript, das `adminhelper-agent` nennt, ist der Test rot und kein leeres Grün.
- **Gegen die echte CLI:**
  - Je Aufruf startet der Test sein eigenes Binary neu, als Hilfsprozess: das übliche Muster mit
    `os.Args[0] -test.run=…` und einer Umgebungsvariable.
  - Der Hilfsprozess setzt `os.Args` auf `adminhelper-agent <unterbefehle…> --help` und ruft `main()`.
  - Erwartet: Exit 0, und jedes Flag des Aufrufs (`--url`, `--token`, `--server-id`, `--insecure`, `--once`) steht in
    der Hilfe dieses Unterbefehls. Ein unbekannter Unterbefehl endet in `main()` mit `os.Exit(1)` (`main.go:48-51`);
    deshalb läuft er im Hilfsprozess und nicht im Testprozess.
- **Gegenprobe, dass der Check fallen kann**, an Fixture-Zeilen statt an den Skripten:
  - `sudo adminhelper-agent sync` → rot.
  - `adminhelper-agent run --onse` → rot (Flag nicht in der Hilfe).
  - `adminhelper-agent frpc sync` → grün.
- Der Test läuft auch im Windows-Job der CI (`ci.yml`, „Go Agent (test, Windows)“). Pfade über `filepath`, und der
  Hilfsprozess braucht keine Shell.
Verify: bash scripts/dev/verify.sh agent --strict
Doku: keine (ein Test; `docs/developer/` beschreibt die Box-Skripte nicht einzeln)
Beweis: origin/main@7860cfdd:
- `git grep -l 'scripts/tests\|box_' -- apps/agent` → kein Treffer: Kein Test des Agents liest die Box-Skripte.
- `multibox_test.sh:41-66`: Die `vm.py`-Attrappe antwortet je Box-Skript mit festen Marken.
- harness-checks T2 (2026-10-13): `sudo adminhelper-agent sync` war mit `multibox_test`, shellcheck, diff-scan und den
  Mutationsproben grün. Ein frisch gebautes Binary: `adminhelper-agent sync --help` rc 1, `adminhelper-agent frpc sync
  --help` rc 0.
Metrik: Aufrufe der Agent-CLI in `scripts/tests/box_*.sh`, die ein Test gegen die CLI prüft: 0 → 7.
Orakel: mutation-sample — in einer Kopie eines Box-Skripts `frpc sync` zu `sync` oder `--once` zu `--onse`: der Test
rot; der Hilfsprozess ruft `main()` nicht (immer Exit 0): die Gegenprobe rot.
Dedup-Key: ref:scripts:box-scripts:agent-cli-check
HEAD: 7860cfdd
Semantik: keine Stelle in docs/ — gesucht in `docs/developer/` nach den Box-Skripten. Im Repo:
`scripts/tests/multibox.sh:6-12`: „multibox.sh — distributed, multi-host AdminHelper E2E … agent-box(s)= real .deb
install + `adminhelper-agent provision` over a network hop“. Die Skripte sollen die echte CLI aufrufen.
