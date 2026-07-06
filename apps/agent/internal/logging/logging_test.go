// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package logging

import (
	"bytes"
	"log/slog"
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
