// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package service

import (
	"fmt"
	"os"
	"path/filepath"
)

// agentBinary is where Install puts the agent: root-owned and without spaces, as on Linux.
const agentBinary = "/usr/local/bin/adminhelper-agent"

// cronFile is the agent's schedule. cron(8) checks /usr/local/etc/cron.d every minute and
// rereads a new or changed file without a restart; it skips names that start with a dot. A var
// only so tests can point it elsewhere.
var cronFile = "/usr/local/etc/cron.d/adminhelper"

// EnableTimer writes the cron file that runs the agent every five minutes; FreeBSD's
// counterpart of enabling the systemd timer. Only the setup calls it (provision, monitor init,
// service install), never a run (R-0641). The file is staged under a dot name, which cron
// ignores, and renamed into place, so cron never reads half a file.
func EnableTimer() error {
	dir := filepath.Dir(cronFile)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return fmt.Errorf("create %s: %w", dir, err)
	}
	tmp := filepath.Join(dir, "."+filepath.Base(cronFile)+".tmp")
	if err := os.WriteFile(tmp, []byte(cronTable(agentBinary)), 0o644); err != nil {
		return fmt.Errorf("write %s: %w", tmp, err)
	}
	// WriteFile applies the umask and keeps the mode of a stale staged file; the cron file is
	// root's to write and everyone's to read, whatever those were.
	if err := os.Chmod(tmp, 0o644); err != nil {
		_ = os.Remove(tmp)
		return fmt.Errorf("chmod %s: %w", tmp, err)
	}
	if err := os.Rename(tmp, cronFile); err != nil {
		_ = os.Remove(tmp)
		return fmt.Errorf("install %s: %w", cronFile, err)
	}
	return nil
}

// Install copies the agent to /usr/local/bin and schedules it with cron. Copying first keeps
// the root cron job off a path a non-root user can write (3.12, as on Linux).
func Install() error {
	exePath, err := os.Executable()
	if err != nil {
		return fmt.Errorf("find own path: %w", err)
	}
	if exePath != agentBinary {
		data, err := os.ReadFile(exePath)
		if err != nil {
			return fmt.Errorf("read the binary: %w", err)
		}
		if err := os.WriteFile(agentBinary, data, 0o755); err != nil {
			return fmt.Errorf("copy the binary to %s: %w", agentBinary, err)
		}
	}
	if err := EnableTimer(); err != nil {
		return fmt.Errorf("schedule the agent: %w", err)
	}
	fmt.Printf("Service installed: %s runs every five minutes\n", cronFile)
	return nil
}

// Uninstall removes the cron file; cron drops the job within a minute. A missing file is fine.
func Uninstall() error {
	if err := os.Remove(cronFile); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("remove %s: %w", cronFile, err)
	}
	fmt.Println("Service uninstalled.")
	return nil
}
