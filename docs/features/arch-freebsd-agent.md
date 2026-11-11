<!--
SPDX-FileCopyrightText: Kevin Stenzel
SPDX-License-Identifier: GPL-3.0-or-later
-->

# FreeBSD-Agent (`arch-freebsd-agent`, Roadmap R-1247)

## Problem / Motivation

Der Agent läuft heute auf Linux und Windows. Ein FreeBSD-Host (Firewall, Storage, Jail-Host) lässt sich weder
überwachen noch per FRP-Tunnel erreichen, und auf FreeBSD aufsetzende Pakete (OPNsense-Plugin, R-1248) brauchen den
Agenten als Grundlage. `GOOS=freebsd go build ./...` scheitert heute schon am Import: `internal/service` hat für
FreeBSD keine Datei („build constraints exclude all Go files“), ebenso `config`, `enroll` (Lock), `logging` und
`frpc` (Plattformteil).

## Ziel & Nicht-Ziele

**Ziel:** derselbe Agent-Code baut und läuft auf FreeBSD 14 und 15 (amd64), mit den gleichen Kommandos und dem
gleichen Wire-Format wie unter Linux:
- Plattformdateien mit `//go:build freebsd` (wo Linux und FreeBSD gleich sind: `linux || freebsd` in einer
  `_unix.go`-Datei); Parser der FreeBSD-Ausgaben ohne Build-Tag, damit die Linux-CI sie testet.
- Takt: Einmal-Lauf alle 5 Minuten über `/usr/local/etc/cron.d/adminhelper` (cron(8) liest das Verzeichnis), mit
  `nice` und einem Zeitdeckel wie `TimeoutStartSec=270` unter systemd.
- frpc als rc.d-Dienst `adminhelper_frpc` über `daemon -r -P` (nur amd64, weil frp nur dafür ein FreeBSD-Release
  baut).
- Monitoring-Lücken: Virtualisierung über `kern.vm_guest` und `security.jail.jailed`, Dienste über `service -e` und
  `service <name> status`, `system_state` mit `reboot_required` und `security_updates`, nur lokal.
- Paket `adminhelper-agent` per `pkg create`, ein signiertes pkg-Repo je ABI (`FreeBSD:14:amd64`,
  `FreeBSD:15:amd64`) auf der Repo-Ebene :8445 unter `/freebsd/`.
- Eine Test-Vorlage FreeBSD 15.1 im Pool `adminhelper-ci` und ein Box-Test, der die Agent-Tests nativ fährt und das
  Paket installiert.

**Nicht-Ziele (YAGNI):**
- `net.Connections` (gopsutil ruft dafür `lsof`): der Agent nutzt Verbindungen mit PID nirgends. Der Roadmap-Punkt
  „Verbindungen ohne lsof“ betrifft nur die eine Stelle, die einen Port prüft (`frpcOwnsAdminPort`); sie liest
  unter FreeBSD `sockstat`.
- Ein Install-Einzeiler wie `scripts/agent-install.sh` und ein FreeBSD-Weg im Desktop-Dialog „Agent installieren“:
  die Doku nennt die Handgriffe (Repo-Datei, Schlüssel, CA, `pkg install`, `provision`). Ein Einzeiler wäre eine
  eigene Zeile.
- arm64: frp hat kein `freebsd_arm64`-Release.
- Temperaturen: gopsutil liest, was der Host als sysctl hat; nichts Eigenes.
- Ressourcen-Deckel über `nice` hinaus (`rctl`, `idprio`): R-1221 regelt die Deckel für alle Plattformen.
  `idprio` lässt den Lauf auf einem ausgelasteten Host ganz verhungern und hielte dabei Locks (frpc-Sync).
- Eine eigene Standardvorlage `freebsd-base` im Monitoring: der Dienst nimmt `os: freebsd` an, schlägt aber wie
  bei `darwin` keine Vorlage vor.

## Betroffene Komponenten & Dateien

**Agent (`apps/agent`):**
- `internal/config/paths_freebsd.go` (neu): `FrpDir` `/usr/local/etc/adminhelper/frp`, `MonitorDir`
  `/usr/local/etc/adminhelper`, `LogDir` `/var/log/adminhelper`, mit denselben `ADMINHELPER_*_DIR`-Overrides wie
  Linux. Drittsoftware gehört nach hier(7) unter `/usr/local/etc`. frp liegt unterhalb von `adminhelper`, damit ein
  frp aus den Ports (`/usr/local/etc/frp`) unberührt bleibt.
- `internal/config/securedir_linux.go` → `securedir_unix.go` (`linux || freebsd`), `internal/enroll/lock_linux.go`
  → `lock_unix.go`, `internal/logging/eventlog_linux.go` → `eventlog_unix.go`: identisch auf beiden Systemen
  (flock, Dateirechte, kein Ereignisprotokoll).
