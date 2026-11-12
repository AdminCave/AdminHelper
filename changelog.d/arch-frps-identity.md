### Changed

- **frps nimmt nur noch die Proxies an, die der Server je Host erzeugt:** jede frpc.toml traegt einen Schluessel je
  Host (`metadatas.ahProxyKey`), und ein Plugin im frps-Image (`frps-policy`) vergleicht jede neue Proxy-Anmeldung mit
  der Konfiguration, die der Server fuer diesen Host erzeugt hat (Name, Typ, Domains, Gruppe); alles andere lehnt frps
  ab, und ohne Policy-Datei oder ohne laufendes Plugin nimmt frps gar keinen Proxy an. Mit dem Update gibt es keine
  Uebergangszeit: Tunnel kommen zurueck, sobald der Agent seine neue frpc.toml holt (sein naechster Lauf, rund 5 min).
  Eine von Hand verteilte frpc.toml muss neu geholt und neu verteilt werden (Betrieb und FRP-Tunnel in der Doku), ebenso
  nach einem Wechsel von `SECRET_KEY`. Das frps-Image baut jetzt aus dem Repo-Root als Kontext.
