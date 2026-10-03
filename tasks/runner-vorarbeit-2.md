<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Runner-Vorarbeit 2: das Red Team als root-eigenes Messinstrument (R-0152) — Task-Ledger
Status: erledigt · Branch: harness/runner-vorarbeit-2 · Commit-Granularität: pro Task · Review: am Ende (feature-review; Harness-Pfade ⇒ Reviewer Opus, eine Runde) · Modell: Opus
Freigabe: Kevin, 2026-10-03 (Design-Gate Stufe-7-Vorarbeit 2, „Freigeben“), übermittelt durch die Aufsichts-Session adminhelper-ac
Spec: Roadmap R-0152
Heavy: none — nur Skripte (runner-env.sh, runner-redteam.sh, runner-setup.sh) und ihre hermetischen Tests mit Fake-HOME und Stub-Binärdateien; kein Stack-, Gateway-, PKI- oder Install-Pfad. Den Beweis als echter Runner liefert Kevins Setup- und Red-Team-Lauf nach dem Merge (Absatz unten).
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-03 von der Aufsicht (adminhelper-ac). Zeilenangaben main@2508f092.

Befund: Das Red Team (`scripts/dev/runner-redteam.sh`) soll belegen, was der Nutzer `adminhelper-runner` nicht kann.
Heute liegt das Messinstrument selbst in dem, was dieser Nutzer schreiben kann:
- Das Skript und `runner-env.sh` liegen im Runner-Klon; `runner-setup.sh:304` übergibt `$SRV` per `chown -R` an den
  Runner, und Kevin startet genau diese Datei (`DEVELOPMENT.md:865`, `:925`).
- `runner-redteam.sh:206` sourct `runner-env.sh`, und `runner-env.sh:55` sourct als Erstes die Runner-eigene
  `~/.devenv.sh` (angelegt von `runner-setup.sh:362`, setzt `PATH` mit `$HOME/.local/bin` vorn). Eine Datei des
  geprüften Nutzers läuft damit in der Shell des Messinstruments, nach dessen Definitionen (`runner-redteam.sh:166–168`)
  und vor allen Proben; Programme wie `gh`, `git` oder `claude` werden aus einem Pfad aufgelöst, den der Runner füllt.
- Die `claude`-Binärdatei des Runners (`runner-setup.sh:443`) ist Runner-eigen; das Red Team liest nur ihre Version.
Ziel: Das Messinstrument liegt außerhalb dessen, was der geprüfte Nutzer schreiben kann, startet in einer festen
Umgebung, und eine veränderte `claude`-Binärdatei ist ein FAIL.

Entscheidungen (Kevin, 2026-10-03): A — root-eigenes Messinstrument (T1 + T2) · B — sha256 der Runner-`claude`
beim Setup festhalten, FAIL bei Abweichung · C — R-0108 (Allow-Liste für Temp-Pfade) gehört in den Stufe-7-Plan,
nicht in dieses Ledger.

### T1 — Red Team startet in fester Umgebung und sourct keine Datei des Runners  [x]
Komponente: scripts · Dateien: scripts/dev/runner-env.sh, scripts/dev/runner-redteam.sh, scripts/tests/redteam_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @0ec9b238 2026-10-03T11:14:30+02:00
Review: Review am Ende (Kurz-Ledger, Opus); Gegenproben: altes runner-env.sh => devenv gesourct und Integritaets-FAIL, ohne Neustart => Fake-gh sichtbar
Änderung: `runner-env.sh` lässt das Sourcen von `~/.devenv.sh` (`:55`) aus, wenn `AH_RUNNER_ENV_NO_DEVENV=1`
gesetzt ist; sonst bleibt alles wie heute (die Arbeits-Sessions des Runners brauchen PATH und AH_TEST_DB). Das Red
Team startet sich im normalen Lauf einmal neu unter `env -i` mit festem `PATH=/usr/local/bin:/usr/bin:/bin`, `HOME`
aus `getent passwd` und `LANG=C.UTF-8`, setzt `AH_RUNNER_ENV_NO_DEVENV=1` vor dem Sourcen (`:206`) und prüft danach,
dass `ok`/`fail`/`info` unverändert definiert sind (Vergleich der `declare -f`-Ausgabe von vor und nach dem
Sourcen; Abweichung ⇒ FAIL und Abbruch). Die Schritte `--verdict`, `--pin` und `--py-lock` bleiben ohne Neustart
(hermetische Tests). Tests (`redteam_test.sh`): ein Fake-HOME mit einer `.devenv.sh`, die PATH umbiegt und eine
Funktion des Red Teams überschreibt, dazu ein Fake-`gh` vorn im PATH ⇒ der Lauf sourct die Datei nicht, `command -v gh`
zeigt auf `/usr/bin` bzw. fehlt, und ein erzwungener FAIL bleibt in der Zählung; ein zweiter Fall prüft, dass
`runner-env.sh` ohne den Schalter die devenv weiter liest. Vor dem Fix rot: der erste Fall.
Beweis: origin/main@2508f092, Wegwerf-HOME im Scratchpad der Aufsicht (2026-10-03): `runner-env.sh` aus main mit
einer `.devenv.sh`, die PATH auf ein Fake-Verzeichnis setzt und eine vorher definierte Funktion ersetzt, gesourct ⇒
die Funktion war danach ersetzt und `command -v gh` zeigte auf das Fake-Verzeichnis
Dedup-Key: bug:scripts:runner-redteam.sh:sources-runner-env
HEAD: 2508f092
Semantik: `docs/features/harness-stufe-4.md:33–34`: „Ein Red-Team-Skript beweist, dass dieser User weder pushen noch
fremde Secrets lesen noch den Harness ändern kann.“ Ein Beweis, dessen Instrument der geprüfte Nutzer verändern kann,
trägt diese Aussage nicht.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine (intern; der Aufruf ändert sich erst mit T2, Doku in T3)

