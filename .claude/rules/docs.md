---
paths:
  - "docs/**"
  - "README.md"
  - "DEVELOPMENT.md"
  - "CHANGELOG.md"
  - "changelog.d/**"
---

# Doku-Regeln

Pfadgebunden: für Dateien in einem Worktree (`../AdminHelper-<slug>/…`) lädt diese Datei nicht von selbst;
`/feature-plan`, `/feature-build` und `reviewer` lesen sie ausdrücklich.

**Wann:** Ändert sich dokumentiertes Verhalten, eine API, die Architektur, Konfiguration, Installation oder Betrieb,
gehört das Doku-Update dazu — in derselben Task (`Doku: <Dateien>`) oder gebündelt in einer Doku-Task desselben
Ledgers (`Doku: → T<n>`, `tasks/README.md`). Offene Doku-Punkte stehen damit im Ledger; vor der Abschlussprüfung und
dem Merge sind beide Sprachfassungen vollständig und aktuell (die Doku-Task ist `[x]`). Interne Änderungen ohne
dokumentierten Einfluss tragen `Doku: keine (<Grund>)`. **Falsche Doku ist ein Bug** — korrigieren, auch wenn die
Stelle nicht Teil des Auftrags ist (Ausnahme zur Surgical-Regel).

**Wo — jede Aussage an einer maßgeblichen Stelle;** andere Dokumente verweisen dorthin, statt sie zu kopieren, soweit
die Seite dadurch benutzbar bleibt:
- **`docs/`** — Produkt- **und** Entwickler-Doku als zweisprachiges HTML (`docs/…` DE, `docs/en/…` EN): Bedienung,
  Installation, Betrieb, Monitoring, FRP, Troubleshooting, Architektur, Komponenten-Grenzen, Datenflüsse,
  Wire-Protokolle und Auth, Plattform-Verhalten; `docs/developer/cicd.html` dazu CI, Release, Signatur und die
  Prüfwerkzeuge (bei Workflow-Änderungen mitziehen; der CI-Job `frp-consistency` prüft die vier `FRP_VERSION`-Pins).
  Im Zweifel über Soll-Verhalten zuerst hier nachschlagen.
- **`README.md`** — Einstieg: Install, Build, Usage, Features, CLI-Flags, Voraussetzungen, Troubleshooting.
- **`DEVELOPMENT.md`** — Dev-Setup (`.devenv.sh`), lokale Workflows und Werkzeuge, neue Abhängigkeiten oder
  Komponenten, Docker-Compose.
- **`CLAUDE.md`, `.claude/`, `tasks/README.md`** — der Ablauf für Sessions und Agenten; `DEVELOPMENT.md` und
  `cicd.html` verweisen darauf, statt ihn zu wiederholen.
- **`CHANGELOG.md`** — Keep a Changelog + SemVer: `## [X.Y.Z] - YYYY-MM-DD` mit Added/Changed/Fixed/Removed; Einträge
  umlautfrei (ae/oe/ue), Gedankenstrich „—". Neues schreibt ein Branch nicht hier hinein, sondern in sein Fragment
  `changelog.d/<slug>.md` (nur `### Added` … `### Security` mit Einträgen, `changelog.d/README.md`): parallele
  Branches ändern so nie dieselbe Datei. Der Release faltet die Fragmente in `## [Unreleased]`.

**Wie:**
- Übersetzt (DE ↔ EN) werden die fertig abgestimmten, geänderten Abschnitte, nicht Zwischenstände.
- Commit-Typ: Doku in der Task trägt den Typ der Code-Änderung; eine Doku-Task `docs:`.
- **Scannen, dann entscheiden:** `grep -rl '<Begriff>' docs README.md DEVELOPMENT.md` statt raten.
- **Nie versionieren** (Repo ist öffentlich): Homelab-Namen und -Adressen, Tokens, ungefixte Sicherheitsfunde, interne
  Roadmaps und Ledger mit Infra-Details — die gehören nach `tasks/private/`.
