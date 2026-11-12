### Security

- **Monitoring: Proben auf dem eigenen Host enger gefasst:** der Agent weist einen Port ab, auf dem ein Weiterleiter
  lauscht (Netz rootless laufender Container, kube-proxy, port-forward, ssh, socat), und jede TCP-Probe auf eigene
  Adressen, wenn ein Docker-Daemon laeuft, dessen Container er nicht lesen kann. Einen Unix-Socket prueft er an der
  Datei selbst, nicht nur an ihrem Namen.

### Fixed

- **Monitoring: Meldung zu `not_allowed`:** der Text lautet jetzt „The agent refused the target“ und passt zu jedem
  Grund; den Grund nennt weiter die Fehlermeldung des Agents.
