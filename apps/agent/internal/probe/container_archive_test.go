// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"archive/tar"
	"bytes"
	"context"
	"errors"
	"io"
	"os/exec"
	"slices"
	"strings"
	"testing"
	"time"
)

// tarEntry is one entry of an archive a test builds the way docker cp sends it: the base name of the
// path asked for, its children below it.
type tarEntry struct {
	name, body, link string
	dir              bool
}

func buildTar(t *testing.T, entries ...tarEntry) []byte {
	t.Helper()
	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)
	for _, e := range entries {
		h := &tar.Header{Name: e.name, Mode: 0o644, Typeflag: tar.TypeReg, Size: int64(len(e.body))}
		switch {
		case e.dir:
			h = &tar.Header{Name: e.name + "/", Mode: 0o755, Typeflag: tar.TypeDir}
		case e.link != "":
			h = &tar.Header{Name: e.name, Mode: 0o777, Typeflag: tar.TypeSymlink, Linkname: e.link}
		}
		if err := tw.WriteHeader(h); err != nil {
			t.Fatal(err)
		}
		if h.Typeflag == tar.TypeReg {
			if _, err := tw.Write([]byte(e.body)); err != nil {
				t.Fatal(err)
			}
		}
	}
	if err := tw.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

// fakeArchives stands in for docker cp: each path of the container its archive; a path without one
// fails like docker cp on a path that is not there. It records the calls and how much of each
// archive's entries the reader read.
type fakeArchives struct {
	archives map[string][]byte
	calls    [][]string
}

func (f *fakeArchives) run(_ context.Context, _ time.Duration, read func(io.Reader) error, name string, args ...string) error {
	f.calls = append(f.calls, append([]string{name}, args...))
	_, p, _ := strings.Cut(args[len(args)-2], ":")
	data, ok := f.archives[p]
	if !ok {
		return &exec.ExitError{}
	}
	return read(bytes.NewReader(data))
}

func (f *fakeArchives) asked() []string {
	var ps []string
	for _, c := range f.calls {
		_, p, _ := strings.Cut(c[len(c)-2], ":")
		ps = append(ps, p)
	}
	return ps
}

func useArchives(t *testing.T, f *fakeArchives) {
	t.Helper()
	old := runToolReader
	runToolReader = f.run
	t.Cleanup(func() { runToolReader = old })
}

const ctrID = "0123456789ab"

func TestContainerFileReadsAFileOverDockerCp(t *testing.T) {
	f := &fakeArchives{archives: map[string][]byte{
		"/etc/nginx/nginx.conf": buildTar(t, tarEntry{name: "nginx.conf", body: "events {}\n"}),
	}}
	useArchives(t, f)
	got, err := newContainerFS(ctrID).file(context.Background(), "/etc/nginx/nginx.conf", 1<<20)
	if err != nil || string(got) != "events {}\n" {
		t.Fatalf("file = %q, %v", got, err)
	}
	want := []string{"docker", "cp", "--", ctrID + ":/etc/nginx/nginx.conf", "-"}
	if len(f.calls) != 1 || !slices.Equal(f.calls[0], want) {
		t.Fatalf("calls = %q, want %q", f.calls, want)
	}
}

func TestContainerFileFollowsLinksItself(t *testing.T) {
	f := &fakeArchives{archives: map[string][]byte{
		"/etc/nginx/nginx.conf":       buildTar(t, tarEntry{name: "nginx.conf", link: "../conf/main.conf"}),
		"/etc/conf/main.conf":         buildTar(t, tarEntry{name: "main.conf", link: "/srv/real.conf"}),
		"/srv/real.conf":              buildTar(t, tarEntry{name: "real.conf", body: "http {}\n"}),
		"/etc/nginx/sites/loop.conf":  buildTar(t, tarEntry{name: "loop.conf", link: "loop.conf"}),
		"/etc/nginx/sites/dir.conf":   buildTar(t, tarEntry{name: "dir.conf", link: "/etc"}),
		"/etc":                        buildTar(t, tarEntry{name: "etc", dir: true}),
		"/etc/nginx/sites/gone.conf":  buildTar(t, tarEntry{name: "gone.conf", link: "/nowhere.conf"}),
		"/etc/nginx/sites/large.conf": buildTar(t, tarEntry{name: "large.conf", body: strings.Repeat("x", 64)}),
	}}
	useArchives(t, f)
	ctx := context.Background()
	fs := newContainerFS(ctrID)
	if got, err := fs.file(ctx, "/etc/nginx/nginx.conf", 1<<20); err != nil || string(got) != "http {}\n" {
		t.Fatalf("file through two links = %q, %v", got, err)
	}
	for p, want := range map[string]error{
		"/etc/nginx/sites/loop.conf":  errContainerLinks,
		"/etc/nginx/sites/dir.conf":   errContainerNoFile,
		"/etc/nginx/sites/gone.conf":  errNotInContainer,
		"/etc/nginx/sites/large.conf": errContainerConfLarge,
		"/etc/nginx/../shadow":        errNotInContainer,
	} {
		if _, err := fs.file(ctx, p, 32); !errors.Is(err, want) {
			t.Errorf("file(%s) err = %v, want %v", p, err, want)
		}
	}
	if slices.Contains(f.asked(), "/etc/shadow") || slices.Contains(f.asked(), "/etc/nginx/../shadow") {
		t.Fatalf("asked docker cp for a dotted path: %q", f.asked())
	}
}

