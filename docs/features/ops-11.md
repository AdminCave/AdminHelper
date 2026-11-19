# ops-11 — TOFU-Warnung in agent-install.sh

Roadmap: R-1634 (BUG)

## Problem / Motivation
Gibt der Admin `--ca-fp` an und kennt der installierte Agent die Option noch nicht, fällt
`scripts/agent-install.sh` auf Trust-on-first-use zurück. Die Warnung dazu sagt, der Admin solle
den Fingerprint, den der Agent ausgibt, mit dem Provisionierungs-Tab des Desktops vergleichen. Der
Tab zeigt aber den CA-Fingerprint, der Agent den des gepinnten Server-Zertifikats. Die beiden
stimmen nie überein: Der Vergleich schlägt immer fehl und gewöhnt Admins daran, die Warnung zu
übergehen. `agent-install.ps1` ist seit ops-10 T6 (7618a652f) korrigiert.

## Ziel & Nicht-Ziele
Ziel: Die Warnung verweist auf das Server-Zertifikat (wie der Hinweis des Agents) und auf ein
Agent-Update, damit `--ca-fp` wirkt. Nicht-Ziel: das Verhalten des Fallbacks selbst (TOFU bleibt).

## Betroffene Komponenten & Dateien
`scripts/agent-install.sh` (Fallback-Zweig), `scripts/tests/agent_install_test.sh`.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
Den Fallback ganz streichen (Abbruch statt TOFU), wenn `--ca-fp` gegeben, aber nicht unterstützt
wird: strenger, ändert aber sichtbares Verhalten bei Rollouts. Nicht Teil dieses Fixes.

## Risiken & Rollback
Nur Text einer Warnung. Rollback: Revert des Task-Commits.

## Doku-Impact
Keine: `docs/admin/agent-deployment.html` beschreibt den Vergleich mit dem Server-Zertifikat schon richtig.

## Offene Fragen
Keine.
