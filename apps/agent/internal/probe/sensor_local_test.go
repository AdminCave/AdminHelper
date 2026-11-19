// SPDX-FileCopyrightText: 2026 Kevin Stenzel
//
// SPDX-License-Identifier: GPL-3.0-or-later

package probe

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io/fs"
	"math/big"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"testing"
	"time"

	"adminhelper-agent/internal/allowlist"
)

const containerID = "4f2a9c1e7b3d5a6f8e0c2b4d6a8f0e1c3b5d7a9f1e3c5b7d9f1a3c5e7b9d1f3a"

// inspectJSON is what `docker inspect` prints for a container web of state, health ("" for none) and
// network mode.
func inspectJSON(t *testing.T, state, health, mode string) string {
	t.Helper()
	h := ""
	if health != "" {
		h = fmt.Sprintf(`,"Health":{"Status":%q,"FailingStreak":0,"Log":[]}`, health)
	}
	return fmt.Sprintf(`[{"Id":%q,"Name":"/web","RestartCount":3,
 "State":{"Status":%q,"Running":%t,"Pid":4242,"ExitCode":0,"StartedAt":"2025-11-09T14:40:00.123456789Z"%s},
 "HostConfig":{"NetworkMode":%q},
 "NetworkSettings":{"Networks":{"front":{"IPAddress":"192.0.2.6","GlobalIPv6Address":""},
  "bridge":{"IPAddress":"192.0.2.5","GlobalIPv6Address":"2001:db8::5"},"empty":{"IPAddress":"","GlobalIPv6Address":""}}}}]`,
		containerID, state, state == "running", h, mode)
}

// tool is a call of runTool a test answers.
type tool struct {
	out  string
	err  error
	args []string
}

// stubTool puts in a runTool that answers every call with out and err and records its arguments.
func stubTool(t *testing.T, out string, err error) *tool {
	t.Helper()
	tl := &tool{out: out, err: err}
	old := runTool
	runTool = func(_ context.Context, _ time.Duration, name string, args ...string) ([]byte, error) {
		tl.args = append([]string{name}, args...)
		checkAllowed(t, name, args)
		return []byte(tl.out), tl.err
	}
	t.Cleanup(func() { runTool = old })
	return tl
}

// stubNow sets the clock of the sensors to at.
func stubNow(t *testing.T, at time.Time) {
	t.Helper()
	old := now
	now = func() time.Time { return at }
	t.Cleanup(func() { now = old })
}

func TestTheLocalSensorsAreRegistered(t *testing.T) {
	for _, name := range []string{"unit", "process", "socket", "container", "certfile", "file_age"} {
		if sensors[name] == nil {
			t.Errorf("sensor %s is not registered", name)
		}
	}
}

func TestProcessSensorCountsTheProcessesOfAName(t *testing.T) {
	stubNow(t, start)
	var asked string
	procs := []proc{
		{rss: 100 << 20, started: start.Add(-90 * time.Second)},
		{rss: 20 << 20, started: start.Add(-3600 * time.Second)},
	}
	old := findProcesses
	findProcesses = func(_ context.Context, name string) ([]proc, error) {
		asked = name
		return procs, nil
	}
	t.Cleanup(func() { findProcesses = old })
	p := Probe{Sensor: "process", Target: &Target{Kind: kindProcess, Name: "php-fpm"}}

	got, err := processSensor(context.Background(), p, "")
	want := map[string]any{"count": 2, "rss_bytes": uint64(120 << 20), "uptime_s": int64(3600)}
	if err != nil || fmt.Sprint(got) != fmt.Sprint(want) || asked != "php-fpm" {
		t.Fatalf("process sensor = %v, %v (asked %q); want %v", got, err, asked, want)
	}

	procs = nil
	got, err = processSensor(context.Background(), p, "")
	if err != nil || len(got) != 1 || got["count"] != 0 {
		t.Errorf("no process = %v, %v; want a count of 0 alone", got, err)
	}

	findProcesses = func(context.Context, string) ([]proc, error) { return nil, errors.New("no /proc") }
	if _, err := processSensor(context.Background(), p, ""); err == nil {
		t.Error("an unreadable process table is no error")
	}
	p.Params = map[string]any{"user": "www"}
	if _, err := processSensor(context.Background(), p, ""); !errors.Is(err, ErrInvalid) {
		t.Errorf("params = %v, want ErrInvalid", err)
	}
}

