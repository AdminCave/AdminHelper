### Security

- **FRP-Tunnel: der Desktop prueft das frps-Zertifikat strenger:** wie der Agent verlangt auch der frpc des
  Desktop-Visitors den festen Namen `frps.adminhelper.invalid` (`transport.tls.serverName`), den nur das
  frps-Zertifikat traegt. Der Server liefert den Namen im Visitor-Bundle mit (`frps_tls_name`); gegen einen aelteren
  Server ohne das Feld verbindet der Desktop wie bisher.
