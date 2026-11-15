// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

// The tests of moodle_checks: runuser and the exit codes of a real process are Linux's.

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"testing"
	"time"

	"adminhelper-agent/internal/execx"
)

// exitWith is the error of a process that exited with code.
func exitWith(t *testing.T, code int) error {
	t.Helper()
	err := exec.Command("sh", "-c", fmt.Sprintf("exit %d", code)).Run()
	var exitErr *exec.ExitError
	if !errors.As(err, &exitErr) || exitErr.ExitCode() != code {
		t.Fatalf("sh exit %d gave %v", code, err)
	}
	return err
}

// moodleRoot is the document root of a Moodle in a directory of the test, its files the test user's,
// and the user the web server runs as stands for uid and gid (the test user's when they are -1; as
// root, a user of its own, since uid 0 never runs). Its config.php names the dataroot moodledata
// beside it (moodleData), the user's, with a cache configuration in muc/.
func moodleRoot(t *testing.T, uid, gid int) string {
	t.Helper()
	root := filepath.Join(t.TempDir(), "moodle")
	data := moodleData(root)
	for _, dir := range []string{"admin/cli", "lib"} {
		if err := os.MkdirAll(filepath.Join(root, dir), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.MkdirAll(filepath.Join(data, "muc"), 0o750); err != nil {
		t.Fatal(err)
	}
	for _, f := range []string{"admin/cli/checks.php", "lib/moodlelib.php", "../moodledata/muc/config.php"} {
		if err := os.WriteFile(filepath.Join(root, f), []byte("<?php\n"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	moodleConfig(t, root, "$CFG->dataroot  = '"+data+"';\n")
	// A umask that lets the group write (t.TempDir too) would else give each file a group no rule takes.
	for _, p := range []string{filepath.Dir(root), root, root + "/admin", root + "/admin/cli", root + "/lib", data, data + "/muc"} {
		chmod(t, p, 0o755)
	}
	for _, p := range []string{root + "/admin/cli/checks.php", root + "/lib/moodlelib.php", data + "/muc/config.php"} {
		chmod(t, p, 0o644)
	}
	if uid < 0 {
		uid = os.Getuid()
		if uid == 0 {
			uid = 4242
		}
	}
	if gid < 0 {
		gid = os.Getgid()
	}
	if os.Getuid() == 0 {
		for _, p := range []string{data, filepath.Join(data, "muc"), filepath.Join(data, "muc/config.php")} {
			if err := os.Lchown(p, uid, gid); err != nil {
				t.Fatal(err)
			}
		}
	}
	old := moodleLookup
	moodleLookup = func(name string) (*user.User, error) {
		return &user.User{Username: name, Uid: strconv.Itoa(uid), Gid: strconv.Itoa(gid)}, nil
	}
	t.Cleanup(func() { moodleLookup = old })
	return root
}

// moodleData is the dataroot moodleRoot makes beside root.
func moodleData(root string) string { return filepath.Join(filepath.Dir(root), "moodledata") }

// moodleConfig writes the config.php of the Moodle at root with the lines of text.
func moodleConfig(t *testing.T, root, text string) {
	t.Helper()
	conf := "<?php\nunset($CFG);\nglobal $CFG;\n$CFG = new stdClass();\n" + text +
		"require_once(__DIR__ . '/lib/setup.php');\n"
	if err := os.WriteFile(filepath.Join(root, "config.php"), []byte(conf), 0o640); err != nil {
		t.Fatal(err)
	}
	chmod(t, filepath.Join(root, "config.php"), 0o640)
}

// resolved is path with its links resolved, as the agent runs checks.php.
func resolved(t *testing.T, path string) string {
	t.Helper()
	real, err := filepath.EvalSymlinks(path)
	if err != nil {
		t.Fatal(err)
	}
	return real
}

// moodleVhost is the Moodle at root that nginx serves as lms.example.org on 443 as user.
func moodleVhost(root, user string) Vhost {
	return Vhost{Server: "nginx", Name: "lms.example.org", Port: 443, TLS: true, App: "moodle",
		root: root, user: user}
}

// stubCapped stands in for runCapped as stubTools does for runTool: each call takes the next answer.
func stubCapped(t *testing.T, answers ...answer) *[][]string {
	t.Helper()
	var calls [][]string
	old := runCapped
	runCapped = func(_ context.Context, _ time.Duration, limit int, name string, args ...string) ([]byte, error) {
		calls = append(calls, append([]string{name}, args...))
		checkAllowed(t, name, args)
		if limit != moodleMaxOutput {
			t.Errorf("output bounded at %d, want %d", limit, moodleMaxOutput)
		}
		if len(calls) > len(answers) {
			t.Errorf("call %q past the %d answers", calls[len(calls)-1], len(answers))
			return nil, errors.New("no answer")
		}
		a := answers[len(calls)-1]
		return []byte(a.out), a.err
	}
	t.Cleanup(func() { runCapped = old })
	return &calls
}

var moodleTarget = Target{Kind: kindVhost, Name: "lms.example.org", PortHint: 443}

// The output of checks.php (admin/cli/checks.php of moodle main): the first line, then the table of
// the checks that are not OK, each with its summary and details on rows of an empty first column. A
// line of the details html_to_text broke has no column, and may hold a '|' of its own.
const moodleCritical = `CRITICAL: Cron (core_cron)
    Status | Check
----------+--------------------------------------------------------------------
  Critical| Cron (core_cron)
          |     The cron has not run for 3 days
          |     Set up cron as the web server's user
see also | the docs
   Warning| Debug messages (core_debugging)
          |     Debugging is on
`

func TestMoodleChecksRunsChecksPHPAsTheWebServersUser(t *testing.T) {
	ctx := context.Background()
	cases := []struct {
		name, out string
		code      int
		want      map[string]any
	}{
		{"all OK", "OK: All 'status' checks OK\n", 0, map[string]any{"state": "ok", "not_ok": 0}},
		{"a warning", "WARNING: Debug messages (core_debugging)\n    Status | Check\n" +
			"----------+-----\n   Warning| Debug messages (core_debugging)\n          |     Debugging is on\n", 1,
			map[string]any{"state": "warning", "not_ok": 1}},
		{"critical and a warning", moodleCritical, 2, map[string]any{"state": "critical", "not_ok": 2}},
		{"a notice of PHP first", "PHP Deprecated:  x in y on line 3\n" + moodleCritical, 2,
			map[string]any{"state": "critical", "not_ok": 2}},
		{"unknown", "UNKNOWN: Antivirus (core_antivirus)\n", 3, map[string]any{"state": "unknown", "not_ok": 0}},
		{"coloured", "WARNING: x (y)\n    Status | Check\n----------+--\n\x1b[33mWarning\x1b[0m| x (y)\n", 1,
			map[string]any{"state": "warning", "not_ok": 1}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			root := moodleRoot(t, -1, -1)
			stubVhostCache(t, time.Now(), []Vhost{moodleVhost(root, "www-data")}, nil)
			var err error
			if c.code != 0 {
				err = exitWith(t, c.code)
			}
			calls := stubCapped(t, answer{out: c.out, err: err})
			got, gerr := moodleChecks(ctx, moodleTarget)
			if gerr != nil || fmt.Sprint(got) != fmt.Sprint(c.want) {
				t.Errorf("moodle_checks = %v, %v\nwant %v", got, gerr, c.want)
			}
			want := []string{"runuser", "-u", "www-data", "--", "php", resolved(t, root) + "/admin/cli/checks.php"}
			if len(*calls) != 1 || !slices.Equal((*calls)[0], want) {
				t.Errorf("calls %q, want %q", *calls, want)
			}
		})
	}
}

func TestMoodleChecksNeedsAMoodleAndAUserOtherThanRoot(t *testing.T) {
	ctx := context.Background()
	root := moodleRoot(t, -1, -1)
	other := moodleVhost(root, "www-data")
	other.App = "wordpress"
	cases := []struct {
		name string
		list []Vhost
		want string
	}{
		{"no vhost of the name", []Vhost{{Name: "web.example.org", Port: 443, App: "moodle", user: "www-data"}},
			"no web server of this host serves"},
		{"another app", []Vhost{other}, "serves no Moodle"},
		{"no user", []Vhost{moodleVhost(root, "")}, "no user other than root"},
		{"root", []Vhost{moodleVhost(root, "root")}, "no user other than root"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			stubVhostCache(t, time.Now(), c.list, nil)
			calls := stubCapped(t)
			_, err := moodleChecks(ctx, moodleTarget)
			if err == nil || !strings.Contains(err.Error(), c.want) {
				t.Errorf("moodle_checks: %v, want %q", err, c.want)
			}
			if len(*calls) != 0 {
				t.Errorf("ran %q", *calls)
			}
		})
	}
}

func TestMoodleChecksTakesOnlyAnAnswerOfChecksPHP(t *testing.T) {
	ctx := context.Background()
	cases := map[string]answer{
		"runuser knows no such user": {err: exitWith(t, 1)},
		"a fatal error of PHP":       {out: "PHP Fatal error:  x\n", err: exitWith(t, 255)},
		"another script":             {out: "Usage: …\n"},
		"an exit it does not give":   {out: "WARNING: x (y)\n", err: exitWith(t, 4)},
		"php not installed":          {err: exitWith(t, 127)},
		"no runuser":                 {err: notInstalled("runuser")},
		"hangs":                      {err: context.DeadlineExceeded},
		"writes without end":         {err: execx.ErrOutputLimit},
	}
	for name, a := range cases {
		t.Run(name, func(t *testing.T) {
			stubVhostCache(t, time.Now(), []Vhost{moodleVhost(moodleRoot(t, -1, -1), "www-data")}, nil)
			stubCapped(t, a)
			got, err := moodleChecks(ctx, moodleTarget)
			if err == nil {
				t.Errorf("moodle_checks = %v, want an error", got)
			}
		})
	}
}

func TestMoodleChecksSaysNoTextOfTheSite(t *testing.T) {
	stubVhostCache(t, time.Now(), []Vhost{moodleVhost(moodleRoot(t, -1, -1), "www-data")}, nil)
	stubCapped(t, answer{out: "PHP Fatal error: the password s3cret\n", err: exitWith(t, 255)})
	_, err := moodleChecks(context.Background(), moodleTarget)
	if err == nil || strings.Contains(err.Error(), "s3cret") || !strings.Contains(err.Error(), "exit 255") {
		t.Errorf("moodle_checks: %v, want the exit code alone", err)
	}
}

// The code checks.php would run must be root's and the web server user's alone: else, where each site
// has a PHP user of its own, the agent would start that user's code as the web server's.
func TestMoodleChecksRunsOnlyCodeOfRootAndTheWebServersUser(t *testing.T) {
	ctx := context.Background()
	// Files of root are fine for any user: as root, the test's own files are.
	other, asRoot := os.Getuid()+4242, os.Getuid() == 0
	cases := []struct {
		name     string
		uid, gid int
		change   func(t *testing.T, root string)
		runs     bool
	}{
		{"the user's own", -1, -1, func(*testing.T, string) {}, true},
		{"another user's", other, -1, func(*testing.T, string) {}, asRoot},
		{"a group of the user may write", -1, -1, func(t *testing.T, root string) {
			chmod(t, filepath.Join(root, "admin/cli/checks.php"), 0o664)
		}, os.Getgid() == 0},
		{"another group may write", -1, os.Getgid() + 4242, func(t *testing.T, root string) {
			chmod(t, filepath.Join(root, "config.php"), 0o664)
		}, os.Getgid() == 0},
		{"anyone may write a file", -1, -1, func(t *testing.T, root string) {
			chmod(t, filepath.Join(root, "lib/moodlelib.php"), 0o646)
		}, false},
		{"anyone may write the root", -1, -1, func(t *testing.T, root string) { chmod(t, root, 0o757) }, false},
		{"anyone may write the root, sticky", -1, -1, func(t *testing.T, root string) {
			chmod(t, root, 0o757|os.ModeSticky)
		}, true},
		{"a file missing", -1, -1, func(t *testing.T, root string) {
			if err := os.Remove(filepath.Join(root, "lib/moodlelib.php")); err != nil {
				t.Fatal(err)
			}
		}, false},
		{"a file is a link", -1, -1, func(t *testing.T, root string) {
			lib := filepath.Join(root, "lib/moodlelib.php")
			if err := os.Rename(lib, lib+".real"); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(lib+".real", lib); err != nil {
				t.Fatal(err)
			}
		}, false},
		{"no cache configuration yet", -1, -1, func(t *testing.T, root string) {
			if err := os.RemoveAll(filepath.Join(moodleData(root), "muc")); err != nil {
				t.Fatal(err)
			}
		}, true},
		{"anyone may write the cache configuration", -1, -1, func(t *testing.T, root string) {
			chmod(t, filepath.Join(moodleData(root), "muc"), 0o777)
		}, false},
		{"the cache configuration is a link", -1, -1, func(t *testing.T, root string) {
			muc := filepath.Join(moodleData(root), "muc/config.php")
			if err := os.Remove(muc); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(filepath.Join(root, "lib/moodlelib.php"), muc); err != nil {
				t.Fatal(err)
			}
		}, false},
		{"a dataroot of another user", -1, -1, func(t *testing.T, root string) {
			// /usr is root's, as the dataroot of a site whose PHP runs as a user of its own is that user's.
			moodleConfig(t, root, "$CFG->dataroot = '/usr';\n")
		}, false},
		{"a dataroot of a variable", -1, -1, func(t *testing.T, root string) {
			moodleConfig(t, root, "$CFG->dataroot = $data;\n")
		}, false},
		{"a dataroot set twice", -1, -1, func(t *testing.T, root string) {
			moodleConfig(t, root, "$CFG->dataroot = '"+moodleData(root)+"';\n$CFG->dataroot = '/srv/x';\n")
		}, false},
		{"a relative dataroot", -1, -1, func(t *testing.T, root string) {
			moodleConfig(t, root, "$CFG->dataroot = 'moodledata';\n")
		}, false},
		{"caches moved out", -1, -1, func(t *testing.T, root string) {
			moodleConfig(t, root, "$CFG->dataroot = '"+moodleData(root)+"';\n$CFG->localcachedir = '/srv/c';\n")
		}, false},
		{"no config.php", -1, -1, func(t *testing.T, root string) {
			if err := os.Remove(filepath.Join(root, "config.php")); err != nil {
				t.Fatal(err)
			}
		}, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			root := moodleRoot(t, c.uid, c.gid)
			c.change(t, root)
			stubVhostCache(t, time.Now(), []Vhost{moodleVhost(root, "www-data")}, nil)
			var calls *[][]string
			if c.runs {
				calls = stubCapped(t, answer{out: "OK: All 'status' checks OK\n"})
			} else {
				calls = stubCapped(t)
			}
			_, err := moodleChecks(ctx, moodleTarget)
			if c.runs && (err != nil || len(*calls) != 1) {
				t.Errorf("moodle_checks: %v, calls %q, want one run", err, *calls)
			}
			if !c.runs && (!errors.Is(err, ErrUnsupported) || len(*calls) != 0) {
				t.Errorf("moodle_checks: %v, calls %q, want ErrUnsupported and no run", err, *calls)
			}
		})
	}
}

func TestMoodleChecksNeverRunsAsAUserOfUid0(t *testing.T) {
	root := moodleRoot(t, 0, -1)
	if _, err := moodleOwned(root, "toor"); !errors.Is(err, ErrUnsupported) || !strings.Contains(err.Error(), "is root") {
		t.Errorf("a user of uid 0: %v, want ErrUnsupported as root", err)
	}
}

func TestMoodleChecksRunsTheScriptOnThePathItChecked(t *testing.T) {
	root := moodleRoot(t, -1, -1)
	link := filepath.Join(t.TempDir(), "current")
	if err := os.Symlink(root, link); err != nil {
		t.Fatal(err)
	}
	stubVhostCache(t, time.Now(), []Vhost{moodleVhost(link, "www-data")}, nil)
	calls := stubCapped(t, answer{out: "OK: All 'status' checks OK\n"})
	if _, err := moodleChecks(context.Background(), moodleTarget); err != nil {
		t.Fatalf("a link to the user's own tree: %v", err)
	}
	want := []string{"runuser", "-u", "www-data", "--", "php", resolved(t, root) + "/admin/cli/checks.php"}
	if len(*calls) != 1 || !slices.Equal((*calls)[0], want) {
		t.Errorf("calls %q, want %q: the link resolved", *calls, want)
	}
	moodleRoot(t, os.Getuid()+4242, -1)
	if _, err := moodleOwned(link, "www-data"); os.Getuid() != 0 && !errors.Is(err, ErrUnsupported) {
		t.Errorf("a link to a tree of another user: %v, want ErrUnsupported", err)
	}
}

// chmod sets mode on path, the sticky bit too.
func chmod(t *testing.T, path string, mode os.FileMode) {
	t.Helper()
	if err := os.Chmod(path, mode); err != nil {
		t.Fatal(err)
	}
}

func TestTheUserOfTheWebServerStaysWithItsVhosts(t *testing.T) {
	dump := "# configuration file /etc/nginx/nginx.conf:\nuser www-data;\nevents { }\nhttp {\n" +
		"server { listen 443 ssl; server_name lms.example.org; root /var/www/moodle; }\n}\n"
	if got := nginxVhosts([]byte(dump)); len(got) != 1 || got[0].user != "www-data" {
		t.Errorf("nginx vhosts %+v, want user www-data", got)
	}
	if got := nginxVhosts([]byte(strings.Replace(dump, "user www-data;", "", 1))); len(got) != 1 || got[0].user != "" {
		t.Errorf("nginx vhosts %+v without a user directive, want none", got)
	}
	text := "<VirtualHost *:80>\nServerName lms.example.org\nDocumentRoot /var/www/moodle\n</VirtualHost>\n"
	out := writeApacheConf(t, text, "*:80                   lms.example.org (CONF:1)\n"+
		"User: name=\"apache\" id=48\nGroup: name=\"apache\" id=48\n")
	got, err := apacheVhosts([]byte(out))
	if err != nil || len(got) != 1 || got[0].user != "apache" {
		t.Errorf("apache vhosts %+v, %v, want user apache", got, err)
	}
}
