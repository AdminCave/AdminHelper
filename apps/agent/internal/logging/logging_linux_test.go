// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package logging

import (
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// With a stdout that cannot be written, as for a Windows service, Init still writes
// each line to agent.log. A closed file stands in for that stdout. Linux only: on
// Windows the open file logger would keep the temp directory from being removed.
func TestFanOutInitWritesTheLogFileWhenStdoutFails(t *testing.T) {
	logDir := t.TempDir()
	t.Setenv("ADMINHELPER_LOG_DIR", logDir)
	stubInitSeams(t, nil, false)
	closed, err := os.Create(filepath.Join(t.TempDir(), "stdout"))
	if err != nil {
		t.Fatal(err)
	}
	if err := closed.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := closed.Write([]byte("probe\n")); err == nil {
		t.Fatal("a write to the closed stand-in for stdout succeeded; the test would prove nothing")
	}
	origStdout := os.Stdout
	t.Cleanup(func() { os.Stdout = origStdout })

	os.Stdout = closed
	Init("info")
	// The handler holds the closed file now; the test framework gets its stdout back.
	os.Stdout = origStdout
	slog.Info("a line while stdout fails")

	data, err := os.ReadFile(filepath.Join(logDir, "agent.log"))
	if err != nil {
		t.Fatalf("agent.log is missing although the log directory is writable: %v", err)
	}
	if !strings.Contains(string(data), "a line while stdout fails") {
		t.Fatalf("agent.log lacks the line logged while stdout failed: %q", data)
	}
}
