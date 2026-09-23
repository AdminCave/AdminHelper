<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Den Runner festnageln: Modell, Effort, CLI-Version — Task-Ledger
Status: erledigt · Branch: harness/pin-the-runner · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Spec: dieses Ledger (Harness-Nacharbeit zu Stufe 4, Roadmap R-0072)
Fast-Suite: lokal · Warm-Profil: desktop
Heavy: nein — der Diff berührt nur `scripts/dev/`, `scripts/tests/` und `DEVELOPMENT.md`.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

## Warum

Die Regel „Planen und Bauen laufen auf mindestens Opus" (CLAUDE.md §2) ruht für den Runner heute
allein auf dem Standard der CLI: `scripts/dev/runner-settings.json` enthält nur `hooks` und
`permissions`, kein Modell, keinen Effort, und nichts hält die CLI-Version fest. Bei einem
überwachten Worker setzt ein Mensch diese Werte. Beim Runner sitzt ab Stufe 7 niemand davor.

Drei Befunde vom 2026-09-23, alle an der installierten CLI 2.1.280 gemessen, nicht vermutet:

- **Kevins Sessions stehen auf dem Alias `opus[1m]`**, der immer auf das neueste Opus zeigt. Für
  interaktive Arbeit richtig, für einen unbeaufsichtigten Lauf falsch: das Modell wechselte beim
  nächsten Release ohne Review.
- **Opus 5.5 hat den Standard-Effort `medium`**, eine Stufe unter Opus 5. Ohne Festlegung liefe
  der Runner flacher, als jede Regel annimmt.
- **Effort wird pro Modell gespeichert.** `/effort` schreibt `modelSettings.<modell>.effortLevel`,
  nicht nur einen globalen Wert.

Kevins Wahl am 2026-09-23: **Opus 5.5 mit einer Million Kontext, Effort `xhigh`.**

## Wie gemessen wird statt behauptet

Eine Probe mit `--model 'claude-opus-5-5[1m]' --output-format stream-json --verbose` lieferte:
das Ereignis `system/init` trägt `model = claude-opus-5-5[1m]` **und** `claude_code_version`; die
Antwort meldet `message.model = claude-opus-5-5`; `result.modelUsage` nennt
`claude-opus-5-5[1m]`. Eine einzige Probe kann also Modell und Version zugleich zurücklesen, und
die Nutzungszählung belegt, welches Modell tatsächlich geantwortet hat. Genau darauf baut T3.

### T1 — Modell, Effort und Auto-Updater in die Runner-Settings  [x]
Komponente: scripts · Dateien: scripts/dev/runner-settings.json, scripts/tests/runner_setup_test.sh
Evidenz: runner_setup_test 61/0 · Gegenprobe: Alias opus[1m] statt fester Kennung ⇒ 1 failed
Änderung: `runner-settings.json` bekommt `"model": "claude-opus-5-5[1m]"` (feste Kennung, **kein** Alias), `"effortLevel": "xhigh"`, dazu `"modelSettings": {"claude-opus-5-5": {"effortLevel": "xhigh"}}` — das ist der Ort, den `/effort` selbst beschreibt, also der, den die CLI liest —, und `"env": {"DISABLE_AUTOUPDATER": "1"}`, damit die Version nicht unter der Hand wandert. Test: die Datei trägt genau diese Werte, das Modell ist keine Alias-Form (`opus`, `sonnet`, `opus[1m]` …), und die bestehenden `hooks`/`permissions` bleiben unverändert.
Beim Bau korrigiert (T3): Der Updater-Schalter stand zuerst als `env`-Block in `runner-settings.json`. `hooks_test` hat das zu Recht abgewiesen — die Datei ist öffentlich und trägt Regeln, **nie** einen `env`-Block, weil dort sonst Tokens und Hosts landen. Der Schalter liegt jetzt in `scripts/dev/runner-env.sh`, das jede arbeitsfähige Runner-Session ohnehin sourct, denn nur von dort kommt das Abo-Token. `runner_setup_test` prüft beides: kein `env`-Block in den Settings, `DISABLE_AUTOUPDATER=1` in `runner-env.sh`.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (T3)

### T2 — Eine Quelle für die CLI-Version, und `runner-setup.sh` setzt sie durch  [x]
Komponente: scripts · Dateien: scripts/dev/runner-claude.version (neu), scripts/dev/runner-setup.sh, scripts/dev/harness-paths.txt, scripts/tests/runner_setup_test.sh
Evidenz: runner_setup_test 64/0 · Gegenprobe: Versionsprüfung entfernt ⇒ ein Wert mit Shell-Code erreicht su -c (1 failed) · Katalog belegt: 2.1.278 kennt claude-opus-5-5 nicht (0 Treffer im Binary, 2.1.280: 15)
Änderung: Die gepinnte Version steht in **einer** Datei (`2.1.280`, die Fassung, die Opus 5.5 kennt — 2.1.278 lehnt das Modell ab). `runner-setup.sh` liest sie und installiert genau diese Fassung für den Runner (`claude install <version>`); fehlt dem Runner die CLI noch, sagt der Schritt das und nennt den dokumentierten Weg, statt still zu übergehen. Die Versionsdatei kommt auf die Harness-Pfade, weil sie bestimmt, womit der Runner arbeitet. Test: der Trockenlauf-Plan enthält den Installationsschritt mit genau der Version aus der Datei.
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: keine (T3)
Abhängt von: T1

