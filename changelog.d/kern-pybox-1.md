### Changed

- **Test-Boxen:** `scripts/vm/bootstrap_linux.sh` installiert `python3.14` aus einem per Release und SHA-256
  gepinnten python-build-standalone-Archiv statt aus dem deadsnakes-PPA; ein Ausfall des PPA bricht keine Box mehr ab.
