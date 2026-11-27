<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# kern-ca-15 — ca-issuer: Erneuerung mit Besitznachweis, Entrypoint-Test

Zug der Kern-Session (Roadmap R-1812, R-1813). Kevin 2026-11-27: beide angenommen; für R-1812 Form und Übergang
entschieden (unten).

## Problem je Zeile

- **R-1812** ca-issuer `POST /renew` (`apps/ca-issuer/app/main.py:246`, `apps/ca-issuer/app/issuer.py:218`):
  Erneuerung härten. Ziel (Kevin 2026-11-27): Der Client weist nach, dass er den privaten Schlüssel des
  vorgelegten Zertifikats besitzt.
  - Neues Feld `proof` in `RenewRequest` (`main.py:197`): Base64 einer ECDSA-P-256/SHA-256-Signatur (ASN.1 DER)
    mit dem Schlüssel des vorgelegten Zertifikats über `b"AdminHelper renew v1\x00"` + die DER-Bytes der CSR. Der
    feste Präfix trennt diese Signatur von jeder anderen, die der Schlüssel leistet; die CSR bindet den neuen
    Schlüssel an den alten, ein Nonce-Roundtrip entfällt.
  - Der ca-issuer prüft `proof` mit dem Public Key des vorgelegten Zertifikats; eine falsche oder unlesbare
    Signatur ist `403` wie jede andere abgelehnte Erneuerung.
  - Übergang (Kevin 2026-11-27): Ein Renew ohne `proof` wird noch angenommen und mit einer `WARN`-Zeile (CN,
    Scope) protokolliert; ab dem übernächsten Release lehnt der ca-issuer ihn ab (eigene Roadmap-Zeile, hängt an
    R-1812).
  - Agent (`apps/agent/internal/enroll/renew.go:69`) signiert mit dem bisherigen Schlüssel (`KeyPath`), bevor er
    den neuen speichert. Desktop (`apps/desktop/src-tauri/src/enrollment.rs:814`) behält beim Renew den Schlüssel
    und signiert mit ihm (rcgen `SigningKey::sign`, ECDSA P-256 SHA-256 ASN.1).
- **R-1813** `apps/ca-issuer/docker-entrypoint.sh:28` startet uvicorn mit `--no-proxy-headers`, ohne Test. Ziel:
  ein Test wie `apps/server/tests/test_server_entrypoint.py:66`, der die Option im Entrypoint festhält.

## Nicht-Ziele

- Die Ablehnung ohne `proof` (später, eigene Zeile).
- Browser-Zertifikate: sie erneuern nicht über `/renew` des Clients, sondern per neuem Enrollment.
- Keine Änderung am Gateway, an `/enroll` oder `/trust`.

## Risiken & Rollback

- Ein Fehler in der Prüfung ließe Agenten und Desktop nicht mehr erneuern. Die Tests prüfen die Signatur über
  die Sprachgrenze: ein fester Vektor (`apps/ca-issuer/tests/fixtures/renew_proof_vector.json`) wird von Python,
  Go und Rust je mit der eigenen Kopie des Präfixes geprüft; ein Renew ohne `proof` bleibt im Übergang
  möglich, ein Rollback des ca-issuer schadet neuen Clients nicht (das Feld wird ignoriert).
- Keine Migration, kein Wire-Format außer dem neuen optionalen Feld.

## Heavy

linux-full: `apps/ca-issuer` und `apps/agent` (Stack- und Agent-Schritte im Sammellauf).

## Doku-Impact

`docs/developer/index.html` und `docs/en/developer/index.html` (ca-issuer: `/renew` mit Besitznachweis), Changelog
neutral.

## Offene Fragen

Keine (Kevin 2026-11-27).
