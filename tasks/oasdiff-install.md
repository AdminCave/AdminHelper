<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# oasdiff lokal installieren — Doku-Ergaenzung (Kurz-Ledger)
Status: aktiv · Branch: docs/oasdiff-install · Commit-Granularität: pro Task · Review: am Ende (feature-review) · Modell: Opus
Spec: DEVELOPMENT.md „OpenAPI-Snapshot aktualisieren", .github/workflows/ci.yml Job `openapi-compat` — Kurz-Ledger, keine eigene Spec
Fast-Suite: lokal · Warm-Profil: —
Heavy: keine (reine Doku, kein Code, kein Wire-Format)
DoD je Task: CLAUDE.md, dazu `.claude/rules/docs.md` (CHANGELOG-Einträge umlautfrei; hier kein CHANGELOG-Eintrag, siehe T1)
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung
Roadmap: — (Nebenbefund aus `input-boundary-validation`, 2026-09-23) · Hängt ab von: —

Befund: `DEVELOPMENT.md:211` beschreibt, wie man das OpenAPI-Gate lokal fährt, und nennt die
Voraussetzung („braucht `oasdiff` im PATH, sonst Exit 75 = SKIP") — aber nirgends steht, wie man
es installiert. Beim Bau von `input-boundary-validation` war das eine echte Lücke: das Gate war
die einzige Stelle, deren Wirkung vor dem Push unbelegt blieb, weil das Binary fehlte, und zwar
genau auf dem PR, der die frische Severity-Datei aus #32 zum ersten Mal wirklich auf die Probe
stellte. Kevin hat es dann von Hand installiert; damit lief das Gate lokal
(`37 changes: 0 error, 37 warning, 0 info`, Exit 0, beide Dienste).

Entschieden (Kevin hat die Entscheidung am 2026-09-23 an mich delegiert; Begründung hier, damit sie
nachlesbar ist statt nur passiert zu sein): **die Zahlen stehen im Klartext in der Doku, datiert, mit
`ci.yml` als benannter Quelle der Wahrheit — und es gibt keinen Konsistenz-Check.**

Verworfen wurden drei Alternativen:
- *Werte per `grep -oP` aus `ci.yml` ableiten.* Klingt nach Root-Cause, ist aber ein Regex auf YAML in
  einer Anleitung: `grep -P` gibt es nicht überall (macOS hat es nicht), und wer ein Werkzeug installieren
  will, soll nicht erst einem Muster trauen müssen. Lesbarkeit schlägt hier Cleverness.
- *Nur auf `ci.yml` verweisen, ohne Zahlen.* Dann muss jeder die Datei aufschlagen, um drei Zeilen zu
  kopieren — die Anleitung erklärt dann, statt zu helfen.
- *Zahlen plus CI-Konsistenz-Check.* Der Präzedenzfall `frp-consistency` bewacht **vier** Pins über vier
  Dateien; hier sind es zwei Werte in einer Datei, und wer sie bumpt, arbeitet ohnehin am selben Gate.
  Ein eigener Gate-Schritt dafür ist die prophylaktische Abstraktion, die YAGNI meint.

Was bleibt, ist der Datums-Stempel: er macht Drift **sichtbar** statt still. Genau das ist der Unterschied,
auf den es ankommt — eine Zahl ohne Stand behauptet Gültigkeit, eine mit Stand lädt zum Nachsehen ein.

### T1 — Installationsblock in DEVELOPMENT.md  [x]
Komponente: scripts · Dateien: DEVELOPMENT.md
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped @70dd4682 2026-09-23T09:15:39+02:00
Review: Review am Ende (Kurz-Ledger)
Änderung: Im Abschnitt „OpenAPI-Snapshot aktualisieren", direkt vor dem bestehenden Block „Lokal gegen den Basis-Branch pruefen", ein kurzer Installationsblock: Tarball von `github.com/oasdiff/oasdiff/releases/download/v<VERSION>/oasdiff_<VERSION>_linux_amd64.tar.gz`, SHA-256 gegengeprüft, entpackt nach `~/.local/bin`. Version und Prüfsumme **wörtlich aus `.github/workflows/ci.yml`** (`OASDIFF_VERSION`, `OASDIFF_SHA256_LINUX_AMD64`), damit Doku und Gate dieselbe Zahl nennen, mit Verweis auf die Datei als Quelle der Wahrheit. Dazu ein Satz zum Warum des Tarballs statt `go install`: ab oasdiff v1.24.0 verlangt jede Fassung `go 1.26` in der go.mod, die Workflows pinnen aber Go 1.25 mit `GOTOOLCHAIN=local` — Bauen aus der Quelle scheitert dort genau so wie seinerzeit `govulncheck` (PR #14); ein fertiges Binary braucht gar keine Toolchain. Begründung steht wörtlich als Kommentar in `ci.yml` beim Schritt „Install oasdiff". Schreibweise wie der umgebende Abschnitt, der durchgehend transliteriert ist („pruefen", „Aenderung", „gekuerzten") — die Datei als Ganzes ist gemischt (35 Zeilen mit Umlauten), die Umlautregel aus `.claude/rules/docs.md` gilt ausdruecklich nur fuer CHANGELOG-Eintraege. Maßgeblich ist hier also die Nachbarschaft, nicht eine Regel. Kein CHANGELOG-Eintrag: kein nach außen sichtbares Verhalten, keine neue Abhängigkeit des Produkts — nur ein optionales Entwicklerwerkzeug.
Beweis: Die `scripts`-Suite sieht `DEVELOPMENT.md` gar nicht an — `doc-smoke.py` prüft nur `docs/**/*.html`. Der Verify-Lauf zeigt hier also nur, dass nichts kaputtgegangen ist. Der eigentliche Beleg ist, die dokumentierten Befehle auszuführen: am 2026-09-23 in ein Wegwerf-Verzeichnis gefahren (Download, `sha256sum -c -` → OK, entpackt, `oasdiff version 1.32.0`), und `V`/`S` gegen `ci.yml` gegengeprüft — beide byte-gleich mit `OASDIFF_VERSION` und `OASDIFF_SHA256_LINUX_AMD64`.
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: DEVELOPMENT.md (ist die Änderung selbst)

### T2 — Der Prüfsummen-Schritt muss das Entpacken wirklich verhindern  [x]
Komponente: scripts · Dateien: DEVELOPMENT.md
Evidenz: run.sh[quick]: 5 passed, 0 failed, 12 skipped @dabb05e3 2026-09-23T09:23:37+02:00
Review: blocker aus dem Abschluss-Review, behoben; Re-Review folgt
Änderung: Blocker aus dem Abschluss-Review. Der Block aus T1 prüft die Prüfsumme **vor** dem Entpacken, aber er hindert nichts: ohne `set -e` und ohne Verkettung läuft `tar` auch nach einem FEHLSCHLAG. In CI fällt das nicht auf, weil GitHub `run:`-Schritte mit `bash -e` fährt — beim Copy-Paste in eine normale Shell schon. Damit widerspricht der Block dem Satz direkt darunter („die Pruefsumme macht ein ausgetauschtes Asset zum Fehler statt zur Ueberraschung"), und genau das Szenario, für das die Prüfsumme da ist (gültiges Archiv, falscher Inhalt), landet still in `~/.local/bin`. Nachgestellt 2026-09-23 mit einem selbst gebauten `oasdiff.tgz` mit falschem Inhalt: alte Fassung `exit=0`, Binary entpackt; verkettete Fassung `exit=1`, nichts entpackt. Die Schritte werden deshalb mit `&&` verkettet. Kein `set -e`: der Block ist zum Einfügen in eine interaktive Shell gedacht, und dort wirkt `set -e` auf die Shell des Benutzers weiter.
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: DEVELOPMENT.md (ist die Änderung selbst)
