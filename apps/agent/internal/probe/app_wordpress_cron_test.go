// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/go-sql-driver/mysql"
)

// phpS, phpI and phpA write values the way PHP's serialize() does.
func phpS(s string) string { return fmt.Sprintf("s:%d:\"%s\";", len(s), s) }
func phpI(n int64) string  { return fmt.Sprintf("i:%d;", n) }
func phpA(pairs ...string) string {
	return fmt.Sprintf("a:%d:{%s}", len(pairs)/2, strings.Join(pairs, ""))
}

// wpEvent is one event of the option cron: schedule, args and, for a recurring one, interval.
func wpEvent(schedule string, args string) string {
	if schedule == "" {
		return phpA(phpS("schedule"), "b:0;", phpS("args"), args)
	}
	return phpA(phpS("schedule"), phpS(schedule), phpS("args"), args, phpS("interval"), phpI(43200))
}

func TestWPCronCountsEventsAndTheOverdueOnes(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	hash := "40cd750bba9870f18aada2478b24840a"
	cron := phpA(
		// Due an hour ago: two hooks, one of them with two events (other arguments).
		phpI(now.Unix()-3600), phpA(
			phpS("wp_version_check"), phpA(phpS(hash), wpEvent("twicedaily", "a:0:{}")),
			phpS("my_plugin_job"), phpA(
				phpS("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), wpEvent("", phpA(phpI(0), "d:1.5;", phpI(1), "N;")),
				phpS("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"), wpEvent("", phpA(phpI(0), `O:8:"stdClass":1:{`+phpS("x")+"b:1;}")),
			),
		),
		// Due half an hour ago: overdue, but not the oldest.
		phpI(now.Unix()-1800), phpA(phpS("wp_privacy_delete_old_export_files"), phpA(phpS(hash), wpEvent("hourly", "a:0:{}"))),
		// Due ten minutes ago, the limit: not yet overdue, nor one due five minutes ago.
		phpI(now.Unix()-600), phpA(phpS("delete_expired_transients"), phpA(phpS(hash), wpEvent("daily", "a:0:{}"))),
		phpI(now.Unix()-300), phpA(phpS("wp_scheduled_delete"), phpA(phpS(hash), wpEvent("daily", "a:0:{}"))),
		// Due tomorrow.
		phpI(now.Unix()+86400), phpA(phpS("wp_update_plugins"), phpA(phpS(hash), wpEvent("twicedaily", "a:0:{}"))),
		phpS("version"), phpI(2),
	)
	got, err := wpCronCounts([]byte(cron), now)
	if err != nil {
		t.Fatalf("wpCronCounts: %v", err)
	}
	want := map[string]any{"events": int64(7), "overdue": int64(4), "oldest_overdue_s": int64(3600)}
	if fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestWPCronCountsNothingWithoutEvents(t *testing.T) {
	got, err := wpCronCounts([]byte(phpA(phpS("version"), phpI(2))), time.Unix(1_800_000_000, 0))
	if err != nil {
		t.Fatalf("wpCronCounts: %v", err)
	}
	if fmt.Sprint(got) != fmt.Sprint(map[string]any{"events": int64(0), "overdue": int64(0), "oldest_overdue_s": int64(0)}) {
		t.Fatalf("got %v", got)
	}
}

func TestWPCronRefusesAnOptionOfAnotherForm(t *testing.T) {
	secret := "hook_name_that_must_not_leak"
	good := phpA(phpI(1), phpA(phpS(secret), phpA(phpS("h"), wpEvent("", "a:0:{}"))))
	deep := strings.Repeat("a:1:{i:0;", wpCronMaxDepth+2) + "N;" + strings.Repeat("}", wpCronMaxDepth+2)
	for name, data := range map[string]string{
		"empty":                   "",
		"truncated":               good[:len(good)-1],
		"trailing bytes":          good + "N;",
		"a string too long":       `a:1:{i:1;s:99:"` + secret + `";}`,
		"a string too short":      `a:1:{i:1;s:2:"` + secret + `";}`,
		"a count too high":        `a:2:{i:1;a:0:{}}`,
		"a reference":             `a:1:{i:1;R:1;}`,
		"custom serialization":    `a:1:{i:1;C:3:"Foo":0:{}}`,
		"an array as key":         `a:1:{a:0:{}i:1;}`,
		"a bool of 2":             `a:1:{i:1;b:2;}`,
		"a number too long":       `a:1:{i:123456789012345678901;a:0:{}}`,
		"not an array":            phpS(secret),
		"a timestamp of a string": phpA(phpI(1), phpS(secret)),
		"a hook of a string":      phpA(phpI(1), phpA(phpS(secret), phpS("x"))),
		"nested too deep":         deep,
		"too large":               phpA(phpS("version"), phpS(strings.Repeat("x", wpCronMaxBytes))),
	} {
		t.Run(name, func(t *testing.T) {
			_, err := wpCronCounts([]byte(data), time.Unix(1_800_000_000, 0))
			if !errors.Is(err, errPHPForm) {
				t.Fatalf("got %v, want errPHPForm", err)
			}
			if strings.Contains(err.Error(), secret) {
				t.Fatalf("the error quotes the option: %v", err)
			}
		})
	}
}

func TestWPCronStopsAtTooManyValues(t *testing.T) {
	var b strings.Builder
	n := wpCronMaxValues / 2
	fmt.Fprintf(&b, "a:%d:{", n)
	for i := range n {
		fmt.Fprintf(&b, "i:%d;N;", i)
	}
	b.WriteString("}")
	if _, err := parsePHP([]byte(b.String())); !errors.Is(err, errPHPForm) {
		t.Fatalf("got %v, want errPHPForm", err)
	}
}

// wpCronOption is the option cron of a fresh WordPress 6.8 (wordpress:latest, 2026-11): three events.
const wpCronOption = `a:4:{i:1794725908;a:1:{s:16:"wp_version_check";a:1:{s:32:"40cd750bba9870f18aada2478b24840a";` +
	`a:3:{s:8:"schedule";s:10:"twicedaily";s:4:"args";a:0:{}s:8:"interval";i:43200;}}}i:1794727708;a:1:{` +
	`s:17:"wp_update_plugins";a:1:{s:32:"40cd750bba9870f18aada2478b24840a";a:3:{s:8:"schedule";s:10:"twicedaily";` +
	`s:4:"args";a:0:{}s:8:"interval";i:43200;}}}i:1794729508;a:1:{s:16:"wp_update_themes";a:1:{` +
	`s:32:"40cd750bba9870f18aada2478b24840a";a:3:{s:8:"schedule";s:10:"twicedaily";s:4:"args";a:0:{}` +
	`s:8:"interval";i:43200;}}}s:7:"version";i:2;}`

func TestWPCronCountsTheOptionOfAFreshSite(t *testing.T) {
	got, err := wpCronCounts([]byte(wpCronOption), time.Unix(1794729508+3600, 0))
	want := map[string]any{"events": int64(3), "overdue": int64(3), "oldest_overdue_s": int64(7200)}
	if err != nil || fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("got %v, %v; want %v", got, err, want)
	}
}

// wpSecret is the password of the tests: no error may quote it, nor the user.
const wpSecret = "s3cr3t-Passw0rd"

func wpEnv(extra ...string) []string {
	return append([]string{"PATH=/usr/bin", "WORDPRESS_DB_HOST=db", "WORDPRESS_DB_USER=wpuser",
		"WORDPRESS_DB_PASSWORD=" + wpSecret, "WORDPRESS_DB_NAME=site_1"}, extra...)
}

func TestWPDBOfReadsTheEnvironmentLikeTheImage(t *testing.T) {
	db, err := wpDBOf(wpEnv())
	if err != nil || db != (wpDB{host: "db", user: "wpuser", password: wpSecret, name: "site_1", prefix: "wp_"}) {
		t.Fatalf("wpDBOf = %+v, %v", db, err)
	}
	db, err = wpDBOf([]string{"WORDPRESS_DB_USER=u", "WORDPRESS_DB_PASSWORD=", "WORDPRESS_TABLE_PREFIX="})
	if err != nil || db != (wpDB{host: "mysql", user: "u", name: "wordpress"}) {
		t.Fatalf("the image's defaults: wpDBOf = %+v, %v", db, err)
	}
	db, err = wpDBOf(wpEnv("WORDPRESS_DB_HOST=MariaDB.internal:3306", "WORDPRESS_TABLE_PREFIX=blog2_"))
	if err != nil || db.host != "MariaDB.internal" || db.prefix != "blog2_" {
		t.Fatalf("host with 3306 and a prefix: wpDBOf = %+v, %v", db, err)
	}
}

func TestWPDBOfLeavesOtherEnvironmentsUnsupported(t *testing.T) {
	for name, env := range map[string][]string{
		"no user":                {"WORDPRESS_DB_PASSWORD=" + wpSecret},
		"no password":            {"WORDPRESS_DB_USER=" + wpSecret},
		"an empty user":          wpEnv("WORDPRESS_DB_USER="),
		"a password file":        wpEnv("WORDPRESS_DB_PASSWORD_FILE=/run/secrets/" + wpSecret),
		"a user file":            wpEnv("WORDPRESS_DB_USER_FILE=/run/secrets/u"),
		"another port":           wpEnv("WORDPRESS_DB_HOST=db:3307"),
		"a socket":               wpEnv("WORDPRESS_DB_HOST=localhost:/run/mysqld/" + wpSecret + ".sock"),
		"an address":             wpEnv("WORDPRESS_DB_HOST=192.0.2.7"),
		"an address with a port": wpEnv("WORDPRESS_DB_HOST=192.0.2.7:3306"),
		"an IPv6 address":        wpEnv("WORDPRESS_DB_HOST=[2001:db8::7]:3306"),
		"a user of other chars":  wpEnv("WORDPRESS_DB_USER=wp-" + wpSecret),
		"a name of other chars":  wpEnv("WORDPRESS_DB_NAME=site`; DROP TABLE x; -- " + wpSecret),
		"a prefix of SQL":        wpEnv("WORDPRESS_TABLE_PREFIX=wp_` WHERE 1; --"),
		"a prefix too long":      wpEnv("WORDPRESS_TABLE_PREFIX=" + strings.Repeat("p", 21)),
	} {
		t.Run(name, func(t *testing.T) {
			_, err := wpDBOf(env)
			if !errors.Is(err, ErrUnsupported) {
				t.Fatalf("wpDBOf = %v, want ErrUnsupported", err)
			}
			if strings.Contains(err.Error(), wpSecret) || strings.Contains(err.Error(), "wpuser") {
				t.Fatalf("the error quotes the environment: %v", err)
			}
		})
	}
}

func TestImageBaseIsTheRepositoryAlone(t *testing.T) {
	for image, want := range map[string]string{
		"mariadb":                         "mariadb",
		"mariadb:11":                      "mariadb",
		"docker.io/library/mysql:8.4":     "mysql",
		"registry.example:5000/mariadb:1": "mariadb",
		"mariadb:11@sha256:0123abcd":      "mariadb",
		"bitnami/mariadb":                 "mariadb",
		"mariadb-backup:1":                "mariadb-backup",
		"sha256:0123abcd":                 "sha256",
	} {
		if got := imageBase(image); got != want {
			t.Errorf("imageBase(%q) = %q, want %q", image, got, want)
		}
	}
}

func TestWPCronQueryIsFixed(t *testing.T) {
	if got, want := wpCronQuery("wp_", true), "SET STATEMENT max_statement_time=5 FOR SELECT option_value FROM `wp_options` "+
		"WHERE option_name = 'cron' AND LENGTH(option_value) <= 1048576"; got != want {
		t.Errorf("MariaDB: %q, want %q", got, want)
	}
	if got, want := wpCronQuery("blog_", false), "SELECT /*+ MAX_EXECUTION_TIME(5000) */ option_value FROM `blog_options` "+
		"WHERE option_name = 'cron' AND LENGTH(option_value) <= 1048576"; got != want {
		t.Errorf("MySQL: %q, want %q", got, want)
	}
}

// The ids of the containers of the tests, in the form docker gives and the command allowlist takes.
var (
	wpID  = strings.Repeat("a1", 32)
	dbID  = strings.Repeat("b2", 32)
	db2ID = strings.Repeat("c3", 32)
	db3ID = strings.Repeat("d4", 32)
)

// wpPIDs gives each container of the tests its own pid, so a test sees whose root the view opens.
var wpPIDs = map[string]int{wpID: 4343, dbID: 4344, db2ID: 4345, db3ID: 4346}

// wpInspect is `docker inspect` of one container: id, state, image, environment and its networks with
// their aliases and DNS names.
func wpInspect(id, state, image string, env []string, networks map[string][]string) string {
	nets := map[string]any{}
	for name, names := range networks {
		nets[name] = map[string]any{"IPAddress": "192.0.2.9", "Aliases": names[:1], "DNSNames": names[1:]}
	}
	b, _ := json.Marshal(map[string]any{
		"Id": id, "State": map[string]any{"Status": state, "Running": state == "running", "Pid": wpPIDs[id]},
		"Config": map[string]any{"Image": image, "Env": env}, "NetworkSettings": map[string]any{"Networks": nets},
	})
	return string(b)
}

// stubDocker answers docker inspect of the container web with wp, docker ps with the ids of all and the
// inspect of those ids with all; it returns the calls.
func stubDocker(t *testing.T, wp string, all ...string) *[][]string {
	t.Helper()
	var calls [][]string
	old := runTool
	runTool = func(_ context.Context, _ time.Duration, name string, args ...string) ([]byte, error) {
		calls = append(calls, append([]string{name}, args...))
		checkAllowed(t, name, args)
		switch {
		case slices.Equal(args, []string{"inspect", "--type", "container", "--", "web"}):
			return []byte("[" + wp + "]"), nil
		case args[0] == "ps":
			var ids []string
			for _, c := range all {
				var info containerInfo
				if err := json.Unmarshal([]byte(c), &info); err != nil {
					t.Fatal(err)
				}
				ids = append(ids, info.ID)
			}
			return []byte(strings.Join(ids, "\n") + "\n"), nil
		case args[0] == "inspect":
			return []byte("[" + strings.Join(all, ",") + "]"), nil
		}
		t.Errorf("unexpected call %v", args)
		return nil, errors.New("unexpected")
	}
	t.Cleanup(func() { runTool = old })
	return &calls
}

func TestWPDBContainerIsTheOneCarryingTheHost(t *testing.T) {
	wp := wpInspect(wpID, "running", "wordpress:6", wpEnv(), map[string][]string{"site": {"wordpress", "wp1"}})
	db := wpInspect(dbID, "running", "mariadb:11", nil, map[string][]string{"site": {"db", "site-db-1", "db1"}})
	other := wpInspect(db2ID, "running", "mysql:8.4", nil, map[string][]string{"elsewhere": {"db"}})
	mysql8 := wpInspect(db3ID, "running", "mysql:8.4", nil, map[string][]string{"site": {"mysql8", "DB"}})
	var c containerInfo
	if err := json.Unmarshal([]byte(wp), &c); err != nil {
		t.Fatal(err)
	}
	stubDocker(t, wp, wp, db, other)
	got, mariadb, err := wpDBContainer(context.Background(), c, "db")
	if err != nil || got.ID != dbID || !mariadb {
		t.Fatalf("wpDBContainer = %s, %t, %v; want db1 of mariadb", got.ID, mariadb, err)
	}
	stubDocker(t, wp, wp, other, mysql8)
	got, mariadb, err = wpDBContainer(context.Background(), c, "db")
	if err != nil || got.ID != db3ID || mariadb {
		t.Fatalf("a DNS name of another case = %s, %t, %v; want db3 of mysql", got.ID, mariadb, err)
	}
	for name, all := range map[string][]string{
		"none in a shared network": {wp, other},
		"two":                      {wp, db, mysql8},
		"another image":            {wp, wpInspect(dbID, "running", "postgres:17", nil, map[string][]string{"site": {"db"}})},
		"the WordPress container":  {wpInspect(wpID, "running", "mariadb:11", wpEnv(), map[string][]string{"site": {"db"}})},
	} {
		stubDocker(t, wp, all...)
		if _, _, err := wpDBContainer(context.Background(), c, "db"); !errors.Is(err, ErrUnsupported) {
			t.Errorf("%s: %v, want ErrUnsupported", name, err)
		}
	}
	stubDocker(t, wp, wp, wpInspect(dbID, "exited", "mariadb:11", nil, map[string][]string{"site": {"db"}}))
	if _, _, err := wpDBContainer(context.Background(), c, "db"); err == nil || errors.Is(err, ErrUnsupported) {
		t.Errorf("a stopped database = %v, want an error", err)
	}
	stubDocker(t, wp, wp, wpInspect(db2ID, "exited", "mysql:8.4", nil, map[string][]string{"site": {"db"}}), db)
	if got, _, err := wpDBContainer(context.Background(), c, "db"); err != nil || got.ID != dbID {
		t.Errorf("a stopped one beside a running one = %s, %v; want the running one", got.ID, err)
	}
}

func TestWPDBContainerTakesAContainerRemovedSinceDockerPs(t *testing.T) {
	wp := wpInspect(wpID, "running", "wordpress:6", wpEnv(), map[string][]string{"site": {"wordpress"}})
	db := wpInspect(dbID, "running", "mariadb:11", nil, map[string][]string{"site": {"db"}})
	var c containerInfo
	if err := json.Unmarshal([]byte(wp), &c); err != nil {
		t.Fatal(err)
	}
	gone := false
	old := runTool
	runTool = func(_ context.Context, _ time.Duration, _ string, args ...string) ([]byte, error) {
		switch {
		case args[0] == "ps" && !gone:
			gone = true
			return []byte(wpID + "\n" + dbID + "\n" + db2ID + "\n"), nil
		case args[0] == "ps":
			return []byte(wpID + "\n" + dbID + "\n"), nil
		case args[0] == "inspect":
			// docker prints what it found and ends with exit 1 for the rest.
			return []byte("[" + wp + "," + db + "]"), &exec.ExitError{}
		}
		t.Errorf("unexpected call %v", args)
		return nil, errors.New("unexpected")
	}
	t.Cleanup(func() { runTool = old })
	if got, _, err := wpDBContainer(context.Background(), c, "db"); err != nil || got.ID != dbID {
		t.Fatalf("wpDBContainer = %s, %v; want db1", got.ID, err)
	}
	runTool = func(_ context.Context, _ time.Duration, _ string, args ...string) ([]byte, error) {
		if args[0] == "inspect" {
			return []byte("[" + wp + "," + db + "]"), &exec.ExitError{}
		}
		return []byte(wpID + "\n" + dbID + "\n" + db2ID + "\n"), nil
	}
	if _, _, err := wpDBContainer(context.Background(), c, "db"); err == nil {
		t.Fatal("a container docker inspect skipped but docker ps still lists: no error")
	}
}

func TestWordPressCronStopsBeforeTheDatabaseWhereItCannotGo(t *testing.T) {
	pids := stubContainerRoot(t, func(int) (*os.Root, error) { return nil, errors.New("no root") })
	for name, wp := range map[string]string{
		"stopped":         wpInspect(wpID, "exited", "wordpress:6", wpEnv(), map[string][]string{"site": {"wp"}}),
		"a password file": wpInspect(wpID, "running", "wordpress:6", wpEnv("WORDPRESS_DB_PASSWORD_FILE=/run/s"), nil),
		"no database":     wpInspect(wpID, "running", "wordpress:6", wpEnv(), map[string][]string{"site": {"wp"}}),
	} {
		stubDocker(t, wp, wp)
		_, err := wordpressCron(context.Background(), wpTarget())
		if err == nil || strings.Contains(err.Error(), wpSecret) {
			t.Errorf("%s: %v, want an error without the password", name, err)
		}
	}
	if len(*pids) != 0 {
		t.Errorf("opened the roots of %v, want none", *pids)
	}
}

func TestReadWPCronNamesNoUserInItsErrors(t *testing.T) {
	db := wpDB{host: "db", user: "wpuser", password: wpSecret, name: "site_1", prefix: "wp_"}
	for name, dial := range map[string]func(context.Context) (net.Conn, error){
		"no socket": func(context.Context) (net.Conn, error) {
			return nil, fmt.Errorf("%w: it holds neither /run/mysqld/mysqld.sock nor /var/run/mysqld/mysqld.sock", errWPSocket)
		},
		"a server that hangs up": func(context.Context) (net.Conn, error) {
			c, s := net.Pipe()
			s.Close()
			return c, nil
		},
		"a server that answers nothing": func(context.Context) (net.Conn, error) {
			c, s := net.Pipe()
			go func() { _, _ = s.Read(make([]byte, 64)) }()
			return c, nil
		},
	} {
		t.Run(name, func(t *testing.T) {
			// The server that answers nothing holds the login until the context ends; 1 s keeps the test
			// below the view's own limit of wpDBTimeout.
			ctx, cancel := context.WithTimeout(context.Background(), time.Second)
			defer cancel()
			_, err := readWPCron(ctx, dial, db, true)
			if err == nil || strings.Contains(err.Error(), wpSecret) || strings.Contains(err.Error(), "wpuser") {
				t.Fatalf("readWPCron = %v, want an error naming no user", err)
			}
		})
	}
}

func TestWPDBErrorKeepsTheServersTextOut(t *testing.T) {
	refused := &mysql.MySQLError{Number: 1045, SQLState: [5]byte{'2', '8', '0', '0', '0'},
		Message: "Access denied for user 'wpuser'@'localhost' (using password: YES)"}
	if got := wpDBError(refused).Error(); got != "its database refuses with error 1045" {
		t.Errorf("a refused login = %q", got)
	}
	if got := wpDBError(context.DeadlineExceeded).Error(); got != "its database does not answer within 5s" {
		t.Errorf("a timeout = %q", got)
	}
	if got := wpDBError(errors.New("packets.go: wpuser " + wpSecret)).Error(); got != "the connection to its database fails" {
		t.Errorf("another error = %q", got)
	}
}

// fakeMySQL plays a database server on s: the handshake of protocol 10 with mysql_native_password, OK for
// any login, then answer for the query, which it is given without its command byte.
func fakeMySQL(s net.Conn, answer func(query string, w func(seq byte, payload []byte) error) error) {
	defer s.Close()
	w := func(seq byte, payload []byte) error {
		n := len(payload)
		_, err := s.Write(append([]byte{byte(n), byte(n >> 8), byte(n >> 16), seq}, payload...))
		return err
	}
	var last []byte
	read := func() error {
		var h [4]byte
		if _, err := io.ReadFull(s, h[:]); err != nil {
			return err
		}
		last = make([]byte, int(h[0])|int(h[1])<<8|int(h[2])<<16)
		_, err := io.ReadFull(s, last)
		return err
	}
	// CLIENT_PROTOCOL_41 | CLIENT_SECURE_CONNECTION | CLIENT_PLUGIN_AUTH.
	var caps uint32 = 0x200 | 0x8000 | 0x80000
	hello := []byte{10}
	hello = append(hello, "5.7.0\x00"...)
	hello = append(hello, 1, 0, 0, 0)
	hello = append(hello, "abcdefgh"...)
	hello = append(hello, 0, byte(caps), byte(caps>>8), 45, 2, 0, byte(caps>>16), byte(caps>>24), 21)
	hello = append(hello, make([]byte, 10)...)
	hello = append(hello, "ijklmnopqrst\x00"...)
	hello = append(hello, "mysql_native_password\x00"...)
	ok := []byte{0, 0, 0, 2, 0, 0, 0}
	if w(0, hello) != nil || read() != nil || w(2, ok) != nil || read() != nil {
		return
	}
	_ = answer(string(last[1:]), w)
}

func lenencStr(s string) []byte {
	if n := len(s); n >= 251 {
		return append([]byte{0xfc, byte(n), byte(n >> 8)}, s...)
	}
	return append([]byte{byte(len(s))}, s...)
}

// honestAnswer answers the query with the option cron in one column of type BLOB.
func honestAnswer(option string) func(string, func(byte, []byte) error) error {
	return func(_ string, w func(byte, []byte) error) error {
		var col []byte
		for _, f := range []string{"def", "site_1", "wp_options", "wp_options", "option_value", "option_value"} {
			col = append(col, lenencStr(f)...)
		}
		// Character set, length, type MYSQL_TYPE_BLOB, flags, decimals, filler.
		col = append(col, 0x0c, 45, 0, 0xff, 0xff, 0xff, 0xff, 0xfc, 0x10, 0, 0, 0, 0)
		eof := []byte{0xfe, 0, 0, 2, 0}
		for i, p := range [][]byte{{1}, col, eof, lenencStr(option), eof} {
			if err := w(byte(1+i), p); err != nil {
				return err
			}
		}
		return nil
	}
}

func TestReadWPCronTakesTheOptionFromAnHonestServer(t *testing.T) {
	db := wpDB{host: "db", user: "wpuser", password: wpSecret, name: "site_1", prefix: "wp_"}
	dial := func(context.Context) (net.Conn, error) {
		c, s := net.Pipe()
		go fakeMySQL(s, honestAnswer(wpCronOption))
		return c, nil
	}
	got, err := readWPCron(context.Background(), dial, db, true)
	if err != nil || string(got) != wpCronOption {
		t.Fatalf("readWPCron = %q, %v; want the option", got, err)
	}
}

func TestReadWPCronStopsAServerThatSendsMoreThanItReads(t *testing.T) {
	db := wpDB{host: "db", user: "wpuser", password: wpSecret, name: "site_1", prefix: "wp_"}
	for name, answer := range map[string]func(string, func(byte, []byte) error) error{
		// The count of columns the driver allocates by: 2^38 is an out of memory, no panic.
		"a result of 2^38 columns": func(_ string, w func(byte, []byte) error) error {
			return w(1, []byte{0xfe, 0, 0, 0, 0, 0x40, 0, 0, 0})
		},
		"a result of two columns": func(_ string, w func(byte, []byte) error) error {
			return w(1, []byte{2})
		},
		"a packet longer than the budget": func(_ string, w func(byte, []byte) error) error {
			return w(1, make([]byte, wpDBReadBudget))
		},
		// Packets of 16 MiB - 1 continue each other without end.
		"continued packets without end": func(_ string, w func(byte, []byte) error) error {
			full := make([]byte, 1<<24-1)
			full[0] = 1
			for seq := byte(1); ; seq++ {
				if err := w(seq, full); err != nil {
					return err
				}
			}
		},
	} {
		t.Run(name, func(t *testing.T) {
			dial := func(context.Context) (net.Conn, error) {
				c, s := net.Pipe()
				go fakeMySQL(s, answer)
				return c, nil
			}
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			if got, err := readWPCron(ctx, dial, db, true); err == nil {
				t.Fatalf("readWPCron = %q, want an error", got)
			}
		})
	}
}

func TestWordPressCronCountsTheEventsInTheDatabaseOfItsSite(t *testing.T) {
	wp := wpInspect(wpID, "running", "wordpress:6", wpEnv(), map[string][]string{"site": {"wordpress"}})
	db := wpInspect(dbID, "running", "mariadb:11", nil, map[string][]string{"site": {"db"}})
	stubDocker(t, wp, wp, db)
	pids := stubContainerRoot(t, func(int) (*os.Root, error) { return os.OpenRoot(t.TempDir()) })
	stubNow(t, time.Unix(1794729508+3600, 0))
	var queries []string
	old := dialSocket
	dialSocket = func(context.Context, *os.Root) (net.Conn, error) {
		c, s := net.Pipe()
		answer := honestAnswer(wpCronOption)
		go fakeMySQL(s, func(q string, w func(byte, []byte) error) error {
			queries = append(queries, q)
			return answer(q, w)
		})
		return c, nil
	}
	t.Cleanup(func() { dialSocket = old })
	got, err := wordpressCron(context.Background(), wpTarget())
	want := map[string]any{"events": int64(3), "overdue": int64(3), "oldest_overdue_s": int64(7200)}
	if err != nil || fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("wordpressCron = %v, %v; want %v", got, err, want)
	}
	if !slices.Equal(*pids, []int{wpPIDs[dbID]}) {
		t.Errorf("opened the roots of %v, want the database's %d alone", *pids, wpPIDs[dbID])
	}
	if !slices.Equal(queries, []string{wpCronQuery("wp_", true)}) {
		t.Errorf("queries = %q, want the one query in the form of mariadb", queries)
	}
}

