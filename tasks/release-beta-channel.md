<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Release: Beta ohne Suffix-Tag — Task-Ledger
Status: aktiv · Branch: feature/release-beta-channel · Review: am Ende
Spec: Roadmap R-0014
Heavy: none — nur Regeltext und ein Kommentar; kein Build-, Release- oder Install-Pfad ändert sich
DoD je Task: CLAUDE.md (Tests grün, ruff/gofmt/clippy/eslint sauber, Doku im selben Commit, SPDX bei neuen Dateien).
Task-Status: [ ] offen · [x] fertig · [~] übersprungen (Grund) · [?] braucht Entscheidung

Entscheidung Kevin 2026-10-20: Ein Beta ist der Tag `vX.Y.Z` ohne Suffix, als GitHub-Release mit „Pre-release“
veröffentlicht; bewährt es sich, setzt Kevin dasselbe Release auf „Latest“, ohne neuen Tag. Grund: Tags mit Suffix
baut die Pipeline heute nicht (tauri-cli 2.11.2 lehnt für das MSI eine nicht numerische Prerelease-Kennung ab,
`msi/mod.rs:336`; eine RPM-Version darf kein `-` tragen; `dpkg --compare-versions` sortiert `0.46.0-beta.1` über
`0.46.0`). `check-versions.sh` vergleicht weiter wörtlich.

Entschieden mit der Freigabe (Empfehlung): Gilt die 7-Tage-Regel (heute: stable frühestens 7 Tage nach dem RC ohne Fix und ohne
Rückmeldung) ab der Veröffentlichung als Pre-release? Empfehlung: ja, ein RC entfällt in diesem Schema.

### T1 — Kanäle in release.md und Kommentar in check-versions.sh  [x]
Komponente: scripts · Dateien: .claude/rules/release.md, scripts/release/check-versions.sh
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @e56d7728 2026-10-20T08:27:49+02:00
Review: am Ende (Branch-Review)
Änderung: `release.md`, Abschnitt „Ablauf und Kanäle“ (`:72-75`): Beta ist der Tag `vX.Y.Z` ohne Suffix, veröffentlicht als „Pre-release“ (`gh release edit vX.Y.Z --draft=false --prerelease`); der Wechsel auf „Latest“ (`gh release edit vX.Y.Z --prerelease=false --latest`) ist Kevins Entscheidung und ersetzt den Stable-Schnitt; die 7-Tage-Regel gilt ab der Veröffentlichung als Pre-release (Kevin 2026-10-20, Freigabe mit der Empfehlung); ein Fix ist ein neues Patch-Release. Den Grund in einem Satz (Suffix-Tags bauen MSI, RPM und deb heute nicht richtig) und die Folge nennen: `docker.yml` setzt `:latest` nach der Semver-Version des Tags, die Images `:latest` zeigen also auch auf ein Beta; `install.sh`/`update.sh` lesen `releases/latest` und damit nie ein Pre-release. Die Sätze zu `vX.Y.Z-beta.N` und `vX.Y.Z-rc.N` entfallen. `check-versions.sh:28-32`: der Satz zur offenen Entscheidung (R-0014, T6a) wird durch den Hinweis ersetzt, dass Tags kein Suffix tragen und der wörtliche Vergleich deshalb genügt.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: .claude/rules/release.md (Regeltext); sonst keine (intern)

### T2 — CLAUDE.md §10 und cicd.html an den Beta-Kanal angleichen  [x]
Komponente: scripts · Dateien: CLAUDE.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Evidenz: run.sh[quick] scripts: 6 passed, 0 failed, 12 skipped @05e0bc7f 2026-10-20T08:52:09+02:00
Review: am Ende (Branch-Review)
Änderung: Kevin 2026-10-20 (Harness-Datei auf sein Wort): `CLAUDE.md` §10, Zeile „Release-Kanäle“: Beta ist der Tag `vX.Y.Z` ohne Suffix, veröffentlicht als Pre-release; Stable entsteht per Flag auf „Latest“ ohne neuen Tag, frühestens 7 Tage nach dem Beta ohne Fix und ohne Rückmeldung; `hotfix` bleibt der einzige Weg daran vorbei; Verweis auf `.claude/rules/release.md` bleibt. `docs/developer/cicd.html` + EN, Abschnitt Container-Images: ein Satz, dass `:latest` dem neuesten Tag folgt, auch einem Beta (Pre-release), und wer nur Stable will, die Version pinnt (`install.sh`/`update.sh` tun das bereits über `releases/latest`); das Code-Beispiel „letzter Semver-Release“ entsprechend.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: CLAUDE.md · docs/developer/cicd.html + EN

### T3 — `:latest` erst mit Stable, Draft als Pre-release  [ ]
Komponente: scripts · Dateien: .github/workflows/docker.yml, .github/workflows/release.yml, .claude/rules/release.md, docs/developer/cicd.html, docs/en/developer/cicd.html, CHANGELOG.md
Änderung: Kevin 2026-10-20 (Workflow-Dateien; den PR mergt Kevin): `release.yml`, Draft-Schritt (softprops, `:520-528`): der Draft entsteht mit `prerelease: true`, damit „Publish“ in der Web-Oberfläche ein Beta nie zu „Latest“ macht. `docker.yml`: beim Tag-Push kein `:latest` mehr (`flavor: latest=false`, `X.Y.Z` und `sha` bleiben); ein neuer Job auf dem Release-Event, das beim Umschalten eines Releases von Pre-release auf Release feuert (vorher in der GitHub-Doku zu `release`-Events nachlesen, Quelle im Commit nennen, Unbelegtes als „nicht verifiziert“), setzt `:latest` auf das schon gebaute und signierte Image `X.Y.Z` (Manifest umtaggen, nicht neu bauen) und signiert den Tag wie den Bestand (cosign keyless); Rechte des Jobs minimal (`packages: write`, `id-token: write`, `contents: read`), Actions per SHA gepinnt wie im Bestand. Doku: `release.md` „Ablauf und Kanäle“ und `cicd.html` DE+EN sagen, dass `:latest` erst mit Stable kommt; `release.md` schränkt `install.sh` wie `cicd.html` ein (liest `releases/latest` nur ohne lokalen Checkout); Nit aus dem Branch-Review: EN `cicd.html` (~:517) „when that happens is set out in“. Die CHANGELOG-Zeile aus T2 entsprechend anpassen. Ein Beweis am echten Tag ist erst beim Beta möglich; das nennt der Commit-Body.
Verify: bash scripts/dev/verify.sh scripts --strict
Doku: .claude/rules/release.md · docs/developer/cicd.html + EN · CHANGELOG
