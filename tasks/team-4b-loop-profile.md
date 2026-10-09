<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Team-Plan 4b: der Loop unter Kevins Benutzer (Builder-Profil) — Task-Ledger
Status: aktiv · Branch: harness/team-4b-loop-profile · Commit-Granularität: pro Task · Review: pro Task (feature-review; Harness ⇒ Reviewer Opus) · Modell: Opus
Freigabe: Kevin, 2026-10-09 (Stufen-Plan, im Chat mit der Aufsicht). Offene Fragen: 1 R-0231 und R-0237 angenommen (Kevin); WebFetch-Domains (Kevin): gofrp.org, docs.python.org, code.claude.com, tauri.app, docs.victoriametrics.com, pve.proxmox.com; 2 R-0190/R-0191 hängt die Aufsicht von 7b auf dieses Ledger um (erledigt); 3 der Start legt die tmux-Session selbst an (Aufsicht); 4 die CLI-Sandbox wird eine eigene Roadmap-Zeile (Aufsicht); 5 der python3-Symlink des eingefrorenen Runners bleibt liegen (Aufsicht)
Spec: docs/features/team-4b-loop-profile.md (Roadmap R-0230, R-0231, R-0237, R-0226, R-0190, R-0191, R-0234)
Heavy: none — Shell, Python und Settings unter scripts/dev mit hermetischen Tests; kein Stack-, Gateway-, PKI- oder Install-Pfad. Die Abnahme (ein zweiter Lauf ohne Handgriff außer dem Start, keine Kosten als 0) ist ein echter Loop-Lauf: Kevins Start, nach dem Merge.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-09 von Worker A für die Aufsicht (adminhelper-ac); ein Stufen-Plan, die Freigabe ist Kevins.
Zeilenangaben main@81c8efe9; beim Bau an Symbolen orientieren. Die Vorlage sind die Einrichtungs-, Start- und
Token-Skripte des ersten Messlaufs (#99), die außerhalb des Repos liegen.

### T1 — Vorprüfung ohne Terminal: `claude --version` und `auth status` mit `</dev/null` (R-0230)  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @7d8c707c 2026-10-09T12:53:37+02:00
Review: approve (opus)
Änderung: Die zwei CLI-Aufrufe der Vorprüfung (`ledger-loop.sh:344` und `:346`) lesen von `/dev/null`. In einem
tmux-Terminal hielt `timeout` sonst `claude auth status` an (SIGTTIN, State T), über das Timeout hinaus. Test: Die
Fake-CLI in `ledger_loop_test.sh` schreibt bei `--version` und `auth`, woher ihr stdin kommt
(`readlink /proc/self/fd/0`); beide Aufrufe zeigen `/dev/null`, auch wenn der Test den Loop mit einem stdin startet,
das nie endet.
Rot vorher: Ohne die Änderung zeigt stdin auf das stdin des Loops, nicht auf `/dev/null`.
Beweis: Messlauf 1, Aufsicht 2026-10-08 · Versuch 1: `claude auth status` 2:24 min in `do_signal_stop` (State T); Versuch 2 mit `</dev/null` läuft durch
Dedup-Key: bug:scripts:ledger-loop.sh:preflight-tty
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T2 — `ledger_loop_test.sh` hermetisch gegen ein geerbtes `AH_LOOP_REPO` (R-0231)  [x]
Komponente: scripts · Dateien: scripts/tests/ledger_loop_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @b405c953 2026-10-09T13:10:13+02:00
Review: approve (opus)
Änderung: Der Test nimmt `AH_LOOP_REPO` in seine `unset`-Zeile (`:32`). Die Loop-Aufrufe (`loop()` bei `:281`
und der Signal-Fall bei `:340`) setzen ihn nicht und dürfen ihn deshalb nicht erben. Der Beweis ist die Revert-Probe
im Bau: `AH_LOOP_REPO` auf einen falschen Pfad gesetzt, dann `bash scripts/tests/ledger_loop_test.sh` — ohne die
Änderung rot, mit ihr grün. Kein Fall, der den Test in sich selbst noch einmal startet.
Rot vorher: Mit gesetztem `AH_LOOP_REPO` sind rund 25 Fälle rot (`no branch feature/<fixture> on origin`).
Beweis: Messlauf 1, Aufsicht 2026-10-08 · Versuch 2: Grundlage rot, scripts (hermetic) mit ~25 FAIL in ledger_loop_test
Dedup-Key: bug:scripts:ledger_loop_test.sh:inherited-loop-repo
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T3 — Reste einer Session beenden, bevor der Loop weitergeht oder entsperrt (R-0226)  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh, docs/features/team-4b-loop-profile.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @af22cb0a 2026-10-09T13:37:24+02:00
Review: approve (opus)
Änderung: Nach jeder Session und vor `finish()` beendet der Loop die Prozesse dieses Benutzers, deren
Arbeitsverzeichnis in der Lane liegt (`/proc/<pid>/cwd`): erst TERM, nach einer kurzen Frist KILL. Jeder beendete
Prozess steht mit pid und Kommandozeile (gekürzt) im Log. Auch ein Rest mit eigener Prozessgruppe wird so gefasst.
Dazu die zwei nits der Zeile: Der `exit 74` in `state()` (`:196`) entsperrt vorher (`flock -u 9`, wie `finish()`),
und `kill -HUP` im Test schreibt nichts mehr auf stderr. Test: Die Fake-Session startet mit `setsid` einen Schläfer in
der Lane, der über das Ende der Session lebt. Danach ist er beendet und im Log genannt, und ein zweiter Lauf startet.
Rot vorher: Der Schläfer überlebt das Ende der Session und den Lauf.
Beweis: Review R-0200 Runde 2, Worker A, 2026-10-07 · harness/r1q-flake@fd1f00be
Dedup-Key: ref:scripts:ledger-loop.sh:lock-orphan-session
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; die Spec nennt das Restrisiko eines Rests, der sein Verzeichnis wechselt)

