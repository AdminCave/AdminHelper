### Fixed

- **Agent: Platten unter FreeBSD:** Ein haengender NFS- oder SMB-Mount haelt den Lauf nicht mehr an. Netz-Mounts
  bekommen 5 s fuer ihre Antwort; wer bis dahin nicht antwortet, fehlt in diesem Lauf.
