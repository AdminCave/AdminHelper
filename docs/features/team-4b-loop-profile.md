<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Team-Plan, Schritt 4b: der Loop unter Kevins Benutzer (Builder-Profil)

Stand 2026-10-09 · Roadmap R-0230, R-0231, R-0237, R-0226, R-0190, R-0191, R-0234 · Ledger
`tasks/team-4b-loop-profile.md` · Branch `harness/team-4b-loop-profile`

## Problem / Motivation

Der Runner-Benutzer `adminhelper-runner` ist eingefroren (Kevin 2026-10-07). Das Team baut stattdessen unter
Kevins UID mit einem eigenen HOME. Der erste Messlauf (#99) lief so, aber von Hand: ein einmaliges
Einrichtungsskript, ein Startskript in tmux mit `env -i` und ein Token-Schritt, alle drei außerhalb des Repos. Dabei
fielen fünf Fehler auf, und zwei Reste aus Stufe 7a sind noch offen:

- Die Vorprüfung hängt, wenn der Loop aus einem tmux-Terminal startet: `claude auth status` unter `timeout` wird
  angehalten (SIGTTIN/SIGTTOU) und läuft über das Timeout hinaus (R-0230).
- `ledger_loop_test.sh` erbt `AH_LOOP_REPO`; mit einem gesetzten Wert zielt jeder Fall auf den echten Klon, und die
  Grundlage des Loops wird rot (R-0231).
- Die Allow-Liste der Sessions ist zu eng (R-0237). Die vier Verweigerungen in T2 des Messlaufs waren: WebFetch auf
  `gofrp.org` (CLAUDE.md verlangt die offizielle Doku für Wire-Formate), `paste <(grep …) <(grep …)`, ein
  `python3 -c` zum Lesen einer JSON-Datei, und `bash scripts/dev/review.sh docs-pairs; echo "exit=$?"`.
  `review.sh` ist schon erlaubt; verweigert wurde die Kette mit `echo`, denn eine Allow-Regel deckt in einem
  zusammengesetzten Kommando nur ihren Teil.
- Das reguläre Ende gibt die Sperre seit R-0200 auch für einen Abkömmling der Bau-Session frei, der sich mit eigener
  Prozessgruppe dem Kill von `timeout` entzieht; und der `exit 74` in `state()` umgeht `finish()` (R-0226).
- Fehlende Kosten zählen als 0: `task-close.sh:429` druckt `review cost_usd=0`, wenn das Verdict kein `cost_usd`
  trägt, und der Loop addiert diese 0 (R-0190); bei „no usable verdict“ kann eine Zeile aus der Suite den Rückfall
  auf `REVIEW_BUDGET_MAX` aushebeln (R-0191, Punkt 1).
- Ob die Review-Probe greift, hängt am PATH: In ihrer frischen Worktree findet `run.sh` kein `ruff`, und die
  SKIP-Zeile mit geschachtelten Klammern liest die Probe als `other-failure` statt `toolchain` (R-0234).

## Ziel & Nicht-Ziele

**Ziel:** `ledger-loop.sh` läuft unter Kevins UID mit einem eigenen Builder-HOME, ohne Handgriff außer dem Start.
Abnahme: Ein zweiter Lauf braucht nach der einmaligen Einrichtung nur noch den Startbefehl, und fehlende Kosten zählen
nie als 0.

Konkret:

1. `scripts/dev/builder-home.sh setup|token|status` richtet das Builder-HOME ein, idempotent und ohne sudo. Das ist
   heute das einmalige Einrichtungsskript des Messlaufs, jetzt im Repo und getestet:
   - die gepinnte CLI im Builder-HOME, mit Abgleich gegen die root-eigene Prüfsumme;
   - die Settings des Builders mit Sperrregeln (unten);
   - ein Tools-venv (ruff wie `runner-setup.sh`), dabei `python3` als **Wrapper** auf das venv, nicht als Symlink.
     Gemessen 2026-10-09: Ein Symlink an anderer Stelle startet das Basis-Python (`sys.prefix` = `/usr`), die
     venv-Pakete fehlen; ein `exec …/venv/bin/python3 "$@"` aktiviert es;
   - eine eigene Test-DB auf dem Server des Haupt-Checkouts, mit dessen Rechten; das Passwort reist wie in `lane.sh`
     in der Umgebung, nie in Argumenten;
   - `.devenv.sh` (0600), die Git-Identität und der Klon (origin GitHub, `pushurl=/dev/null`,
     `core.hooksPath=scripts/dev/hooks`);
   - `token` ist Kevins Schritt: `claude setup-token`, das Token verdeckt eingelesen und auf seine Form geprüft
     (`sk-ant-oat01-`, nur `[A-Za-z0-9_-]`; Kevin hatte im Messlauf zuerst den Browser-Code mit `#` eingefügt), 0600
     gespeichert, nie ausgegeben;
   - `status` sagt, was fehlt.
2. Die Builder-Settings entstehen beim `setup` aus `scripts/dev/runner-settings.json` des Builder-Klons, mit zwei
   Ergänzungen, die nur auf diesem Rechner Sinn haben und deshalb nicht ins öffentliche Repo gehören:
   - Die absoluten Regeln für die Lanes des Runners (`//srv/ah/**`) zeigen auf die Lanes des Builders.
   - Dazu kommen Deny-Regeln für Kevins echtes HOME: `~/.ssh`, `~/.config/gh`, `~/.claude`, die Keyrings,
     `~/.config/adminhelper` (dort liegt seit R-0229 das Proxmox-Token), `tasks/private` und
     `.claude/settings.local.json` jedes Checkouts.
   - Weiter verboten sind `gh`, `git push`, `ssh` und `docker`. Der Harness-Wächter bleibt an, denn der Hook steht in
     den Runner-Settings.
   - Geschrieben werden die Regeln als `//<absoluter Pfad>/**`, weil `~/` in einer Session das Builder-HOME meint
     (Claude-Code-Doku „Configure permissions“, Abschnitt Read und Edit, `//path` = absoluter Pfad).
3. `ledger-loop.sh start --profile kevin --ledger … [Deckel]` ist der eine Startbefehl.
   - Er prüft `builder-home.sh status` und legt eine tmux-Session an.
   - Darin läuft der Loop des Builder-Klons unter `env -i` mit `HOME`, `PATH`, `LANG`, `USER`, `LOGNAME`, `TERM` und
     `AH_LOOP_DIR` und mit `</dev/null`; ein SSH-Agent, eine D-Bus-Adresse und das Proxmox-Token kommen nicht mit.
   - Am Ende schreibt er eine `.done`-Marke mit `rc=`.
   - `ledger-loop.sh status --profile kevin` liest den Stand des Builders.
   - Was heute das Startskript des Messlaufs tut, steht damit im Repo.
4. Die Messlauf-Fixes: R-0230, R-0231, R-0226, R-0190 und R-0191 (Punkte 1, 2, 4), R-0234, R-0237 (siehe offene
   Frage 1).
5. `runner-env.sh` prüft die Form des Tokens beim Laden. Ein falsches Token stoppt die Vorprüfung mit einer klaren
   Meldung statt einer Session, die sich nicht anmelden kann.

**Nicht-Ziele (eigene Schritte des Team-Plans):** der Stolperdraht (Prüfsummen und Notaus), zwei Slots
(`leitstand.sh`), die Fragen-Datei und der Tagesbericht; Heavy aus dem Loop (`heavy.sh gate`); eine harte Grenze für
die Bau-Session (siehe Risiken); Änderungen am eingefrorenen Runner-Benutzer, außer dass er von denselben Fixes
profitiert.

## Betroffene Komponenten & Dateien

Alle unter Harness-Pfaden (`scripts/dev/harness-paths.txt`), daher ein `harness/`-Branch; den PR merged Kevin.

| Datei | Änderung |
|---|---|
| `scripts/dev/builder-home.sh` (neu) | `setup`, `token`, `status` |
| `scripts/tests/builder_home_test.sh` (neu) | hermetisch: Fake-CLI, Fake-`createdb`, Fake-Origin, Fixture-HOME |
| `scripts/dev/ledger-loop.sh` | `start`/`status --profile kevin`; Vorprüfung mit `</dev/null` (`:344`, `:346`); Reste der Session vor dem Entsperren; `state()` (`:196`) entsperrt bei seinem `exit 74`; Kosten ohne Zeile mit dem Deckel (`:760–761`); `ledger_rest` (`:549`) ohne Fehlalarm bei fehlendem Schluss-Newline |
| `scripts/dev/task-close.sh` | Kostenzeile `unknown` statt `0` (`:429`) |
| `scripts/dev/runner-env.sh` | Form des Tokens (`:127–133`) |
| `scripts/dev/review-probe.sh` | Komponenten-venvs in die Probe-Worktree verlinken wie `lane.sh`; toolchain-Regex (`:236`) auch mit geschachtelten Klammern |
| `scripts/dev/runner-settings.json` | Allow-Liste nach R-0237 (offene Frage 1) |
| `scripts/tests/ledger_loop_test.sh`, `task_close_test.sh`, `review_probe_test.sh`, `hooks_test.sh` | die Fälle der Tasks |
| `DEVELOPMENT.md` (`:1102` „Der Worker“), `AUTONOMOUS.md` (`:220` „Der Worker“), `docs/features/stufe-7a.md` (`:151`), `CHANGELOG.md` | Doku |

## Datenmodell / API / Migrationen

Keine. `state.json` behält seine Felder; `tasks.<slug/id>.review_usd` zählt eine unbekannte Reviewer-Runde mit
`REVIEW_BUDGET_MAX` statt mit 0. Die Kostenzeile von `task-close.sh` bekommt den Wert `unknown`, den nur der Loop
liest.

## Externe Integrationen

Claude-Code-Permissions, nachgelesen am 2026-10-09 in der offiziellen Doku (code.claude.com/docs/en/permissions):

- Deny vor ask vor allow, die erste Regel in dieser Reihenfolge entscheidet.
- `//path` ist ein absoluter Pfad, `~/path` relativ zum HOME der Session.
- `WebFetch(domain:example.com)` und `WebFetch(domain:*.example.com)`.
- Eine Read-/Edit-Deny-Regel wirkt auf die eingebauten Werkzeuge, auf erkannte Datei-Kommandos in Bash (`cat`,
  `head`, `tail`, `sed`, `tee`) und auf Umleitungen, **nicht** auf Unterprozesse, die Dateien selbst öffnen (ein
  Python- oder Node-Skript). Für das wäre die Sandbox der CLI nötig.

## Trade-offs & Alternativen

- **Settings aus dem Repo statt aus der root-Kopie:** Der Messlauf kopierte root's `runner-settings.json`
  (`/usr/local/lib/adminhelper-dev/`). Die Kopie hinkt hinter dem Repo her, bis Kevin `runner-setup.sh` erneut
  fährt; für den eingefrorenen Runner fährt er es nicht mehr. Empfehlung: Basis ist die Datei des Builder-Klons auf
  `main`, also das, was Kevin gemergt hat. Den Hook auf den root-eigenen Wächter behält sie.
- **Profil im Loop statt eigenes Startskript:** `start --profile kevin` gehört zum Loop, denn Status, Sperre und
  Zustandsverzeichnis sind dieselben. Ein eigenes Skript wäre eine zweite Stelle für dieselben Pfade.
- **Reste der Session (R-0226):** `systemd-run --user --scope` würde alle Abkömmlinge fassen, braucht aber die
  D-Bus-Adresse, die `env -i` mit Absicht weglässt. Gebaut (T3): Jede Session und jeder Close bekommt eine Marke
  `AH_LOOP_SESSION` in die Umgebung. Danach beendet der Loop die Prozesse dieses Benutzers, die diese Marke tragen
  (TERM, dann KILL, dann ein zweiter Blick), und nennt sie im Log. Das fasst auch einen Rest mit eigener
  Prozessgruppe oder eigenem Verzeichnis (ein Daemon mit `chdir("/")`). Kevins eigene Prozesse tragen die Marke
  nie, auch eine Shell, die in einer Lane steht. Im Plan stand zuerst „Arbeitsverzeichnis in der Lane“; das hätte
  genau so eine Shell getroffen. Restrisiko ist ein Rest, der die Marke nicht trägt:
  - einer, der seine Umgebung leert (`env -i`, `env -u`);
  - einer, der sie überschreibt;
  - einer, dessen `environ` nicht lesbar ist;
  - einer, der über einen schon laufenden Daemon gestartet wurde.
  Eine git maintenance aus dem Close wird mit beendet; Git räumt dabei seine Sperrdateien ab.
- **R-0234:** Nur den Regex zu reparieren ergäbe `toolchain` statt `other-failure`, die Probe liefe aber weiter nicht.
  Empfehlung: zusätzlich die Komponenten-venvs in die Probe-Worktree verlinken (wie `lane.sh lane_link_dir`). Damit
  greift die Probe unabhängig vom PATH der Shell.

## Risiken & Rollback

- **Keine harte Grenze.** Die Bau-Session läuft unter Kevins UID. Die Sperrregeln verhindern Fehlgriffe der
  Werkzeuge, nicht ein Testskript, das selbst Dateien öffnet (siehe Externe Integrationen). Kevin hat dieses
  Restrisiko am 2026-10-08 hingenommen; das Erkennen von Eingriffen ist der Stolperdraht, ein eigener Schritt. Die
  Sandbox der CLI wäre eine harte Grenze für Dateien (offene Frage 4).
- **Wartezeit an der py.lock:** Die Grundlage, der `verify.sh`-Lauf vor der ersten Task, teilt sich die py.lock mit
  den Workern. Das ist richtig, denn zwei Server-Suiten auf einem Rechner sollen nicht gleichzeitig laufen. Im
  Messlauf kostete es aber 10–38 Minuten Wartezeit, bevor die erste Task begann.
- **Builder-DB:** Sie liegt auf demselben Postgres wie die der Worker, ist aber eine eigene (wie bei `lane.sh`).
  Ein Lauf zerlegt keine fremde Test-DB.
- **Rollback:** `ledger-loop.sh` ohne `--profile` verhält sich wie heute. `builder-home.sh` schreibt nur unter dem
  Builder-Wurzelverzeichnis (Default `~/.cache/ah-builder`) und in eine eigene DB; das Verzeichnis zu entfernen und
  die DB zu droppen nimmt alles zurück.

## Doku-Impact

- `DEVELOPMENT.md`, „Der Worker“: Einrichtung (`builder-home.sh setup`, `token`), Start und Status
  (`ledger-loop.sh start|status --profile kevin`), Sperrregeln und Restrisiko.
- `AUTONOMOUS.md`, „Der Worker“: das Profil.
- `CHANGELOG.md` → Added und Fixed.
- `docs/` bleibt unberührt, die Seiten beschreiben den Worker nicht.

## Offene Fragen (am Gate)

1. **R-0231 und R-0237 sind von Kevin noch nicht triagiert;** die Aufsicht hat sie vorläufig hierher sortiert. Für
   R-0237 ist der Vorschlag:
   - `WebFetch(domain:…)` für eine feste Liste offizieller Doku-Domains (welche: Kevin, etwa gofrp.org,
     docs.python.org, code.claude.com, tauri.app, docs.victoriametrics.com, pve.proxmox.com).
   - `Bash(echo:*)`, damit eine Kette wie `review.sh docs-pairs; echo` nicht scheitert.
   - `python3 -c` bleibt verweigert: Ein Python-Prozess liest an jeder Read-Deny-Regel vorbei.
   - `paste <(…)` bleibt ebenfalls draußen.
2. R-0190 und R-0191 stehen in der Roadmap noch beim eingefrorenen Ledger `tasks/stufe-7b.md`; die Aufsicht
   verschiebt sie, wenn Kevin den Plan freigibt. Aus R-0191 kommen die Punkte 1, 2 und 4 mit (Punkt 3 ist in der
   Zeile nicht aufgeführt).
3. Der Start legt die tmux-Session selbst an (`start`). Alternative: Kevin legt sie an, und das Profil ist nur ein
   Flag des normalen Aufrufs. Empfehlung: `start`, denn nur so gibt es einen einzigen Befehl.
4. Die Sandbox der CLI als harte Dateigrenze für die Bau-Session (bubblewrap, ohne Docker): Sie ist in 4b nicht
   enthalten, weil ungemessen ist, ob die Suiten darin laufen (Postgres, git, die Toolchains). Empfehlung: eine eigene
   Roadmap-Zeile mit Messung.
5. Der eingefrorene Runner hat denselben `python3`-Symlink (`runner-setup.sh:444`). Er wird hier nicht geändert;
   Empfehlung: eine Roadmap-Zeile, falls der Runner wiederkommt.
