### Changed

- **Agent: frpc-Text des Servers nur mit dem TLS-Teil des Servers:** der Agent übernimmt den frpc-Text nur, wenn
  `transport.tls` genau so steht, wie der Server ihn schreibt (`enable = true` und die drei Identitätspfade).
