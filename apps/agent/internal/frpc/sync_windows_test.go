// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package frpc

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"adminhelper-agent/internal/config"
)

// Sync changes nothing when the data root cannot be secured: the open root holds a child
// of another account that is held open, so that it cannot be removed. frp and the sync
// config exist, so a sync that went on would write admin.conf with the admin API's
// password and frpc.toml with the frps token there.
func TestSyncFailsWhenTheDataRootCannotBeSecured(t *testing.T) {
	srv, _ := hashServer(t, `{"hash":"`+hashConfig(tunnelToml)+`"}`, tunnelToml)
	calls := setupSyncTest(t, srv.URL)
	root := t.TempDir()
	frpDir := filepath.Join(root, "frp")
	if err := os.Mkdir(frpDir, 0o700); err != nil {
		t.Fatal(err)
	}
	// Named to come before frp, so that the cleanup of the root stops at it first.
	holdForeignChild(t, root, "a-held.txt")
	t.Setenv("ADMINHELPER_MONITOR_DIR", root)
	t.Setenv("ADMINHELPER_FRP_DIR", frpDir)
	pointSyncAt(t, srv.URL)

	err := Sync(context.Background())
	if err == nil || !strings.Contains(err.Error(), frpDir) {
		t.Fatalf("Sync = %v, want the failure to secure %s, naming it", err, frpDir)
	}
	for _, path := range []string{config.FrpConfigFile(), config.FrpConfigFile() + ".tmp", adminConfFile()} {
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			t.Errorf("%s was written (Stat: %v)", path, err)
		}
	}
	if calls.enables+calls.restarts+calls.reloads+calls.disables != 0 {
		t.Errorf("enables = %d, restarts = %d, reloads = %d, disables = %d, want none",
			calls.enables, calls.restarts, calls.reloads, calls.disables)
	}
}

// The log file, held open the way the logger keeps it (lumberjack opens it with
// O_CREATE|O_WRONLY|O_APPEND, without FILE_SHARE_DELETE), does not stop a sync with a
// new config: securing the data root keeps the file and only resets its ACL, and the
// logger goes on writing to it.
func TestSyncIsNotStoppedByTheOpenLogFile(t *testing.T) {
	srv, _ := hashServer(t, `{"hash":"`+hashConfig(tunnelToml)+`"}`, tunnelToml)
	calls := setupSyncTest(t, srv.URL)
	root := t.TempDir()
	t.Setenv("ADMINHELPER_MONITOR_DIR", root)
	t.Setenv("ADMINHELPER_FRP_DIR", filepath.Join(root, "frp"))
	t.Setenv("ADMINHELPER_LOG_DIR", filepath.Join(root, "logs"))
	// As logging.Init does before the logger opens the file, and the provisioning before
	// it writes the sync config.
	if err := config.EnsureLogDir(); err != nil {
		t.Fatalf("EnsureLogDir: %v", err)
	}
	logFile, err := os.OpenFile(config.LogFile(), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { logFile.Close() })
	if err := config.EnsureDataDir(config.FrpDir()); err != nil {
		t.Fatalf("EnsureDataDir(%s): %v", config.FrpDir(), err)
	}
	pointSyncAt(t, srv.URL)

	if err := Sync(context.Background()); err != nil {
		t.Fatalf("Sync with the log file open: %v", err)
	}
	if got, want := readFile(t, config.FrpConfigFile()), localHead(t)+string(tunnelToml); got != want {
		t.Errorf("frpc.toml = %q, want %q", got, want)
	}
	if calls.enables != 1 {
		t.Errorf("enables = %d, want 1", calls.enables)
	}
	if _, err := logFile.WriteString("still logging\n"); err != nil {
		t.Fatalf("write to the open log file after the sync: %v", err)
	}
	if got := readFile(t, config.LogFile()); got != "still logging\n" {
		t.Errorf("log file = %q, want %q", got, "still logging\n")
	}
}
