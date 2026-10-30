<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# klein-doku-2 — Doku: Agent-Deployment und Agent-Entwicklerseite

Roadmap R-0944, R-0882. Beide ändern nur Doku (DE+EN) und einen CHANGELOG-Satz, kein Verhalten. `overlap.sh` ohne
Treffer (`kern-ca-1` ist gemergt). R-0946 (`DEVELOPMENT.md`) fährt nicht mit: db-roles, api-contracts und
api-contracts-clients ändern die Datei noch; die Zeile wartet in `klein-doku-3`.

## Problem / Motivation
- **R-0944:** `docs/admin/agent-deployment.html` (EN gleich) sagt zu `--insecure`, den von `provision` ausgegebenen
  Fingerprint mit dem CA-Fingerprint aus dem Provisionierungs-Tab zu vergleichen. `provision` gibt aber den SHA-256 des
  vom Server vorgelegten Leaf-Zertifikats aus (`apps/agent/internal/provision/provision.go`, Block „Fingerprint“); der
  CA-Fingerprint gleicht ihm nie. Soll: den Leaf-Fingerprint des Servers als Vergleichswert nennen.
- **R-0882, Doku:** `docs/developer/agent.html` (EN gleich) nennt `collectServiceHealth`, `collectWatchedServices`,
  `collectDocker`, `collectZFS`, `collectProxmox`, `collectSmart` und `collectSystemState` ohne den `ctx`-Parameter,
  den sie seit `agent-run-ctx` haben. Der Satz „eine IP-Adresse nennt das Zertifikat nur, wenn sie in `EXTRA_SANS`
  steht“ (agent-deployment DE+EN, CHANGELOG-Eintrag in `[Unreleased]`) ist zu absolut: das Zertifikat nennt auch
  `DOMAIN` und `127.0.0.1`.

## R-0882, darwin-vet: fährt nicht mit
`GOOS=darwin go vet ./...` scheitert nicht nur an `internal/service`: auch `internal/config` hat keine darwin-Datei
(`FrpDir`, `LogDir`, `MonitorDir`, `OwnByAdministrators`). Der Agent wird für Linux und Windows gebaut; darwin zu
unterstützen wäre ein eigenes Vorhaben. Ein Stub allein behebt den Fund nicht. Frage an Kevin (Gate): darwin-vet
ablehnen (Empfehlung: der Agent liefert nur Linux und Windows) oder als eigene Zeile führen.

## Ziel & Nicht-Ziele
- Vergleichswert und Signaturen stimmen mit dem Code überein; die EXTRA_SANS-Aussage ist nicht mehr absolut.
- Nicht-Ziel: Code; darwin-Unterstützung.

## Betroffene Komponenten & Dateien
`docs/admin/agent-deployment.html`, `docs/en/admin/agent-deployment.html`, `docs/developer/agent.html`,
`docs/en/developer/agent.html`, `CHANGELOG.md` (ein Satz im Eintrag `[Unreleased]`).

## Datenmodell / API / Migrationen
Keine.

## Trade-offs
Den CHANGELOG-Eintrag in `[Unreleased]` direkt ändern statt über ein Fragment: der Eintrag steht schon dort, ein
Fragment würde ihn doppeln. `overlap.sh` meldet für `CHANGELOG.md` keinen offenen Branch.

## Risiken & Rollback
Reine Doku; `git revert`.

## Doku-Impact
Die vier Seiten oben und der CHANGELOG-Satz, DE+EN.

## Offene Fragen
darwin-vet (R-0882): siehe oben.
