<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Server: Tokens an die Benutzer-ID binden

## Problem / Motivation

Access- und Refresh-Token tragen den Benutzer nur als `sub` = Benutzername (`apps/server/app/modules/users/auth_router.py:213`,
`:255`, `:391`). Der Name ist über die Zeit nicht eindeutig: ein Konto kann gelöscht und unter demselben Namen neu
angelegt werden. Beim Anmelden schützt die Anlege-Marke (`users.tokens_valid_after` = Anlegezeit,
`apps/server/app/modules/users/models.py:49`), aber jede Stelle, die einen Token per Name einem Konto zuordnet,
muss das selbst bedenken, etwa die Erkennung eines wiederverwendeten Refresh-Tokens (`_refuse_reused_refresh`,
`auth_router.py:134`, über `username_from_token_unverified`, `apps/server/app/core/auth.py:167`). Robuster ist ein
Token, der sein Konto über die ID nennt.

## Ziel & Nicht-Ziele

Ziel:
- Jeder Token trägt zusätzlich `uid` = `users.id`. `_get_user_from_token` (`auth.py:83`) sucht das Konto über `uid`;
  ein Token ohne `uid` (jeder vor dem Update ausgestellte) gilt nicht (Kevin 2026-10-29: alle melden sich einmal neu
  an, keine Übergangslogik).
- Die Reuse-Erkennung ordnet einen widerrufenen Refresh-Token über `uid` zu; ohne `uid` setzt sie keine Marke.
- `sub` bleibt (Logs, Audit-Label beim Logout, `require_cert_user`), entscheidet aber nicht mehr über das Konto.

Nicht-Ziele:
- Keine Änderung an Laufzeiten, Rotation, Blacklist oder Cookie.
- Keine Migration (die Claims stehen nur im Token).
- Keine Client-Änderung: Web und Desktop lesen den Token nicht, ein abgelehnter Token führt wie heute über den
  fehlgeschlagenen Refresh zum Login.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | server | `apps/server/app/core/auth.py`, `apps/server/app/modules/users/auth_router.py`, `apps/server/tests/conftest.py`, `apps/server/tests/test_token_uid.py` (neu), die elf Testdateien mit `create_access_token`/`create_refresh_token` (Liste in der Task), `docs/developer/server.html`, `docs/en/developer/server.html`, `CHANGELOG.md` |

## Datenmodell / API / Migrationen

Kein Schema, keine Route, keine Migration. Der Token-Inhalt ändert sich (neuer Claim `uid`); `TokenResponse` bleibt.
Vertrags-Drift: keine Client-Komponente dekodiert den Token (`grep` über `apps/web`, `apps/desktop`).

## Externe Integrationen

Keine. PyJWT wie bisher, `uid` ist ein zusätzlicher privater Claim.

## Trade-offs & Alternativen

1. **Einmal neu anmelden (Kevin 2026-10-29)** statt einer Übergangszeit, in der Tokens ohne `uid` per Name gelten:
   kein Code, der später wieder raus muss; Preis: nach dem Update landen Web und Desktop einmal auf dem Login.
2. **Konto über `uid` suchen, nicht `sub` und `uid` gemeinsam.** Ein Umbenennen gibt es heute nicht; käme es, bliebe
   die Sitzung gültig, was erwünscht ist. `sub` bleibt nur informativ.
3. **Ein Test-Helfer in `conftest.py`** statt jede der 43 Testaufrufe mit eigener ID-Suche: die Tests erzeugen
   Tokens heute aus dem Namen; der Helfer sucht die ID in der Test-DB.

## Risiken & Rollback

- Alle offenen Sitzungen enden beim Update; Release-Notes nennen das.
- Ein Rollback (Revert) macht die neuen Tokens nicht ungültig: ein älterer Server liest `sub` und ignoriert `uid`.

## Doku-Impact

`docs/developer/server.html` (Absatz Token-Claims und Liste zur Rotation/Reuse-Detection, DE+EN): `uid`, Zuordnung
über die ID, Tokens ohne `uid` gelten nicht. CHANGELOG (Changed: nach dem Update einmal neu anmelden).

## Offene Fragen

Keine; die Übergangsfrage hat Kevin am 2026-10-29 entschieden.
