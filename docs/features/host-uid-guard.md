<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Install: Installationsverzeichnis nur für den Installierenden, Warnung bei Container-UIDs auf dem Host

## Problem / Motivation

Die Container laufen unter festen UIDs: `server`, `scheduler`, `ca-issuer` und `monitoring` als `app` (UID 10001),
Postgres als UID/GID 70 (Image `postgres:*-alpine`). Dateien unter `./data` gehören auf dem Host deshalb UID 10001
(Entrypoint `chown -R app:app`, `apps/server/docker-entrypoint.sh:10`). `install.sh` legt das Installationsverzeichnis
(`--dir`, Standard `./adminhelper`, `scripts/install.sh:56` auf dem Stand von #275) mit der umask des Aufrufers an,
meist 0755. Ein anderes Host-Konto, das zufällig dieselbe UID trägt, kann dann in das Verzeichnis und an die Dateien
des Dienstes. `docs/admin/betrieb.html:85` rät schon, UID 10001 auf dem Host keinem anderen Konto zu geben; geprüft
wird das nirgends.

## Ziel & Nicht-Ziele

Ziel (Kevin 2026-10-29):
- `install.sh` setzt das Installationsverzeichnis auf `0750`; `update.sh` zieht ein bestehendes nach. Eigentümer
  bleibt, wer installiert (meist root; `install.sh` läuft auch als Nicht-root mit Docker-Gruppe).
- Beide prüfen vorab, ob auf dem Host ein Konto mit UID 10001 oder 70 existiert, und warnen dann mit UID und
  Kontoname (kein Abbruch).
- Doku: Installation und Betrieb nennen Verzeichnisrechte und die zwei UIDs.

Nicht-Ziele:
- Kein Wechsel der Container-UIDs, kein abgeleitetes Postgres-Image (eigenes Vorhaben, Kevin 2026-10-29: nein).
- Kein Abbruch bei einer Kollision; der Admin entscheidet.

## Betroffene Komponenten & Dateien

| Task | Komponente | Dateien |
|---|---|---|
| T1 | scripts | `scripts/install.sh`, `scripts/update.sh`, `scripts/tests/install_test.sh`, `scripts/tests/update_test.sh`, `docs/admin/installation.html`, `docs/en/admin/installation.html`, `docs/admin/betrieb.html`, `docs/en/admin/operations.html`, `CHANGELOG.md` |

## Datenmodell / API / Migrationen

Keine. Rechte eines Host-Verzeichnisses; `update.sh` ändert sie bei jedem Lauf idempotent.

## Externe Integrationen

Docker-Bind-Mounts löst der Docker-Daemon als root auf; die Container sehen `./data` unter `/app/data` und brauchen
keine Durchquerung des Host-Verzeichnisses. `getent passwd` (glibc/NSS) für die Kontosuche.

## Trade-offs & Alternativen

1. **0750 mit Eigentümer = Installierender** statt `root:root`: gleiche Wirkung gegen ein fremdes Konto, sperrt aber
   eine Nicht-root-Installation nicht aus.
2. **Warnen statt abbrechen** (Kevin 2026-10-29): ein bestehendes Konto umzubenennen ist Sache des Admins; ein Abbruch
   machte die Installation auf solchen Hosts unmöglich.

## Risiken & Rollback

- Ein Werkzeug, das als anderes Konto in das Installationsverzeichnis schaut (Backup-Agent eines Fremdanbieters),
  braucht danach Gruppenrechte oder root. Die Doku nennt das.
- Rollback: Revert; ein `chmod 755` stellt den alten Zustand her.

## Doku-Impact

`docs/admin/installation.html` (DE+EN): Verzeichnisrechte und die Warnung. `docs/admin/betrieb.html:85` /
`docs/en/admin/operations.html:52`: UID 70 neben 10001, beide prüft install/update. CHANGELOG (Changed).

## Offene Fragen

Keine; Kevin hat am 2026-10-29 entschieden. Bau erst nach dem Merge von #275 (ops-install-hardening, gleiche
Skripte).
