// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package execx

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"
)

// helperEnv tells TestHelperProcess, run as a child process, how to behave.
const helperEnv = "AH_EXECX_HELPER"

// helperOutput is what the "print" and "exit-orphan" helpers write before they end.
const helperOutput = "helper output"

// grandchildLifetime bounds the "chatter" grandchild of "exit-orphan". It ends at its first failed
// write, once Run has closed the pipe. A grandchild that outlived the test would keep go test from
// deleting the test binary on Windows.
const grandchildLifetime = 20 * time.Second

// TestHelperProcess is no test of its own: the tests below start the test binary as their child
// process, which then behaves as helperEnv says. Without it, it returns at once.
func TestHelperProcess(t *testing.T) {
	switch os.Getenv(helperEnv) {
	case "print":
		fmt.Print(helperOutput)
		os.Exit(0)
	case "hang":
		time.Sleep(time.Minute)
	case "fail":
		os.Exit(3)
	case "exit-orphan":
		// A tool that starts a grandchild with its own stdout (a daemon, a pager) and exits 0.
		grandchild := exec.Command(os.Args[0], "-test.run=^TestHelperProcess$")
		grandchild.Env = append(os.Environ(), helperEnv+"=chatter")
		grandchild.Stdout = os.Stdout
		if err := grandchild.Start(); err != nil {
			os.Exit(4)
		}
		fmt.Print(helperOutput)
		os.Exit(0)
	case "chatter":
		for end := time.Now().Add(grandchildLifetime); time.Now().Before(end); {
			if _, err := fmt.Println("chatter"); err != nil {
				os.Exit(0)
			}
			time.Sleep(100 * time.Millisecond)
		}
	}
}

// runHelper runs the test binary through Run as a child process that behaves as mode says.
func runHelper(t *testing.T, ctx context.Context, mode string, timeout time.Duration) ([]byte, error, time.Duration) {
	t.Helper()
	t.Setenv(helperEnv, mode)
	start := time.Now()
	out, err := Run(ctx, timeout, os.Args[0], "-test.run=^TestHelperProcess$")
	return out, err, time.Since(start)
}

func TestRunReturnsTheOutput(t *testing.T) {
	out, err, _ := runHelper(t, context.Background(), "print", time.Minute)
	if err != nil {
		t.Fatalf("err = %v", err)
	}
	if !strings.HasPrefix(string(out), helperOutput) {
		t.Errorf("output = %q, want it to start with %q", out, helperOutput)
	}
}

func TestRunTimeoutIsDeadlineExceeded(t *testing.T) {
	// exec reports the kill as the ExitError "signal: killed": Run must say it was the timeout.
	_, err, elapsed := runHelper(t, context.Background(), "hang", 100*time.Millisecond)
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("err = %v, want context.DeadlineExceeded", err)
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		t.Errorf("err = %v is an ExitError, a hanging tool would pass for a failing one", err)
	}
	if elapsed > 10*time.Second {
		t.Errorf("Run returned after %s, the timeout did not stop the call", elapsed)
	}
}

func TestRunCanceledContextIsCanceled(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	time.AfterFunc(100*time.Millisecond, cancel)
	_, err, elapsed := runHelper(t, ctx, "hang", time.Minute)
	if !errors.Is(err, context.Canceled) {
		t.Errorf("err = %v, want context.Canceled", err)
	}
	if elapsed > 10*time.Second {
		t.Errorf("Run returned after %s, the context did not end the call", elapsed)
	}
}

func TestRunFailingToolIsItsExitError(t *testing.T) {
	_, err, _ := runHelper(t, context.Background(), "fail", time.Minute)
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != 3 {
		t.Fatalf("err = %v, want the ExitError with code 3", err)
	}
	if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
		t.Errorf("err = %v, a failing tool is no timeout", err)
	}
}

func TestRunToolThatExitedWhileAGrandchildHoldsStdoutSucceeds(t *testing.T) {
	// The tool exited 0 and its output is complete; only its grandchild keeps the pipe open. Run
	// stops reading after WaitDelay and reports no error (exec.ErrWaitDelay).
	out, err, elapsed := runHelper(t, context.Background(), "exit-orphan", time.Minute)
	if err != nil {
		t.Fatalf("err = %v, want nil", err)
	}
	if !strings.Contains(string(out), helperOutput) {
		t.Errorf("output = %q, want it to hold %q", out, helperOutput)
	}
	if elapsed > WaitDelay+8*time.Second {
		t.Errorf("Run returned after %s, the grandchild held it past WaitDelay", elapsed)
	}
}
