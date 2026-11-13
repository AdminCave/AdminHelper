// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

func stubWPVersionFile(t *testing.T, name string) {
	t.Helper()
	old := wpVersionFile
	wpVersionFile = name
	t.Cleanup(func() { wpVersionFile = old })
}

// viewWithin runs the view on the container web and fails the test if it does not return within 30 s.
func viewWithin(t *testing.T) (map[string]any, error) {
	t.Helper()
	type result struct {
		values map[string]any
		err    error
	}
	done := make(chan result, 1)
	go func() {
		values, err := wordpressVersion(context.Background(), wpTarget())
		done <- result{values, err}
	}()
	select {
	case r := <-done:
		return r.values, r.err
	case <-time.After(30 * time.Second):
		t.Fatal("the view waits")
		return nil, nil
	}
}

// A link at version.php is never followed, wherever it leads, and the error does not say where; a
// link to a directory on the way is followed while it stays in the root of the container.
func TestTheWordPressViewFollowsNoLinkOutOfTheContainer(t *testing.T) {
	outside := filepath.Join(t.TempDir(), "elsewhere")
	writeWPFile(t, outside, versionPHP("$wp_version = '6.8.12';"))
	outsideFile := filepath.Join(outside, filepath.FromSlash(wpVersionFile))
	outsideDocs := filepath.Join(outside, "var/www/html")
	secrets := []string{"elsewhere", outside, "usr/src", "6.8"}
	link := func(t *testing.T, root, at, to string) {
		t.Helper()
		path := filepath.Join(root, filepath.FromSlash(at))
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink(to, path); err != nil {
			t.Fatal(err)
		}
	}
	inRoot := func(t *testing.T) string {
		root, _ := wpContainer(t, "")
		writeWPFile(t, filepath.Join(root, "usr/src/wordpress"), versionPHP("$wp_version = '6.8.12';"))
		return root
	}
	for name, to := range map[string]string{
		"absolute":    outsideFile,
		"relative":    strings.Repeat("../", 12) + strings.TrimPrefix(outsideFile, "/"),
		"in the root": "../../../../usr/src/wordpress/var/www/html/wp-includes/version.php",
	} {
		t.Run("at version.php, "+name, func(t *testing.T) {
			link(t, inRoot(t), wpVersionFile, to)
			values, err := viewWithin(t)
			if err == nil || err.Error() != "container web: /var/www/html/wp-includes/version.php is no regular file" {
				t.Fatalf("values %v, error %v; want the link refused", values, err)
			}
			holdsNoSecret(t, "error", err.Error(), secrets)
		})
	}
	for name, to := range map[string]string{
		"absolute": outsideDocs,
		"relative": strings.Repeat("../", 12) + strings.TrimPrefix(outsideDocs, "/"),
	} {
		t.Run("on the way, "+name, func(t *testing.T) {
			link(t, inRoot(t), "var/www/html", to)
			values, err := viewWithin(t)
			if err == nil || err.Error() != "container web: /var/www/html/wp-includes/version.php cannot be read: path escapes from parent" {
				t.Fatalf("values %v, error %v; want the link refused", values, err)
			}
			holdsNoSecret(t, "error", err.Error(), secrets)
		})
	}
	t.Run("on the way in the root", func(t *testing.T) {
		link(t, inRoot(t), "var/www/html", "../../usr/src/wordpress/var/www/html")
		if got, err := viewWithin(t); err != nil || got["version"] != "6.8.12" {
			t.Errorf("values %v, %v; want version 6.8.12 through the link", got, err)
		}
	})
}

