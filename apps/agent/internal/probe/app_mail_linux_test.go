// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"bufio"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/netip"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"slices"
	"strconv"
	"strings"
	"testing"
	"time"
)

// mailcowDir is the directory of the compose project of Mailcow below the root of the tests.
const mailcowDir = "/opt/mailcow-dockerized"

var redisMailcow = Target{Kind: kindContainer, Name: "redis-mailcow"}

// mailcowLabels is inspectJSON with the label of the compose project at dir.
func mailcowLabels(t *testing.T, dir string) string {
	t.Helper()
	labels := fmt.Sprintf(`"Config":{"Labels":{"com.docker.compose.project.working_dir":%q,"com.docker.compose.service":"redis-mailcow"}},"HostConfig":`, dir)
	return strings.Replace(inspectJSON(t, "running", "", "bridge"), `"HostConfig":`, labels, 1)
}

// mailcowInspect answers docker inspect of redis-mailcow with the project at dir, and docker ps of the
// guard's snapshot with no container.
func mailcowInspect(t *testing.T, dir string) {
	t.Helper()
	stubTools(t, answer{out: mailcowLabels(t, dir)}, answer{out: ""})
}

// writeHostFile writes content to name below root.
func writeHostFile(t *testing.T, root, name, content string) {
	t.Helper()
	full := filepath.Join(root, filepath.FromSlash(name))
	if err := os.MkdirAll(filepath.Dir(full), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(full, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
}

// fakeRedis is a Redis that answers each command with the next of its replies and records the
// commands it got.
type fakeRedis struct {
	commands chan []string
}

// startRedis listens on 127.0.0.1, answers the commands of one connection with replies in turn and
// points mailcowEndpoint at itself.
func startRedis(t *testing.T, replies ...string) *fakeRedis {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { ln.Close() })
	fr := &fakeRedis{commands: make(chan []string, 8)}
	go func() {
		conn, err := ln.Accept()
		if err != nil {
			return
		}
		defer conn.Close()
		r := bufio.NewReader(conn)
		for _, reply := range replies {
			cmd, err := readRESPCommand(r)
			if err != nil {
				return
			}
			fr.commands <- cmd
			if _, err := io.WriteString(conn, reply); err != nil {
				return
			}
		}
	}()
	freshSnapshot(t)
	port := portOf(t, ln.Addr().String())
	old := mailcowEndpoint
	mailcowEndpoint = func(_ context.Context, tg Target) (endpoint, error) {
		if tg.PortHint != mailcowRedisPort {
			t.Errorf("port hint %d, want %d", tg.PortHint, mailcowRedisPort)
		}
		return endpoint{addr: netip.MustParseAddr("127.0.0.1"), port: uint16(port)}, nil
	}
	t.Cleanup(func() { mailcowEndpoint = old })
	return fr
}

// readRESPCommand reads one command of RESP2: an array of bulk strings.
func readRESPCommand(r *bufio.Reader) ([]string, error) {
	line, err := r.ReadString('\n')
	if err != nil || !strings.HasPrefix(line, "*") {
		return nil, errors.New("no array")
	}
	n, _ := strconv.Atoi(strings.TrimSpace(line[1:]))
	var cmd []string
	for range n {
		line, err := r.ReadString('\n')
		if err != nil {
			return nil, err
		}
		size, _ := strconv.Atoi(strings.TrimSpace(line[1:]))
		buf := make([]byte, size+2)
		if _, err := io.ReadFull(r, buf); err != nil {
			return nil, err
		}
		cmd = append(cmd, string(buf[:size]))
	}
	return cmd, nil
}

// next is the next command fr got.
func (fr *fakeRedis) next(t *testing.T) []string {
	t.Helper()
	select {
	case cmd := <-fr.commands:
		return cmd
	case <-time.After(30 * time.Second):
		t.Fatal("no command")
		return nil
	}
}

// bulkArray is the answer of LRANGE with entries.
func bulkArray(entries ...string) string {
	s := "*" + strconv.Itoa(len(entries)) + "\r\n"
	for _, e := range entries {
		s += "$" + strconv.Itoa(len(e)) + "\r\n" + e + "\r\n"
	}
	return s
}

func TestMailcowWatchdogReadsItsLogWithThePasswordOfMailcowConf(t *testing.T) {
	root := mailRoot(t)
	writeHostFile(t, root, mailcowDir+"/mailcow.conf", "# Redis\nDBPASS=dbsecret\nREDISPASS=\"s3cr3t\"\n")
	stubNow(t, time.Unix(1_795_000_000, 0))
	calls := stubTools(t, answer{out: mailcowLabels(t, mailcowDir)}, answer{out: ""})
	fr := startRedis(t, "+OK\r\n", bulkArray(
		`{"time":"1794999700","service":"Postfix","lvl":"0","hpnow":"8","hptotal":"8","hpdiff":"0"}`,
		`{"time":"1794999650","service":"Rspamd","lvl":"1","hpnow":"14","hptotal":"15","hpdiff":"-1"}`,
	))
	got, err := mailcowWatchdog(context.Background(), redisMailcow)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"services": 2, "services_failing": 1, "logged": true, "last_age_s": int64(300)}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	if c := fr.next(t); !slices.Equal(c, []string{"AUTH", "s3cr3t"}) {
		t.Fatalf("first command %q", c)
	}
	if c := fr.next(t); !slices.Equal(c, []string{"LRANGE", "WATCHDOG_LOG", "0", "499"}) {
		t.Fatalf("second command %q", c)
	}
	if !slices.Equal((*calls)[0], []string{"docker", "inspect", "--type", "container", "--", "redis-mailcow"}) {
		t.Fatalf("inspect %q", *calls)
	}
}

