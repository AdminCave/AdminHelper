### Changed

- **CI: Downloads mit Wiederholung:** apt-Pakete, Playwright-Browser und die Release-Downloads per curl werden bei
  einem Haenger oder 5xx wiederholt, statt den Job rot zu machen; die Playwright-Browser und die .deb-Archive der
  Tauri-Systempakete liegen in einem Cache.
- **CI: eingebettetes RDP je Pull Request:** der neue Job `rdp-embedded` faehrt die xrdp-Suite
  (`desktop_e2e_rdp_embedded.sh`) auf jedem Pull Request, nicht mehr nur im woechentlichen Lauf.
