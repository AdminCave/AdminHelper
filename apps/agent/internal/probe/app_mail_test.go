// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"slices"
	"strconv"
	"testing"
	"time"
)

var postfixUnit = Target{Kind: kindUnit, Name: "postfix.service"}

// mailRoot makes a temporary directory the root of this host and returns it.
func mailRoot(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	old := hostRoot
	hostRoot = func() (*os.Root, error) { return os.OpenRoot(dir) }
	t.Cleanup(func() { hostRoot = old })
	return dir
}

// queueFiles puts n empty queue files into dir below root.
func queueFiles(t *testing.T, root, dir string, n int) {
	t.Helper()
	full := filepath.Join(root, filepath.FromSlash(dir))
	if err := os.MkdirAll(full, 0o700); err != nil {
		t.Fatal(err)
	}
	for i := range n {
		if err := os.WriteFile(filepath.Join(full, fmt.Sprintf("4bQ7mT%04X", i)), nil, 0o600); err != nil {
			t.Fatal(err)
		}
	}
}

func TestPostfixQueueCountsEachQueueWithItsHashLevels(t *testing.T) {
	root := mailRoot(t)
	queueFiles(t, root, "var/spool/postfix/incoming", 1)
	queueFiles(t, root, "var/spool/postfix/active", 2)
	// deferred is hashed (hash_queue_names): the files sit one level down, in 0-F.
	queueFiles(t, root, "var/spool/postfix/deferred/A", 3)
	queueFiles(t, root, "var/spool/postfix/deferred/7", 1)
	// A directory of a longer name is no hash level, and the queue maildrop is not counted.
	queueFiles(t, root, "var/spool/postfix/deferred/lost+found", 5)
	queueFiles(t, root, "var/spool/postfix/maildrop", 4)
	calls := stubToolsEnv(t, answer{out: "/var/spool/postfix\n"})
	got, err := postfixQueue(context.Background(), postfixUnit)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"incoming": 1, "active": 2, "deferred": 4, "hold": 0, "total": 7, "capped": false}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	if c := (*calls)[0]; !slices.Equal(c.args, []string{"postconf", "-h", "queue_directory"}) {
		t.Fatalf("call %q", c.args)
	}
}

func TestPostfixQueueRefusesWhatIsNoQueueDirectory(t *testing.T) {
	mailRoot(t)
	stubToolsEnv(t, answer{out: "/var/spool/postfix\n"})
	if _, err := postfixQueue(context.Background(), postfixUnit); !errors.Is(err, ErrUnsupported) {
		t.Fatalf("no queues = %v, want unsupported", err)
	}
	for _, out := range []string{"var/spool/postfix\n", "/var/spool/../postfix\n", "\n", "/a\n/b\n"} {
		stubToolsEnv(t, answer{out: out})
		if _, err := postfixQueue(context.Background(), postfixUnit); err == nil || errors.Is(err, ErrUnsupported) {
			t.Errorf("postconf %q = %v, want an error", out, err)
		}
	}
	stubToolsEnv(t, answer{err: exec.ErrNotFound})
	if _, err := postfixQueue(context.Background(), postfixUnit); !errors.Is(err, ErrUnsupported) {
		t.Fatalf("no postconf = %v, want unsupported", err)
	}
}

func TestCountFilesStopsAtItsBudget(t *testing.T) {
	dir := t.TempDir()
	queueFiles(t, dir, "q", 5)
	queueFiles(t, dir, "q/0", 5)
	root, err := os.OpenRoot(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	budget := 7
	n, err := countFiles(root, "q", 0, &budget)
	if err != nil || n != 7 || budget != 0 {
		t.Fatalf("count %d, budget %d, err %v; want 7, 0", n, budget, err)
	}
}

func TestPostfixQueueAgeReadsTheOldestArrival(t *testing.T) {
	root := mailRoot(t)
	queueFiles(t, root, "var/spool/postfix/deferred/3", 2)
	stubNow(t, time.Unix(1_795_000_000, 0))
	// postqueue -j: one object per queue file; sender and recipients are read by nobody.
	out := `{"queue_name": "deferred", "queue_id": "4bQ7mT0pZ1z9", "arrival_time": 1794996400, "message_size": 1830, "forced_expire": false, "sender": "a@example.org", "recipients": [{"address": "b@example.net", "delay_reason": "connect timed out"}]}
{"queue_name": "deferred", "queue_id": "4bQ7mT0pZ2z9", "arrival_time": 1794999000, "message_size": 911, "sender": "", "recipients": [{"address": "c@example.net"}]}
`
	calls := stubToolsEnv(t, answer{out: "/var/spool/postfix\n"}, answer{out: out})
	got, err := postfixQueueAge(context.Background(), postfixUnit)
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"age_read": true, "oldest_age_s": int64(3600)}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	if c := (*calls)[1]; !slices.Equal(c.args, []string{"postqueue", "-j"}) {
		t.Fatalf("call %q", c.args)
	}
}