// guardedRead sends frames to a wpDBGuard after the client's query and returns what the guard lets through.
func guardedRead(t *testing.T, budget int, frames ...[]byte) ([]byte, error) {
	t.Helper()
	c, s := net.Pipe()
	g := &wpDBGuard{Conn: c, budget: budget}
	t.Cleanup(func() { g.Close() })
	go func() {
		defer s.Close()
		_, _ = io.ReadFull(s, make([]byte, 9))
		for _, f := range frames {
			n := len(f)
			if _, err := s.Write(append([]byte{byte(n), byte(n >> 8), byte(n >> 16), 1}, f...)); err != nil {
				return
			}
		}
	}()
	if _, err := g.Write([]byte{5, 0, 0, 0, 0x03, 'S', 'E', 'L', 0}); err != nil {
		t.Fatal(err)
	}
	return io.ReadAll(g)
}

func TestWPDBGuardLetsThroughOnlyTheAnswerTheViewReads(t *testing.T) {
	got, err := guardedRead(t, 64, []byte{1})
	if err != nil || !slices.Equal(got, []byte{1, 0, 0, 1, 1}) {
		t.Fatalf("one column = %v, %v; want it passed", got, err)
	}
	got, err = guardedRead(t, 64, []byte{0xff, 0x15, 0x04})
	if err != nil || len(got) != 7 {
		t.Fatalf("an error = %v, %v; want it passed", got, err)
	}
	for name, frames := range map[string][][]byte{
		"two columns":          {{2}},
		"an OK":                {{0, 0, 0, 2, 0, 0, 0}},
		"a local file":         {{0xfb, 'x'}},
		"a count of 8 bytes":   {{0xfe, 0, 0, 0, 0, 0x40, 0, 0, 0}},
		"more than the budget": {{1}, make([]byte, 64)},
		// Empty packets cost their headers alone: 5 bytes and 15 headers of 4 are one more than 64.
		"headers beyond the budget": append([][]byte{{1}}, make([][]byte, 15)...),
	} {
		if _, err := guardedRead(t, 64, frames...); !errors.Is(err, errWPDBServer) {
			t.Errorf("%s: %v, want errWPDBServer", name, err)
		}
	}
}