### T3 — Das Red Team liest zurück, was wirklich lief  [x]
Komponente: scripts · Dateien: scripts/dev/runner-redteam.sh, scripts/tests/redteam_test.sh, DEVELOPMENT.md, scripts/dev/runner-env.sh, scripts/dev/runner-settings.json, scripts/dev/runner-setup.sh, scripts/tests/runner_setup_test.sh
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped (scripts) · redteam_test 17/0 · runner_setup_test 65/0 · hooks_test 171/0 · gegen das echte Protokoll vom 2026-09-23: ok / version:2.1.280 bei falscher Pin-Version / model:… bei einem Alias als Soll
Änderung: Eine Probe liest aus dem `system/init`-Ereignis einer Modellprobe das tatsächliche Modell und die tatsächliche CLI-Version und vergleicht beides mit dem Soll (`model` aus `runner-settings.json`, Version aus `runner-claude.version`). Abweichung ⇒ **FAIL**, fehlendes Ereignis ⇒ **FAIL** — ein Messgerät, das nichts misst, darf nicht wie ein Ergebnis aussehen. Die Auswertung ist wie das Urteil der Modellproben ein eigener, aufrufbarer Schritt, den ein Test gegen gespeicherte Ereignisse fährt (passt, falsches Modell, falsche Version, kein Init-Ereignis), ohne Claude Code zu starten. In `DEVELOPMENT.md` beim Runner-User: was festgenagelt ist, warum kein Alias, und wie man anhebt (Versionsdatei und Settings ändern, `runner-setup.sh`, Red Team).
Verify: bash scripts/tests/run.sh quick --strict --only scripts
Doku: DEVELOPMENT.md (Runner-User: Modell, Effort, Version und das Anheben)
Abhängt von: T1, T2

## Review am Ende (Opus, frischer Kontext, 2026-09-23)

Urteil `request_changes`, kein Blocker, drei wichtige Punkte — alle behoben, jede neue Zusicherung gegengeprobt (ohne den Fix rot):

- **Zwei Kopien des Solls:** `runner-setup.sh` liest aus dem aufrufenden Checkout, das Red Team aus dem Klon des Runners, und `fetch` bewegt dessen Arbeitsbaum nicht. Übergabe und Doku sagen jetzt `pull --ff-only`, der Anheben-Ablauf geht über PR und Merge.
- **`--pin` war ohne Ergebnis `ok`:** eine Probe ohne `result` oder mit leerer `modelUsage` ist jetzt `noresult` ⇒ FAIL (zwei neue Fälle). Eine fehlende CLI ist FAIL statt `info`.
- **Verweis ins Leere:** der Hinweis bei fehlender CLI nennt jetzt den Installer mit genau der gepinnten Version; die Doku ebenso (Installer-Syntax `bash -s <version>` aus der offiziellen Setup-Doku).

Dazu drei Nits, weil sie das Festnageln selbst betreffen: `ANTHROPIC_MODEL` und `CLAUDE_CODE_EFFORT_LEVEL` haben laut Doku Vorrang vor den Settings — `runner-env.sh` leert beide (hooks_test). Die Versionsprüfung verlangt genau `N.N.N` mit ausgeschriebenen Ziffern (unter `de_DE.UTF-8` ließ `[0-9]` eine arabisch-indische Ziffer durch) und läuft vor Schritt 1. Und die Doku stellt richtig: ein `effortLevel` oben in User-Settings zählt für Opus 5.5 laut Doku nicht mehr, wirksam ist `modelSettings.claude-opus-5-5.effortLevel` (im Binary von 2.1.280 belegt: `modelSettings:{[r]:{effortLevel:n}}`); den Effort liest das Red Team nicht zurück, weil kein Ereignis ihn trägt.

Evidenz: redteam_test 19/0 · runner_setup_test 67/0 · hooks_test 172/0 · doc_smoke 15/0 · run.sh[quick]: 5 passed, 0 failed, 12 skipped (scripts, mit dem CI-ruff 0.15.20) · Gegenproben: alte späte Prüfung ⇒ 2 failed (alle fünf Fehlformen durch) · alte `--pin`-Regel ⇒ 2 failed · ohne `unset` ⇒ 1 failed.
