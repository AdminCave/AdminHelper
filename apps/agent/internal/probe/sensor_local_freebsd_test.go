// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build freebsd

package probe

import (
	"context"
	"errors"
	"net"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
)

func TestRefuseKernelFileReadsTheFileSystemOfFreeBSD(t *testing.T) {
	path := filepath.Join(t.TempDir(), "plain")
	if err := os.WriteFile(path, []byte("x"), 0o600); err != nil {
		t.Fatal(err)
	}
	for p, refused := range map[string]bool{path: false, "/dev/null": true} {
		f, err := os.Open(p)
		if err != nil {
			t.Fatal(err)
		}
		err = refuseKernelFile(f, p)
		_ = f.Close()
		if got := err != nil && strings.Contains(err.Error(), "file system of the kernel"); got != refused {
			t.Errorf("refuseKernelFile(%s) = %v, want refused %v", p, err, refused)
		}
	}
}

func TestDialUnixNamesTheProcessServingTheSocket(t *testing.T) {
	path := filepath.Join(t.TempDir(), "s.sock")
	ln, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			_ = c.Close()
		}
	}()
	ctx := context.Background()

	conn, err := net.Dial("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	pid, err := peerPID(conn.(*net.UnixConn))
	_ = conn.Close()
	if err != nil || pid != int32(os.Getpid()) {
		t.Fatalf("peerPID = %d, %v, want the test's own %d", pid, err, os.Getpid())
	}

	h := &fakeHost{names: map[int32]string{int32(os.Getpid()): "nginx"}}
	stubHost(t, h)
	if c, err := dialUnix(ctx, path); err != nil {
		t.Errorf("dialUnix served by nginx = %v, want it connected", err)
	} else {
		_ = c.Close()
	}
	for _, name := range []string{"inetd", "sshd", "socat", "rinetd"} {
		h.names[int32(os.Getpid())] = name
		if c, err := dialUnix(ctx, path); !errors.Is(err, ErrNotAllowed) {
			if c != nil {
				_ = c.Close()
			}
			t.Errorf("dialUnix served by %s = %v, want ErrNotAllowed", name, err)
		}
	}
	if _, err := dialUnix(ctx, filepath.Join(t.TempDir(), "none.sock")); !errors.Is(err, errNoListener) {
		t.Errorf("dialUnix of a missing socket = %v, want errNoListener", err)
	}
}

// shortTempDir returns a new directory with its links resolved, short enough for a unix socket path
// (104 bytes on FreeBSD; t.TempDir carries the test's name).
func shortTempDir(t *testing.T) string {
	dir, err := os.MkdirTemp("", "ah")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	dir, err = filepath.EvalSymlinks(dir)
	if err != nil {
		t.Fatal(err)
	}
	return dir
}

func TestDialUnixNeverConnectsToASocketOfAControlService(t *testing.T) {
	dir := shortTempDir(t)
	path := filepath.Join(dir, "s.sock")
	ln, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = ln.Close() })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			_ = c.Close()
		}
	}()
	stubHost(t, &fakeHost{names: map[int32]string{int32(os.Getpid()): "nginx"}})
	ctx := context.Background()
	if c, err := dialUnix(ctx, path); err != nil {
		t.Fatalf("before = %v; want it connected", err)
	} else {
		_ = c.Close()
	}
	link := filepath.Join(shortTempDir(t), "l.sock")
	if err := os.Symlink(path, link); err != nil {
		t.Fatal(err)
	}
	old := controlSockets
	t.Cleanup(func() { controlSockets = old })
	controlSockets = append(slices.Clone(old), dir+"/")

	for _, p := range []string{path, link} {
		c, err := dialUnix(ctx, p)
		if c != nil {
			_ = c.Close()
		}
		if !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), "a socket of a service the agent never probes") {
			t.Errorf("dialUnix(%s) = %v; want it refused", p, err)
		}
	}
	// OPNsense's configd, whether it serves on this host or not.
	c, err := dialUnix(ctx, "/var/run/configd.socket")
	if c != nil {
		_ = c.Close()
	}
	if !errors.Is(err, ErrNotAllowed) {
		t.Errorf("dialUnix(/var/run/configd.socket) = %v; want ErrNotAllowed", err)
	}
}

func TestDialUnixFollowsTheSocketNotItsName(t *testing.T) {
	stubHost(t, &fakeHost{names: map[int32]string{int32(os.Getpid()): "nginx"}})
	dir := shortTempDir(t)
	ctx := context.Background()
	old := controlSockets
	t.Cleanup(func() { controlSockets = old })
	listen := func(path string) {
		t.Helper()
		ln, err := net.Listen("unix", path)
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = ln.Close() })
		go func() {
			for {
				c, err := ln.Accept()
				if err != nil {
					return
				}
				_ = c.Close()
			}
		}()
	}
	refused := func(p, why string) {
		t.Helper()
		c, err := dialUnix(ctx, p)
		if c != nil {
			_ = c.Close()
		}
		if !errors.Is(err, ErrNotAllowed) || !strings.Contains(err.Error(), why) {
			t.Errorf("dialUnix(%s) = %v; want it refused: %s", p, err, why)
		}
	}

	// A second name of a single control socket is refused before the dial.
	ctl := filepath.Join(dir, "ctl.sock")
	listen(ctl)
	controlSockets = append(slices.Clone(old), ctl)
	hard := filepath.Join(dir, "h.sock")
	if err := os.Link(ctl, hard); err != nil {
		t.Fatal(err)
	}
	refused(hard, "under another name")

	// A directory of controlSockets renamed after the bind: the name its server bound gives it away.
	if err := os.Mkdir(filepath.Join(dir, "a"), 0o700); err != nil {
		t.Fatal(err)
	}
	listen(filepath.Join(dir, "a", "s.sock"))
	controlSockets = append(slices.Clone(old), filepath.Join(dir, "a")+"/")
	if err := os.Rename(filepath.Join(dir, "a"), filepath.Join(dir, "b")); err != nil {
		t.Fatal(err)
	}
	refused(filepath.Join(dir, "b", "s.sock"), "a socket of a service the agent never probes")
	controlSockets = old
	if c, err := dialUnix(ctx, filepath.Join(dir, "b", "s.sock")); err != nil {
		t.Errorf("the renamed socket outside controlSockets = %v; want it connected", err)
	} else {
		_ = c.Close()
	}

	// A server that bound a relative path says nothing about where its socket is.
	t.Chdir(dir)
	listen("r.sock")
	refused(filepath.Join(dir, "r.sock"), "bound no absolute path")
}
