### Fixed

- **Gateway: Healthcheck ueber /healthz auf 127.0.0.1:** Das Gateway hat einen Healthcheck ueber einen Listener nur auf
  127.0.0.1 (`/healthz`); `docker compose ps` zeigt `healthy` oder `unhealthy` statt nur `running`.
- **Compose: Healthchecks fuer victoria und monitoring ueber HTTP:** victoria hat einen Healthcheck auf `/health`;
  monitoring fragt `/health` per HTTP statt nur einen TCP-Connect zu pruefen, ein haengender Prozess wird so
  `unhealthy`.
