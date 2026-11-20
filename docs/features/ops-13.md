# ops-13 — agent-install.sh: TOFU-Ausweg nennt --ca-fp

Roadmap: R-1648 (REF)

## Problem / Motivation
Kennt der installierte Agent `--ca-fp` noch nicht, fällt `scripts/agent-install.sh` auf Trust-on-first-use zurück und
nennt als wirksamen Weg: „update the AdminHelper server, which ships the agent, and provision again with a new
token.“ Dass die neue Provisionierung wieder `--ca-fp` braucht, steht nicht da; ohne die Option bleibt auch der
zweite Lauf TOFU (Nit der Abschlussprüfung von ops-11, `scripts/agent-install.sh:396`).

## Ziel & Nicht-Ziele
Ziel: Die Zeile nennt `--ca-fp` ausdrücklich. Nicht-Ziel: das Verhalten des Fallbacks (TOFU bleibt) und
`agent-install.ps1`.

## Betroffene Komponenten & Dateien
`scripts/agent-install.sh` (Fallback-Zweig), `scripts/tests/agent_install_test.sh`.

## Datenmodell / API / Migrationen
Keine.

## Externe Integrationen
Keine.

## Trade-offs & Alternativen
Keine: eine Textzeile.

## Risiken & Rollback
Nur Text einer Warnung. Rollback: Revert des Task-Commits. Kevin merged (`scripts/agent-install.sh`, CLAUDE.md §2).

## Doku-Impact
Keine: `docs/admin/agent-deployment.html` beschreibt `--ca-fp` schon.

## Offene Fragen
Keine.
