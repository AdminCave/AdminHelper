### Fixed

- **Compose:** The healthchecks of `monitoring` and `ca-issuer` no longer go through an HTTP proxy from the
  environment, like the server's check; without a reachable proxy they stayed unhealthy.
- **Logging:** `LOG_LEVEL` accepts only `DEBUG`, `INFO`, `WARNING`, `ERROR` and `CRITICAL`, as documented. A name
  such as `TRACE`, and the aliases `WARN` and `FATAL`, now stop the server and monitoring from starting.
- **Hooks:** Two failures of the same hook at once give one bell notice, not two. When a hook run breaks off with an
  exception in the server, the notice names only the exception type; the details stay in the server log. The
  desktop lists the category `hooks` with its label.
- **Monitoring:** The tag sync no longer waits for the hub while it sends the all-clears of a deleted server.
