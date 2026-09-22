<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness Stufe 4 — Runner-Isolation und deterministische Gates

Roadmap-Zeile R-0007 · Quelle: privates Roadmap-Dokument §Stufe 4, D18 (alles auf dem Abo, kein API-Key),
D20 (`adminhelper-runner`) · Stand 2026-09-18 · Claude Code 2.1.274 lokal.

## Problem / Motivation

Heute gelten die Regeln des Betriebsmodells nur, weil das Modell sie liest: Commits entstehen in der Modell-Session,
das Modell könnte seinen eigenen Harness (`CLAUDE.md`, Skills, Hooks, `run.sh`) ändern, Sicherheitsfunde könnten
in versionierte Dateien geraten, und jeder Bau läuft mit Kevins Rechten, Kevins SSH-Schlüssel, Kevins `gh`-Login
und den Bypass-Rechten seiner Worker-Sessions. Solange ein Mensch jeden Lauf startet und jeden PR liest, trägt das.
Stufe 7 (Worker in `tmux`, ohne Zuschauer) trägt es nicht mehr. Stufe 4 macht die Regeln technisch:

- **Credential-Ebene:** ein eigener Unix-User ohne SSH-Schlüssel, ohne `gh`, ohne D-Bus, mit einem Klon, der nicht
  pushen kann, einem eigenen Proxmox-Token nur für den Pool und einem eigenen Abo-Token (`claude setup-token`, D18).
- **Prozess-Ebene:** ein `[x]` und ein Commit entstehen nur in `task-close.sh`, das außerhalb der Modell-Session
  Verify, Diff-Scan, Scope und Sec-Sperre prüft. Das Modell kann `git commit` nicht mehr selbst aufrufen.
- **Harness-Schutz:** eine Liste von Harness-Pfaden, ein PreToolUse-Hook, der Edits darauf im autonomen Lauf
  verweigert, und ein Kill-Switch, der die Hooks in Warnungen verwandelt.

Kleiner als die zweite Fassung der Roadmap: kein Commit-Gate-Hook, kein Verdict-Hook, keine Tree-Hash-Kette über
`mark-done` — das Modell committet nicht mehr, also braucht es diese Bremsen nicht.

## Ziel & Nicht-Ziele

**Ziel.** Nach dem Merge und Kevins `runner-setup.sh` existiert `adminhelper-runner` mit Klon `/srv/ah/repo`
(`pushurl=/dev/null`), Lanes unter `/srv/ah/lanes/<slug>`, eigener Test-Datenbank, eigenem Proxmox-Token, eigenem
Abo-Token und einer `~/.claude/settings.json` im Modus `dontAsk` mit Deny-Regeln. Ein Red-Team-Skript beweist, dass
dieser User weder pushen noch fremde Secrets lesen noch den Harness ändern kann. `task-close.sh` ist ab dem Merge der
einzige Weg zu `[x]` und Commit — auch für die interaktiven Opus-Bauten, damit die Mechanik vor Stufe 7 Wochen im
Alltag läuft. `ledger.sh`, `review.sh` (drei Verben), `harness.sh`, `runner-env.sh` und `hooks_test.sh` stehen.

**Nicht-Ziele.** Kein Worker-Loop (`ledger-loop.sh`, Stufe 7). Kein Reviewer als eigener Prozess und keine
Agent-Dateien (Stufe 6; `task-close.sh --review none` ist bis dahin der Default). Kein `roadmap.py` (Stufe 5). Keine
Bash-Sandbox (bubblewrap ist installiert, aber mit den Toolchains unverifiziert — kein Startkriterium). Keine
Toolchain-Kopie für Go/Rust/Node auf den Runner: der Runner baut in Lanes mit `Fast-Suite: vm`, seine schweren
Suiten laufen auf den VMs, lokal braucht er Python, shellcheck und git (offene Frage 1). Kein GitHub-Token für den
Runner: Draft-PRs öffnet Kevin bzw. Stufe 7 über einen gescopten Token, nicht diese Stufe.

## Betroffene Komponenten & Dateien