### T4 — Fehlende Reviewer-Kosten zählen mit dem Deckel, nie als 0 (R-0190, R-0191 Punkt 1)  [x]
Komponente: scripts · Dateien: scripts/dev/task-close.sh, scripts/dev/ledger-loop.sh, scripts/tests/task_close_test.sh, scripts/tests/ledger_loop_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @e393fcc2 2026-10-09T14:01:59+02:00
Review: approve (opus)
Änderung:
- `task-close.sh` (`:429`) druckt `review cost_usd=unknown round=<n>`, wenn das Verdict kein brauchbares
  `cost_usd` trägt, statt `0`.
- Der Loop (`ledger-loop.sh:760–761`) zählt `unknown`, eine fehlende Zeile und jedes „the reviewer gave no usable
  verdict“ mit `REVIEW_BUDGET_MAX`. Bei „no usable verdict“ gilt das immer, auch wenn eine Zeile aus der Suite einen
  Wert drückt.

Tests:
- `task_close_test.sh`: ein Verdict ohne `cost_usd` ergibt `unknown`.
- `ledger_loop_test.sh`: `unknown` ergibt 15 $ in `state.json` (`review_usd` und Summe). „no usable verdict“ ergibt
  15 $, auch hinter einer Suite-Zeile `review cost_usd=0`.

Rot vorher: `unknown` gibt es nicht; ein fehlender Wert zählt 0.
Beweis: Worker B, Reviewer-r2 Stufe 7a T14, 2026-10-05 · `task-close.sh:429` druckt `0` für ein fehlendes `cost_usd` (Code-Lesung, main@81c8efe9)
Dedup-Key: ref:scripts:task-close.sh:missing-cost-zero
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; die Regel „unbekannte Kosten zählen mit dem Deckel“ steht schon in AUTONOMOUS.md)

### T5 — `ledger_rest` ohne Fehlalarm, die Doku nennt Schwere, Datei und Pfad (R-0191 Punkte 2 und 4)  [x]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh, docs/features/stufe-7a.md, AUTONOMOUS.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @19ad07bc 2026-10-09T14:54:26+02:00
Review: approve (opus, round 2)
Änderung: `ledger_rest` (`ledger-loop.sh:549`) vergleicht den Rest des Ledgers so, dass ein fehlender Schluss-Newline
nach einem legitimen `set-files` keinen Fehlalarm „the build session changed the ledger outside its own task“ gibt.
Konkret: ein Newline am Dateiende wird vor dem Hashen ergänzt. `docs/features/stufe-7a.md:151` und
`AUTONOMOUS.md:251` sagen „`[?]` mit der Schwere, der Datei und dem Pfad des Verdicts“ statt „mit dem ersten Blocker“.
Test: Ein Ledger ohne Schluss-Newline plus eine Session, die `set-files` ruft, ergibt keinen Block wegen „outside its
own task“.
Rot vorher: Der Fall wird als Eingriff außerhalb der Task blockiert.
Beweis: Worker B, Reviewer Stufe 7a T14, 2026-10-05 · harness/stufe-7a@10815978 (Code-Lesung)
Dedup-Key: ref:scripts:ledger-loop.sh:t14-rest
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/features/stufe-7a.md, AUTONOMOUS.md (Wortlaut)

