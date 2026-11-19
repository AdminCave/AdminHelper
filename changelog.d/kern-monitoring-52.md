### Fixed

- **Monitoring, „Mehr Log“ unter OPNsense:** Der Tab liest jetzt auch das Systemlog von OPNsense
  (`/var/log/system/system_*.log`) statt nur `/var/log/messages`, das OPNsense nicht schreibt; vorher blieb er dort leer.
