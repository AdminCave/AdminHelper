//go:build windows

package config

import (
	"os"
	"path/filepath"
)

func FrpDir() string {
	return filepath.Join(os.Getenv("ProgramData"), "SRM", "frp")
}

func MonitorDir() string {
	return filepath.Join(os.Getenv("ProgramData"), "SRM")
}
