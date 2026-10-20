// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package logging gives the agent one place to configure operational logging.
//
// Output goes to BOTH stdout (so the systemd journal / Windows service log keep
// capturing it) AND a size-rotated file under config.LogDir(), so an operator
// has a durable, self-contained log to inspect or attach to a bug report —
// independent of the service manager. stdout is written first in the MultiWriter
// so a non-writable log directory (e.g. an interactive non-root run) never
// suppresses console output; the file write just fails silently in that case.
//
// Format is slog's human-readable text (key=value with an RFC3339 timestamp),
// not JSON: the agent logs sparsely and operators read this directly.
package logging

import (
	"fmt"
	"io"
	"log/slog"
	"os"
	"strings"

	"gopkg.in/natefinch/lumberjack.v2"

	"adminhelper-agent/internal/config"
)

// Init installs the default slog logger. Call once at startup, before any
// command runs. level is one of debug/info/warn/error (default info).
//
// The log directory is secured first (config.EnsureLogDir, Windows only), since
// the file logger would create it with inherited rights. If that fails, the agent
// logs to stdout only, silently, as with a non-writable log directory.
func Init(level string) {
	var writer io.Writer = os.Stdout
	if config.EnsureLogDir() == nil {
		writer = io.MultiWriter(os.Stdout, &lumberjack.Logger{
			Filename:   config.LogFile(),
			MaxSize:    10, // megabytes per file
			MaxBackups: 5,  // keep 5 rotated files
			Compress:   true,
		})
	}
	handler := slog.NewTextHandler(writer, &slog.HandlerOptions{Level: parseLevel(level)})
	slog.SetDefault(slog.New(handler))
}

func parseLevel(s string) slog.Level {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "debug":
		return slog.LevelDebug
	case "warn", "warning":
		return slog.LevelWarn
	case "error":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

// Logger is a small printf-style facade over slog tagged with a component name.
// It resolves slog.Default() on each call, so package-level instances created
// via For() before Init() runs still log through the configured handler.
type Logger struct {
	component string
}

// For returns a logger tagged with the given component (e.g. "frpc").
func For(component string) *Logger {
	return &Logger{component: component}
}

func (l *Logger) tagged() *slog.Logger {
	return slog.Default().With("component", l.component)
}

// Infof logs at INFO with printf-style formatting.
func (l *Logger) Infof(format string, args ...any) { l.tagged().Info(fmt.Sprintf(format, args...)) }

// Warnf logs at WARN with printf-style formatting.
func (l *Logger) Warnf(format string, args ...any) { l.tagged().Warn(fmt.Sprintf(format, args...)) }

// Errorf logs at ERROR with printf-style formatting.
func (l *Logger) Errorf(format string, args ...any) {
	l.tagged().Error(fmt.Sprintf(format, args...))
}
