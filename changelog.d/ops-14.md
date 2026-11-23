### Security

- **Images per Digest gepinnt:** Der Release-Lauf schreibt die Digests der fuenf eigenen Images (`server`, `gateway`,
  `frps`, `ca-issuer`, `monitoring`) als Datei `IMAGES` ins signierte Runtime-Bundle, nur wenn die cosign-Signatur von
  `docker.yml` fuer diesen Tag darauf passt. `install.sh --ref` und `update.sh` pinnen damit
  `ghcr.io/admincave/adminhelper/<image>:X.Y.Z@sha256:<digest>`; ein spaeter umgehaengter Tag aendert nicht mehr, was
  ein Host zieht. Bundles ohne `IMAGES` pinnen wie bisher den Tag, eine kaputte `IMAGES` bricht vor jeder Aenderung ab.
