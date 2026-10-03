<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Runner-Vorarbeit 3: Messinstrument und Grenzen unabhängig vom geprüften Nutzer — Task-Ledger
Status: aktiv · Branch: harness/runner-vorarbeit-3 · Commit-Granularität: pro Task · Review: pro Task (feature-review; Harness-Pfade ⇒ Reviewer Opus, eine Runde) · Modell: Opus
Freigabe: Kevin, 2026-10-03 (Design-Gate Stufe-7-Vorarbeit 3, „Freigeben“; T3: Proxmox-Ziel root-eigen beim Setup), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: docs/features/runner-vorarbeit-3.md (Roadmap R-0156, R-0158, R-0159, R-0160, R-0161, R-0162, R-0163)
Heavy: none — nur Harness-Skripte (runner-redteam.sh, runner-setup.sh, harness-guard.sh, runner-settings.json) und ihre hermetischen Tests mit Fake-Klon, Stub-Binärdateien (curl, busctl) und JSON auf stdin; kein Stack-, Gateway-, PKI- oder Install-Pfad. Den Beweis als echter Runner liefert Kevins Setup- und Red-Team-Lauf nach dem Merge (Spec „Kevins Handarbeit“).
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-03 von der Aufsicht (adminhelper-ac). Zeilenangaben main@587f3c7b. Bau interaktiv (Harness-Pfade).
Ziel: Messinstrument und Grenzen sind von dem, was der geprüfte Nutzer `adminhelper-runner` ändern kann, unabhängig.

Entscheidungen (Kevin bzw. Aufsicht, 2026-10-03):
- A: Probe 4 direkt an der Proxmox-API mit `curl`, Token über stdin bzw. `--config -`, nie in der argv (Kevin).
- B: fail-closed hier nur für `runner-settings.json`; dieselbe Zeile für `review-settings.json` gibt die Aufsicht
  Worker B für Stufe 6b mit (Kevin).
- C: Im Runner-Hook läuft weiter der Wächter aus dem Arbeitsbaum, nur fail-closed; eine root-eigene Wächter-Kopie
  gehört zu Stufe 7a (Roadmap R-0164) (Aufsicht).
- D: Abweichende Runner-Settings werden hier erkannt (T6); das Verhindern entscheidet Stufe 7a (Kevin).
- R-0158 wird hier geschlossen (T4) (Kevin).

Parallelität: `scripts/tests/hooks_test.sh` teilen sich Stufe 6b und dieses Ledger — wer als Zweiter merged, holt
`origin/main` vorher herein.

### T1 — Red Team: unbekannte Argumente enden sofort, die D-Bus-Probe misst den echten Socket  [x]
Komponente: scripts · Dateien: scripts/dev/runner-redteam.sh, scripts/tests/redteam_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @fa865623 2026-10-03T12:48:06+02:00
Review: approve (opus); Nits (zwei weitere D-Bus-Faelle, Notiz, Meldung) in derselben Runde; Gegenproben: HEAD-Kopie mit --foo erreicht den vollen Lauf, Mutante ohne XDG_RUNTIME_DIR meldet ok
Änderung: Die erlaubten Argumente (`--py-lock`, `--claude-sum`, `--pin`, `--verdict`, `--self-check`, `--env-check`,
kein Argument) stehen als Liste vor der ersten Weiche (`runner-redteam.sh:204`); jedes andere endet mit Exit 2 und einer
Zeile, bevor der Neustart (`:236`) oder eine Probe läuft. Die D-Bus-Probe (`:430`) prüft zuerst, ob
`/run/user/<uid>/bus` ein Socket ist; nur dann `busctl --user status` mit gesetztem `XDG_RUNTIME_DIR` (erreichbar ⇒
`FAIL`); kein Socket ⇒ `ok`. Dazu eine Probe, dass `/run/user/1000` nicht betretbar ist (`ok`), bzw. `info`, wenn es
nicht existiert. Der Pfad ist für den hermetischen Test über eine Variable verschiebbar, die nur im Test gesetzt wird
und der Neustart nicht weiterreicht. Tests (`redteam_test.sh`): `--self-chek` und `--foo` ⇒ Exit 2, keine Probe-Zeile;
D-Bus mit Fake-Socket und `busctl`-Stub (erreichbar) ⇒ `FAIL`, ohne Socket ⇒ `ok`. Vor dem Fix rot: beide Fälle.
Beweis: Code-Lesung origin/main@587f3c7b — Weiche `runner-redteam.sh:204`–`:223` und `:293`/`:301`, sonst voller
Lauf; `:430` `busctl --user status`, der Neustart `:236` setzt kein `XDG_RUNTIME_DIR`
Dedup-Key: bug:scripts:runner-redteam.sh:dbus-probe-blind · ref:scripts:runner-redteam.sh:unknown-args
HEAD: 587f3c7b
Semantik: `docs/features/harness-stufe-4.md:33–34`: „Ein Red-Team-Skript beweist, dass dieser User weder pushen noch
fremde Secrets lesen noch den Harness ändern kann.“ Eine Probe, deren `ok` unabhängig vom Zustand kommt, trägt das nicht.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine in dieser Task (T5)
Notiz: Die D-Bus-Probe ist ein eigener Schritt `--dbus <runtime-wurzel> <owner-uid>` wie `--py-lock` statt einer
Test-Variable — gleiche Wirkung (verschiebbar nur im Test, der normale Lauf ruft `/run/user`), ohne Umweg am Neustart vorbei.
Die Owner-uid ist der Besitzer von `$OWNER_HOME` (ersatzweise 1000, wie dessen Default); ein leeres Argument `""` gilt
als unbekannt.