func TestProcessesNamedFindsThisProcess(t *testing.T) {
	ctx := context.Background()
	name, err := nameOf(ctx, int32(os.Getpid()))
	if err != nil {
		t.Fatal(err)
	}
	procs, err := processesNamed(ctx, strings.ToUpper(name))
	if err != nil || len(procs) == 0 {
		t.Fatalf("processesNamed(%s) = %v, %v; want this process at least", name, procs, err)
	}
	for _, p := range procs {
		if p.rss == 0 || p.started.IsZero() || p.started.After(time.Now()) {
			t.Errorf("process %+v, want its memory and start", p)
		}
	}
	if procs, err := processesNamed(ctx, "no-such-process-of-adminhelper"); err != nil || len(procs) != 0 {
		t.Errorf("processesNamed(unknown) = %v, %v; want none", procs, err)
	}
}

func TestNamedAsTellsAMulticallBinaryByItsApplet(t *testing.T) {
	oldName, oldArgs := processName, processArgs
	t.Cleanup(func() { processName, processArgs = oldName, oldArgs })
	names := map[int32]string{1: "busybox", 2: "busybox", 3: "toybox"}
	args := map[int32][]string{1: {"/bin/busybox", "crond", "-f"}, 3: {"toybox"}}
	processName = func(_ context.Context, pid int32) (string, error) { return names[pid], nil }
	processArgs = func(_ context.Context, pid int32) ([]string, error) {
		if a, ok := args[pid]; ok {
			return a, nil
		}
		return nil, errors.New("access is denied")
	}
	ctx := context.Background()
	for _, c := range []struct {
		pid        int32
		name, want string
		named      bool
	}{
		{1, "busybox", "crond", true},
		{1, "busybox", "busybox", false},
		{2, "busybox", "crond", false}, // its argv cannot be read
		{3, "toybox", "toybox", false}, // no applet named
		{9, "CronD", "crond", true},
		{9, "crond", "httpd", false},
	} {
		if got := namedAs(ctx, c.pid, c.name, c.want); got != c.named {
			t.Errorf("namedAs(%d, %s, %s) = %v, want %v", c.pid, c.name, c.want, got, c.named)
		}
	}
}

func TestContainerSensorReadsStateHealthAndRestarts(t *testing.T) {
	ctx := context.Background()
	p := Probe{Sensor: "container", Target: &Target{Kind: kindContainer, Name: "web"}}

	tl := stubTool(t, inspectJSON(t, "running", "unhealthy", "bridge"), nil)
	got, err := containerSensor(ctx, p, "")
	want := map[string]any{"state": "running", "health": "unhealthy", "restarts": 3, "started_at": int64(1762699200)}
	if err != nil || fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("container = %v, %v; want %v", got, err, want)
	}
	if want := []string{"docker", "inspect", "--type", "container", "--", "web"}; !slices.Equal(tl.args, want) {
		t.Errorf("runTool %v, want %v", tl.args, want)
	}

	tl.out = inspectJSON(t, "exited", "", "bridge")
	got, err = containerSensor(ctx, p, "")
	want = map[string]any{"state": "exited", "health": "none", "restarts": 3}
	if err != nil || fmt.Sprint(got) != fmt.Sprint(want) {
		t.Errorf("an exited container without healthcheck = %v, %v; want %v", got, err, want)
	}

	tl.out, tl.err = "[]\n", &exec.ExitError{}
	if _, err := containerSensor(ctx, p, ""); err == nil || err.Error() != "no container web on this host" {
		t.Errorf("no container = %v", err)
	}
	tl.out, tl.err = "", &exec.ExitError{}
	if _, err := containerSensor(ctx, p, ""); err == nil || strings.Contains(err.Error(), "no container") {
		t.Errorf("docker failing = %v, want its error", err)
	}
	tl.out, tl.err = "", &exec.Error{Name: "docker", Err: exec.ErrNotFound}
	if _, err := containerSensor(ctx, p, ""); !errors.Is(err, ErrUnsupported) {
		t.Errorf("no docker = %v, want ErrUnsupported", err)
	}
	for _, out := range []string{`{"Id":"x"}`, `[{"Id":"x"},{"Id":"y"}]`} {
		tl.out, tl.err = out, nil
		if _, err := containerSensor(ctx, p, ""); err == nil || !strings.Contains(err.Error(), "another form") {
			t.Errorf("an answer of another form %s = %v", out, err)
		}
	}
	tl.out, tl.err = "", context.DeadlineExceeded
	if _, err := containerSensor(ctx, p, ""); !errors.Is(err, context.DeadlineExceeded) {
		t.Errorf("a timeout = %v, want the deadline", err)
	}
}

