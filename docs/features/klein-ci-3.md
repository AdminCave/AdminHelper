<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ci-3 — Spec

## Problem
- **R-1385** (Nit aus ci-13): der Cache-Wächter `.github/scripts/cache_settings.sh` erkennt einen Image-Build in einem
  `run:`-Schritt nur als `docker build`/`docker buildx build|bake` mit Leerzeichen. `/usr/bin/docker build`, ein
  Tab als Trenner, `docker compose build`, `docker image build` und `docker builder build` laufen durch, obwohl ein
  Workflow ohne Caches sie nicht zulassen soll.
- **R-1386** (Nit aus ci-13): `docs/developer/cicd.html` (DE+EN) zeigt `cosign verify` mit `--certificate-identity`
  und nennt die verankerte Regex für Skripte, sagt aber nicht, dass nur die feste Identität die Version bindet; die
  Regex nimmt jedes Release-Tag an.
- **R-1396** fährt nicht mit: sie ändert `.github/workflows/ci.yml` (Kevin merged) und wandert in `tasks/klein-ci-4.md`.

## Ziel / Nicht-Ziele
Das Muster `dockerbuild` erkennt genau die genannten Formen (Pfad vor `docker`, beliebiger Leerraum, Unterbefehle
`compose`, `image`, `builder` vor `build`/`bake`); alles andere (`docker compose up`, `docker image ls`,
`docker builder prune`, `imagetools`) bleibt grün. Kein Parser für Shell-Syntax, keine weiteren Formen.

## Dateien
`.github/scripts/cache_settings.sh`, `.github/scripts/cache_settings_test.sh`; `docs/developer/cicd.html`,
`docs/en/developer/cicd.html`.

## Datenmodell / API / Migrationen
Keine.

## Doku-Impact
`cicd.html` DE+EN (ein Satz zur Version in der Signatur-Prüfung). Der Wächter ist in `cicd.html` beschrieben; die
Beschreibung nennt die erkannten Formen nicht einzeln und bleibt gültig.

## Risiken & Rollback
Gering. Ein zu weites Muster macht ein Workflow ohne Caches rot, das Test mit dem echten `ci.yml`, `release.yml` und
`docker.yml` fängt das ab. Je Task einzeln zurücknehmbar.

## Offene Fragen
Keine.
