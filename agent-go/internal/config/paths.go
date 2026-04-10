package config

// Plattform-spezifische Pfade werden in paths_linux.go und paths_windows.go definiert.
// Jede Datei exportiert:
//   FrpDir()     — Basisverzeichnis fuer frpc-Konfiguration
//   MonitorDir() — Basisverzeichnis fuer Monitor-Konfiguration

import "path/filepath"

// Abgeleitete Pfade (plattform-unabhaengig)

func FrpConfigFile() string  { return filepath.Join(FrpDir(), "frpc.toml") }
func FrpSrmConf() string     { return filepath.Join(FrpDir(), "adminhelper.conf") }
func FrpHashFile() string    { return filepath.Join(FrpDir(), ".config-hash") }
func FrpPkiDir() string      { return filepath.Join(FrpDir(), "pki") }
func FrpCACert() string      { return filepath.Join(FrpDir(), "ca.crt") }
func MonitorConfFile() string { return filepath.Join(MonitorDir(), "monitor.conf") }