### T2 — runner-setup.sh installiert das Messinstrument root-eigen und hält die sha256 der Runner-`claude` fest  [x]
Komponente: scripts · Dateien: scripts/dev/runner-setup.sh, scripts/dev/runner-redteam.sh, scripts/tests/runner_setup_test.sh, scripts/tests/redteam_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @9dda705d 2026-10-03T11:24:29+02:00
Review: Review am Ende (Kurz-Ledger, Opus); Gegenproben gegen HEAD: runner_setup_test 91/6, statische Red-Team-Checks rot; alte Fassung nie mit neuen Schritten aufgerufen
Änderung: Ein neuer Setup-Schritt nach dem Klon (`runner-setup.sh:304`) installiert `runner-redteam.sh` und
`runner-env.sh` aus Kevins Checkout nach `/usr/local/lib/adminhelper-dev/` (Verzeichnis `root:root 0755`, Dateien
`0755` bzw. `0644`, per `install`, ohne Symlink im Pfad — `no_symlink_in` wie beim Lock-Verzeichnis `:318–338`).
Nach dem Claude-Schritt (`:443`) schreibt er die sha256 der Runner-`claude` (aufgelöster Pfad, `readlink -f`) nach
`/var/lib/adminhelper-dev/runner-claude.sha256` (`root:root 0644`); fehlt die CLI noch, kein Eintrag und ein Hinweis.
`--remove` (`:170–195`) nimmt beides weg; `--dry-run` zeigt die Schritte (Pfade über `AH_RUNNER_DRY_*` verschiebbar
wie `AH_RUNNER_DRY_LOCKDIR`, `:84`). Das Red Team erkennt seinen Ort: Läuft es nicht aus
`/usr/local/lib/adminhelper-dev/` oder gehört die eigene Datei bzw. das Verzeichnis nicht uid 0 ⇒ FAIL mit dem
richtigen Aufruf; `REPO` (`runner-redteam.sh:38`) wird zu `/srv/ah/repo` (über `AH_REDTEAM_REPO` nur im Test
verschiebbar) und ist nur noch Ziel der Proben. Neue Probe: sha256 der aufgelösten `claude` gleich der festgehaltenen
⇒ ok; abweichend ⇒ FAIL; keine festgehaltene ⇒ FAIL mit Hinweis auf `runner-setup.sh`. Die Prüfung ist ein eigener
Schritt (`--claude-sum <datei> <binär>`) wie `--py-lock`, damit der hermetische Test sie ohne root fährt.
Dazu (Aufsicht 2026-10-03, „Messinstrument root-eigen“ zu Ende gedacht): das Soll des Pin-Checks — `model` aus
`runner-settings.json` und `runner-claude.version` — installiert der Setup-Schritt mit nach
`/usr/local/lib/adminhelper-dev/` (root, `0644`); das Red Team liest es nur von dort, nicht mehr aus dem Runner-Klon. Tests:
`runner_setup_test.sh` (Dry-Run nennt Ziel, Besitzer, Modus beider Dateien und die Prüfsumme; `--remove` nennt beide),
`redteam_test.sh` (`--claude-sum` gleich/abweichend/fehlend; Ortsprüfung mit einer Kopie in einem nicht root-eigenen
Verzeichnis ⇒ FAIL). Vor dem Fix rot: die neuen Fälle.
Beweis: Code-Lesung origin/main@2508f092 — `runner-setup.sh:304` (`chown -R` auf `$SRV`), `DEVELOPMENT.md:865`/`:925`
(Aufruf aus `/srv/ah/repo`), `runner-setup.sh:443` (Runner-eigene CLI)
Dedup-Key: bug:scripts:runner-redteam.sh:sources-runner-env
HEAD: 2508f092
Semantik: wie T1 (`docs/features/harness-stufe-4.md:33–34`).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine in dieser Task (T3)
Abhängt von: T1

