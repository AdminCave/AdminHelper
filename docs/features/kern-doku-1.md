<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Doku Agent-Deployment: manuelles apt-Rezept übernimmt den Schlüssel-Export aus `agent-install.sh`

Zug `kern-doku-1` (Roadmap R-0857). Stand: `origin/main@41dac791`.

## Problem / Motivation

`docs/admin/agent-deployment.html:76-85` (EN `docs/en/admin/agent-deployment.html:76-85`) beschreibt die manuelle
Einrichtung der apt-Quelle. `scripts/agent-install.sh` (`pinned_keyring`, `:180-208`) richtet den Schlüssel seit
#275 über einen Export aus einem Wegwerf-Keyring ein; die Doku beschreibt diesen Weg für das Skript schon
(`agent-deployment.html:51`). Das manuelle Rezept übernimmt ihn. Einzelheiten privat.

## Ziel & Nicht-Ziele

- Ziel: Das apt-Rezept importiert die geladene Datei in ein Wegwerf-Verzeichnis (`mktemp -d`), exportiert nur den
  Schlüssel `$FPR`, prüft, dass der Export genau diesen Primärschlüssel trägt, installiert nur ihn und räumt auf.
  DE und EN gleich, Kommentare im Rezept nennen den Grund.
- Nicht-Ziel: das dnf-Rezept (`gpgkey=` zeigt auf den Server, dnf zeigt den Fingerprint beim Import); das Skript.

## Betroffene Komponenten & Dateien

`docs/admin/agent-deployment.html`, `docs/en/admin/agent-deployment.html`, `changelog.d/kern-doku-1.md`.

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

apt `Signed-By` nimmt eine binäre Keyring-Datei, wie `gpg --export` sie schreibt (so auch `agent-install.sh`).

## Trade-offs & Alternativen

- Das Rezept ruft `agent-install.sh` auf, statt den Export zu wiederholen: kürzer, aber das manuelle Rezept ist gerade
  der Weg ohne das Skript. Empfehlung: Export im Rezept, fünf Zeilen mehr.

## Risiken & Rollback

Ein Tippfehler im Rezept bricht beim Nutzer ab (fail-closed: ohne passenden Schlüssel wird nichts installiert).
Geprobt mit Wegwerf-Schlüsseln (Einzelheiten privat). Rollback: Revert.

## Doku-Impact

Genau diese Seite (DE+EN) und der Changelog.

## Offene Fragen

Keine.
