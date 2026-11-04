### Security

- **FRP-Tunnel: der Agent prueft das frps-Zertifikat strenger:** frpc verlangt den festen Namen
  `frps.adminhelper.invalid` (`transport.tls.serverName`), den nur das frps-Zertifikat traegt. Der ca-issuer stellt
  das frps-Zertifikat beim ersten Start einmal neu aus.
