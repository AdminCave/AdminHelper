<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# vm.py und lib.sh lesen den Proxmox-Zugang aus einer 0600-Datei (R-0229) — Task-Ledger
Status: aktiv · Branch: harness/vm-token-file · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-08 (kleines Paket aus R-0229, Team-Plan Phase 0, von Kevin am 2026-10-08 angenommen; Delegation Kevin 2026-10-05; Harness-Pfade, den PR merged Kevin)
Spec: Roadmap R-0229 (Kurz-Ledger ohne Spec)
Heavy: none — Python und Shell unter scripts/vm mit hermetischen Tests, dazu Harness-Doku; kein Stack-, Gateway-, PKI- oder Install-Pfad. Den echten Zugriff mit dem umgezogenen Token (`vm.py doctor`) prüft Kevin nach seinem Umzug (T3).
DoD je Task: CLAUDE.md (Tests grün, ruff und shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-08 von Worker A für die Aufsicht (adminhelper-ac), Team-Plan Phase 0 (Hygiene). Zeilenangaben
main@7129dc57; beim Bau an Symbolen orientieren.

Befund: `Config.load` (`scripts/vm/vm.py:123`) liest den Proxmox-Zugang nur aus `.claude/settings.local.json` →
`env` (`:126`), eine gesetzte Umgebungsvariable gewinnt (`:138`); `vm_load_env` (`scripts/vm/lib.sh:26`) ebenso
(`:34`). Claude Code exportiert diesen `env`-Block in jede Session, also steht `AH_PVE_TOKEN` in der Umgebung jeder
Session und jedes Kindprozesses. `~/.config/adminhelper/pve.env` liest heute nur `scripts/dev/runner-env.sh`, für
den Runner.

Entwurf (für alle drei Tasks):
- Quelle: `~/.config/adminhelper/pve.env`, in vm.py als Modulkonstante `PVE_ENV_FILE`, erst beim Laden mit
  `os.path.expanduser` aufgelöst — Tests patchen die Konstante (Python) bzw. setzen `HOME` (Shell).
- Format wie `runner-env.sh` (`:141–152`): Zeilen `KEY=VALUE`, wahlweise mit `export ` davor; Leerraum am Rand und
  ein Paar umschließender doppelter oder einfacher Anführungszeichen fallen weg; nur Schlüssel `AH_PVE_*` und
  `AH_VM_*`, alles andere (Kommentare, Leerzeilen, fremde Schlüssel) wird übergangen; eine spätere Zeile gewinnt.
  Die Datei wird gelesen, nie gesourct oder ausgeführt.
- Prüfungen wie `ah_secure_file` und die Verzeichnisprüfung in `runner-env.sh` (`:96–121`): Fehlt die Datei, ist das
  kein Fehler (Rückfall wie heute). Sonst muss sie eine reguläre Datei sein, kein Symlink, Modus 600, mit dem
  eigenen Benutzer als Besitzer, und ihr Verzeichnis darf für Gruppe und Andere nicht schreibbar sein — sonst
  `Usage` (Exit 2) mit dem Pfad und dem passenden Befehl (`chmod 600 <datei>` bzw. `chmod 700 <verzeichnis>`). Eine
  Meldung nennt nie einen Wert aus der Datei.
- Vorrang je Schlüssel: Umgebung > pve.env > `env`-Block von settings.local.json > `DEFAULTS`. Der `env`-Block bleibt
  als Rückfall.
- Eine Implementierung: eine Funktion in vm.py (etwa `file_values(root)`) führt pve.env und den `env`-Block
  zusammen (nur `AH_PVE_*`/`AH_VM_*`; mehr Schlüssel liest vm.py nicht). `Config.load` nutzt sie und
  `vm_load_env` auch, über `import vm` — so wie `lib_vm_test.sh` vm.py für `current_lane` schon importiert. Kein
  zweiter Parser in lib.sh.
- Nicht in diesem Ledger: `lane.sh` (kopiert settings.local.json in neue Lanes; nach Kevins Umzug ohne Token),
  `runner-env.sh` und `runner-setup.sh` (unverändert, der Runner hat schon seine eigene pve.env), die Sec-Sperre
  (pve.env liegt nie im Baum).

Semantik: CLAUDE.md §8 „Provider-Env und Token liegen **nur** in `.claude/settings.local.json` (gitignored), nie in
`settings.json`." — beschreibt heute die settings-Datei als Absicht. Kevin hat am 2026-10-08 entschieden, dass das
Token in eine 0600-Datei wandert (Konzept „AdminHelper Agenten-Team“, Abschnitt Sicherheit; über die Aufsicht); T3
zieht diese und die übrigen Stellen nach. Unter `docs/` nennt nur `docs/developer/cicd.html` (DE und EN)
`settings.local.json`, in der Liste der Sec-Sperre, und das bleibt wahr.

### T1 — vm.py: `Config.load` liest zusätzlich `~/.config/adminhelper/pve.env` (R-0229)  [x]
Komponente: scripts · Dateien: scripts/vm/vm.py, scripts/vm/tests/test_vm.py, scripts/vm/tests/conftest.py
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @c128d669 2026-10-08T13:18:43+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Nach dem Entwurf: `PVE_ENV_FILE`, eine Lese- und Prüffunktion für pve.env und `file_values(root)`, die
`Config.load` nutzt; der Vorrang der Umgebung (`:138`) bleibt. Die Usage-Meldung für einen fehlenden Schlüssel
(`:146`) und der Modul-Docstring (`:15–17`) nennen beide Quellen. Ein autouse-Fixture in `conftest.py` (wie
`state_dir`, `:229`) zeigt `vm.PVE_ENV_FILE` in jedem Test auf einen Pfad unter `tmp_path`, der nicht existiert —
sonst läse die Suite die echte Datei des Entwicklers, und `test_missing_key_is_a_usage_error` (`test_vm.py:55`)
fiele mit ihr um. Neue Tests, nur mit Platzhalterwerten: ein Wert aus pve.env kommt an; der Vorrang je Schlüssel
(Umgebung > pve.env > settings.local.json); `export `, Anführungszeichen, Kommentare und fremde Schlüssel; Symlink,
Modus 640, Verzeichnis mit Schreibrecht für Andere und fremder Besitzer (über ein gepatchtes `os.getuid`, nicht als
root) ergeben je `Usage` mit dem chmod-Hinweis und ohne den Wert in der Meldung; eine fehlende Datei fällt wie heute
auf settings.local.json zurück. Bestehende Tests und Assertions bleiben unverändert.
Rot vorher: die neuen Tests scheitern auf main (kein `PVE_ENV_FILE`, pve.env wird nicht gelesen).
Beweis: main@7129dc57 · `grep -n 'settings.local.json' scripts/vm/vm.py scripts/vm/lib.sh` → `Config.load` (`vm.py:126`) und `vm_load_env` (`lib.sh:34`) sind die einzigen Quellen; `grep -rn 'pve.env' scripts/vm` → keine Treffer
Dedup-Key: ref:vm:vm.py:Config.load
HEAD: 7129dc57
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine in dieser Task (die Doku ist T3)

### T2 — lib.sh: `vm_load_env` nimmt dieselbe Quelle über vm.py (R-0229)  [x]
Komponente: scripts · Dateien: scripts/vm/lib.sh, scripts/tests/lib_vm_test.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @d8af69d9 2026-10-08T13:29:50+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Das Python in `vm_load_env` (`lib.sh:31–39`) liest settings.local.json nicht mehr selbst, sondern
importiert vm.py aus `$VM_ROOT/scripts/vm` und exportiert die Werte von `file_values()` für jeden Schlüssel, der in der
Umgebung noch leer ist (Vorrang wie heute, `shlex.quote` bleibt). Eine abgelehnte pve.env (`Usage`) endet mit der
Meldung von vm.py auf stderr und einem Return ≠ 0, auch wenn settings.local.json alles hätte — kein stiller
Rückfall. Der frühe Return bei gesetztem `AH_PVE_URL` (`:27`) bleibt, denn `vm_wrappers_test.sh`,
`iter_flags_test.sh` und `heavy_test.sh` verlassen sich darauf; die Meldung in `:40` nennt beide Quellen. In
`lib_vm_test.sh` bekommt der FAKE-Baum `scripts/vm/vm.py`, und die Fälle unter „the environment“ (`:122`) laufen mit
`HOME` auf einem Fixture-Verzeichnis, sonst läse der Test die echte pve.env. Neue Fälle, nur mit Platzhaltern: ein
Wert, der nur in pve.env steht, kommt an; pve.env schlägt settings.local.json; die Umgebung schlägt pve.env; eine
pve.env mit Modus 644 ergibt Return ≠ 0 mit „chmod 600“ in der Meldung.
Rot vorher: die neuen Fälle scheitern auf dem Stand von T1 ohne diese Änderung (lib.sh liest pve.env nicht).
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: keine in dieser Task (die Doku ist T3)
Abhängt von: T1

### T3 — Doku: das Token gehört nach pve.env, und der Umzug für Kevin (R-0229)  [x]
Komponente: scripts · Dateien: CLAUDE.md, DEVELOPMENT.md, AUTONOMOUS.md, .claude/skills/vm/SKILL.md, .claude/skills/test/SKILL.md, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped · contracts: 1 ok @757f2792 2026-10-08T13:41:51+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: CLAUDE.md §8 (`:205–206`), DEVELOPMENT.md „VMs mit vm.py“ (Konfiguration, `:1542–1544`) und „Schwere
Suites auf VMs“ (`:1653–1654`), AUTONOMOUS.md (`:333–335`), der `/vm`-Skill (`:47–49`) und der `/test`-Skill
(`:13–15`) nennen `~/.config/adminhelper/pve.env` (0600, Zeilen `KEY=VALUE`, gelesen, nie gesourct) als Ort des
Tokens und den Vorrang aus dem Entwurf; der `env`-Block von settings.local.json bleibt als Rückfall genannt.
DEVELOPMENT.md bekommt den Umzug als einmaligen Schritt für Kevin: ein Befehl, der `AH_PVE_TOKEN` aus
`.claude/settings.local.json` nach pve.env schreibt (Datei 0600, Verzeichnis 700) und aus der JSON-Datei entfernt,
ohne den Wert je auszugeben. Dazu drei Sätze: jede Lane trägt eine eigene Kopie von settings.local.json (`lane.sh
new`), dort fällt der Eintrag mit demselben Befehl im Lane-Verzeichnis weg; laufende Sessions tragen den alten Wert
bis zu ihrem Neustart in der Umgebung; `python3 scripts/vm/vm.py doctor` ist die Probe danach. CHANGELOG
`[Unreleased]` → Changed.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: das ist die Doku-Task (Harness-Seiten auf Deutsch, die Skills wie bisher; `docs/` bleibt unberührt)
Abhängt von: T1, T2

### T4 — Nachbesserung aus dem Review am Ende: der Umzugsbefehl verliert kein Token (R-0229)  [ ]
Komponente: scripts · Dateien: DEVELOPMENT.md, .claude/skills/test/SKILL.md, scripts/vm/tests/README.md, scripts/tests/heavy.sh
Änderung: Angelegt 2026-10-08 aus dem Review am Ende (Opus, request_changes). wichtig, belegt mit Platzhaltern
gegen ein Fake-HOME: Der Umzugsbefehl in DEVELOPMENT.md verliert das Token, wenn schon eine pve.env liegt. (1) Endet
ihre letzte Zeile ohne Zeilenumbruch, klebt die neue Zeile daran (`AH_VM_MAX=3AH_PVE_TOKEN=…`): das Token fehlt in
beiden Dateien, und `AH_VM_MAX` trägt es in eine Fehlermeldung von vm.py. (2) Eine leere Zeile `AH_PVE_TOKEN=` zählt
als vorhanden, das Token verschwindet aus der JSON-Datei, vm.py wertet leer als nicht gesetzt. Der Befehl liest die
vorhandene Datei deshalb wie vm.py (`export`, Anführungszeichen, leer zählt nicht), setzt vor die neue Zeile einen
Umbruch, wenn der letzten einer fehlt, und öffnet pve.env mit `O_NOFOLLOW` (ein Symlink dort bricht ab, das Token
bleibt in der JSON-Datei). Dazu die nits aus derselben Runde: der Umzugsblock steht hinter der Schlüsseltabelle, die
Zeile im `/test`-Skill wird umbrochen, und `scripts/vm/tests/README.md` (Aufzeichnung „mit dem Token aus
settings.local.json“) sowie die Meldung in `heavy.sh` `preflight` nennen beide Quellen. Kein Test pinnt die Meldung.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: das ist Doku (DEVELOPMENT.md, Skill, README); kein CHANGELOG-Nachtrag, der Eintrag aus T3 gilt
