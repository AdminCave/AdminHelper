### Added

- **Agent: FreeBSD (amd64, FreeBSD 14 und 15):** der Agent laeuft als pkg-Paket `adminhelper-agent` aus einem
  signierten pkg-Repo je ABI, das das Gateway unter `/freebsd/` auf der Repo-Ebene (Port 8445) ausliefert. Der Takt
  kommt aus `/usr/local/etc/cron.d/adminhelper` (alle 5 Minuten, mit `nice` und Zeitdeckel), der FRP-Tunnel ist der
  rc.d-Dienst `adminhelper_frpc` unter daemon(8). Einrichtung: Agent-Verteilung, Abschnitt FreeBSD.
- **Monitoring: FreeBSD-Hosts:** der Agent meldet `os: freebsd`, Sicherheitsupdates aus `pkg audit` gegen die lokale
  Schwachstellen-Datenbank (Pakete und, auf einem RELEASE, das Basissystem; nie mit `-F`), `reboot_required` aus
  `freebsd-version` und Dienste aus `service -e`. Ein Jail zaehlt wie ein Container
  (kein Neustart- und kein Last-Befund), VM-Gaeste werden aus `kern.vm_guest` erkannt. FreeBSD bekommt kein
  Standard-Template.
- **Tests: FreeBSD-Box:** `vm.py import --profile base-freebsd` legt aus FreeBSDs Cloud-Image (gepinnte sha256) eine
  Vorlage im Test-Pool an; `scripts/tests/freebsd_box.sh` faehrt darauf die Agent-Tests, das Paket, das signierte
  Repo, den cron-Eintrag und den rc.d-Tunnel.