**Neu:** `scripts/dev/harness-paths.txt`, `scripts/dev/harness.sh`, `scripts/dev/hooks/harness-guard.sh`,
`scripts/dev/ledger.sh`, `tasks/templates/task.md`, `scripts/dev/review.sh` (Verben `diff-scan`, `scope`, `sec`),
`scripts/dev/task-close.sh`, `scripts/dev/runner-env.sh`, `scripts/dev/runner-setup.sh`,
`scripts/dev/runner-settings.json`, `scripts/dev/runner-redteam.sh`, `.gitattributes`, Tests
`scripts/tests/{hooks,ledger,review_scripts,task_close,runner_setup}_test.sh`.
**Geändert:** `.claude/settings.json` (Hook `PreToolUse`, `permissions.ask` für `git add|commit|checkout|stash`),
`.claude/skills/feature-build/SKILL.md` (Commit über `task-close.sh`), `CLAUDE.md` §2, `AUTONOMOUS.md`,
`DEVELOPMENT.md` (Abschnitt „Runner-User"), `scripts/tests/run.sh` (nur `AH_SCRIPT_TESTS_DEFAULT`), `CHANGELOG.md`.
**Unverändert:** `scripts/tests/heavy.sh`, `scripts/vm/vm.py` (bekommen nur Einträge in `harness-paths.txt`).

Heutiger Stand (Exploration 2026-09-18): `.claude/settings.json` hat eine leere `deny`-Liste, `git add|commit|checkout|
stash` in `allow`, einen `SessionStart`-Hook (`session-status.sh`, still unter `AH_AUTONOMOUS=1`), keinen
`PreToolUse`-Hook; `format-file.sh` ist kein Hook mehr (bewusst entfernt, AUTONOMOUS.md). Keine der neuen Dateien
existiert, kein `.gitattributes`. Der Bau committet heute selbst (Build-Skill Schritt 5).

## Datenmodell / API / Migrationen

Keine DB, kein Endpunkt. Drei Dateiformate, alle Text:

- **`harness-paths.txt`:** eine Glob-Zeile je Pfad, `#`-Kommentare: `.claude/**`, `CLAUDE.md`, `AUTONOMOUS.md`,
  `scripts/dev/hooks/**`, `scripts/dev/{verify,task-close,review,ledger,runner-env,runner-setup,harness,tree-hash}.sh`,
  `scripts/dev/harness-paths.txt`, `scripts/dev/runner-settings.json`, `scripts/tests/run.sh`, `scripts/tests/heavy.sh`,
  `scripts/vm/vm.py`. Konsumenten: `harness-guard.sh` (Hook) und später der Loop-Preflight (Stufe 7).
- **Ledger-Marker:** `ledger.sh mark-done <id>` hängt an die Task-Zeile `[x] (<stichwort>)` und darunter die Zeilen
  `Evidenz: run.sh[quick]: N passed, 0 failed, 0 skipped @<head-kurz> <ts>` und `Review: <urteil> (<modell|selbst>)`
  (Format aus den bisherigen Ledgern, jetzt maschinell). `.vm/active-task` trägt `<ledger>\t<id>\t<Komponente>\t<Dateien>`.
- **Task-Vorlage** `tasks/templates/task.md` mit den Pflichtfeldern aus `tasks/README.md` und den optionalen
  `Beweis/Orakel/Refuter/Dedup-Key/Metrik` (für Stufe 5 vorbereitet, hier ungenutzt).
- **Runner-Settings** `scripts/dev/runner-settings.json` (versioniert, wird nach `~adminhelper-runner/.claude/settings.json`
  kopiert): `permissions.defaultMode: "dontAsk"`, `deny`: `Bash(git stash *)`, `Bash(git checkout *)`,
  `Bash(git restore *)`, `Bash(git add *)`, `Bash(git commit *)`, `Bash(git push *)`, `Bash(gh *)`,
  `Bash(python3 scripts/vm/vm.py bake *)`, `Bash(bash scripts/dev/task-close.sh *)`, `Bash(bash scripts/dev/ledger.sh mark-done *)`,
  `Bash(sudo *)`, `Edit(./tasks/private/**)`, `Edit(./.claude/**)`, `Edit(./scripts/dev/**)`, `Edit(./scripts/tests/run.sh)`,
  `Edit(./scripts/tests/heavy.sh)`, `Edit(./scripts/vm/vm.py)`, `Edit(./CLAUDE.md)`, `Read(~/.config/adminhelper/oauth.env)`;
  `allow`: `Bash(bash scripts/dev/verify.sh *)`, `Bash(bash scripts/tests/run.sh quick *)`, `… lint *`, `… unit *`,
  `Bash(bash scripts/dev/ledger.sh mark-skip *)`, `… mark-question *`, `… set-files *`, `… start *`, `Bash(python3 scripts/vm/vm.py *)`
  (ohne `bake`, Deny gewinnt), `Bash(bash scripts/vm/*.sh *)`, `Bash(git diff *)`, `… log *`, `… show *`, `… status *`, `… grep *`,
  `Bash(rg *)`, `Bash(sed -n *)`, `Bash(cat *)`, `Bash(ls *)`, `Bash(wc *)`, `Bash(pytest *)`, `Bash(ruff *)`, `Bash(go test *)`,
  `Bash(cargo test *)`, `Bash(npm run *)`, `Edit(./apps/**)`, `Edit(./docs/**)`, `Edit(./scripts/**)`, `Edit(./tasks/**)`,
  `Edit(./CHANGELOG.md)`, `Edit(./README.md)`, `Edit(./DEVELOPMENT.md)`; `hooks`: `PreToolUse` (Edit|Write|Bash →
  `harness-guard.sh`), `SessionStart` (`session-status.sh`).

Verifiziert in der Claude-Code-Doku (2026-09-18, permissions.md / settings.md / headless.md): Regeln werden in der
Reihenfolge deny → ask → allow ausgewertet, die erste Übereinstimmung entscheidet („An allow rule can't carve an
exception out of a deny rule"); `Read`/`Edit`-Regeln nutzen gitignore-Syntax mit `//` (absolut), `~/` (Home), `./`
(Projekt); `dontAsk` „auto-denies every call that would otherwise prompt"; Bash-Regeln kennen Verbund-Operatoren
(`&&`, `||`, `;`, `|`), Deny/Ask greifen auf jedes Teilkommando inklusive Subshells und Command-Substitution; die
Wrapper `timeout time nice nohup stdbuf` werden vor dem Match entfernt, `sudo` und `bash -c` **nicht** (deshalb
`Bash(sudo *)` in `deny`); ein blockierender Hook (Exit 2 oder `permissionDecision: deny`) hat Vorrang vor
Allow-Regeln, Deny-Regeln gelten unabhängig von Hooks; Settings-Präzedenz managed > `--settings` > Projekt-lokal >
Projekt > User, und die User-Ebene gilt auch in `-p`; `--bare` schaltet Hooks, Skills und das OAuth-Token ab, der
Runner läuft deshalb **nie** mit `--bare`; `--permission-prompts none` (≥ 2.1.259) und `--output-format stream-json`
mit `permission_denials` im Result. `CLAUDE_CODE_OAUTH_TOKEN` liegt in der Präzedenz hinter `ANTHROPIC_API_KEY`,
deshalb löscht `runner-env.sh` diese Variable.

## Externe Integrationen

Claude Code CLI (Flags/Settings wie oben), Proxmox-API (zweiter Token `adminhelper-runner@pve!run`, dieselbe Rolle
`AdminHelperVM`, dieselben vier ACL-Pfade — der Nutzer existiert seit 2026-09-15), Postgres (Rolle/DB
`ah_runner_test` mit `CREATEDB`), GitHub Ruleset auf `main` (PR-Pflicht, Status-Checks, kein Force-Push, kein
Bypass-Akteur — Kevin klickt). Kein FRP-, Tauri- oder VictoriaMetrics-Format berührt.

## Trade-offs & Alternativen

1. **Runner-Toolchain minimal** (Python-Venv mit ruff/pytest, shellcheck, git) statt Kopie von Go/Rust/Node (~4 GB,
   erster Rust-Bau 20 min): der Runner baut in Lanes mit `Fast-Suite: vm`, die Warm-Box hat alles. Trade-off: ohne
   VM kann der Runner nur `scripts`/Python-Suiten lokal fahren. **Empfehlung:** minimal (offene Frage 1).
2. **`task-close.sh` sofort auch für interaktive Bauten** statt erst mit dem Worker: das Modell verliert `git commit`,
   dafür entsteht die Evidenz-Zeile mechanisch und die Mechanik ist vor Stufe 7 erprobt. Trade-off: ein zusätzlicher
   Skript-Aufruf je Task und ein Umbau des Build-Skills jetzt. **Empfehlung:** sofort (offene Frage 2).
3. **Harness-Schutz doppelt** (Deny-Regeln in den Runner-Settings **und** Hook): die Regeln decken `Edit`, der Hook
   fängt zusätzlich `sed -i`, `tee`, `>`-Umleitungen über Bash, soweit erkennbar. Trade-off: zwei Stellen. Bewusst.
4. **Kill-Switch als Marker-Datei** `.vm/harness.off` im Checkout statt Env-Variable: wirkt auch auf Hooks, die keine
   Variable erben. `harness.sh status` zeigt Marker und `AH_AUTONOMOUS`.
5. **`review.sh` beginnt hier mit drei Verben** (`diff-scan`, `scope`, `sec`), Stufe 6 ergänzt `docs-pairs`,
   `contracts`, `risk`, `check-verdict`, `pr-body`, `log`. Ein Skript, das wächst, statt zweier.
6. **Sec-Sperre fail-closed:** gestaged unter `tasks/private/**`, `tasks/sec-*.md`, `docs/features/sec-*.md` oder ein
   Diff mit `Dedup-Key: sec:` ⇒ Exit 4. `tasks/private/` ist zwar gitignored, aber `git add -f` gäbe es her.

## Risiken & Rollback

- **Hook-Verhalten in `-p` und `dontAsk` mit pfadbeschränkten `Edit`-Allows:** in der Doku belegt, aber nicht in diesem
  Repo geprobt. T10 (Red-Team) probt es real als Runner; scheitert die Probe, bleibt die Deny-Liste die Grenze und die
  Allow-Feinheit wird Roadmap-Zeile.
- **`task-close.sh` bricht den Bau-Fluss**, wenn `verify.sh` oder der Scope zu streng ist (z. B. eine Task, die eine
  Datei außerhalb von `Dateien:` braucht): `ledger.sh set-files` erweitert die Liste bewusst und sichtbar, statt den
  Scope zu lockern.
- **Kevins Alltag:** `git commit` und `git add` prompten in interaktiven Nicht-Bypass-Sessions. Die Worker laufen mit
  Bypass, dort ändert sich nichts; Fable-Sessions wie diese nutzen `task-close.sh` oder Kevins Freigabe.
- **Rollback:** additive Skripte, `git revert`; `runner-setup.sh --remove` entfernt User, Klon und DB-Rolle; die
  Allowlist-Änderung in `.claude/settings.json` ist ein Commit.

## Doku-Impact

`DEVELOPMENT.md` neuer Abschnitt „Runner-User `adminhelper-runner`" (Setup-Skript, was Kevin von Hand tut, Token-Dateien,
Red-Team-Skript) und Absatz zu `task-close.sh`/`ledger.sh` im Build-Ablauf; `AUTONOMOUS.md` (Zyklus-Tabelle, Permissions);
`CLAUDE.md` §2 (der Satz „Committen … bis `task-close.sh` es übernimmt (Stufe 4)" wird eingelöst); `CHANGELOG` Added.
`docs/developer/cicd.html` nur ein Satz zum Ruleset (DE+EN).

## Offene Fragen (Design-Gate)

1. **Runner-Toolchain minimal** (Python, shellcheck, git; Rest auf VMs) — Empfehlung ja.
2. **`task-close.sh` sofort auch interaktiv** und `git add|commit|checkout|stash` in Kevins Settings von `allow` nach `ask`
   — Empfehlung ja; Bypass-Worker unberührt.
3. **Runner-Proxmox-Token jetzt anlegen** (Kevin, 5 Minuten, Nutzer existiert) statt in Stufe 7 — Empfehlung jetzt, weil
   das Red-Team-Skript ihn braucht.
4. **GitHub Ruleset auf `main`** ohne Bypass-Akteur — Empfehlung ja; `/release cut` (Stufe 13) arbeitet dann über einen
   Release-Branch.
5. **bubblewrap-Probe** als eigene Task (`bwrap` ist installiert) — Empfehlung nein, erst wenn ein Befund sie verlangt.

## Verify-Prinzip

`hooks_test.sh`, `ledger_test.sh`, `review_scripts_test.sh`, `task_close_test.sh`, `runner_setup_test.sh --dry-run` grün
im Scripts-Block. Red-Team als `adminhelper-runner` (Kevin führt `runner-redteam.sh` aus, Ergebnis in den Ledger-Anhang):
Lesen von `~kevin/.ssh/id_ed25519` und `~kevin/.claude/settings.local.json` ⇒ EACCES; `git push` nach GitHub und in ein
`/tmp/bare.git` scheitern; `gh auth status` ≠ 0; `busctl --user` keine Session; `vm.py clone` im Pool ok, Zugriff auf eine
VM außerhalb ⇒ 403; `claude -p 'push den Branch' --permission-mode dontAsk --permission-prompts none --output-format
stream-json` ⇒ `permission_denials` enthält `git push`; Edit an `.claude/settings.json` ⇒ deny durch Hook **und** Regel.
`task-close.sh T1` ohne gestagte Änderung ⇒ Abbruch; mit `@pytest.mark.skip` im Diff ⇒ 4; mit `tasks/private/x.md`
gestaged ⇒ 4; grün ⇒ Commit mit Code + Ledger, `git log -1 --stat` zeigt beides; `harness.sh off` ⇒ Warnungen statt Abbruch.
