### Changed

- **Agent: frpc-Text des Servers nur mit dem TLS-Teil des Servers:** der Agent uebernimmt den frpc-Text nur, wenn
  `transport.tls` genau so steht, wie der Server ihn schreibt (`enable = true` und die drei Identitaetspfade).