// writeCert writes a PEM file of a leaf certificate signed by a CA, valid until notAfter, after a
// block of another type.
func writeCert(t *testing.T, notAfter time.Time) string {
	t.Helper()
	key := func() *ecdsa.PrivateKey {
		k, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
		if err != nil {
			t.Fatal(err)
		}
		return k
	}
	caKey, leafKey := key(), key()
	ca := &x509.Certificate{
		SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "Test CA", Organization: []string{"AdminHelper"}},
		NotBefore: start.Add(-time.Hour), NotAfter: start.Add(365 * 24 * time.Hour),
		IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign,
	}
	leaf := &x509.Certificate{
		SerialNumber: big.NewInt(2), Subject: pkix.Name{CommonName: "mail.example.org"},
		NotBefore: start.Add(-time.Hour), NotAfter: notAfter,
	}
	der, err := x509.CreateCertificate(rand.Reader, leaf, ca, &leafKey.PublicKey, caKey)
	if err != nil {
		t.Fatal(err)
	}
	data := pem.EncodeToMemory(&pem.Block{Type: "EC PARAMETERS", Bytes: []byte{6, 8, 42, 134, 72, 206, 61, 3, 1, 7}})
	data = append(data, pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})...)
	path := filepath.Join(t.TempDir(), "cert.pem")
	if err := os.WriteFile(path, data, 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

// slashPath returns path as the monitoring service names it: from the root, with slashes. On Windows
// that root is the one of the current drive, so the test moves there.
func slashPath(t *testing.T, path string) string {
	t.Helper()
	vol := filepath.VolumeName(path)
	if vol != "" {
		t.Chdir(vol + string(filepath.Separator))
	}
	return filepath.ToSlash(path[len(vol):])
}

func certfile(t *testing.T, path string) Probe {
	t.Helper()
	return Probe{Sensor: "certfile", Params: map[string]any{"path": slashPath(t, path)}}
}

func TestCertfileSensorReadsTheFirstCertificate(t *testing.T) {
	stubNow(t, start)
	ctx := context.Background()
	cases := []struct {
		name     string
		notAfter time.Time
		days     int64
	}{
		{"ten days", start.Add(10*24*time.Hour + time.Minute), 10},
		{"a minute short of ten days", start.Add(10*24*time.Hour - time.Minute), 9},
		{"expired an hour ago", start.Add(-time.Hour), -1},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, err := certfileSensor(ctx, certfile(t, writeCert(t, c.notAfter)), "")
			want := map[string]any{
				"not_after": c.notAfter.Unix(), "days_left": c.days,
				"issuer": "CN=Test CA,O=AdminHelper", "subject": "CN=mail.example.org",
			}
			if err != nil || fmt.Sprint(got) != fmt.Sprint(want) {
				t.Fatalf("certfile = %v, %v; want %v", got, err, want)
			}
		})
	}
}

func TestCertfileSensorNeverTellsWhatTheFileHolds(t *testing.T) {
	ctx := context.Background()
	dir := t.TempDir()
	write := func(name string, data []byte) string {
		path := filepath.Join(dir, name)
		if err := os.WriteFile(path, data, 0o600); err != nil {
			t.Fatal(err)
		}
		return path
	}
	const secret = "s3cr3t-pa55word"
	badDER := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: []byte(secret)})
	cases := map[string]struct {
		path string
		want string
	}{
		"no PEM":           {write("plain", []byte(secret+"\n")), "holds no PEM certificate"},
		"no certificate":   {write("key", pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: []byte(secret)})), "holds no PEM certificate"},
		"a broken one":     {write("bad", badDER), "cannot be parsed"},
		"a directory":      {dir, "is no regular file"},
		"a file too large": {write("big", make([]byte, maxCertFileBytes+1)), "is larger than"},
		"no file":          {filepath.Join(dir, "missing"), "missing"},
	}
	for name, c := range cases {
		t.Run(name, func(t *testing.T) {
			_, err := certfileSensor(ctx, certfile(t, c.path), "")
			if err == nil || !strings.Contains(err.Error(), c.want) || strings.Contains(err.Error(), secret) {
				t.Fatalf("certfile = %v, want an error with %q and nothing of the file", err, c.want)
			}
		})
	}
	data, err := readSmallFile(write("max", make([]byte, 10)), 10)
	if err != nil || len(data) != 10 {
		t.Errorf("readSmallFile at the limit = %d bytes, %v", len(data), err)
	}
}