func TestMailcowWatchdogWithoutAPasswordSendsNoAuth(t *testing.T) {
	root := mailRoot(t)
	writeHostFile(t, root, mailcowDir+"/mailcow.conf", "MAILCOW_HOSTNAME=mx.example.org\n")
	stubNow(t, time.Unix(1_795_000_000, 0))
	mailcowInspect(t, mailcowDir)
	fr := startRedis(t, "*0\r\n")
	got, err := mailcowWatchdog(context.Background(), redisMailcow)
	if want := (map[string]any{"services": 0, "services_failing": 0, "logged": false}); err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, %v; want %v", got, err, want)
	}
	if c := fr.next(t); c[0] != "LRANGE" {
		t.Fatalf("first command %q", c)
	}
}

func TestMailcowWatchdogNeverQuotesThePassword(t *testing.T) {
	root := mailRoot(t)
	writeHostFile(t, root, mailcowDir+"/mailcow.conf", "REDISPASS=s3cr3t\n")
	mailcowInspect(t, mailcowDir)
	startRedis(t, "-WRONGPASS invalid username-password pair or user is disabled. s3cr3t\r\n", "-NOAUTH\r\n")
	_, err := mailcowWatchdog(context.Background(), redisMailcow)
	if !errors.Is(err, ErrDenied) || strings.Contains(err.Error(), "s3cr3t") || strings.Contains(err.Error(), "WRONGPASS") {
		t.Fatalf("a refused password = %v", err)
	}
	writeHostFile(t, root, mailcowDir+"/mailcow.conf", "MAILCOW_HOSTNAME=mx.example.org\n")
	mailcowInspect(t, mailcowDir)
	startRedis(t, "-NOAUTH Authentication required.\r\n")
	if _, err := mailcowWatchdog(context.Background(), redisMailcow); !errors.Is(err, ErrDenied) {
		t.Fatalf("no password = %v, want denied", err)
	}
}

func TestMailcowWatchdogRefusesWhatIsNoListOfEntries(t *testing.T) {
	root := mailRoot(t)
	writeHostFile(t, root, mailcowDir+"/mailcow.conf", "")
	for _, reply := range []string{
		"-WRONGTYPE Operation against a key holding the wrong kind of value\r\n",
		"*501\r\n",
		"*1\r\n:5\r\n",
		"*1\r\n$3\r\nabcde\r\n",
		"+OK\n",
		bulkArray(`{"time":"x"}`),
	} {
		mailcowInspect(t, mailcowDir)
		startRedis(t, reply)
		if _, err := mailcowWatchdog(context.Background(), redisMailcow); err == nil {
			t.Errorf("reply %q read as the log", reply)
		}
	}
}