### T6 — Die Probe greift ohne `ruff` auf dem PATH (R-0234)  [x]
Komponente: scripts · Dateien: scripts/dev/review-probe.sh, scripts/tests/review_probe_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @4a7e1d91 2026-10-09T15:18:41+02:00
Review: approve (opus)
Änderung: `review-probe.sh` verlinkt nach `git worktree add` die Komponenten-venvs des Aufrufers in seine Worktree,
Eintrag für Eintrag in ein echtes Verzeichnis, so wie `lane.sh lane_link_dir`. Damit findet `run.sh` `ruff` über die
Komponenten-venv. Dazu erkennt der toolchain-Regex (`:236`) auch eine SKIP-Zeile mit geschachtelten Klammern
(`ruff not installed (not on PATH, no component venv)`) als `toolchain` statt `other-failure`.
Tests in `review_probe_test.sh`:
- Die Fake-Suite sieht in der Probe-Worktree `apps/<c>/.venv` des Aufrufers.
- Eine SKIP-Zeile mit geschachtelten Klammern ergibt `toolchain`.
Rot vorher: Die venv fehlt in der Worktree, und die Zeile ergibt `other-failure`.
Beweis: Planung R-0227, Worker A, 2026-10-09 · `review-probe.sh server --commit d2a0c4c4 -- tests/test_enrollment_mint.py`: zweimal ohne ruff `other-failure`, einmal mit ruff `applicable: true, red_without_change: false`
Dedup-Key: bug:scripts:review-probe.sh:toolchain-path
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern)

### T7 — `runner-env.sh` prüft die Form des Tokens  [x]
Komponente: scripts · Dateien: scripts/dev/runner-env.sh, scripts/tests/hooks_test.sh, scripts/tests/ledger_loop_test.sh, scripts/tests/redteam_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @ac35dbda 2026-10-09T15:57:26+02:00
Review: approve (opus, round 2)
Änderung: `runner-env.sh` (`:127–133`) nimmt das Token nur in der Form `sk-ant-oat01-` gefolgt von
`[A-Za-z0-9_-]+`. Etwas anderes, etwa der Browser-Code mit `#`, endet mit Return ≠ 0 und einer Meldung, die die
Datei nennt und nie den Wert. Tests im Abschnitt `runner-env.sh` von `hooks_test.sh` (`:1252`), nur mit Platzhaltern:
- Ein Wert mit `#` wird abgelehnt.
- Ein Platzhalter in der richtigen Form wird angenommen.
- Die Meldung trägt den Wert nicht.
Rot vorher: Jeder Wert wird exportiert.
Beweis: Messlauf 1, 2026-10-08 · Kevin hatte zuerst den Browser-Code eingefügt; das Token-Skript des Messlaufs prüfte die Form deshalb selbst
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine in dieser Task (T11)

### T8 — Allow-Liste der Sessions nach dem Messlauf (R-0237)  [ ]
Komponente: scripts · Dateien: scripts/dev/runner-settings.json, scripts/tests/hooks_test.sh
Änderung: Nach der Antwort auf offene Frage 1 der Spec (Kevin triagiert R-0237):
- `WebFetch(domain:…)` für die Liste offizieller Doku-Domains, die Kevin festlegt.
- `Bash(echo:*)`.
- `python3 -c` und `paste <(…)` bleiben draußen, die Deny-Liste bleibt unverändert.
Tests im Abschnitt `runner-settings.json` von `hooks_test.sh` (`:1408`): Die Domains stehen als `domain:`-Regeln da,
kein blankes `WebFetch` und kein `domain:*`; `echo` ist erlaubt; `python3 -c` ist es nicht.
Rot vorher: WebFetch und `echo` fehlen in der Allow-Liste.
Beweis: Messlauf 1, Aufsicht 2026-10-09 · `loop/messlauf-1/T2.s1.json` `permission_denials`: WebFetch gofrp.org, `paste <(…)`, `python3 -c`, `review.sh docs-pairs; echo`
Dedup-Key: ref:scripts:runner-settings.json:loop-allow-list
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine in dieser Task (T11)

### T9 — `builder-home.sh setup|token|status`: das Builder-HOME ohne Handgriff  [ ]
Komponente: scripts · Dateien: scripts/dev/builder-home.sh (neu, SPDX), scripts/tests/builder_home_test.sh (neu, SPDX), scripts/tests/run.sh
Änderung: Nach der Spec, Ziel 1 und 2. `setup` ist idempotent und braucht kein sudo; ein zweites `setup` ändert
nichts, was schon stimmt. Es legt an:
- die Verzeichnisse mit 0700;
- die gepinnte CLI aus `runner-claude.version`, mit Abgleich gegen die root-eigene Prüfsumme (eine Abweichung ist
  eine Meldung, der Loop verweigert dann selbst);
