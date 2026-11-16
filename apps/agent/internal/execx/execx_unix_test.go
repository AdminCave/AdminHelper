// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux || freebsd

package execx

import (
	"context"
	"errors"
	"os"
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
