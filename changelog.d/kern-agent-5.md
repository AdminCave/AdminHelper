### Changed

- **Agent: Ansichten mit Dateien aus einem Container:** die Ansichten, die Dateien unter der Wurzel eines Containers
  lesen (etwa Mailcow-Queues, WordPress, Nextcloud AIO), lesen nur noch Container von Docker und Podman, die root mit den
  ueblichen cgroups startet; rootless Container, ein eigenes `--cgroup-parent`, Kubernetes-Pods und Container in
  einem LXC-Gast (vom Host aus) melden dort einen Fehler.
- **Agent: Waechter fuer Proben am eigenen Host:** weitere Weiterleiter und Tunnel-Programme sowie Super-Server an
  Unix-Sockets gelten als nicht pruefbar (`not_allowed`).

### Fixed

- **Agent: vHost-Checks bei Weiterleitung auf den eigenen Namen:** eine Seite, die auf ihren eigenen Domainnamen
  weiterleitet (etwa Moodle mit `forcelogin` zum Login), blieb `unknown`; der Agent folgt jetzt einer Weiterleitung auf
  denselben Namen bei gleichem Schema und Port, an dieselbe Adresse. Jede andere Weiterleitung bleibt abgewiesen.
- **Agent: HTTP-Checks im Modus `auto` mit kurzem Timeout:** ein Dienst ohne TLS, der auf einen TLS-Gruss schweigt,
  wurde bei 1 s Timeout nicht erkannt; die TLS-Erkennung wartet jetzt hoechstens die Haelfte der verbleibenden Zeit.
- **Agent: Antwortgrenze bei Checks mit JSON-Feldern:** die Grenze von 1 MiB gilt dort jetzt auch im Leser selbst.
