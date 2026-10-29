### Fixed

- **Gateway: Healthcheck:** das Gateway hat einen Healthcheck ueber einen Listener nur auf 127.0.0.1 (`/healthz`); `docker compose ps` zeigt `healthy` oder `unhealthy` statt nur `running`.