### T3 — Doku: neuer Red-Team-Aufruf und Setup-Schritt  [x]
Komponente: scripts · Dateien: DEVELOPMENT.md, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped · contracts: 1 ok @1e5567eb 2026-10-03T11:30:54+02:00
Review: Review am Ende (Kurz-Ledger, Opus)
Änderung: DEVELOPMENT.md — der Red-Team-Aufruf an beiden Stellen (`:865`, `:925`) wird
`sudo -u adminhelper-runner bash /usr/local/lib/adminhelper-dev/runner-redteam.sh`, mit einem Satz zum Warum (das
Messinstrument liegt außerhalb dessen, was der geprüfte Nutzer schreiben kann; feste Umgebung; Prüfsumme der CLI);
der Runner-Abschnitt nennt den neuen Setup-Schritt und dass ein CLI-Wechsel (`runner-claude.version`) ein erneutes
`runner-setup.sh` braucht, sonst meldet das Red Team die Prüfsumme als FAIL. CHANGELOG unter „Changed“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md · CHANGELOG
Abhängt von: T2

## Kevins Handgriffe nach dem Merge
1. Aus einem Checkout auf dem neuen main: `sudo bash scripts/dev/runner-setup.sh` — installiert das Red Team und
   `runner-env.sh` root-eigen unter `/usr/local/lib/adminhelper-dev/` und hält die Prüfsumme der Runner-CLI fest.
2. `sudo -u adminhelper-runner git -C /srv/ah/repo pull --ff-only`.
3. Red Team mit dem neuen Aufruf: `sudo -u adminhelper-runner bash /usr/local/lib/adminhelper-dev/runner-redteam.sh`;
   Ergebnis in den Ledger-Anhang. Erwartet: die neuen Proben (Ort, Prüfsumme) `ok`, keine neue FAIL-Zeile.

### T4 — Befunde aus dem Gesamt-Review: Abschlusstext, Prüfsumme als Runner  [x]
Komponente: scripts · Dateien: scripts/dev/runner-setup.sh, scripts/dev/runner-redteam.sh, scripts/tests/runner_setup_test.sh, scripts/tests/redteam_test.sh, DEVELOPMENT.md, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped · contracts: 1 ok @68bf8415 2026-10-03T11:56:55+02:00
Review: Gesamt-Review Opus: Runde 1 request_changes (wichtig Abschlusstext, Pruefsumme als root), Runde 2 Befunde behoben, neu wichtig Test closing steps unter .../repo -> nur Handover-Teil geprueft, Nit --zero; Gegenprobe HEAD-Setup 96/2
Änderung: (1) Der Abschlusstext von `runner-setup.sh` nennt den neuen Aufruf aus `$LIB_DIR` statt aus dem Klon, ohne
den Satz „the red team runs from that worktree“; der Dry-Run-Test hält das fest. (2) Die sha256 der Runner-CLI bildet
`runuser -u "$RUNNER" -- timeout 120 sha256sum -- <pfad>` — root öffnet keinen Pfad, den der Runner wählen kann (die
Prüfsumme ist ohnehin „trust on first use“ beim Setup); Plan und Test ziehen nach. (3) Nits: veralteter Kommentar zum
Soll im Klon (`runner-setup.sh`, Claude-Schritt), Kommentar zum Neustart nennt `--self-check`, Doku „sourct keine
Datei des Runners“ statt „liest keine“, der normale Lauf endet nach einem FAIL der Ortsprüfung, `SHELL=/bin/bash`
beim Neustart und `USER`/`LOGNAME` neben `HOME` (die CLI nach `env -i`), `AH_REDTEAM_REPO` entfällt (kein Test
nutzt es; YAGNI an einem Messinstrument).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md, CHANGELOG.md (Wortlaut)

Abschluss-Evidenz (2026-10-03):
- Gesamt-Schnellcheck @d4ea2012: `run.sh[quick]: 18 passed, 0 failed, 0 skipped, 12 test-skips, 0 reruns`
  (`run.sh quick --strict`); origin/main@2508f092 war schon enthalten, seitdem nichts Neues auf main.
- Review am Ende (Opus): Runde 1 `request_changes` mit zwei `wichtig` (Abschlusstext des Setups nannte den alten Aufruf;
  die Prüfsumme der CLI las root über einen Pfad des Runners) und Nits → T4; Runde 2: alles behoben, dazu ein `wichtig`
  im Test (Negativ-Check traf einen Checkout unter `…/repo`) und ein Nit (`--zero`), in T4 behoben.
- Gegenproben: T1 das neue Red Team neben dem `runner-env.sh` aus main ⇒ devenv gesourct und Integritäts-FAIL, ohne
  Neustart ⇒ Fake-`gh` sichtbar; T2 `runner_setup_test` gegen das Setup aus main 91 passed, 6 failed, statische
  Red-Team-Checks rot; T4 96 passed, 2 failed. Die alte Fassung des Red Teams lief nie mit einem neuen Schritt.
- Bewusst nicht hier: Probe 4 führt `vm.py` aus dem Klon aus (eigene Roadmap-Zeile, Aufsicht 2026-10-03).
- Heavy: none (wie geplant). Den Beweis als echter Runner liefern Kevins Handgriffe unten.

