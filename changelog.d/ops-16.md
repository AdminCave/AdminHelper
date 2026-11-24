### Fixed

- **Agent-Installation: Repo-Konfiguration:** `agent-install.sh` schreibt die TLS-Einstellung des Paket-Repos
  bei jedem Lauf nach dem Stand des Hosts; ein erneuter Lauf auf einem schon eingebundenen Host behaelt die
  Bindung an die interne CA.
- **Update: neue .env-Schluessel:** `update.sh` ergaenzt ein fehlendes Zeilenende der `.env`, bevor es neue
  Schluessel anhaengt; bisher klebte der erste neue Schluessel an der letzten Zeile.
- **Installation: Neustart nach Abbruch:** `install.sh` behaelt die Version des Release-Bundles, bis die
  Installation gelungen ist; ein Neustart aus dem Verzeichnis nach einem abgebrochenen Versuch installiert damit
  dieselbe gepinnte Version statt `:latest`.
- **Restore ueber einem neueren Schema:** `restore.sh` leert jede Datenbank als ihre Dienst-Rolle, bevor es den
  Dump einspielt; ein Restore nach einem gescheiterten Update scheitert nicht mehr an Tabellen der neueren Version
  und laesst keine zurueck.
- **Secrets: Aufraeumen bei Abbruch:** `init-secrets.sh` entfernt seine Arbeitskopie neben der `.env` auch dann,
  wenn der Lauf durch ein Signal endet, wie `install.sh` und `update.sh`.

### Changed

- **Update: Platz in backups/:** `update.sh` behaelt von den Laufzeit-Snapshots `runtime-prev-*` die drei
  neuesten und nennt am Ende, wie viel Platz `backups/` belegt.
- **Taegliche DB-Sicherung als Profil:** Der Dienst `pg-backup` ist jetzt Teil der `docker-compose.yml` und laeuft
  nur mit `COMPOSE_PROFILES=backup` in der `.env`; Updates lassen die Einstellung stehen. Bisher musste man einen
  auskommentierten Block einkommentieren, den jedes Update wieder ueberschrieb.
- **Runtime-Bundle: pg-restore.sh:** Das Release-Bundle liefert `scripts/pg-restore.sh` mit, auf das die
  Betriebs-Doku verweist; `install.sh` legt `backups/` beim Installieren nur fuer den Besitzer lesbar an.
