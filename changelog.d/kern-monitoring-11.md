### Added

- **Monitoring: Mail-, Verzeichnis- und Schuldienste:** neue Katalog-Module pruefen Postfix (Begruessung, Queues,
  Alter der aeltesten Mail), Dovecot, Mailcow (Container, Queue, Watchdog ueber das lokale Redis, ohne API-Key),
  MailPiler, ClamAV (Alter der Signaturen), Rspamd, SpamAssassin und OpenDKIM, dazu Samba als Domaenencontroller
  (Replikation, FSMO-Rollen, LDAPS-Zertifikat) und als Dateiserver oder Domaenenmitglied (smb.conf, winbind,
  Vertrauenskonto) und linuxmuster.net 7.x (ausstehender Geraete-Import, veraltete LINBO-Torrents, Zertifikat des
  Servers). Der Agent liest nur Dateien und feste Lesekommandos des eigenen Hosts; Passwoerter aus `mailcow.conf`
  und `piler.conf` verlassen den Host nicht, zum Server gehen nur Zahlen, Alter und Zustaende, keine Adressen,
  Domains, Nutzer- oder Freigabenamen. Nicht an laufenden Diensten geprueft; edulution folgt spaeter. Doku:
  Monitoring, Abschnitt App-Module; Agent (DE+EN).
