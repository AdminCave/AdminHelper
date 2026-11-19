### Added

- **Agent-Installation FreeBSD und OPNsense mit einem Befehl:** `scripts/agent-install-bsd.sh` (POSIX sh) richtet
  das signierte pkg-Repo mit dem mitgelieferten Schluessel ein, installiert `adminhelper-agent` (auf OPNsense das
  Plugin `os-adminhelper`), registriert den Agent mit verdeckt abgefragtem Token und `--ca-fp` und stellt danach die
  TLS-Pruefung des Repos auf die interne CA um. Ohne `--server-id` installiert oder aktualisiert es nur. Doku
  Agent-Rollout, Abschnitte FreeBSD und OPNsense.
