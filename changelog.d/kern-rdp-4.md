### Added

- **Desktop: Anzeige und Skalierung im RDP-Tab:** Die Kopfleiste des RDP-Tabs waehlt die Anzeige (*Eingepasst*,
  *Vollbild*, *Mehrfach-Monitor*, *Benutzerdefiniert* mit Zoom 25 bis 200 %, 1:1 und Einpassen) und die Skalierung
  (*Automatisch*, *Normal*, *HiDPI*); die Startwerte kommen aus der Verbindung bzw. den Einstellungen. Der Desktop
  des Servers folgt der Groesse des Tabs ohne Neuverbindung, wo der Server das kann. *Mehrfach-Monitor* verteilt
  den Desktop auf zwei Monitore, den zweiten in einem eigenen Fenster. Der Bild-WebSocket nimmt `size` und
  `layout`, `rdp_session_start` ein optionales `display`. Doku: Desktop-Entwicklerdoku und Admin-Handbuch (DE+EN).
- **Desktop: RDP-Tab abdocken:** Eine verbundene RDP-Sitzung laesst sich wie ein SSH-Tab in ein eigenes Fenster
  abdocken und wieder andocken, ohne neu zu verbinden. Neue Befehle `rdp_session_attach`, `rdp_detach` und
  `rdp_dock`; die Fenster `rdp-*` duerfen nur ihre eigene Sitzung erreichen.

### Changed

- **Desktop: eingebettetes RDP ohne festes 1280x720:** Der Desktop hat nicht mehr fest 1280x720, sondern die
  gewaehlte Groesse. Ein Client, der den Bild-WebSocket schliesst, beendet die Sitzung nicht mehr; ein Fenster
  meldet sich mit `rdp_session_attach` neu an. Der Fork `AdminCave/IronRDP` steht auf Revision `1dc939ea`
  (zusaetzlich ein Groessenwechsel mit der Grafik-Pipeline ohne Neuverbindung).