func TestFileAgeSensorReadsAgeAndSizeOnly(t *testing.T) {
	stubNow(t, start)
	ctx := context.Background()
	path := filepath.Join(t.TempDir(), "backup.tar")
	if err := os.WriteFile(path, []byte("12345"), 0o600); err != nil {
		t.Fatal(err)
	}
	p := Probe{Sensor: "file_age", Params: map[string]any{"path": slashPath(t, path)}}
	for _, c := range []struct {
		mtime time.Time
		age   int64
	}{{start.Add(-90 * time.Second), 90}, {start.Add(time.Minute), -60}} {
		if err := os.Chtimes(path, c.mtime, c.mtime); err != nil {
			t.Fatal(err)
		}
		got, err := fileAgeSensor(ctx, p, "")
		want := map[string]any{"exists": true, "age_s": c.age, "size_bytes": int64(5)}
		if err != nil || fmt.Sprint(got) != fmt.Sprint(want) {
			t.Errorf("file_age = %v, %v; want %v", got, err, want)
		}
	}

	p.Params["path"] = slashPath(t, path) + ".gone"
	got, err := fileAgeSensor(ctx, p, "")
	if err != nil || len(got) != 1 || got["exists"] != false {
		t.Errorf("a missing file = %v, %v; want exists false alone", got, err)
	}
}

