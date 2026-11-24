### Fixed

- **Agent-Installation: Repo-Konfiguration:** `agent-install.sh` schreibt die TLS-Einstellung des Paket-Repos
  bei jedem Lauf nach dem Stand des Hosts; ein erneuter Lauf auf einem schon eingebundenen Host behaelt die
  Bindung an die interne CA.
- **Update: neue .env-Schluessel:** `update.sh` ergaenzt ein fehlendes Zeilenende der `.env`, bevor es neue
  Schluessel anhaengt; bisher klebte der erste neue Schluessel an der letzten Zeile.
- **Installation: Neustart nach Abbruch:** `install.sh` behaelt die Version des Release-Bundles, bis die
  Installation gelungen ist; ein Neustart aus dem Verzeichnis nach einem abgebrochenen Versuch installiert damit
  dieselbe gepinnte Version statt `:latest`.

### Changed

- **Update: Platz in backups/:** `update.sh` behaelt von den Laufzeit-Snapshots `runtime-prev-*` die drei
  neuesten und nennt am Ende, wie viel Platz `backups/` belegt.
