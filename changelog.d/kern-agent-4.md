### Security

- **Agent: Probe-Waechter strenger:** weitere Weiterleiter (etwa nc/netcat, cloudflared, wstunnel, Teleport `tsh`)
  und Super-Server (`tcpserver`, `s6-tcpserver`) ergeben `not_allowed`. Hinter einem von Docker veroeffentlichten
  Port prueft der Agent unter Linux auch den Prozess im Container; ist er nicht ermittelbar (etwa ohne root), wird
  die Probe abgewiesen. Zugangsdaten gehen nur an einen unmittelbar vorher erneut geprueften Listener des Ziels, nie
  an einen von Docker veroeffentlichten Port (Ziel ist dann der Container).
- **Agent: Dateizugriff der Fuehler:** Fuehler lesen nur regulaere Dateien und genau die geprueften (Linux und
  FreeBSD ueber einen Pfad-Deskriptor).