func TestFileAgeNewestInReadsTheNewestRegularFileOfADirectory(t *testing.T) {
	stubNow(t, start)
	ctx := context.Background()
	dir := t.TempDir()
	write := func(name, data string, mtime time.Time) {
		t.Helper()
		path := filepath.Join(dir, name)
		if err := os.WriteFile(path, []byte(data), 0o600); err != nil {
			t.Fatal(err)
		}
		if err := os.Chtimes(path, mtime, mtime); err != nil {
			t.Fatal(err)
		}
	}
	p := Probe{Sensor: "file_age", Params: map[string]any{"newest_in": slashPath(t, dir)}}

	got, err := fileAgeSensor(ctx, p, "")
	if err != nil || len(got) != 1 || got["exists"] != false {
		t.Errorf("an empty directory = %v, %v; want exists false alone", got, err)
	}

	write("old.tar", "1", start.Add(-time.Hour))
	write("new.tar", "123", start.Add(-90*time.Second))
	// Neither a directory nor anything below it counts, however new.
	sub := filepath.Join(dir, "sub")
	if err := os.Mkdir(sub, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(sub, "newer.tar"), []byte("12345"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(sub, start, start); err != nil {
		t.Fatal(err)
	}
	// A link is not followed, though it points at a newer file outside.
	outside := filepath.Join(t.TempDir(), "outside")
	if err := os.WriteFile(outside, []byte("1234567"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(outside, start, start); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(dir, "link")); err != nil && runtime.GOOS != "windows" {
		t.Fatal(err)
	}

	got, err = fileAgeSensor(ctx, p, "")
	want := map[string]any{"exists": true, "age_s": int64(90), "size_bytes": int64(3)}
	if err != nil || fmt.Sprint(got) != fmt.Sprint(want) {
		t.Errorf("newest_in = %v, %v; want %v", got, err, want)
	}

	p.Params["newest_in"] = slashPath(t, dir) + "/gone"
	if got, err := fileAgeSensor(ctx, p, ""); err != nil || len(got) != 1 || got["exists"] != false {
		t.Errorf("a missing directory = %v, %v; want exists false alone", got, err)
	}
	p.Params["newest_in"] = slashPath(t, dir) + "/new.tar"
	if _, err := fileAgeSensor(ctx, p, ""); !errors.Is(err, errNotDir) {
		t.Errorf("newest_in on a file = %v, want no directory", err)
	}
}

func TestFileAgeNewestInRefusesADirectoryOfTooManyEntries(t *testing.T) {
	dir := t.TempDir()
	for i := range maxDirEntries + 1 {
		f, err := os.Create(filepath.Join(dir, strconv.Itoa(i)))
		if err != nil {
			t.Fatal(err)
		}
		_ = f.Close()
	}
	p := Probe{Sensor: "file_age", Params: map[string]any{"newest_in": slashPath(t, dir)}}
	if _, err := fileAgeSensor(context.Background(), p, ""); err == nil || !strings.Contains(err.Error(), "more than 10000 entries") {
		t.Errorf("a directory of %d entries = %v, want it refused", maxDirEntries+1, err)
	}
	if err := os.Remove(filepath.Join(dir, "0")); err != nil {
		t.Fatal(err)
	}
	if got, err := fileAgeSensor(context.Background(), p, ""); err != nil || got["exists"] != true {
		t.Errorf("a directory of %d entries = %v, %v; want the newest", maxDirEntries, got, err)
	}
}

func TestFileAgeTakesEitherPathOrNewestIn(t *testing.T) {
	for name, params := range map[string]map[string]any{
		"both":                 {"path": "/var/backups/a.tar", "newest_in": "/var/backups"},
		"a relative newest_in": {"newest_in": "var/backups"},
		"newest_in not a path": {"newest_in": 3},
	} {
		p := Probe{ID: "f1", Sensor: "file_age", TimeoutS: 5, Params: params}
		if res := Run(context.Background(), p, start, nil); res.Status != StatusInvalid {
			t.Errorf("file_age with %s = %+v, want invalid", name, res)
		}
	}
}

func TestTheFileSensorsEndWithTheirContext(t *testing.T) {
	entered := make(chan struct{}, 2)
	release := make(chan struct{})
	old, oldOpen := statPath, openFile
	statPath = func(string) (fs.FileInfo, error) {
		entered <- struct{}{}
		<-release
		return nil, fs.ErrNotExist
	}
	openFile = func(string) (*os.File, error) {
		entered <- struct{}{}
		<-release
		return nil, fs.ErrNotExist
	}
	t.Cleanup(func() {
		close(release)
		statPath, openFile = old, oldOpen
	})
	for _, sensor := range []string{"certfile", "file_age"} {
		p := Probe{Sensor: sensor, Params: map[string]any{"path": "/mnt/gone/x"}}
		ctx, cancel := context.WithCancel(context.Background())
		done := make(chan error, 1)
		go func() {
			_, err := sensors[sensor](ctx, p, "")
			done <- err
		}()
		select {
		case <-entered:
		case <-time.After(5 * time.Second):
			t.Fatalf("%s never reads the file", sensor)
		}
		cancel()
		select {
		case err := <-done:
			if !errors.Is(err, context.Canceled) {
				t.Errorf("%s on a hanging file system = %v, want the end of its context", sensor, err)
			}
		case <-time.After(5 * time.Second):
			t.Fatalf("%s waits for a hanging file system beyond its context", sensor)
		}
	}
}

func TestTheFileSensorsTakeAPathAndNoTarget(t *testing.T) {
	for _, sensor := range []string{"certfile", "file_age"} {
		for name, p := range map[string]Probe{
			"a target":        {Target: &Target{Kind: kindLoopback, PortHint: 80}, Params: map[string]any{"path": "/etc/hosts"}},
			"a relative path": {Params: map[string]any{"path": "etc/hosts"}},
			"no path":         {},
		} {
			p.ID, p.Sensor, p.TimeoutS = "f1", sensor, 5
			if res := Run(context.Background(), p, start, nil); res.Status != StatusInvalid {
				t.Errorf("%s with %s = %+v, want invalid", sensor, name, res)
			}
		}
	}
}

func TestUnitAndContainerSensorsTakeNoParams(t *testing.T) {
	ctx := context.Background()
	tl := stubTool(t, "", errors.New("must not run"))
	for _, p := range []Probe{
		{Sensor: "unit", Target: &Target{Kind: kindUnit, Name: "nginx.service"}, Params: map[string]any{"x": 1}},
		{Sensor: "container", Target: &Target{Kind: kindContainer, Name: "web"}, Params: map[string]any{"x": 1}},
		{Sensor: "unit", Target: &Target{Kind: kindContainer, Name: "web"}},
		{Sensor: "container", Target: &Target{Kind: kindUnit, Name: "web"}},
	} {
		if _, err := sensors[p.Sensor](ctx, p, ""); !errors.Is(err, ErrInvalid) {
			t.Errorf("%s %+v = %v, want ErrInvalid", p.Sensor, p.Target, err)
		}
	}
	if tl.args != nil {
		t.Errorf("an invalid probe ran %v", tl.args)
	}
}

// checkAllowed fails the test if the call a stub of runTool got is not on the command allowlist, which
// the real runTool would refuse.
func checkAllowed(t *testing.T, name string, args []string) {
	t.Helper()
	if !allowlist.Allowed(name, args) {
		t.Errorf("call %q is not on the command allowlist", append([]string{name}, args...))
	}
}

// mountsJSON is what `docker inspect` prints for a running container web with mounts, each a type,
// a source and a destination.
func mountsJSON(t *testing.T, mounts ...[3]string) string {
	t.Helper()
	type mount struct{ Type, Source, Destination, Mode, Propagation string }
	list := []mount{}
	for _, m := range mounts {
		list = append(list, mount{m[0], m[1], m[2], "", "rprivate"})
	}
	data, err := json.Marshal(list)
	if err != nil {
		t.Fatal(err)
	}
	return fmt.Sprintf(`[{"Id":%q,"Name":"/web","State":{"Status":"running","Running":true,"Pid":4242},"Mounts":%s}]`, containerID, data)
}

func TestHostPathTakesTheLongestBindOrVolumeMount(t *testing.T) {
	var list []containerInfo
	out := mountsJSON(t,
		[3]string{"bind", "/srv/web", "/data"},
		[3]string{"volume", "/var/lib/docker/volumes/db/_data", "/data/db/"},
		[3]string{"bind", "/srv/x", "/datax"},
		[3]string{"tmpfs", "", "/tmp"},
		[3]string{"volume", "", "/cloud"},
		[3]string{"image", "/var/lib/docker/image", "/img"},
	)
	if err := json.Unmarshal([]byte(out), &list); err != nil || len(list) != 1 {
		t.Fatalf("inspect = %v, %v", list, err)
	}
	for path, want := range map[string][2]string{
		"/data/f":      {"/srv/web", "f"},
		"/data/sub/f":  {"/srv/web", "sub/f"},
		"/data":        {"/srv/web", "."},
		"/data/db":     {"/var/lib/docker/volumes/db/_data", "."},
		"/data/db/x/y": {"/var/lib/docker/volumes/db/_data", "x/y"},
		"/datax/f":     {"/srv/x", "f"},
	} {
		source, rel, ok := list[0].hostPath(path)
		if !ok || source != want[0] || rel != want[1] {
			t.Errorf("hostPath(%s) = %s, %s, %t; want %s, %s", path, source, rel, ok, want[0], want[1])
		}
	}
	for _, path := range []string{"/dat", "/etc/hosts", "/tmp/f", "/cloud/f", "/img/f", "/"} {
		if source, rel, ok := list[0].hostPath(path); ok {
			t.Errorf("hostPath(%s) = %s, %s; want no mount", path, source, rel)
		}
	}
}

// containerProbe is a probe of sensor on a path in the container web.
func containerProbe(sensor, key, path string) Probe {
	return Probe{Sensor: sensor, Target: &Target{Kind: kindContainer, Name: "web"}, Params: map[string]any{key: path}}
}

func TestCertfileReadsAPathInsideAContainer(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("docker names the sources of its mounts on Linux")
	}
	stubNow(t, start)
	ctx := context.Background()
	notAfter := start.Add(10*24*time.Hour + time.Minute)
	src := filepath.Dir(writeCert(t, notAfter))
	outside := writeCert(t, notAfter)
	if err := os.Symlink(outside, filepath.Join(src, "abs.pem")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("../../"+filepath.Base(filepath.Dir(outside))+"/cert.pem", filepath.Join(src, "rel.pem")); err != nil {
		t.Fatal(err)
	}
	// certbot's form: live/<name>/cert.pem links to archive/<name>/cert1.pem.
	for _, dir := range []string{"live/web", "archive/web"} {
		if err := os.MkdirAll(filepath.Join(src, dir), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Rename(filepath.Join(src, "cert.pem"), filepath.Join(src, "archive/web/cert1.pem")); err != nil {
		t.Fatal(err)
	}
	for link, to := range map[string]string{"live/web/cert.pem": "../../archive/web/cert1.pem", "cert.pem": "live/web/cert.pem"} {
		if err := os.Symlink(to, filepath.Join(src, link)); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Symlink("loop.pem", filepath.Join(src, "loop.pem")); err != nil {
		t.Fatal(err)
	}
	tl := stubTool(t, mountsJSON(t, [3]string{"bind", src, "/etc/certs"}), nil)

	got, err := certfileSensor(ctx, containerProbe("certfile", "path", "/etc/certs/cert.pem"), "")
	if runtime.GOOS != "linux" {
		if !errors.Is(err, ErrUnsupported) {
			t.Fatalf("certfile in a container off Linux = %v, %v; want ErrUnsupported", got, err)
		}
		return
	}
	want := map[string]any{
		"not_after": notAfter.Unix(), "days_left": int64(10),
		"issuer": "CN=Test CA,O=AdminHelper", "subject": "CN=mail.example.org",
	}
	if err != nil || fmt.Sprint(got) != fmt.Sprint(want) {
		t.Fatalf("certfile in a container = %v, %v; want %v", got, err, want)
	}
	if want := []string{"docker", "inspect", "--type", "container", "--", "web"}; !slices.Equal(tl.args, want) {
		t.Errorf("runTool %v, want %v", tl.args, want)
	}
	// A relative link is followed within the mount alone, an absolute one not at all.
	for _, name := range []string{"abs.pem", "rel.pem", "loop.pem"} {
		_, err := certfileSensor(ctx, containerProbe("certfile", "path", "/etc/certs/"+name), "")
		if err == nil || strings.Contains(err.Error(), src) || strings.Contains(err.Error(), outside) {
			t.Errorf("certfile on the link %s = %v, want an error without a host path", name, err)
		}
	}
	_, err = certfileSensor(ctx, containerProbe("certfile", "path", "/etc/ssl/cert.pem"), "")
	if !errors.Is(err, ErrInvalid) || strings.Contains(err.Error(), "/etc") {
		t.Errorf("certfile on no mount = %v, want invalid without the path", err)
	}
	_, err = certfileSensor(ctx, containerProbe("certfile", "path", "/etc/certs/gone.pem"), "")
	if err == nil || strings.Contains(err.Error(), src) || !strings.Contains(err.Error(), "/etc/certs/gone.pem") {
		t.Errorf("certfile on a missing file = %v, want an error naming the container path alone", err)
	}
}

func TestFileAgeReadsAPathInsideAContainer(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("docker names the sources of its mounts on Linux")
	}
	stubNow(t, start)
	ctx := context.Background()
	src := t.TempDir()
	write := func(dir, name, data string, mtime time.Time) {
		t.Helper()
		path := filepath.Join(dir, name)
		if err := os.WriteFile(path, []byte(data), 0o600); err != nil {
			t.Fatal(err)
		}
		if err := os.Chtimes(path, mtime, mtime); err != nil {
			t.Fatal(err)
		}
	}
	write(src, "old.tar", "1", start.Add(-time.Hour))
	write(src, "new.tar", "123", start.Add(-90*time.Second))
	outside := t.TempDir()
	write(outside, "newer.tar", "1234567", start)
	if err := os.Symlink(outside, filepath.Join(src, "out")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(outside, "newer.tar"), filepath.Join(src, "link.tar")); err != nil {
		t.Fatal(err)
	}
	stubTool(t, mountsJSON(t, [3]string{"volume", src, "/backups"}), nil)

	cases := []struct {
		key, path string
		want      map[string]any
	}{
		{"path", "/backups/new.tar", map[string]any{"exists": true, "age_s": int64(90), "size_bytes": int64(3)}},
		{"path", "/backups/gone.tar", map[string]any{"exists": false}},
		// The link in the directory is not followed, though it points at a newer file outside.
		{"newest_in", "/backups", map[string]any{"exists": true, "age_s": int64(90), "size_bytes": int64(3)}},
		{"newest_in", "/backups/gone", map[string]any{"exists": false}},
	}
	for _, c := range cases {
		got, err := fileAgeSensor(ctx, containerProbe("file_age", c.key, c.path), "")
		if err != nil || fmt.Sprint(got) != fmt.Sprint(c.want) {
			t.Errorf("file_age %s %s = %v, %v; want %v", c.key, c.path, got, err, c.want)
		}
	}
	// A link out of the mount is followed nowhere: neither the file nor the directory outside is read.
	for _, c := range [][2]string{{"path", "/backups/link.tar"}, {"newest_in", "/backups/out"}, {"path", "/backups/out/newer.tar"}} {
		got, err := fileAgeSensor(ctx, containerProbe("file_age", c[0], c[1]), "")
		if err == nil || strings.Contains(err.Error(), src) || strings.Contains(err.Error(), outside) {
			t.Errorf("file_age %s %s through a link out of the mount = %v, %v; want an error without a host path", c[0], c[1], got, err)
		}
	}
	if _, err := fileAgeSensor(ctx, containerProbe("file_age", "newest_in", "/backups/new.tar"), ""); !errors.Is(err, errNotDir) {
		t.Errorf("newest_in on a file in a container = %v, want no directory", err)
	}
	_, err := fileAgeSensor(ctx, containerProbe("file_age", "path", "/var/backups/a.tar"), "")
	if !errors.Is(err, ErrInvalid) || strings.Contains(err.Error(), "/var") {
		t.Errorf("file_age on no mount = %v, want invalid without the path", err)
	}
}

// A bind of a single file, a certificate handed to the container: the mount point is the file itself.
func TestTheFileSensorsReadABindOfASingleFile(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("docker names the sources of its mounts on Linux")
	}
	stubNow(t, start)
	ctx := context.Background()
	notAfter := start.Add(10*24*time.Hour + time.Minute)
	file := writeCert(t, notAfter)
	stubTool(t, mountsJSON(t, [3]string{"bind", file, "/etc/nginx/cert.pem"}), nil)
	got, err := fileAgeSensor(ctx, containerProbe("file_age", "path", "/etc/nginx/cert.pem"), "")
	if err != nil || got["exists"] != true {
		t.Errorf("file_age on a bind of a file = %v, %v; want it read", got, err)
	}
	if _, err := fsSensor(ctx, containerProbe("fs", "path", "/etc/nginx/cert.pem"), ""); !errors.Is(err, errNotDir) {
		t.Errorf("fs on a bind of a file = %v, want no directory", err)
	}
	got, err = certfileSensor(ctx, containerProbe("certfile", "path", "/etc/nginx/cert.pem"), "")
	if runtime.GOOS == "linux" && (err != nil || got["days_left"] != int64(10)) {
		t.Errorf("certfile on a bind of a file = %v, %v; want it read", got, err)
	}
	// docker inspect names a source as given, a link among them, and docker mounted what it resolves to.
	links := t.TempDir()
	if err := os.Symlink(file, filepath.Join(links, "cert.pem")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Dir(file), filepath.Join(links, "data")); err != nil {
		t.Fatal(err)
	}
	stubTool(t, mountsJSON(t, [3]string{"bind", filepath.Join(links, "cert.pem"), "/etc/nginx/cert.pem"}), nil)
	got, err = fileAgeSensor(ctx, containerProbe("file_age", "path", "/etc/nginx/cert.pem"), "")
	if err != nil || got["exists"] != true {
		t.Errorf("file_age on a bind of a link to a file = %v, %v; want it read", got, err)
	}
	stubTool(t, mountsJSON(t, [3]string{"bind", filepath.Join(links, "data"), "/data"}), nil)
	got, err = fsSensor(ctx, containerProbe("fs", "path", "/data"), "")
	if _, ok := got["used_pct"]; err != nil || !ok {
		t.Errorf("fs on a bind of a link to a directory = %v, %v; want it read", got, err)
	}
	got, err = fileAgeSensor(ctx, containerProbe("file_age", "newest_in", "/data"), "")
	if err != nil || got["exists"] != true {
		t.Errorf("newest_in on a bind of a link to a directory = %v, %v; want it read", got, err)
	}
}

func TestTheFileSensorsTakeOnlyAValidContainerTarget(t *testing.T) {
	ctx := context.Background()
	tl := stubTool(t, "", errors.New("must not run"))
	for _, sensor := range []string{"certfile", "file_age", "fs"} {
		for name, p := range map[string]Probe{
			"a unit":            {Target: &Target{Kind: kindUnit, Name: "web.service"}, Params: map[string]any{"path": "/data"}},
			"a bad name":        {Target: &Target{Kind: kindContainer, Name: "-web"}, Params: map[string]any{"path": "/data"}},
			"a relative path":   {Target: &Target{Kind: kindContainer, Name: "web"}, Params: map[string]any{"path": "data"}},
			"a path with ..":    {Target: &Target{Kind: kindContainer, Name: "web"}, Params: map[string]any{"path": "/data/../etc"}},
			"no path":           {Target: &Target{Kind: kindContainer, Name: "web"}},
			"another parameter": {Target: &Target{Kind: kindContainer, Name: "web"}, Params: map[string]any{"path": "/data", "x": 1}},
		} {
			p.Sensor = sensor
			if _, err := sensors[sensor](ctx, p, ""); !errors.Is(err, ErrInvalid) {
				t.Errorf("%s with %s = %v, want ErrInvalid", sensor, name, err)
			}
		}
	}
	if tl.args != nil {
		t.Errorf("an invalid probe ran %v", tl.args)
	}
}
