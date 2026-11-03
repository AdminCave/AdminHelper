<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-laufzeit-1: Laufzeiten auf aktuelle Stable/LTS

Kevin 2026-11-02: alle Laufzeiten auf die aktuelle LTS- bzw. Stable-Linie. Die Versionen sind am 2026-11-02 nachgeprüft.

## Problem je Zeile
- **R-1029 (REL):** Das Gateway basiert auf `nginx:1.29-alpine`. Die Mainline 1.29 bekommt seit 2026-05-13 keine Fixes mehr (endoflife.date/nginx). Die stabile Linie ist 1.30 (`nginx:1.30.6-alpine`).
- **R-1030 (REF):** Die Python-Images (Root-`Dockerfile` des Servers, `apps/monitoring`, `apps/ca-issuer`) laufen auf `python:3.12-slim`, die CI-Matrix auf 3.12 und 3.13. Ziel: Images auf 3.14, CI-Matrix 3.14 und 3.15, Lock-Jobs auf 3.14, gehashte Locks neu unter 3.14. Ein 3.15-Image kommt erst, wenn pyyaml cp315-Wheels hat (6.0.3 hat am 2026-11-02 keine).
- **R-1031 (REF):** Node 22 steckt im Root-`Dockerfile` (`frontend-build`), in `ci.yml`, `release.yml` und `audit.yml`. `@types/node` steht auf 25. Ziel: Node 26 LTS (gepflegt bis 2029-04-30, endoflife.date/nodejs) und `@types/node` 26.
- **R-1033 (REF):** Laut docs.victoriametrics.com/victoriametrics/lts-releases gibt es VictoriaMetrics-LTS-Linien nur für Enterprise („LTS releases are published for Enterprise versions of VictoriaMetrics only“). Die Fixes dieser Linien stehen auch im jeweils neuesten regulären Release. Deshalb geht das Community-Image auf die aktuelle Stable v1.155.0 (2026-10-26) statt v1.144.0, mit Digest-Pin.
- **R-1032 (Redis 8)** fährt nicht mit. Die Lizenzwahl (RSALv2/SSPLv1/AGPLv3) ist Kevins Entscheidung, die Zeile liegt im nächsten Zug.

## Doku-Impact
`DEVELOPMENT.md` (Node-Voraussetzung, Python-Versionen) und `docs/developer/cicd.html` DE+EN (Matrix-Namen `py3.12|py3.13`). Einträge in `THIRD_PARTY_LICENSES.md` nur, wo eine Version genannt ist. Dazu `changelog.d/kern-laufzeit-1.md`.

## Risiken & Rollback
- **Prüfnamen:** Das Ruleset fordert die Server-Jobs unter den Namen `Server (pytest, py3.12|py3.13)`. Mit der neuen Matrix heißen sie `py3.14|py3.15`, das Ruleset passt Kevin beim Merge an (Repo-Einstellung).
- **Workflows:** Der PR ändert `.github/workflows/`, deshalb merged Kevin.
- **VictoriaMetrics:** Elf Minor-Versionen Sprung. Die Update-Notes im CHANGELOG von v1.145 bis v1.155 werden vor dem Bauen gelesen. Das Datenformat ist rückwärtskompatibel, das ist zu belegen.
- **Python 3.14:** Die Locks werden neu aufgelöst, Pins können sich verschieben. Das prüfen die Lock-Jobs der CI.
- **Rollback:** jede Task einzeln per Revert.
