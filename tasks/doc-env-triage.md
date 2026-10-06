<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# doc-smoke `--env`: Namen gegen das ganze Repo statt gegen drei config.py, der eine Doku-Bug, Gate in der CI (R-0044) — Task-Ledger
Status: freigegeben · Branch: harness/doc-env-triage · Commit-Granularität: pro Task · Review: am Ende (feature-review; ci.yml ist ein Risikopfad ⇒ Reviewer Opus) · Modell: Opus
Freigabe: Aufsicht adminhelper-ac, 2026-10-06 (kleines Fund-Paket aus der in der Triage angenommenen Zeile R-0044; --env als Gate nach dem Plan von Stufe 8a; Delegation Kevin 2026-10-05)
Spec: Roadmap R-0044 (Kurz-Ledger ohne Spec)
Heavy: none — ein Doku-Prüfskript unter scripts/dev, sein hermetischer Test, ein CI-Schritt und Doku-Seiten; kein Stack-, Gateway-, PKI- oder Install-Pfad.
DoD je Task: CLAUDE.md (Tests grün, ruff check und ruff format sauber, shellcheck sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Geplant 2026-10-06 von Worker A für die Aufsicht (adminhelper-ac). Einteilung des Reports
`python3 scripts/dev/doc-smoke.py --env` auf main@3345e748: 138 Funde, 48 eindeutige Namen (je DE und EN).
- (a) Die Doku nennt einen Namen, den es im Repo außerhalb von `docs/` nirgends gibt: genau einer, `FRP_DOMAIN`
  (`docs/en/admin/frp-tunnel.html:53`, `:91`). Den Subdomain-Host eines HTTP-Tunnels setzt keine Env-Variable,
  sondern das Feld `subdomain_host` der FRP-Server-Konfiguration (`apps/server/app/modules/frp/config_generator.py:106`,
  `subDomainHost` in frps.toml). → T2.
- (b) config.py liest einen Namen, Doku und `.env.example` fehlen: keiner. Was eine der drei `config.py` liest, meldet
  `--env` gar nicht.
- (c) Ein Name, den es im Repo gibt, der aber keine App-Konfiguration ist: die übrigen 47. HTTP-Methoden und SQL
  (`POST`, `DELETE`, `DROP`), Log-Level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `WARN`), Agent-Zustände (`RUNNING`,
  `PAUSED`, `STOPPED`), Konstanten im Code (`CHECK_TYPE_METRICS`, `EXCLUDED_FSTYPES`, `CERT_REQUIRED`), Fehlercodes
  (`ERR_TLS_UNKNOWN_ISSUER`, `EX_TEMPFAIL`), Dateinamen (`SHA256SUMS`, `VERSION`), git und Dockerfile (`HEAD`, `FROM`),
  CI-Secrets (`MINISIGN_SECRET_KEY`, `MINISIGN_PUBKEY`, `REPO_GPG_PRIVATE_KEY`), Variablen der Harness-Skripte
  (`AH_ONLY`, `AH_REQUIRED`, `AH_TEST_DB`, `AH_ARGS`, `AH_NOTIFY_URL`, `ITEST_WEB_URL`, `FRP_VERSION`, `VENV_PKGS`), die
  Konfiguration des Agents (`ADMINHELPER_URL`, `API_KEY`, `MONITOR_URL`, `SERVER_ID`, `CACERT`, `INSECURE`,
  `SERVICES`), Test-Marker (`UPGRADE_OK`, `UPDATE_SH_OK`, `UPDATE_SH_SKIP`, `MISSING`, `UNVERIFIED`) und
  `PATH`/`PYTHONPATH`/`GLIBC_`. Als Ausnahmen passen sie nicht: Die Allowlist ist auf 5 Einträge gedeckelt
  (`doc-smoke.py` `_ALLOW_MAX`), zwei sind schon Pfade. → T1 statt 47 Ausnahmen.
Gegenprobe (main@3345e748, ohne Änderung, nur gelesen): Alle Großbuchstaben-Wörter aus `git grep` über die getrackten
Dateien außerhalb von `docs/`, `CHANGELOG.md` und `tasks/` als bekannt gezählt, bleibt von den 48 genau `FRP_DOMAIN`.
Entscheidungen der Aufsicht 2026-10-06: Branch `harness/…` nach Konvention (scripts/dev), gebaut interaktiv, nicht vom
Runner; Umsetzungsweg T1 wie geplant; `--env` wird Gate (T3), wie der 8a-Plan es ab ≤ 5 Ausnahmen vorsah
(`docs/features/harness-stufe-8a.md:130–132`).