### T2 — Red Team: die git-Proben führen keinen Code und keine ausführbare Konfiguration aus dem Klon aus  [x]
Komponente: scripts · Dateien: scripts/dev/runner-redteam.sh, scripts/tests/redteam_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @e3293f9e 2026-10-03T13:19:58+02:00
Review: Opus zwei Runden: R1 wichtig Netz-Probe blind fuer git-Credentials, *.lock zu breit; R2 wichtig pushInsteadOf, mittel Token in Ausgabe -> behoben (Regex inkl. URL-Rewrites, Schwaerzung, Schema-Regel, leerer helper); Gegenprobe: alter Push aus dem Klon startete receivepack, status/diff fsmonitor und filter
Änderung: Grundsatz „Konfiguration lesen ja, ausführen nie“. Die Push-Proben (`:389`, `:396`) bekommen `--no-verify`,
`-c credential.helper=` und `-c core.fsmonitor=false`; die Bare-Probe (`:408`/`:409`) läuft aus einem frischen
Temp-Repo (`git init --template=`) mit `GIT_CONFIG_GLOBAL=/dev/null` und `GIT_CONFIG_NOSYSTEM=1`, nicht aus dem Klon.
Kein `-c core.hooksPath=…` (der Wächter weist das in jedem Modus ab). „Hat die Modellprobe den Klon geändert?“
(`:474`/`:483`) wird ein Dateisystem-Vergleich ohne git (Marker-Datei, `find "$REPO" -newer`, ohne `.git/index` und
Sperrdateien); „CLAUDE.md unverändert“ (`:557`) wird `sha256sum` vorher/nachher. Die lesenden Proben (`:369`, `:379`)
bleiben. Nachlesen und im Ledger festhalten: ob `GIT_SSH_COMMAND` (`:388`) `core.sshCommand` aus dem Klon übersteuert;
wenn nicht belegt, laufen auch die Push-Proben aus dem Temp-Repo. Test (`redteam_test.sh`): ein Fake-Klon mit
`pre-push`-Hook, `core.fsmonitor` und clean-Filter, die je eine Marker-Datei anlegen ⇒ nach den git-Proben und dem
Änderungs-Vergleich existiert keine Marker-Datei; die Proben werten weiter richtig (Push scheitert ⇒ `ok`). Vor dem Fix
rot: die Marker-Dateien entstehen.
Beweis: origin/main@587f3c7b, Wegwerf-Repo im Scratchpad der Aufsicht, git 2.47.3 (2026-10-03): `pre-push` lief bei
`push --dry-run` (erst `--no-verify` unterdrückte es), `core.fsmonitor` lief bei `git status` (nicht mit
`-c core.fsmonitor=false`), ein clean-Filter lief bei `git status` und bei `git diff --quiet`
Dedup-Key: bug:scripts:runner-redteam.sh:git-runner-config
HEAD: 587f3c7b
Semantik: wie T1 (`docs/features/harness-stufe-4.md:33–34`).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine in dieser Task (T5)
Notiz: Nachgelesen (git-config(1), git 2.47.3): `core.sshCommand` „is overridden when the environment variable is set“ —
`GIT_SSH_COMMAND` übersteuert ihn also. Trotzdem laufen alle Push-Proben aus dem Temp-Repo: Gegenprobe im Scratchpad,
der alte Push aus dem Klon an die lokale pushurl `/dev/null` startete `remote.origin.receivepack` des Klons, das die
`-c`-Optionen des Plans nicht abdecken. Der Fake-Hook im Test liegt in `.git/hooks` (der Wächter weist
`git config core.hooksPath` in jedem Modus ab, auch für einen Fake-Klon).

