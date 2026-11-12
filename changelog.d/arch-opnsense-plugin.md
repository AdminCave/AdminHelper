### Added

- **Agent: OPNsense-Plugin `os-adminhelper` (OPNsense 26.1 und 26.7, amd64):** kommt aus demselben signierten
  pkg-Repo des Servers wie der FreeBSD-Agent und zieht ihn als Abhaengigkeit nach. Die Seite Services → AdminHelper
  schaltet Takt und Tunnel an und aus und zeigt Registrierung, Server, Agent-Version, Takt, Tunnel-Client und den
  letzten Monitoring-Lauf; den Tunnel fuehrt OPNsense als Dienst `adminhelper_frpc`, und die Repo-Datei haelt das
  Plugin auf den Server des Agents gerichtet. Registriert wird nur in der Shell (`provision --token-stdin`), kein
  Token steht in `config.xml`. Das Repo ist ein Fremd-Repo, von OPNsense nicht unterstuetzt. Einrichtung:
  Agent-Verteilung, Abschnitt OPNsense.
- **Monitoring: Modul OPNsense:** liest ueber lesende configd-Aktionen, ohne API-Key, Dienste, Gateways,
  Firmware-Stand, Zustandstabelle und CARP der Firewall — gestoppte Dienste und ausgefallene Gateways sind kritisch,
  eine Zustandstabelle ab 80 % Warnung und ab 95 % kritisch, CARP-Adressen im Zustand INIT kritisch. Ein verfuegbares
  Update und der CARP-Wartungsmodus bewerten nichts, die Karte zeigt sie.
- **Monitoring: Probes auf FreeBSD:** Units sind dort rc.d-Dienste (`service <name> onestatus`), Unix-Sockets prueft
  der Agent wie unter Linux an Pfad und Gegenprozess, und die Erkennung findet Marker-Pfade auch unter FreeBSD.
- **Tests: OPNsense-Box:** `vm.py bake --profile base-opnsense` macht aus der FreeBSD-Vorlage eine Vorlage mit
  OPNsense 26.7; `scripts/tests/opnsense_box.sh` prueft darauf Plugin und Agent gegen das echte `configctl`.