func TestPostfixQueueAgeOfAnEmptyQueueIsZero(t *testing.T) {
	root := mailRoot(t)
	queueFiles(t, root, "var/spool/postfix/active", 0)
	stubToolsEnv(t, answer{out: "/var/spool/postfix\n"}, answer{out: ""})
	got, err := postfixQueueAge(context.Background(), postfixUnit)
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"age_read": true, "oldest_age_s": int64(0)}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestPostfixQueueAgeLeavesAFullQueueAlone(t *testing.T) {
	root := mailRoot(t)
	queueFiles(t, root, "var/spool/postfix/deferred/0", postqueueMax)
	// One answer: a call of postqueue past it fails the test.
	stubToolsEnv(t, answer{out: "/var/spool/postfix\n"})
	got, err := postfixQueueAge(context.Background(), postfixUnit)
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"age_read": false}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestPostfixQueueAgeRefusesWhatIsNoQueueListing(t *testing.T) {
	root := mailRoot(t)
	queueFiles(t, root, "var/spool/postfix/active", 1)
	for _, out := range []string{
		"-Queue ID-  --Size-- ----Arrival Time---- -Sender/Recipient-------\n",
		`{"queue_name": "active"}` + "\n",
		`{"arrival_time": "yesterday"}` + "\n",
		`{"arrival_time": -5}` + "\n",
	} {
		stubToolsEnv(t, answer{out: "/var/spool/postfix\n"}, answer{out: out})
		if _, err := postfixQueueAge(context.Background(), postfixUnit); err == nil {
			t.Errorf("postqueue %q read as an age", out)
		}
	}
	stubToolsEnv(t, answer{out: "/var/spool/postfix\n"}, answer{err: repoExit(t, 69, "postqueue: fatal: Mail system is down\n")})
	if _, err := postfixQueueAge(context.Background(), postfixUnit); err == nil {
		t.Fatal("a failed postqueue reads as an age")
	}
}

// doveadmServices is doveadm -f tab service status of Dovecot 2.4: imap at its process limit, lmtp
// without a limit.
const doveadmServices = "name\tprocess_count\tprocess_avail\tprocess_limit\tclient_limit\tthrottle_secs\texit_failure_last\texit_failures_in_sec\tlast_drop_warning\tlisten_pending\tlistening\tdoveadm_stop\tprocess_total\n" +
	"imap\t100\t0\t100\t1\t0\t0\t0\t1794999000\tn\ty\tn\t5310\n" +
	"imap-login\t3\t1\t100\t1000\t0\t0\t0\t0\tn\ty\tn\t12\n" +
	"lmtp\t2\t0\t0\t1\t0\t0\t0\t0\tn\ty\tn\t40\n"

// doveadmErrors is doveadm log errors: two errors, a fatal one and a warning.
const doveadmErrors = `Nov 14 14:12:01.004211 Error: imap(alice)<4711><abc>: Mailbox INBOX: open failed
Nov 14 14:30:44.120000 Warning: auth: Time moved forwards by 1.2 seconds
Nov 14 14:40:00.000001 Fatal: lmtp(bob@example.org): Out of memory
Nov 14 14:41:00.000001 Error: auth-worker: pam(carol,192.0.2.7): pam_authenticate() failed
`

func TestDovecotStatusCountsLimitsAndErrors(t *testing.T) {
	stubNow(t, time.Unix(1_795_000_000, 0))
	calls := stubToolsEnv(t, answer{out: doveadmServices}, answer{out: doveadmErrors})
	got, err := dovecotStatus(context.Background(), Target{Kind: kindUnit, Name: "dovecot.service"})
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"services": 3, "services_at_limit": 1, "errors_1h": 3, "warnings_1h": 1}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	since := strconv.FormatInt(1_795_000_000-3600, 10)
	if c := (*calls)[1]; !slices.Equal(c.args, []string{"doveadm", "log", "errors", "-s", since}) {
		t.Fatalf("call %q", c.args)
	}
	if c := (*calls)[0]; !slices.Equal(c.args, []string{"doveadm", "-f", "tab", "service", "status"}) {
		t.Fatalf("call %q", c.args)
	}
}

func TestDovecotStatusRefusesWhatIsNoServiceTable(t *testing.T) {
	for _, out := range []string{
		"name\tprocess_count\nimap\t3\n",
		"name\tprocess_count\tprocess_limit\nimap\t3\n",
		"name\tprocess_count\tprocess_limit\nimap\tmany\t100\n",
		"imap 3 100\n",
	} {
		stubToolsEnv(t, answer{out: out})
		if _, err := dovecotStatus(context.Background(), Target{Kind: kindUnit, Name: "dovecot.service"}); err == nil {
			t.Errorf("service status %q read as services", out)
		}
	}
	stubToolsEnv(t, answer{err: exec.ErrNotFound})
	if _, err := dovecotStatus(context.Background(), Target{Kind: kindUnit, Name: "dovecot.service"}); !errors.Is(err, ErrUnsupported) {
		t.Fatalf("no doveadm = %v, want unsupported", err)
	}
	stubToolsEnv(t, answer{out: doveadmServices}, answer{err: repoExit(t, 75, "doveadm: Error: connect(/run/dovecot/log-errors) failed\n")})
	if _, err := dovecotStatus(context.Background(), Target{Kind: kindUnit, Name: "dovecot.service"}); err == nil {
		t.Fatal("a failed log errors reads as no errors")
	}
}

func TestMailViewsAreBoundToUnits(t *testing.T) {
	for _, view := range []string{"postfix_queue", "postfix_queue_age", "dovecot_status"} {
		if v, ok := appViews[view]; !ok || !slices.Equal(v.kinds, unitKinds) {
			t.Errorf("view %s: %+v", view, v)
		}
	}
}
