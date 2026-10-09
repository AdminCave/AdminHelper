<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Messlauf 1: Offset-Schutztest und FRP-Doku (R-0210, R-0214) — Task-Ledger
Status: blockiert · Branch: feature/messlauf-1 · Commit-Granularität: pro Task · Review: am Ende · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-08 (kleines Fund-Paket aus R-0210 und R-0214, von Kevin am 2026-10-07 in der Triage angenommen; Messlauf laut Team-Plan, Kevin 2026-10-08)
Spec: Roadmap R-0210, R-0214 (Kurz-Ledger ohne Spec)
Heavy: none — ein neuer Server-Test ohne Produktivcode und zwei Doku-Seiten; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, ruff sauber, Doku DE und EN im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-08 von der Aufsicht (adminhelper-ac) aus R-0210 und R-0214, beide von Kevin in der Triage vom
2026-10-07 als Futter für den Loop angenommen. Dieses Ledger ist der erste Messlauf des Agenten-Teams (Team-Plan
Phase 0, Kevin 2026-10-08): `ledger-loop.sh` baut es unter Kevins Benutzer mit eigenem Builder-HOME. Gemessen werden
Turns, Verweigerungen, Dauer und Limit-Anteil je Task. Zeilenangaben main@7129dc57.

### T1 — Schutztest: kein `to_dict` liefert einen Zeitstempel ohne Offset (R-0210)  [x]
Komponente: server · Dateien: apps/server/tests/test_to_dict_utc_offsets.py
Evidenz: run.sh[quick] server: 4 passed, 0 failed, 14 skipped @8f7fcc53 2026-10-09T09:47:54+02:00
Review: approve (sonnet/high) · round 1
Änderung: Ein neuer Test geht alle ORM-Klassen mit eigenem `to_dict` durch. Er findet sie über die Mapper-Registry
von `Base`, nicht über eine feste Liste: Ein neues Modell wird so automatisch mitgeprüft, und ein entferntes bricht den
Test nicht (R-0208 nimmt `EnrollmentToken.to_dict`, `app/modules/enrollment/models.py:54`, gerade weg). Je Klasse
entsteht eine Instanz ohne Datenbank, jede `DateTime`-Spalte bekommt einen naiven Wert wie `datetime(2026, 10, 5, 12, 0)`.
Dann läuft `to_dict()` mit den Default-Argumenten. Jeder String im Ergebnis, auch verschachtelt, der als
ISO-Zeitstempel parst, muss auf `Z` oder einen Offset enden. Die Ausnahmen der Semantik-Stelle gelten:
`lastUsed` einer Connection ist ein gespeicherter String und wird nicht geprüft. Eine Klasse, für die sich ohne
Pflicht-Beziehungen keine Instanz bauen lässt, steht als benannte Ausnahme mit Grund im Test und wird nicht still
übersprungen. Die Prüffunktion bekommt einen eigenen Negativfall: Ein dict mit `datetime(...).isoformat()` muss sie als
Fehler melden. Sonst wäre ein Test, der nie anschlägt, nicht von einem guten zu unterscheiden.
Beweis: Roadmap R-0210 — code-review R-0064 (F5), Worker B, 2026-10-06, feature/tz-aware-datetimes: ein neues
`to_dict` mit `.isoformat()` schreibt still wieder einen Zeitstempel ohne Offset; heute hält kein Test das auf.
Semantik: `docs/developer/api-reference.html:50`: „Zeitstempel in Antworten sind RFC 3339 in UTC mit `Z`, z. B.
`2026-10-05T12:00:00Z` – auch dort, wo das Schema sie als `string` führt. Ausnahmen: `lastUsed` einer Connection ist
ein gespeicherter String …“
Dedup-Key: ref:server:to_dict:offset-guard-test
Verify: bash scripts/dev/verify.sh server --strict -- tests/test_to_dict_utc_offsets.py
Doku: keine (intern)

### T2 — FRP-Tunnel-Doku: DE und EN mit demselben Inhalt (R-0214)  [?] (Doku ist gebaut (nur die zwei Task-Dateien im Arbeitsbaum geändert), aber 'verify.sh scripts --strict' ist nicht grün: 'vm.py pytest' und 'scripts/dev pytest' sind SKIP mit 'python3 or pytest not installed' (Builder-Umgebung ohne .devenv.sh und ohne pytest), alle übrigen Schritte PASS (run.sh[quick]: 4 passed, 2 failed, 14 skipped). Bekommt die Builder-Umgebung pytest, damit T2 danach über task-close.sh geschlossen werden kann?)
Komponente: scripts · Dateien: docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html
Änderung: Die beiden Seiten sind auseinandergelaufen. Der deutschen fehlt der Abschnitt zur Firewall mit seiner
Tabelle (EN `:84`), der englischen fehlen „Architektur“ (DE `:41`) und „Provision-Token“ (DE `:76`). Die
Tunneltypen sind auf beiden Seiten verschieden ausführlich beschrieben (DE `:84`, EN `:48`). Beide Seiten bekommen
dieselben Abschnitte in derselben Reihenfolge, die der deutschen Seite als Vorlage. Fehlender Inhalt wird übersetzt,
nicht neu erfunden; widersprechen sich die Seiten in einer Aussage, gilt, was der Code tut: Ports und Pfade in
`apps/server/app/modules/frp/` und `apps/gateway/` nachlesen. Lässt sich ein Widerspruch so nicht klären, ist das ein
`[?]` mit beiden Fassungen, keine Wahl.
Beweis: Roadmap R-0214 — Planung R-0044, Worker A, 2026-10-06, main@3345e748: Abschnitte der beiden Seiten
verglichen.
Semantik: `.claude/rules/docs.md:16-18`: „vollständige Produkt- und Entwickler-Doku als zweisprachiges HTML (`docs/…`
DE, `docs/en/…` EN): Bedienung, Installation, Betrieb, Monitoring, FRP, … Beide Sprachen im selben Commit.“
`review.sh docs-pairs` prüft das beim Schließen.
Dedup-Key: ref:docs:frp-tunnel.html:de-en-drift
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/admin/frp-tunnel.html, docs/en/admin/frp-tunnel.html (das ist die Task)
