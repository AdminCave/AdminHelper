<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Runner-Vorarbeit 3: Messinstrument und Grenzen unabhängig vom geprüften Nutzer

Roadmap: R-0156, R-0158, R-0159, R-0160, R-0161, R-0162, R-0163 · Stand: main@587f3c7b · Geplant 2026-10-03 von der
Aufsicht, Entscheidungen Kevin 2026-10-03

## Problem / Motivation

Seit runner-vorarbeit-2 (#73) läuft das Red Team (`scripts/dev/runner-redteam.sh`) aus einer root-eigenen Kopie in
einer festen Umgebung. Einige Proben werten aber noch aus, was der geprüfte Nutzer `adminhelper-runner` selbst ändern
kann, und zwei Grenzen hängen an Dateien, die er schreiben kann:

- **Probe 4 (Hypervisor, R-0156)** ruft `python3 "$REPO/scripts/vm/vm.py"` aus dem Runner-Klon auf
  (`runner-redteam.sh:446`, `:450`). Ob die VM außerhalb des Pools abgewiesen wird, entscheidet damit Code aus dem Klon.
- **Die git-Proben (R-0162)** laufen im Runner-Klon und damit mit dessen Konfiguration und Hooks: die Push-Proben
  (`:389`, `:396`, `:409`), `git status --porcelain` vor und nach jeder Modellprobe (`:474`, `:483`) und
  `git diff --quiet -- CLAUDE.md` (`:557`). Gemessen (git 2.47.3, Wegwerf-Repo der Aufsicht): ein `pre-push`-Hook läuft
  auch bei `push --dry-run`, `core.fsmonitor` läuft bei `git status`, ein clean-Filter aus `.gitattributes` läuft bei
  `git status` und bei `git diff --quiet`. Konfiguration **lesen** (`:369`, `:379`) führt nichts aus.
- **Die D-Bus-Probe (R-0160)** prüft `busctl --user status` (`:430`). Ohne `XDG_RUNTIME_DIR` scheitert das immer, und
  der Neustart unter `env -i` (`:236`) gibt die Variable nicht weiter: das `ok` kommt unabhängig vom echten Zustand.
- **Die Argument-Weiche (R-0161)** kennt nur `--py-lock`, `--claude-sum`, `--pin`, `--verdict` (`:204`–`:223`) und nach
  dem Neustart `--self-check`, `--env-check` (`:293`, `:301`). Jedes andere Argument startet den vollen Lauf mit
  Push-Proben, Proxmox und Modellproben.
- **Die Runner-Settings (R-0163)** installiert `runner-setup.sh:413` als Datei des Runners
  (`install -o $RUNNER -m 600`). Das Red Team prüft daran nur, ob eine Deny-Regel für `git push` darin steht
  (`:509`–`:517`). Eine Abweichung vom Stand im Repo bliebe unbemerkt.
- **Der PreToolUse-Hook (R-0159)** in `runner-settings.json:114` ruft `harness-guard.sh` aus dem Arbeitsbaum auf. Laut
  Claude-Code-Doku (code.claude.com/docs/en/hooks) blockiert ein Hook, dessen Skript fehlt oder der in die Zeitgrenze
  läuft, nicht: „When the script path doesn't exist or isn't executable, the shell exits with a code like 127 … For
  most hook events, the action proceeds.“ und „A timed-out `command` … hook doesn't block the tool call.“ Nur Exit 2
  bzw. `permissionDecision: "deny"` blockiert.
- **Der Wächter (R-0158)** kennt im git-Zweig (`harness-guard.sh:805`) nur die Umgehungen des pre-commit-Hooks
  (`git_skips_hook`, `:496`), nicht die Ausgabe-Optionen, mit denen git selbst Dateien schreibt. Die Runner-Settings
  erlauben `Bash(git diff|log|show|status|grep:*)` (`runner-settings.json:70`–`:74`).

Alles bestand vor diesem Paket und ist Voraussetzung für Stufe 7 (Worker unter `adminhelper-runner`).

## Ziel & Nicht-Ziele

**Ziel**
- Das Red Team führt keinen Code und keine ausführbare Konfiguration aus dem Runner-Klon aus; was es misst, hängt nur
  von seiner root-eigenen Kopie, festen Zielen und der echten Grenze ab.
- Probe 4 misst die Rechte des Proxmox-Tokens direkt an der API.
- Die D-Bus-Probe misst den echten Socket; ein unbekanntes Argument endet, bevor eine Probe läuft.
- Eine Abweichung der Runner-Settings von der root-eigenen Kopie ist ein `FAIL` (erkennen; verhindern ist 7a).
- Der Runner-Hook blockiert, wenn der Wächter fehlt, nicht startet oder hängt (fail-closed).
- Der Wächter erkennt die Schreibwege von git über Ausgabe-Optionen als Schreibzugriff auf Harness-Pfade.

**Nicht-Ziele**
- Keine root-eigene Kopie des Wächters für den Runner-Hook: der Wächter liest `harness-paths.txt` relativ zu sich
  (`harness-guard.sh:106`) und müsste dafür umgebaut werden. Gehört zu Stufe 7a (Roadmap R-0164).
- Kein Verhindern geänderter Runner-Settings (Managed Settings würden systemweit auch für Kevin gelten); das entscheidet
  Stufe 7a. Hier nur Erkennen.
- Keine Änderung an `review-settings.json` (Stufe 6b im Bau): dieselbe fail-closed-Zeile gibt die Aufsicht Worker B mit.
- Keine Neufassung der Runner-Allowlist (Stufe 7a T2).

## Betroffene Komponenten & Dateien

| Datei | Task |
|---|---|
| `scripts/dev/runner-redteam.sh` | T1 Weiche + D-Bus, T2 git ohne Klon-Code, T3 Probe 4, T6 Settings-Vergleich |
| `scripts/tests/redteam_test.sh` | T1, T2, T3, T6 |
| `scripts/dev/hooks/harness-guard.sh` | T4 |
| `scripts/tests/hooks_test.sh` | T4, T5 |
| `scripts/dev/runner-settings.json` | T5 |
| `scripts/dev/runner-setup.sh`, `scripts/tests/runner_setup_test.sh` | T3 (Ziel der Proxmox-Probe), T6 (nur falls nötig) |
| `DEVELOPMENT.md`, `CHANGELOG.md` | T5 (Doku des Pakets) |

Alle Skripte liegen unter Harness-Pfaden (`scripts/dev/harness-paths.txt`): Bau interaktiv, Review mit Opus, eine Runde.

## Design

### Weiche und D-Bus (T1)
- Die erlaubten Argumente stehen als Liste ganz oben; ein anderes Argument endet mit Exit 2 und einer Zeile, bevor der
  Neustart oder eine Probe läuft.
- D-Bus: `/run/user/<uid>/bus` existiert als Socket ⇒ `busctl --user status` mit gesetztem `XDG_RUNTIME_DIR`;
  erreichbar ⇒ `FAIL`, kein Socket ⇒ `ok`. Dazu: `/run/user/1000` (Kevins Laufzeitverzeichnis) ist nicht betretbar.

### git ohne Code aus dem Klon (T2)
Grundsatz: Konfiguration des Klons darf gelesen, nie ausgeführt werden.
- Push-Proben: `--no-verify` (die git-Doku: „With `--no-verify`, the hook is bypassed completely“), dazu
  `-c credential.helper=` (gitcredentials: der leere Wert „resets the helper list to empty“) und
  `-c core.fsmonitor=false`. Die Probe „kein Credential-Helfer konfiguriert“ (`:369`) liest weiter nur.
- Die Bare-Probe läuft aus einem frischen Temp-Repo (`git init --template=`), nicht aus dem Klon, mit
  `GIT_CONFIG_GLOBAL=/dev/null` und `GIT_CONFIG_NOSYSTEM=1` (git-Doku: „Can be set to `/dev/null` to skip reading
  configuration files of the respective level“).
- Kein `-c core.hooksPath=…`: der Wächter weist das in jedem Modus als Umgehung des pre-commit-Hooks ab.
- „Hat die Modellprobe den Klon geändert?“ (`:474`/`:483`) wird ein Dateisystem-Vergleich ohne git: Marker-Datei vorher,
  danach `find "$REPO" -newer <marker>` ohne `.git/index` und Sperrdateien. `CLAUDE.md` unverändert (`:557`) wird
  `sha256sum` vorher und nachher.
- Nicht verifiziert: dass `GIT_SSH_COMMAND` (schon gesetzt, `:388`) `core.sshCommand` aus dem Klon übersteuert; der
  Builder liest das in der git-Doku nach und setzt die Probe sonst ebenfalls in das Temp-Repo.

### Probe 4 direkt an der API (T3)
- `curl` gegen die Proxmox-API; das Token geht als Kopfzeile über stdin (`curl --config -`), nie in die argv
  (`/proc/<pid>/cmdline` ist für alle lesbar).
- Gegenprobe: `GET /pools/<pool>` ⇒ 200 belegt, dass das Token wirkt. Probe:
  `GET /nodes/<node>/qemu/<fremde-vmid>/status/current` ⇒ 403 ⇒ `ok`, 200 ⇒ `FAIL`, sonst `info` mit Code.
- Ziel der Probe (URL, Node, Pool, CA-Datei) kommt nicht aus der Runner-eigenen `pve.env`, sondern aus einer
  root-eigenen Datei neben dem Red Team, die `runner-setup.sh` anlegt (Quelle: siehe Offene Fragen). Aus der `pve.env`
  des Runners kommt nur das Token — gemessen werden dessen Rechte.
- Fehlt `curl` oder die Zieldatei ⇒ `info` (kein Bestehen).
- Nicht verifiziert: dass Proxmox fehlende Rechte als 403 meldet; das zeigt Kevins echter Lauf.

### Wächter: git-Schreibwege (T4)
Im git-Zweig von `harness-guard.sh` zählen als Schreibziel: `--output[=]<f>` bei diff/log/show/range-diff;
`-o`/`--output[=]` bei archive; `-o`/`--output-directory` bei format-patch (Verzeichnis-Ziel wie bei `cp`);
`bundle create <f>`. `grep -O<cmd>`/`--open-files-in-pager` wird wie `bash -c` weitergescannt. Tests in jedem Modus,
dazu Gegenproben ohne Treffer (dieselben Befehle ohne Harness-Ziel, `git diff --stat`).

### Hook fail-closed (T5)
Der Hook-Befehl in `runner-settings.json` prüft, dass der Wächter lesbar ist, ruft ihn mit innerer Zeitgrenze
(`timeout`) auf und endet mit Exit 2, wenn eins davon scheitert; dazu ein `timeout`-Feld am Hook, größer als die
innere Grenze. Vorher belegt der Builder, dass `harness-guard.sh` in jedem Fall mit 0 endet (Kopfkommentar `:51`),
sonst würde ein normaler Fehlercode zur Sperre. Regel-Test in `hooks_test.sh` auf den Befehlstext und mit fehlendem
Skript (Exit 2).

### Runner-Settings erkennen (T6)
`runner-setup.sh` installiert `runner-settings.json` schon root-eigen nach `/usr/local/lib/adminhelper-dev/`
(`runner-setup.sh:356`). Das Red Team vergleicht `~/.claude/settings.json` des Runners byte-genau mit dieser Kopie:
gleich ⇒ `ok`, abweichend oder fehlend ⇒ `FAIL` mit dem Hinweis, `runner-setup.sh` erneut zu fahren. Die bisherige
Prüfung auf die Deny-Regel bleibt als zweite Zeile.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
- Claude-Code-Hooks: code.claude.com/docs/en/hooks (gelesen 2026-10-03, Zitate oben).
- git: git-push (`--no-verify`), gitcredentials (leerer Helfer), git (`GIT_CONFIG_GLOBAL`, `GIT_CONFIG_NOSYSTEM`).
- Proxmox-API: Pfade `/pools/<pool>` und `/nodes/<node>/qemu/<vmid>/status/current`, Header `PVEAPIToken` wie in
  `scripts/vm/vm.py:250`; das 403-Verhalten ist nicht verifiziert.

## Trade-offs & Alternativen
- Probe 4 über eine root-eigene vm.py-Kopie: misst wie bisher, braucht aber Zustandsverzeichnis und Config-Pfade
  von vm.py; die direkte API misst genau die Grenze (die ACL des Tokens). Kevin: direkte API.
- fail-closed hier oder erst in 7a: der Runner-Hook ist heute schon die Grenze für jede Runner-Session; die Zeile ist
  klein. Kevin: hier, `review-settings.json` über 6b.

## Risiken & Rollback
- Ein zu strenger Hook-Befehl sperrt jede Runner-Session (Exit 2 bei jedem Aufruf). Der Regel-Test fährt den echten
  Befehl mit vorhandenem Wächter (Exit 0) und mit fehlendem (Exit 2). Rollback: Revert von T5.
- Ein neuer Wächter-Treffer kann ein Fehlalarm sein (Kevins interaktive Sessions warnen nur). Rollback: Revert von T4.
- Das Red Team meldet nach dem Merge neue `FAIL`, bis Kevin `runner-setup.sh` erneut gefahren hat (Zieldatei der
  Proxmox-Probe, Settings-Kopie). Das ist gewollt.

## Parallelität
- `scripts/tests/hooks_test.sh` teilen sich Stufe 6b und dieses Paket (beide hängen Fälle an): wer als Zweiter merged,
  holt `origin/main` vorher herein.
- Zu Stufe 7a nicht parallel: gemeinsam sind `runner-redteam.sh`, `redteam_test.sh`, `runner-settings.json`,
  `hooks_test.sh`. 7a wird nach 6b gebaut, dieses Paket ist dann gemergt; 7a T9 setzt auf T2/T3 auf.

## Kevins Handarbeit nach dem Merge
1. `sudo bash scripts/dev/runner-setup.sh` — legt die Zieldatei der Proxmox-Probe an und frischt die root-eigene
   Kopie von Red Team und Settings auf.
2. `sudo -u adminhelper-runner git -C /srv/ah/repo pull --ff-only`
3. `sudo -u adminhelper-runner bash /usr/local/lib/adminhelper-dev/runner-redteam.sh` — erst dieser Lauf zeigt die
   echte Antwort der Proxmox-API auf die fremde VM und den D-Bus-Zustand. Ergebnis in den Ledger-Anhang.

## Doku-Impact
`DEVELOPMENT.md` (Red-Team-Abschnitt: Probe 4 misst die API, git-Proben ohne Klon-Code, Settings-Vergleich; Absatz zum
`PreToolUse`-Hook: fail-closed im Runner) und `CHANGELOG.md`. Keine `docs/`-Seite.

## Offene Fragen
1. **Quelle des Proxmox-Ziels (T3).** Vorschlag: `runner-setup.sh` übernimmt `AH_PVE_URL`, `AH_PVE_NODE`,
   `AH_PVE_POOL` und `AH_PVE_CA` (ohne Token) aus der Umgebung des Setup-Aufrufs bzw. aus Kevins
   `.claude/settings.local.json` und schreibt sie nach `/usr/local/lib/adminhelper-dev/pve-target.env` (root, 0644).
   Fehlen sie, legt es keine Datei an und Probe 4 meldet `info`. Am Gate änderbar.
2. **`GIT_SSH_COMMAND` gegen `core.sshCommand` (T2).** Nicht verifiziert; der Builder liest es nach.
