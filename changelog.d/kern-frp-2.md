### Fixed

- **FRP: Namen in der erzeugten Config geprueft:** Server- und Nutzernamen mit Zeichen, die die API ablehnt,
  schreibt der Generator nicht in frpc- und Visitor-Config; die Routen antworten dafuer 404, der ZIP-Export
  ueberspringt sie.
- **FRP: frpc-Config fuer Admins wie beim Agent:** Die Admin-Route fuer die frpc.toml eines Servers liefert
  denselben Text wie der Abgleich des Agents, auch bei Tunneln in mehreren FRP-Configs.
- **FRP: Warnungen zu ausgelassenen Tunneln einmal:** Der Server warnt je Tunnel und Grund einmal statt bei jedem
  Abgleich und gibt Namen maskiert aus.