func TestTheWordPressViewNeverWaitsForAFIFO(t *testing.T) {
	root, _ := wpContainer(t, "")
	path := filepath.Join(root, filepath.FromSlash(wpVersionFile))
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Mkfifo(path, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := viewWithin(t); err == nil || err.Error() != "container web: /var/www/html/wp-includes/version.php is no regular file" {
		t.Errorf("a FIFO at version.php = %v, want no regular file", err)
	}
}

// The view reads the file it checked: a FIFO put at version.php since then is never opened.
func TestTheWordPressViewReadsTheFileItChecked(t *testing.T) {
	root, _ := wpContainer(t, versionPHP("$wp_version = '6.8.12';"))
	fifo := filepath.Join(root, "fifo")
	if err := syscall.Mkfifo(fifo, 0o600); err != nil {
		t.Fatal(err)
	}
	swapped := 0
	old := reopenChecked
	reopenChecked = func(p *os.File) (*os.File, error) {
		if err := os.Rename(fifo, filepath.Join(root, filepath.FromSlash(wpVersionFile))); err != nil {
			t.Error(err)
		}
		swapped++
		return old(p)
	}
	t.Cleanup(func() { reopenChecked = old })
	if got, err := viewWithin(t); err != nil || got["version"] != "6.8.12" || swapped != 1 {
		t.Errorf("values %v, %v after %d swaps; want version 6.8.12 of the file checked", got, err, swapped)
	}
}

// A lease on version.php does not hold the view up: its open fails at once.
func TestTheWordPressViewNeverWaitsForALease(t *testing.T) {
	root, _ := wpContainer(t, versionPHP("$wp_version = '6.8.12';"))
	holder, err := os.OpenFile(filepath.Join(root, filepath.FromSlash(wpVersionFile)), os.O_WRONLY, 0)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = holder.Close() })
	if _, err := unix.FcntlInt(holder.Fd(), unix.F_SETLEASE, unix.F_WRLCK); err != nil {
		t.Fatalf("a lease on version.php: %v", err)
	}
	if _, err := viewWithin(t); err == nil ||
		err.Error() != "container web: /var/www/html/wp-includes/version.php cannot be read: resource temporarily unavailable" {
		t.Errorf("a leased version.php = %v, want it unavailable", err)
	}
}

// The view reads through /proc/<pid>/root of the container's process, here this test's own, and never
// a file of the kernel there.
func TestTheWordPressViewReadsThroughTheRootOfTheProcess(t *testing.T) {
	pid := os.Getpid()
	stubTool(t, strings.Replace(inspectJSON(t, "running", "", "bridge"), `"Pid":4242`, `"Pid":`+strconv.Itoa(pid), 1), nil)
	dir := t.TempDir()
	file := filepath.Join(dir, "version.php")
	if err := os.WriteFile(file, []byte(versionPHP("$wp_version = '6.8.12';")), 0o644); err != nil {
		t.Fatal(err)
	}
	stubWPVersionFile(t, strings.TrimPrefix(file, "/"))
	res := Run(context.Background(), appProbe("wordpress_version", &Target{Kind: kindContainer, Name: "web"}, "version"), time.Now(), nil)
	if res.Status != StatusOK || !reflect.DeepEqual(res.Values, map[string]any{"version": "6.8.12"}) {
		t.Errorf("status %s (%s) with %v, want ok with version 6.8.12", res.Status, res.Error, res.Values)
	}

	root, err := openProcRoot(pid)
	if err != nil {
		t.Fatalf("openProcRoot(%d) = %v", pid, err)
	}
	if want := "/proc/" + strconv.Itoa(pid) + "/root"; root.Name() != want {
		t.Errorf("root %s, want %s", root.Name(), want)
	}
	_ = root.Close()

	stubWPVersionFile(t, "proc/self/status")
	if _, err := wordpressVersion(context.Background(), wpTarget()); err == nil ||
		err.Error() != "container web: /proc/self/status lies in a file system of the kernel" {
		t.Errorf("version.php in /proc = %v, want it refused", err)
	}
}

func TestTheWordPressViewReadsTheVersion(t *testing.T) {
	for _, v := range []string{"6.8.12", "6.9", "7.2-beta5-65467", "6.9-RC1", "6.9-RC2-61200", "6.9-alpha-60500", "6.9-beta1"} {
		t.Run(v, func(t *testing.T) {
			_, pids := wpContainer(t, versionPHP("$wp_version = '"+v+"';"))
			got, err := wordpressVersion(context.Background(), wpTarget())
			if err != nil || !reflect.DeepEqual(got, map[string]any{"version": v}) {
				t.Errorf("values %v, %v; want version %s", got, err, v)
			}
			if !slices.Equal(*pids, []int{4242}) {
				t.Errorf("opened the roots of %v, want the root of the container's process 4242", *pids)
			}
		})
	}
	t.Run("line ends of DOS", func(t *testing.T) {
		wpContainer(t, strings.ReplaceAll(versionPHP("$wp_version = '6.8.12';"), "\n", "\r\n"))
		if got, err := wordpressVersion(context.Background(), wpTarget()); err != nil || got["version"] != "6.8.12" {
			t.Errorf("values %v, %v; want version 6.8.12", got, err)
		}
	})
}

