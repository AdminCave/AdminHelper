# Agent-Installation: apt-CA lesbar für apt, smartmontools nur auf Blech (ops-8)

Roadmap: R-0810, R-1541 (Kevin 2026-11-18 Triage, Zug ops-8). Kevin 2026-11-18: die Session merged den PR dieses
Zugs selbst, bei grüner CI, `security` approve und grünem scenario-Lauf auf VM (Installer-PR); danach Meldung an
Kevin.

## Problem / Motivation
- **R-0810:** `scripts/agent-install.sh:388` pinnt apt nach dem Enrollment per
  `Acquire::https::<host>::CAInfo` auf `/etc/adminhelper/identity/ca.crt`. Das Paket setzt `/etc/adminhelper` auf
  0700 (`apps/agent/deb/DEBIAN/postinst:9`), apt lädt die CA aber als Benutzer `_apt`: `apt update` auf der
  AdminHelper-Quelle scheitert nach dem CA-Flip immer, betroffene Hosts bekommen keine Agent-Updates mehr. dnf läuft
  als root und ist nicht betroffen. Der Capstone (`scripts/tests/box_agentbox.sh:159`) greppt nur die Konf-Zeile und
  fährt nie `apt-get update`. Repro aus der Zeile: debian:13-slim und bookworm-slim, CA unter 0700 rc=100, 0644-Kopie
  unter `/etc/apt` rc=0.
- **R-1541:** Das Agent-Paket empfiehlt `smartmontools` (`apps/agent/deb/DEBIAN/control:6`,
  `apps/agent/rpm/adminhelper-agent.spec:18`); apt und dnf installieren Recommends standardmäßig, also landet es auch
  in VMs und LXC-Containern, wo es keine SMART-Platten gibt und `smartd` ins Leere läuft.

## Ziel & Nicht-Ziele
Ziel:
- apt liest die gepinnte CA aus einer öffentlichen Kopie (0644) `/etc/apt/adminhelper-ca.crt`; der Agent hält die
  Kopie aktuell, wenn er seine Identität neu speichert (Erneuerung, Wechsel der Trust-Generation).
- Der Capstone beweist den Flip mit einem echten `apt-get update`.
- Das Paket schlägt `smartmontools` nur noch vor (`Suggests`); `agent-install.sh` installiert es nur auf Blech
  (`systemd-detect-virt` meldet `none`).
- Doku: Bestandshosts reparieren (Kopie anlegen, Konf umstellen; smartmontools in VMs entfernen).

Nicht-Ziele:
- Keine Heilung kaputter Bestandshosts durch das Paket: ein Host mit kaputtem `apt update` bekommt das neue Paket
  gar nicht erst; die Doku nennt die zwei Befehle (ein erneuter Lauf von `agent-install.sh` pinnt nur mit
  `--server-id` und neuem Token, Fund der Abschlussprüfung).
- Die Berechtigung von `/etc/adminhelper` bleibt 0700 (Schlüssel und Token liegen darunter).
- „SMART-Check auf virtuellen Hosts nicht vorschlagen“ (Teil von R-1541) fährt nicht mit: der Check steckt in der
  Standardvorlage `linux-base` (`apps/monitoring/app/builtin_templates.py`, versionierte Vorlagen-Hashes) und gehört
  zur Monitoring-Neuordnung (Abdeckung). Auf einer VM bleibt der Check heute schon `ok` mit Grund
  (`not_installed`). Eigene Roadmap-Zeile, am Gate gemeldet.

## Betroffene Komponenten & Dateien
- Agent: `apps/agent/internal/enroll/enroll.go` (`Store`, `:147`) und Test; `apps/agent/deb/DEBIAN/control`,
  `apps/agent/rpm/adminhelper-agent.spec`, `apps/agent/cmd/adminhelper-agent/packaging_test.go`.
- Skripte: `scripts/agent-install.sh` (CA-Flip ab `:383`, Paketinstallation), `scripts/tests/agent_install_test.sh`,
  `scripts/tests/box_agentbox.sh`, `scripts/tests/multibox.sh` (Marker), `scripts/tests/multibox_test.sh` (Fake).
- Doku: `docs/admin/agent-deployment.html`, `docs/en/admin/agent-deployment.html` (manuelle Variante A,
  Bestandshosts), `docs/admin/monitoring.html`, `docs/en/admin/monitoring.html` (Satz zu `Recommends`),
  `changelog.d/ops-8.md`.

## Datenmodell / API / Migrationen
Keine. Neue Datei auf dem Host: `/etc/apt/adminhelper-ca.crt` (0644, root), Inhalt gleich
`/etc/adminhelper/identity/ca.crt`.

## Externe Integrationen
apt: `Acquire::https::<host>::CAInfo` (apt.conf(5), apt-transport-https); apt lädt Dateien als `_apt` (Sandbox-User,
seit apt 1.1). Belegt durch den Repro der Zeile, nicht neu nachgelesen.
rpm/dnf: `Suggests` ist ein schwaches Rückwärts-Tag, dnf installiert es nicht (`install_weak_deps` gilt nur für
Recommends) — vor T2 in der Doku von rpm/dnf nachlesen.

## Trade-offs & Alternativen
- **Ort der Kopie:** `/etc/apt/adminhelper-ca.crt` (Empfehlung: Repro der Zeile, liegt bei der apt-Konfiguration,
  die sie nutzt) statt Kevins Workaround `/usr/local/share/adminhelper/repo-ca.crt` (`/usr/local` gehört dem Admin,
  nicht einem Installer). Hosts mit dem Workaround stellen die zwei Befehle der Doku auf den neuen Pfad um; die
  alte Kopie bleibt liegen (Doku).
- **Agent pflegt die Kopie nur, wenn sie existiert:** so bleibt er auf dnf- und Nicht-apt-Hosts unbeteiligt; der
  Installer legt sie an. Ein Fehler beim Nachziehen kostet die Erneuerung nicht (nur Warnung).
- **Alternative 0711 auf `/etc/adminhelper`:** verworfen, weitere Dateien darunter würden für `_apt` erreichbar.

## Risiken & Rollback
- Eine veraltete Kopie nach einem Trust-Wechsel bräche `apt update` wieder: deshalb zieht `Store` sie nach (Test).
- Bestehende Bare-Metal-Hosts verlieren nichts (smartmontools bleibt installiert, APT behält Suggests beim
  autoremove).
- Rollback: Revert des PRs; Hosts behalten die Kopie, die Konf zeigt darauf und bleibt gültig.

## Doku-Impact
`agent-deployment.html` DE+EN (Variante A auf die Kopie, Absatz „Bestandshosts“), `monitoring.html` DE+EN
(Suggests, Installer nur auf Blech), `changelog.d/ops-8.md`.

## Offene Fragen
Keine aus Kevins Bereich. Gemeldet am Gate: der abgespaltene Teil „SMART nicht vorschlagen“ als neue Zeile.
