### Security

- **Test-Boxen: Downloads gepinnt und in eigenem Verzeichnis:** `scripts/vm/bootstrap_linux.sh` legt seine Downloads in ein eigenes `mktemp -d` statt unter feste Namen in `/tmp`, prueft die Apt-Schluessel von Docker und nodesource per Fingerprint, laedt rustup-init in fester Version mit SHA-256 und fuehrt kein heruntergeladenes Skript mehr aus.
