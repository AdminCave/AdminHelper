// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package selfupdate

import (
	"bytes"
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

// repo serves testdata/ as /windows/, with optional overrides per file.
func repo(t *testing.T, override map[string][]byte) Options {
	t.Helper()
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		name, ok := bytes.CutPrefix([]byte(r.URL.Path), []byte("/windows/"))
		if !ok {
			http.NotFound(w, r)
			return
		}
		if b, ok := override[string(name)]; ok {
			_, _ = w.Write(b)
			return
		}
		b, err := os.ReadFile(filepath.Join("testdata", string(name)))
		if err != nil {
			http.NotFound(w, r)
			return
		}
		_, _ = w.Write(b)
	}))
	t.Cleanup(srv.Close)
	return Options{
		RepoURL:   srv.URL + "/windows/",
		Client:    srv.Client(),
		PublicKey: testKey(t),
		Current:   "v1.2.2",
		StageDir:  filepath.Join(t.TempDir(), "stage"),
	}
}

func TestFetchStagesVerifiedRelease(t *testing.T) {
	o := repo(t, nil)
	v, err := Fetch(context.Background(), o)
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	if v != "1.2.3" {
		t.Fatalf("version = %q", v)
	}
	for _, name := range []string{AgentFile, FrpcFile} {
		got, err := os.ReadFile(filepath.Join(o.StageDir, name))
		if err != nil || !bytes.Equal(got, readTestdata(t, name)) {
			t.Fatalf("%s not staged correctly: %v", name, err)
		}
	}
}

func TestFetchUpToDate(t *testing.T) {
	for name, mod := range map[string]func(*Options){
		"same version":    func(o *Options) { o.Current = "v1.2.3" },
		"newer running":   func(o *Options) { o.Current = "1.3.0" },
		"dev build":       func(o *Options) { o.Current = "dev" },
		"describe build":  func(o *Options) { o.Current = "v1.2.2-3-gabcdef" },
		"failed before":   func(o *Options) { o.Skip = "1.2.3" },
		"failed before v": func(o *Options) { o.Skip = "v1.2.3" },
	} {
		t.Run(name, func(t *testing.T) {
			o := repo(t, nil)
			mod(&o)
			if _, err := Fetch(context.Background(), o); !errors.Is(err, ErrUpToDate) {
				t.Fatalf("err = %v, want ErrUpToDate", err)
			}
			if _, err := os.Stat(o.StageDir); !os.IsNotExist(err) {
				t.Fatal("stage dir created without an update")
			}
		})
	}
}

func TestFetchRejects(t *testing.T) {
	for name, override := range map[string]map[string][]byte{
		"tampered agent":   {AgentFile: []byte("evil\n")},
		"tampered frpc":    {FrpcFile: []byte("evil\n")},
		"tampered VERSION": {VersionFile: []byte("9.9.9\n")},
		"comment of other version": {
			"SHA256SUMS.minisig": readTestdata(t, "SHA256SUMS.othercomment.minisig"),
		},
		"unsigned sums":  {"SHA256SUMS": append(readTestdata(t, "SHA256SUMS"), '\n', 'x')},
		"wrong key":      {"SHA256SUMS.minisig": readTestdata(t, "SHA256SUMS.wrongkey.minisig")},
		"oversized file": {"SHA256SUMS": bytes.Repeat([]byte("a"), maxSmallFile+1)},
	} {
		t.Run(name, func(t *testing.T) {
			o := repo(t, override)
			if _, err := Fetch(context.Background(), o); err == nil || errors.Is(err, ErrUpToDate) {
				t.Fatalf("err = %v, want a rejection", err)
			}
			if _, err := os.Stat(o.StageDir); !os.IsNotExist(err) {
				t.Fatal("stage dir left behind after a rejection")
			}
		})
	}
}

func TestFetchReplacesOldStage(t *testing.T) {
	o := repo(t, nil)
	if err := os.MkdirAll(o.StageDir, 0o700); err != nil {
		t.Fatal(err)
	}
	stale := filepath.Join(o.StageDir, "stale")
	if err := os.WriteFile(stale, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Fetch(context.Background(), o); err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	if _, err := os.Stat(stale); !os.IsNotExist(err) {
		t.Fatal("stale file survived in the stage")
	}
}

func TestFetchMissingSignature(t *testing.T) {
	o := repo(t, nil)
	o.RepoURL += "missing/"
	if _, err := Fetch(context.Background(), o); err == nil {
		t.Fatal("Fetch succeeded without files")
	}
}

func TestParseSums(t *testing.T) {
	good := readTestdata(t, "SHA256SUMS")
	if _, err := parseSums(good); err != nil {
		t.Fatalf("parseSums: %v", err)
	}
	h := "0000000000000000000000000000000000000000000000000000000000000000"
	for name, in := range map[string]string{
		"extra file":   string(good) + h + "  other.exe\n",
		"duplicate":    string(good) + h + "  frpc.exe\n",
		"missing":      h + "  VERSION\n" + h + "  frpc.exe\n",
		"short hash":   "abc  VERSION\n",
		"one space":    h + " VERSION\n",
		"path in name": h + "  VERSION\n" + h + "  frpc.exe\n" + h + "  ../adminhelper-agent.exe\n",
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := parseSums([]byte(in)); err == nil {
				t.Fatal("parseSums accepted it")
			}
		})
	}
}

func TestNewer(t *testing.T) {
	for _, c := range []struct {
		cand, cur string
		want      bool
	}{
		{"1.2.3", "v1.2.2", true},
		{"1.10.0", "1.9.9", true},
		{"2.0.0", "v1.99.99", true},
		{"1.2.3", "1.2.3", false},
		{"1.2.2", "1.2.3", false},
		{"1.2.3", "dev", false},
		{"1.2.3-beta", "1.2.2", false},
		{"01.2.3", "1.2.2", false},
		{"+1.2.3", "1.2.2", false},
		{"1.2", "1.1.0", false},
	} {
		if got := Newer(c.cand, c.cur); got != c.want {
			t.Errorf("Newer(%q, %q) = %v, want %v", c.cand, c.cur, got, c.want)
		}
	}
}

func TestFetchSkipsOnlyTheFailedVersion(t *testing.T) {
	o := repo(t, nil)
	o.Skip = "1.2.2"
	if v, err := Fetch(context.Background(), o); err != nil || v != "1.2.3" {
		t.Fatalf("Fetch = %q, %v; want 1.2.3 staged", v, err)
	}
}

func TestRepoURL(t *testing.T) {
	for in, want := range map[string]string{
		"https://adminhelper.example.org":       "https://adminhelper.example.org:8445/windows/",
		"https://192.0.2.10:443/api":            "https://192.0.2.10:8445/windows/",
		"https://[2001:db8::1]":                 "https://[2001:db8::1]:8445/windows/",
		"http://adminhelper.example.org:8080/x": "https://adminhelper.example.org:8445/windows/",
	} {
		got, err := RepoURL(in)
		if err != nil || got != want {
			t.Errorf("RepoURL(%q) = %q, %v; want %q", in, got, err, want)
		}
	}
	if _, err := RepoURL("::"); err == nil {
		t.Error("RepoURL accepted garbage")
	}
}
