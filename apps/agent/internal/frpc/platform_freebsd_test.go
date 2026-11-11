// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package frpc

import (
	"context"
	"errors"
	"net"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"testing"
	"time"

	"adminhelper-agent/internal/config"
)

// fakeService points serviceCommand at a script that logs its arguments, one call per line, and
// then runs script; no test reaches the host's rc.d. It returns the log's path.
func fakeService(t *testing.T, script string) string {
	t.Helper()
	dir := t.TempDir()
	log := filepath.Join(dir, "calls")
	stub := filepath.Join(dir, "service")
	body := "#!/bin/sh\necho \"$*\" >> " + log + "\n" + script + "\n"
	if err := os.WriteFile(stub, []byte(body), 0o755); err != nil {
		t.Fatal(err)
	}
	old := serviceCommand
	serviceCommand = stub
	t.Cleanup(func() { serviceCommand = old })
	return log
}

func serviceCalls(t *testing.T, log string) []string {
	t.Helper()
	data, err := os.ReadFile(log)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	return strings.Split(strings.TrimSpace(string(data)), "\n")
}

// The rcvar gates start and restart: while it is off they do nothing and exit 0. So the agent
// starts and restarts with the one prefix, and stops with fast, which exits 0 when frpc does not
// run.
func TestFrpcServiceCalls(t *testing.T) {
	for _, tc := range []struct {
		name   string
		action func(context.Context) error
		want   []string
	}{
		{"enableFrpcService", enableFrpcService, []string{rcName + " enable", rcName + " onestart"}},
		{"restartFrpc", restartFrpc, []string{rcName + " onerestart"}},
		{"disableFrpc", disableFrpc, []string{rcName + " faststop", rcName + " disable"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			log := fakeService(t, "exit 0")
			if err := tc.action(context.Background()); err != nil {
				t.Fatalf("%s = %v", tc.name, err)
			}
			if got := serviceCalls(t, log); !reflect.DeepEqual(got, tc.want) {
				t.Errorf("service calls = %q, want %q", got, tc.want)
			}
		})
	}
}

// A failing first call ends the action: no start after a failed enable, no disable after a
// failed stop, which would leave frpc running without starting at boot.
func TestFrpcServiceStopsAtTheFirstFailure(t *testing.T) {
	for name, action := range map[string]func(context.Context) error{
		"enableFrpcService": enableFrpcService,
		"disableFrpc":       disableFrpc,
	} {
		t.Run(name, func(t *testing.T) {
			log := fakeService(t, "exit 1")
			if err := action(context.Background()); err == nil {
				t.Fatalf("%s = nil, want an error", name)
			}
			if got := serviceCalls(t, log); len(got) != 1 {
				t.Errorf("service calls = %q, want only the first", got)
			}
		})
	}
}

func TestFrpcActive(t *testing.T) {
	for _, tc := range []struct {
		script  string
		active  bool
		wantErr bool
	}{
		{"exit 0", true, false},
		{"exit 1", false, false},
		// A service(8) that does not answer is no answer, not "not running".
		{"exec /bin/sleep 30", false, true},
	} {
		fakeService(t, tc.script)
		old := serviceTimeout
		serviceTimeout = 200 * time.Millisecond
		active, err := frpcActive(context.Background())
		serviceTimeout = old
		if active != tc.active || (err != nil) != tc.wantErr {
			t.Errorf("%s: frpcActive = %v, %v; want %v, error %v", tc.script, active, err, tc.active, tc.wantErr)
		}
		if tc.wantErr && !errors.Is(err, context.DeadlineExceeded) {
			t.Errorf("%s: frpcActive error %v does not wrap context.DeadlineExceeded", tc.script, err)
		}
	}
}

// daemon(8) runs on while frpc fails and empties the child pidfile until it starts frpc again;
// frpc counts as down then, as on Linux while systemd waits to restart it.
func TestFrpcDownReadsTheChildPidFile(t *testing.T) {
	dir := t.TempDir()
	old := rcChildPidFile
	rcChildPidFile = filepath.Join(dir, "child.pid")
	t.Cleanup(func() { rcChildPidFile = old })
	for _, tc := range []struct {
		name, status string
		pid          *string
		down         bool
	}{
		{"daemon down", "exit 1", ptr("1234\n"), true},
		{"frpc runs", "exit 0", ptr("1234\n"), false},
		{"daemon waits to restart frpc", "exit 0", ptr(""), true},
		{"pidfile with a blank line", "exit 0", ptr("\n"), true},
		{"no pidfile", "exit 0", nil, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			fakeService(t, tc.status)
			_ = os.Remove(rcChildPidFile)
			if tc.pid != nil {
				if err := os.WriteFile(rcChildPidFile, []byte(*tc.pid), 0o644); err != nil {
					t.Fatal(err)
				}
			}
			down, err := frpcDown(context.Background())
			if err != nil || down != tc.down {
				t.Errorf("frpcDown = %v, %v; want %v, nil", down, err, tc.down)
			}
		})
	}
}

func ptr(s string) *string { return &s }

// The parser against the real sockstat: it finds this test's own listener on loopback by the
// test's uid and pid, and frpcOwnsAdminPort takes it for frpc only if the child pidfile names this
// process and it runs as root.
func TestSockstatSeesItsOwnListener(t *testing.T) {
	ln, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	port := ln.Addr().(*net.TCPAddr).Port
	uid, pid := strconv.Itoa(os.Getuid()), strconv.Itoa(os.Getpid())
	if !sockstatListens(port, uid, pid) {
		t.Fatalf("sockstat does not show uid %s, pid %s on 127.0.0.1:%d", uid, pid, port)
	}
	if sockstatListens(port, uid, strconv.Itoa(os.Getpid()+1)) {
		t.Error("sockstat matched another pid")
	}
	if sockstatListens(port, uid+"1", pid) {
		t.Error("sockstat matched another uid")
	}

	old := rcChildPidFile
	rcChildPidFile = filepath.Join(t.TempDir(), "child.pid")
	t.Cleanup(func() { rcChildPidFile = old })
	for _, tc := range []struct {
		name, content string
		want          bool
	}{
		{"names this process", pid + "\n", os.Getuid() == 0},
		{"names another process", strconv.Itoa(os.Getpid()+1) + "\n", false},
		{"is empty", "", false},
	} {
		if err := os.WriteFile(rcChildPidFile, []byte(tc.content), 0o644); err != nil {
			t.Fatal(err)
		}
		if got := frpcOwnsAdminPort(port); got != tc.want {
			t.Errorf("child pidfile %s: frpcOwnsAdminPort = %v, want %v", tc.name, got, tc.want)
		}
	}
	if err := os.Remove(rcChildPidFile); err != nil {
		t.Fatal(err)
	}
	if frpcOwnsAdminPort(port) {
		t.Error("frpcOwnsAdminPort without a child pidfile = true")
	}
}

// The rc script reads the frpc.toml the agent writes, and frpcDown reads the pidfile the script
// has daemon(8) write; rcscript_test.go checks the script against rcChildPidFile.
func TestRCScriptMatchesTheAgentsPaths(t *testing.T) {
	t.Setenv("ADMINHELPER_FRP_DIR", "")
	if got := config.FrpConfigFile(); got != rcScriptFrpcConfig {
		t.Errorf("config.FrpConfigFile() = %q, the rc script reads %q", got, rcScriptFrpcConfig)
	}
}
