// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux

package probe

import (
	"context"
	"errors"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// listenAt puts a unix socket at name below dir and returns it; connections to it are accepted.
func listenAt(t *testing.T, dir, name string) *net.UnixListener {
	t.Helper()
	path := filepath.Join(dir, filepath.FromSlash(name))
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	l, err := net.ListenUnix("unix", &net.UnixAddr{Name: path, Net: "unix"})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { l.Close() })
	return l
}

// shortDir is a temporary directory with a short path: t.TempDir carries the test's name, and a socket's
// path must fit in 108 bytes.
func shortDir(t *testing.T) string {
	t.Helper()
	dir, err := os.MkdirTemp("", "ah")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
	return dir
}

func openTestRoot(t *testing.T, dir string) *os.Root {
	t.Helper()
	root, err := os.OpenRoot(dir)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { root.Close() })
	return root
}

// accepted dials the socket below dir through dialRootSocket and tells if l took the connection.
func accepted(t *testing.T, dir string, l *net.UnixListener) error {
	t.Helper()
	c, err := dialRootSocket(context.Background(), openTestRoot(t, dir))
	if err != nil {
		return err
	}
	defer c.Close()
	s, err := l.Accept()
	if err != nil {
		t.Fatalf("the listener took no connection: %v", err)
	}
	s.Close()
	return nil
}

func TestDialRootSocketConnectsToTheSocketOfTheContainer(t *testing.T) {
	dir := shortDir(t)
	if err := accepted(t, dir, listenAt(t, dir, "run/mysqld/mysqld.sock")); err != nil {
		t.Fatalf("/run: %v", err)
	}
	// An image without /run/mysqld: /var/run/mysqld; a relative link inside the root is followed
	// (os.Root takes an absolute link for an escape).
	dir = shortDir(t)
	if err := accepted(t, dir, listenAt(t, dir, "var/run/mysqld/mysqld.sock")); err != nil {
		t.Fatalf("/var/run: %v", err)
	}
	dir = shortDir(t)
	l := listenAt(t, dir, "srv/mysqld/mysqld.sock")
	if err := os.Symlink("srv", filepath.Join(dir, "run")); err != nil {
		t.Fatal(err)
	}
	if err := accepted(t, dir, l); err != nil {
		t.Fatalf("a link to a directory in the root: %v", err)
	}
}

func TestDialRootSocketGoesNowhereElse(t *testing.T) {
	outside := shortDir(t)
	host := listenAt(t, outside, "host.sock")
	linked := listenAt(t, outside, "d/mysqld.sock")
	for name, put := range map[string]func(dir string) error{
		"nothing": func(string) error { return nil },
		"a link at the name": func(dir string) error {
			if err := os.MkdirAll(filepath.Join(dir, "run/mysqld"), 0o755); err != nil {
				return err
			}
			return os.Symlink(filepath.Join(outside, "host.sock"), filepath.Join(dir, "run/mysqld/mysqld.sock"))
		},
		"a link of a directory out of the root": func(dir string) error {
			if err := os.MkdirAll(filepath.Join(dir, "run"), 0o755); err != nil {
				return err
			}
			return os.Symlink(filepath.Join(outside, "d"), filepath.Join(dir, "run/mysqld"))
		},
		"a regular file": func(dir string) error {
			if err := os.MkdirAll(filepath.Join(dir, "run/mysqld"), 0o755); err != nil {
				return err
			}
			return os.WriteFile(filepath.Join(dir, "run/mysqld/mysqld.sock"), nil, 0o644)
		},
	} {
		t.Run(name, func(t *testing.T) {
			dir := shortDir(t)
			if err := put(dir); err != nil {
				t.Fatal(err)
			}
			_, err := dialRootSocket(context.Background(), openTestRoot(t, dir))
			if !errors.Is(err, errWPSocket) {
				t.Fatalf("dialRootSocket = %v, want errWPSocket", err)
			}
			if strings.Contains(err.Error(), outside) {
				t.Fatalf("the error names where a link leads: %v", err)
			}
		})
	}
	// Nothing ever reached a socket outside the root. Every dial above has returned, so a connection would
	// already wait in the backlog: 100 ms only bounds Accept, it waits for nothing in flight.
	for _, l := range []*net.UnixListener{host, linked} {
		if err := l.SetDeadline(time.Now().Add(100 * time.Millisecond)); err != nil {
			t.Fatal(err)
		}
		if c, err := l.Accept(); err == nil {
			c.Close()
			t.Fatal("a connection reached a socket outside the root")
		}
	}
}
