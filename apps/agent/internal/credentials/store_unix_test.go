// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

//go:build linux || freebsd

package credentials

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSetWritesAFileOfTheAgentsAccountAlone(t *testing.T) {
	path := storePath(t)
	if err := Set(context.Background(), path, "db", "secret"); err != nil {
		t.Fatal(err)
	}
	for p, want := range map[string]os.FileMode{path: 0o600, filepath.Dir(path): 0o700 | os.ModeDir} {
		st, err := os.Stat(p)
		if err != nil {
			t.Fatal(err)
		}
		if st.Mode() != want {
			t.Errorf("%s: mode %v; want %v", p, st.Mode(), want)
		}
	}
}

func TestLoadUsesNoFileOthersCanRead(t *testing.T) {
	for _, mode := range []os.FileMode{0o640, 0o604, 0o620, 0o602, 0o601} {
		path := storePath(t)
		if err := Set(context.Background(), path, "db", "secret"); err != nil {
			t.Fatal(err)
		}
		if err := os.Chmod(path, mode); err != nil {
			t.Fatal(err)
		}
		if creds, err := Load(path); err == nil || !strings.Contains(err.Error(), "chmod 600") {
			t.Errorf("mode %#o: Load = %v, %v; want an error that names chmod 600", mode, creds, err)
		}
		// A set does not paper over it: the agent did not write the file in that state.
		if err := Set(context.Background(), path, "db", "other"); err == nil {
			t.Errorf("mode %#o: Set = nil; want the error of Load", mode)
		}
	}
}

func TestLoadFollowsNoLink(t *testing.T) {
	target := storePath(t)
	if err := Set(context.Background(), target, "db", "secret"); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(t.TempDir(), "credentials.json")
	if err := os.Symlink(target, link); err != nil {
		t.Fatal(err)
	}
	if creds, err := Load(link); err == nil {
		t.Fatalf("Load through a link = %v; want an error", creds)
	}
}

func TestLoadUsesNoDirectory(t *testing.T) {
	path := storePath(t)
	if err := os.MkdirAll(path, 0o700); err != nil {
		t.Fatal(err)
	}
	if creds, err := Load(path); err == nil || !strings.Contains(err.Error(), "no regular file") {
		t.Fatalf("Load of a directory = %v, %v; want an error that it is no regular file", creds, err)
	}
}

func TestLoadUsesNoFileBeyondItsSize(t *testing.T) {
	path := storePath(t)
	if err := Set(context.Background(), path, "db", "secret"); err != nil {
		t.Fatal(err)
	}
	writeRaw(t, path, []byte(`{"version":1,"credentials":{}}`+strings.Repeat(" ", maxFileBytes)))
	if creds, err := Load(path); err == nil {
		t.Fatalf("Load of an oversized file = %v; want an error", creds)
	}
}

func TestLoadUsesNoFileOfAnotherAccount(t *testing.T) {
	path := storePath(t)
	if err := Set(context.Background(), path, "db", "secret"); err != nil {
		t.Fatal(err)
	}
	own := os.Geteuid()
	euid = func() int { return own + 1 }
	t.Cleanup(func() { euid = os.Geteuid })
	if creds, err := Load(path); err == nil || !strings.Contains(err.Error(), "not to the agent's account") {
		t.Fatalf("Load of a file of another account = %v, %v; want an error", creds, err)
	}
}