- die Builder-Settings: `runner-settings.json` des Builder-Klons, die Lanes-Regeln auf die Builder-Wurzel umgeschrieben,
  dazu die absoluten Deny-Regeln für das echte HOME, `tasks/private` und `.claude/settings.local.json`, und Deny für
  `ssh` und `docker`. Der Wächter-Hook bleibt;
- das Tools-venv mit `ruff` in der Version von `runner-setup.sh`, dazu pytest, `python3` als Wrapper;
- die eigene Test-DB auf dem Server des Haupt-Checkouts (`createdb`, Passwort über die Umgebung wie in `lane.sh`);
- `.devenv.sh` (0600), die Git-Identität und den Klon (`pushurl=/dev/null`, `core.hooksPath`).

`token` ruft `claude setup-token`, liest das Token verdeckt, prüft die Form wie T7 und schreibt `oauth.env` (0600).
`status` nennt, was fehlt, mit Exit ≠ 0. Keine Ausgabe nennt ein Passwort oder ein Token.

`builder_home_test.sh` ist in `AH_SCRIPT_TESTS_DEFAULT` von `run.sh` registriert und arbeitet mit Fake-CLI,
Fake-`createdb`, Fake-Origin und einem Fixture-HOME. Geprüft wird:
- Modi, Settings (die Deny-Regeln absolut, keine `//srv/ah`-Regel mehr, der Hook da);
- der Wrapper aktiviert das venv;
- ein zweites `setup` lässt alles, wie es ist;
- `token` lehnt einen Wert mit `#` ab;
- `status` meldet ein fehlendes Token;
- in keiner Ausgabe steht der Platzhalter-Wert.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine in dieser Task (T11)
Abhängt von: T7, T8

### T10 — `ledger-loop.sh start|status --profile kevin`: der eine Startbefehl  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger-loop.sh, scripts/tests/ledger_loop_test.sh
Änderung: Nach der Spec, Ziel 3. Ablauf von `start --profile kevin --ledger … [Deckel]`:
- Es prüft `builder-home.sh status` (Exit ≠ 0: Meldung, kein Start) und eine schon laufende tmux-Session
  (Meldung, kein zweiter Start).
- Es legt die tmux-Session an. Darin läuft `ledger-loop.sh` des Builder-Klons unter `env -i` mit `HOME`, `PATH`,
  `LANG`, `USER`, `LOGNAME`, `TERM` und `AH_LOOP_DIR` und mit `</dev/null`.
- Die Ausgabe geht in ein Log unter dem Loop-Verzeichnis, am Ende eine `.done`-Marke mit `rc=`.
- `status --profile kevin` liest `state.json` des Builders.
- Ohne `--profile` ist alles wie heute.

Tests mit einer Fake-tmux, die den Befehl ausführt:
- Die Umgebung der Bau-Session (`FIXTURE_ENVLOG`) trägt nur die genannten Namen plus das, was `runner-env.sh`
  setzt; kein `SSH_AUTH_SOCK`, kein `DBUS_SESSION_BUS_ADDRESS`, kein `AH_PVE_*`, auch wenn der Aufrufer sie hat.
- stdin ist `/dev/null`, die `.done`-Marke trägt `rc=`.
- Ein zweiter `start` neben einer laufenden Session wird verweigert.
- Ein fehlendes Token stoppt vor dem Start.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine in dieser Task (T11)
Abhängt von: T1, T9

### T11 — Doku: Builder-Profil, Einrichtung, Start und Restrisiko  [ ]
Komponente: scripts · Dateien: DEVELOPMENT.md, AUTONOMOUS.md, CHANGELOG.md
Änderung: `DEVELOPMENT.md`, „Der Worker“ (`:1102`):
- die Einrichtung (`builder-home.sh setup`, dann `token`) und der Start und Status
  (`ledger-loop.sh start|status --profile kevin`);
- die Sperrregeln und ihre Grenze: Sie halten die Werkzeuge der Session, nicht ein Testskript, das Dateien selbst
  öffnet;
- die Wartezeit an der py.lock vor der ersten Task (10–38 Minuten im Messlauf).

`AUTONOMOUS.md`, „Der Worker“ (`:220`): das Profil in einem Absatz. CHANGELOG `[Unreleased]`: Added (Profil, Einrichtung)
und Fixed (R-0230, R-0231, R-0226, R-0190/R-0191, R-0234).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: das ist die Doku-Task (`docs/` bleibt unberührt)
Abhängt von: T1–T10
