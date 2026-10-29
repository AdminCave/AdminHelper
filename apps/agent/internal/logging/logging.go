// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Package logging gives the agent one place to configure operational logging.
//
// Output goes to BOTH stdout (so the systemd journal keeps capturing it; under the
// Windows service manager no one reads it) AND a size-rotated file under
// config.LogDir(), so an operator has a durable, self-contained log to inspect or
// attach to a bug report — independent of the service manager. If the log
// directory cannot be secured (config.EnsureLogDir, Windows only, e.g. a run
// without administrator rights), the agent logs to stdout only; as a Windows
// service, it also says so once in the Windows event log. Each line goes to both
// targets, and a target that fails holds up neither the other nor the caller: a
// non-writable log directory (e.g. an interactive non-root run) never suppresses
// console output, the file write just fails silently then; and a stdout that
// cannot be written (a Windows service has none) never keeps a line out of the
// file.
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

// reportFunc hands one message to the log of the service manager the agent runs
// under, where the operator of the service sees it.
type reportFunc func(msg string) error

// Seams, so that a test can have securing the log directory fail and run Init as a
// service. serviceReporter returns nil when there is no log besides stdout to report
// to: in an interactive run, and on Linux, where the journal keeps stdout.
var (
	ensureLogDir    = config.EnsureLogDir
	serviceReporter = platformReporter
)

// Init installs the default slog logger. Call once at startup, before any
// command runs. level is one of debug/info/warn/error (default info).
//
// The log directory is secured first (config.EnsureLogDir, Windows only), since
// the file logger would create it with inherited rights. If that fails, the agent
// logs to stdout only, as with a non-writable log directory. As a Windows service,
// whose stdout no one sees, it reports the directory and the reason once to the
// Windows event log; an interactive run stays silent.
func Init(level string) {
	var writer io.Writer = os.Stdout
	if err := ensureLogDir(); err == nil {
		writer = fanOut{os.Stdout, &lumberjack.Logger{
			Filename:   config.LogFile(),
			MaxSize:    10, // megabytes per file
			MaxBackups: 5,  // keep 5 rotated files
			Compress:   true,
		}}
	} else if report := serviceReporter(); report != nil {
		// If the report fails too, stdout is all that is left, as in an interactive run.
		_ = report(fmt.Sprintf("The AdminHelper agent cannot secure its log directory %s: %v. "+
			"Until the service restarts, the agent logs to stdout only and writes no agent.log. "+
			"The FRP sync changes nothing as long as the data directory cannot be secured.",
			config.LogDir(), err))
	}
	handler := slog.NewTextHandler(writer, &slog.HandlerOptions{Level: parseLevel(level)})
	slog.SetDefault(slog.New(handler))
}

// fanOut hands each write to every target, also after one of them failed:
// io.MultiWriter stops at the first error, and under a Windows service, whose
// stdout cannot be written, no line would then reach agent.log. A write that one
// target took in full counts as done; only when none did does the first error
// come back.
type fanOut []io.Writer

func (f fanOut) Write(p []byte) (int, error) {
	var firstErr error
	done := false
	for _, w := range f {
		n, err := w.Write(p)
		if err == nil && n < len(p) {
			err = io.ErrShortWrite
		}
		if err == nil {
			done = true
		} else if firstErr == nil {
			firstErr = err
		}
	}
	if !done && firstErr != nil {
		return 0, firstErr
	}
	return len(p), nil
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
