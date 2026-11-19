// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux || freebsd

package execx

import (
	"context"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestRunCappedEndsTheGrandchildOfACommandItKills(t *testing.T) {
	for name, limit := range map[string]int{"its time limit": 1 << 10, "its output limit": 4} {
		t.Run(name, func(t *testing.T) {
			pidFile := filepath.Join(t.TempDir(), "pid")
			// The shell stands for runuser: the sleep below it is what the kill must reach too.
			script := `sleep 60 & echo $! > "$1"; echo 0123456789; wait`
			timeout := 2 * time.Second
			if limit == 4 {
				timeout = time.Minute
			}
			_, err := RunCapped(context.Background(), timeout, limit, "sh", "-c", script, "sh", pidFile)
			if !errors.Is(err, context.DeadlineExceeded) && !errors.Is(err, ErrOutputLimit) {
				t.Fatalf("err = %v, want the end of the command by a limit", err)
			}
			text, rerr := os.ReadFile(pidFile)
			if rerr != nil {
				t.Fatal(rerr)
			}
			pid, perr := strconv.Atoi(strings.TrimSpace(string(text)))
			if perr != nil {
				t.Fatal(perr)
			}
			t.Cleanup(func() { _ = syscall.Kill(pid, syscall.SIGKILL) })
			deadline := time.Now().Add(30 * time.Second)
			for syscall.Kill(pid, 0) == nil {
				if time.Now().After(deadline) {
					t.Fatalf("the grandchild %d still runs after RunCapped ended its command", pid)
				}
				time.Sleep(50 * time.Millisecond)
			}
		})
	}
}

func TestRunReaderStreamsAndEndsTheCommandWhenReadFails(t *testing.T) {
	ctx := context.Background()
	var got string
	err := RunReader(ctx, time.Minute, func(r io.Reader) error {
		b, err := io.ReadAll(r)
		got = string(b)
		return err
	}, "sh", "-c", "printf abc")
	if err != nil || got != "abc" {
		t.Fatalf("RunReader = %q, %v", got, err)
	}

	// A read that stops early ends a command that would write on: its error is the result, and the
	// command does not run on to its own end.
	stop := errors.New("enough")
	start := time.Now()
	err = RunReader(ctx, time.Minute, func(r io.Reader) error {
		_, _ = r.Read(make([]byte, 1))
		return stop
	}, "sh", "-c", "yes; sleep 60")
	if !errors.Is(err, stop) || time.Since(start) > 20*time.Second {
		t.Fatalf("err = %v after %v, want %v at once", err, time.Since(start), stop)
	}

	// A read that leaves the rest still sees the exit of the command.
	err = RunReader(ctx, time.Minute, func(io.Reader) error { return nil }, "sh", "-c", "echo x; exit 3")
	if exitErr := (*exec.ExitError)(nil); !errors.As(err, &exitErr) || exitErr.ExitCode() != 3 {
		t.Fatalf("err = %v, want exit 3", err)
	}

	// The deadline itself is under test, so it is short on purpose.
	err = RunReader(ctx, 200*time.Millisecond, func(r io.Reader) error {
		_, err := io.ReadAll(r)
		return err
	}, "sh", "-c", "sleep 60")
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("err = %v, want the timeout", err)
	}
}