- `internal/service/service_freebsd.go` (neu) und `cronentry.go` (Zeile ohne Build-Tag, getestet unter Linux):
  `EnableTimer` schreibt die cron.d-Datei, `Install` kopiert das Binary nach `/usr/local/bin/adminhelper-agent`
  und schreibt sie, `Uninstall` entfernt sie.
- `internal/frpc/platform_freebsd.go` (neu): `service adminhelper_frpc …` und `sysrc`, frpc unter
  `/usr/local/libexec/adminhelper/frpc`; `frpcOwnsAdminPort` über `sockstat -4 -l -q -n -P tcp -p <port>`, Parser in
  `sockstat.go` ohne Build-Tag. `platform_linux.go` bleibt.
- `internal/monitor/`: `virt_freebsd.go` (sysctl über `golang.org/x/sys/unix`, kein Prozess), `services_freebsd.go`
  und `rcservice.go` (Parser), `system_freebsd.go` und `pkgaudit.go` (Parser); `system_other.go` wird
  `!linux && !freebsd`; `skipFSTypes` um `devfs`, `fdescfs`, `procfs`, `linprocfs`, `linsysfs`, `nullfs`.
- `cmd/adminhelper-agent/crossbuild_test.go` (neu): `go vet` mit `GOOS=freebsd GOARCH=amd64` über das ganze
  Modul. Er läuft in jedem `go test ./...`, also in der PR-CI (Jobs `agent` und `agent-windows`) und in
  `verify.sh agent`, ohne `ci.yml` und `run.sh` zu ändern.
- `freebsd/adminhelper_frpc` (rc.d-Skript), `build-pkg.sh` (Paket je ABI), `build-repo.sh` (Teilbaum `freebsd/`),
  `Makefile` (`build-freebsd`).

**Monitoring (`apps/monitoring`):** `app/template_suggestions.py` nimmt `freebsd` in `_OSES` auf, ohne
Vorlagen-Vorschlag.

**Gateway (`apps/gateway/nginx.conf`):** die Repo-Ebene :8445 lässt `/freebsd/` zu (heute nur `apt|rpm`). Test in
`apps/server/tests/test_gateway_container.py`.

**Release (`.github/workflows/release.yml`):** baut `pkg` aus den Quellen (`freebsd/pkg`, Tag gepinnt), das Paket
für beide ABIs und das signierte Repo; der Teilbaum geht in den bestehenden Tarball
`adminhelper-agent-repo-<tag>.tar.gz`. `install.sh` und `update.sh` packen den ganzen Tarball nach `./repo` aus und
brauchen keine Änderung.

**Test-Infrastruktur:** `scripts/vm/profiles.json` (Profil `freebsd`), `scripts/vm/bootstrap_freebsd.sh`,
`scripts/tests/freebsd_agent_box.sh` (Box-Test), `scripts/tests/pkg_repo_build_test.sh` (Repo-Bau unter Linux im
Container, wie `repo_build_test.sh`).

## Datenmodell / API / Migrationen

Keine Migration, kein neues Wire-Feld:
- `host.os` ist `freebsd` (`runtime.GOOS`). Bisher verwarf der Monitoring-Dienst unbekannte Werte. Jetzt speichert
  er `freebsd`.
- `host.virtualization` hat dieselbe Form wie unter Linux:
  - `{system: <kern.vm_guest>, role: guest}` in einer VM (`kvm`, `bhyve`, `vmware`, `hv`, `xen`, `vbox`,
    `parallels`, `nvmm`, `generic`; Liste aus `sys/kern/subr_param.c`, releng/15.0)
  - `{system: jail, role: guest}` in einem Jail
  - sonst leere Werte
- Der Block `systemd` behält Schlüssel und Eintragsform (`unit`, `active_state`, `enabled_state`). Windows nutzt
  denselben Schlüssel schon für die SCM-Dienste. Ein Dienst aus `service -e` gilt als `active`, wenn
  `service <name> status` „is running“ meldet, und als `inactive` bei „is not running“. Andere Antworten lässt der
  Agent aus: Viele rc-Skripte (z. B. `netif`, `routing`) kennen kein `status`, das ist kein Befund. `failed` bleibt
  unter FreeBSD leer, rc(8) kennt keinen solchen Zustand. Gemeldet wird also `enabled_inactive`.
- `system_state.reboot_required`: der installierte Kernel (`freebsd-version -k`) ist ein anderer als der laufende
  (`freebsd-version -r`).
