<!--
SPDX-FileCopyrightText: 2026 Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# CA-Issuer: Startprüfung, Server-Leaves und Renew-Laufzeit (Zug kern-ca-1)

Stand des Codes: `origin/main@94aba678` (nach dem Merge von `feature/ca-rotation`). Ledger: `tasks/kern-ca-1.md`.
Roadmap R-0918, R-0834, R-0880, R-0912, R-0833.

## Problem
- **R-0918:** Die Prüfung der Hierarchie beim Start (`apps/ca-issuer/app/storage.py:106` `ensure_hierarchy`) prüft
  das aktuelle Intermediate eines Scopes weniger vollständig als die retired Intermediates (`_load_retired`,
  `storage.py:247` mit `pki.intermediate_problem`). Details in `tasks/private/`.
- **R-0834:** Eine nicht lesbare `root.crt`, `<scope>.crt` oder `<scope>.key` bricht den Start mit einem nackten
  `ValueError` aus `pki.cert_from_pem`/`pki.key_from_pem` ab (`storage.py:169`, `:180-181`), ohne Datei und Scope.
- **R-0880:** `_provision_server_material` (`storage.py:373`) stellt das Gateway- bzw. frps-Leaf nur neu aus, wenn
  es altert, nicht passt, vom falschen Intermediate stammt oder die Kette fehlt; geänderte `DOMAIN`/`EXTRA_SANS`
  wirken erst nach `down -v` oder Ablauf der halben Laufzeit. Die Doku sagt nicht, wie die Neuausstellung kommt.
- **R-0912:** Das Trust-Bundle wird mit `write_bytes` direkt überschrieben (`storage.py:405`); ein Abbruch dabei
  hinterlässt ein leeres oder halbes Bundle, das nginx bzw. frps beim nächsten Start nicht laden.
- **R-0833:** `/renew` leitet die Laufzeit des Nachfolgers aus der Spanne des vorgelegten Zertifikats ab
  (`apps/ca-issuer/app/issuer.py:216-219`): ein Browser-Leaf, das `sign_leaf` vor dem Ende seines Intermediates
  gekürzt hat (≤ `LEAF_DAYS_NATIVE`), wird als native erkannt und bekommt 90 statt 365 Tage.

## Ziel
1. Beim Start durchläuft das aktuelle Intermediate jedes Scopes dieselbe Prüfung wie die retired ones; ein Fund
   bricht den Start mit Datei und Scope ab (`_invalid_hierarchy`, wie R-0666).
2. Nicht lesbare PEM-Dateien der Hierarchie brechen den Start mit `_invalid_hierarchy` ab, die Meldung nennt Datei
   und Scope.
3. Weichen die SANs des vorhandenen Server-Leafs von `DOMAIN`+`EXTRA_SANS` ab, stellt der Start ein neues Leaf aus.
4. Trust-Bundles werden atomar geschrieben (tmp-Datei im selben Verzeichnis, `os.replace`).
5. `/renew` bestimmt die Laufzeit aus der `kind` der Device-Line im Register (`browser` → `LEAF_DAYS_BROWSER`, sonst
   `LEAF_DAYS_NATIVE`); nur eine noch nicht erfasste Legacy-Identität fällt auf die Spanne zurück (`legacy_kind`).

## Nicht-Ziele
- Kein neues Format, keine Migration: `device_lines.kind` gibt es schon (`apps/ca-issuer/app/db.py:84`).
- Keine Änderung an `.env.example` (überschneidet sich mit `feature/db-roles`).

## Betroffene Komponenten & Dateien
`apps/ca-issuer/app/storage.py`, `issuer.py`, `tokens.py` (`RenewSigner`, `InMemoryTokenStore.renew`), `db.py`
(`DbTokenStore.renew`), Tests unter `apps/ca-issuer/tests/`, Doku `docs/admin/agent-deployment.html:189`,
`docs/en/admin/agent-deployment.html:187`, `changelog.d/kern-ca-1.md`.

## Datenmodell / API / Migrationen
Keine. `RenewSigner` ist intern (Signatur `Callable[[str], …]`, die `kind` der Line).

## Trade-offs & Alternativen
- R-0833: die `kind` als Spalte im Zertifikat (Extension) statt im Register — verworfen, das Register trägt sie
  bereits, und ältere Leaves hätten sie nicht.
- R-0880: SAN-Vergleich als Menge (Reihenfolge egal) aus `_classify_sans` gegen die SAN-Extension des Leafs; ein
  Leaf ohne SAN-Extension gilt als abweichend.

## Risiken & Rollback
Ein falscher SAN-Vergleich stellt bei jedem Start neu aus (harmlos, aber Log-Rauschen) — der Test prüft, dass ein
unverändertes Leaf bleibt. Die strengere Startprüfung kann eine bisher startende, aber fehlerhafte Hierarchie
stoppen; das ist gewollt, die Meldung nennt Datei und Scope. Rollback: Revert der Task-Commits.

## Doku-Impact
`agent-deployment` DE+EN: Ändert sich `DOMAIN` oder `EXTRA_SANS`, stellt der ca-issuer beim nächsten Start ein neues
Server-Leaf aus. CHANGELOG über `changelog.d/kern-ca-1.md`.

## Offene Fragen
Keine.