func TestContainerGlobTakesTheMatchingFilesOfTheDirectoryOnly(t *testing.T) {
	f := &fakeArchives{archives: map[string][]byte{
		"/etc/nginx/conf.d": buildTar(t,
			tarEntry{name: "conf.d", dir: true},
			tarEntry{name: "conf.d/b.conf", body: "server { listen 80; }\n"},
			tarEntry{name: "conf.d/a.conf", body: "server { listen 443; }\n"},
			tarEntry{name: "conf.d/notes.txt", body: "unread"},
			// A wildcard of nginx and Apache never takes a name with a leading dot.
			tarEntry{name: "conf.d/.old.conf", body: "unread"},
			tarEntry{name: "conf.d/site.key", body: "-----BEGIN PRIVATE KEY-----"},
			tarEntry{name: "conf.d/chain.PEM", body: "-----BEGIN PRIVATE KEY-----"},
			tarEntry{name: "conf.d/sub", dir: true},
			tarEntry{name: "conf.d/sub/deep.conf", body: "unread"},
			tarEntry{name: "conf.d/c.conf", link: "/srv/c.conf"},
			tarEntry{name: "conf.d/k.conf", link: "/srv/tls/site.key"},
			tarEntry{name: "conf.d/hop.conf", link: "/srv/hop.conf"},
			tarEntry{name: "conf.d/dangling.conf", link: "/srv/none.conf"},
		),
		"/srv/c.conf":   buildTar(t, tarEntry{name: "c.conf", body: "server { listen 8080; }\n"}),
		"/srv/hop.conf": buildTar(t, tarEntry{name: "hop.conf", link: "/srv/tls/other.pem"}),
	}}
	useArchives(t, f)
	files, err := newContainerFS(ctrID).glob(context.Background(), "/etc/nginx/conf.d/*.conf", 1<<20)
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, cf := range files {
		names = append(names, cf.name)
		if strings.Contains(string(cf.text), "PRIVATE KEY") || string(cf.text) == "unread" {
			t.Errorf("%s holds text the agent must not read: %q", cf.name, cf.text)
		}
	}
	want := []string{"/etc/nginx/conf.d/a.conf", "/etc/nginx/conf.d/b.conf", "/etc/nginx/conf.d/c.conf"}
	if !slices.Equal(names, want) {
		t.Fatalf("glob = %q, want %q", names, want)
	}
	for _, p := range f.asked() {
		if keyPath(p) {
			t.Errorf("asked docker cp for %s, a path that looks like a key", p)
		}
	}
}

func TestContainerGlobFollowsALinkedDirectoryAndSkipsKeys(t *testing.T) {
	f := &fakeArchives{archives: map[string][]byte{
		"/etc/nginx/sites-enabled": buildTar(t, tarEntry{name: "sites-enabled", link: "/data/sites"}),
		"/data/sites": buildTar(t,
			tarEntry{name: "sites", dir: true},
			tarEntry{name: "sites/app", body: "server {}\n"},
			// "*" matches a key too: the name alone keeps it unread.
			tarEntry{name: "sites/site.key", body: "-----BEGIN PRIVATE KEY-----"},
			tarEntry{name: "sites/Chain.Pem", body: "-----BEGIN PRIVATE KEY-----"},
			tarEntry{name: "sites/tls.conf", link: "/data/tls/site.key"},
		),
	}}
	useArchives(t, f)
	files, err := newContainerFS(ctrID).glob(context.Background(), "/etc/nginx/sites-enabled/*", 1<<20)
	if err != nil || len(files) != 1 || files[0].name != "/etc/nginx/sites-enabled/app" {
		t.Fatalf("glob = %+v, %v", files, err)
	}
	for _, p := range f.asked() {
		if keyPath(p) {
			t.Errorf("asked docker cp for %s, a path that looks like a key", p)
		}
	}
}

func TestContainerGlobOfAMissingDirectoryIsNoFile(t *testing.T) {
	useArchives(t, &fakeArchives{})
	fs := newContainerFS(ctrID)
	files, err := fs.glob(context.Background(), "/etc/nginx/conf.d/*.conf", 1<<20)
	if err != nil || len(files) != 0 {
		t.Fatalf("glob = %+v, %v", files, err)
	}
	if _, err := fs.glob(context.Background(), "/etc/*/conf.d/*.conf", 1<<20); !errors.Is(err, errNotInContainer) {
		t.Fatalf("glob with a pattern directory: err = %v", err)
	}
}

func TestContainerArchivesStopAtTheBudgetOfTheContainer(t *testing.T) {
	big := strings.Repeat("x", 1<<20)
	f := &fakeArchives{archives: map[string][]byte{}}
	var entries []tarEntry
	entries = append(entries, tarEntry{name: "conf.d", dir: true})
	for _, n := range []string{"a", "b", "c", "d", "e"} {
		entries = append(entries, tarEntry{name: "conf.d/" + n + ".conf", body: big})
	}
	f.archives["/etc/nginx/conf.d"] = buildTar(t, entries...)
	useArchives(t, f)
	_, err := newContainerFS(ctrID).glob(context.Background(), "/etc/nginx/conf.d/*.conf", 2<<20)
	if !errors.Is(err, errContainerConfLarge) {
		t.Fatalf("five MiB against a budget of four: err = %v", err)
	}
	// The budget holds for every archive of the container: a second read after the first used it up
	// fails too, a fresh container reads again.
	f.archives["/etc/nginx/nginx.conf"] = buildTar(t, tarEntry{name: "nginx.conf", body: "events {}\n"})
	fs := newContainerFS(ctrID)
	fs.left = 10
	if _, err := fs.file(context.Background(), "/etc/nginx/nginx.conf", 1<<20); !errors.Is(err, errContainerConfLarge) {
		t.Fatalf("after the budget: err = %v", err)
	}
	if _, err := newContainerFS(ctrID).file(context.Background(), "/etc/nginx/nginx.conf", 1<<20); err != nil {
		t.Fatal(err)
	}
}
