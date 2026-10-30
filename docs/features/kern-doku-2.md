<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Doku Agent-Deployment: Prüfsatz für einen schon installierten apt-Keyring

Zug `kern-doku-2` (Roadmap R-0985). Stand: `origin/main@66d3ef6f`.

## Problem / Motivation

Das manuelle apt-Rezept (`docs/admin/agent-deployment.html:75-90`, EN `docs/en/admin/agent-deployment.html:75-90`)
installiert seit kern-doku-1 (#330) nur den Schlüssel mit dem veröffentlichten Fingerprint. Wer den Keyring mit einer
älteren Fassung des Rezepts eingerichtet hat, bekommt keinen Hinweis, die installierte Datei zu prüfen. Einzelheiten
privat.

## Ziel & Nicht-Ziele

- Ziel: Ein kurzer Prüfsatz im apt-Rezept: `gpg --show-keys --with-colons` auf
  `/usr/share/keyrings/adminhelper-archive-keyring.gpg` muss genau einen `pub`-Schlüssel mit `$FPR` zeigen; sonst
  Schritt 1 erneut fahren (er überschreibt die Datei). DE und EN gleich.
- Nicht-Ziel: das dnf-Rezept; `agent-install.sh` (installiert schon nur den gepinnten Schlüssel).

## Betroffene Komponenten & Dateien

`docs/admin/agent-deployment.html`, `docs/en/admin/agent-deployment.html`, `changelog.d/kern-doku-2.md`.

## Datenmodell / API / Migrationen

Keine.

## Externe Integrationen

`gpg --show-keys --with-colons` (GnuPG, Spalten-Format `doc/DETAILS`): eine `pub`-Zeile je Primärschlüssel, die
folgende `fpr`-Zeile trägt den Fingerprint in Feld 10 — dieselbe Auswertung wie Schritt 1 des Rezepts.

## Trade-offs & Alternativen

- Den Keyring bei jedem Lauf blind neu installieren lassen: deckt nur, wer das Rezept erneut fährt. Empfehlung: ein
  eigener Prüfsatz, der ohne Neuinstallation zeigt, ob etwas zu tun ist.

## Risiken & Rollback

Nur Doku; der Prüfsatz ändert nichts am System. Rollback: Revert.

## Doku-Impact

Genau diese Seite (DE+EN) und der Changelog.

## Offene Fragen

Keine.
