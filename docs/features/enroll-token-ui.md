<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Registrierungs-Token im Web-Panel ausstellen

Roadmap R-0396 (FEAT) · Kevin, Onboarding eines neuen Benutzers nach der Installation v0.45.0, 2026-10-16.

## Problem / Motivation

Unter erzwungenem mTLS kommt ein neuer Benutzer nur über ein Einmal-Token an sein erstes Zertifikat
(ADR 0003, `docs/admin/benutzer.html:91`). Ein Admin stellt dieses Token heute nur per API aus
(`POST /api/enrollment/token/for`, mit Admin-Zertifikat) oder per Server-CLI im Container
(`python -m app.cli mint-enroll-token`). Im Web-Panel gibt es keinen Weg: `apps/web/src` ruft
`/api/enrollment` nirgends auf (main@aa7decf6). Der Admin verwaltet die Benutzer aber genau dort.

## Ziel & Nicht-Ziele

**Ziel:** In der Benutzerliste des Web-Panels stellt ein Admin je Benutzer ein Registrierungs-Token aus.
Er wählt die Gültigkeit (10 Minuten, 1 Stunde, 24 Stunden; voreingestellt 10 Minuten), sieht das Token
genau einmal mit Kopier-Knopf, die Ablaufzeit in Ortszeit und einen Hinweis, wo es eingelöst wird
(Desktop: „Gerät mit Token registrieren“).

**Nicht-Ziele (Entscheidungen am Gate, Kevin 2026-10-16):**
- Kein Knopf im Desktop-Client; der hat keine Benutzerverwaltung.
- Kein Browser-Token (`browser: true`, langlebiges Zertifikat) aus dem Web-Panel; das bleibt API und CLI vorbehalten.
- Keine Liste offener Tokens und kein Widerruf eines Tokens; es ist einmalig und läuft ab.
- `POST /api/enrollment/token` (Selbst-Registrierung) bekommt keine wählbare Gültigkeit.

## Betroffene Komponenten & Dateien

- **Server** `apps/server/app/modules/enrollment/router.py` (`EnrollmentTokenForRequest` `:88-90`,
  `mint_enrollment_token_for` `:93-120`, `_mint_token` `:36-52`), `enrollment/service.py`
  (`mint_enrollment_token` `:29-51`, `DEFAULT_TTL` `:26`), Tests `apps/server/tests/test_enrollment_mint.py`,
  `apps/server/tests/openapi.snapshot.json`.
- **Web** `apps/web/src/lib/api/users.ts`, `lib/api/types.ts`, `pages/Users.svelte` (Zeilen-Aktionen
  `:104-110`), neues Modal `modals/EnrollTokenModal.svelte` (nach dem Muster von `KeyRevealModal.svelte`),
  `lib/i18n/dictionaries.ts`, Playwright `tests/e2e/crud.spec.ts` und `tests/e2e/mocks.ts`.
- **Doku** `docs/admin/benutzer.html:91` / `docs/en/admin/users.html:85` (Onboarding, Schritt 2),
  `docs/developer/api-reference.html:158` / EN, `CHANGELOG.md`.

## Datenmodell / API / Migrationen

Keine Migration: `enrollment_tokens.expires_at` gibt es schon (`models.py:58`, naive UTC).

API, beide Änderungen additiv:
- `POST /api/enrollment/token/for` nimmt optional `ttl_minutes` (Ganzzahl, 1 bis 1440, Standard 10 =
  `DEFAULT_TTL`); ein Wert außerhalb ist 422.
- Beide Token-Routen (`/token`, `/token/for`) liefern zusätzlich `expiresAt`: den gespeicherten Ablauf der
  Token-Zeile als UTC-Zeitstempel mit `Z`.
- Das Audit-Detail von `enrollment.token.minted_for` nennt die Gültigkeit (z. B. `browser=False, ttl=60min`),
  damit länger gültige Tokens im Audit-Log auffindbar sind.

`mint_enrollment_token` behält seine Signatur und Rückgabe: Die Server-CLI ruft sie (`cli.py:90`), und
R-0397 baut dort parallel. Den Ablauf liefert eine zweite Funktion daneben oder die gespeicherte Zeile.

Vertrags-Drift: Web liest `expiresAt` und schickt `ttl_minutes`; Desktop (`enrollment.rs`) und Agent lesen
die Antwort von `/token/for` nicht und ignorieren unbekannte Felder. Die Antwort ist ein untypisiertes
`dict`, das OpenAPI-Schema ändert sich nur am Request (`ttl_minutes`).

## Externe Integrationen

Keine. Die Zwischenablage nutzt `navigator.clipboard.writeText` wie `KeyRevealModal.svelte`.

## Trade-offs & Alternativen

- **Ablaufzeit vom Server (gewählt)** statt im Web „jetzt + 10 min“ zu rechnen: stimmt auch bei
  wählbarer Gültigkeit und bei einer geänderten `DEFAULT_TTL`.
- **Wählbare Gültigkeit (gewählt, Kevin):** Ein Token, das 10 Minuten gilt, verfällt bei einer Übergabe
  per Mail oder Chat leicht. Die Obergrenze 24 h hält die Lebensdauer des Geheimnisses klein; es bleibt
  einmalig und wird gehasht gespeichert. Die drei Stufen im Web halten die Auswahl einfach, die API erlaubt
  jeden Wert bis 1440.
- **Eigenes Modal statt `KeyRevealModal`:** Titel, Hinweis, Ablaufzeit und Gültigkeitsauswahl unterscheiden
  sich; `KeyRevealModal` bleibt für API-Keys unverändert.

## Risiken & Rollback

Ein 24 h gültiges Token ist ein längeres Zeitfenster für Missbrauch, falls es abgefangen wird. Abhilfe:
Audit-Detail mit Gültigkeit, Standard bleibt 10 Minuten, Obergrenze 24 h. Rollback: Revert des Merges;
keine Datenänderung.

## Doku-Impact

Sichtbar: Onboarding-Schritt 2 in `benutzer.html`/`users.html` nennt den Knopf in der Benutzerliste und die
Gültigkeit; die API-Referenz (DE+EN) nennt `ttl_minutes` und `expiresAt`; CHANGELOG unter `### Added`.

## Offene Fragen

Keine. Die vier Entscheidungen (nur Web, Ablauf vom Server, kein Browser-Token, wählbare Gültigkeit) sind
am Gate gefallen.
