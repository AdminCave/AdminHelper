### Security

- **Desktop: Ansible-Laeufe mit `--ask-pass` ueber Sprung-Hosts:** Jeder Sprung-Host meldet sich nur ohne Passwort
  an (Key oder Agent), auch ein `ProxyJump` aus `~/.ssh/config`; jeder Hop laeuft als eigenes `ProxyCommand`. Laesst
  sich die Sprung-Kette nicht ermitteln, startet der Lauf nicht und nennt den Server.