- `system_state.security_updates`: die Zahl der verwundbaren Pakete aus `pkg audit -q` plus je eins für einen
  verwundbaren Userland-Stand (`FreeBSD-<freebsd-version -u>`) und Kernel-Stand (`FreeBSD-kernel-<-k>`). Das ist
  derselbe Abgleich wie in den periodic-Skripten `405.pkg-base-audit` und `410.pkg-audit`.
  - Gezählt wird stündlich wie unter Linux, nur gegen die lokale `vuln.xml`, ohne `-F`.
  - Die Datenbank frischt periodic(8) selbst auf: täglich, mit Zufallsversatz (`anticongestion`), sobald sie älter
    als zwei Tage ist (`security_status_pkgaudit_enable` und `_baseaudit_enable` sind standardmäßig `YES`).
  - Der Agent geht deshalb nie selbst ins Netz.
  - Fehlt die Datenbank (periodic lief noch nie), bleibt das Feld weg wie bei einer fehlgeschlagenen Zählung unter
    Linux.
- `pkg upgrade -n -U` (Zahl allgemeiner Paket-Updates) und `freebsd-update updatesready` (bereitliegende
  Basis-Updates): dafür gibt es kein Wire-Feld, auch Linux meldet nur Sicherheitsupdates. Offene Frage 4.

## Externe Integrationen

