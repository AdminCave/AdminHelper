// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package main

import (
	"bytes"
	"errors"
	"io"
	"strings"
	"testing"

	"adminhelper-agent/internal/monitor"
)

// stubMonitorInit puts init in place of monitor.Init and a counter in place of
// service.EnableTimer (systemctl on Linux) for one test; the timer stub returns timerErr.
func stubMonitorInit(t *testing.T, init func(monitor.InitParams) error, timerErr error) *int {
	t.Helper()
	calls := 0
	origInit, origTimer := monitorInit, enableTimer
	monitorInit = init
	enableTimer = func() error { calls++; return timerErr }
	t.Cleanup(func() { monitorInit, enableTimer = origInit, origTimer })
	return &calls
}

// runMonitorInit runs `monitor init` with the required flags and returns its error.
func runMonitorInit() error {
	cmd := monitorInitCmd()
	cmd.SetArgs([]string{"--url", "https://monitor.example/api/monitoring", "--api-key", "key", "--server-id", "srv-1"})
	cmd.SetOut(io.Discard)
	cmd.SetErr(io.Discard)
	return cmd.Execute()
}

// R-0641: `monitor init` is a setup, so it enables the agent timer, once and only after the
// monitor is set up; a refused setup (wrong trust, no certificate to pin) enables nothing. A
// timer that cannot be enabled is a warning, the setup stands.
func TestMonitorInitEnablesTheTimerAfterTheSetup(t *testing.T) {
	t.Run("setup done", func(t *testing.T) {
		var got monitor.InitParams
		calls := stubMonitorInit(t, func(p monitor.InitParams) error {
			got = p
			return nil
		}, nil)

		if err := runMonitorInit(); err != nil {
			t.Fatalf("monitor init: %v", err)
		}
		if *calls != 1 {
			t.Errorf("timer enabled %d times, want 1", *calls)
		}
		if got.URL != "https://monitor.example/api/monitoring" || got.APIKey != "key" || got.ServerID != "srv-1" {
			t.Errorf("monitor.Init got %+v, want the flags", got)
		}
	})
	t.Run("setup refused", func(t *testing.T) {
		refused := errors.New("--cacert cannot be combined with --insecure")
		calls := stubMonitorInit(t, func(monitor.InitParams) error {
			return refused
		}, nil)

		if err := runMonitorInit(); !errors.Is(err, refused) {
			t.Errorf("monitor init = %v, want the error of monitor.Init", err)
		}
		if *calls != 0 {
			t.Errorf("timer enabled %d times after a refused setup, want 0", *calls)
		}
	})
	t.Run("timer cannot be enabled", func(t *testing.T) {
		calls := stubMonitorInit(t, func(monitor.InitParams) error { return nil },
			errors.New("systemctl enable --now adminhelper-agent.timer: exit status 1"))

		if err := runMonitorInit(); err != nil {
			t.Errorf("monitor init = %v, want nil: the setup stands", err)
		}
		if *calls != 1 {
			t.Errorf("timer enabled %d times, want 1", *calls)
		}
	})
}

// runMonitorInitArgs runs `monitor init` with url, server ID, extra and stdin; out is
// what it wrote to stdout and stderr.
func runMonitorInitArgs(stdin io.Reader, extra ...string) (out string, err error) {
	var buf bytes.Buffer
	cmd := monitorInitCmd()
	cmd.SetArgs(append([]string{"--url", "https://monitor.example/api/monitoring", "--server-id", "srv-1"}, extra...))
	cmd.SetIn(stdin)
	cmd.SetOut(&buf)
	cmd.SetErr(&buf)
	err = cmd.Execute()
	return buf.String(), err
}

func TestMonitorInitAPIKeyFromStdin(t *testing.T) {
	var got monitor.InitParams
	stubMonitorInit(t, func(p monitor.InitParams) error { got = p; return nil }, nil)
	if _, err := runMonitorInitArgs(strings.NewReader(" mon-key-zz9 \nsecond\n"), "--api-key-stdin"); err != nil {
		t.Fatal(err)
	}
	if got.APIKey != "mon-key-zz9" {
		t.Errorf("API key %q, want the trimmed first line of stdin", got.APIKey)
	}
}

func TestMonitorInitAPIKeyStdinErrors(t *testing.T) {
	for name, c := range map[string]struct {
		stdin string
		args  []string
		want  string
	}{
		"empty stdin": {"\n", []string{"--api-key-stdin"}, "no API key on stdin"},
		"both":        {"", []string{"--api-key", "k", "--api-key-stdin"}, "api-key-stdin"},
		"neither":     {"", nil, "api-key-stdin"},
	} {
		calls := 0
		stubMonitorInit(t, func(monitor.InitParams) error { calls++; return nil }, nil)
		stdin := &untouchedStdin{}
		var in io.Reader = stdin
		if c.stdin != "" {
			in = strings.NewReader(c.stdin)
		}
		out, err := runMonitorInitArgs(in, c.args...)
		if err == nil || !strings.Contains(err.Error(), c.want) {
			t.Errorf("%s: err %v, want one naming %q", name, err, c.want)
		}
		if calls != 0 || stdin.read {
			t.Errorf("%s: monitor.Init ran %d times, stdin read %v", name, calls, stdin.read)
		}
		if strings.Contains(out, "zz9") {
			t.Errorf("%s: the output quotes stdin:\n%s", name, out)
		}
	}
}

func TestMonitorInitAPIKeyTerminalPrompt(t *testing.T) {
	fakeTerminal(t, []byte("mon-key"), nil)
	var got monitor.InitParams
	stubMonitorInit(t, func(p monitor.InitParams) error { got = p; return nil }, nil)
	out, err := runMonitorInitArgs(&untouchedStdin{}, "--api-key-stdin")
	if err != nil {
		t.Fatal(err)
	}
	if got.APIKey != "mon-key" || !strings.Contains(out, "API key: ") {
		t.Errorf("API key %q, output %q; want the key read without echo after the prompt", got.APIKey, out)
	}
}
