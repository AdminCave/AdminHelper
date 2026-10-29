### Fixed

- **FRP: Tunnel-Altzeilen in der Config:** Ein Tunnel, dessen gespeicherte Felder die API heute ablehnen wuerde,
  fehlt in der erzeugten frpc- und Visitor-Config; der Server loggt seinen Namen als Warnung.
- **FRP: Config-Routen wie der Generator:** Die Routen fuer frpc-Config, Visitor-Config und den ZIP-Export lassen
  dieselben Tunnel aus wie die erzeugte Config; ein Host ohne nutzbaren Tunnel bekommt 404 statt einer Config ohne
  Tunnel, und der ZIP-Export enthaelt fuer ihn keine frpc.toml.