- pkg: [pkg-create(8)](https://man.freebsd.org/cgi/man.cgi?query=pkg-create&sektion=8),
  [pkg-repo(8)](https://man.freebsd.org/cgi/man.cgi?query=pkg-repo&sektion=8) (Signatur `rsa:`/`ecdsa:` per OpenSSL,
  `eddsa:` nur per `pkg key`), [pkg.conf(5)](https://man.freebsd.org/cgi/man.cgi?query=pkg.conf&sektion=5)
  (`signature_type: pubkey`, `ENV` je Repository für `SSL_CA_CERT_FILE` aus fetch(3), damit die Gateway-CA nur für
  dieses Repo gilt), [pkg-audit(8)](https://man.freebsd.org/cgi/man.cgi?query=pkg-audit&sektion=8); die periodic-Skripte
  unter `scripts/periodic/` in [freebsd/pkg](https://github.com/freebsd/pkg). `pkg` baut laut seinem CI-Workflow
  `build.yaml` auf ubuntu-24.04.
- Basis: [cron(8)](https://man.freebsd.org/cgi/man.cgi?query=cron&sektion=8) (`/usr/local/etc/cron.d`),
  [daemon(8)](https://man.freebsd.org/cgi/man.cgi?query=daemon&sektion=8) (`-r`, `-P`, `-p`),
  [rc.subr(8)](https://man.freebsd.org/cgi/man.cgi?query=rc.subr&sektion=8),
  [freebsd-update(8)](https://man.freebsd.org/cgi/man.cgi?query=freebsd-update&sektion=8),
  [sockstat(1)](https://man.freebsd.org/cgi/man.cgi?query=sockstat&sektion=1),
  [nuageinit(7)](https://man.freebsd.org/cgi/man.cgi?query=nuageinit&sektion=7) (Label `cidata`/`config-2`).
- frp v0.72.0 hat `frp_0.72.0_freebsd_amd64.tar.gz` (GitHub-Release, geprüft 2026-11-09).
- gopsutil v4.26.10: `host.Virtualization` liefert unter FreeBSD `ErrNotImplementedError`.
- VM-Image: `FreeBSD-15.1-RELEASE-amd64-BASIC-CLOUDINIT-{ufs,zfs}.qcow2.xz` unter
  download.freebsd.org/releases/VM-IMAGES/15.1-RELEASE/amd64/Latest/ (14.4 analog).

**Unverifiziert bis zum Box-Test:**
- ob Proxmox' NoCloud-Laufwerk mit nuageinit trägt
- ob `pkg create` unter Linux ein Paket baut, das FreeBSD installiert
- die Antworttexte von `service <name> status` über die Basis-Skripte hinaus

## Trade-offs & Alternativen

1. **Paket- und Repo-Bau im Release.** Optionen:
   - *Empfehlung:* `pkg` aus den Quellen auf dem Ubuntu-Runner, Tag und Commit gepinnt. Der Signierschlüssel
     bleibt auf dem GitHub-Runner wie heute der GPG-Schlüssel.
   - Eine FreeBSD-VM-Action (z. B. vmactions): fremder Code mit Zugriff auf den Schlüssel.
   - Das pkg-Format selbst schreiben (tar plus UCL-Manifest plus Katalog): Nachbau eines fremden Formats.
2. **Signatur:** pkg kann kein OpenPGP. *Empfehlung:* RSA-4096 per OpenSSL. pkg kennt RSA am längsten, und
   `ecdsa:`/`eddsa:` brauchen jüngere pkg-Stände.
3. **Takt:**
   - *Gewählt:* cron.d. Das ist der Weg, den rc(8) und cron(8) für Drittsoftware vorsehen.
   - Ein Dauerprozess über rc.d wäre ein zweiter Lebenszyklus neben dem Einmal-Lauf.
4. **frpc-Pfad:** `/usr/local/libexec/adminhelper/frpc` statt `/usr/local/bin/frpc`. Das Port-Paket `net/frp`
   liefert `/usr/local/bin/frpc`, und pkg verweigert die Installation bei Dateikonflikten.
5. **Cross-Build-Wächter als Go-Test statt als CI-Schritt:**
   - Er läuft überall, wo `go test` läuft, auch in jedem `Verify:` dieses Vorhabens.
   - Ein Schritt in `ci.yml` und `run.sh` wäre ein Workflow- bzw. Harness-Pfad.
   - Kosten: einige Sekunden je Lauf (Build-Cache).

## Risiken & Rollback

- Die Umbenennungen `_linux.go` → `_unix.go` ändern Build-Tags von Linux-Dateien. Die Linux-Suite und der
  Cross-Build für Linux und Windows sichern sie ab.
- frpc auf FreeBSD ist Risikopfad (Tunnel). `security` prüft die Task, der Box-Test startet den Dienst echt.
- Repo-Ebene: eine weitere Location auf :8445, certless wie `apt|rpm`. Die Echtheit trägt die pkg-Signatur, TLS
  pinnt die Gateway-CA per Repo-`ENV`. Fehlt der Teilbaum, antwortet nginx mit 404.
- Release: ein fehlendes oder falsches Signier-Secret bricht den Release-Lauf ab (fail-closed, wie beim GPG-Schlüssel
  über `EXPECTED_FPR`).
- Rollback: Revert des Merge-Commits. FreeBSD-Hosts behalten das installierte Paket; ohne Teilbaum `freebsd/` finden
  sie nur keine Updates mehr.

## Doku-Impact

- `docs/admin/agent.html` und `docs/en/admin/agent.html` (oder die Seite, die heute die Agent-Installation führt):
  Abschnitt FreeBSD mit Repo-Datei, Schlüssel, CA, `pkg install`, `provision`, Pfaden, Dienst `adminhelper_frpc`.
- Die Monitoring-Seite DE+EN: FreeBSD-Spezifika (`security_updates`, `reboot_required`, Dienste).
- `docs/developer/cicd.html` DE+EN: pkg-Repo-Bau und Signatur im Release.
- `DEVELOPMENT.md`: `make build-freebsd`, die Vorlage, der Box-Test.
- `changelog.d/arch-freebsd-agent.md`.

## Offene Fragen

1. **Basis-Vorlage FreeBSD 15.1:** Das Token sieht nur einen lvmthin-Storage (Inhalt `images,rootdir`) und hat dort
   kein `Datastore.AllocateTemplate`. Ein qcow2 importieren kann es also nicht.
   - *Empfehlung:* Kevin gibt dem Token `Datastore.AllocateTemplate` auf einem Datei-Storage mit Inhalt `import`.
     Dann lädt und importiert `vm.py` die Images selbst: 15.1 jetzt, 14.4 und OPNsense (R-1248) später.
   - Alternative: Kevin importiert von Hand; die Befehle liefert das Gate.
2. **Signierschlüssel des pkg-Repos:** neues Secret.
   - *Empfehlung:* RSA-4096 per `openssl genrsa`, Secret `PKG_REPO_SIGNING_KEY` (PEM).
   - Der Public Key wird als `apps/agent/freebsd/adminhelper-pkg.pub` versioniert und im Release gegen den Schlüssel
     geprüft, wie `EXPECTED_FPR`.
3. **Merge-Weg:** `release.yml` macht den PR zu einem Kevin-Merge.
   - *Empfehlung:* ein PR, Kevin merged nach grüner CI und grünem Box-Test.
   - Alternative: den Release-Teil als eigene Zeile abspalten.
4. **Updates über die Sicherheitszahl hinaus:** `pkg upgrade -n -U` und `freebsd-update updatesready` bräuchten
   neue Wire-Felder in Monitoring und Desktop.
   - *Empfehlung:* jetzt weglassen und mit R-1225/R-1227 („Updates und Neustarts“) für alle Plattformen einführen.

**Antworten (Kevin 2026-11-11):** 1 wie empfohlen, das Token-Recht setzt Kevin und `vm.py` importiert selbst (T8).
2 wie empfohlen; den Schlüssel erzeugt Kevin auf seinem eigenen Rechner. 3 die Alternative: Den Agent-Code merged
die Session nach grünem Box-Lauf (T9), CI und Release (T10) ziehen in die eigene Zeile R-1303 (Zug `ci-10`, Merge
durch Kevin), beide vor 0.47.0. 4 bleibt bei der Empfehlung.
