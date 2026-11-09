### Added

- **Desktop: H.264 im eingebetteten RDP unter Linux:** Der eingebettete RDP-Client dekodiert H.264 unter Linux
  mit Ciscos OpenH264. Die erste Sitzung laedt Ciscos Binary 2.6.0 ueber HTTPS, prueft die gepinnte SHA-256 und
  legt es im Datenverzeichnis der App ab; scheitert der Download binnen 15 s, laeuft die Sitzung ohne H.264. Der
  Schalter *H.264 (OpenH264)* unter *Einstellungen -> RDP* (Standard an) zeigt Ciscos Hinweis und Lizenztext;
  aus loescht die Bibliothek (neuer Befehl `openh264_remove`). Doku: Desktop-Entwicklerdoku und Admin-Handbuch
  (DE+EN).
