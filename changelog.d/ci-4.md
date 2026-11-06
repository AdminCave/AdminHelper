### Changed

- **Images mit cosign 3 signiert:** die Signatur der Container-Images liegt als Sigstore-Bundle in einem
  OCI-1.1-Referrer; pruefen mit cosign 3 (oder ab 2.6 mit `--new-bundle-format`). cosign 3 prueft auch die
  aelteren Images bis 0.46.0.
