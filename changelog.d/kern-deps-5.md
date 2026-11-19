### Changed

- **Abhaengigkeiten und Basis-Images aktualisiert:** Desktop-Crates im semver-Rahmen (u. a. Tauri 2.12.6), Go 1.27.4
  fuer Agent und frps-Image samt Go-Modulen des Agents, neue Digests fuer `python:3.14-slim`, `nginx:1.30.6-alpine`,
  `postgres:18-alpine` und `node:26-alpine`, VictoriaMetrics v1.156.0; die eigenen Images spielen beim Bau die
  Paket-Updates der Distribution ein.
- **Container wechseln per `setpriv` auf den Dienst-Nutzer:** server, scheduler, monitoring und ca-issuer nutzen statt
  `gosu` das `setpriv` aus util-linux; `HOME` ist dabei `/app`.

### Removed

- **`pip` und `gosu` aus den Runtime-Images:** `pip` wird nach der Installation der Anforderungen im selben Schritt
  deinstalliert (das von Python mitgelieferte `ensurepip`-Wheel bleibt im Image), `gosu` wird nicht mehr installiert.
