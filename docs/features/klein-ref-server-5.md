<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-ref-server-5 — Spec

## Problem
- **R-1176** (Nit aus dem security-Review kern-server-7): `_WINDOWS_DEVICE_NAMES` in
  `apps/server/app/modules/servers/schemas.py` führt CON, PRN, AUX, NUL, COM1–9 und LPT1–9 (auch mit hochgestellter
  Ziffer). Python 3.13 `ntpath.isreserved` zählt zusätzlich `CONIN$` und `CONOUT$` (auch mit Endung) als reserviert
  (lokal geprüft: `CONIN$`, `conout$`, `CONIN$.txt` → `True`). Der Name eines neuen oder umbenannten Servers wird im
  FRP-Bulk-ZIP ein Ordner (`clients/<name>/frpc.toml`).
- **Nicht verifiziert:** Microsoft Learn, „Naming Files, Paths, and Namespaces“, nennt `CONIN$`/`CONOUT$` nicht
  (Seite am 2026-11-12 gelesen). Grundlage ist allein CPythons Liste; die Zeile ist ein vorsorglicher Nit.

## Ziel / Nicht-Ziele
Ein neuer oder umbenannter Servername `CONIN$` oder `CONOUT$` (ohne Rücksicht auf Groß-/Kleinschreibung, auch mit
Endung wie `conin$.lab`) ergibt `422` wie die übrigen Gerätenamen. Ein gespeicherter Name bleibt gültig (R-1056). Nicht
Ziel: `COM0`/`LPT0` oder andere Namen (CPython führt sie nicht); der Namensvorschlag in `sftp.rs` (Desktop, eigene
Komponente, eigene Zeile).

## Betroffene Komponenten & Dateien
`apps/server/app/modules/servers/schemas.py`, `apps/server/tests/test_servers_name_windows.py`,
`docs/developer/api-reference.html`, `docs/en/developer/api-reference.html`, `changelog.d/klein-ref-server-5.md`.

## Datenmodell / API / Migrationen
Keine Migration; das Schema bleibt gleich (die Prüfung steht in einer Funktion, nicht im OpenAPI-Schema). Sichtbar:
`POST/PUT /api/servers` mit diesen zwei Namen ist `422` statt `201/200`.

## Doku-Impact
`api-reference.html` DE+EN (die Aufzählung der Gerätenamen am Eintrag `POST /api/servers`), Changelog-Fragment.

## Risiken & Rollback
Gering: zwei zusätzliche abgelehnte Namen. Ein bereits gespeicherter Name `CONIN$` bleibt editierbar. Rollback: Revert.

## Offene Fragen
Keine (Kevin hat die Zeile in der Triage 2026-11-09 angenommen).
