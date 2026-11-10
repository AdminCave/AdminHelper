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
	for _, name := range []string{"inetd", "sshd"} {
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