func TestMailcowWatchdogWantsMailcowConfOfItsProject(t *testing.T) {
	mailRoot(t)
	for _, dir := range []string{"", "opt/mailcow", "/opt/../etc", "/opt/mailcow\n"} {
		mailcowInspect(t, dir)
		if _, err := mailcowWatchdog(context.Background(), redisMailcow); !errors.Is(err, ErrUnsupported) {
			t.Errorf("project dir %q = %v, want unsupported", dir, err)
		}
	}
	stubTool(t, inspectJSON(t, "running", "", "bridge"), nil)
	if _, err := mailcowWatchdog(context.Background(), redisMailcow); !errors.Is(err, ErrUnsupported) {
		t.Errorf("no compose label = %v, want unsupported", err)
	}
	mailcowInspect(t, mailcowDir)
	if _, err := mailcowWatchdog(context.Background(), redisMailcow); !errors.Is(err, ErrUnsupported) {
		t.Errorf("no mailcow.conf = %v, want unsupported", err)
	}
}

// pilerConf is a piler.conf of the package with the access to its database.
const pilerConf = "verbosity=1\n;comment=x\nmysqlhost=\nmysqlport=0\nmysqlsocket=/var/run/mysqld/mysqld.sock\n" +
	"mysqluser=piler\nmysqlpwd=p1l3r\nmysqldb=piler\n"

func TestPilerStatusReadsTheNewestArrivalWithThePasswordInTheEnvironment(t *testing.T) {
	root := mailRoot(t)
	writeHostFile(t, root, "etc/piler/piler.conf", pilerConf)
	stubNow(t, time.Unix(1_795_000_000, 0))
	calls := stubToolsEnv(t, answer{out: "1794996400\n"})
	got, err := pilerStatus(context.Background(), Target{Kind: kindUnit, Name: "piler.service"})
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"archived": true, "last_age_s": int64(3600)}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	c := (*calls)[0]
	want := []string{"mariadb", "--no-defaults", "--batch", "--skip-column-names", "--connect-timeout=5",
		"--socket=/var/run/mysqld/mysqld.sock", "--user=piler", "--database=piler", "--execute=" + pilerQuery}
	if !slices.Equal(c.args, want) || !slices.Contains(c.env, "MYSQL_PWD=p1l3r") {
		t.Fatalf("call %q env %q", c.args, c.env)
	}
	if slices.ContainsFunc(c.args, func(a string) bool { return strings.Contains(a, "p1l3r") }) {
		t.Fatalf("the password stands in an argument: %q", c.args)
	}
}

func TestPilerStatusFallsBackToMysqlAndAnEmptyArchive(t *testing.T) {
	root := mailRoot(t)
	writeHostFile(t, root, "usr/local/etc/piler/piler.conf", pilerConf)
	calls := stubToolsEnv(t, answer{err: exec.ErrNotFound}, answer{out: "NULL\n"})
	got, err := pilerStatus(context.Background(), Target{Kind: kindUnit, Name: "piler.service"})
	if err != nil || !reflect.DeepEqual(got, map[string]any{"archived": false}) {
		t.Fatalf("got %v, %v", got, err)
	}
	if (*calls)[1].args[0] != "mysql" {
		t.Fatalf("calls %v", *calls)
	}
}

func TestPilerStatusKeepsItsAccessOnThisHost(t *testing.T) {
	root := mailRoot(t)
	writeHostFile(t, root, "etc/piler/piler.conf", pilerConf)
	stubToolsEnv(t, answer{err: repoExit(t, 1, "ERROR 1045 (28000): Access denied for user 'piler'@'localhost' (using password: YES)\n")})
	_, err := pilerStatus(context.Background(), Target{Kind: kindUnit, Name: "piler.service"})
	if err == nil || !strings.Contains(err.Error(), "1045") || strings.Contains(err.Error(), "piler'@") {
		t.Fatalf("a refused access = %v, want its code alone", err)
	}
	stubToolsEnv(t, answer{err: repoExit(t, 2, "mariadb: unknown option p1l3r\n")})
	if _, err := pilerStatus(context.Background(), Target{Kind: kindUnit, Name: "piler.service"}); err == nil || strings.Contains(err.Error(), "p1l3r") {
		t.Fatalf("a failed client = %v", err)
	}
	for _, out := range []string{"", "yesterday\n", "-5\n", "1\n2\n"} {
		stubToolsEnv(t, answer{out: out})
		if _, err := pilerStatus(context.Background(), Target{Kind: kindUnit, Name: "piler.service"}); err == nil {
			t.Errorf("answer %q read as an arrival", out)
		}
	}
	stubToolsEnv(t, answer{err: exec.ErrNotFound}, answer{err: exec.ErrNotFound})
	if _, err := pilerStatus(context.Background(), Target{Kind: kindUnit, Name: "piler.service"}); !errors.Is(err, ErrUnsupported) {
		t.Fatalf("no client = %v, want unsupported", err)
	}
}

