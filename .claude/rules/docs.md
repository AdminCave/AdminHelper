---
paths:
  - "docs/**"
  - "README.md"
  - "DEVELOPMENT.md"
  - "CHANGELOG.md"
---

# Doku-Regeln

<!-- Stufe 0 · Quelle: bisherige CLAUDE.md „Doku-Pflege" -->

Code-Änderung ohne passendes Doku-Update ist unvollständig. **Falsche Doku ist ein Bug** — korrigieren, auch wenn die
Stelle nicht Teil des Auftrags ist (Ausnahme zur Surgical-Regel).

- **`docs/`** — vollständige Produkt- **und** Entwickler-Doku als zweisprachiges HTML (`docs/…` DE, `docs/en/…` EN):
  Bedienung, Installation, Betrieb, Monitoring, FRP, Troubleshooting, Architektur, Komponenten-Grenzen, Datenflüsse,
  Wire-Protokolle und Auth, Plattform-Verhalten. **Beide Sprachen im selben Commit.** Im Zweifel über Soll-Verhalten
  zuerst hier nachschlagen.
- **`README.md`** — Einstieg: Install, Build, Usage, Features, CLI-Flags, Voraussetzungen, Troubleshooting.
- **`DEVELOPMENT.md`** — Dev-Setup (`.devenv.sh`), lokale Workflows, neue Abhängigkeiten oder Komponenten, Docker-Compose.
- **`CHANGELOG.md`** — Keep a Changelog + SemVer: `## [X.Y.Z] - YYYY-MM-DD` mit Added/Changed/Fixed/Removed; Einträge
  umlautfrei (ae/oe/ue), Gedankenstrich „—"; Neues unter `## [Unreleased]`.
- **Commit:** Doku im selben Commit wie der Code; der Conventional-Commit-Typ bleibt der der Code-Änderung. `docs:`
  nur, wenn ausschließlich Doku geändert wird.
- **Scannen, dann entscheiden:** `grep -rl '<Begriff>' docs README.md DEVELOPMENT.md` statt raten.
- **Pipeline-Doku:** `docs/developer/cicd.html` (DE + EN) beschreibt CI, Release und Signatur — bei Workflow-Änderungen
  mitziehen; der CI-Job `frp-consistency` prüft die vier `FRP_VERSION`-Pins.
- **Nie versionieren** (Repo ist öffentlich): Homelab-Namen und -Adressen, Tokens, ungefixte Sicherheitsfunde, interne
  Roadmaps und Ledger mit Infra-Details — die gehören nach `tasks/private/`.