### T3 — Red Team: Probe 4 misst die Rechte des Proxmox-Tokens direkt an der API  [x]
Komponente: scripts · Dateien: scripts/dev/runner-redteam.sh, scripts/dev/runner-setup.sh, scripts/tests/redteam_test.sh, scripts/tests/runner_setup_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @65b1dbb5 2026-10-03T13:35:55+02:00
Review: request_changes (opus): Blocker curl las ~/.curlrc des Runners -> curl -q als erstes Argument und --noproxy, mit Fake-curlrc belegt; Nits curl-Exit in info, Hinweis zum alten Ziel, vm.py-Reste weg, weitere Testfaelle; keine zweite Runde (ein Flag, Test und Verhaltensprobe)
Änderung: Probe 4 (`:446`/`:450`) ruft kein `vm.py` mehr auf. Sie fragt die Proxmox-API mit `curl`: das Token geht als
Kopfzeile `Authorization: PVEAPIToken=…` über stdin (`curl --config -`), nie in die argv. Gegenprobe
`GET /pools/<pool>` ⇒ 200 (Token wirkt), sonst `FAIL`; Probe `GET /nodes/<node>/qemu/<fremde-vmid>/status/current`
⇒ 403 ⇒ `ok`, 200 ⇒ `FAIL`, anderer Code ⇒ `info` mit Code. URL, Node, Pool und CA-Datei kommen aus
`/usr/local/lib/adminhelper-dev/pve-target.env` (root, 0644), die `runner-setup.sh` im Red-Team-Schritt
(`runner-setup.sh:353`) anlegt — Quelle laut Spec „Offene Fragen“ 1; aus der Runner-eigenen `pve.env` kommt nur das
Token. Fehlt `curl` oder die Zieldatei ⇒ `info`. Die Prüfung ist ein eigener Schritt (`--pve <target-datei>`) wie
`--py-lock`, damit der Test sie mit einem `curl`-Stub ohne Netz fährt. Tests: `redteam_test.sh` (Stub 200/403 ⇒ `ok`;
200/200 ⇒ `FAIL`; 401 auf den Pool ⇒ `FAIL`; Token nicht in der argv des Stubs — der Stub schreibt seine Argumente
mit); `runner_setup_test.sh` (Dry-Run nennt die Zieldatei, Besitzer, Modus; ohne Quelle keine Datei und ein Hinweis).
Vor dem Fix rot: die neuen Fälle.
Beweis: Code-Lesung origin/main@587f3c7b — `runner-redteam.sh:446` `python3 "$REPO/scripts/vm/vm.py" doctor`, `:450`
`vm.py ssh`; `$REPO` ist der Runner-Klon
Dedup-Key: bug:scripts:runner-redteam.sh:probe4-runner-vmpy
HEAD: 587f3c7b
Semantik: wie T1 (`docs/features/harness-stufe-4.md:33–34`).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine in dieser Task (T5)
Abhängt von: T1
Notiz: Gegenprobe `GET /pools?poolid=<pool>` statt `GET /pools/<pool>` — das offizielle API-Schema
(pve-docs/api-viewer/apidoc.js, gelesen 2026-10-03) nennt `/pools/{poolid}` „deprecated, no support for nested pools,
use 'GET /pools/?poolid={poolid}'“; die Listenform antwortet jedem gültigen Token mit 200 und nennt nur Pools mit
`Pool.Audit`, also prüft die Probe, dass der Pool in der Antwort steht. `status/current` verlangt laut Schema `VM.Audit`
auf `/vms/{vmid}`; dass der fehlende Recht als 403 kommt, ist nicht verifiziert (Kevins Lauf). Die CA kopiert das Setup
root-eigen nach `pve-ca.pem` (Kevins Datei liegt unter seinem Home, der Runner kann sie nicht lesen); Code `000`
(API antwortet nicht) ist `info`, mit dem curl-Exit. Beide Testskripte entfernen geerbte `AH_PVE_*` am Anfang. curl läuft
mit `-q` als erstem Argument (curl(1): „If used as the first parameter … the curlrc config file is not read“) und
`--noproxy '*'` — sonst läse es die `~/.curlrc` des Runners (Review: `insecure`/`connect-to` darin lenkten die Probe auf
eine Fake-API); mit einer Fake-curlrc gegengeprüft.

