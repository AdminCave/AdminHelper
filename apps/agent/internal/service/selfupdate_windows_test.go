// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package service

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"testing"
	"time"

	"adminhelper-agent/internal/logging"
)

// Without an installed frpc.exe, Backup drops a stale frpc.exe.old: a later Restore must not
// bring back an frpc the host no longer had.
func TestBackupWithoutFrpcDropsAStaleCopy(t *testing.T) {
	dir := t.TempDir()
	writeTestFile(t, filepath.Join(dir, agentExeName), []byte("agent"))
	writeTestFile(t, filepath.Join(dir, frpcExeName+backupSuffix), []byte("stale frpc"))
	if err := backup(dir); err != nil {
		t.Fatalf("backup: %v", err)
	}
	if data, err := os.ReadFile(filepath.Join(dir, agentExeName+backupSuffix)); err != nil || string(data) != "agent" {
		t.Errorf("agent backup = %q (%v), want the agent", data, err)
	}
	if _, err := os.Stat(filepath.Join(dir, frpcExeName+backupSuffix)); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("the stale frpc backup is still there: %v", err)
	}
}

// The rollback: after an update, restore stops the service, puts the saved agent and frpc back
// and starts the service again. A missing frpc backup leaves the installed frpc.
func TestRestoreBringsBackTheSavedRelease(t *testing.T) {
	name := fmt.Sprintf("AdminHelper-Agent-Test-%d", os.Getpid())
	source := fmt.Sprintf("%s-Test-%d-%d", logging.EventSource, os.Getpid(), time.Now().UnixNano())
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	agent, err := os.ReadFile(self)
	if err != nil {
		t.Fatal(err)
	}
	frpcExe := []byte("fake frpc")
	pinFakeFrpc(t, frpcExe)
	src := t.TempDir()
	installer := filepath.Join(src, agentExeName)
	writeTestFile(t, installer, agent)
	writeTestFile(t, filepath.Join(src, frpcSourceNames[0]), frpcExe)
	dir := filepath.Join(t.TempDir(), "AdminHelper")
	// Registered after the temporary folders, so that it runs before their removal.
	t.Cleanup(func() {
		if err := uninstall(name, source); err != nil {
			t.Errorf("uninstall: %v", err)
		}
	})
	target := installTarget{name: name, displayName: name, eventSource: source, dir: dir, self: installer}
	if err := install(target); err != nil {
		t.Fatalf("install: %v", err)
	}
	if err := backup(dir); err != nil {
		t.Fatalf("backup: %v", err)
	}

	// The update: a newer agent and frpc.
	newer := append(slices.Clone(agent), []byte("newer")...)
	newerFrpc := []byte("newer frpc")
	writeTestFile(t, installer, newer)
	writeTestFile(t, filepath.Join(src, frpcSourceNames[0]), newerFrpc)
	pinFakeFrpc(t, newerFrpc)
	if err := install(target); err != nil {
		t.Fatalf("update: %v", err)
	}
	updated := runningPID(t, name)

	if err := restore(name, dir); err != nil {
		t.Fatalf("restore: %v", err)
	}
	if restored := runningPID(t, name); restored == updated {
		t.Errorf("the service still runs process %d of the update", updated)
	}
	for path, want := range map[string][]byte{
		filepath.Join(dir, agentExeName): agent, filepath.Join(dir, frpcExeName): frpcExe,
	} {
		if data, err := os.ReadFile(path); err != nil || !slices.Equal(data, want) {
			t.Errorf("%s holds %d bytes (%v), want %d", path, len(data), err, len(want))
		}
		assertOwnedByAdministrators(t, ownerOf(t, path), path)
	}

	// Without a saved frpc, restore keeps the installed one and still restarts the service.
	if err := os.Remove(filepath.Join(dir, frpcExeName+backupSuffix)); err != nil {
		t.Fatal(err)
	}
	before := runningPID(t, name)
	if err := restore(name, dir); err != nil {
		t.Fatalf("restore without a saved frpc: %v", err)
	}
	if after := runningPID(t, name); after == before {
		t.Errorf("restore without a saved frpc did not restart the service")
	}
	if data, err := os.ReadFile(filepath.Join(dir, frpcExeName)); err != nil || !slices.Equal(data, frpcExe) {
		t.Errorf("frpc.exe = %q (%v), want the installed one", data, err)
	}
}
