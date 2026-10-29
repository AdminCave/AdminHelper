// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package logging

import (
	"bytes"
	"errors"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestParseLevel(t *testing.T) {
	cases := map[string]slog.Level{
		"debug":    slog.LevelDebug,
		"DEBUG":    slog.LevelDebug,
		"info":     slog.LevelInfo,
		"":         slog.LevelInfo,
		"nonsense": slog.LevelInfo,
		"warn":     slog.LevelWarn,
		"warning":  slog.LevelWarn,
		" error ":  slog.LevelError,
	}
	for in, want := range cases {
		if got := parseLevel(in); got != want {
			t.Errorf("parseLevel(%q) = %v, want %v", in, got, want)
		}
	}
}

// swapDefaultLogger installs a slog default for the duration of the test and restores the previous
// one afterwards, so a WARN-filtered handler can't leak into a later test in this package under a
// different run order (6.100).
func swapDefaultLogger(t *testing.T, h slog.Handler) {
	t.Helper()
	prev := slog.Default()
	slog.SetDefault(slog.New(h))
	t.Cleanup(func() { slog.SetDefault(prev) })
}

func TestLoggerTagsComponentAndLevel(t *testing.T) {
	var buf bytes.Buffer
	swapDefaultLogger(t, slog.NewTextHandler(&buf, &slog.HandlerOptions{Level: slog.LevelInfo}))

	For("frpc").Warnf("disk at %d%%", 90)

	out := buf.String()
	for _, want := range []string{"level=WARN", "component=frpc", "disk at 90%"} {
		if !strings.Contains(out, want) {
			t.Errorf("log line %q is missing %q", out, want)
		}
	}
}

func TestLoggerInfofRespectsLevelFilter(t *testing.T) {
	var buf bytes.Buffer
	swapDefaultLogger(t, slog.NewTextHandler(&buf, &slog.HandlerOptions{Level: slog.LevelWarn}))

	For("monitor").Infof("should be filtered out")

	if buf.Len() != 0 {
		t.Errorf("INFO must be suppressed at WARN level, got: %q", buf.String())
	}
}

// failingWriter refuses every write, like the stdout of a Windows service.
type failingWriter struct{ err error }

func (w failingWriter) Write([]byte) (int, error) { return 0, w.err }

// shortWriter takes one byte less than it is given and reports no error.
type shortWriter struct{}

func (shortWriter) Write(p []byte) (int, error) { return len(p) - 1, nil }

// The fan-out gives every write to each target, also to one after a target that
// failed, and the write counts as done once one target took it in full. Only when
// no target took it does the first error come back.
func TestFanOutWriterKeepsWritingAfterAFailingTarget(t *testing.T) {
	stdoutErr := errors.New("stdout cannot be written")
	line := []byte("level=INFO msg=\"a line\"\n")

	var file bytes.Buffer
	n, err := fanOut{failingWriter{stdoutErr}, &file}.Write(line)
	if n != len(line) || err != nil {
		t.Fatalf("Write with the first target failing = (%d, %v), want (%d, nil)", n, err, len(line))
	}
	if file.String() != string(line) {
		t.Fatalf("the target after the failing one got %q, want %q", file.String(), line)
	}

	n, err = fanOut{failingWriter{stdoutErr}, failingWriter{errors.New("disk full")}}.Write(line)
	if n != 0 || !errors.Is(err, stdoutErr) {
		t.Fatalf("Write with every target failing = (%d, %v), want (0, %v)", n, err, stdoutErr)
	}
	if _, err := (fanOut{shortWriter{}}).Write(line); !errors.Is(err, io.ErrShortWrite) {
		t.Fatalf("Write with the only target taking less = %v, want %v", err, io.ErrShortWrite)
	}
}

// stubInitSeams has securing the log directory end with ensureErr and runs Init as a
// service with a reporter of its own, or interactively without one; it restores both
// seams and the default logger afterwards. It returns what the reporter received.
func stubInitSeams(t *testing.T, ensureErr error, asService bool) *[]string {
	t.Helper()
	var msgs []string
	origEnsure, origReporter, prevLogger := ensureLogDir, serviceReporter, slog.Default()
	ensureLogDir = func() error { return ensureErr }
	serviceReporter = func() reportFunc {
		if !asService {
			return nil
		}
		return func(msg string) error { msgs = append(msgs, msg); return nil }
	}
	t.Cleanup(func() {
		ensureLogDir, serviceReporter = origEnsure, origReporter
		slog.SetDefault(prevLogger)
	})
	return &msgs
}

// As a service, Init reports a log directory it cannot secure once, with the directory,
// the reason and the consequences, and logs to stdout only. With the directory secured,
// or in an interactive run, it reports nothing.
func TestInitReportsAnUnsecuredLogDirOnlyAsAService(t *testing.T) {
	reason := errors.New("a child of another account is held open")
	cases := []struct {
		name      string
		ensureErr error
		asService bool
		want      int
	}{
		{"unsecured, as a service", reason, true, 1},
		{"secured, as a service", nil, true, 0},
		{"unsecured, interactive", reason, false, 0},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			logDir := filepath.Join(t.TempDir(), "logs")
			t.Setenv("ADMINHELPER_LOG_DIR", logDir)
			msgs := stubInitSeams(t, tc.ensureErr, tc.asService)

			Init("info")

			if len(*msgs) != tc.want {
				t.Fatalf("Init reported %d messages, want %d: %q", len(*msgs), tc.want, *msgs)
			}
			for _, msg := range *msgs {
				for _, want := range []string{logDir, reason.Error(), "stdout only", "FRP sync changes nothing"} {
					if !strings.Contains(msg, want) {
						t.Errorf("the report %q is missing %q", msg, want)
					}
				}
			}
			// A secured directory gets the file logger, which a line would open; on Windows
			// the open file would keep the temp directory from being removed.
			if tc.ensureErr == nil {
				return
			}
			slog.Info("a line after Init")
			if _, err := os.Lstat(filepath.Join(logDir, "agent.log")); !os.IsNotExist(err) {
				t.Fatalf("agent.log exists although the log directory could not be secured (Lstat: %v)", err)
			}
		})
	}
}