### T4 — Wächter: Schreibwege von git über Ausgabe-Optionen zählen als Schreibzugriff  [x]
Komponente: scripts · Dateien: scripts/dev/hooks/harness-guard.sh, scripts/tests/hooks_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @55aafbe4 2026-10-03T14:11:10+02:00
Review: Opus zwei Runden: R1 sechs wichtig (Cluster, Praefixe, -- als Wert, format-patch --output getrennt, bundle --version, schreibender Pager) -> getopt-Lesen; R2 mittel Pfadangaben-Regel (Verzeichnis/Glob/Magic) -> behoben und getestet; Gegenprobe HEAD-Waechter: 64 Treffer rot, freie gruen
Änderung: Im git-Zweig (`harness-guard.sh:805`) zählen als Schreibziel, wenn es ein Harness-Pfad ist:
`--output[=]<f>` bei diff/log/show/range-diff; `-o`/`--output[=]` bei archive; `-o`/`--output-directory` bei
format-patch (Verzeichnis-Ziel wie bei `cp`, `:897`–`:920`); `bundle create <f>`. Der Befehl hinter `grep -O<cmd>`
bzw. `--open-files-in-pager=<cmd>` wird wie bei `bash -c` weitergescannt. Globale Optionen vor dem Unterbefehl
(`-C`, `-c`) werden wie in `git_skips_hook` (`:496`) übersprungen. Tests (`hooks_test.sh`): jeder Weg auf
`CLAUDE.md` bzw. `scripts/dev/` ⇒ deny im autonomen Modus und Warnung interaktiv; Gegenproben ohne Treffer
(`git diff --stat`, `git diff --output=<pfad außerhalb des Harness>`, `git archive -o <pfad außerhalb>`).
Vor dem Fix rot: die Treffer-Fälle.
Beweis: Code-Lesung origin/main@587f3c7b — `harness-guard.sh:805`–`:808` prüft im git-Zweig nur `git_skips_hook`;
`runner-settings.json:70`–`:74` erlaubt `git diff|log|show|status|grep`
Dedup-Key: bug:scripts:harness-guard.sh:git-output
HEAD: 587f3c7b
Semantik: `DEVELOPMENT.md:657`–`:660`: „Der `PreToolUse`-Hook `scripts/dev/hooks/harness-guard.sh` ermittelt vor jedem
`Edit`/`Write`/`MultiEdit`/`Bash`, welche Datei der Aufruf schreiben wuerde — inklusive `sed -i`, `tee`,
`>`-Umleitung, `cp`/`mv` und `bash -c` — und verweigert ihn, wenn sie auf der Liste steht.“
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine in dieser Task (T5)
Notiz: Gelesen wie git liest (Review, zwei Runden, jede Umgehung mit git 2.47.3 real belegt): Kurz-Cluster links nach
rechts (`-ko DIR`, `-iO…`), eindeutige Präfixe (`--open=`, `--vers 3`), `--` beendet die Optionen nur bei diff ohne
`--no-index`, log und show; `format-patch --output <f>` getrennt. Ein Pager hinter `-O` wird mit den Dateien gescannt,
die er bekommt: eine Pfadangabe zählt nur als existierende Datei ohne Glob/Magic, sonst steht `CLAUDE.md` stellvertretend.
Bekannte Lücken im Kopfkommentar: `--output` anderer Unterbefehle, Pager/Alias über `-c`/GIT_PAGER, `archive --exec`,
`git diff` außerhalb eines Repos (liest hinter `--` weiter).

