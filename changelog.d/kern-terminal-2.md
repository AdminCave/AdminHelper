### Added

- **Desktop: Snippets im SSH-Terminal:** Das Panel *Snippets* neben einer SSH-Sitzung tippt gespeicherte Befehle
  per Klick in die Sitzung; die Liste gilt je Workspace und startet mit einer Standardliste. *An alle
  SSH-Sitzungen senden* schickt ein Snippet an jede laufende SSH-Sitzung des Workspace, der Fuss jeder Sitzung
  zeigt dann *Broadcast aktiv*.
- **Desktop: Dateien (SFTP) im SSH-Terminal:** Das Panel *Dateien* zeigt die Ordner des Hosts, laedt Dateien per
  Klick herunter und per Dialog oder Ziehen aufs Fenster hoch und legt Ordner an; eine vorhandene Datei wird erst
  nach einer Rueckfrage ersetzt. Unter Linux und macOS laeuft SFTP ueber die Verbindung der Sitzung, unter Windows
  braucht es einen SSH-Schluessel oder den SSH-Agent.