func TestTheWordPressViewTakesNothingButAVersion(t *testing.T) {
	cases := map[string]struct{ content, want string }{
		"double quotes":       {versionPHP(`$wp_version = "6.8.12";`), "to no version"},
		"a blank in it":       {versionPHP("$wp_version = '6.8.12 ';"), "to no version"},
		"no blanks around =":  {versionPHP("$wp_version='6.8.12';"), "to no version"},
		"more on the line":    {versionPHP("$wp_version = '6.8.12'; $leak = 'x';"), "to no version"},
		"overlong":            {versionPHP("$wp_version = '6." + strings.Repeat("9", 40) + "';"), "to no version"},
		"an overlong build":   {versionPHP("$wp_version = '6.9-beta1-123456789';"), "to no version"},
		"a suffix of its own": {versionPHP("$wp_version = '6.8.12-custom';"), "to no version"},
		"markup":              {versionPHP("$wp_version = '<script>';"), "to no version"},
		"a call":              {versionPHP("$wp_version = wp_get_version();"), "to no version"},
		"set twice":           {versionPHP("$wp_version = '6.8.12';\n$wp_version = '6.8.11';"), "does not set $wp_version once"},
		"not set":             {versionPHP("// no version here"), "does not set $wp_version once"},
		"larger than 16 KiB": {
			versionPHP("$wp_version = '6.8.12';") + "/*" + strings.Repeat("x", maxWPVersionBytes) + "*/\n",
			"is larger than 16384 bytes",
		},
	}
	secrets := []string{"6.8", "6.9", "leak", "custom", "script", "wp_get_version", "xxxx"}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			wpContainer(t, c.content)
			values, err := wordpressVersion(context.Background(), wpTarget())
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Fatalf("values %v, error %v; want an error naming %q", values, err, c.want)
			}
			holdsNoSecret(t, "error", err.Error(), secrets)
			res := Run(context.Background(), appProbe("wordpress_version", &Target{Kind: kindContainer, Name: "web"}), time.Now(), nil)
			if res.Status != StatusError || len(res.Values) != 0 {
				t.Errorf("status %s with %v, want an error without values", res.Status, res.Values)
			}
			holdsNoSecret(t, "error of Run", res.Error, secrets)
		})
	}
}

func TestTheWordPressViewWithoutItsFile(t *testing.T) {
	root, _ := wpContainer(t, "")
	_, err := wordpressVersion(context.Background(), wpTarget())
	if err == nil || err.Error() != "container web: it holds no /var/www/html/wp-includes/version.php" || errors.Is(err, ErrUnsupported) {
		t.Errorf("no version.php = %v, want a failure naming the file", err)
	}
	if err := os.MkdirAll(filepath.Join(root, filepath.FromSlash(wpVersionFile)), 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := wordpressVersion(context.Background(), wpTarget()); err == nil || !strings.Contains(err.Error(), "is no regular file") {
		t.Errorf("a directory at version.php = %v, want it refused", err)
	}
}

func TestTheWordPressViewRunsThroughRunWithItsTarget(t *testing.T) {
	wpContainer(t, versionPHP("$wp_version = '6.8.12';"))
	res := Run(context.Background(), appProbe("wordpress_version", &Target{Kind: kindContainer, Name: "web"}, "version"), time.Now(), nil)
	if res.Status != StatusOK || !reflect.DeepEqual(res.Values, map[string]any{"version": "6.8.12"}) {
		t.Errorf("status %s (%s) with %v, want ok with version 6.8.12", res.Status, res.Error, res.Values)
	}
	if _, err := appSensor(context.Background(), appProbe("wordpress_version", unitTarget("apache2.service")), ""); !errors.Is(err, ErrInvalid) {
		t.Errorf("a unit as target = %v, want ErrInvalid", err)
	}
}