### T5 — Runner-Hook fail-closed; Doku des Pakets  [ ]
Komponente: scripts · Dateien: scripts/dev/runner-settings.json, scripts/tests/hooks_test.sh, DEVELOPMENT.md, CHANGELOG.md
Änderung: Der `PreToolUse`-Hook in `runner-settings.json:114` prüft, dass der Wächter lesbar ist, ruft ihn mit innerer
Zeitgrenze (`timeout`) auf und endet mit Exit 2, wenn das Skript fehlt, nicht startet oder die Zeit überschreitet;
dazu ein `timeout`-Feld am Hook, größer als die innere Grenze. Vorher belegen (Code und Test), dass `harness-guard.sh`
in jedem Fall mit 0 endet (`:51`), sonst würde jeder normale Fehlercode zur Sperre. Tests (`hooks_test.sh`): der
Befehlstext aus `runner-settings.json` mit vorhandenem Wächter und harmlosem Aufruf ⇒ Exit 0; mit fehlendem Wächter
⇒ Exit 2; mit einem Wächter-Stub, der hängt ⇒ Exit 2 nach der inneren Grenze. Doku: DEVELOPMENT.md — Red-Team-Abschnitt
(`:931`–`:957`: Probe 4 misst die API, die git-Proben führen keinen Code aus dem Klon aus, Settings-Vergleich aus T6,
unbekannte Argumente) und der Hook-Absatz (`:657` ff.: im Runner fail-closed); CHANGELOG. Vor dem Fix rot: der Fall
„fehlender Wächter“ (Exit 127, durchgelassen).
Beweis: code.claude.com/docs/en/hooks (gelesen 2026-10-03): „When the script path doesn't exist or isn't executable,
the shell exits with a code like 127 … For most hook events, the action proceeds.“ und „A timed-out `command` … hook
doesn't block the tool call.“; Hook-Eintrag `runner-settings.json:114`
Dedup-Key: ref:scripts:hooks:fail-closed
HEAD: 587f3c7b
Semantik: `docs/features/harness-stufe-4.md:33–34` (wie T1): der Harness gilt als nicht änderbar für diesen User; ein
Hook, der bei fehlendem Wächter durchlässt, trägt das nicht.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Red Team, Hook) · CHANGELOG (Fixed)
Abhängt von: T1, T2, T3, T4

### T6 — Red Team: die Runner-Settings gleichen byte-genau der root-eigenen Kopie  [ ]
Komponente: scripts · Dateien: scripts/dev/runner-redteam.sh, scripts/tests/redteam_test.sh, scripts/dev/runner-setup.sh, scripts/tests/runner_setup_test.sh
Änderung: `runner-setup.sh` installiert `runner-settings.json` schon root-eigen neben das Red Team
(`runner-setup.sh:356`) und als `~/.claude/settings.json` des Runners (`:413`), beide aus derselben Quelle. Das Red
Team vergleicht `~/.claude/settings.json` byte-genau mit `$SELF_DIR/runner-settings.json`: gleich ⇒ `ok`; abweichend
oder fehlend ⇒ `FAIL` mit dem Hinweis, `runner-setup.sh` erneut zu fahren. Die bisherige Prüfung auf die Deny-Regel
für `git push` (`:509`–`:517`) bleibt. Eigener Schritt `--settings <soll> <ist>` für den hermetischen Test.
`runner-setup.sh` nur ändern, falls der Test zeigt, dass beide Installationen nicht dieselbe Quelle haben
(`runner_setup_test.sh` prüft das im Dry-Run). Tests: gleich ⇒ `ok`, ein Byte anders ⇒ `FAIL`, fehlend ⇒ `FAIL`.
Vor dem Fix rot: „ein Byte anders“ (heute `ok`, solange die Deny-Regel steht).
Beweis: Code-Lesung origin/main@587f3c7b — `runner-setup.sh:413` installiert die Settings als Datei des Runners
(`install -o $RUNNER -m 600`); `runner-redteam.sh:509`–`:517` prüft nur die Deny-Regel für `git push`
Dedup-Key: bug:scripts:runner-redteam.sh:settings-drift
HEAD: 587f3c7b
Semantik: wie T1 (`docs/features/harness-stufe-4.md:33–34`).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: in T5 (Red-Team-Abschnitt), sonst keine
Abhängt von: T1
