<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-10 — Erstkontakt-Doku in Einklang mit dem Code

Zug `tasks/klein-doku-10.md` mit R-1716. `overlap.sh` (2026-11-24): kein offener Branch ändert README.md, die beiden
`installation.html`, `.env.example`, `DEVELOPMENT.md` oder `SECURITY.md`; kern-server-14 und ops-16 sind gemergt.

Die Zeilenangaben der Roadmap-Zeile sind veraltet; die Punkte (a) bis (e) wurden am Stand `origin/main@7d787e4d2`
neu gegen den Code geprüft.

## Problem / Motivation
- **(a) Voraussetzungen.** `scripts/install.sh` verlangt `minisign` (`MINISIGN_PUBKEY` ist gesetzt, ohne das Programm
  bricht `verify_sums_signature` ab); `scripts/init-secrets.sh` ruft `openssl` auf. Weder README noch die
  Voraussetzungen in `docs/admin/installation.html` und `docs/en/admin/installation.html` nennen eines von beiden.
  Der Satz „Ist die Release-Signatur scharf geschaltet“ steht nicht mehr in der Doku (schon behoben).
- **(b) DE und EN weichen ab.** Port `8445`: DE „optional (falls genutzt)“, EN „recommended“; der Agent-Einzeiler
  (`docs/admin/agent-deployment.html`, Abschnitt Repo-Schlüssel von `:8445`) braucht ihn. Linux-Distributionen und der
  DNS-Eintrag für `frp.example.com` stehen nur in EN. Der manuelle Weg `docker compose pull server` /
  `docker compose up -d server` steht nur im DE-Abschnitt Updates.
- **(c) Bootstrap-Token.** README (Zeile 234–238), `.env.example` (Zeile 58–62) und `DEVELOPMENT.md` (Zeile 886, 928)
  sagen, der Token liege in `data/.bootstrap_token` und stehe im Log. Dort liegt der Hash; der Token steht in
  `data/.bootstrap_setup` und nie im Log (`apps/server/app/main.py`: `write_private_file(BOOTSTRAP_SETUP_FILE, token)`,
  das Log nennt nur Pfad und Befehl). Richtig ist `docker compose exec server cat /app/data/.bootstrap_setup`, wie
  `docs/admin/installation.html` es schon beschreibt.
- **(d) `.env.example`.** Zeile 41 nennt ein `certs/`, das kein Dienst liest (das Gateway-Zertifikat stellt der
  `ca-issuer` aus, `DOMAIN` ist das SAN). `VISITOR_PORT_START`/`_END` stehen in der Variablentabelle beider
  `installation.html`, aber `docker-compose.yml` reicht sie nicht an den Server durch (`apps/server/app/core/config.py`
  liest sie, der Standard 6000–6999 gilt).
- **(e) `SECURITY.md`.** „frps container capability hardening — attempted and reverted“ stimmt nicht mehr:
  `docker-compose.yml` setzt für frps `cap_drop: [ALL]` mit `cap_add: [DAC_OVERRIDE, SETUID, SETGID, KILL]`. Der Eintrag
  „Base-image / GitHub-Action tag pinning“ stimmt nicht mehr: die Dockerfiles ziehen ihre Basis-Images per `@sha256`,
  alle `uses:` der Workflows sind auf einen Commit-SHA gepinnt (106 von 106).

## Ziel & Nicht-Ziele
Jede Aussage der fünf Punkte stimmt mit dem Code überein, in beiden Sprachen gleich. **Nicht-Ziele:** kein Verhalten
ändern (die Compose-Durchreichung von `VISITOR_PORT_*` ist ein Verhaltens-Eingriff und bleibt Kevins Wort); keine
Umformulierung an Stellen, die der Fund nicht berührt.

## Betroffene Komponenten & Dateien
`README.md`, `docs/admin/installation.html`, `docs/en/admin/installation.html`, `.env.example`, `DEVELOPMENT.md`,
`SECURITY.md`. Keine Code-Datei.

## Datenmodell / API / Migrationen
Keine.

## Trade-offs & Alternativen
`VISITOR_PORT_START`/`_END`: Die Tabellenzeile bekommt den Hinweis, dass die mitgelieferte `docker-compose.yml` die
Variable nicht durchreicht (Standard 6000–6999; wer sie ändern will, trägt sie unter `environment:` des Servers ein).
Alternative: sie in Compose durchreichen. Das ändert eine Laufzeit-Datei und ihr Verhalten und gehört nicht in einen
Doku-Zug; Empfehlung bleibt der Doku-Hinweis, die Frage an Kevin steht am Gate.

## Risiken & Rollback
Reine Doku. `.env.example` gehört zum Laufzeit-Bundle (`RUNTIME_FILES`), dort ändern sich nur Kommentare; der
Doku-Smoketest (`doc_smoke_test`, `doc-smoke --env`) deckt die Variablennamen ab. Rückgängig per Revert.

## Doku-Impact
Die Änderung ist die Doku: README, beide Installationsseiten (DE+EN gleichzeitig), `.env.example`, `DEVELOPMENT.md`,
`SECURITY.md`. Kein `changelog.d`-Fragment (kein Nutzerverhalten).

## Offene Fragen
- `VISITOR_PORT_START`/`_END` in `docker-compose.yml` durchreichen? Empfehlung: nein, Doku-Hinweis (Verhalten ist
  Kevins Bereich).
