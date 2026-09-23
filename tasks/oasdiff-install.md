<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# oasdiff lokal installieren — Doku-Ergaenzung (Kurz-Ledger)
Status: geplant · Branch: docs/oasdiff-install · Commit-Granularität: pro Task · Review: am Ende (feature-review) · Modell: Opus
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

Offen für das Gate (bewusst NICHT als Task eingeplant, weil es eine Entscheidung ist und keine
Ausführung): Soll ein CI-Schritt prüfen, dass die Versions- und Prüfsummen-Angabe in
`DEVELOPMENT.md` mit `ci.yml` übereinstimmt? Präzedenz gibt es — der Job `frp-consistency` prüft
genau so die vier `FRP_VERSION`-Pins. Ohne einen solchen Check driftet die Doku beim nächsten
`OASDIFF_VERSION`-Bump still, und ein Entwickler installiert eine Version, gegen die CI nicht
misst. Dagegen steht YAGNI: es ist ein Pin in einer Datei. Wenn ja, wird das eine zweite Task.

### T1 — Installationsblock in DEVELOPMENT.md  [ ]
Komponente: — (reine Doku, keine Komponenten-Suite) · Dateien: DEVELOPMENT.md
Änderung: Im Abschnitt „OpenAPI-Snapshot aktualisieren", direkt vor dem bestehenden Block „Lokal gegen den Basis-Branch pruefen", ein kurzer Installationsblock: Tarball von `github.com/oasdiff/oasdiff/releases/download/v<VERSION>/oasdiff_<VERSION>_linux_amd64.tar.gz`, SHA-256 gegengeprüft, entpackt nach `~/.local/bin`. Version und Prüfsumme **wörtlich aus `.github/workflows/ci.yml`** (`OASDIFF_VERSION`, `OASDIFF_SHA256_LINUX_AMD64`), damit Doku und Gate dieselbe Zahl nennen, mit Verweis auf die Datei als Quelle der Wahrheit. Dazu ein Satz zum Warum des Tarballs statt `go install`: ab oasdiff v1.24.0 verlangt jede Fassung `go 1.26` in der go.mod, die Workflows pinnen aber Go 1.25 mit `GOTOOLCHAIN=local` — Bauen aus der Quelle scheitert dort genau so wie seinerzeit `govulncheck` (PR #14); ein fertiges Binary braucht gar keine Toolchain. Begründung steht wörtlich als Kommentar in `ci.yml` beim Schritt „Install oasdiff". Schreibweise wie der umgebende Abschnitt, der durchgehend transliteriert ist („pruefen", „Aenderung", „gekuerzten") — die Datei als Ganzes ist gemischt (35 Zeilen mit Umlauten), die Umlautregel aus `.claude/rules/docs.md` gilt ausdruecklich nur fuer CHANGELOG-Eintraege. Maßgeblich ist hier also die Nachbarschaft, nicht eine Regel. Kein CHANGELOG-Eintrag: kein nach außen sichtbares Verhalten, keine neue Abhängigkeit des Produkts — nur ein optionales Entwicklerwerkzeug.
Verify: bash scripts/tests/run.sh unit --strict --only scripts
Doku: DEVELOPMENT.md (ist die Änderung selbst)
