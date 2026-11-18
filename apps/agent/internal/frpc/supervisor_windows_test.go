// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build windows

package frpc

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"net"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"golang.org/x/sys/windows"
)

// The test binary stands in for frpc.exe when AH_FAKE_FRPC is set: `reload` exits with
// AH_FAKE_FRPC_RELOAD_RC; a run appends a line to AH_FAKE_FRPC_LOG, listens on
// 127.0.0.1:AH_FAKE_FRPC_PORT if set, and ends after AH_FAKE_FRPC_LIFE or never.
func TestMain(m *testing.M) {
	if os.Getenv("AH_FAKE_FRPC") == "1" {
		os.Exit(fakeFrpcMain(os.Args[1:]))
	}
	os.Exit(m.Run())
}

func fakeFrpcMain(args []string) int {
	if len(args) > 0 && args[0] == "reload" {
		rc, _ := strconv.Atoi(os.Getenv("AH_FAKE_FRPC_RELOAD_RC"))
		return rc
	}
	if f, err := os.OpenFile(os.Getenv("AH_FAKE_FRPC_LOG"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600); err == nil {
		f.WriteString(strings.Join(args, " ") + "\n")
		f.Close()
	}
	if port := os.Getenv("AH_FAKE_FRPC_PORT"); port != "" {
		ln, err := net.Listen("tcp", "127.0.0.1:"+port)
		if err != nil {
			return 2
		}
		defer ln.Close()
	}
	if life, err := time.ParseDuration(os.Getenv("AH_FAKE_FRPC_LIFE")); err == nil {
		time.Sleep(life)
		return 1
	}
	select {}
}

// useFakeFrpc points the supervisor at the test binary as frpc.exe, pinned with its own hash,
// and returns the file each start of it writes a line to.
func useFakeFrpc(t *testing.T) (startLog string) {
	t.Helper()
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(exe)
	if err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(data)
	oldPath, oldSum := frpcExePath, frpcWantSHA256
	frpcExePath = func() (string, error) { return exe, nil }
	frpcWantSHA256 = hex.EncodeToString(sum[:])
	t.Cleanup(func() { frpcExePath, frpcWantSHA256 = oldPath, oldSum })

	dir := t.TempDir()
	t.Setenv("ADMINHELPER_FRP_DIR", dir)
	startLog = dir + `\starts.log`
	t.Setenv("AH_FAKE_FRPC", "1")
	t.Setenv("AH_FAKE_FRPC_LOG", startLog)
	t.Setenv("AH_FAKE_FRPC_PORT", "")
	t.Setenv("AH_FAKE_FRPC_LIFE", "")
	t.Setenv("AH_FAKE_FRPC_RELOAD_RC", "0")
	return startLog
}

// supervise runs a supervisor as the service does, until the test ends.
func supervise(t *testing.T) *supervisor {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	stop, err := Supervise(ctx)
	if err != nil {
		cancel()
		t.Fatalf("Supervise: %v", err)
	}
	s := current.Load()
	t.Cleanup(func() {
		stop()
		cancel()
		if current.Load() != nil {
			t.Error("the supervisor is still current after stop")
		}
	})
	return s
}

func starts(t *testing.T, startLog string) int {
	t.Helper()
	data, err := os.ReadFile(startLog)
	if errors.Is(err, os.ErrNotExist) {
		return 0
	}
	if err != nil {
		t.Fatal(err)
	}
	return strings.Count(string(data), "\n")
}

func waitFor(t *testing.T, what string, cond func() bool) {
	t.Helper()
	deadline := time.Now().Add(30 * time.Second)
	for !cond() {
		if time.Now().After(deadline) {
			t.Fatalf("timed out waiting for %s", what)
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func active(t *testing.T) bool {
	t.Helper()
	ok, err := frpcActive(context.Background())
	if err != nil {
		t.Fatalf("frpcActive: %v", err)
	}
	return ok
}

// enable starts frpc once on frpc.toml, a second enable keeps it, restart starts a new one and
// disable stops it.
func TestSupervisorStartsRestartsAndStopsFrpc(t *testing.T) {
	startLog := useFakeFrpc(t)
	// A short backoff, so that a restart after disable would show within the check below.
	oldMin := restartMin
	restartMin = 10 * time.Millisecond
	t.Cleanup(func() { restartMin = oldMin })
	s := supervise(t)
	ctx := context.Background()

	if active(t) {
		t.Fatal("frpc runs before the first enable")
	}
	if err := enableFrpcService(ctx); err != nil {
		t.Fatalf("enable: %v", err)
	}
	first := s.pid()
	if first == 0 || !active(t) {
		t.Fatal("frpc does not run after enable")
	}
	if down, err := frpcDown(ctx); down || err != nil {
		t.Errorf("frpcDown = %v, %v while frpc runs", down, err)
	}
	if err := enableFrpcService(ctx); err != nil || s.pid() != first {
		t.Errorf("a second enable = %v and pid %d, want frpc %d kept", err, s.pid(), first)
	}
	waitFor(t, "the first start", func() bool { return starts(t, startLog) == 1 })
	if data, _ := os.ReadFile(startLog); !strings.Contains(string(data), "-c "+os.Getenv("ADMINHELPER_FRP_DIR")) {
		t.Errorf("frpc was started with %q, want -c on frpc.toml", data)
	}

	if err := restartFrpc(ctx); err != nil {
		t.Fatalf("restart: %v", err)
	}
	if second := s.pid(); second == 0 || second == first {
		t.Fatalf("pid after restart = %d, want a new frpc (old %d)", second, first)
	}
	waitFor(t, "the second start", func() bool { return starts(t, startLog) == 2 })

	if err := disableFrpc(ctx); err != nil {
		t.Fatalf("disable: %v", err)
	}
	if active(t) {
		t.Fatal("frpc runs after disable")
	}
	time.Sleep(100 * time.Millisecond)
	if n := starts(t, startLog); n != 2 {
		t.Errorf("frpc started %d times, want 2: disable must not lead to a restart", n)
	}
}

// A frpc.exe that is not the pinned one does not start.
func TestSupervisorRefusesAnUnpinnedFrpc(t *testing.T) {
	startLog := useFakeFrpc(t)
	frpcWantSHA256 = strings.Repeat("0", 64)
	supervise(t)

	err := enableFrpcService(context.Background())
	if err == nil || !strings.Contains(err.Error(), "not the pinned frpc") {
		t.Fatalf("enable = %v, want the refusal of an unpinned frpc", err)
	}
	if active(t) {
		t.Error("an unpinned frpc runs")
	}
	if err := reloadFrpc(context.Background()); err == nil {
		t.Error("reload ran an unpinned frpc")
	}
	time.Sleep(100 * time.Millisecond)
	if n := starts(t, startLog); n != 0 {
		t.Errorf("the unpinned frpc started %d times", n)
	}
}

// When frpc ends on its own, the supervisor starts it again after the backoff, until disable.
func TestSupervisorRestartsFrpcWhenItEnds(t *testing.T) {
	startLog := useFakeFrpc(t)
	t.Setenv("AH_FAKE_FRPC_LIFE", "50ms")
	oldMin, oldMax := restartMin, restartMax
	restartMin, restartMax = 10*time.Millisecond, 100*time.Millisecond
	t.Cleanup(func() { restartMin, restartMax = oldMin, oldMax })
	supervise(t)

	if err := enableFrpcService(context.Background()); err != nil {
		t.Fatalf("enable: %v", err)
	}
	waitFor(t, "three starts", func() bool { return starts(t, startLog) >= 3 })
	if err := disableFrpc(context.Background()); err != nil {
		t.Fatalf("disable: %v", err)
	}
	n := starts(t, startLog)
	time.Sleep(300 * time.Millisecond)
	if after := starts(t, startLog); after != n {
		t.Errorf("frpc started %d more times after disable", after-n)
	}
}

// frpc sits in a job object that kills it when the job's last handle closes, which is what
// happens when the agent process dies.
func TestFrpcEndsWithItsJob(t *testing.T) {
	useFakeFrpc(t)
	job, err := newKillOnCloseJob()
	if err != nil {
		t.Fatal(err)
	}
	exe, _ := frpcExePath()
	s := &supervisor{ctx: context.Background(), exe: exe, job: job}
	if err := s.enable(); err != nil {
		windows.CloseHandle(job)
		t.Fatalf("enable: %v", err)
	}
	s.mu.Lock()
	s.want = false // the restart is not what this test is about
	done := s.done
	s.mu.Unlock()

	windows.CloseHandle(job)
	select {
	case <-done:
	case <-time.After(30 * time.Second):
		_ = s.disable()
		t.Fatal("frpc still runs after its job was closed")
	}
}

// Outside the service process no hook claims that frpc runs or was started (R-0708).
func TestHooksFailOutsideTheService(t *testing.T) {
	if current.Load() != nil {
		t.Fatal("a supervisor is left over from another test")
	}
	ctx := context.Background()
	for name, hook := range map[string]func() error{
		"enable":  func() error { return enableFrpcService(ctx) },
		"restart": func() error { return restartFrpc(ctx) },
		"disable": func() error { return disableFrpc(ctx) },
		"reload":  func() error { return reloadFrpc(ctx) },
		"active":  func() error { _, err := frpcActive(ctx); return err },
		"down":    func() error { _, err := frpcDown(ctx); return err },
	} {
		if err := hook(); !errors.Is(err, errNotSupervised) {
			t.Errorf("%s = %v, want errNotSupervised", name, err)
		}
	}
	if frpcOwnsAdminPort(7400) {
		t.Error("frpcOwnsAdminPort is true without a supervisor")
	}
}

func freePort(t *testing.T) int {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	ln.Close()
	return port
}

// The reload goes only to a port the frpc of the supervisor listens on, not to another process's.
func TestFrpcOwnsItsAdminPortOnly(t *testing.T) {
	useFakeFrpc(t)
	port := freePort(t)
	t.Setenv("AH_FAKE_FRPC_PORT", strconv.Itoa(port))
	supervise(t)
	if frpcOwnsAdminPort(port) {
		t.Fatal("frpcOwnsAdminPort is true before frpc runs")
	}
	if err := enableFrpcService(context.Background()); err != nil {
		t.Fatalf("enable: %v", err)
	}
	waitFor(t, "frpc on its admin port", func() bool { return frpcOwnsAdminPort(port) })

	other, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close()
	if frpcOwnsAdminPort(other.Addr().(*net.TCPAddr).Port) {
		t.Error("frpcOwnsAdminPort is true for a port of another process")
	}
}

// reload runs the pinned frpc.exe with `reload -c frpc.toml` and reports its failure.
func TestReloadFrpc(t *testing.T) {
	useFakeFrpc(t)
	supervise(t)
	if err := reloadFrpc(context.Background()); err != nil {
		t.Fatalf("reload: %v", err)
	}
	t.Setenv("AH_FAKE_FRPC_RELOAD_RC", "3")
	if err := reloadFrpc(context.Background()); err == nil {
		t.Error("a failed reload reports success")
	}
}

// lineTail keeps the last lines frpc wrote, also a line without its newline.
func TestLineTail(t *testing.T) {
	tail := &lineTail{max: 2}
	if got := tail.String(); got != "(none)" {
		t.Errorf("empty tail = %q", got)
	}
	tail.Write([]byte("one\r\ntwo\nthr"))
	tail.Write([]byte("ee\nfour"))
	if got, want := tail.String(), "two | three | four"; got != want {
		t.Errorf("tail = %q, want %q", got, want)
	}
}
