### Changed

- **CI: Downloads mit Wiederholung:** apt-Pakete, Playwright-Browser (jetzt mit Cache) und die Release-Downloads per
  curl werden bei einem Haenger oder 5xx wiederholt, statt den Job rot zu machen.
- **CI: eingebettetes RDP je Pull Request:** der neue Job `rdp-embedded` faehrt die xrdp-Suite
  (`desktop_e2e_rdp_embedded.sh`) auf jedem Pull Request, nicht mehr nur im woechentlichen Lauf.
