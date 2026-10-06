<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Harness-Kleinpaket 2: Zeilennummern und Token-Formen in sec, Werkzeug-Hülle, commit-msg-Hook — Task-Ledger
Status: aktiv · Branch: harness/kleinpaket-2 · Commit-Granularität: pro Task · Review: auto · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-06 (kleines Fund-Paket aus den von Kevin am 2026-10-06 als Kleinpaket-2 angenommenen Zeilen R-0194, R-0195, R-0196, R-0197; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0194, R-0196, R-0195, R-0197 (Kurz-Ledger ohne Spec)
Heavy: none — nur Harness-Skripte unter scripts/dev, ihre hermetischen Tests und Doku; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-06 von der Aufsicht (adminhelper-ac) aus den Zeilen, die Kevin in der Triage vom 2026-10-06 als
Kleinpaket-2 angenommen hat; alle vier stammen aus dem `/code-review` über Kleinpaket-1. Der Branch setzt auf
`harness/kleinpaket-1` (#81, @6c9d7b8e) auf, weil er dieselben Stellen weiterführt; gemergt wird er erst nach #81.
Bau interaktiv (Harness-Pfade), keine Lane. Zeilenangaben harness/kleinpaket-1@6c9d7b8e. Die Fixtures setzen
Werkzeug-Tags und Token zur Laufzeit zusammen, wie in Kleinpaket-1, damit keine Datei im Repo sie wörtlich trägt.

### T1 — `review.sh sec`: richtige Zeilennummern nach „\ No newline“, weitere Proxmox-Formen (R-0194, R-0196)  [ ]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/tests/review_scripts_test.sh, DEVELOPMENT.md, docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: (1) In beiden awk von `sec` (`sec_scan`, `:737–744`, und `sec_scan_merge`, `:756–765`) fällt die Zeile
„\ No newline at end of file“ heute in den Zweig, der `newno` hochzählt; jede folgende Fundzeile ist um eins
verschoben. Eine eigene Regel für Zeilen, die mit einem Backslash beginnen, überspringt sie, ohne zu zählen.
(2) `pvetoken` (`:695–701`) erkennt heute nur `USER@REALM!TOKENID=UUID`. Dazu kommen: die PBS-Form mit Doppelpunkt
statt Gleichheitszeichen, die URL-kodierte Form (`%40`, `%21`, `%3D`) und ein Secret allein hinter einem
Schlüsselnamen (etwa `api_token_secret`, `token_secret`, `PVE_TOKEN_SECRET`, gefolgt von `:` oder `=` und einer UUID).
Ein nacktes UUID ohne Schlüsselnamen bleibt erlaubt. Die Platzhalter-Regel (`plain`, höchstens zwei verschiedene
Zeichen) gilt für alle neuen Formen. Tests: ein Diff mit „\ No newline“ vor einem Fund meldet die richtige Zeile, in
beiden awk; je Form ein Treffer, je Form ein Platzhalter ohne Treffer, ein nacktes UUID ohne Treffer; die Meldung
nennt nie den Treffer selbst.
Beweis: Roadmap R-0194, von Worker B auf harness/kleinpaket-1@8ff9b6d7 nachgestellt (gemeldet a.md:4 statt :3);
R-0196 aus demselben Review (PVE-Formen fallen durch).
Semantik: `review.sh` über `sec_scan`: „It also names the line, because "somewhere in this diff" is not
actionable.“ — die genannte Zeile muss stimmen. DEVELOPMENT.md beschreibt die Token-Muster (Kleinpaket-1 T2); die
Stelle bekommt die neuen Formen.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Token-Muster) · docs/developer/cicd.html DE+EN (die Aufzählung beim Public repo guard)

### T2 — `ledger.sh lint`: Werkzeug-Hülle und zurückgegebene Ausgabe als Rest (R-0195)  [ ]
Komponente: scripts · Dateien: scripts/dev/ledger.sh, scripts/tests/ledger_test.sh, tasks/README.md
Änderung: Das Rest-Muster (`ledger.sh:385`) meldet heute die schließenden Tags von content, invoke und parameter
und die öffnenden invoke und parameter mit `name=`. Dazu kommen nur schließende Tags, damit Markdown mit gewöhnlichem
HTML grün bleibt: das der Werkzeugaufruf-Hülle (function_calls) und das der zurückgegebenen Ausgabe (result, output),
jeweils auch mit Namensraum-Präfix wie heute. Tests: je ein Fixture-Ledger mit einem der neuen Tags ⇒ ERROR mit
Zeile; ein Ledger mit einem öffnenden output- oder result-Tag allein bleibt grün; alle echten Ledger unter `tasks/`
bleiben grün (`ledger_test.sh` lintet sie schon).
Beweis: Roadmap R-0195 — der Review von Kleinpaket-1 (C11) fand, dass Hülle und Ausgabe eines Werkzeugaufrufs nicht
erkannt werden.
Semantik: `tasks/README.md` (die `lint`-Zeile, seit Kleinpaket-1 T1 mit „Werkzeug-Reste“) — die Zeile nennt danach
auch Hülle und Ausgabe.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: tasks/README.md (die `lint`-Zeile)

### T3 — commit-msg-Hook: Token in der Commit-Nachricht schon beim Commit sperren (R-0197)  [ ]
Komponente: scripts · Dateien: scripts/dev/review.sh, scripts/dev/hooks/commit-msg (neu, SPDX), scripts/dev/harness.sh, scripts/tests/review_scripts_test.sh, scripts/tests/hooks_test.sh, DEVELOPMENT.md
Änderung: `review.sh sec` bekommt `--message <datei>`: liest die Datei mit derselben `token()`-Funktion wie
`sec_scan_message` (`:771–776`) und meldet nur Zeile und Art, nie den Treffer; Kommentarzeilen, die git selbst
einfügt (`#` am Zeilenanfang), zählen nicht. Neuer Hook `scripts/dev/hooks/commit-msg` (`0755`, SPDX über
`reuse annotate`) ruft `review.sh sec --message "$1"`, Exit ≠ 0 bricht den Commit ab (fail closed wie pre-commit).
`harness.sh status` (`:54`) prüft den neuen Hook mit. `git commit --no-verify` überspringt commit-msg; das verweigert
der Harness-Wächter schon (R-0102), der Test hält es nicht neu fest. Tests: ein Commit mit einem Token in `-m` wird
abgewiesen (Exit 4, die Ausgabe ohne den Token), ein Commit mit einem Platzhalter geht durch, eine Merge-Nachricht
geht durch; `harness.sh status` meldet einen fehlenden commit-msg-Hook.
Beweis: Roadmap R-0197 — heute fängt erst `--range` (pre-push, CI) einen Token in der Nachricht; der Commit selbst
liegt dann schon lokal.
Semantik: DEVELOPMENT.md „pre-commit-Hook“ (`:819` ff.) beschreibt, welcher Hook wann `sec` fährt — der Abschnitt
bekommt den commit-msg-Hook.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: DEVELOPMENT.md (Hook-Abschnitt)