func TestPilerStatusHandsOnOnlyAccessOfTheLocalSocket(t *testing.T) {
	root := mailRoot(t)
	stubToolsEnv(t)
	if _, err := pilerStatus(context.Background(), Target{Kind: kindUnit, Name: "piler.service"}); !errors.Is(err, ErrUnsupported) {
		t.Fatalf("no piler.conf = %v, want unsupported", err)
	}
	for _, conf := range []string{
		strings.Replace(pilerConf, "mysqlsocket=/var/run/mysqld/mysqld.sock", "mysqlsocket=", 1),
		strings.Replace(pilerConf, "mysqlsocket=/var/run/mysqld/mysqld.sock", "mysqlsocket=run/mysqld.sock", 1),
		strings.Replace(pilerConf, "mysqlsocket=/var/run/mysqld/mysqld.sock", "mysqlsocket=/var/../mysqld.sock", 1),
		strings.Replace(pilerConf, "mysqluser=piler", "mysqluser=piler --host=evil", 1),
		strings.Replace(pilerConf, "mysqldb=piler", "mysqldb=", 1),
	} {
		writeHostFile(t, root, "etc/piler/piler.conf", conf)
		if _, err := pilerStatus(context.Background(), Target{Kind: kindUnit, Name: "piler.service"}); err == nil {
			t.Errorf("piler.conf %q handed on", conf)
		}
	}
}

// cvdFile writes a database of ClamAV with a header of version and build time below root.
func cvdFile(t *testing.T, root, name string, version int, built int64) {
	t.Helper()
	header := fmt.Sprintf("ClamAV-VDB:13 Nov 2026 08-26 +0000:%d:2071234:90:0123456789abcdef0123456789abcdef:sig:raynman:%d", version, built)
	writeHostFile(t, root, name, header+strings.Repeat(" ", cvdHeaderBytes-len(header))+"\x1f\x8bbody")
}

func TestClamavDBReadsTheNewerDailyDatabase(t *testing.T) {
	root := mailRoot(t)
	stubNow(t, time.Unix(1_795_000_000, 0))
	cvdFile(t, root, "var/lib/clamav/daily.cvd", 27810, 1_794_000_000)
	cvdFile(t, root, "var/lib/clamav/daily.cld", 27830, 1_794_996_400)
	got, err := clamavDB(context.Background(), Target{Kind: kindUnit, Name: "clamav-daemon.service"})
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]any{"version": 27830, "age_s": int64(3600)}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

func TestClamavDBRefusesWhatIsNoDatabase(t *testing.T) {
	root := mailRoot(t)
	if _, err := clamavDB(context.Background(), Target{Kind: kindUnit, Name: "clamav-daemon.service"}); !errors.Is(err, ErrUnsupported) {
		t.Fatalf("no database = %v, want unsupported", err)
	}
	for _, content := range []string{
		"ClamAV-VDB:short",
		strings.Repeat("x", cvdHeaderBytes),
		"ClamAV-VDB:13 Nov 2026:many:1:90:md5:sig:raynman:1794996400" + strings.Repeat(" ", 460),
		"ClamAV-VDB:13 Nov 2026:27830:1:90:md5:sig:raynman:never" + strings.Repeat(" ", 460),
	} {
		writeHostFile(t, root, "var/lib/clamav/daily.cvd", content)
		if _, err := clamavDB(context.Background(), Target{Kind: kindUnit, Name: "clamav-daemon.service"}); err == nil || errors.Is(err, ErrUnsupported) {
			t.Errorf("header %.40q = %v, want an error", content, err)
		}
	}
	if err := os.Remove(filepath.Join(root, "var/lib/clamav/daily.cvd")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("/etc/shadow", filepath.Join(root, "var/lib/clamav/daily.cld")); err != nil {
		t.Fatal(err)
	}
	if _, err := clamavDB(context.Background(), Target{Kind: kindUnit, Name: "clamav-daemon.service"}); err == nil || errors.Is(err, ErrUnsupported) {
		t.Fatalf("a link = %v, want an error", err)
	}
}