### T1 — `--env`: bekannt ist ein Name, den das Repo außerhalb der Doku trägt (R-0044)  [ ]
Komponente: scripts · Dateien: scripts/dev/doc-smoke.py, scripts/tests/doc_smoke_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: `_known_env_names` (`doc-smoke.py:144`) nimmt zu den drei `config.py` und `.env.example` jedes Wort in
Großbuchstaben (`[A-Z][A-Z0-9_]{3,}`, als ganzes Wort) aus den von git getrackten Dateien außerhalb von `docs/`,
`CHANGELOG.md` und `tasks/` — eine Abfrage per `git grep`, gegen die getrackten Dateien wie beim Pfad-Check (gleicher
Grund: lokal und im CI dieselbe Antwort). `CHANGELOG.md` und `tasks/` zählen nicht, weil sie entfernte Namen als
Historie tragen. Außerhalb eines git-Checkouts bleiben die bisherigen Quellen. Ein Kommentar an der Stelle nennt den
Trade-off: ein Name, den nur noch ein Test oder ein Kommentar trägt, fällt nicht mehr auf. Docstring und `--help` sagen die neue
Regel; die Untergrenze (`len(known) < 10`) bleibt. Tests in `doc_smoke_test.sh` (Fixture als eigenes git-Repo): ein
Name nur in der Doku ⇒ Fund; ein Name, den eine getrackte `.py`- oder `.sh`-Datei trägt ⇒ kein Fund; ein Name nur in
`CHANGELOG.md` oder `tasks/` ⇒ Fund; eine ungetrackte Datei zählt nicht; `--env --strict` mit Fund ⇒ Exit 1.
Doku: der `--env`-Absatz in `docs/developer/cicd.html` und `docs/en/developer/cicd.html` (heute „noch kein Gate: die
Heuristik meldet derzeit 43 Namen …“) beschreibt die neue Regel; ob es ein Gate ist, sagt er erst mit Kevins Wort
(offene Frage am Gate).
Rot vorher: die Fälle „getrackte .sh trägt den Namen ⇒ kein Fund“ scheitern auf main.
Beweis: main@3345e748 · `python3 scripts/dev/doc-smoke.py --env` ⇒ `doc-smoke: 138 finding(s)` über 48 Namen, darunter
`POST`, `RUNNING`, `SHA256SUMS`, `AH_ONLY`
HEAD: 3345e748
Semantik: `docs/developer/cicd.html` (doc-smoke-Absatz): „Die zweite Prüfung --env (Namen in Großbuchstaben gegen die
drei config.py und .env.example) ist noch kein Gate: die Heuristik meldet derzeit 43 Namen, die gar keine
Env-Variablen sind (HTTP-Methoden, Log-Level, Dateinamen).“ — die Doku nennt die Fehlmeldungen selbst als den Grund,
warum es noch kein Gate ist; der Docstring von `doc-smoke.py` sagt, gemeint ist „a variable … known to at least one
… source“, und „a variable read by one service and documented for another is not drift“.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html (der `--env`-Absatz)

### T2 — `FRP_DOMAIN` in der FRP-Doku: der Subdomain-Host der FRP-Server-Konfiguration (R-0044)  [ ]
Komponente: scripts · Dateien: docs/en/admin/frp-tunnel.html, docs/admin/frp-tunnel.html
Änderung: `docs/en/admin/frp-tunnel.html:53` („HTTP-reverse-proxy tunnel on `FRP_DOMAIN`, subdomain-routed“) und
`:91` („443/tcp on `FRP_DOMAIN`“) nennen statt der Variable, die es nicht gibt, den Subdomain-Host der
FRP-Server-Konfiguration (Feld `subdomain_host`, in frps.toml `subDomainHost`). Die deutsche Seite hat zu beiden Zeilen
kein Gegenstück; ihre Zeile zum Tunneltyp `http / https` (`docs/admin/frp-tunnel.html:89`, „Web-UIs mit
Virtual-Host-Routing“) nennt denselben Subdomain-Host, damit beide Sprachen im selben Commit dasselbe sagen. Sonst
nichts an der Seite (die fehlende Firewall-Tabelle auf der deutschen Seite ist eine eigene Roadmap-Zeile).
Rot vorher: `python3 scripts/dev/doc-smoke.py --env --strict` meldet nach T1 genau `FRP_DOMAIN` (Exit 1).
Verify: bash scripts/dev/verify.sh scripts --strict   und   python3 scripts/dev/doc-smoke.py --env --strict
Doku: docs/admin/frp-tunnel.html + docs/en/admin/frp-tunnel.html (sie sind die Änderung)
Abhängt von: T1

### T3 — `--env` als Gate in der CI: `doc-smoke.py --paths --env --strict` (R-0044)  [ ]
Komponente: scripts · Dateien: .github/workflows/ci.yml, scripts/tests/doc_smoke_test.sh, docs/developer/cicd.html, docs/en/developer/cicd.html
Änderung: Der Schritt „Documentation smoke test“ im Job `ops-scripts` (`ci.yml:842`, heute `doc-smoke.py --strict`)
fährt `python3 scripts/dev/doc-smoke.py --paths --env --strict`; `--env` allein schaltet den Pfad-Check ab
(`check_paths = args.paths or not args.env`), deshalb beide Flags. Der Kommentar darüber (`ci.yml:835–837`, heute
„--env stays off … until that list is triaged (harness 8a, T17)“) sagt, dass beide Prüfungen Gate sind und warum
(die Namen sind nach R-0044 ohne Ausnahme sauber). Test in `doc_smoke_test.sh`: ein Fixture mit je einem Pfad- und
einem Env-Fund meldet unter `--paths --env --strict` beide, Exit 1; `--env` allein meldet den Pfad nicht (hält den
Schalter fest, den die CI-Zeile braucht). Doku: der `--env`-Absatz in `cicd.html` DE+EN nennt `--env` als Gate im
Job `ops-scripts`.
Rot vorher: der neue Testfall zu `--paths --env` gibt es auf main nicht; die CI-Zeile prüft heute nur Pfade.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: docs/developer/cicd.html + docs/en/developer/cicd.html (der `--env`-Absatz)
Abhängt von: T1, T2
